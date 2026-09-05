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

@dataclass
class BoundingBox():
    confidence: float = field(default_factory=float)
    model_version: str = field(default_factory=str)
    name: str = field(default_factory=str)
    x1: int = field(default=0)
    y1: int = field(default=0)
    x2: int = field(default=0)
    y2: int = field(default=0)

    def set_points(self, points: list):
        self.x1 = points[0]
        self.y1 = points[1]
        self.x2 = points[2]
        self.y2 = points[3]