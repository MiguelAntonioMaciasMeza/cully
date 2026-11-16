"""
File: Cully/modules/models/face_score.py
Description: Models for ranking photos inside a burst. FaceScore holds one face's sharpness and
eye openness, RankedPhoto holds a photo's place within its burst.
Author: Miguel Macias
Date: 2026-11-06
"""

from dataclasses import dataclass
import sqlite3


@dataclass
class FaceScore:
    face_box_id: int
    image_hash: str
    sharpness: float
    # Smaller of the two EARs, so a wink counts as closed. None when landmarks found no face
    ear: float | None = None
    # Who this face is, from position matching within the burst (scoring/face_matching.py)
    person_id: int | None = None
    box: tuple[int, int, int, int] | None = None  # x1, y1, x2, y2 in the full image

    @classmethod
    def from_sql_row(cls, row: sqlite3.Row):
        ears = (row["ear_left"], row["ear_right"])
        return cls(
            row["face_box_id"],
            row["image_hash"],
            row["score"],
            None if None in ears else min(ears),
            box=(row["x1"], row["y1"], row["x2"], row["y2"]),
        )


@dataclass
class RankedPhoto:
    image_hash: str
    score: float  # weakest face's sharpness relative to the burst's best, 0-1
    eyes_open: bool
    rank: int = 0  # 1 = best in burst
    is_candidate: bool = False  # close enough to the best to keep, see rank_burst
