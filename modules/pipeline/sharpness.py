"""
File: Cully/modules/pipeline/sharpness.py
Description: Scores how sharp every stored face box is and saves the scores to the catalog's
face_scores table. Crops are scaled to the crop_size["sharpness"] setting before scoring.
Author: Miguel Macias
Date: 2026-10-30
"""

from dataclasses import dataclass, field
from config.settings import Settings
from models.catalog import Catalog
from scoring.laplacian import laplacian_sharpness
from utils.progress import file_name, track
import cv2


@dataclass
class SharpnessStep:
    catalog: Catalog = field(default_factory=Catalog)
    settings: Settings = field(default_factory=Settings)
    show_progress: bool = False  # redraw a progress line while running

    def run(self, method: str | None = None):
        method = method or self.settings.models["sharpness"]
        if method != "laplacian":
            raise ValueError(f"[sharpness.py] Unknown sharpness method {method!r}, expected 'laplacian'")
        target = self.settings.crop_size["sharpness"]
        boxes_by_hash = self.catalog.get_face_boxes_with_hash()
        rows = []
        if boxes_by_hash is None:
            raise ValueError(
                "[sharpness.py] get_face_boxes_with_hash returned back None, check catalog DB."
            )

        for image_hash, boxes in track(boxes_by_hash.items(), "sharpness", self.show_progress,
                                   describe=lambda item: file_name(self.catalog.get_photo_path_by_hash(item[0]))):
            path = self.catalog.get_photo_path_by_hash(image_hash)
            if path is None:
                raise ValueError(
                    f"[sharpness.py] get_photo_path_by_hash returns back none on hash {image_hash}"
                )
            img = cv2.imread(path)

            # Grade each box for image
            for box in boxes:
                # A box with no area inside the image can't be graded, skip it rather than the whole run
                try:
                    rows.append((box.id, method, laplacian_sharpness(img, box, target)))
                except ValueError as e:
                    print(f"[sharpness.py] Skipping box {box.id} on hash {image_hash}: {e}")

        self.catalog.insert_face_scores(rows)
