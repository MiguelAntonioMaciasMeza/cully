"""
File: Cully/modules/utils/read_image.py
Description: One place to read a photo into a BGR array, RAW (CR2, NEF) included. Every step uses it,
so boxes found on one read line up with the next.
RAW files are read from the JPEG the camera embeds in them: full size and fast.
Author: Miguel Macias
Date: 2026-11-21
"""

from pathlib import Path

import cv2
import numpy as np
import rawpy

RAW_SUFFIXES = {".cr2", ".nef"}  # Canon, Nikon


def read_image(path: Path | str | None, flags: int = cv2.IMREAD_COLOR) -> np.ndarray | None:
    """Reads a photo as BGR. None if it's missing or can't be read."""
    if path is None:
        return None
    path = Path(path)
    if not path.is_file():
        return None
    if path.suffix.lower() in RAW_SUFFIXES:
        return _read_raw(path, flags)
    return cv2.imread(str(path), flags)


def _read_raw(path: Path, flags: int) -> np.ndarray | None:
    """Reads the embedded preview of a RAW file, or decodes it if there isn't one."""
    try:
        with rawpy.imread(str(path)) as raw:
            try:
                thumb = raw.extract_thumb()
            except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
                thumb = None

            if thumb is not None and thumb.format == rawpy.ThumbFormat.JPEG:
                # imdecode turns it upright from the JPEG's own orientation tag
                return cv2.imdecode(np.frombuffer(thumb.data, np.uint8), flags)
            if thumb is not None and thumb.format == rawpy.ThumbFormat.BITMAP:
                return cv2.cvtColor(thumb.data, cv2.COLOR_RGB2BGR)
            # No usable preview, decode the sensor data instead (slow)
            return cv2.cvtColor(raw.postprocess(), cv2.COLOR_RGB2BGR)
    except (rawpy.LibRawError, OSError) as e:
        print(f"[read_image.py] Could not read {path}: {e}")
        return None
