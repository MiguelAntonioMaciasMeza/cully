"""
File: Cully/modules/utils/image_ops.py
Description: This file contains usable image operations that can be used within other 
Author: Miguel Macias
Date: 2026-10-25
"""
import cv2
import numpy as np
from models.boundingbox import BoundingBox



def normalize_crop(img: np.ndarray, box: BoundingBox, target: int = 256) -> np.ndarray:
    """
    Grabs the croped section of a image derived from BoundingBox. The cropped image 
    will then be turned to gray scale and normalized, which other modules can use for scoring.
    """
    # Detector boxes can hang past the frame, and negative indices would wrap around in numpy
    height, width = img.shape[:2]
    x1, x2 = max(0, box.x1), min(width, box.x2)
    y1, y2 = max(0, box.y1), min(height, box.y2)
    if x1 >= x2 or y1 >= y2:
        raise ValueError(f"[image_ops.py] box {box} has no area inside the {width}x{height} image")
    crop = img[y1:y2, x1:x2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    scale = target/max(gray.shape[:2])
    return  cv2.resize(gray,(0,0), fx=scale, fy=scale, interpolation = cv2.INTER_AREA)
    


def resize_image(img: np.ndarray, scale: float) -> np.ndarray:
    resizedImage = cv2.resize(img, (0,0), fx= scale, fy= scale)


    return resizedImage 