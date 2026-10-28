"""
File: Cully/modules/detector/face_landmarker.py
Description: Contains the FaceLandmarker class, responsible for detecting and returning
any facial landmark feature detected within a BoundingBox if any
Author: Miguel Macias
Date: 2026-09-14
"""

import mediapipe
from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions
from config.config import Config
from models.boundingbox import BoundingBox
from dataclasses import dataclass, field
from mediapipe.tasks.python.components.containers.landmark_detection_result import (
    LandmarksDetectionResult,
)
from models.face_landmarks import FaceLandmarks
from collections import defaultdict
import cv2
import numpy as np
import pprint
from platformdirs import user_data_dir

DEBUG = False
BaseOptions = mediapipe.tasks.BaseOptions
MPFaceLandmarker = mediapipe.tasks.vision.FaceLandmarker
LandmarkerOptions = mediapipe.tasks.vision.FaceLandmarkerOptions
VisionRunningMode = mediapipe.tasks.vision.RunningMode
MODEL_DIR = str(
    user_data_dir("cully") + "/models/mediapipe/face_landmarker/face_landmarker.task"
)
print(MODEL_DIR)

# Face mesh indices for EAR as p1..p6: p1/p4 are the eye corners, p2/p6 and p3/p5 the upper/lower
# lid pairs. Left/right are the subject's, matching the eyeBlinkLeft/eyeBlinkRight blendshapes
LEFT_EYE = (362, 385, 387, 263, 373, 380)
RIGHT_EYE = (33, 160, 158, 133, 153, 144)


def eye_aspect_ratio(points, eye: tuple[int, ...], width: int, height: int) -> float:
    """EAR = (|p2-p6| + |p3-p5|) / (2|p1-p4|): This method calculates the eye aspect ratio.
    We use face mesh indices and normalize the points to our crop. As a non square crop will
    skew our results.
    """
    p1, p2, p3, p4, p5, p6 = (np.array([points[i].x * width, points[i].y * height]) for i in eye)
    return float((np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)) / (2 * np.linalg.norm(p1 - p4)))


@dataclass
class FaceLandmarker:
    config: Config = field(default_factory=Config)
    detector: FaceLandmarker = field(init=False, repr=False)

    def __post_init__(self):
        options = FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=MODEL_DIR),
            running_mode=VisionRunningMode.IMAGE,
            output_face_blendshapes=True,
        )
        self.detector = MPFaceLandmarker.create_from_options(options)

    def detect_landmarks(
        self, image_path: str, image_hash: str, bounding_box: list[BoundingBox]
    ) -> list[FaceLandmarks] | None:
        img = cv2.imread(image_path)
        results: list[FaceLandmarks] = list()
        if img is None:
            raise FileNotFoundError(f"Could not read image at; {image_path}")
        for box in bounding_box:
            cropped = img[box.y1 : box.y2, box.x1 : box.x2]

            if DEBUG:
                cv2.namedWindow("cropped", cv2.WINDOW_NORMAL)
                cv2.resizeWindow("cropped", 1920, 1080)
                cv2.imshow("cropped", cropped)
                cv2.waitKey()
                cv2.destroyAllWindows()

            cropped_rgb = cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB)
            mp_image = mediapipe.Image(
                image_format=mediapipe.ImageFormat.SRGB, data=cropped_rgb
            )
            if DEBUG:
                print(
                    f"[face_landmarker.py]Reading image:{image_path} into landmark detector "
                )

            height, width = cropped.shape[:2]
            results.append(
                self._parse_results(self.detector.detect(mp_image), box.id, image_hash, width, height)
            )
        return results

    def _parse_results(
        self, landmarks: LandmarksDetectionResult, parent_id: int, image_hash: str, width: int, height: int
    ) -> FaceLandmarks:
        if len(landmarks.face_blendshapes) > 0:
            categories = landmarks.face_blendshapes[0]

            result = FaceLandmarks.from_landmark_detection(
                parent_id, categories, image_hash
            )
            if len(landmarks.face_landmarks) > 0:
                points = landmarks.face_landmarks[0]
                result.ear_left = eye_aspect_ratio(points, LEFT_EYE, width, height)
                result.ear_right = eye_aspect_ratio(points, RIGHT_EYE, width, height)
            return result
        else:
            return FaceLandmarks(parent_id, 0, 0, defaultdict(), image_hash)
