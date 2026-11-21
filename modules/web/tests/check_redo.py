"""
File: Cully/modules/web/tests/check_redo.py
Description: Checks redo tracking: step fingerprints, the first-run backfill, out-of-date counts after a
settings change, what --redo deletes (and keeps), and a real redo run. Temp catalogs and temp settings
files only, never the real ones.

Run from Cully/modules (the real run needs venv-main, it's skipped elsewhere):
    python -m web.tests.check_redo
Author: Miguel Macias
Date: 2026-11-21
"""

from pathlib import Path
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import time

from config.settings import DEFAULT_SETTINGS, Settings
from models.catalog import Catalog
from utils.steps import CATALOG_STEPS, PHOTO_STEPS, fingerprint
from web.app import create_app
from web.tests.check_catalog import make_burst_catalog

MODULES = Path(__file__).resolve().parents[2]
SAMPLES = MODULES.parent / "TestImages" / "Input"


class Skip(Exception):
    """Raised by a test that can't run here, so it shows as SKIP instead of FAIL."""


def fingerprints(settings: Settings) -> dict[str, str]:
    return {step: fingerprint(settings, step) for step in PHOTO_STEPS + CATALOG_STEPS}


def make_detected_catalog(folder: Path) -> tuple[Catalog, list[str]]:
    """Returns back the 3-photo burst catalog with detections on every photo: one person box,
    one face box with landmarks, a score and an embedding each. hashes[1] is marked keep."""
    catalog, _, _, hashes = make_burst_catalog(folder)
    assert catalog.cursor is not None and catalog.catalog_connection is not None
    cursor = catalog.cursor
    for i, image_hash in enumerate(hashes, start=1):
        cursor.execute(
            "INSERT INTO bounding_boxes (id, image_hash, confidence, name, x1, y1, x2, y2) "
            "VALUES (?, ?, 90, 'person', 0, 0, 80, 60)", (i, image_hash))
        cursor.execute(
            "INSERT INTO face_boxes (id, name, parent_box_id, confidence, x1, y1, x2, y2) "
            "VALUES (?, 'Face Box', ?, 92, 10, 10, 30, 30)", (i, i))
        cursor.execute(
            "INSERT INTO face_landmarks (face_box_id, image_hash, ear_left, ear_right) VALUES (?, ?, .3, .3)",
            (i, image_hash))
        cursor.execute("INSERT INTO face_scores VALUES (?, 'laplacian', 100)", (i,))
        cursor.execute(
            "INSERT INTO face_embeddings (face_box_id, image_hash, model_name, embedding_json) VALUES (?, ?, 'm', '[]')",
            (i, image_hash))
    catalog.catalog_connection.commit()
    catalog.set_culled_status(hashes[1], "keep")
    return catalog, hashes


def count(catalog: Catalog, table: str) -> int:
    assert catalog.cursor is not None
    return catalog.cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_fingerprints_follow_their_settings():
    with tempfile.TemporaryDirectory() as folder:
        settings = Settings(path=Path(folder) / "settings.json")
        before = fingerprints(settings)
        #Only ranking depends on grouping
        settings.update({"grouping": {"burst_gap_seconds": 9}})
        after = fingerprints(settings)
        assert [s for s in before if before[s] != after[s]] == ["ranking"], (before, after)
        #face_threshold is used when detecting faces and when ranking
        settings.update({"face_threshold": 50})
        changed = fingerprints(settings)
        assert [s for s in after if after[s] != changed[s]] == ["faces", "ranking"], (after, changed)
        #The device doesn't change results
        settings.update({"hardware": {"device": "cpu"}})
        assert fingerprints(settings) == changed


def test_first_run_backfills():
    with tempfile.TemporaryDirectory() as folder:
        catalog, hashes = make_detected_catalog(Path(folder))
        settings = Settings(path=Path(folder) / "settings.json")
        prints = fingerprints(settings)
        #Before tracking, nothing is recorded, so everything would look out of date
        assert len(catalog.stale_photos("objects", prints["objects"])) == 3
        assert catalog.start_tracking(prints) is True
        assert catalog.start_tracking(prints) is False  # only once
        stale = {step: catalog.stale_photos(step, prints[step]) for step in PHOTO_STEPS}
        catalog.close()
        assert stale == {"objects": set(), "faces": set()}, stale


def test_settings_change_makes_photos_stale():
    with tempfile.TemporaryDirectory() as folder:
        catalog, hashes = make_detected_catalog(Path(folder))
        settings = Settings(path=Path(folder) / "settings.json")
        catalog.start_tracking(fingerprints(settings))
        settings.update({"object_threshold": 60})
        prints = fingerprints(settings)
        objects = catalog.stale_photos("objects", prints["objects"])
        faces = catalog.stale_photos("faces", prints["faces"])
        catalog.close()
        assert objects == set(hashes) and faces == set(), (objects, faces)


def test_redo_objects_deletes_detections_keeps_choices():
    with tempfile.TemporaryDirectory() as folder:
        catalog, hashes = make_detected_catalog(Path(folder))
        catalog.start_tracking(fingerprints(Settings(path=Path(folder) / "settings.json")))
        assert catalog.delete_detections(hashes[:2], "objects") == 2
        counts = {t: count(catalog, t) for t in
                  ("bounding_boxes", "face_boxes", "face_landmarks", "face_scores", "face_embeddings")}
        runs = count(catalog, "step_runs")
        status = {p.image_hash: p.culled_status for p in catalog.get_report_photos()}
        catalog.close()
        #Only the third photo's rows are left, its 2 step records too
        assert counts == dict.fromkeys(counts, 1), counts
        assert runs == 2, runs
        assert status[hashes[1]] == "keep", status


def test_redo_faces_keeps_person_boxes():
    with tempfile.TemporaryDirectory() as folder:
        catalog, hashes = make_detected_catalog(Path(folder))
        catalog.start_tracking(fingerprints(Settings(path=Path(folder) / "settings.json")))
        catalog.delete_detections(hashes, "faces")
        boxes, faces = count(catalog, "bounding_boxes"), count(catalog, "face_boxes")
        assert catalog.cursor is not None
        steps = {row[0] for row in catalog.cursor.execute("SELECT step FROM step_runs")}
        catalog.close()
        assert (boxes, faces) == (3, 0), (boxes, faces)
        assert steps == {"objects"}, steps


def test_staleness_route():
    with tempfile.TemporaryDirectory() as folder:
        catalog, _ = make_detected_catalog(Path(folder))
        catalog.close()
        settings_path = Path(folder) / "settings.json"
        client = create_app(Path(folder) / "catalog.db", settings_path, Path(folder) / "cache").test_client()
        fresh = client.get("/api/staleness").get_json()
        assert fresh == {"objects": 0, "faces": 0, "sharpness": False, "ranking": False, "any": False}, fresh

        #Edit the settings file, as a user would by hand. The server reads it on every request
        values = json.loads(settings_path.read_text())
        values["face_threshold"] = 55
        values["grouping"]["burst_gap_seconds"] = 8
        settings_path.write_text(json.dumps(values))
        changed = client.get("/api/staleness").get_json()
        #make_burst_catalog has groups, so the backfill said ranking ran with the old settings
        assert changed == {"objects": 0, "faces": 3, "sharpness": False, "ranking": True, "any": True}, changed


def test_redo_run_validation():
    with tempfile.TemporaryDirectory() as folder:
        client = create_app(Path(folder) / "c.db", Path(folder) / "s.json", Path(folder) / "cache").test_client()
        bad = [
            {"redo": "ranking"},
            {"redo": "objects", "steps": ["objects"]},   # redo without its step
            {"steps": ["redo", "objects"]},               # step without redo
            {"steps": ["scan"]},                          # scan needs a folder
        ]
        for body in bad:
            response = client.post("/api/run", json=body)
            assert response.status_code == 400, (body, response.status_code)


def run_main(*args: str) -> subprocess.CompletedProcess:
    done = subprocess.run([sys.executable, "main.py", *args], cwd=MODULES, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-800:]
    return done


def test_real_redo_run():
    if importlib.util.find_spec("torch") is None:
        raise Skip("main.py needs torch, run this in venv-main")
    with tempfile.TemporaryDirectory() as folder:
        photos = Path(folder) / "photos"
        photos.mkdir()
        for sample in sorted(SAMPLES.glob("*.jpg"))[:3]:
            shutil.copy(sample, photos / sample.name)
        catalog_path, settings_path = Path(folder) / "catalog.db", Path(folder) / "settings.json"
        common = ["--catalog", str(catalog_path), "--settings", str(settings_path)]
        run_main(str(photos), *common)

        client = create_app(catalog_path, settings_path, Path(folder) / "cache").test_client()
        assert client.get("/api/staleness").get_json()["any"] is False
        client.put(f"/api/photos/{_first_hash(client)}/status", json={"status": "reject"})

        #A lower person threshold: every photo's objects are now out of date
        settings = Settings(path=settings_path)
        settings.update({"detection": {"person_threshold": 30}})
        settings.save()
        assert client.get("/api/staleness").get_json()["objects"] == 3

        done = run_main("--redo", "objects", *common)
        assert "3 photos cleared for objects" in done.stdout + done.stderr, done.stdout[-500:]
        after = client.get("/api/staleness").get_json()
        assert after["any"] is False, after
        assert client.get(f"/api/photos/{_first_hash(client)}").get_json()["culled_status"] == "reject"


def _first_hash(client) -> str:
    data = client.get("/api/events").get_json()
    photos = [p for e in data["events"] for b in e["bursts"] for p in b["photos"]] + data["loose"]
    return sorted(p["hash"] for p in photos)[0]


if __name__ == "__main__":
    tests = [value for name, value in dict(globals()).items() if name.startswith("test_")]
    failed = 0
    skipped = 0
    for test in tests:
        started = time.perf_counter()
        try:
            test()
            print(f"  [PASS] {test.__name__} ({time.perf_counter() - started:.0f}s)")
        except Skip as reason:
            skipped += 1
            print(f"  [SKIP] {test.__name__}: {reason}")
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {test.__name__} {type(e).__name__}: {e}")
    print(f"{len(tests) - failed - skipped}/{len(tests)} passed, {skipped} skipped")
    raise SystemExit(1 if failed else 0)
