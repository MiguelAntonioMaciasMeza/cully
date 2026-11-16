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

from dataclasses import dataclass, field


@dataclass
class DirectoryScanner:
    catalog: Catalog = field(default_factory=Catalog)

    def __init__(self, catalog: Catalog):
        self.catalog = catalog

    def scan(self, directory: Path):
        photos = list()
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            photo = Photo(path)
            self.catalog.insert_photo(photo)
            photos.append(photos)
