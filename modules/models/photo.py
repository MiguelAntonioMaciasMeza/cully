"""
File: Cully/modules/models/photo.py
Description: This file contains the model image.py
Properties:
    path_to_image: Path to where the image (.jpg,.png,.raw) is stored
    exif_data:Exif data from the camera, at the moment only grabs datetime_original
    image_hash: Unique image hash based on image content
    scores: Contains scores from each of the pipelining steps
    objects: Stores objects detected from YOLO, as long as they pass a confidence level
Author: Miguel Macias
Date: 2026-09-02
"""

from dataclasses import dataclass, field
from typing import Any
from pathlib import Path
from ingest.exifReader import ExifReader
from models.boundingbox import BoundingBox
from collections import defaultdict
from hashlib import sha256


@dataclass
class Photo:
    path_to_photo: Path
    exif_data: dict[str, Any] | None = field(default_factory=dict)
    image_hash: str = field(default_factory=str)
    scores: dict = field(default_factory=dict)
    cached: bool = False
    objects: defaultdict[str, BoundingBox] = field(default_factory=defaultdict)

    def __post_init__(self):
        raw = self.path_to_photo.read_bytes()
        self.image_hash = sha256(raw).hexdigest()
        self.exif_data = ExifReader(self.path_to_photo).get_image_exif()

    def set_objects(self, objects: defaultdict | None):
        if objects is None:
            print(f"Image {Path.stem} had no objects detected.")
            return

        self.objects = objects
