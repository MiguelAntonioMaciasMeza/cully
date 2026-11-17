"""
File: Cully/modules/pipeline/face_grouping.py
Description: Clusters stored face embeddings into people. Kept apart from grouping.py
because it needs scipy and deepface (venv-faces only).
Author: Miguel Macias
Date: 2026-11-16
"""
from dataclasses import dataclass, field
import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist
from deepface.modules.verification import find_threshold
from config.settings import Settings
from models.catalog import Catalog


@dataclass
class FaceGrouper:
    catalog: Catalog
    # model_name and metric come from the "models" setting unless given here
    model_name: str = ""
    metric: str = ""
    settings: Settings = field(default_factory=Settings)

    def __post_init__(self):
        self.model_name = self.model_name or self.settings.models["embedding"]
        self.metric = self.metric or self.settings.models["embedding_metric"]

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
