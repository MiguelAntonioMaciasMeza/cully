"""
File: Cully/modules/models/report_photo.py
Description: One photo as the results report shows it: its event and burst, ranking flags and how many
persons and faces were found (used to explain why a photo is unranked).
Author: Miguel Macias
Date: 2026-11-16
"""

from dataclasses import dataclass
import sqlite3


@dataclass
class ReportPhoto:
    image_hash: str
    image_path: str
    camera_model: str | None
    capture_time: str | None
    event_id: int | None
    event_start: str | None
    event_end: str | None
    burst_id: int | None
    burst_start: str | None
    score: float | None
    rank: int | None
    eyes_open: bool | None
    is_candidate: bool
    persons: int  # YOLO person boxes
    faces: int  # real face boxes at or above the face threshold
    culled_status: str | None
    width: int | None
    height: int | None
    @property
    def unranked_reason(self) -> str | None:
        """Short reason the photo has no rank, None if it is ranked."""
        if self.rank is not None:
            return None
        if self.capture_time is None:
            return "No capture time"
        if self.persons == 0:
            return "No person found"
        if self.faces == 0:
            return "No usable face"
        return "Not scored"

    @classmethod
    def from_sql_row(cls, row: sqlite3.Row):
        return cls(
            row["image_hash"],
            row["image_path"],
            row["camera_model"],
            row["capture_time"],
            row["event_id"],
            row["event_start"],
            row["event_end"],
            row["burst_id"],
            row["burst_start"],
            row["final_score"],
            row["burst_rank"],
            None if row["eyes_open"] is None else bool(row["eyes_open"]),
            bool(row["is_candidate"]),
            row["persons"],
            row["faces"],
            row["culled_status"],
            row["width"],
            row["height"]
        )
