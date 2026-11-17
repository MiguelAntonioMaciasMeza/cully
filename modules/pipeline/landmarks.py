"""
File: Cully/modules/pipeline/landmarks.py
Description: Runs the MediaPipe face landmarker on the face boxes of photos that have no
landmarks yet, and stores the results (including eye aspect ratios).
Author: Miguel Macias
Date: 2026-11-16
"""

from dataclasses import dataclass, field

from config.config import Config
from config.settings import Settings
from detector.face_landmarker import FaceLandmarker
from models.catalog import Catalog
from utils.progress import file_name, track


@dataclass
class LandmarkStep:
    catalog: Catalog
    settings: Settings = field(default_factory=Settings)
    config: Config = field(default_factory=Config)
    show_progress: bool = False  # redraw a progress line while running

    def run(self) -> int:
        """Finds landmarks in unprocessed photos. Returns how many were processed."""
        face_boxes = self.catalog.get_face_boxes_with_hash() or {}
        done_hashes = self.catalog.hashes_from_face_landmarks()
        pending = {h: boxes for h, boxes in face_boxes.items() if h not in done_hashes}
        if not pending:
            return 0

        detector = FaceLandmarker(config=self.config)
        done = 0
        for image_hash, boxes in track(pending.items(), "landmarks", self.show_progress,
                                   describe=lambda item: file_name(self.catalog.get_photo_path_by_hash(item[0]))):
            path = self.catalog.get_photo_path_by_hash(image_hash)
            if path is None:
                print(f"[landmarks.py] Skipping {image_hash}, no path in catalog")
                continue
            try:
                landmarks = detector.detect_landmarks(path, image_hash, boxes)
            except FileNotFoundError as e:
                print(f"[landmarks.py] Skipping {path}: {e}")
                continue
            if landmarks:
                self.catalog.insert_face_landmarks(landmarks)
            done += 1
        return done
