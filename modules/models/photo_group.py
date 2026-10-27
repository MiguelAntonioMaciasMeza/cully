"""
File: Cully/modules/models/photo_group.
Description: Models for capture_time grouping. An Event represents a long time window in where
images are taken, with Burst being a smaller window. An Event consists of Bursts, in where there is a 
list of CapturedPhoto's to represent the photos that were within that smaller time window.
Author: Miguel Macias
Date: 2026-10-26
"""
from dataclasses import dataclass, field
from datetime import datetime
import sqlite3


@dataclass
class CapturedPhoto:
    """A catalog photo with a known capture time. Unlike Photo, building one doesn't open the file."""
    image_hash: str
    image_path: str
    camera_model: str | None
    capture_time: datetime

    @classmethod
    def from_sql_row(cls, row: sqlite3.Row):
        return cls(
            row["image_hash"],
            row["image_path"],
            row["camera_model"],
            datetime.fromisoformat(row["capture_time"]),
        )


@dataclass
class Burst:
    photos: list[CapturedPhoto] = field(default_factory=list)  # in capture order

    @property
    def start_time(self) -> datetime:
        return self.photos[0].capture_time

    @property
    def end_time(self) -> datetime:
        return self.photos[-1].capture_time

    @property
    def camera_model(self) -> str | None:
        return self.photos[0].camera_model


@dataclass
class Event:
    bursts: list[Burst] = field(default_factory=list)  # in capture order

    @property
    def start_time(self) -> datetime:
        return self.bursts[0].start_time

    @property
    def end_time(self) -> datetime:
        return self.bursts[-1].end_time

    @property
    def camera_model(self) -> str | None:
        return self.bursts[0].camera_model

    @property
    def photos(self) -> list[CapturedPhoto]:
        return [photo for burst in self.bursts for photo in burst.photos]
