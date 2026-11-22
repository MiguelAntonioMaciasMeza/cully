"""
File: Cully/modules/export/__main__.py
Description: Exports the kept photos from the command line. Needs no models, so it runs in either venv.
Run from Cully/modules:
    python -m export [DEST] [--catalog PATH] [--settings PATH] [--progress] [--progress-json]
DEST defaults to the export_folder setting.
Author: Miguel Macias
Date: 2026-11-21
"""

import argparse
import sys
from pathlib import Path
from time import perf_counter

from config.settings import Settings
from export.exporter import export_keepers, kept_photos
from models.catalog import Catalog
from utils.progress import emit, use_json


def main():
    parser = argparse.ArgumentParser(description="Copy the photos marked keep into a folder per event")
    parser.add_argument("dest", type=Path, nargs="?", help="folder to export into (default: the export_folder setting)")
    parser.add_argument("--catalog", type=Path, help="catalog file (default: the main catalog)")
    parser.add_argument("--settings", type=Path, help="settings file (default: ~/.config/cully/settings.json)")
    parser.add_argument("-p", "--progress", action="store_true", help="show a live progress line")
    parser.add_argument("--progress-json", action="store_true", help="write progress as JSON lines on stdout")
    args = parser.parse_args()

    #Same deal as main.py: stdout carries JSON only, prints go to stderr
    if args.progress_json:
        use_json(sys.stdout)
        sys.stdout = sys.stderr
    if args.dest is None:
        settings = Settings(path=args.settings) if args.settings else Settings()
        args.dest = Path(settings.export_folder)
    dest = args.dest.expanduser()

    catalog = Catalog(str(args.catalog)) if args.catalog else Catalog()
    photos = catalog.get_report_photos()
    catalog.close()

    start = perf_counter()
    emit("step_start", step="export")
    copied = export_keepers(photos, dest, args.progress or args.progress_json)
    result = f"{copied} of {len(kept_photos(photos))} kept photos copied to {dest}"
    seconds = perf_counter() - start
    print(f"[__main__.py] export: {result} ({seconds:.1f}s)")
    emit("step_end", step="export", result=result, seconds=round(seconds, 1))
    emit("done")


if __name__ == "__main__":
    main()
