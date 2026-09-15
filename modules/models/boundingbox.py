"""
File: Cully/modules/models/boundingbox.py
Description: Declares the bounding box model, stores relevent information that is grabbed from YOLO's Object detection
Properties:
    confidence: YOLO's confidence on a given object 
    x1,x2,y1,y2: stores each of the points for bounding box
Author: Miguel Macias
Date: 2026-09-02
"""

from dataclasses import dataclass, field
import sqlite3

@dataclass
class BoundingBox():
    confidence: float = field(default_factory=float)
    model_version: str = field(default_factory=str)
    name: str = field(default_factory=str)
    x1: int = field(default=0)
    y1: int = field(default=0)
    x2: int = field(default=0)
    y2: int = field(default=0)
    id: int = field(default= -1)

    def set_points(self, points: list):
        self.x1 = points[0]
        self.y1 = points[1]
        self.x2 = points[2]
        self.y2 = points[3]

    @classmethod
    def from_sql_row(cls, row: sqlite3.Row):
        confidence = row["confidence"]
        model_version = row["model_version"]
        name = row["name"]
        x1 = row["x1"]
        y1 = row["y1"]
        x2 = row["x2"]
        y2 = row["y2"]
        id = row["id"]
        return cls(confidence,model_version,name, x1,y1,x2,y2, id)