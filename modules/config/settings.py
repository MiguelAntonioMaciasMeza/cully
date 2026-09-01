from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
import json

class SaliencyInputScale(Enum):
    QUARTER = 0.25
    HALF = 0.5
    THIRD = .75
    FULL = 1

class SaliencyModels(Enum):
    U2NET = "u2net"
    U2NETP = "u2netp"

DEFAULT_SETTINGS = {
    "saliency_scale": float(SaliencyInputScale.QUARTER.value),
    "saliency_model": str(SaliencyModels.U2NET.value),
}

settings_path = Path.home() / ".config" / "cully"/"settings.json"
@dataclass
class Settings():
    path: Path = settings_path
    saliency_scale: float = field(default=DEFAULT_SETTINGS["saliency_scale"])
    saliency_model: str = field(default=DEFAULT_SETTINGS["saliency_model"])

    def __post_init__(self):
        #Check if directory exists, if not create
        if not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)

        #Check if settings.json exists
        if self.path.exists():
            with open(self.path, "r") as f:
                settings = json.load(f)
                self.saliency_scale = settings.get("saliency_scale")
                self.saliency_model = settings.get("saliency_model")
        else:
            with open(self.path, "w") as f:
                json.dump(DEFAULT_SETTINGS,f, indent=4)

Settings()
        

        


