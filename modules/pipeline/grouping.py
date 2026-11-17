"""
File: Cully/modules/pipeline/grouping.py
Description: This module holds all necessary pipeline orchestration in regards to grouping
Author: Miguel Macias
Date: 2026-09-09
"""
from dataclasses import field,dataclass
from models.catalog import Catalog
from models.boundingbox import BoundingBox
from models.photo_group import Burst, CapturedPhoto, Event
from collections import defaultdict
from datetime import timedelta
from typing import Optional
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

    def group_boxes_by_hash(self,table:str) -> defaultdict[str,BoundingBox] | None:
        if DEBUG:
            print("[grouping.py]grouping boxes by hash")
        results = self.catalog.get_boxes_by_name(table)
        if results is None:
            return

        if DEBUG:
            for result in results:
                print(f"[grouping.py]{result}")

    def group_by_capture_time(self, burst_gap: timedelta = timedelta(seconds=5),
                              event_gap: timedelta = timedelta(minutes=30)) -> list[Event]:
        """This method allows the pipeline to group photos into events, and each event into bursts,
        by capture time.

        Walks the photos in capture order per camera and starts a new event when the gap to the
        previous shot exceeds event_gap (or the camera changes), and a new burst when it exceeds
        burst_gap. Gap splitting keeps a burst together even when it straddles a minute boundary.
        """
        events: list[Event] = []
        previous: CapturedPhoto | None = None
        for photo in self.catalog.get_photos_by_capture_time():
            if previous is None or photo.camera_model != previous.camera_model \
                    or photo.capture_time - previous.capture_time > event_gap:
                events.append(Event([Burst()]))
            elif photo.capture_time - previous.capture_time > burst_gap:
                events[-1].bursts.append(Burst())
            events[-1].bursts[-1].photos.append(photo)
            previous = photo
        return events
