"""
File: Cully/modules/detector/face_detector.py
Description: reads image and returns back the bounding_box tied only to the face region. This region will be used for getting
facial embeddings as it will allow DeepFace to already have a selected are for a given face

TO DO: 
    -FIX MODEL PATH: Current grabs from hard coded model_path, pass in settings so it'll
    grab model path from whatever config has it as




Date: 2026-09-08
"""

from dataclasses import dataclass, field
from typing import Optional, Any
from mediapipe.tasks.python.vision import FaceDetector
from mediapipe.tasks.python.components.containers.detections import Detection, DetectionResult
import mediapipe
from config.config import Config
from models.boundingbox import BoundingBox
import cv2
DEBUG = False
BaseOptions = mediapipe.tasks.BaseOptions
MPFaceDetector = mediapipe.tasks.vision.FaceDetector
FaceDetectorOptions = mediapipe.tasks.vision.FaceDetectorOptions
VisionRunningMode = mediapipe.tasks.vision.RunningMode


@dataclass
class FaceDetector:
    config: Config = field(default_factory=Config)
    detector: FaceDetector = field(init=False, repr=False)

    def __post_init__(self):
        options = FaceDetectorOptions(
            base_options=BaseOptions(model_asset_path=self.config.models_path + "/mediapipe/blaze_face_full_range.tflite"),
            running_mode=VisionRunningMode.IMAGE
        )
        self.detector = MPFaceDetector.create_from_options(options)
        
    def detect_face(self, img_path: str, bounding_box: list[BoundingBox]) -> list[BoundingBox]:
        img = cv2.imread(img_path)
        if img is None:
            raise FileNotFoundError(f"Coult not read image at: {img_path}")

        face_results: list[BoundingBox] = []
        for box in bounding_box:
            #Crop image around person box
            cropped = img[box.y1:box.y2, box.x1:box.x2]

            #Convert image for mediapipe as it requries RGB
            cropped_rgb = cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB)
            mp_image = mediapipe.Image(image_format=mediapipe.ImageFormat.SRGB, data=cropped_rgb)

            boxes = self._parse_results(self.detector.detect(mp_image),box.id)  # type: ignore[reportAttributeAccessIssue] — mediapipe stub gap, verified via dir()
            for face in boxes:
                face_results.append(face)
            if DEBUG:
                for point in boxes:
                    face_x1 = box.x1 + point.x1
                    face_y1 = box.y1 + point.y1
                    face_x2 = box.x1 + point.x2
                    face_y2 = box.y1 + point.y2
                    cv2.rectangle(img, (face_x1, face_y1), (face_x2, face_y2), (100, 100, 100), 5)
                    cv2.namedWindow("Face Detector", cv2.WINDOW_NORMAL)
                    cv2.resizeWindow("Face Detector", 1920,1080)
                    cv2.moveWindow("Face Detector" , 1920, 1080)
                    cv2.imshow("Face Detector", img)
                    cv2.waitKey()
                    cv2.destroyAllWindows()

        if len(boxes) < 1:
            face_results.append(BoundingBox(0, "Media Pipe Face Detector", "No Faces Found", 0,0,0,0,bounding_box[0].id))
            return face_results
             
        return face_results

    def _parse_results(self, detections: DetectionResult, parent_id: int) -> list[BoundingBox]:
        boxes: list[BoundingBox] = []
        for result in detections.detections: 
            x1, y1, width, height, confidence = (
                result.bounding_box.origin_x,
                result.bounding_box.origin_y,
                result.bounding_box.width,
                result.bounding_box.height,
                result.categories[0].score * 100
            )
            boxes.append(BoundingBox(round(confidence,2), "Media Pipe Face Detector", "Face Box", x1, y1, x1 + width, y1 + height, parent_id))
        return boxes

    