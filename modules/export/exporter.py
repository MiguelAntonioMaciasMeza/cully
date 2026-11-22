"""
File: Cully/modules/export/exporter.py
Description: Copies the photos marked keep out of Cully into a folder, one sub-folder per event, so the
choices can be used in any other app.
Author: Miguel Macias
Date: 2026-11-21
"""

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from ingest.exif_reader import SUPPORTED_SUFFIXES
from models.report_photo import ReportPhoto
from utils.files import copy_safely
from utils.progress import track
from utils.xmp import write_rating

NO_DATE = "No date"  # folder for kept photos in no event (no capture time)
RECORD = ".cully-export.json"  # in each event folder: original photo hash -> exported file name


def event_folder(photo: ReportPhoto) -> str:
    """Returns back the sub-folder name for photo's event, its start time like "2026-11-21 14-05" """
    if not photo.event_start:
        return NO_DATE
    #Colons aren't allowed in file names on every system
    return datetime.fromisoformat(photo.event_start).strftime("%Y-%m-%d %H-%M")


def kept_photos(photos: list[ReportPhoto]) -> list[ReportPhoto]:
    return [p for p in photos if p.culled_status == "keep"]


def _read_record(folder: Path) -> dict[str, str]:
    """Returns back what was exported to folder before. Untouched photos found there count too"""
    record = {}
    if (folder / RECORD).is_file():
        record = json.loads((folder / RECORD).read_text())
    #Exports from before the record existed: match the files by content
    if folder.is_dir():
        known = set(record.values())
        for path in folder.iterdir():
            if path.is_file() and path.name not in known and path.suffix.lower() in SUPPORTED_SUFFIXES:
                record[sha256(path.read_bytes()).hexdigest()] = path.name
    return record


def export_keepers(photos: list[ReportPhoto], dest: Path, rating: int, show_progress: bool = False) -> tuple[int, int]:
    """Copies the kept photos into dest/<event>/ and writes their rating for darktable and Lightroom.
    Photos already there only get their rating rewritten. Returns back (copied, rated)"""
    copied = rated = 0
    records: dict[Path, dict[str, str]] = {}  # each event folder's record, read once
    for photo in track(kept_photos(photos), "export", show_progress, describe=lambda p: Path(p.image_path).name):
        source = Path(photo.image_path)
        folder = dest / event_folder(photo)
        if folder not in records:
            records[folder] = _read_record(folder)
        record = records[folder]

        #Ratings change the JPEG copy, so exported photos are found through the record, not by content
        exported = record.get(photo.image_hash)
        if exported and (folder / exported).is_file():
            target = folder / exported
        elif source.is_file():
            folder.mkdir(parents=True, exist_ok=True)
            target = copy_safely(source, folder)
            record[photo.image_hash] = target.name
            (folder / RECORD).write_text(json.dumps(record, indent=1))
            copied += 1
        else:
            print(f"[exporter.py] Skipped, file is gone: {source}")
            continue

        if write_rating(target, rating):
            rated += 1
        else:
            print(f"[exporter.py] Rating not written for {target.name}, it has a sidecar or XMP Cully can't change")
    return copied, rated
