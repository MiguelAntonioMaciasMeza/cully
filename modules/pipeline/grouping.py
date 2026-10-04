"""
File: Cully/modules/pipline/grouping.py
Description: This module holds all necessary pipeline orchestration in regards to grouping
Author: Miguel Macias
Date: 2026-09-09
"""
from dataclasses import field,dataclass
import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist
from deepface.modules.verification import find_threshold
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
    def group_boxes_by_hash(self,table:str) -> defaultdict[str,BoundingBox] | None:
        print("grouping boxes by hash")
        results = self.catalog.get_boxes_by_name(table)
        if results is None:
            return

        for result in results:
            print(result)

@dataclass
class FaceGrouper:
    catalog: Catalog
    model_name: str = "Facenet512"
    metric: str = "cosine"

    def group_faces(self) -> dict[int, int]:
        """Clusters the stored embeddings for model_name into people.

        Average-linkage agglomerative clustering, cut at the model's recognition threshold so
        two groups only merge when their average distance is still a match. Returns
        face_box_id -> group id (1-based, ordered by first appearance in the catalog).
        """
        rows = self.catalog.get_face_embeddings(self.model_name)
        if not rows:
            return {}
        if len(rows) == 1:
            return {rows[0].face_box_id: 1}

        vectors = np.array([row.embedding for row in rows])
        distances = pdist(vectors, metric=self.metric)
        tree = linkage(distances, method="average")
        threshold = find_threshold(self.model_name, self.metric)
        labels = fcluster(tree, t=threshold, criterion="distance")

        return {row.face_box_id: int(label) for row, label in zip(rows, labels)}