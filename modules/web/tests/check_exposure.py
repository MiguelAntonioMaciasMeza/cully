"""
File: Cully/modules/web/tests/check_exposure.py
Description: Checks exposure scoring: the frame and face numbers, each exposure rule, the penalty in
ranking, ranking photos with no face, the catalog tables and the exposure settings.
Temp catalogs and temp settings files only, never the real ones.

Run from Cully/modules:
    python -m web.tests.check_exposure
Author: Miguel Macias
Date: 2026-11-21
"""

from pathlib import Path
import json
import tempfile
import time

import numpy as np

from config.settings import DEFAULT_SETTINGS, Settings
from models.face_score import FaceScore
from models.photo_metrics import PhotoMetrics
from pipeline.exposure import ExposureStep
from scoring.burst_rank import append_ranked, rank_burst, rank_frames
from scoring.exposure import exposure_issues, face_brightness, frame_metrics, stops_from
from web.tests.check_redo import make_detected_catalog

LIMITS = dict(DEFAULT_SETTINGS["exposure"])


def metrics(image_hash: str, brightness: float = 120, clipped: float = 0, crushed: float = 0) -> PhotoMetrics:
    return PhotoMetrics(image_hash, brightness, clipped, crushed, 100.0)


def test_frame_metrics():
    black = frame_metrics("b", np.zeros((40, 60, 3), np.uint8))
    assert black.brightness == 0 and black.crushed == 100 and black.clipped == 0, black
    white = frame_metrics("w", np.full((40, 60, 3), 255, np.uint8))
    assert white.clipped == 100 and white.crushed == 0, white
    #Noise is sharper than a flat grey
    flat = frame_metrics("f", np.full((40, 60, 3), 128, np.uint8))
    noisy = frame_metrics("n", np.random.default_rng(1).integers(0, 255, (40, 60, 3), dtype=np.uint8))
    assert noisy.sharpness > flat.sharpness == 0


def test_face_brightness_scales_and_clamps():
    img = np.zeros((100, 100, 3), np.uint8)
    img[10:20, 10:20] = 200
    #Full-size box (40, 40, 80, 80) on a 1/4 size read is (10, 10, 20, 20)
    assert face_brightness(img, (40, 40, 80, 80), 0.25) == 200
    assert face_brightness(img, (900, 900, 999, 999), 0.25) is None  # outside the image


def test_stops():
    assert abs(stops_from(137, 100) - 1) < 0.01  # x1.37 is about one stop
    assert stops_from(50, 100) < -2


def test_each_rule():
    burst = {
        "ok": metrics("ok"),
        "black": metrics("black", brightness=1, crushed=97),
        "white": metrics("white", brightness=250, clipped=96),
        "dark_face": metrics("dark_face"),
        "bright_face": metrics("bright_face"),
        "under": metrics("under", brightness=60),
        "over": metrics("over", brightness=200),
    }
    faces = {"ok": [110], "dark_face": [20], "bright_face": [240]}
    issues = exposure_issues(burst, faces, LIMITS)
    assert issues["ok"] is None, issues
    assert issues["black"] == "black frame"
    assert issues["white"] == "white frame"
    assert issues["dark_face"] == "face too dark"
    assert issues["bright_face"] == "face too bright"
    assert issues["under"].endswith("stops under burst"), issues["under"]
    assert issues["over"].endswith("stops over burst"), issues["over"]


def test_dark_scenes_and_check_off():
    #A whole dark burst (an aquarium) is fine, only frames that stand out are flagged
    dark = {h: metrics(h, brightness=15, crushed=35) for h in ("a", "b", "c")}
    assert set(exposure_issues(dark, {}, LIMITS).values()) == {None}
    #A single photo has no burst to compare with
    assert exposure_issues({"a": metrics("a", brightness=30)}, {}, LIMITS) == {"a": None}
    off = dict(LIMITS, check=False)
    assert exposure_issues({"a": metrics("a", crushed=100)}, {}, off) == {"a": None}


def test_penalty_in_face_ranking():
    #Photo "a" is sharpest but blown out: it sorts below "b" and isn't a candidate
    faces = [FaceScore(1, "a", 100.0, 0.3, person_id=1), FaceScore(2, "b", 95.0, 0.3, person_id=1)]
    ranked = {p.image_hash: p for p in rank_burst(faces, exposure={"a": "white frame", "b": None})}
    assert ranked["b"].rank == 1 and ranked["b"].is_candidate
    assert ranked["a"].rank == 2 and not ranked["a"].is_candidate
    assert ranked["a"].exposure_issue == "white frame"


def test_rank_one_with_bad_exposure_is_no_candidate():
    #A lone black frame used to be suggested just for being rank 1
    ranked = rank_frames({"a": 5.0}, {"a": "black frame"})
    assert ranked[0].rank == 1 and not ranked[0].is_candidate


def test_faceless_ranking():
    ranked = rank_frames({"soft": 50.0, "sharp": 100.0})
    assert [p.image_hash for p in ranked] == ["sharp", "soft"]
    assert ranked[0].eyes_open is None and ranked[0].score == 1.0
    #In a burst with faces, faceless photos go after and are never candidates
    faces = rank_burst([FaceScore(1, "f", 80.0, 0.3, person_id=1)])
    merged = append_ranked(faces, rank_frames({"x": 100.0}))
    assert [(p.image_hash, p.rank, p.is_candidate) for p in merged] == [("f", 1, True), ("x", 2, False)]


def test_catalog_tables_and_redo():
    with tempfile.TemporaryDirectory() as folder:
        catalog, hashes = make_detected_catalog(Path(folder))
        #Each sample photo has one person box and one face box (id = 1, 2, 3)
        assert ExposureStep(catalog).run() == 3
        assert ExposureStep(catalog).run() == 0, "nothing new to measure"
        assert set(catalog.get_photo_metrics(hashes)) == set(hashes)
        assert sorted(catalog.get_face_brightness(hashes, 0)) == sorted(hashes)
        #A redo drops the face numbers with the faces, the frame numbers stay
        catalog.delete_detections(hashes[:1], "faces")
        assert 1 not in catalog.get_face_exposure_ids()
        assert hashes[0] in catalog.get_photo_metric_hashes()
        catalog.close()


def test_settings():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "settings.json"
        settings = Settings(path=path)
        assert settings.exposure == DEFAULT_SETTINGS["exposure"]
        for bad in ({"face_dark": 240}, {"burst_stops": 0}, {"black_frame": 120}):
            try:
                settings.update({"exposure": bad})
            except ValueError:
                pass
            else:
                raise AssertionError(f"{bad} should be refused")
        #A settings file from before exposure existed gets the new group filled in
        values = json.loads(path.read_text())
        del values["exposure"]
        path.write_text(json.dumps(values))
        assert Settings(path=path).exposure == DEFAULT_SETTINGS["exposure"]


if __name__ == "__main__":
    tests = [value for name, value in dict(globals()).items() if name.startswith("test_")]
    failed = 0
    for test in tests:
        started = time.perf_counter()
        try:
            test()
            print(f"  [PASS] {test.__name__} ({time.perf_counter() - started:.0f}s)")
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {test.__name__} {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
