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

model = YOLO("yolo26l.pt")
model.cuda()
print(model.device)


@dataclass
class Objects:
    path: Path = field(default_factory=Path)
    output_dir: str = field(default_factory=str)
    settings: Settings = field(default_factory=Settings)

    def __post_init__(self):
        self.output_dir = self.path.stem + ".jpg"

    def detect_objects(self, img: np.ndarray) -> defaultdict | None:
        self.prediction = cast(list, model.predict(img, verbose=False))
        objects = defaultdict(list)

        for result in self.prediction:
            if result.boxes is None or result.boxes.cls is None:
                return None

            for cls_id, confidence, (x1, y1, x2, y2) in zip(
                result.boxes.cls.tolist(),
                result.boxes.conf.tolist(),
                result.boxes.xyxy.tolist(),
            ):
                confidence = float(confidence * 100)

                if confidence >= self.settings.object_threshold:
                    cls_name = result.names[int(cls_id)]
                    box = BoundingBox(
                        confidence=round(confidence,2),
                        model_version= self.settings
                        name = cls_name,
                        x1=int(x1),
                        y1=int(y1),
                        x2=int(x2),
                        y2=int(y2),
                    )

                    objects[cls_name].append(box)

        return objects if objects else None


object_instance = Objects()
print(object_instance.settings.object_threshold)
directory = Path("/home/ripley/Documents/FinalRepo/Unused Images/")
catalog = Catalog()
size = 0
for images in directory.glob("*.jpg"):
    size += 1
    image_tag = Photo(images)
    img = cv2.imread(images)
    img = cv2.resize(img, (640, 640))
    if img is None:
        raise FileExistsError(f"Could not find file {images}")

    catalog.insert_photo(image_tag)

catalog.show_row_table_all()
print(size)


