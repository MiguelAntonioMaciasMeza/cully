"""
File: Cully/modules/pipeline/exposure.py
Description: Measures every photo's exposure and whole-frame sharpness, and every face's brightness,
then stores them for ranking (see scoring/exposure.py). Only photos and faces not measured yet are read.
Photos are read at 1/4 size, which is plenty for brightness and keeps the step quick.
Author: Miguel Macias
Date: 2026-11-21
"""

from dataclasses import dataclass

import cv2

from models.catalog import Catalog
from scoring.exposure import face_brightness, frame_metrics
from utils.progress import file_name, track
from utils.read_image import read_image

READ_FLAGS = cv2.IMREAD_REDUCED_COLOR_4
READ_SCALE = 0.25  # what READ_FLAGS gives, used when a photo's width isn't stored


@dataclass
class ExposureStep:
    catalog: Catalog
    show_progress: bool = False  # redraw a progress line while running

    def run(self) -> int:
        """Measures unmeasured photos and faces. Returns how many photos were read."""
        pending_photos = self.catalog.get_all_hashes() - self.catalog.get_photo_metric_hashes()
        measured = self.catalog.get_face_exposure_ids()
        pending_faces = {
            image_hash: [b for b in boxes if b.id not in measured and b.name != "No Faces Found"]
            for image_hash, boxes in (self.catalog.get_face_boxes_with_hash() or {}).items()
        }
        todo = pending_photos | {h for h, boxes in pending_faces.items() if boxes}
        if not todo:
            return 0

        widths = self.catalog.get_photo_widths()
        done = 0
        for image_hash in track(sorted(todo), "exposure", self.show_progress,
                                describe=lambda item: file_name(self.catalog.get_photo_path_by_hash(item))):
            path = self.catalog.get_photo_path_by_hash(image_hash)
            img = read_image(path, READ_FLAGS)
            if img is None:
                print(f"[exposure.py] Skipping {path}, could not read it")
                continue
            # Face boxes are in full-size pixels, the read is smaller
            width = widths.get(image_hash)
            scale = img.shape[1] / width if width else READ_SCALE
            faces = []
            for box in pending_faces.get(image_hash, []):
                brightness = face_brightness(img, (box.x1, box.y1, box.x2, box.y2), scale)
                if brightness is not None:
                    faces.append((box.id, brightness))
            metrics = frame_metrics(image_hash, img) if image_hash in pending_photos else None
            # Per photo, so a cancelled run still keeps what it finished
            self.catalog.insert_photo_exposure(metrics, faces)
            done += 1
        return done
