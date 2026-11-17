"""
File: Cully/modules/pipeline/embeddings.py
Description: Embeds every stored face box that has no embedding for the current model yet.
"No Faces Found" marker boxes are skipped, they are a whole person box, not a face.
Ranking does not use embeddings, so this step is optional.
Author: Miguel Macias
Date: 2026-11-16
"""

from dataclasses import dataclass, field

import cv2

from config.settings import Settings
from detector.face_embeddings import FaceEmbedder
from models.catalog import Catalog
from utils.progress import file_name, track


@dataclass
class EmbeddingStep:
    catalog: Catalog
    settings: Settings = field(default_factory=Settings)
    show_progress: bool = False  # redraw a progress line while running

    def run(self) -> int:
        """Embeds unprocessed face boxes. Returns how many photos were processed."""
        model_name = self.settings.models["embedding"]
        embedded = {row.face_box_id for row in self.catalog.get_face_embeddings(model_name)}
        face_boxes = self.catalog.get_face_boxes_with_hash() or {}
        pending = {
            h: [b for b in boxes if b.id not in embedded and b.name != "No Faces Found"]
            for h, boxes in face_boxes.items()
        }
        pending = {h: boxes for h, boxes in pending.items() if boxes}
        if not pending:
            return 0

        embedder = FaceEmbedder(settings=self.settings)
        done = 0
        for image_hash, boxes in track(pending.items(), "embeddings", self.show_progress,
                                   describe=lambda item: file_name(self.catalog.get_photo_path_by_hash(item[0]))):
            path = self.catalog.get_photo_path_by_hash(image_hash)
            img = cv2.imread(path) if path else None
            if img is None:
                print(f"[embeddings.py] Skipping {path}, could not read it")
                continue
            for box in boxes:
                crop = img[box.y1:box.y2, box.x1:box.x2]
                if embedder.register(self.catalog, box.id, image_hash, crop) is None:
                    print(f"[embeddings.py] Could not embed face box {box.id} in {path}")
            done += 1
        return done
