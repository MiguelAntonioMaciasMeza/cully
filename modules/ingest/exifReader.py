from typing import Any
from exif import Image as ExifLib
import exifread
from pathlib import Path
from datetime import datetime
import logging
from enum import Enum
import pprint

# logging.getLogger("exif").setLevel(logging.ERROR)

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".cr2"}


class uot(Enum):
    YEAR = 0
    MONTH = 1
    DAY = 2
    HOUR = 3
    MINUTE = 4
    SECOND = 5


class ExifReader:
    path: Path
    image_exif: dict[str, Any]
    date_time: datetime | None

    def __init__(self, path: Path):
        self.path = path

        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            print(f"Unsupported file type: {path.name}")
            return

        try:
            if suffix in (".jpg", ".jpeg"):
                self._read_jpg_exif(path)
            elif suffix == ".cr2":
                self._read_raw_exif(path)
            self._set_date_time()
        except Exception as e:
            # print(f"Missing file exif data from {path.name}: {e}")
            pass

    def _read_jpg_exif(self, path: Path):
        with open(path, "rb") as f:
            img = ExifLib(f)
        self.image_exif = {}
        

        try:
            self.image_exif["datetime_original"] = img.datetime_original
        except (AttributeError, KeyError):
            self.image_exif["datetime_original"] = None

        try:
            self.image_exif["subsecond_original"] = img.subsec_time_original
        except (AttributeError, KeyError):
            self.image_exif["subsecond_original"] = None

        try:
            self.image_exif["PixelXDimension"] = img.image_width
        except (AttributeError, KeyError):
            self.image_exif["PixelXDimension"] = None

        try:
            self.image_exif["PixelYDimension"] = img.image_height
        except (AttributeError, KeyError):
            self.image_exif["PixelYDimension"] = None

    def _read_raw_exif(self, path: Path):
        with open(path, "rb") as f:
            tags = exifread.process_file(f, details=False)

        # normalize to the same key names _set_date_time expects
        self.image_exif = {
            "datetime_original": str(tags.get("EXIF DateTimeOriginal", "")) or None,
            "subsecond_original": str(tags.get("EXIF SubSecTimeOriginal", "")) or None,
            "x_resolution": int(tags.get("EXIF PixelXDimension", "")) or None,
            "y_resolution": int(tags.get("EXIF PixelYDimension", "")) or None,
        }

    def _set_date_time(self):
        try:
            raw = self.image_exif.get("datetime_original")
            date_string = str(raw)
            raw = self.image_exif["subsecond_original"]
            sub_second = str(raw) if raw is not None else "0"
            date_string += "." + sub_second
            date_time = datetime.strptime(date_string, "%Y:%m:%d %H:%M:%S.%f")
            self.image_exif["datetime_original"] = date_time

        except (AttributeError, ValueError):
            self.date_time = None
            print("File is missing dateTime_original tag")

    def get_date_time(self, uot: uot) -> int:
        if self.date_time is None:
            return -1
        match uot.value:
            case 0:
                return self.date_time.year
            case 1:
                return self.date_time.month
            case 2:
                return self.date_time.day
            case 3:
                return self.date_time.hour
            case 4:
                return self.date_time.minute
            case 5:
                return self.date_time.second
        return -1

    def get_image_exif(self) -> dict[str, Any] | None:
        return self.image_exif
