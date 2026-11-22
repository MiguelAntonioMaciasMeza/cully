"""
File: Cully/modules/web/tests/check_api.py
Description: Checks every web route through Flask's test client, that the server stays light and starts
fast, and that statuses survive a ranking rerun. Uses throwaway catalogs, never the real one.

Run from Cully/modules:
    python -m web.tests.check_api                      #tiny catalog built here
    python -m web.tests.check_api --catalog PATH       #also runs on a copy of a main.py catalog
The ranking rerun needs venv-main (main.py loads torch), in venv-faces it is skipped.
Author: Miguel Macias
Date: 2026-11-21
"""

from pathlib import Path
import argparse
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import time

import cv2

from web.app import create_app
from web.tests.check_catalog import make_burst_catalog

MODULES = Path(__file__).resolve().parents[2]
HEAVY = ("torch", "tensorflow", "mediapipe", "ultralytics", "deepface")
ORIGIN = "http://localhost"  # the test client's own address
REAL_CATALOG: Path | None = None  # set by --catalog


class Skip(Exception):
    """Raised by a test that can't run here, so it shows as SKIP instead of FAIL."""


def make_app(folder: Path):
    """Returns back a test client on a tiny catalog (1 event, 1 burst, 3 photos, 1 face),
    plus the burst id, the 3 hashes and the face box id"""
    catalog, burst_id, _, hashes = make_burst_catalog(folder)
    assert catalog.cursor is not None and catalog.catalog_connection is not None

    #A person box with one face on the first photo, so /face has something to crop
    catalog.cursor.execute(
        "INSERT INTO bounding_boxes (id, image_hash, confidence, name, x1, y1, x2, y2) "
        "VALUES (1, ?, 0.9, 'person', 0, 0, 80, 60)",
        (hashes[0],),
    )
    #Confidence is a percent, it must clear the face threshold (70) to show
    catalog.cursor.execute(
        "INSERT INTO face_boxes (id, name, parent_box_id, confidence, x1, y1, x2, y2) "
        "VALUES (7, 'Face Box', 1, 92, 10, 10, 30, 30)"
    )
    catalog.cursor.execute("INSERT INTO face_scores VALUES (7, 'laplacian', 123.5)")
    catalog.cursor.execute(
        "INSERT INTO face_landmarks (face_box_id, image_hash, ear_left, ear_right) VALUES (7, ?, 0.3, 0.28)",
        (hashes[0],),
    )
    catalog.catalog_connection.commit()
    catalog.close()

    app = create_app(folder / "catalog.db", folder / "settings.json", folder / "cache")
    return app.test_client(), burst_id, hashes, 7


def make_real_app(folder: Path):
    """Returns back a test client on a copy of the --catalog file"""
    assert REAL_CATALOG is not None
    copy = folder / "real.db"
    shutil.copy(REAL_CATALOG, copy)
    app = create_app(copy, folder / "settings.json", folder / "cache")
    return app.test_client(), copy


def put_status(client, image_hash: str, body, **headers):
    """Returns back the response of a status change, sent as JSON from this app's page by default"""
    return client.put(f"/api/photos/{image_hash}/status", json=body, headers={"Origin": ORIGIN, **headers})


def statuses(client) -> dict[str, str | None]:
    """Returns back hash -> culled_status for every photo, read through the API"""
    data = client.get("/api/events").get_json()
    photos = [p for e in data["events"] for b in e["bursts"] for p in b["photos"]] + data["loose"]
    return {p["hash"]: p["culled_status"] for p in photos}


UNKNOWN_HASH = "0" * 64


# ---------- Page and read-only routes ----------

def test_index():
    with tempfile.TemporaryDirectory() as folder:
        client, *_ = make_app(Path(folder))
        response = client.get("/")
        assert response.status_code == 200, response.status_code
        assert b'id="events"' in response.data


def test_events():
    with tempfile.TemporaryDirectory() as folder:
        client, burst_id, hashes, _ = make_app(Path(folder))
        data = client.get("/api/events").get_json()
        assert len(data["events"]) == 1 and data["loose"] == [], data
        burst = data["events"][0]["bursts"][0]
        assert burst["id"] == burst_id and burst["number"] == 1, burst
        assert [p["hash"] for p in burst["photos"]] == hashes
        #Every field the page reads
        keys = {"hash", "name", "rank", "score", "eyes_open", "is_candidate",
                "unranked_reason", "culled_status", "width", "height"}
        assert set(burst["photos"][0]) == keys, set(burst["photos"][0])


def test_summary():
    with tempfile.TemporaryDirectory() as folder:
        client, _, hashes, _ = make_app(Path(folder))
        before = client.get("/api/summary").get_json()
        assert before["photos"] == 3 and before["events"] == 1 and before["bursts"] == 1, before
        assert before["candidates"] == 1 and before["unreviewed"] == 3, before
        put_status(client, hashes[0], {"status": "keep"})
        put_status(client, hashes[1], {"status": "reject"})
        after = client.get("/api/summary").get_json()
        assert (after["kept"], after["rejected"], after["unreviewed"]) == (1, 1, 1), after


def test_photo_detail():
    with tempfile.TemporaryDirectory() as folder:
        client, _, hashes, face_id = make_app(Path(folder))
        data = client.get(f"/api/photos/{hashes[0]}").get_json()
        assert data["hash"] == hashes[0] and data["path"].endswith("burst_0.jpg"), data
        assert [f["id"] for f in data["faces"]] == [face_id], data["faces"]
        face = data["faces"][0]
        assert face["box"] == [10, 10, 30, 30], face
        assert (face["sharpness"], face["ear_left"], face["ear_right"]) == (123.5, 0.3, 0.28), face


def test_bad_and_unknown_hash():
    with tempfile.TemporaryDirectory() as folder:
        client, *_ = make_app(Path(folder))
        for route in ("/api/photos/{}", "/thumb/{}", "/preview/{}"):
            bad = client.get(route.format("not-a-hash"))
            unknown = client.get(route.format(UNKNOWN_HASH))
            assert bad.status_code == 400, (route, bad.status_code)
            assert unknown.status_code == 404, (route, unknown.status_code)
            assert "error" in unknown.get_json(), route  # errors are JSON too


def test_images():
    with tempfile.TemporaryDirectory() as folder:
        client, _, hashes, face_id = make_app(Path(folder))
        for url in (f"/thumb/{hashes[0]}", f"/preview/{hashes[0]}", f"/face/{face_id}"):
            response = client.get(url)
            assert response.status_code == 200, (url, response.status_code)
            assert response.mimetype == "image/jpeg", (url, response.mimetype)
            assert response.headers["Cache-Control"].startswith("private"), url
        assert client.get("/face/99999").status_code == 404


def test_missing_file_says_rescan():
    with tempfile.TemporaryDirectory() as folder:
        client, _, hashes, _ = make_app(Path(folder))
        (Path(folder) / "burst_2.jpg").unlink()
        response = client.get(f"/thumb/{hashes[2]}")
        assert response.status_code == 404, response.status_code
        assert "Rescan" in response.get_json()["error"], response.get_json()


# ---------- Writes ----------

def test_set_status():
    with tempfile.TemporaryDirectory() as folder:
        client, _, hashes, _ = make_app(Path(folder))
        for value in ("keep", "reject", None):
            response = put_status(client, hashes[0], {"status": value})
            assert response.status_code == 200, (value, response.status_code)
            assert statuses(client)[hashes[0]] == value, value


def test_set_status_bad_body():
    with tempfile.TemporaryDirectory() as folder:
        client, _, hashes, _ = make_app(Path(folder))
        for body in ({"status": "maybe"}, {}, ["keep"], "keep"):
            response = put_status(client, hashes[0], body)
            assert response.status_code == 400, (body, response.status_code)
        assert put_status(client, UNKNOWN_HASH, {"status": "keep"}).status_code == 404
        #Nothing was stored by the bad requests
        assert statuses(client)[hashes[0]] is None


def test_writes_need_json():
    with tempfile.TemporaryDirectory() as folder:
        client, burst_id, hashes, _ = make_app(Path(folder))
        status = client.put(f"/api/photos/{hashes[0]}/status", data='{"status": "keep"}')
        accept = client.post(f"/api/bursts/{burst_id}/accept", data="{}")
        assert status.status_code == 415, status.status_code
        assert accept.status_code == 415, accept.status_code
        assert statuses(client)[hashes[0]] is None


def test_writes_check_origin():
    with tempfile.TemporaryDirectory() as folder:
        client, _, hashes, _ = make_app(Path(folder))
        other = put_status(client, hashes[0], {"status": "keep"}, Origin="http://evil.example")
        assert other.status_code == 403, other.status_code
        assert statuses(client)[hashes[0]] is None
        #No Origin at all (curl, scripts) is allowed
        response = client.put(f"/api/photos/{hashes[0]}/status", json={"status": "keep"})
        assert response.status_code == 200, response.status_code


def test_accept_burst():
    with tempfile.TemporaryDirectory() as folder:
        client, burst_id, hashes, _ = make_app(Path(folder))
        response = client.post(f"/api/bursts/{burst_id}/accept", json={}, headers={"Origin": ORIGIN})
        assert response.get_json() == {"kept": 1, "rejected": 2}, response.get_json()
        assert [statuses(client)[h] for h in hashes] == ["keep", "reject", "reject"]
        unknown = client.post("/api/bursts/99999/accept", json={}, headers={"Origin": ORIGIN})
        assert unknown.status_code == 404, unknown.status_code


# ---------- Light server, fast start ----------

#Builds the app and serves the page and the events in a fresh Python, like `python -m web` does
START_CODE = """
import sys
from web.app import create_app
client = create_app(sys.argv[1], sys.argv[2], sys.argv[3]).test_client()
assert client.get("/").status_code == 200
assert client.get("/api/events").status_code == 200
"""


def run_start(folder: Path, *flags: str) -> tuple[subprocess.CompletedProcess, float]:
    """Returns back the finished start-up process and how long it took in seconds"""
    command = [sys.executable, *flags, "-c", START_CODE,
               str(folder / "catalog.db"), str(folder / "settings.json"), str(folder / "cache")]
    start = time.perf_counter()
    done = subprocess.run(command, cwd=MODULES, capture_output=True, text=True)
    return done, time.perf_counter() - start


def test_light_imports():
    with tempfile.TemporaryDirectory() as folder:
        make_app(Path(folder))
        #-X importtime lists every module loaded, on stderr
        checks = [
            run_start(Path(folder), "-X", "importtime")[0],
            subprocess.run([sys.executable, "-X", "importtime", "-m", "web", "--help"],
                           cwd=MODULES, capture_output=True, text=True),
        ]
        for done in checks:
            assert done.returncode == 0, done.stderr[-500:]
            loaded = [line for line in done.stderr.splitlines() if any(name in line for name in HEAVY)]
            assert not loaded, loaded[:5]


def test_starts_fast():
    with tempfile.TemporaryDirectory() as folder:
        make_app(Path(folder))
        done, seconds = run_start(Path(folder))
        assert done.returncode == 0, done.stderr[-500:]
        assert seconds < 1.0, f"took {seconds:.2f}s"


# ---------- Statuses survive a ranking rerun ----------

def rerun_ranking(catalog_path: Path):
    """Runs main.py --steps ranking on catalog_path. Skips when torch isn't installed (venv-faces)."""
    if importlib.util.find_spec("torch") is None:
        raise Skip("main.py needs torch, run this in venv-main")
    #The folder argument is only read by the scan step
    command = [sys.executable, "main.py", str(catalog_path.parent), "--steps", "ranking",
               "--catalog", str(catalog_path)]
    done = subprocess.run(command, cwd=MODULES, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-500:]


def test_status_survives_ranking_rerun():
    with tempfile.TemporaryDirectory() as folder:
        client, _, hashes, _ = make_app(Path(folder))
        put_status(client, hashes[0], {"status": "reject"})
        put_status(client, hashes[2], {"status": "keep"})
        before = statuses(client)
        rerun_ranking(Path(folder) / "catalog.db")
        assert statuses(client) == before, statuses(client)


# ---------- Settings ----------

def put_settings(client, body):
    return client.put("/api/settings", json=body, headers={"Origin": ORIGIN})


def test_settings_read_and_update():
    with tempfile.TemporaryDirectory() as folder:
        client, *_ = make_app(Path(folder))
        data = client.get("/api/settings").get_json()
        assert set(data) == {"values", "defaults", "info", "order", "path", "models"}, set(data)
        assert data["values"] == data["defaults"], "a fresh settings file has the defaults"

        response = put_settings(client, {"ranking": {"candidate_margin": 0.8}, "face_threshold": 60})
        assert response.status_code == 200, response.get_json()
        #Saved to the file, so the next request (a new Settings) sees it
        values = client.get("/api/settings").get_json()["values"]
        assert values["ranking"]["candidate_margin"] == 0.8 and values["face_threshold"] == 60, values
        assert values["ranking"]["eye_gate"] == data["defaults"]["ranking"]["eye_gate"], "others untouched"


def test_settings_bad_values():
    with tempfile.TemporaryDirectory() as folder:
        client, *_ = make_app(Path(folder))
        bad = [
            {"ranking": {"eye_gate": 1.5}},          # out of range
            {"face_threshold": "high"},              # wrong type
            {"nope": 1},                             # unknown key
            {"ranking": {"nope": 1}},                # unknown key in a group
            {"models": {"sharpness": "sobel"}},      # not one of the choices
        ]
        for body in bad:
            response = put_settings(client, body)
            assert response.status_code == 400, (body, response.status_code)
            assert response.get_json()["error"].startswith("[settings.py]"), response.get_json()
        unknown = put_settings(client, {"nope": 1}).get_json()["error"]
        assert "unknown setting: nope" in unknown, unknown
        #Nothing was saved by the bad requests
        data = client.get("/api/settings").get_json()
        assert data["values"] == data["defaults"]
        assert client.put("/api/settings", data="{}").status_code == 415


def test_settings_reset():
    with tempfile.TemporaryDirectory() as folder:
        client, *_ = make_app(Path(folder))
        put_settings(client, {"grouping": {"burst_gap_seconds": 9}})
        response = client.post("/api/settings/reset", json={}, headers={"Origin": ORIGIN})
        assert response.status_code == 200, response.status_code
        data = client.get("/api/settings").get_json()
        assert data["values"] == data["defaults"], data["values"]["grouping"]


def test_settings_locked_while_running():
    with tempfile.TemporaryDirectory() as folder:
        client, *_ = make_app(Path(folder))
        runner = client.application.config["RUNNER"]
        runner.state.running = True  # pretend, no real run needed
        try:
            assert put_settings(client, {"face_threshold": 60}).status_code == 409
            assert client.post("/api/settings/reset", json={}).status_code == 409
            assert client.post("/api/rerank", json={}).status_code in (400, 409)  # 400 without torch
        finally:
            runner.state.running = False
        assert client.get("/api/settings").get_json()["values"]["face_threshold"] == 70


# ---------- Export ----------

def wait_for_run(client, timeout: float = 60) -> dict:
    """Returns back the run state once the run has ended"""
    runner = client.application.config["RUNNER"]
    end = time.monotonic() + timeout
    state = runner.snapshot()
    while state["running"]:
        assert time.monotonic() < end, f"timed out, last state: {state}"
        state = runner.wait_for_change(state["version"], 5)
    return state


def test_export_kept_photos():
    with tempfile.TemporaryDirectory() as folder:
        client, _, hashes, _ = make_app(Path(folder))
        out = Path(folder) / "exports"
        put_settings(client, {"export_folder": str(out)})
        #Nothing kept yet
        assert client.get("/api/export").get_json() == {"kept": 0, "rejected": 0, "undecided": 1, "folder": str(out),
                                                       "rating": 3, "mode": "copy"}
        assert client.post("/api/export", json={}).status_code == 400

        #Keep the 2 photos that aren't suggestions, the suggestion stays undecided
        for image_hash in hashes[1:]:
            put_status(client, image_hash, {"status": "keep"})
        assert client.get("/api/export").get_json()["kept"] == 2

        runner = client.application.config["RUNNER"]
        runner.state.running = True  # pretend
        try:
            assert client.post("/api/export", json={}).status_code == 409
        finally:
            runner.state.running = False

        #No torch needed, so this runs in either venv
        assert client.post("/api/export", json={}).status_code == 202
        final = wait_for_run(client)
        assert final["exit_code"] == 0, final["log"][-10:]
        assert final["steps"] == ["export"] and "2 of 2" in final["finished"][0]["result"], final["finished"]
        event = out / "2026-01-01 10-00"
        assert sorted(p.name for p in event.iterdir()) == [".cully-export.json", "burst_1.jpg", "burst_2.jpg"], list(out.rglob("*"))
        #The copies carry the rating inside, the originals don't
        assert b'xmp:Rating="3"' in (event / "burst_1.jpg").read_bytes()
        assert b"xmp:Rating" not in (Path(folder) / "burst_1.jpg").read_bytes()
        assert cv2.imread(str(event / "burst_1.jpg")) is not None, "rated JPEG still opens"

        #Exporting again copies nothing new, it only updates the rating
        put_settings(client, {"export_rating": 5})
        client.post("/api/export", json={})
        again = wait_for_run(client)
        assert "0 of 2" in again["finished"][0]["result"] and "2 rated 5" in again["finished"][0]["result"], again["finished"]
        assert len(list(event.iterdir())) == 3
        rated = (event / "burst_1.jpg").read_bytes()
        assert b'xmp:Rating="5"' in rated and b'xmp:Rating="3"' not in rated


def test_export_sidecars_only():
    with tempfile.TemporaryDirectory() as folder:
        client, _, hashes, _ = make_app(Path(folder))
        photos = Path(folder)
        #burst_0 already has the editor's own sidecar
        (photos / "burst_0.jpg.xmp").write_text("<darktable history/>")
        for image_hash, status in zip(hashes, ("keep", "keep", "reject")):
            put_status(client, image_hash, {"status": status})
        before = (photos / "burst_1.jpg").read_bytes()

        assert client.post("/api/export", json={"mode": "nope"}).status_code == 400
        assert client.post("/api/export", json={"mode": "sidecars"}).status_code == 202
        final = wait_for_run(client)
        assert final["exit_code"] == 0, final["log"][-10:]
        assert final["finished"][0]["result"].startswith("2 sidecars written next to the originals, 1 skipped"), final["finished"]
        assert 'xmp:Rating="3"' in (photos / "burst_1.jpg.xmp").read_text()
        assert 'xmp:Rating="-1"' in (photos / "burst_2.jpg.xmp").read_text()
        assert (photos / "burst_0.jpg.xmp").read_text() == "<darktable history/>", "editor's sidecar untouched"
        assert not (photos / "burst_1.xmp").exists(), "JPEGs only get the darktable name"
        assert (photos / "burst_1.jpg").read_bytes() == before, "originals unchanged"
        assert not (photos / "exports").exists() and client.get("/api/export").get_json()["mode"] == "sidecars"

        #Cleared photos lose the sidecar Cully wrote
        put_status(client, hashes[1], {"status": None})
        client.post("/api/export", json={})
        again = wait_for_run(client)
        assert "1 cleared" in again["finished"][0]["result"], again["finished"]
        assert not (photos / "burst_1.jpg.xmp").exists()


# ---------- Person detector models ----------

def test_model_list_and_choice():
    with tempfile.TemporaryDirectory() as folder:
        models = Path(folder) / "models"
        models.mkdir()
        (models / "yolo26n.pt").write_bytes(b"x" * 2_000_000)
        (models / "my_people.pt").write_bytes(b"x")
        make_app(Path(folder))  # builds the catalog
        client = create_app(Path(folder) / "catalog.db", Path(folder) / "settings.json", Path(folder) / "cache",
                            models).test_client()
        listing = client.get("/api/settings").get_json()["models"]
        official = {m["name"]: m["mb"] for m in listing["official"]}
        assert len(official) == 10 and official["yolo26n.pt"] == 2.0 and official["yolo11x.pt"] is None, official
        assert [m["name"] for m in listing["custom"]] == ["my_people.pt"], listing["custom"]

        #Official models can be picked before they're downloaded, custom ones must be in the folder
        assert put_settings(client, {"YOLOModel": "yolo26s.pt"}).status_code == 200
        assert put_settings(client, {"YOLOModel": "my_people.pt"}).status_code == 200
        for bad in ("nope.pt", "../evil.pt", "yolo26n"):
            assert put_settings(client, {"YOLOModel": bad}).status_code == 400, bad

        post = lambda name: client.post("/api/models/download", json={"name": name})
        assert post("my_people.pt").status_code == 400   # not official
        assert post("yolo26n.pt").status_code == 400     # already installed
        runner = client.application.config["RUNNER"]
        runner.state.running = True  # pretend
        try:
            assert post("yolo26s.pt").status_code == 409
        finally:
            runner.state.running = False


def test_model_download():
    from detector import download_model
    with tempfile.TemporaryDirectory() as folder:
        #A local file stands in for GitHub, no network
        release = Path(folder) / "release"
        release.mkdir()
        (release / "yolo26s.pt").write_bytes(b"w" * 3_000_000)
        before = download_model.RELEASE_URL
        download_model.RELEASE_URL = release.as_uri()
        try:
            path = download_model.download("yolo26s.pt", Path(folder) / "models")
        finally:
            download_model.RELEASE_URL = before
        assert path.read_bytes() == b"w" * 3_000_000
        assert [p.name for p in path.parent.iterdir()] == ["yolo26s.pt"], "no temp file left"


# ---------- Real catalog (only with --catalog) ----------

def test_real_catalog_routes():
    if REAL_CATALOG is None:
        raise Skip("no --catalog given")
    with tempfile.TemporaryDirectory() as folder:
        client, _ = make_real_app(Path(folder))
        all_status = statuses(client)
        summary = client.get("/api/summary").get_json()
        assert len(all_status) == summary["photos"], (len(all_status), summary["photos"])
        for image_hash in all_status:
            response = client.get(f"/api/photos/{image_hash}")
            assert response.status_code == 200, (image_hash, response.status_code)


def test_real_catalog_status_survives_ranking():
    if REAL_CATALOG is None:
        raise Skip("no --catalog given")
    with tempfile.TemporaryDirectory() as folder:
        client, copy = make_real_app(Path(folder))
        hashes = list(statuses(client))
        put_status(client, hashes[0], {"status": "keep"})
        put_status(client, hashes[-1], {"status": "reject"})
        before = statuses(client)
        rerun_ranking(copy)
        assert statuses(client) == before


def test_real_catalog_rerank_follows_settings():
    if REAL_CATALOG is None:
        raise Skip("no --catalog given")
    if importlib.util.find_spec("torch") is None:
        raise Skip("re-ranking needs torch, run this in venv-main")
    with tempfile.TemporaryDirectory() as folder:
        client, _ = make_real_app(Path(folder))
        runner = client.application.config["RUNNER"]

        def rerank() -> int:
            assert client.post("/api/rerank", json={}).status_code == 202
            end = time.monotonic() + 120
            while runner.snapshot()["running"]:
                assert time.monotonic() < end, "re-rank timed out"
                time.sleep(0.2)
            assert runner.snapshot()["exit_code"] == 0, runner.snapshot()["log"][-10:]
            return client.get("/api/summary").get_json()["candidates"]

        before = rerank()
        #A lower margin lets more photos close to the best one count as candidates
        put_settings(client, {"ranking": {"candidate_margin": 0.5}})
        after = rerank()
        assert after > before, (before, after)
        assert client.get("/api/staleness").get_json()["any"] is False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m web.tests.check_api")
    parser.add_argument("--catalog", type=Path, help="a main.py catalog to also test on (only a copy is used)")
    args = parser.parse_args()
    if args.catalog is not None and not args.catalog.is_file():
        parser.error(f"[check_api.py]No catalog file at {args.catalog}")
    REAL_CATALOG = args.catalog

    tests = [value for name, value in dict(globals()).items() if name.startswith("test_")]
    failed = 0
    skipped = 0
    for test in tests:
        try:
            test()
            print(f"  [PASS] {test.__name__}")
        except Skip as reason:
            skipped += 1
            print(f"  [SKIP] {test.__name__}: {reason}")
        except Exception as e:  # a missing route shows as a failure, not a crash
            failed += 1
            print(f"  [FAIL] {test.__name__} {type(e).__name__}: {e}")
    print(f"{len(tests) - failed - skipped}/{len(tests)} passed, {skipped} skipped")
    raise SystemExit(1 if failed else 0)
