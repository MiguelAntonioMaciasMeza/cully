from typing import Any
from exif import Image as ExifLib
import exifread
from pathlib import Path
from datetime import datetime
import logging
from enum import Enum
from typing import cast
import rawpy
import cv2
DEBUG = False
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
        self.image_exif = {"datetime_original": None}
        self.date_time = None

        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            if DEBUG:
                print(f"[exif_reader.py]Unsupported file type: {path.name}")
            return

        try:
            if suffix in (".jpg", ".jpeg"):
                self._read_jpg_exif(path)
            elif suffix == ".cr2":
                if DEBUG:
                    print("[exif_reader.py]Reading raw exif")
                self._read_raw_exif(path)
            self._set_date_time()
        except Exception as e:
            if DEBUG:
                print(f"[exifreader.py]Missing file exif data from {path.name}: {e}")
            pass

    def _read_jpg_exif(self, path: Path):
        with open(path, "rb") as f:
            img = ExifLib(f)  
            if img.has_exif:
                self._get_exif_data(img,"datetime_original")
                self._get_exif_data(img,"subsec_time_original")
                self.image_exif["camera_model"] = self._clean_model(img.get("model"))
        if DEBUG:
            print(f"[exif_reader.py]Reading: {path}")
        img = cv2.imread(str(path))
        if img is not None:
            # OpenCV shape is (height, width)
            self.image_exif["x_resolution"] = img.shape[1]
            self.image_exif["y_resolution"] = img.shape[0]

    def _read_raw_exif(self, path: Path):
        with open(path, "rb") as f:
            tags = exifread.process_file(f, details=False)
            # normalize to the same key names _set_date_time expects
            self.image_exif = {}

            self.image_exif["datetime_original"] = tags.get("EXIF DateTimeOriginal")
            self.image_exif["subsecond_original"] = str(tags.get("EXIF SubSecTimeOriginal"))
            self.image_exif["camera_model"] = self._clean_model(tags.get("Image Model"))
            raw_img = rawpy.imread(str(path))
            if raw_img is not None:
                img_sizes = raw_img.sizes
                self.image_exif["x_resolution"] = img_sizes.crop_width
                self.image_exif["y_resolution"] = img_sizes.crop_height
            
    @staticmethod
    def _clean_model(raw: Any) -> str | None:
        """Camera model as trimmed text, None if missing."""
        if raw is None:
            return None
        model = str(raw).strip(" \x00")
        return model or None

    def _set_date_time(self):
        try:
            
            raw = self.image_exif.get("datetime_original")
            if raw is not None:
                date_string = str(raw)
                # RAWs store subseconds as subsecond_original, JPGs as subsec_time_original;
                # a missing tag reads as None/-1/"None", so anything non-numeric counts as 0
                raw = self.image_exif.get("subsecond_original", self.image_exif.get("subsec_time_original"))
                sub_second = str(raw) if str(raw).isdigit() else "0"
                date_string += "." + sub_second
                date_time = datetime.strptime(date_string, "%Y:%m:%d %H:%M:%S.%f")
                self.image_exif["datetime_original"] = date_time
                self.date_time = date_time

        except (AttributeError, ValueError):
            self.date_time = None
            self.image_exif["datetime_original"] = None
            if DEBUG:
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

    def _get_exif_data(self, exif: ExifLib, tag: str):
        try:
            self.image_exif[tag] = exif.get(tag, -1)
        except (AttributeError, ValueError):
            self.image_exif[tag] = None

    def get_image_exif(self) -> dict[str, Any] | None:
        return self.image_exif
