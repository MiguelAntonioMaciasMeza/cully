"""
File: Cully/modules/ingest/directory_scanner.py
Description: Reads a directory and scans for images that can be ingested
Author: Miguel Macias
Date: 2026-09-11
"""

from ingest.exif_reader import SUPPORTED_SUFFIXES
from models.photo import Photo
from models.catalog import Catalog
from pathlib import Path
from utils.progress import track

from dataclasses import dataclass, field


@dataclass
class DirectoryScanner:
    catalog: Catalog = field(default_factory=Catalog)

    def __init__(self, catalog: Catalog):
        self.catalog = catalog

    def scan(self, directory: Path, show_progress: bool = False) -> list[Photo]:
        """Adds supported photos in directory to the catalog and returns them."""
        photos: list[Photo] = []
        paths = [p for p in sorted(directory.iterdir()) if p.suffix.lower() in SUPPORTED_SUFFIXES]
        for path in track(paths, "scan", show_progress, describe=lambda p: p.name):
            photo = Photo(path)
            self.catalog.insert_photo(photo)
            photos.append(photo)
        return photos
