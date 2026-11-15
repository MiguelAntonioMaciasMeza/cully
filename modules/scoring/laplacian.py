"""
File: Cully/modules/scoring/laplacian.py
Description: Simple method that retrieves an image/crop's laplcian score
Author: Miguel Macias
Date: 2026-10-20
"""
import cv2
import numpy as np
from models.boundingbox import BoundingBox
import utils.image_ops as utils

def laplacian_sharpness(img: np.ndarray, box: BoundingBox, target: int = 256) -> float:
    """
    Given an image and a bounding box, determine it's laplacian value for
    given box and return it. target is the long side the crop is scaled to before scoring.
    """
    crop = utils.normalize_crop(img, box, target)
    return float(cv2.Laplacian(crop, cv2.CV_64F).var())