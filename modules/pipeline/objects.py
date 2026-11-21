"""
File: Cully/modules/pipeline/objects.py
Description: Runs YOLO on every catalog photo that has no object boxes yet and stores the boxes.
Photos are shrunk by the detection["object_scale"] setting before detection; boxes are scaled
back to full size.
Author: Miguel Macias
Date: 2026-11-16
"""

from dataclasses import dataclass, field

import cv2

from config.config import Config
from config.settings import Settings
from utils.steps import fingerprint
from detector.one_shot_object import Objects
from models.catalog import Catalog
from utils.progress import file_name, track


@dataclass
class ObjectStep:
    catalog: Catalog
    settings: Settings = field(default_factory=Settings)
    config: Config = field(default_factory=Config)
    show_progress: bool = False  # redraw a progress line while running

    def run(self) -> int:
        """Detects objects in unprocessed photos. Returns how many were processed."""
        pending = self.catalog.get_all_hashes() - self.catalog.get_object_hashes()
        if not pending:
            return 0

        detector = Objects(settings=self.settings, config=self.config)
        scale = float(self.settings.detection["object_scale"])
        settings_used = fingerprint(self.settings, "objects")
        done = 0
        for image_hash in track(sorted(pending), "objects", self.show_progress,
                                   describe=lambda item: file_name(self.catalog.get_photo_path_by_hash(item))):
            path = self.catalog.get_photo_path_by_hash(image_hash)
            img = cv2.imread(path) if path else None
            if img is None:
                print(f"[objects.py] Skipping {path}, could not read it")
                continue

            h, w = img.shape[:2]
            resized = cv2.resize(img, (int(w * scale), int(h * scale)))
            boxes = detector.detect_objects(resized, 1 / scale)
            if boxes:
                self.catalog.insert_bounding_box(image_hash, boxes)
            #Per photo, so a cancelled run still records what it finished
            self.catalog.record_step_runs("objects", [image_hash], settings_used)
            done += 1
        return done
