"""
File: Cully/modules/web/tests/check_runner.py
Description: Checks the web runner with real main.py runs on 3 photos: progress events, a second start,
cancel, bad input and a failing run. Temp folders and temp catalogs only, never the real one.

Run from Cully/modules with venv-main (main.py needs torch), takes about a minute:
    python -m web.tests.check_runner
Author: Miguel Macias
Date: 2026-11-21
"""

from pathlib import Path
import importlib.util
import json
import shutil
import subprocess
import tempfile
import time

from utils.steps import default_steps
from web.app import create_app
from web.runner import Runner

MODULES = Path(__file__).resolve().parents[2]
SAMPLES = MODULES.parent / "TestImages" / "Input"
RUN_TIMEOUT = 300  # seconds, model loading alone takes a while


class Skip(Exception):
    """Raised by a test that can't run here, so it shows as SKIP instead of FAIL."""


def photo_folder(folder: Path) -> Path:
    """Returns back a folder holding 3 sample photos"""
    if importlib.util.find_spec("torch") is None:
        raise Skip("main.py needs torch, run this in venv-main")
    photos = folder / "photos"
    photos.mkdir()
    for sample in sorted(SAMPLES.glob("*.jpg"))[:3]:
        shutil.copy(sample, photos / sample.name)
    return photos


def wait_until(runner: Runner, check, timeout: float = RUN_TIMEOUT) -> dict:
    """Returns back the first state check(state) accepts. Fails after timeout seconds"""
    end = time.monotonic() + timeout
    state = runner.snapshot()
    while not check(state):
        left = end - time.monotonic()
        assert left > 0, f"timed out, last state: {state}"
        state = runner.wait_for_change(state["version"], min(left, 5))
    return state


def children_left(catalog: Path) -> bool:
    """True if any process still has this test's catalog path on its command line"""
    return subprocess.run(["pgrep", "-f", str(catalog)], capture_output=True).returncode == 0


def test_real_run():
    with tempfile.TemporaryDirectory() as folder:
        photos = photo_folder(Path(folder))
        catalog = Path(folder) / "catalog.db"
        runner = Runner(catalog)
        steps = default_steps(False)
        runner.start(photos, steps)

        #Every state along the way, so we can check what the page would have seen
        seen = []
        final = wait_until(runner, lambda s: seen.append(s) or not s["running"])
        assert final["exit_code"] == 0, final["log"][-10:]
        assert final["error"] is None, final["error"]
        assert [f["step"] for f in final["finished"]] == steps, final["finished"]
        assert final["summary"] is not None and "bursts" in final["summary"], final["summary"]

        started = {s["current_step"] for s in seen if s["current_step"]}
        assert "scan" in started and "ranking" in started, started
        assert any(s["total"] == 3 and s["done"] > 0 for s in seen), "no progress event seen"


def test_second_start_and_cancel():
    with tempfile.TemporaryDirectory() as folder:
        photos = photo_folder(Path(folder))
        catalog = Path(folder) / "catalog.db"
        app = create_app(catalog, Path(folder) / "settings.json", Path(folder) / "cache")
        client = app.test_client()
        runner = app.config["RUNNER"]

        first = client.post("/api/run", json={"folder": str(photos)})
        second = client.post("/api/run", json={"folder": str(photos)})
        assert first.status_code == 202, first.get_json()
        assert second.status_code == 409, second.status_code

        #Cancel while the models load, the slow part
        wait_until(runner, lambda s: s["current_step"] in ("objects", "faces") or not s["running"])
        assert client.post("/api/run/cancel", json={}).status_code == 200
        final = wait_until(runner, lambda s: not s["running"], timeout=15)
        assert final["cancelled"] and final["exit_code"] != 0, final
        assert "cancelled" in final["error"], final["error"]
        time.sleep(0.5)  # let the OS reap the group
        assert not children_left(catalog), "main.py still running after cancel"
        #Nothing left to cancel
        assert client.post("/api/run/cancel", json={}).status_code == 409


def test_events_stream():
    with tempfile.TemporaryDirectory() as folder:
        photos = photo_folder(Path(folder))
        app = create_app(Path(folder) / "catalog.db", Path(folder) / "settings.json", Path(folder) / "cache")
        client = app.test_client()
        assert client.post("/api/run", json={"folder": str(photos), "steps": ["scan"]}).status_code == 202

        #The stream ends by itself after the final state, so reading all of it returns
        response = client.get("/api/run/events")
        assert response.mimetype == "text/event-stream", response.mimetype
        text = response.get_data(as_text=True)
        states = [json.loads(line[len("data: "):]) for line in text.splitlines() if line.startswith("data: ")]
        assert states[0]["running"] and not states[-1]["running"], (states[0], states[-1])
        assert states[-1]["exit_code"] == 0, states[-1]["log"][-10:]
        versions = [s["version"] for s in states]
        assert versions == sorted(set(versions)), versions  # one event per change, in order


def test_bad_input():
    with tempfile.TemporaryDirectory() as folder:
        photos = photo_folder(Path(folder))
        app = create_app(Path(folder) / "catalog.db", Path(folder) / "settings.json", Path(folder) / "cache")
        client = app.test_client()
        bodies = [
            {"folder": str(Path(folder) / "missing")},
            {"folder": str(photos / sorted(photos.iterdir())[0].name)},  # a file, not a folder
            {},
            {"folder": str(photos), "steps": ["scan", "nope"]},
            {"folder": str(photos), "steps": []},
            {"folder": str(photos), "embeddings": "yes"},
        ]
        for body in bodies:
            response = client.post("/api/run", json=body)
            assert response.status_code == 400, (body, response.status_code)
        assert app.config["RUNNER"].snapshot()["running"] is False


def test_failed_run_shows_error():
    with tempfile.TemporaryDirectory() as folder:
        photos = photo_folder(Path(folder))
        runner = Runner(Path(folder) / "catalog.db")
        #The API refuses unknown steps, the runner passes them on, so main.py fails like a broken run
        runner.start(photos, ["nope"])
        final = wait_until(runner, lambda s: not s["running"], timeout=120)
        assert final["exit_code"] == 2, final["exit_code"]
        assert "failed" in final["error"] and "start the run again" in final["error"], final["error"]
        assert any("unknown steps: nope" in line for line in final["log"]), final["log"]


def test_folders():
    with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
        (Path(folder) / "shoot").mkdir()
        (Path(folder) / ".hidden").mkdir()
        for name in ("a.jpg", "b.CR2", "notes.txt"):
            (Path(folder) / "shoot" / name).write_bytes(b"")
        app = create_app(Path(folder) / "catalog.db", Path(folder) / "settings.json", Path(folder) / "cache")
        client = app.test_client()

        data = client.get("/api/folders", query_string={"path": folder}).get_json()
        #.hidden is skipped, notes.txt isn't a photo, the CR2 counts
        assert [(f["name"], f["photos"]) for f in data["folders"]] == [("shoot", 2)], data["folders"]
        assert data["parent"] == str(Path(folder).resolve().parent), data

        home = client.get("/api/folders").get_json()
        assert home["path"] == str(Path.home().resolve()) and home["parent"] is None, home
        assert client.get("/api/folders", query_string={"path": "/"}).status_code == 400
        file_path = str(Path(folder) / "shoot" / "a.jpg")
        assert client.get("/api/folders", query_string={"path": file_path}).status_code == 400


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
        except Exception as e:  # a missing route shows as a failure, not a crash
            failed += 1
            print(f"  [FAIL] {test.__name__} {type(e).__name__}: {e}")
    print(f"{len(tests) - failed - skipped}/{len(tests)} passed, {skipped} skipped")
    raise SystemExit(1 if failed else 0)
