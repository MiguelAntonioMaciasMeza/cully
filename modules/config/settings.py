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
    "min_dimension": {"saliency": 640, "face": 400, "blur": 300},
    "object_threshold": 75,
}

settings_path = Path.home() / ".config" / "cully" / "settings.json"


@dataclass
class Settings:
    path: Path = settings_path
    saliency_scale: float = field(default=DEFAULT_SETTINGS["saliency_scale"])
    saliency_model: str = field(default=DEFAULT_SETTINGS["saliency_model"])
    YOLOModel: str = field(default=DEFAULT_SETTINGS["YOLOModel"])
    min_dimension: dict[str, int] = field(
        default_factory=lambda: DEFAULT_SETTINGS["min_dimension"]
    )
    object_threshold: float = field(default=DEFAULT_SETTINGS["object_threshold"])

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
                    settings[key] = value
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
