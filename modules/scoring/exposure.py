"""
File: Cully/modules/scoring/exposure.py
Description: Measures a photo's exposure and whole-frame sharpness, and finds exposure problems in a burst.
A problem is a penalty, like closed eyes: the photo ranks below good frames and can't be a candidate.
    -Black / white frame: nearly every pixel crushed or blown out
    -Face too dark / too bright: a face's mean brightness outside the face limits
    -Off from its burst: brighter or darker than the burst's median by more than burst_stops
Thresholds come from the exposure settings, picked from the test sets (see the handoff).
Author: Miguel Macias
Date: 2026-11-21
"""

import math
from statistics import median

import cv2
import numpy as np

from models.photo_metrics import PhotoMetrics

FRAME_SIZE = 1000  # long side frames are scaled to, so sharpness compares across file sizes
CLIP_LEVEL = 250  # at or above this a pixel is blown out
CRUSH_LEVEL = 5  # at or below this a pixel is black
GAMMA = 2.2  # one stop changes a pixel value by about 2 ** (1 / 2.2), x1.37


def frame_metrics(image_hash: str, img: np.ndarray) -> PhotoMetrics:
    """Returns back the brightness, % clipped, % crushed and sharpness of a whole BGR image."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    scale = FRAME_SIZE / max(gray.shape[:2])
    if scale < 1:
        gray = cv2.resize(gray, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return PhotoMetrics(
        image_hash,
        float(gray.mean()),
        float((gray >= CLIP_LEVEL).mean() * 100),
        float((gray <= CRUSH_LEVEL).mean() * 100),
        float(cv2.Laplacian(gray, cv2.CV_64F).var()),
    )


def face_brightness(img: np.ndarray, box: tuple[int, int, int, int], scale: float) -> float | None:
    """Mean brightness of a face box (full-size coordinates) in img, which is scale times full size.
    None if the box has no area inside the image."""
    height, width = img.shape[:2]
    x1, y1, x2, y2 = (round(v * scale) for v in box)
    x1, x2 = max(0, x1), min(width, x2)
    y1, y2 = max(0, y1), min(height, y2)
    if x1 >= x2 or y1 >= y2:
        return None
    return float(cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY).mean())


def stops_from(value: float, reference: float) -> float:
    """How many stops brighter (+) or darker (-) value is than reference."""
    return GAMMA * math.log2(max(value, 0.5) / max(reference, 0.5))


def exposure_issues(
    metrics: dict[str, PhotoMetrics], faces: dict[str, list[float]], settings: dict
) -> dict[str, str | None]:
    """Returns back each burst photo's exposure problem, None when it's fine.
    metrics: the burst's photos, faces: each photo's face brightness values, settings: the exposure group."""
    issues: dict[str, str | None] = {}
    # The whole burst being dark (a night scene) isn't a problem, only frames that stand out are
    burst_brightness = median(m.brightness for m in metrics.values()) if len(metrics) > 1 else None
    for image_hash, m in metrics.items():
        issues[image_hash] = None
        if not settings["check"]:
            continue
        if m.crushed >= settings["black_frame"]:
            issues[image_hash] = "black frame"
        elif m.clipped >= settings["white_frame"]:
            issues[image_hash] = "white frame"
        elif any(b < settings["face_dark"] for b in faces.get(image_hash, [])):
            issues[image_hash] = "face too dark"
        elif any(b > settings["face_bright"] for b in faces.get(image_hash, [])):
            issues[image_hash] = "face too bright"
        elif burst_brightness is not None and burst_brightness >= 1:
            stops = stops_from(m.brightness, burst_brightness)
            if abs(stops) > settings["burst_stops"]:
                issues[image_hash] = f"{abs(stops):.1f} stops {'over' if stops > 0 else 'under'} burst"
    return issues
