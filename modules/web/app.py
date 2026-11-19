"""
File: Cully/modules/web/app.py
Description: The Flask app for Cully: create_app() builds it, with one catalog per request, the safety
checks on writes, JSON errors and the image routes. Light imports only, the pipeline's models
(torch, TensorFlow, mediapipe) never load here.
Author: Miguel Macias
Date: 2026-11-17
"""

import re
from pathlib import Path

from flask import Flask, abort, g, jsonify, request, send_file
from platformdirs import user_cache_dir
from werkzeug.exceptions import HTTPException

from config.settings import Settings
from models.catalog import Catalog
from web.images import cached_face, cached_resize

HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
THUMB_SIZE = 360
PREVIEW_SIZE = 2000
# Personal photos: browsers may keep them, shared caches and proxies may not
IMAGE_CACHE_CONTROL = "private, max-age=86400"


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
        abort(404, description=f"File not found: {Path(source).name}. Rescan its folder.")
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
        return _image_response(cached_resize(Path(source), target, PREVIEW_SIZE), source)

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


def register_routes(app: Flask) -> None:
    """The JSON API."""

    # U4: GET /api/summary
    #   photos = get_catalog().get_report_photos(get_settings().face_threshold)

    # U5: PUT /api/photos/<image_hash>/status
    #   use require_photo(image_hash) and json_body()

    # U6: POST /api/bursts/<int:burst_id>/accept
