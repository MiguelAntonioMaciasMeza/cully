from ultralytics import YOLO
from ultralytics.engine.results import Results
from dataclasses import dataclass, field
from config.config import Config
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
    config: Config = field(default_factory=Config)
    # No default: a bare YOLO() would load Ultralytics' default model from the current folder
    model: YOLO = field(init=False, repr=False)

    def __post_init__(self):
        self.output_dir = self.path.stem + ".jpg"
        # Ultralytics downloads official weights to this path if the file is missing
        model_path = Path(self.config.models_path) / "object_detection" / self.settings.YOLOModel
        self.model = YOLO(model_path)
        #Faces are only searched inside person boxes, a model without people can't feed the later steps
        if "person" not in self.model.names.values():
            raise SystemExit(f"[one_shot_object.py] {self.settings.YOLOModel} has no 'person' class, pick another model in Settings")
        self.model.to(self.settings.hardware["device"])

    def detect_objects(self, img: np.ndarray,inverse_scale: float) -> list[BoundingBox] | None:
        self.prediction = cast(list, self.model.predict(img, verbose=False))
        boxes = list()
        for result in self.prediction:

            for cls_id, confidence, (x1, y1, x2, y2) in zip(
                result.boxes.cls.tolist(),
                result.boxes.conf.tolist(),
                result.boxes.xyxy.tolist(),
            ):
                confidence = float(confidence * 100)
                cls_name = result.names[int(cls_id)]
                # People get their own, lower threshold: a missed person hides their face from
                # every later step, while a false one is dropped later by face detection
                threshold = (
                    self.settings.detection["person_threshold"]
                    if cls_name == "person"
                    else self.settings.object_threshold
                )

                if confidence >= threshold:
                    box = BoundingBox(
                        confidence=round(confidence, 2),
                        model_version=self.settings.YOLOModel,
                        name=cls_name,
                        x1=int(x1* inverse_scale),
                        y1=int(y1* inverse_scale),
                        x2=int(x2* inverse_scale),
                        y2=int(y2* inverse_scale),
                    )

                    boxes.append(box)
        if len(boxes) == 0:
            boxes.append(
                BoundingBox(
                    0, self.settings.YOLOModel, "No Objects detected", 0, 0, 0, 0
                )
            )

        return boxes
