from rembg import remove, new_session
from dataclasses import dataclass
from pathlib import Path
from models.photo import Photo
from config.settings import Settings
import cv2
import numpy as np
from PIL import Image as PILImage
from typing import Any
import pprint


def build_saliency_session(settings: Settings):
    return new_session(
        settings.saliency_model,
        providers=[
            (
                "CUDAExecutionProvider",
                {
                    "cudnn_conv_algo_search": "HEURISTIC",
                    "arena_extend_strategy": "kNextPowerOfTwo",  # default, but explicit
                },
            ),
        ],
    )


@dataclass
class SailencyDetector:
    x1, x2, y1, y2 = 0, 0, 0, 0
    image: Photo
    output_dir: str
    settings: Settings
    session: Any

    def __post_init__(self):
        if not Path(self.output_dir).exists():
            Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        self.output_dir += self.image.path_to_photo.stem + ".jpg"

    def remove_background(self, img: np.ndarray):
        if self.settings.saliency_scale == 1:
            salient = remove(img, session=self.session)
            if not isinstance(salient, np.ndarray):
                raise TypeError(f"Expected ndarray from remove got {type(salient)} ")
            cv2.imwrite(self.output_dir, salient)
            pprint.pprint(salient)

        # Native model input
        elif self.settings.saliency_scale - 1:
            img = cv2.resize(img, (320, 320))
            salient = remove(img, session=self.session)
            if not isinstance(salient, np.ndarray):
                raise TypeError(f"Expected ndarray from remove got {type(salient)} ")
            cv2.imwrite(self.output_dir, salient)

        # scale to any other res
        else:
            scale = self.settings.saliency_scale
            img = cv2.resize(img, (0, 0), fx=scale, fy=scale)
            salient = remove(img, session=self.session)
            if not isinstance(salient, np.ndarray):
                raise TypeError(f"Expected ndarray from remove got {type(salient)} ")
            cv2.imwrite(self.output_dir, salient)
