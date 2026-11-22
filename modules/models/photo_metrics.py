"""
File: Cully/modules/models/photo_metrics.py
Description: Whole-frame numbers for one photo, made by the exposure step: brightness, how much is
blown out or crushed, and whole-frame sharpness (used to rank photos with no usable face).
Author: Miguel Macias
Date: 2026-11-21
"""

from dataclasses import dataclass
import sqlite3


@dataclass
class PhotoMetrics:
    image_hash: str
    brightness: float  # mean grey level, 0-255
    clipped: float  # % of pixels blown out (>= 250)
    crushed: float  # % of pixels crushed to black (<= 5)
    sharpness: float  # Laplacian variance of the whole frame, only compared within a burst

    @classmethod
    def from_sql_row(cls, row: sqlite3.Row):
        return cls(row["image_hash"], row["brightness"], row["clipped"], row["crushed"], row["sharpness"])
