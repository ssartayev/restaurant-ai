"""Person detectors behind one small interface, so the rest of the worker never
depends on a particular model.

  TraceDetector       replays boxes from a JSON trace (tests, synthetic evaluation, demos)
  OnnxYoloxDetector   YOLOX exported to ONNX, run on CPU with ONNX Runtime

STATUS: OnnxYoloxDetector follows the published YOLOX pre/post-processing but has NOT
been run against real weights or footage in this repository. Verify it on the first
staged clip (AGENTS.md section 8, task CV-1) before trusting any number from it.
Check the licence of the exact weights you download (YOLOX is Apache-2.0).
"""
from typing import Protocol

from .zones import Box


class Detector(Protocol):
    def detect(self, frame) -> list[Box]:
        """Return person boxes for one frame, normalised to 0..1."""


class TraceDetector:
    """frames: list of {"t": seconds, "boxes": [[x1, y1, x2, y2, conf], ...]}"""

    def __init__(self, frames: list[dict]):
        self.frames = frames

    def __iter__(self):
        for f in self.frames:
            yield f["t"], [Box(*b) for b in f["boxes"]]


class OnnxYoloxDetector:
    PERSON_CLASS = 0  # COCO

    def __init__(self, model_path: str, input_size: int = 640, score_thr: float = 0.35,
                 nms_thr: float = 0.45):
        import numpy as np
        import onnxruntime as ort
        self.np = np
        self.session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.size, self.score_thr, self.nms_thr = input_size, score_thr, nms_thr

    def _preprocess(self, frame):
        import cv2
        np, s = self.np, self.size
        h, w = frame.shape[:2]
        r = min(s / h, s / w)
        resized = cv2.resize(frame, (int(w * r), int(h * r)), interpolation=cv2.INTER_LINEAR)
        padded = np.full((s, s, 3), 114, dtype=np.uint8)  # letterbox: pad bottom/right
        padded[: resized.shape[0], : resized.shape[1]] = resized
        blob = padded.transpose(2, 0, 1)[None].astype(np.float32)  # YOLOX expects raw 0..255 BGR
        return blob, r, (h, w)

    def _decode(self, out):
        """YOLOX heads predict offsets per grid cell at strides 8, 16, 32."""
        np, s = self.np, self.size
        grids, strides = [], []
        for stride in (8, 16, 32):
            n = s // stride
            xv, yv = np.meshgrid(np.arange(n), np.arange(n))
            grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
            strides.append(np.full((n * n, 1), stride))
        grids, strides = np.concatenate(grids), np.concatenate(strides)
        out = out.copy()
        out[:, :2] = (out[:, :2] + grids) * strides
        out[:, 2:4] = np.exp(out[:, 2:4]) * strides
        return out

    def _nms(self, boxes, scores):
        np = self.np
        order, keep = scores.argsort()[::-1], []
        area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
        while order.size:
            i = order[0]
            keep.append(i)
            xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
            yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
            xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
            yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
            inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
            iou = inter / (area[i] + area[order[1:]] - inter + 1e-9)
            order = order[1:][iou <= self.nms_thr]
        return keep

    def detect(self, frame) -> list[Box]:
        np = self.np
        blob, r, (h, w) = self._preprocess(frame)
        pred = self._decode(self.session.run(None, {self.input_name: blob})[0][0])
        scores = pred[:, 4] * pred[:, 5 + self.PERSON_CLASS]
        mask = scores >= self.score_thr
        pred, scores = pred[mask], scores[mask]
        if not len(pred):
            return []
        xyxy = np.stack([pred[:, 0] - pred[:, 2] / 2, pred[:, 1] - pred[:, 3] / 2,
                         pred[:, 0] + pred[:, 2] / 2, pred[:, 1] + pred[:, 3] / 2], 1) / r
        out = []
        for i in self._nms(xyxy, scores):
            x1, y1, x2, y2 = xyxy[i]
            out.append(Box(max(0.0, x1 / w), max(0.0, y1 / h), min(1.0, x2 / w), min(1.0, y2 / h),
                           float(scores[i])))
        return out
