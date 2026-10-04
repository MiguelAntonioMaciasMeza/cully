"""
File: Cully/modules/detector/face_embeddings.py
Description: Computes face embeddings with DeepFace and stores/searches them against
our own sqlite Catalog. DeepFace's own register()/search() are not used here: both are
hard-wired to a fixed set of external database backends out sqlite catalog. Therefore we have to compute 
Author: Miguel Macias
Date: 2026-09-28
"""
from dataclasses import dataclass, field
import numpy as np
from numpy.typing import NDArray
import tensorflow as tf
from deepface import DeepFace
from deepface.modules.verification import find_distance, find_threshold
from models.catalog import Catalog
from models.face_embeddings import FaceEmbeddings as FaceEmbeddingRow

for gpu in tf.config.list_physical_devices("GPU"):
    tf.config.experimental.set_memory_growth(gpu, True)


@dataclass
class FaceEmbeddings:
    model_name: str = "Facenet512"

    def __post_init__(self):
        DeepFace.build_model(task="facial_recognition", model_name=self.model_name)

    def embed(self, crop: NDArray[np.uint8]) -> list[float] | None:
        if crop is None or crop.size == 0:
            return None
        results = DeepFace.represent(
            img_path=crop,  # BGR numpy array, no file read
            model_name=self.model_name,
            detector_backend="skip",  # box already found by MediaPipe
            enforce_detection=False,
        )
        if not results:
            return None

        return results[0]["embedding"]

    def register(
        self,
        catalog: Catalog,
        face_box_id: int,
        image_hash: str,
        crop: NDArray[np.uint8],
    ) -> FaceEmbeddingRow | None:
        """Embeds crop and stores it in the catalog's face_embeddings table."""
        embedding = self.embed(crop)
        if embedding is None:
            return None

        row = FaceEmbeddingRow(face_box_id, image_hash, self.model_name, embedding)
        catalog.insert_face_embeddings([row])
        return row

    def search(
        self,
        catalog: Catalog,
        crop: NDArray[np.uint8],
        metric: str = "cosine",
        k: int | None = None,
    ) -> list[tuple[FaceEmbeddingRow, float]]:
        """Embeds crop and returns catalog matches sorted by ascending distance.

        Matches are limited to the model's recognition threshold, unless k is given,
        in which case the k closest rows are returned regardless of threshold.
        """
        query_embedding = self.embed(crop)
        if query_embedding is None:
            return []

        threshold = find_threshold(self.model_name, metric)
        candidates = catalog.get_face_embeddings(self.model_name)

        results = [
            (row, find_distance(query_embedding, row.embedding, metric))
            for row in candidates
        ]
        results.sort(key=lambda pair: pair[1])

        if k is not None:
            return results[:k]
        return [pair for pair in results if pair[1] <= threshold]

    def compare_and_group(
        self,
        embeddings: dict[int, list[float]],
        metric: str = "cosine",
    ) -> dict[int, int]:
        threshold = find_threshold(self.model_name, metric)
        groups: list[list[int]] = []  # each group is a list of face_box_ids
        assignment: dict[int, int] = {}

        for face_id, emb in embeddings.items():
            best_group, best_dist = None, threshold
            for gid, members in enumerate(groups):
                # average distance to the group's members
                d = sum(
                    find_distance(emb, embeddings[m], metric) for m in members
                ) / len(members)
                if d < best_dist:
                    best_group, best_dist = gid, d

            if best_group is None:
                groups.append([face_id])
                assignment[face_id] = len(groups) - 1
            else:
                groups[best_group].append(face_id)
                assignment[face_id] = best_group

        return assignment
