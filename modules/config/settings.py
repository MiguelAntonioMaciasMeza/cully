from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
import json


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
    # eye_check: false ranks on sharpness only, for posed eyes-down shots
    "ranking": {"eye_gate": 0.6, "ear_floor": 0.15, "face_match_iou": 0.3, "eye_check": True},
    # Which model or method each step uses
    "models": {"embedding": "Facenet512", "embedding_metric": "cosine", "sharpness": "laplacian"},
    # "cuda" or "cpu". Only YOLO uses it for now, DeepFace and MediaPipe pick their own device
    "hardware": {"device": "cuda"},
    # object_scale: images are shrunk by this before YOLO (no pipeline step uses it yet)
    "detection": {"object_scale": 0.5},
}

settings_path = Path.home() / ".config" / "cully" / "settings.json"


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
                with open(self.path, "w") as f:
                    json.dump(settings, f, indent=4)

        else:
            with open(self.path, "w") as f:
                json.dump(DEFAULT_SETTINGS, f, indent=4)


Settings()
