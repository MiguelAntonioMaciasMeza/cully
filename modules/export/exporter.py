"""
File: Cully/modules/export/exporter.py
Description: Copies the photos marked keep out of Cully into a folder, one sub-folder per event, so the
choices can be used in any other app.
Author: Miguel Macias
Date: 2026-11-21
"""

from datetime import datetime
from hashlib import sha256
from pathlib import Path

from models.report_photo import ReportPhoto
from utils.files import copy_safely, folder_hashes
from utils.progress import track

NO_DATE = "No date"  # folder for kept photos in no event (no capture time)


def event_folder(photo: ReportPhoto) -> str:
    """Returns back the sub-folder name for photo's event, its start time like "2026-11-21 14-05" """
    if not photo.event_start:
        return NO_DATE
    #Colons aren't allowed in file names on every system
    return datetime.fromisoformat(photo.event_start).strftime("%Y-%m-%d %H-%M")


def kept_photos(photos: list[ReportPhoto]) -> list[ReportPhoto]:
    return [p for p in photos if p.culled_status == "keep"]


def export_keepers(photos: list[ReportPhoto], dest: Path, show_progress: bool = False) -> int:
    """Copies the kept photos into dest/<event>/, skipping ones already there.
    Returns back how many were copied"""
    copied = 0
    seen: dict[Path, set[str]] = {}  # each event folder's photo hashes, read once
    for photo in track(kept_photos(photos), "export", show_progress, describe=lambda p: Path(p.image_path).name):
        source = Path(photo.image_path)
        if not source.is_file():
            print(f"[exporter.py] Skipped, file is gone: {source}")
            continue
        folder = dest / event_folder(photo)
        if folder not in seen:
            seen[folder] = folder_hashes(folder)
        raw = source.read_bytes()
        image_hash = sha256(raw).hexdigest()
        #Exporting again only copies new keepers
        if image_hash in seen[folder]:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        copy_safely(source, folder, raw)
        seen[folder].add(image_hash)
        copied += 1
    return copied
