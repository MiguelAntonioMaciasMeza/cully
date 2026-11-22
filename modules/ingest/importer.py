"""
File: Cully/modules/ingest/importer.py
Description: Copies photos off a memory card into a folder on disk before they're scanned, so the
catalog points at files that stay put after the card is taken out or wiped.
Author: Miguel Macias
Date: 2026-11-21
"""

from datetime import date
from hashlib import sha256
from pathlib import Path

from ingest.exif_reader import SUPPORTED_SUFFIXES
from utils.files import copy_safely, folder_hashes
from utils.progress import track


def import_folder(root: str | Path, day: date | None = None) -> Path:
    """Returns back the folder inside root (the import_folder setting) that photos imported on day
    (default today) are copied into"""
    return Path(root).expanduser() / (day or date.today()).isoformat()


def card_photos(source: Path) -> list[Path]:
    """Returns back every photo in source and its sub-folders (cards keep them in DCIM/100CANON, ...)"""
    return sorted(
        p for p in source.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES and not p.name.startswith(".")
    )


def import_photos(source: Path, dest: Path, known_hashes: set[str], show_progress: bool = False) -> int:
    """Copies photos from source (and sub-folders) into dest, skipping ones already in the catalog
    (known_hashes) or already copied. Returns back how many were copied."""
    dest.mkdir(parents=True, exist_ok=True)
    #Photos already in dest count as known too, so importing the same card twice copies nothing
    seen = set(known_hashes) | folder_hashes(dest)

    copied = 0
    for path in track(card_photos(source), "import", show_progress, describe=lambda p: p.name):
        raw = path.read_bytes()
        image_hash = sha256(raw).hexdigest()  # same hash as Photo uses
        if image_hash in seen:
            continue
        copy_safely(path, dest, raw)
        seen.add(image_hash)
        copied += 1
    return copied
