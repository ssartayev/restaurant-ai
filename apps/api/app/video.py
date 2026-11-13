"""Analyze a fixed-camera recording and return a timeline in video seconds."""
from collections import deque
from functools import lru_cache
from pathlib import Path
from statistics import median_low
from tempfile import TemporaryDirectory
import os

import cv2
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from .main import app as management

from .pose import Pose
from .table_activity import activity
from worker.detector import OnnxYoloxDetector
from worker.zones import anchor_point
from worker.tableware import TABLEWARE_CLASSES, counts_by_surface

ROOT = Path(__file__).resolve().parents[3]
app = FastAPI(title="Restaurant Camera", lifespan=management.router.lifespan_context)
PERSON, TABLE = 0, 60  # COCO person and dining table


@lru_cache(maxsize=1)
def detector():
    return OnnxYoloxDetector(os.environ.get("YOLOX_MODEL", str(ROOT / ".models/yolox_s.onnx")),
                            score_thr=0.23)


def overlap(a, b):
    intersection = max(0, min(a.x2, b.x2) - max(a.x1, b.x1)) * max(0, min(a.y2, b.y2) - max(a.y1, b.y1))
    area_a = (a.x2 - a.x1) * (a.y2 - a.y1)
    area_b = (b.x2 - b.x1) * (b.y2 - b.y1)
    union = area_a + area_b - intersection
    if min(area_a, area_b) <= 0:
        return 0
    # Partial occlusion can shrink a detection to a box inside the full table.
    return max(intersection / union, .65 * intersection / min(area_a, area_b))


def analyze(path, pose_model=None):
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise HTTPException(422, "Could not open the recording. Try an H.264 MP4.")
        model = detector()
        fps = capture.get(cv2.CAP_PROP_FPS) or 25
        step = max(1, round(fps))
        samples, candidates, dish_samples, objects = [], [], [], []
        pose = Pose(pose_model or ROOT / ".models/pose_landmarker_lite.task")
        lookup = model.np.array([round(255 * (v / 255) ** .66) for v in range(256)], dtype="uint8")
        index = 0
        while capture.grab():
            if index % step == 0:
                ok, frame = capture.retrieve()
                if not ok:
                    break
                # Improve local contrast only for genuinely dark recordings.
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if gray.mean() < 85:
                    frame = cv2.LUT(frame, lookup)
                detected = model.detect_classes(frame, (PERSON, TABLE, *TABLEWARE_CLASSES))
                dish_samples.append([box for category in TABLEWARE_CLASSES for box in detected[category]])
                frame_objects = []
                def add_object(box, label, kind):
                    frame_objects.append({"box": [box.x1, box.y1, box.x2, box.y2],
                                          "label": label, "kind": kind, "confidence": round(float(box.conf), 3)})
                for box in detected[TABLE]:
                    add_object(box, "Table", "table")
                for category, label in {40: "Glass", 41: "Cup", 42: "Fork", 43: "Knife", 44: "Spoon", 45: "Bowl"}.items():
                    for box in detected[category]:
                        add_object(box, label, "tableware")
                people = []
                for box in detected[PERSON]:
                    if box.conf < .35:
                        continue
                    seated = pose.seated(frame, box, detected[TABLE])
                    add_object(box, "Seated person" if seated is True else "Person", "person")
                    width = (box.x2 - box.x1) * frame.shape[1]
                    height = (box.y2 - box.y1) * frame.shape[0]
                    if seated is True or (seated is None and height <= 1.85 * width):
                        people.append(anchor_point(box, ay=.65))
                samples.append((index / fps, people))
                objects.append((index / fps, frame_objects))
                matched = set()
                for box in detected[TABLE]:
                    match = max(range(len(candidates)), key=lambda i: overlap(box, candidates[i][0]), default=None)
                    if match is not None and overlap(box, candidates[match][0]) >= .32:
                        if match not in matched:
                            prior, count = candidates[match]
                            candidates[match] = (box if box.conf > prior.conf else prior, count + 1)
                            matched.add(match)
                    else:
                        matched.add(len(candidates))
                        candidates.append((box, 1))
            index += 1
        if not samples:
            raise HTTPException(422, "The recording contains no readable frames.")
    finally:
        capture.release()
        if "pose" in locals():
            pose.model.close()

    tables = sorted((box for box, count in candidates if count >= min(2, len(samples))),
                    key=lambda box: (box.y1 + box.y2, box.x1 + box.x2))
    detected_tables = [
        {"id": i + 1, "x": (box.x1 + box.x2) / 2, "y": (box.y1 + box.y2) / 2,
         "box": [box.x1, box.y1, box.x2, box.y2]}
        for i, box in enumerate(tables)
    ]
    timeline = activity(detected_tables, samples)
    recent_items = [deque(maxlen=3) for _ in tables]
    for (_, readings), items in zip(timeline, dish_samples):
        for reading, count, recent in zip(readings, counts_by_surface(tables, items), recent_items):
            recent.append(count)
            reading["tableware_count"] = median_low(recent) if len(recent) >= 2 else 0
    return {"tables": detected_tables, "timeline": timeline, "objects": objects}


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
