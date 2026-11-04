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

def laplacian_sharpness(img: np.ndarray, box: BoundingBox) -> float:
    """
    Given an image and a bounding box, determine it's laplacian value for
    given box and return it
    """
    crop = utils.normalize_crop(img, box)
    return float(cv2.Laplacian(crop, cv2.CV_64F).var())