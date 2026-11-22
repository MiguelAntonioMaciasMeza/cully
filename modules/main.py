"""
File: Cully/modules/main.py
Description: Runs the whole Cully pipeline on a folder: scan, objects, faces, landmarks,
(embeddings), sharpness and burst ranking. Each step only does photos it hasn't done yet,
except sharpness and ranking, which redo the whole catalog.
Run from Cully/modules with venv-main:
    python main.py <folder> [--catalog NAME|PATH] [--embeddings] [--steps scan,objects,...] [--progress]
    [--progress-json] [--import-to DEST] [--settings PATH]
    python main.py --redo objects|faces [--all] [--catalog PATH] [--settings PATH]
With --import-to, photos in <folder> and its sub-folders (a memory card) are copied to DEST first,
and DEST is scanned instead. --redo deletes the objects (or faces) of every photo made with older
settings, then the steps after it redo them. With --all, every processed photo is redone, settings
changed or not. Keep/reject choices are never touched.
Author: Miguel Macias
Date: 2026-11-16
"""

import io
import os
import sys

# With --progress-json, stdout carries JSON only: keep a copy of it, then point stdout at stderr so
# prints, library chatter and C-level writes can't break the stream. Done before the heavy imports.
JSON_OUT = None
if "--progress-json" in sys.argv:
    JSON_OUT = os.fdopen(os.dup(1), "w")
    os.dup2(2, 1)
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)  # stderr-like, so log lines show up in order

# triton has to be loaded before mediapipe or it segfaults (see tests/pipeline/pipeline_steps_test.py)
import triton  # noqa: F401, E402

import argparse
from pathlib import Path
from time import perf_counter

from config.config import Config
from config.settings import Settings
from ingest.directory_scanner import DirectoryScanner
from ingest.importer import import_photos
from models.catalog import Catalog, resolve_catalog_path
# torch (YOLO) has to load before TensorFlow (DeepFace) or the process crashes, so objects goes first
from pipeline.objects import ObjectStep
from pipeline.faces import FaceStep
from pipeline.landmarks import LandmarkStep
from pipeline.sharpness import SharpnessStep
from pipeline.burst_ranking import BurstRankStep
from utils.progress import emit, use_json
from utils.steps import CATALOG_STEPS, PHOTO_STEPS, STEPS, default_steps, fingerprint


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Cully pipeline on a folder of photos.")
    parser.add_argument("folder", type=Path, nargs="?", help="folder of photos to scan (not needed for --redo)")
    parser.add_argument("--catalog", help="catalog name (shoot1 -> <catalog folder>/shoot1.db, made if new) or file path. Default: the main catalog")
    parser.add_argument("--embeddings", action="store_true", help="also embed faces (ranking doesn't need it)")
    parser.add_argument("--steps", help=f"comma separated subset of: {','.join(STEPS)}")
    parser.add_argument("-p", "--progress", action="store_true", help="show a live progress line for each step")
    parser.add_argument("--import-to", type=Path, help="copy the folder's photos (and its sub-folders') here first, then scan this folder")
    parser.add_argument("--redo", choices=PHOTO_STEPS, help="redo this step (and the ones after it) for photos made with older settings")
    parser.add_argument("--all", action="store_true", help="with --redo: redo every processed photo, not just out-of-date ones")
    parser.add_argument("--settings", type=Path, help="settings file to use (default: ~/.config/cully/settings.json)")
    parser.add_argument("--progress-json", action="store_true",
                        help="write progress as JSON lines on stdout, everything else goes to stderr")
    args = parser.parse_args()

    if args.steps:
        args.steps = [s.strip() for s in args.steps.split(",")]
        unknown = set(args.steps) - set(STEPS)
        if unknown:
            parser.error(f"unknown steps: {', '.join(sorted(unknown))}")
    else:
        args.steps = default_steps(args.embeddings, importing=args.import_to is not None, redo=args.redo is not None)
    if "import" in args.steps and args.import_to is None:
        parser.error("the import step needs --import-to DEST")
    if args.all and args.redo is None:
        parser.error("--all needs --redo objects|faces")
    if "redo" in args.steps and args.redo is None:
        parser.error("the redo step needs --redo objects|faces")
    if ("scan" in args.steps or "import" in args.steps) and args.folder is None:
        parser.error("a folder is needed for the scan and import steps")
    return args


def main():
    args = parse_args()
    if ("scan" in args.steps or "import" in args.steps) and not args.folder.is_dir():
        raise SystemExit(f"[main.py] Not a folder: {args.folder}")
    #After an import, the copies are what gets scanned
    scan_folder = args.import_to or args.folder

    # One Settings, Config and Catalog shared by every step
    settings = Settings(path=args.settings) if args.settings else Settings()
    config = Config()
    catalog_path = resolve_catalog_path(args.catalog)
    is_new = not Path(catalog_path).is_file()
    catalog = Catalog(catalog_path)
    print(f"[main.py] Catalog: {catalog.catalog_path}{' (new)' if is_new else ''}")
    #First run since tracking existed: what's already there counts as made with these settings
    if catalog.start_tracking({step: fingerprint(settings, step) for step in PHOTO_STEPS + CATALOG_STEPS}):
        print("[main.py] Started tracking which settings made each result")

    if JSON_OUT is not None:
        use_json(JSON_OUT)
    show = args.progress or args.progress_json
    rankings = []
    for name in STEPS:
        if name not in args.steps:
            continue
        start = perf_counter()
        emit("step_start", step=name)
        if show:
            # Model loading happens before the first photo, so say the step has started
            print(f"[main.py] {name}: starting", flush=True)
        match name:
            case "import":
                copied = import_photos(args.folder, args.import_to, catalog.get_all_hashes(), show)
                result = f"{copied} new photos copied to {args.import_to}"
            case "redo":
                #--all forces every photo, otherwise only ones made with older settings
                if args.all:
                    stale = catalog.processed_photos(args.redo)
                else:
                    stale = catalog.stale_photos(args.redo, fingerprint(settings, args.redo))
                catalog.delete_detections(stale, args.redo)
                result = f"{len(stale)} photos cleared for {args.redo}"
            case "scan":
                result = f"{len(DirectoryScanner(catalog).scan(scan_folder, show))} photos found"
            case "objects":
                result = f"{ObjectStep(catalog, settings, config, show).run()} new photos"
            case "faces":
                result = f"{FaceStep(catalog, settings, config, show).run()} new photos"
            case "landmarks":
                result = f"{LandmarkStep(catalog, settings, config, show).run()} new photos"
            case "embeddings":
                # Loaded here so TensorFlow only starts when asked for, after torch
                from pipeline.embeddings import EmbeddingStep
                result = f"{EmbeddingStep(catalog, settings, show).run()} new photos"
            case "sharpness":
                SharpnessStep(catalog, settings, show).run()
                result = "all face boxes scored"
            case "ranking":
                rankings = BurstRankStep(catalog, settings).run()
                result = f"{len(rankings)} bursts ranked"
        seconds = perf_counter() - start
        print(f"[main.py] {name}: {result} ({seconds:.1f}s)")
        emit("step_end", step=name, result=result, seconds=round(seconds, 1))

    if "ranking" in args.steps:
        ranked = [photo for burst in rankings for photo in burst]
        total = len(catalog.get_all_hashes())
        candidates = sum(p.is_candidate for p in ranked)
        print(
            f"[main.py] Done: {len(rankings)} bursts, {candidates} candidates, "
            f"{total - len(ranked)} of {total} photos unranked"
        )
        emit("done", bursts=len(rankings), candidates=candidates, unranked=total - len(ranked))
    else:
        emit("done")
    catalog.close()


if __name__ == "__main__":
    main()
