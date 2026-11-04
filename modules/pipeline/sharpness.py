"""
File: Cully/modules/pipeline/sharpness.py
Description:
Author: Miguel Macias
Date: 2026-10-30
"""

from dataclasses import dataclass, field
from models.catalog import Catalog
from scoring.laplacian import laplacian_sharpness
import cv2


@dataclass
class SharpnessStep:
    catalog: Catalog = field(default_factory=Catalog)

    def run(self, method: str):
        boxes_by_hash = self.catalog.get_face_boxes_with_hash()
        rows = []
        if boxes_by_hash is None:
            raise ValueError(
                "[sharpness.py] get_face_boxes_with_hash returned back None, check catalog DB."
            )

        for image_hash, boxes in boxes_by_hash.items():
            path = self.catalog.get_photo_path_by_hash(image_hash)
            if path is None:
                raise ValueError(
                    f"[sharpness.py] get_photo_path_by_hash returns back none on hash {image_hash}"
                )
            img = cv2.imread(path)

            # Grade each box for image
            for box in boxes:
                if method == "laplacian":
                    rows.append((box.id, "laplacian", laplacian_sharpness(img, box)))
