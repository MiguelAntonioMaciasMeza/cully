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

            results.append(
                self._parse_results(self.detector.detect(mp_image), box.id, image_hash)
            )
        return results

    def _parse_results(
        self, landmarks: LandmarksDetectionResult, parent_id: int, image_hash: str
    ) -> FaceLandmarks:
        if len(landmarks.face_blendshapes) > 0:
            categories = landmarks.face_blendshapes[0]

            return FaceLandmarks.from_landmark_detection(
                parent_id, categories, image_hash
            )
        else:
            return FaceLandmarks(parent_id, 0, 0, defaultdict(), image_hash)
