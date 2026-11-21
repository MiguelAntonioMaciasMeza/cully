"""
File: Cully/modules/web/app.py
Description: The Flask app for Cully: create_app() builds it, with one catalog per request, the safety
checks on writes, JSON errors and the image routes. Light imports only, the pipeline's models
(torch, TensorFlow, mediapipe) never load here.
Author: Miguel Macias
Date: 2026-11-17
"""

import getpass
import importlib.util
import json
import re
from pathlib import Path

from flask import Flask, Response, abort, current_app, g, jsonify, render_template, request, send_file
from platformdirs import user_cache_dir
from werkzeug.exceptions import HTTPException

from config.settings import Settings
from ingest.exif_reader import SUPPORTED_SUFFIXES
from ingest.importer import card_photos, import_folder
from models.catalog import Catalog
from models.report_photo import ReportPhoto
from models.results import EventResult
from utils.results import group_results
from utils.steps import CATALOG_STEPS, PHOTO_STEPS, STEPS, default_steps, fingerprint
from web.images import cached_face, cached_resize
from web.runner import Runner, RunBusy

HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
VALID_STATUS = ["keep", "reject", None]
THUMB_SIZE = 360
PREVIEW_SIZE = 2000
# Personal photos: browsers may keep them, shared caches and proxies may not
IMAGE_CACHE_CONTROL = "private, max-age=86400"
KEEP_ALIVE = 15  # seconds between SSE comments, so idle streams notice a closed page
# Where memory cards and USB drives show up: /media/<user>/<card> (Ubuntu), /run/media/<user>/<card> (Fedora)
MOUNT_BASES = [Path("/media"), Path("/run/media")]


def get_catalog() -> Catalog:
    """This request's catalog, opened on first use and closed when the request ends."""
    if "catalog" not in g:
        path = g.app_config["CATALOG_PATH"]
        g.catalog = Catalog(str(path)) if path else Catalog()
    return g.catalog


def get_settings() -> Settings:
    """This request's settings, read fresh so changes from the settings page show at once."""
    if "settings" not in g:
        path = g.app_config["SETTINGS_PATH"]
        g.settings = Settings(path=Path(path)) if path else Settings()
    return g.settings


def require_photo(image_hash: str) -> str:
    """Returns the photo's path. 400 for a malformed hash, 404 for one not in the catalog."""
    if not HASH_PATTERN.fullmatch(image_hash):
        abort(400, description="Not a photo hash")
    path = get_catalog().get_photo_path_by_hash(image_hash)
    if path is None:
        abort(404, description="No such photo in the catalog")
    return path


def json_body() -> dict:
    """The request's JSON object. 400 if it isn't one."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        abort(400, description="Body must be a JSON object")
    return body


def _image_response(path: Path | None, source: str):
    if path is None:
        abort(
            404, description=f"File not found: {Path(source).name}. Rescan its folder."
        )
    response = send_file(path, mimetype="image/jpeg")
    response.headers["Cache-Control"] = IMAGE_CACHE_CONTROL
    return response


def create_app(
    catalog_path: str | Path | None = None,
    settings_path: str | Path | None = None,
    cache_dir: str | Path | None = None,
) -> Flask:
    """Builds the app. No paths given means the real catalog, settings and cache."""
    app = Flask(__name__)
    app.config.update(
        CATALOG_PATH=catalog_path,
        SETTINGS_PATH=settings_path,
        CACHE_DIR=Path(cache_dir) if cache_dir else Path(user_cache_dir("cully")),
        #One runner per app, it writes to the same catalog the page reads
        RUNNER=Runner(catalog_path, settings_path=settings_path),
    )

    @app.before_request
    def share_config():
        g.app_config = app.config

    @app.before_request
    def check_writes():
        """Writes must be JSON from this app's own page, so another site can't post to it."""
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return
        if not request.is_json:
            abort(415, description="Send JSON (Content-Type: application/json)")
        origin = request.headers.get("Origin")
        if origin is not None and origin != request.host_url.rstrip("/"):
            abort(403, description="Request from another site")

    @app.teardown_appcontext
    def close_catalog(_error):
        catalog = g.pop("catalog", None)
        if catalog is not None:
            catalog.close()

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException):
        return jsonify(error=error.description), error.code

    @app.errorhandler(Exception)
    def server_error(error: Exception):
        app.logger.exception("[app.py] Unhandled error")
        return jsonify(error=f"Server error: {error}"), 500

    @app.get("/thumb/<image_hash>")
    def thumb(image_hash: str):
        source = require_photo(image_hash)
        target = app.config["CACHE_DIR"] / "thumbs" / f"{image_hash}.jpg"
        return _image_response(cached_resize(Path(source), target, THUMB_SIZE), source)

    @app.get("/preview/<image_hash>")
    def preview(image_hash: str):
        source = require_photo(image_hash)
        target = app.config["CACHE_DIR"] / "previews" / f"{image_hash}.jpg"
        return _image_response(
            cached_resize(Path(source), target, PREVIEW_SIZE), source
        )

    @app.get("/face/<int:face_box_id>")
    def face(face_box_id: int):
        found = get_catalog().get_face_box_with_path(face_box_id)
        if found is None:
            abort(404, description="No such face")
        source, box = found
        target = app.config["CACHE_DIR"] / "faces" / f"{face_box_id}.jpg"
        return _image_response(cached_face(Path(source), box, target), source)

    register_routes(app)
    return app


def photo_json(photo: ReportPhoto) -> dict:
    """One photo as the page needs it."""
    return {
        "hash": photo.image_hash,
        "name": Path(photo.image_path).name,
        "rank": photo.rank,
        "score": photo.score,
        "eyes_open": photo.eyes_open,
        "is_candidate": photo.is_candidate,
        "unranked_reason": photo.unranked_reason,
        "culled_status": photo.culled_status,
        "width": photo.width,
        "height": photo.height,
    }


def event_json(event: EventResult) -> dict:
    """One event with its bursts and their photos."""
    return {
        "id": event.id,
        "number": event.number,
        "start": event.start,
        "end": event.end,
        "camera": event.camera,
        "bursts": [
            {
                "id": burst.id,
                "number": burst.number,
                "start": burst.start,
                "photos": [photo_json(p) for p in burst.photos],
            }
            for burst in event.bursts
        ],
    }


def report_photos() -> list[ReportPhoto]:
    """Every photo, with faces counted at the face threshold (same as the report)."""
    return get_catalog().get_report_photos(get_settings().face_threshold)


def get_runner() -> Runner:
    return current_app.config["RUNNER"]


def pipeline_ready() -> bool:
    """True if this Python can run main.py. Looks torch up without importing it."""
    return importlib.util.find_spec("torch") is not None


def photo_roots() -> list[Path]:
    """Returns back the folders the picker may show: home, then each mounted card or drive"""
    roots = [Path.home().resolve()]
    user = getpass.getuser()
    for base in MOUNT_BASES:
        try:
            roots += sorted(p.resolve() for p in (base / user).iterdir() if p.is_dir())
        except OSError:
            continue  # no such folder on this system, or not readable
    return roots


def count_photos(folder: Path, on_card: bool = False) -> int:
    """Returns back how many photos a run would take from folder. A card import also takes sub-folders,
    a scan doesn't"""
    if on_card:
        return len(card_photos(folder))
    return sum(1 for f in folder.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED_SUFFIXES)


def card_root(folder: Path) -> Path | None:
    """Returns back the mounted card folder is on, None if it isn't on one"""
    folder = folder.resolve()
    cards = [root for root in photo_roots()[1:] if folder.is_relative_to(root)]
    return max(cards, key=lambda r: len(r.parts)) if cards else None


def register_routes(app: Flask) -> None:
    """The page and the JSON API."""

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/events")
    def events():
        grouped, loose = group_results(report_photos())
        return {
            "events": [event_json(e) for e in grouped],
            "loose": [photo_json(p) for p in loose],
        }

    @app.get("/api/photos/<image_hash>")
    def photo_detail(image_hash: str):
        require_photo(image_hash)
        # One scan of the report query is fine at this catalog size
        photo = next((p for p in report_photos() if p.image_hash == image_hash), None)
        if photo is None:
            abort(404, description="No such photo in the catalog")
        settings = get_settings()
        faces = get_catalog().get_faces_for_photo(
            image_hash, settings.models["sharpness"], settings.face_threshold
        )
        return {
            **photo_json(photo),
            "path": photo.image_path,
            "camera": photo.camera_model,
            "capture_time": photo.capture_time,
            "faces": [
                {
                    "id": f.face_box_id,
                    "box": [f.x1, f.y1, f.x2, f.y2],
                    "confidence": f.confidence,
                    "sharpness": f.sharpness,
                    "ear_left": f.ear_left,
                    "ear_right": f.ear_right,
                }
                for f in faces
            ],
        }

    @app.get("/api/summary")
    def summary():
        """Returns back the totals for the page's top bar"""
        photos = report_photos()
        grouped, _ = group_results(photos)
        kept = 0
        rejected = 0
        unreviewed = 0
        candidates = 0
        eyes_closed = 0
        unranked = 0
        for photo in photos:
            if photo.culled_status == "keep":
                kept += 1
            elif photo.culled_status == "reject":
                rejected += 1
            elif photo.culled_status is None:
                unreviewed += 1

            if photo.is_candidate:
                candidates += 1

            if photo.eyes_open is False:
                eyes_closed += 1
            if photo.rank is None:
                unranked += 1

        bursts = sum(len(event.bursts) for event in grouped)

        return {
            "photos": len(photos),
            "events": len(grouped),
            "bursts": bursts,
            "candidates": candidates,
            "eyes_closed": eyes_closed,
            "unranked": unranked,
            "kept": kept,
            "rejected": rejected,
            "unreviewed": unreviewed,
        }

    @app.put("/api/photos/<image_hash>/status")
    def set_status(image_hash: str):
        """Sets one photo to keep, reject or null (unreviewed)"""
        require_photo(image_hash)
        body = json_body()

        if "status" not in body:
            abort(400, "Status key is missing from request body")

        if body["status"] not in VALID_STATUS:
            abort(400, "Status key is not valid")

        get_catalog().set_culled_status(image_hash, body["status"])

        return {"hash": image_hash, "status": body["status"]}

    @app.post("/api/bursts/<int:burst_id>/accept")
    def accept_burst(burst_id: int):
        """Marks a burst's candidates keep and its other ranked photos reject"""

        result = get_catalog().accept_burst(burst_id)
        if result is None:
            abort(404, "No such burst")

        kept, rejected = result
        return {"kept": kept, "rejected": rejected}

    @app.post("/api/run")
    def start_run():
        """Starts main.py: on a folder, a card import, a redo or a re-rank. 409 if a run is going,
        400 for bad input"""
        body = json_body()
        embeddings = body.get("embeddings", False)
        if not isinstance(embeddings, bool):
            abort(400, "embeddings must be true or false")

        #A redo works on out-of-date photos in the whole catalog, no folder
        redo = body.get("redo")
        if redo is not None and redo not in PHOTO_STEPS:
            abort(400, f"redo must be one of: {', '.join(PHOTO_STEPS)}")

        steps = body.get("steps")
        if steps is None:
            steps = default_steps(embeddings, redo=redo is not None)
        elif not isinstance(steps, list) or not steps or any(step not in STEPS for step in steps):
            abort(400, f"steps must be a list from: {', '.join(STEPS)}")
        if ("redo" in steps) != (redo is not None):
            abort(400, "The redo step and \"redo\" go together")

        #Only scan and import read a folder
        folder = body.get("folder")
        needs_folder = "scan" in steps or "import" in steps or body.get("import", False)
        if needs_folder and (not isinstance(folder, str) or not folder or not Path(folder).is_dir()):
            abort(400, f"Not a folder: {folder}")
        if not needs_folder:
            folder = None

        #Photos on a card are copied to disk first, the catalog then points at the copies
        importing = body.get("import", False)
        if not isinstance(importing, bool):
            abort(400, "import must be true or false")
        import_to = None
        if importing:
            if card_root(Path(folder)) is None:
                abort(400, "Only folders on a memory card can be imported")
            if body.get("steps") is None:
                steps = default_steps(embeddings, importing=True)
            elif "import" not in steps:
                abort(400, "An import needs the import step")
            import_to = import_folder()
        elif "import" in steps:
            abort(400, "The import step needs \"import\": true")

        if not pipeline_ready():
            abort(400, "This server can't run the pipeline. Start it with venv-main.")
        try:
            get_runner().start(Path(folder) if folder else None, steps, embeddings, import_to, redo)
        except RunBusy:
            abort(409, "A run is already going")
        return get_runner().snapshot(), 202

    @app.get("/api/staleness")
    def staleness():
        """What's out of date because settings changed since it was made: photos per detection step,
        and whether sharpness or ranking last ran with other settings"""
        settings = get_settings()
        catalog = get_catalog()
        fingerprints = {step: fingerprint(settings, step) for step in PHOTO_STEPS + CATALOG_STEPS}
        #A catalog from before tracking: what's there counts as made with today's settings
        catalog.start_tracking(fingerprints)
        photos = {step: len(catalog.stale_photos(step, fingerprints[step])) for step in PHOTO_STEPS}
        steps = {}
        for step in CATALOG_STEPS:
            last = catalog.catalog_run_fingerprint(step)
            steps[step] = last is not None and last != fingerprints[step]
        return {**photos, **steps, "any": any(photos.values()) or any(steps.values())}

    @app.get("/api/run")
    def run_state():
        return get_runner().snapshot()

    @app.post("/api/run/cancel")
    def cancel_run():
        if not get_runner().cancel():
            abort(409, "No run is going")
        return get_runner().snapshot()

    @app.get("/api/run/events")
    def run_events():
        """Streams the run state as Server-Sent Events, one per change, until the run ends"""
        runner = get_runner()

        def stream():
            state = runner.snapshot()
            yield f"data: {json.dumps(state)}\n\n"
            while state["running"]:
                new = runner.wait_for_change(state["version"], KEEP_ALIVE)
                if new["version"] == state["version"]:
                    yield ": keep-alive\n\n"
                    continue
                state = new
                yield f"data: {json.dumps(state)}\n\n"

        return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.get("/api/folders")
    def folders():
        """Sub-folders of path (default: home) with their photo counts. Only inside home or a mounted card"""
        roots = photo_roots()
        home = roots[0]
        path = Path(request.args.get("path") or home).expanduser().resolve()
        #The deepest root holding path, so a card's top folder has no parent to go up to
        inside = [root for root in roots if path.is_relative_to(root)]
        if not inside:
            abort(400, "Only your home folder and memory cards can be listed")
        root = max(inside, key=lambda r: len(r.parts))
        if not path.is_dir():
            abort(400, f"Not a folder: {path}")

        on_card = root != home
        entries = []
        for child in sorted(path.iterdir(), key=lambda p: p.name.lower()):
            #Skip hidden folders and ones we can't read
            if child.name.startswith(".") or not child.is_dir():
                continue
            try:
                entries.append({"name": child.name, "path": str(child), "photos": count_photos(child, on_card)})
            except PermissionError:
                continue

        return {
            "path": str(path),
            "parent": str(path.parent) if path != root else None,
            "photos": count_photos(path, on_card),
            "folders": entries,
            "import_to": str(import_folder()) if on_card else None,
            "root": str(root),
            "roots": [{"name": "Home" if r == home else r.name, "path": str(r)} for r in roots],
        }
