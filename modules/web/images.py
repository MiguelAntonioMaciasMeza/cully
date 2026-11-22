"""
File: Cully/modules/web/images.py
Description: Makes and caches the images the web app serves: thumbnails, previews and face crops.
Each is made once, on first request, and kept by image hash (faces by image hash and box). OpenCV only, RAW goes through utils/read_image.py.
Author: Miguel Macias
Date: 2026-11-17
"""

from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

from utils.make_thumbnail import make_thumbnail
from utils.read_image import read_image

FACE_MARGIN = 0.15  # extra room around a face box, as a share of its size
JPEG_QUALITY = 90


def _temp_name(target: Path) -> Path:
    """A unique file next to target. Keeps .jpg so OpenCV knows the format."""
    return target.with_name(f".{target.stem}-{uuid4().hex}.jpg")


def cached_resize(source: Path, target: Path, size: int) -> Path | None:
    """Returns target, making it first if needed. None if source can't be read."""
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    # Written under a temp name then renamed, so a second request never sees half a file
    temp = _temp_name(target)
    try:
        if not make_thumbnail(source, temp, size):
            return None
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    return target


def read_full(source: Path) -> np.ndarray | None:
    """Reads a photo at full size, RAW included. None if it can't be read."""
    # Same reader as the pipeline, so face boxes line up with the photo
    return read_image(source)


def cached_face(source: Path, box: tuple[int, int, int, int], target: Path) -> Path | None:
    """Returns target, cropping the face box (plus a margin) out of source first if needed."""
    if target.exists():
        return target
    img = read_full(source)
    if img is None:
        return None
    x1, y1, x2, y2 = box
    pad_x, pad_y = int((x2 - x1) * FACE_MARGIN), int((y2 - y1) * FACE_MARGIN)
    # Clamp to the frame, negative indices would wrap around in numpy
    height, width = img.shape[:2]
    x1, x2 = max(0, x1 - pad_x), min(width, x2 + pad_x)
    y1, y2 = max(0, y1 - pad_y), min(height, y2 + pad_y)
    if x1 >= x2 or y1 >= y2:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = _temp_name(target)
    try:
        if not cv2.imwrite(str(temp), img[y1:y2, x1:x2], [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]):
            return None
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    return target
