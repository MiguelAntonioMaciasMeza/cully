"""
File: Cully/modules/pipeline/faces.py
Description: Finds faces inside the stored YOLO person boxes of photos that have no face boxes
yet, and stores them. A person box with no face gets a "No Faces Found" marker box.
Author: Miguel Macias
Date: 2026-11-16
"""

from dataclasses import dataclass, field

from config.config import Config
from config.settings import Settings
from detector.face_detector import FaceDetector
from models.catalog import Catalog
from pipeline.grouping import PersonGrouper
from utils.progress import file_name, track


@dataclass
class FaceStep:
    catalog: Catalog
    settings: Settings = field(default_factory=Settings)
    config: Config = field(default_factory=Config)
    show_progress: bool = False  # redraw a progress line while running

    def run(self) -> int:
        """Detects faces in unprocessed photos. Returns how many were processed."""
        person_boxes = PersonGrouper(self.catalog).group_person_boxes_by_photo() or {}
        done_hashes = self.catalog.get_face_box_hashes()
        pending = {h: boxes for h, boxes in person_boxes.items() if h not in done_hashes}
        if not pending:
            return 0

        detector = FaceDetector(config=self.config, settings=self.settings)
        done = 0
        for image_hash, boxes in track(pending.items(), "faces", self.show_progress,
                                   describe=lambda item: file_name(self.catalog.get_photo_path_by_hash(item[0]))):
            path = self.catalog.get_photo_path_by_hash(image_hash)
            if path is None:
                print(f"[faces.py] Skipping {image_hash}, no path in catalog")
                continue
            try:
                faces = detector.detect_face(path, boxes)
            except FileNotFoundError as e:
                print(f"[faces.py] Skipping {path}: {e}")
                continue
            for face in faces:
                self.catalog.insert_face_box(face)
            done += 1
        return done
