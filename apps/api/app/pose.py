"""Use Google's pretrained pose landmarks to reject standing people."""
from math import sqrt

import cv2
import mediapipe as mp


class Pose:
    def __init__(self, path):
        options = mp.tasks.vision.PoseLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(path)),
            min_pose_detection_confidence=.35,
        )
        self.model = mp.tasks.vision.PoseLandmarker.create_from_options(options)

    def seated(self, frame, box, tables):
        self.service_motion = False
        height, width = frame.shape[:2]
        margin = .12 * (box.y2 - box.y1)
        left = int(max(0, box.x1 - margin) * width)
        right = int(min(1, box.x2 + margin) * width)
        top = int(max(0, box.y1 - margin) * height)
        bottom = int(min(1, box.y2 + margin) * height)
        if right <= left or bottom <= top:
            return None
        image = mp.Image(image_format=mp.ImageFormat.SRGB,
                         data=cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2RGB))
        result = self.model.detect(image)
        if not result.pose_world_landmarks:
            return None
        image_landmarks = result.pose_landmarks[0]
        shoulders = [image_landmarks[i] for i in (11, 12)]
        hips = [image_landmarks[i] for i in (23, 24)]
        if min(p.visibility for p in shoulders + hips) >= .45:
            shoulder_x = sum(p.x for p in shoulders) / 2
            hip_x = sum(p.x for p in hips) / 2
            torso_height = abs(sum(p.y for p in shoulders) / 2 - sum(p.y for p in hips) / 2)
            if abs(shoulder_x - hip_x) * (right - left) > .45 * torso_height * (bottom - top):
                for wrist in (image_landmarks[15], image_landmarks[16]):
                    x = (left + wrist.x * (right - left)) / width
                    y = (top + wrist.y * (bottom - top)) / height
                    if wrist.visibility >= .5 and any(
                        table.x1 <= x <= table.x2 and table.y1 <= y <= table.y2 for table in tables
                    ):
                        self.service_motion = True
                        return False
        landmarks = result.pose_world_landmarks[0]
        angles = []
        for indices in [(23, 25, 27), (24, 26, 28)]:
            hip, knee, ankle = (landmarks[i] for i in indices)
            if min(hip.visibility, knee.visibility, ankle.visibility) < .45:
                continue
            thigh = [getattr(hip, axis) - getattr(knee, axis) for axis in "xyz"]
            shin = [getattr(ankle, axis) - getattr(knee, axis) for axis in "xyz"]
            magnitude = sqrt(sum(v*v for v in thigh) * sum(v*v for v in shin))
            if magnitude:
                angles.append(sum(a*b for a, b in zip(thigh, shin)) / magnitude)
        if any(angle > -.65 for angle in angles):
            return True
        if angles:
            return False
        return None
