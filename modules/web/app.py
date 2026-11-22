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

from config.settings import DEFAULT_SETTINGS, SETTINGS_INFO, Settings
from config.yolo_models import OFFICIAL, list_models, models_dir
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
    model_dir: str | Path | None = None,
) -> Flask:
    """Builds the app. No paths given means the real catalog, settings, cache and models folder."""
    app = Flask(__name__)
    app.config.update(
        CATALOG_PATH=catalog_path,
        SETTINGS_PATH=settings_path,
        CACHE_DIR=Path(cache_dir) if cache_dir else Path(user_cache_dir("cully")),
        MODEL_DIR=Path(model_dir) if model_dir else models_dir(),
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
        source, image_hash, box = found
        #Keyed by photo and box, not box id: ids restart in every catalog and after a redo
        x1, y1, x2, y2 = box
        target = app.config["CACHE_DIR"] / "faces" / f"{image_hash}_{x1}_{y1}_{x2}_{y2}.jpg"
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
        "exposure_issue": photo.exposure_issue,
        "face_count": photo.faces,
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
        metrics = get_catalog().get_photo_metrics([image_hash]).get(image_hash)
        return {
            **photo_json(photo),
            "exposure": None if metrics is None else {
                "brightness": metrics.brightness, "clipped": metrics.clipped, "crushed": metrics.crushed,
            },
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
        exposure_issues = 0
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
            if photo.exposure_issue:
                exposure_issues += 1
            if photo.rank is None:
                unranked += 1

        bursts = sum(len(event.bursts) for event in grouped)

        return {
            "photos": len(photos),
            "events": len(grouped),
            "bursts": bursts,
            "candidates": candidates,
            "eyes_closed": eyes_closed,
            "exposure_issues": exposure_issues,
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
        #"all" redoes every photo, not just out-of-date ones
        redo_all = body.get("all", False)
        if not isinstance(redo_all, bool):
            abort(400, "all must be true or false")
        if redo_all and redo is None:
            abort(400, "\"all\" needs \"redo\"")

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
            import_to = import_folder(get_settings().import_folder)
        elif "import" in steps:
            abort(400, "The import step needs \"import\": true")

        if not pipeline_ready():
            abort(400, "This server can't run the pipeline. Start it with venv-main.")
        try:
            get_runner().start(Path(folder) if folder else None, steps, embeddings, import_to, redo,
                               redo_all=redo_all)
        except RunBusy:
            abort(409, "A run is already going")
        return get_runner().snapshot(), 202

    def settings_json(settings: Settings) -> dict:
        """Returns back what the settings form needs: current values, defaults and how to show each"""
        #Flask sorts JSON keys, so the form's order is sent as a list
        return {"values": settings.to_dict(), "defaults": DEFAULT_SETTINGS, "info": SETTINGS_INFO,
                "order": list(SETTINGS_INFO), "path": str(settings.path),
                "models": list_models(current_app.config["MODEL_DIR"])}

    def refuse_while_running() -> None:
        #A run read its settings when it started, changing them mid-run would make the results disagree
        if get_runner().snapshot()["running"]:
            abort(409, "A run is going. Change settings once it's done.")

    @app.get("/api/settings")
    def read_settings():
        return settings_json(get_settings())

    @app.put("/api/settings")
    def update_settings():
        """Partial update, for example {"ranking": {"eye_gate": 0.5}}. 400 with the reason on a bad value"""
        body = json_body()
        refuse_while_running()
        settings = get_settings()
        #A custom model has to be in the models folder, official ones can be downloaded later
        model = body.get("YOLOModel")
        if isinstance(model, str) and model not in OFFICIAL and not (current_app.config["MODEL_DIR"] / model).is_file():
            abort(400, f"[settings.py]No model called {model} in {current_app.config['MODEL_DIR']}")
        try:
            settings.update(body)
        except ValueError as error:
            abort(400, str(error))
        settings.save()
        return settings_json(settings)

    @app.post("/api/settings/reset")
    def reset_settings():
        refuse_while_running()
        settings = get_settings()
        settings.reset()
        return settings_json(settings)

    @app.post("/api/rerank")
    def rerank():
        """Redoes sharpness and ranking for the whole catalog with the current settings (seconds).
        exposure only measures what's missing, so older catalogs get their numbers here too"""
        if not pipeline_ready():
            abort(400, "This server can't run the pipeline. Start it with venv-main.")
        try:
            get_runner().start(None, ["sharpness", "exposure", "ranking"])
        except RunBusy:
            abort(409, "A run is already going")
        return get_runner().snapshot(), 202

    def export_counts() -> dict:
        """Returns back the kept and rejected counts, undecided suggestions, and the export settings"""
        photos = report_photos()
        kept = sum(p.culled_status == "keep" for p in photos)
        rejected = sum(p.culled_status == "reject" for p in photos)
        undecided = sum(p.is_candidate and p.culled_status is None for p in photos)
        settings = get_settings()
        return {"kept": kept, "rejected": rejected, "undecided": undecided, "folder": settings.export_folder,
                "rating": settings.export_rating, "mode": settings.export_mode}

    @app.get("/api/export")
    def export_info():
        return export_counts()

    @app.post("/api/export")
    def start_export():
        """Exports with {"mode": "copy" | "sidecars"} (default: the export_mode setting), which is
        remembered. copy: kept photos into the export folder. sidecars: rating files next to the originals.
        Needs no torch"""
        body = json_body()
        settings = get_settings()
        mode = body.get("mode", settings.export_mode)
        if mode not in ("copy", "sidecars"):
            abort(400, "mode must be copy or sidecars")
        counts = export_counts()
        if not counts["kept"] and (mode == "copy" or not counts["rejected"]):
            abort(400, "No photos are marked keep yet" if mode == "copy" else "No photos are marked keep or reject yet")
        export_to = Path(settings.export_folder).expanduser() if mode == "copy" else None
        try:
            get_runner().start(None, ["export"], export_to=export_to, export_mode=mode)
        except RunBusy:
            abort(409, "A run is already going")
        #Remembered, so the popover opens on the same choice next time. The run got the mode directly
        if mode != settings.export_mode:
            settings.update({"export_mode": mode})
            settings.save()
        return get_runner().snapshot(), 202

    @app.post("/api/models/download")
    def download_model():
        """Downloads an official YOLO model into the models folder, shown in the Run panel. 409 if busy"""
        name = json_body().get("name")
        if name not in OFFICIAL:
            abort(400, f"Not an official model: {name}")
        folder = current_app.config["MODEL_DIR"]
        if (folder / name).is_file():
            abort(400, f"{name} is already installed")
        try:
            get_runner().download_model(name, folder)
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
            "import_to": str(import_folder(get_settings().import_folder)) if on_card else None,
            "root": str(root),
            "roots": [{"name": "Home" if r == home else r.name, "path": str(r)} for r in roots],
        }
