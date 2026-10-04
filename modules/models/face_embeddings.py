"""
File: Cully/modules/models/face_embeddings.py
Description: This model stores all the attributes required for passing face embeddings
into our db
Author: Miguel Macias
Date: 2026-09-05
"""
from dataclasses import dataclass, field
import json
import sqlite3


@dataclass
class FaceEmbeddings():
    face_box_id: int = field(default_factory=int)
    image_hash: str = field(default_factory=str)
    model_name: str = field(default_factory=str)
    embedding: list[float] = field(default_factory=list)

    @classmethod
    def from_sql_row(cls, row: sqlite3.Row):
        return cls(
            row["face_box_id"],
            row["image_hash"],
            row["model_name"],
            json.loads(row["embedding_json"]),
        )
