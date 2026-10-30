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
    crop = img[box.y1:box.y2, box.x1:box.x2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    scale = target/max(gray.shape[:2])
    return  cv2.resize(gray,(0,0), fx=scale, fy=scale, interpolation = cv2.INTER_AREA)
    


def resize_image(img: np.ndarray, scale: float) -> np.ndarray:
    resizedImage = cv2.resize(img, (0,0), fx= scale, fy= scale)


    return resizedImage 