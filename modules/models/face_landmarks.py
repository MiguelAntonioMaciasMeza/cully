"""
File: Cully/modules/models/face_landmarks.py
Description: This file contains the FaceLandmarks class, that contains facial landmarks
detected within a BoundingBox, with eye_blink_left and eye_blink_right stored directory as a value
while the rest are stored in JSON format
Author: Miguel Macias
Date: 2026-09-14
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING
from collections import defaultdict

# Type-only: importing mediapipe at runtime (via Catalog) before triton segfaults torch/YOLO
if TYPE_CHECKING:
    from mediapipe.tasks.python.components.containers.category import Category
import json
import sqlite3


@dataclass
class FaceLandmarks:
    face_box_id: int = field(default_factory=int)
    eye_blink_left: float = field(default_factory=float)
    eye_blink_right: float = field(default_factory=float)
    landmark_scores: defaultdict[str, float] = field(default_factory=defaultdict)
    image_hash: str = field(default_factory=str)

    @classmethod
    def from_landmark_detection(cls, box_id: int, results: list[Category],image_hash: str):
        eye_blink_left: float = 0
        eye_blink_right: float = 0
        landmark_scores: defaultdict[str, float] = defaultdict(float)
        for index, landmark in enumerate(results):
            if landmark.category_name == "eyeBlinkLeft":
                if landmark.score is not None:
                    eye_blink_left = round(landmark.score * 100, 4)
            if landmark.category_name == "eyeBlinkRight":
                if landmark.score is not None:
                    eye_blink_right = round(landmark.score * 100, 4)
            if landmark.score is not None and landmark.category_name is not None:
                landmark_scores[landmark.category_name] = round(landmark.score, 4)

        return cls(box_id, eye_blink_left, eye_blink_right, landmark_scores,image_hash)

    @classmethod
    def from_sql_row(cls, row: sqlite3.Row):
        return cls(
            row["face_box_id"],
            row["eye_blink_left"],
            row["eye_blink_right"],
            json.loads(row["landmark_scores_json"]),
            row["image_hash"]
        )
