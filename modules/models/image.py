from dataclasses import dataclass, field
from typing import Any
from pathlib import Path
from ingest.exifReader import ExifReader
from hashlib import sha256


@dataclass
class Image:
    path_to_image: Path
    exif_data: dict[str, Any] | None = field(default_factory=dict)
    image_hash: str | None = field(init=False)
    scores: dict = field(default_factory=dict)
    cached: bool = False
    
    def __post_init__(self):
        raw = self.path_to_image.read_bytes()
        self.image_hash = sha256(raw).hexdigest()
        self.exif_data = ExifReader(self.path_to_image).get_image_exif()
