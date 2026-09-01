from rembg import  remove, new_session
from dataclasses import dataclass, field
from pathlib import Path
from models.image import Image
from config.config import Config
import onnxruntime as ort
import inspect

print(inspect.signature(new_session))
sess_options = ort.SessionOptions()
sess_options.enable_mem_pattern = False
sess_options.enable_cpu_mem_arena = False
session = new_session(
    "u2netp",
    providers=[
        ("CUDAExecutionProvider", {
            "cudnn_conv_algo_search": "HEURISTIC",
            "arena_extend_strategy": "kNextPowerOfTwo",  # default, but explicit
        }),
        "CPUExecutionProvider",
    ],
)

@dataclass
class SailencyDetector: 
    x1, x2, y1, y2 = 0, 0, 0, 0
    image: Image
    output_dir: str

    def __post_init__(self):
        if not Path(self.output_dir).exists():
            Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        self.output_dir += self.image.path_to_image.stem + ".png"
        with open(self.image.path_to_image, "rb") as f:
            with open(self.output_dir, "wb") as o:
                import torch
                output = remove(f.read(), session=session)
                o.write(output)
