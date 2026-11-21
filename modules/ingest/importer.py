"""
File: Cully/modules/ingest/importer.py
Description: Copies photos off a memory card into a folder on disk before they're scanned, so the
catalog points at files that stay put after the card is taken out or wiped.
Author: Miguel Macias
Date: 2026-11-21
"""

import shutil
from datetime import date
from hashlib import sha256
from pathlib import Path

from ingest.exif_reader import SUPPORTED_SUFFIXES
from utils.progress import track

# Where imports land, one folder per day. A constant until the settings page can change it
IMPORT_ROOT = Path.home() / "Pictures" / "Cully"


def import_folder(day: date | None = None) -> Path:
    """Returns back the folder photos imported on day (default today) are copied into"""
    return IMPORT_ROOT / (day or date.today()).isoformat()


def card_photos(source: Path) -> list[Path]:
    """Returns back every photo in source and its sub-folders (cards keep them in DCIM/100CANON, ...)"""
    return sorted(
        p for p in source.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES and not p.name.startswith(".")
    )


def _free_name(dest: Path, name: str) -> Path:
    """Returns back dest/name, or dest/name_1, name_2, ... when that's taken"""
    target = dest / name
    stem, suffix = target.stem, target.suffix
    number = 1
    while target.exists():
        target = dest / f"{stem}_{number}{suffix}"
        number += 1
    return target


def import_photos(source: Path, dest: Path, known_hashes: set[str], show_progress: bool = False) -> int:
    """Copies photos from source (and sub-folders) into dest, skipping ones already in the catalog
    (known_hashes) or already copied. Returns back how many were copied."""
    dest.mkdir(parents=True, exist_ok=True)
    #Photos already in dest count as known too, so importing the same card twice copies nothing
    seen = set(known_hashes)
    for existing in dest.iterdir():
        if existing.is_file() and existing.suffix.lower() in SUPPORTED_SUFFIXES:
            seen.add(sha256(existing.read_bytes()).hexdigest())

    copied = 0
    for path in track(card_photos(source), "import", show_progress, describe=lambda p: p.name):
        raw = path.read_bytes()
        image_hash = sha256(raw).hexdigest()  # same hash as Photo uses
        if image_hash in seen:
            continue
        target = _free_name(dest, path.name)
        #Write to a temp name first, so a card pulled mid-copy never leaves half a photo behind
        partial = target.with_name(f".{target.name}.part")
        partial.write_bytes(raw)
        shutil.copystat(path, partial)  # keep the file times, some tools sort by them
        partial.rename(target)
        seen.add(image_hash)
        copied += 1
    return copied
