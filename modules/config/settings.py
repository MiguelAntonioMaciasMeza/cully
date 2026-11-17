from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
import copy
import json
import re


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
    "object_threshold": 75,
    "face_threshold": 70,  # below this, face boxes are mostly the back of a head or clothing
    # How far apart shots can be and still count as one burst / one event
    "grouping": {"burst_gap_seconds": 5, "event_gap_minutes": 30},
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
    "detection": {"object_scale": 0.5, "person_threshold": 50},
}

settings_path = Path.home() / ".config" / "cully" / "settings.json"


#Only really needed for issues such as 3.0 -> 3, etc
def _checked(value,default):
    """Returns value as same type enforcing original type cast"""
    if type(default) is float and type(value) is int:
        return float(value)
    if type(value) is not type(default):
        raise TypeError(f"expected type {type(type(default).__name__)}, got {value}")

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
    models: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SETTINGS["models"]))
    hardware: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SETTINGS["hardware"]))
    detection: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SETTINGS["detection"]))

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
                raise ValueError(f"[setting.spy]{setting} must be above 0, got {value}")
        if self.ranking["max_candidates"] < 0:
            raise ValueError(f"[settings.py]max_candidates must be 0 or more")
        if not 0 < self.detection["object_scale"] <= 1:
            raise ValueError(f"[settings.py]object scale must above 0 and no more than 1")
    
    def to_dict(self) -> dict:
        """Returns back settings in a dict structure, excludes file path to settings"""
        
        exclude = {"path"}
        settings_dict = {key:copy.deepcopy(getattr(self,key)) for key in DEFAULT_SETTINGS if key not in exclude}
        return settings_dict


    def update(self, values:dict) -> None:
        before = self.to_dict()
        try:
            for key,value in values.items():
                default = DEFAULT_SETTINGS[key]
                if isinstance(default, dict):
                    for sub_key, sub_value in value.items():
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