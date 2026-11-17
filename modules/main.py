"""
File: Cully/modules/main.py
Description: Runs the whole Cully pipeline on a folder: scan, objects, faces, landmarks,
(embeddings), sharpness and burst ranking. Each step only does photos it hasn't done yet,
except sharpness and ranking, which redo the whole catalog.
Run from Cully/modules with venv-main:
    python main.py <folder> [--catalog PATH] [--embeddings] [--steps scan,objects,...] [--progress]
Author: Miguel Macias
Date: 2026-11-16
"""

# triton has to be loaded before mediapipe or it segfaults (see tests/pipeline/pipeline_steps_test.py)
import triton  # noqa: F401

import argparse
from pathlib import Path
from time import perf_counter

from config.config import Config
from config.settings import Settings
from ingest.directory_scanner import DirectoryScanner
from models.catalog import Catalog
# torch (YOLO) has to load before TensorFlow (DeepFace) or the process crashes, so objects goes first
from pipeline.objects import ObjectStep
from pipeline.faces import FaceStep
from pipeline.landmarks import LandmarkStep
from pipeline.sharpness import SharpnessStep
from pipeline.burst_ranking import BurstRankStep

STEPS = ["scan", "objects", "faces", "landmarks", "embeddings", "sharpness", "ranking"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Cully pipeline on a folder of photos.")
    parser.add_argument("folder", type=Path, help="folder of photos to scan")
    parser.add_argument("--catalog", type=Path, help="catalog file to use will default to main catalog, add field if you want a different catalog to be created")
    parser.add_argument("--embeddings", action="store_true", help="also embed faces (ranking doesn't need it)")
    parser.add_argument("--steps", help=f"comma separated subset of: {','.join(STEPS)}")
    parser.add_argument("-p", "--progress", action="store_true", help="show a live progress line for each step")
    args = parser.parse_args()

    if args.steps:
        args.steps = [s.strip() for s in args.steps.split(",")]
        unknown = set(args.steps) - set(STEPS)
        if unknown:
            parser.error(f"unknown steps: {', '.join(sorted(unknown))}")
    else:
        args.steps = [s for s in STEPS if s != "embeddings" or args.embeddings]
    return args


def main():
    args = parse_args()
    if "scan" in args.steps and not args.folder.is_dir():
        raise SystemExit(f"[main.py] Not a folder: {args.folder}")

    # One Settings, Config and Catalog shared by every step
    settings = Settings()
    config = Config()
    catalog = Catalog(str(args.catalog)) if args.catalog else Catalog()
    print(f"[main.py] Catalog: {catalog.catalog_path}")

    show = args.progress
    rankings = []
    for name in STEPS:
        if name not in args.steps:
            continue
        start = perf_counter()
        if show:
            # Model loading happens before the first photo, so say the step has started
            print(f"[main.py] {name}: starting", flush=True)
        match name:
            case "scan":
                result = f"{len(DirectoryScanner(catalog).scan(args.folder, show))} photos found"
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
        print(f"[main.py] {name}: {result} ({perf_counter() - start:.1f}s)")

    if "ranking" in args.steps:
        ranked = [photo for burst in rankings for photo in burst]
        total = len(catalog.get_all_hashes())
        print(
            f"[main.py] Done: {len(rankings)} bursts, {sum(p.is_candidate for p in ranked)} candidates, "
            f"{total - len(ranked)} of {total} photos unranked"
        )
    catalog.close()


if __name__ == "__main__":
    main()
