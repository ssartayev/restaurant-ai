"""Offline runner: a box trace (or a video file) -> events.jsonl, optionally posted to the API.

  python -m worker.runner --synthetic 1 --out events.jsonl
  python -m worker.runner --trace trace.json --out events.jsonl
  python -m worker.runner --video clip.mp4 --zones zones.json --model yolox_s.onnx --out events.jsonl
"""
import argparse
import json

from .occupancy_filter import FilterConfig
from .pipeline import Pipeline
from .zones import Box, TableZone


def zones_from(raw: list[dict]) -> list[TableZone]:
    return [TableZone(z["table_id"], [[tuple(p) for p in poly] for poly in z["polygons"]],
                      z.get("label", "")) for z in raw]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace")
    ap.add_argument("--synthetic", type=int, help="seed for a synthetic trace")
    ap.add_argument("--video")
    ap.add_argument("--zones")
    ap.add_argument("--model")
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--out", default="events.jsonl")
    ap.add_argument("--save-trace", help="write the detector's boxes here (for labelling and evaluation)")
    args = ap.parse_args()

    if args.synthetic is not None:
        from . import synth
        trace = synth.generate(args.synthetic)
    elif args.trace:
        trace = json.loads(open(args.trace).read())
    elif args.video:
        import cv2

        from .detector import OnnxYoloxDetector
        det = OnnxYoloxDetector(args.model)
        cap = cv2.VideoCapture(args.video)
        native = cap.get(cv2.CAP_PROP_FPS) or 25.0
        every, frames, i = max(1, round(native / args.fps)), [], 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if i % every == 0:
                frames.append({"t": round(i / native, 3),
                               "boxes": [[b.x1, b.y1, b.x2, b.y2, b.conf] for b in det.detect(frame)]})
            i += 1
        trace = {"zones": json.loads(open(args.zones).read()), "frames": frames}
        if args.save_trace:
            open(args.save_trace, "w").write(json.dumps(trace))
    else:
        ap.error("give --trace, --synthetic or --video")

    pipe = Pipeline(zones_from(trace["zones"]), FilterConfig())
    n = 0
    with open(args.out, "w") as out:
        for frame in trace["frames"]:
            for ev in pipe.step(frame["t"], [Box(*b) for b in frame["boxes"]]):
                out.write(json.dumps(ev) + "\n")
                n += 1
    print(f"{len(trace['frames'])} frames -> {n} events -> {args.out}")


if __name__ == "__main__":
    main()
