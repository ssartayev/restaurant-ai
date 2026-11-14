"""Analyze a fixed-camera recording and return a timeline in video seconds."""
from collections import OrderedDict, deque
from functools import lru_cache
from pathlib import Path
from statistics import median_low
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4
from .roles import RoleEstimator

import os

import cv2
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from .main import app as management

from .pose import Pose
from .table_activity import activity
from .table_discovery import STRONG, WEAK, TableCandidates
from .tracking import Tracker
from pydantic import BaseModel, Field
from worker.detector import OnnxYoloxDetector
from worker.zones import anchor_point
from worker.tableware import TABLEWARE_CLASSES, counts_by_surface

ROOT = Path(__file__).resolve().parents[3]
app = FastAPI(title="Restaurant Camera", lifespan=management.router.lifespan_context)
PERSON, TABLE = 0, 60  # COCO person and dining table


TRACK_FPS = float(os.environ.get("TRACK_FPS", "4"))   # person tracking rate; 1 disables the extra frames
_CACHE: OrderedDict[str, dict] = OrderedDict()         # evidence of recent analyses, for /recompute
_CACHE_SIZE = 4


@lru_cache(maxsize=1)
def detector():
    # Low floor on purpose: table_discovery adds up weak table evidence over time.
    # Every other class is filtered back to its own threshold below.
    return OnnxYoloxDetector(os.environ.get("YOLOX_MODEL", str(ROOT / ".models/yolox_s.onnx")),
                            score_thr=WEAK)


def clothing(frame, box):
    """Clothing-only colour descriptor: central torso, excluding the head. Not an identity."""
    h, w = frame.shape[:2]
    bw, bh = box.x2 - box.x1, box.y2 - box.y1
    crop = frame[int(max(0, box.y1 + .25 * bh) * h):int(min(1, box.y1 + .65 * bh) * h),
                 int(max(0, box.x1 + .2 * bw) * w):int(min(1, box.x2 - .2 * bw) * w)]
    if not crop.size:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 4, 4], [0, 180, 0, 256, 0, 256])
    hist /= max(float(hist.sum()), 1)
    return hist.flatten().tolist()


def build(tables, samples, dish_samples, staff_tracks=()):
    """Occupancy timeline for a set of tables, leaving out people marked as staff.

    tables: [{"id", "box": [x1, y1, x2, y2]}]; samples: [(time, [(x, y, track), ...])].
    Pure function of stored evidence, so it can be re-run after a correction.
    """
    staff = set(staff_tracks)
    tables = [{"id": t["id"], "box": list(t["box"]),
               "x": (t["box"][0] + t["box"][2]) / 2, "y": (t["box"][1] + t["box"][3]) / 2,
               **({"manual": True} if t.get("manual") else {})} for t in tables]
    guests = [(time, [(x, y) for x, y, track in people if track not in staff]) for time, people in samples]
    timeline = activity(tables, guests)
    surfaces = [SimpleNamespace(x1=t["box"][0], y1=t["box"][1], x2=t["box"][2], y2=t["box"][3]) for t in tables]
    recent_items = [deque(maxlen=3) for _ in tables]
    for (_, readings), items in zip(timeline, dish_samples):
        for reading, count, recent in zip(readings, counts_by_surface(surfaces, items), recent_items):
            recent.append(count)
            reading["tableware_count"] = median_low(recent) if len(recent) >= 2 else 0
    return tables, timeline


def analyze(path, pose_model=None):
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise HTTPException(422, "Could not open the recording. Try an H.264 MP4.")
        model = detector()
        fps = capture.get(cv2.CAP_PROP_FPS) or 25
        step = max(1, round(fps))                                  # full analysis: about once a second
        track_step = max(1, min(step, round(fps / max(TRACK_FPS, 1))))  # person tracking: several a second
        samples, dish_samples, objects = [], [], []
        candidates = TableCandidates()
        tracker = Tracker()
        pose = Pose(pose_model or ROOT / ".models/pose_landmarker_lite.task")
        lookup = model.np.array([round(255 * (v / 255) ** .66) for v in range(256)], dtype="uint8")
        roles = RoleEstimator()
        index = 0
        while capture.grab():
            full = index % step == 0
            if full or index % track_step == 0:
                ok, frame = capture.retrieve()
                if not ok:
                    break
                # Improve local contrast only for genuinely dark recordings.
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if gray.mean() < 85:
                    frame = cv2.LUT(frame, lookup)
                detected = model.detect_classes(
                    frame, (PERSON, TABLE, *TABLEWARE_CLASSES) if full else (PERSON,))
                persons = [box for box in detected[PERSON] if box.conf >= .35]
                looks = [clothing(frame, box) for box in persons]
                track_ids = tracker.update(index / fps, [(b.x1, b.y1, b.x2, b.y2) for b in persons], looks)
                if not full:
                    index += 1
                    continue
                strong_tables = [box for box in detected[TABLE] if box.conf >= STRONG]
                tableware = {c: [b for b in detected[c] if b.conf >= STRONG] for c in TABLEWARE_CLASSES}
                dish_samples.append([box for category in TABLEWARE_CLASSES for box in tableware[category]])
                frame_objects = []
                def add_object(box, label, kind):
                    frame_objects.append({"box": [box.x1, box.y1, box.x2, box.y2],
                                          "label": label, "kind": kind, "confidence": round(float(box.conf), 3)})
                for box in strong_tables:
                    add_object(box, "Table", "table")
                for category, label in {40: "Glass", 41: "Cup", 42: "Fork", 43: "Knife", 44: "Spoon", 45: "Bowl"}.items():
                    for box in tableware[category]:
                        add_object(box, label, "tableware")
                people = []
                person_evidence = []
                for box, track in zip(persons, track_ids):
                    seated = pose.seated(frame, box, strong_tables)
                    person_evidence.append((box, seated, pose.service_motion))
                    width = (box.x2 - box.x1) * frame.shape[1]
                    height = (box.y2 - box.y1) * frame.shape[0]
                    if seated is True or (seated is None and height <= 1.85 * width):
                        people.append((*anchor_point(box, ay=.65), track))
                for (box, _, _), (label, reason), track, look in zip(
                        person_evidence, roles.update(index / fps, person_evidence), track_ids, looks):
                    add_object(box, label, "person")
                    frame_objects[-1].update(reason=reason, track=track)
                    if look:
                        frame_objects[-1]["appearance"] = look
                samples.append((index / fps, people))
                objects.append((index / fps, frame_objects))
                candidates.add_frame(detected[TABLE])
            index += 1
        if not samples:
            raise HTTPException(422, "The recording contains no readable frames.")
    finally:
        capture.release()
        if "pose" in locals():
            pose.model.close()

    found = [{"id": i + 1, "box": [box.x1, box.y1, box.x2, box.y2]}
             for i, box in enumerate(candidates.accepted())]
    tables, timeline = build(found, samples, dish_samples)
    analysis_id = uuid4().hex
    _CACHE[analysis_id] = {"samples": samples, "dishes": dish_samples}
    while len(_CACHE) > _CACHE_SIZE:
        _CACHE.popitem(last=False)
    return {"id": analysis_id, "tables": tables, "timeline": timeline, "objects": objects}


class TableIn(BaseModel):
    id: int = Field(ge=1, le=9999)
    box: tuple[float, float, float, float]
    manual: bool = False


class RecomputeIn(BaseModel):
    tables: list[TableIn] = Field(max_length=200)
    staff_tracks: list[int] = Field(default_factory=list, max_length=500)


@app.post("/analyze/{analysis_id}/recompute")
def recompute(analysis_id: str, body: RecomputeIn):
    """Re-run occupancy after a correction: tables added or removed, people marked as staff.

    Uses the evidence kept in memory from the analysis; the video itself is already deleted.
    """
    evidence = _CACHE.get(analysis_id)
    if evidence is None:
        raise HTTPException(404, "This analysis is no longer in memory. Upload the recording again.")
    for table in body.tables:
        x1, y1, x2, y2 = table.box
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            raise HTTPException(422, "Table boxes need 0 <= left < right <= 1 and 0 <= top < bottom <= 1.")
    if len({t.id for t in body.tables}) != len(body.tables):
        raise HTTPException(422, "Table ids must be unique.")
    tables, timeline = build([t.model_dump() for t in body.tables], evidence["samples"],
                             evidence["dishes"], body.staff_tracks)
    return {"id": analysis_id, "tables": tables, "timeline": timeline}


@app.post("/analyze")
def upload(video: UploadFile = File(...)):
    with TemporaryDirectory() as directory:
        path = Path(directory) / "recording.mp4"
        total = 0
        with path.open("wb") as output:
            while chunk := video.file.read(1024 * 1024):
                total += len(chunk)
                if total > 250 * 1024 * 1024:
                    raise HTTPException(413, "Choose a video under 250 MB.")
                output.write(chunk)
        return analyze(path)


app.include_router(management.router, include_in_schema=False)
app.mount("/", StaticFiles(directory=ROOT / "apps/web/dist", html=True))
