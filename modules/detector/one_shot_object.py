from ultralytics import YOLO
from ultralytics.engine.results import Results
from dataclasses import dataclass, field
from config.settings import Settings
from models.photo import Photo
from models.boundingbox import BoundingBox
from models.catalog import Catalog
from typing import cast
from pathlib import Path
from collections import defaultdict
import numpy as np
import pprint
import cv2


@dataclass
class Objects:
    path: Path = field(default_factory=Path)
    output_dir: str = field(default_factory=str)
    settings: Settings = field(default_factory=Settings)
    model: YOLO = field(default_factory=YOLO)

    def __post_init__(self):
        self.output_dir = self.path.stem + ".jpg"
        self.model = YOLO(self.settings.YOLOModel)
        self.model.cuda()

    def detect_objects(self, img: np.ndarray) -> list[BoundingBox] | None:
        self.prediction = cast(list, self.model.predict(img, verbose=False))
        boxes = list()

        for result in self.prediction:

            for cls_id, confidence, (x1, y1, x2, y2) in zip(
                result.boxes.cls.tolist(),
                result.boxes.conf.tolist(),
                result.boxes.xyxy.tolist(),
            ):
                confidence = float(confidence * 100)

                if confidence >= self.settings.object_threshold:
                    cls_name = result.names[int(cls_id)]
                    box = BoundingBox(
                        confidence=round(confidence, 2),
                        model_version=self.settings.YOLOModel,
                        name=cls_name,
                        x1=int(x1),
                        y1=int(y1),
                        x2=int(x2),
                        y2=int(y2),
                    )

                    boxes.append(box)
        if len(boxes) == 0:
            boxes.append(
                BoundingBox(
                    0, self.settings.YOLOModel, "No Objects detected", 0, 0, 0, 0
                )
            )

        return boxes
