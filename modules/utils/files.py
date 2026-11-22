"""
File: Cully/modules/utils/files.py
Description: Copying photos safely, shared by the card import and the export: a free file name on a
clash, and a temp name until the copy is whole.
Author: Miguel Macias
Date: 2026-11-21
"""

import shutil
from hashlib import sha256
from pathlib import Path

from ingest.exif_reader import SUPPORTED_SUFFIXES


def free_name(dest: Path, name: str) -> Path:
    """Returns back dest/name, or dest/name_1, name_2, ... when that's taken"""
    target = dest / name
    stem, suffix = target.stem, target.suffix
    number = 1
    while target.exists():
        target = dest / f"{stem}_{number}{suffix}"
        number += 1
    return target


def copy_safely(source: Path, dest: Path, raw: bytes | None = None) -> Path:
    """Copies source into the folder dest under a free name. Returns back the new file.
    raw is source's bytes, when the caller already read them"""
    target = free_name(dest, source.name)
    #Write to a temp name first, so a pulled card or a crash never leaves half a photo behind
    partial = target.with_name(f".{target.name}.part")
    partial.write_bytes(source.read_bytes() if raw is None else raw)
    shutil.copystat(source, partial)  # keep the file times, some tools sort by them
    partial.rename(target)
    return target


def folder_hashes(folder: Path) -> set[str]:
    """Returns back the sha256 of every photo directly in folder (none if it doesn't exist)"""
    if not folder.is_dir():
        return set()
    return {
        sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    }
