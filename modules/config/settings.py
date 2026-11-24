from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
import copy
import json
import re

from config.yolo_models import is_model_name


# u2net takes in 320,320 images natively, however if we would like
# we can send images past that resolution, just choose an input scale
class SaliencyInputScale(Enum):
    U2NETNATIVE = -1
    QUARTER = 0.25
    HALF = 0.5
    THIRD = 0.75
    FULL = 1


class SaliencyModels(Enum):
    U2NET = "u2net"
    U2NETP = "u2netp"

class YOLOModel(Enum):
    NANO = "yolo26n.pt"


DEFAULT_SETTINGS = {
    "saliency_scale": float(SaliencyInputScale.U2NETNATIVE.value),
    "saliency_model": str(SaliencyModels.U2NET.value),
    "YOLOModel":str(YOLOModel.NANO.value),
    "min_dimension": {"saliency": 640, "face": 400},  # not used yet
    # Size (longest side) a crop is scaled to before each step scores it
    "crop_size": {"sharpness": 300},
    "object_threshold": 70,
    "face_threshold": 70,  # below this, face boxes are mostly the back of a head or clothing
    # How far apart shots can be and still count as one burst / one event
    "grouping": {"burst_gap_seconds": 3, "event_gap_minutes": 120},
    # Burst ranking: eyes are closed under eye_gate of the person's best EAR or under ear_floor,
    # and faces in two frames are the same person when their boxes overlap by face_match_iou.
    # eye_check: false ranks on sharpness only, for posed eyes-down shots.
    # Candidates: rank 1, plus eyes-open photos scoring at least candidate_margin of the best.
    # max_candidates caps them per burst, 0 = no cap
    "ranking": {
        "eye_gate": 0.6,
        "ear_floor": 0.15,
        "face_match_iou": 0.3,
        "eye_check": True,
        "candidate_margin": 0.9,
        "max_candidates": 0,
    },
    # Which model or method each step uses
    "models": {"embedding": "Facenet512", "embedding_metric": "cosine", "sharpness": "laplacian"},
    # "cuda" or "cpu". Only YOLO uses it for now, DeepFace and MediaPipe pick their own device
    "hardware": {"device": "cuda"},
    # object_scale: images are shrunk by this before YOLO (used by ObjectStep)
    # person_threshold: YOLO confidence for person boxes, other objects use object_threshold
    "detection": {"object_scale": 0.5, "person_threshold": 60},
    # Exposure problems penalise a photo like closed eyes (scoring/exposure.py). Brightness is 0-255.
    # black_frame / white_frame: % of pixels crushed / blown out that makes a failed frame.
    # face_dark / face_bright: limits on a face's mean brightness.
    # burst_stops: how far a photo can be from its burst's median brightness, in stops
    "exposure": {"check": True, "black_frame": 95.0, "white_frame": 95.0, "face_dark": 25, "face_bright": 200,
                 "burst_stops": 1.0},
    # Where photos copied off a memory card go, one folder per day inside it
    "import_folder": "~/Pictures/Cully",
    # Where Export copies the kept photos, one folder per event inside it
    "export_folder": "~/Pictures/Cully/Exports",
    # Stars the exported copies get, so darktable and Lightroom show them as kept
    "export_rating": 3,
    # copy: kept photos are copied and rated. sidecars: a rating file next to each original, no copies
    "export_mode": "sidecars",
}

# How the settings page shows each setting, by "key" or "group.key". Every setting needs an entry,
# check_settings fails otherwise. applies: when a change takes effect
#   next_run    the next ranking (Re-rank, seconds)
#   new_photos  photos processed from now on; older ones show up in the out-of-date banner (Redo detection)
#   next_import the next memory card import
#   next_export the next export
# basic: shown on the Basic tab too, Advanced shows everything
SETTINGS_INFO = {
    #type model: picked from config/yolo_models.py's list plus custom .pt files, see /api/settings
    "YOLOModel": {"group": "Detection", "label": "Person detector model", "type": "model", "applies": "new_photos",
                  "help": "The YOLO model that finds people in each photo. Bigger models find more small or far away "
                          "people but run slower. A custom trained model needs a 'person' class."},
    "detection.person_threshold": {"group": "Detection", "label": "Person confidence", "type": "integer",
                                   "min": 0, "max": 100, "step": 1, "unit": "%", "applies": "new_photos",
                                   "help": "How sure the detector must be that a box is a person. Lower finds more people, and more mistakes."},
    "object_threshold": {"group": "Detection", "label": "Other object confidence", "type": "integer",
                         "min": 0, "max": 100, "step": 1, "unit": "%", "applies": "new_photos",
                         "help": "The same, for everything that isn't a person."},
    "detection.object_scale": {"group": "Detection", "label": "Detection image size", "type": "number",
                               "min": 0.05, "max": 1, "step": 0.05, "applies": "new_photos",
                               "help": "Photos are shrunk by this before detection. Smaller is faster but can miss small people."},
    "face_threshold": {"group": "Detection", "label": "Face confidence", "type": "integer",
                       "min": 0, "max": 100, "step": 1, "unit": "%", "applies": "new_photos",
                       "help": "Faces below this are ignored, they're mostly the back of a head or clothing. Also used by ranking."},
    "grouping.burst_gap_seconds": {"group": "Grouping", "label": "Burst gap", "type": "integer",
                                   "min": 1, "max": 600, "step": 1, "unit": "s", "applies": "next_run", "basic": True,
                                   "help": "Shots taken closer together than this count as one burst, and Cully picks the best of each burst."},
    "grouping.event_gap_minutes": {"group": "Grouping", "label": "Event gap", "type": "integer",
                                   "min": 1, "max": 1440, "step": 1, "unit": "min", "applies": "next_run", "basic": True,
                                   "help": "A break in shooting longer than this starts a new event."},
    "ranking.eye_check": {"group": "Ranking", "label": "Check eyes", "type": "boolean", "applies": "next_run",
                          "basic": True,
                          "help": "Rank photos with closed eyes lower. Turn off for shots where people look down on purpose, then only sharpness counts."},
    "ranking.eye_gate": {"group": "Ranking", "label": "Eye gate", "type": "number",
                         "min": 0, "max": 1, "step": 0.05, "applies": "next_run",
                         "help": "How far below a person's most open eyes in the burst still counts as open."},
    "ranking.ear_floor": {"group": "Ranking", "label": "Closed-eye floor", "type": "number",
                          "min": 0, "max": 1, "step": 0.01, "applies": "next_run",
                          "help": "Eyes more closed than this always count as closed."},
    "ranking.face_match_iou": {"group": "Ranking", "label": "Same-person overlap", "type": "number",
                               "min": 0, "max": 1, "step": 0.05, "applies": "next_run",
                               "help": "How much two face boxes must overlap across frames to be the same person."},
    "ranking.candidate_margin": {"group": "Ranking", "label": "Candidate margin", "type": "number",
                                 "min": 0, "max": 1, "step": 0.01, "applies": "next_run", "basic": True,
                                 "help": "How close to the best photo another must score to also be suggested (0.9 = within 10%). Lower suggests more photos."},
    "ranking.max_candidates": {"group": "Ranking", "label": "Most candidates per burst", "type": "integer",
                               "min": 0, "max": 100, "step": 1, "applies": "next_run", "basic": True,
                               "help": "The most photos suggested from one burst. 0 means no limit."},
    "exposure.check": {"group": "Exposure", "label": "Check exposure", "type": "boolean", "applies": "next_run",
                       "basic": True,
                       "help": "Rank badly exposed photos lower and never suggest them: black or white frames, faces too dark "
                               "or too bright, and frames much brighter or darker than the rest of their burst."},
    "exposure.burst_stops": {"group": "Exposure", "label": "Burst tolerance", "type": "number",
                             "min": 0.1, "max": 5, "step": 0.1, "unit": "stops", "applies": "next_run", "basic": True,
                             "help": "How much brighter or darker than the rest of its burst a photo can be. Catches flash "
                                     "misfires and bracketed shots."},
    "exposure.black_frame": {"group": "Exposure", "label": "Black frame", "type": "number",
                             "min": 0, "max": 100, "step": 1, "unit": "%", "applies": "next_run",
                             "help": "A photo with at least this much pure black is a failed frame. Dark scenes like an "
                                     "aquarium stay well under it."},
    "exposure.white_frame": {"group": "Exposure", "label": "White frame", "type": "number",
                             "min": 0, "max": 100, "step": 1, "unit": "%", "applies": "next_run",
                             "help": "A photo with at least this much pure white is a failed frame. Shots on a white "
                                     "background stay under it."},
    "exposure.face_dark": {"group": "Exposure", "label": "Face too dark", "type": "integer",
                           "min": 0, "max": 255, "step": 1, "applies": "next_run",
                           "help": "A face darker than this (0 black to 255 white) is a silhouette. Moody backlit faces "
                                   "are around 30 to 50."},
    "exposure.face_bright": {"group": "Exposure", "label": "Face too bright", "type": "integer",
                             "min": 0, "max": 255, "step": 1, "applies": "next_run",
                             "help": "A face brighter than this (0 black to 255 white) is blown out."},
    "models.sharpness": {"group": "Models", "label": "Sharpness method", "type": "choice",
                         "choices": ["laplacian"], "applies": "next_run",
                         "help": "How each face crop's sharpness is measured."},
    "crop_size.sharpness": {"group": "Models", "label": "Sharpness crop size", "type": "integer",
                            "min": 50, "max": 2000, "step": 10, "unit": "px", "applies": "next_run",
                            "help": "Face crops are scaled to this size (longest side) before sharpness is measured."},
    "models.embedding": {"group": "Models", "label": "Face embedding model", "type": "choice",
                         "choices": ["Facenet512", "Facenet", "ArcFace", "VGG-Face", "SFace", "GhostFaceNet"],
                         "applies": "next_run",
                         "help": "Used only when faces are embedded (the Run panel checkbox), ranking doesn't need it."},
    "models.embedding_metric": {"group": "Models", "label": "Embedding distance", "type": "choice",
                                "choices": ["cosine", "euclidean", "euclidean_l2"], "applies": "next_run",
                                "help": "How two face embeddings are compared."},
    "hardware.device": {"group": "Hardware", "label": "Device", "type": "text", "applies": "next_run",
                        "help": "cuda (graphics card), cuda:1 for a second card, or cpu. Only the person detector uses it."},
    "import_folder": {"group": "Folders", "label": "Import folder", "type": "text", "applies": "next_import",
                      "basic": True,
                      "help": "Photos copied off a memory card go into a folder per day inside this one."},
    "export_folder": {"group": "Folders", "label": "Export folder", "type": "text", "applies": "next_export",
                      "basic": True,
                      "help": "Export copies your kept photos here, one folder per event."},
    "export_rating": {"group": "Folders", "label": "Kept photo rating", "type": "integer",
                      "min": 1, "max": 5, "step": 1, "unit": "★", "applies": "next_export",
                      "help": "Stars kept photos get, read by darktable and Lightroom."},
    "export_mode": {"group": "Folders", "label": "Export as", "type": "choice", "choices": ["copy", "sidecars"],
                    "applies": "next_export",
                    "help": "copy: kept photos are copied to the export folder and rated. sidecars: no copies, a rating file "
                            "is written next to each kept or rejected original (JPEG ratings this way reach darktable only)."},
    # Not wired up yet, kept off the page
    "saliency_scale": {"hidden": True},
    "saliency_model": {"hidden": True},
    "min_dimension.saliency": {"hidden": True},
    "min_dimension.face": {"hidden": True},
}

settings_path = Path.home() / ".config" / "cully" / "settings.json"


#Only really needed for issues such as 3.0 -> 3, etc
def _checked(value,default):
    """Returns value as same type enforcing original type cast"""
    if type(default) is float and type(value) is int:
        return float(value)
    if type(value) is not type(default):
        raise TypeError(f"expected {type(default).__name__}, got {value!r}")

    return value
@dataclass
class Settings:
    path: Path = settings_path
    saliency_scale: float = field(default=DEFAULT_SETTINGS["saliency_scale"])
    saliency_model: str = field(default=DEFAULT_SETTINGS["saliency_model"])
    YOLOModel: str = field(default=DEFAULT_SETTINGS["YOLOModel"])
    # Groups are copied, so changing one on a Settings never changes the defaults
    min_dimension: dict[str, int] = field(
        default_factory=lambda: dict(DEFAULT_SETTINGS["min_dimension"])
    )
    crop_size: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_SETTINGS["crop_size"]))
    object_threshold: float = field(default=DEFAULT_SETTINGS["object_threshold"])
    face_threshold: float = field(default=DEFAULT_SETTINGS["face_threshold"])
    grouping: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SETTINGS["grouping"]))
    ranking: dict[str, float | bool] = field(default_factory=lambda: dict(DEFAULT_SETTINGS["ranking"]))
    exposure: dict[str, float | bool] = field(default_factory=lambda: dict(DEFAULT_SETTINGS["exposure"]))
    models: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SETTINGS["models"]))
    hardware: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SETTINGS["hardware"]))
    detection: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SETTINGS["detection"]))
    import_folder: str = field(default=DEFAULT_SETTINGS["import_folder"])
    export_folder: str = field(default=DEFAULT_SETTINGS["export_folder"])
    export_rating: int = field(default=DEFAULT_SETTINGS["export_rating"])
    export_mode: str = field(default=DEFAULT_SETTINGS["export_mode"])

    def __post_init__(self):
        # Check if directory exists, if not create
        if not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)

        updated = False

        # Check if settings.json exists
        if self.path.exists():
            with open(self.path, "r") as f:
                settings = json.load(f)

            for key, value in DEFAULT_SETTINGS.items():
                if key not in settings:
                    settings[key] = dict(value) if isinstance(value, dict) else value
                    updated = True
                # A group can also gain new keys over time, fill in the ones the file is missing
                elif isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        if sub_key not in settings[key]:
                            settings[key][sub_key] = sub_value
                            updated = True
                setattr(self, key, settings[key])

            # Save updated settings
            if updated:
                self.save()

        else:
            self.save()

        self._validate()

    def _validate(self):
        """Raises a clear error for values that would fail deep inside a model."""
        device = str(self.hardware["device"])
        if device not in ("cpu", "cuda") and not re.fullmatch(r"cuda:\d+", device):
            raise ValueError(f"[settings.py] hardware.device must be 'cpu', 'cuda' or 'cuda:N', got {device!r}")
        #Detection thresholds 
        thresholds = {
            "object_threshold": self.object_threshold,
            "face_threshold": self.face_threshold,
            "detection.person_threshold": self.detection["person_threshold"],
        }
        for setting, value in thresholds.items():
            if not 0 <= value <= 100:
                raise ValueError(f"[settings.py] {setting} must be between 0 and 100, got {value}")
        # Ranking ratios, between 0 and 1
        fractions = {
            "ranking.eye_gate": self.ranking["eye_gate"],
            "ranking.ear_floor": self.ranking["ear_floor"],
            "ranking.face_match_iou": self.ranking["face_match_iou"],
            "ranking.candidate_margin": self.ranking["candidate_margin"],
        }

        for setting,value in fractions.items():
            if not 0 <= value <= 1:
                raise ValueError(f"[settings.py]{setting} must be between 0 and 1, got {value}")

        for setting, value in self.grouping.items():
            if value <= 0:
                raise ValueError(f"[settings.py]{setting} must be above 0, got {value}")
        exposure = self.exposure
        for setting in ("black_frame", "white_frame"):
            if not 0 <= exposure[setting] <= 100:
                raise ValueError(f"[settings.py]exposure.{setting} must be between 0 and 100, got {exposure[setting]}")
        for setting in ("face_dark", "face_bright"):
            if not 0 <= exposure[setting] <= 255:
                raise ValueError(f"[settings.py]exposure.{setting} must be between 0 and 255, got {exposure[setting]}")
        if exposure["face_dark"] >= exposure["face_bright"]:
            raise ValueError("[settings.py]exposure.face_dark must be below exposure.face_bright")
        if exposure["burst_stops"] <= 0:
            raise ValueError("[settings.py]exposure.burst_stops must be above 0")
        if self.ranking["max_candidates"] < 0:
            raise ValueError(f"[settings.py]max_candidates must be 0 or more")
        if not 0 < self.detection["object_scale"] <= 1:
            raise ValueError(f"[settings.py]object scale must above 0 and no more than 1")
        if self.crop_size["sharpness"] < 1:
            raise ValueError("[settings.py]crop_size.sharpness must be 1 or more")
        if not 1 <= self.export_rating <= 5:
            raise ValueError(f"[settings.py]export_rating must be between 1 and 5, got {self.export_rating}")
        for setting in ("import_folder", "export_folder"):
            if not self.value(setting).strip():
                raise ValueError(f"[settings.py]{setting} can't be empty")
        if not is_model_name(self.YOLOModel):
            raise ValueError(f"[settings.py]YOLOModel must be a .pt file name, got {self.YOLOModel!r}")
        #Settings with a fixed list of values
        for key, info in SETTINGS_INFO.items():
            if info.get("type") == "choice" and self.value(key) not in info["choices"]:
                raise ValueError(f"[settings.py]{key} must be one of {', '.join(info['choices'])}, got {self.value(key)!r}")

    def value(self, key: str):
        """Returns back one setting by "key" or "group.key" """
        group, _, sub_key = key.partition(".")
        value = getattr(self, group)
        return value[sub_key] if sub_key else value

    def reset(self) -> None:
        """Puts every setting back to its default and saves"""
        for key, default in DEFAULT_SETTINGS.items():
            setattr(self, key, copy.deepcopy(default))
        self.save()
    
    def to_dict(self) -> dict:
        """Returns back settings in a dict structure, excludes file path to settings"""
        
        exclude = {"path"}
        settings_dict = {key:copy.deepcopy(getattr(self,key)) for key in DEFAULT_SETTINGS if key not in exclude}
        return settings_dict


    def update(self, values:dict) -> None:
        before = self.to_dict()
        try:
            for key,value in values.items():
                if key not in DEFAULT_SETTINGS:
                    raise ValueError(f"unknown setting: {key}")
                default = DEFAULT_SETTINGS[key]
                if isinstance(default, dict):
                    if not isinstance(value, dict):
                        raise TypeError(f"{key} is a group, send its settings as an object")
                    for sub_key, sub_value in value.items():
                        if sub_key not in default:
                            raise ValueError(f"unknown setting: {key}.{sub_key}")
                        getattr(self,key)[sub_key] = _checked(sub_value, default[sub_key])
                else:
                    setattr(self, key, _checked(value,default))

            self._validate()
        except(KeyError, AttributeError, TypeError, ValueError) as e:
            #Reset setting back to previous one
            for key,value in before.items():
                setattr(self, key,value)
            raise ValueError(f"[settings.py] Bad setting, nothing was changed: {e}") from e

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(self.to_dict(),f, indent=4)
        
        tmp.replace(self.path)