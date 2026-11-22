"""
File: Cully/modules/utils/steps.py
Description: The pipeline's step names in run order. Kept apart from main.py so the web server can
know them without importing main.py (which loads torch).
Author: Miguel Macias
Date: 2026-11-21
"""

import hashlib
import json

STEPS = ["import", "scan", "redo", "objects", "faces", "landmarks", "embeddings", "sharpness", "exposure", "ranking"]

# The settings each step's stored results depend on. A change to one of these makes that step's
# results out of date. landmarks and exposure read no settings (exposure limits are used by ranking), embeddings are already stored per model name and
# hardware.device doesn't change results.
STEP_SETTINGS = {
    "objects": ["YOLOModel", "object_threshold", "detection.person_threshold", "detection.object_scale"],
    "faces": ["face_threshold"],
    "sharpness": ["models.sharpness", "crop_size.sharpness"],
    "ranking": ["grouping", "ranking", "exposure", "face_threshold", "models.sharpness"],
}
# objects and faces only run on new photos, so they're tracked per photo and redone with --redo.
# sharpness and ranking redo the whole catalog every run, so one record each is enough.
PHOTO_STEPS = ["objects", "faces"]
CATALOG_STEPS = ["sharpness", "ranking"]


def default_steps(embeddings: bool, importing: bool = False, redo: bool = False) -> list[str]:
    """Returns back every step in order. import, redo and embeddings only run when asked for.
    A redo works on the catalog, so it has no import or scan"""
    optional = {"embeddings": embeddings, "import": importing and not redo, "redo": redo,
                "scan": not redo}
    return [step for step in STEPS if optional.get(step, True)]


def fingerprint(settings, step: str) -> str:
    """Returns back a short hash of the settings step depends on (settings is a Settings or its to_dict())"""
    values = settings if isinstance(settings, dict) else settings.to_dict()
    used = {}
    for key in STEP_SETTINGS[step]:
        #"detection.object_scale" -> values["detection"]["object_scale"]
        value = values
        for part in key.split("."):
            value = value[part]
        used[key] = value
    return hashlib.sha1(json.dumps(used, sort_keys=True).encode()).hexdigest()[:12]
