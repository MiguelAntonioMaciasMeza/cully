"""
File: Cully/modules/config/yolo_models.py
Description: The person detector models Cully offers: official YOLO26 and YOLO11 models (downloaded
on request) plus any custom trained .pt file put in the models folder. Light, no torch.
Author: Miguel Macias
Date: 2026-11-21
"""

import re
from pathlib import Path

from config.config import Config

RELEASE_URL = "https://github.com/ultralytics/assets/releases/download/v8.4.0"  # same release Ultralytics uses
MODEL_NAME = re.compile(r"[\w.-]+\.pt")  # a plain file name, never a path

SIZES = {
    "n": ("nano", "Fastest. Can miss small or far away people."),
    "s": ("small", "Fast, finds more small people than nano."),
    "m": ("medium", "Balanced speed and accuracy."),
    "l": ("large", "Slower, more accurate."),
    "x": ("extra large", "Slowest and most accurate. Best with a graphics card."),
}
FAMILIES = {"yolo26": "YOLO26", "yolo11": "YOLO11"}  # newest first

# name -> (family, size, note)
OFFICIAL = {
    f"{prefix}{size}.pt": (family, label, note)
    for prefix, family in FAMILIES.items()
    for size, (label, note) in SIZES.items()
}


def models_dir(config: Config | None = None) -> Path:
    """Returns back the folder the person detector loads its .pt files from"""
    return Path((config or Config()).models_path) / "object_detection"


def is_model_name(name: str) -> bool:
    return bool(MODEL_NAME.fullmatch(name))


def list_models(folder: Path) -> dict:
    """Returns back the official models (installed or not) and the custom ones found in folder"""
    def size_mb(path: Path) -> float | None:
        return round(path.stat().st_size / 1e6, 1) if path.is_file() else None

    official = [
        {"name": name, "family": family, "size": size, "note": note, "mb": size_mb(folder / name)}
        for name, (family, size, note) in OFFICIAL.items()
    ]
    custom = []
    if folder.is_dir():
        custom = [
            {"name": p.name, "mb": size_mb(p)} for p in sorted(folder.glob("*.pt"))
            if p.name not in OFFICIAL and is_model_name(p.name)
        ]
    return {"folder": str(folder), "official": official, "custom": custom}
