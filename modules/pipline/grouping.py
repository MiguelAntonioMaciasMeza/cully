"""
File: Cully/modules/pipline/grouping.py
Description: This module holds all necessary pipeline orchestration in regards to grouping
Author: Miguel Macias
Date: 2026-09-09
"""
from dataclasses import field,dataclass
from models.catalog import Catalog
from models.boundingbox import BoundingBox
from collections import defaultdict
from typing import Any, Optional
DEBUG = False
@dataclass
class PersonGrouper:
    catalog: Catalog = field(default_factory=Catalog)

    def __init__(self, catalog: Catalog):
        self.catalog = catalog

    def group_person_boxes_by_photo(self) -> Optional[dict[str,list[BoundingBox]]]:
        bounding_boxes = self.catalog.get_boxes_by_name("person")
        if bounding_boxes is None:
            if DEBUG:
                print("No new detections of people in images")
            return None
        img_group: defaultdict[str,list[BoundingBox]] = defaultdict(list)
        for boxes in bounding_boxes:
            if DEBUG:
                print(boxes)
            img_group[boxes["image_hash"]].append(
                BoundingBox(confidence= boxes["confidence"],
                            model_version=boxes["model_version"],
                            name = boxes["name"],
                            x1= boxes["x1"],
                            y1 = boxes["y1"],
                            x2 = boxes["x2"],
                            y2 = boxes["y2"],
                            id = boxes["id"]
                            ))
        return img_group

@dataclass
class ImageGrouper:
    catalog: Catalog = field(default_factory=Catalog)

    def __init__(self, catalog: Catalog):
        self.catalog = catalog

    def group_by_exif_range(self, window: Any):
        pass

@dataclass
class FaceGrouper:
    face_boxes: list[BoundingBox] = field(default_factory= list)

    def group_face_boxes(self, catalog: Catalog):
        pass