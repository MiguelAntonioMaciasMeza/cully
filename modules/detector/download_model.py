"""
File: Cully/modules/detector/download_model.py
Description: Downloads one official YOLO model into the models folder, with progress for the web app.
Standard library only, so it runs in either venv.
Run from Cully/modules:
    python -m detector.download_model yolo26s.pt [--folder PATH] [--progress-json]
Author: Miguel Macias
Date: 2026-11-21
"""

import argparse
import sys
import urllib.request
from pathlib import Path
from time import perf_counter

from config.yolo_models import OFFICIAL, RELEASE_URL, models_dir
from utils.progress import JSON_INTERVAL, emit, use_json

CHUNK = 1 << 20  # 1 MB


def download(name: str, folder: Path) -> Path:
    """Downloads name into folder through a temp file. Returns back the model's path"""
    target = folder / name
    folder.mkdir(parents=True, exist_ok=True)
    partial = folder / f".{name}.part"
    last = 0.0
    with urllib.request.urlopen(f"{RELEASE_URL}/{name}", timeout=30) as response, open(partial, "wb") as out:
        total = int(response.headers.get("Content-Length", 0))
        done = 0
        while chunk := response.read(CHUNK):
            out.write(chunk)
            done += len(chunk)
            if perf_counter() - last >= JSON_INTERVAL:
                #Sent in MB, the Run panel shows done/total
                emit("progress", step="download", done=done // 1_000_000, total=total // 1_000_000, file=name)
                last = perf_counter()
    #A cut-off download would fail deep inside torch later, so check it's whole
    if total and partial.stat().st_size != total:
        partial.unlink()
        raise SystemExit(f"[download_model.py] {name} download was cut off, try again")
    partial.rename(target)
    return target


def main():
    parser = argparse.ArgumentParser(description="Download an official YOLO model for the person detector")
    parser.add_argument("name", choices=sorted(OFFICIAL), help="model file name")
    parser.add_argument("--folder", type=Path, help="models folder (default: the object_detection models folder)")
    parser.add_argument("--progress-json", action="store_true", help="write progress as JSON lines on stdout")
    args = parser.parse_args()
    if args.progress_json:
        use_json(sys.stdout)
        sys.stdout = sys.stderr
    folder = args.folder or models_dir()

    start = perf_counter()
    emit("step_start", step="download")
    if (folder / args.name).is_file():
        result = f"{args.name} is already installed"
    else:
        path = download(args.name, folder)
        result = f"{args.name} downloaded ({path.stat().st_size / 1e6:.1f} MB)"
    seconds = perf_counter() - start
    print(f"[download_model.py] {result} ({seconds:.1f}s)")
    emit("step_end", step="download", result=result, seconds=round(seconds, 1))
    emit("done")


if __name__ == "__main__":
    main()
