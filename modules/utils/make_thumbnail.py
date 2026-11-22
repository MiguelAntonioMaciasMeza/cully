"""
File: Cully/modules/utils/make_thumbnail.py
Description: util module that allows us to make a thumbnail for report. Really usefull
as most modern cameras taken images that are 20+ megapixels 
Author: Miguel Macias
Date: 2026-11-16
"""
from pathlib import Path
import cv2
from utils.read_image import read_image


def make_thumbnail(source: Path, target: Path, size:int=360) -> bool:
    """Writes a small JPEG of source to target. Returns False if source can't be read."""
    if target.exists():
        return True
    if not source.is_file():
        return False
    # Decode at 1/4 size, the photos are far bigger than a thumbnail
    img = read_image(source, cv2.IMREAD_REDUCED_COLOR_4)
    if img is None:
        return False
    h, w = img.shape[:2]
    scale = size / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return cv2.imwrite(str(target), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
