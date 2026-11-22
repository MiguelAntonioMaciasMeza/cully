"""
File: Cully/modules/detector/face_detector.py
Description: reads image and returns back the bounding_box tied only to the face region. This region will be used for getting
facial embeddings as it will allow DeepFace to already have a selected are for a given face
The model is loaded from Config.models_path.
Date: 2026-09-08
"""

from dataclasses import dataclass, field
from typing import Optional, Any
from mediapipe.tasks.python.vision import FaceDetector
from mediapipe.tasks.python.components.containers.detections import Detection, DetectionResult
import mediapipe
from config.config import Config
from config.settings import Settings
from models.boundingbox import BoundingBox
from pathlib import Path
import cv2
from utils.read_image import read_image
DEBUG = False
BaseOptions = mediapipe.tasks.BaseOptions
MPFaceDetector = mediapipe.tasks.vision.FaceDetector
FaceDetectorOptions = mediapipe.tasks.vision.FaceDetectorOptions
VisionRunningMode = mediapipe.tasks.vision.RunningMode


@dataclass
class FaceDetector:
    config: Config = field(default_factory=Config)
    settings: Settings = field(default_factory=Settings)
    detector: FaceDetector = field(init=False, repr=False)

    def __post_init__(self):
        model_path = Path(self.config.models_path) / "mediapipe" / "face_detection" / "blaze_face_full_range.tflite"
        options = FaceDetectorOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=VisionRunningMode.IMAGE
        )
        self.detector = MPFaceDetector.create_from_options(options)
        
    def detect_face(self, img_path: str, bounding_box: list[BoundingBox]) -> list[BoundingBox]:
        img = read_image(img_path)
        if img is None:
            raise FileNotFoundError(f"Coult not read image at: {img_path}")

        face_results: list[BoundingBox] = []
        for box in bounding_box:
            #Crop image around person box
            cropped = img[box.y1:box.y2, box.x1:box.x2]
            if DEBUG:
                print(cropped)
            #Convert image for mediapipe as it requries RGB
            cropped_rgb = cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB)
            mp_image = mediapipe.Image(image_format=mediapipe.ImageFormat.SRGB, data=cropped_rgb)

            boxes = self._parse_results(self.detector.detect(mp_image),box)  # type: ignore[reportAttributeAccessIssue] — mediapipe stub gap, verified via dir()
            for face in boxes:
                face_results.append(face)
            if DEBUG:
                for point in boxes:
                    face_x1 = point.x1
                    face_y1 = point.y1
                    face_x2 = point.x2
                    face_y2 = point.y2
                    cv2.rectangle(img, (face_x1, face_y1), (face_x2, face_y2), (100, 100, 100), 5)
                    cv2.namedWindow("Face Detector", cv2.WINDOW_NORMAL)
                    cv2.resizeWindow("Face Detector", 1920,1080)
                    cv2.moveWindow("Face Detector" , 1920, 1080)
                    cv2.imshow("Face Detector", img)
                    cv2.waitKey()
                    cv2.destroyAllWindows()

        #If no faces are detected, box the whole image and see if landmarker can detect anything
        if not face_results and bounding_box:
            face_results.append(BoundingBox(0, "Media Pipe Face Detector", "No Faces Found", 0,0,img.shape[1],img.shape[0],bounding_box[0].id))

        return face_results

    def _parse_results(self, detections: DetectionResult, origin_box: BoundingBox) -> list[BoundingBox]:
        boxes: list[BoundingBox] = []
        for result in detections.detections: 
            x1, y1, width, height, confidence = (
                result.bounding_box.origin_x + origin_box.x1 ,
                result.bounding_box.origin_y + origin_box.y1,
                result.bounding_box.width ,
                result.bounding_box.height ,
                result.categories[0].score * 100
            )
            # Low confidence boxes are mostly the back of a head or clothing, not a usable face
            if confidence < self.settings.face_threshold:
                continue
            boxes.append(BoundingBox(round(confidence,2), "Media Pipe Face Detector", "Face Box", x1, y1, x1 + width, y1 + height, origin_box.id))
        return boxes

    