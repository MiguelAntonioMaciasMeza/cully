"""
File: Cully/modules/models/photo_face.py
Description: One face in a photo with what the pipeline measured on it, for the detail view.
Author: Miguel Macias
Date: 2026-11-16
"""

from dataclasses import dataclass
import sqlite3


@dataclass
class PhotoFace:
    face_box_id: int
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float
    sharpness: float | None  # None until the sharpness step has run
    ear_left: float | None  # None until the landmark step has run
    ear_right: float | None

    @classmethod
    def from_sql_row(cls, row: sqlite3.Row):
        return cls(
            row["id"],
            row["x1"],
            row["y1"],
            row["x2"],
            row["y2"],
            row["confidence"],
            row["sharpness"],
            row["ear_left"],
            row["ear_right"],
        )
