# Cully

Culls photo shoots: finds the people and faces in each photo, groups photos into events and bursts, ranks each burst by sharpness and open eyes, and suggests which frames to keep.

## Installation

Tested on Linux Mint 22.3 with Python 3.12. A working install needs about 9 GB of disk space, mostly for the Python packages.

### 1. Clone and install dependencies

```bash
git clone https://github.com/MiguelAntonioMaciasMeza/cully
cd cully
python3.12 -m venv venv-main
venv-main/bin/pip install -r requirements.txt
```

### 2. Download the MediaPipe models

These are **not** downloaded automatically; without them the first run stops at the face detection step.

```bash
M=~/.local/share/cully/models/mediapipe
mkdir -p $M/face_detection $M/face_landmarker
curl -L -o $M/face_detection/blaze_face_full_range.tflite \
  https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_full_range/float16/1/blaze_face_full_range.tflite
curl -L -o $M/face_landmarker/face_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
```

Model information: [Face Detector (BlazeFace full-range)](https://developers.google.com/edge/mediapipe/solutions/vision/face_detector) · [Face Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker)

### 3. GPU or CPU

The default device is `cuda`, which needs an NVIDIA GPU with a working driver. **Without one, set the device to `cpu` before the first run**, or the run stops at object detection with `RuntimeError: No CUDA GPUs are available`. On a new install (this replaces any existing settings file):

```bash
mkdir -p ~/.config/cully
echo '{"hardware": {"device": "cpu"}}' > ~/.config/cully/settings.json
```

Cully fills in the other settings with their defaults. Later you can change it in the web app (Settings → Advanced → Hardware → Device). Only object detection (YOLO) uses the GPU, so the CPU is nearly as fast.

### 4. First run

The first run needs internet access: the default YOLO model (`yolo26n.pt`) downloads automatically. Other YOLO models can be downloaded from the web app's Settings page. After that, Cully works fully offline.

## Usage

```bash
cd modules
../venv-main/bin/python main.py /path/to/photos --catalog myshoot   # run the pipeline
../venv-main/bin/python -m web --catalog myshoot                    # open http://127.0.0.1:5000/
```

`python -m web` needs an existing catalog (the `main.py` run creates it), or pass `--create`.

### Notes

- **Embeddings (`--embeddings`, optional):** the face model weights download automatically on first use. On the GPU this currently needs extra CUDA packages not in `requirements.txt` (`tensorflow[and-cuda]`); run with `CUDA_VISIBLE_DEVICES=""` to use the CPU instead. Ranking does not use embeddings.
- **Face grouping** needs a separate environment with older library versions and is not part of the normal run.

## Web app

Run from `Cully/modules` with **venv-main**:

```bash
../venv-main/bin/python -m web --open                      # the real catalog
../venv-main/bin/python -m web --catalog PATH --port 5000  # another catalog
../venv-main/bin/python -m web --settings PATH             # another settings file (runs use it too)
```

The server listens on `127.0.0.1` only. `--host` with another address needs `--allow-remote`, because anyone on that network could then see your photos.

- **Culling:** browse events, bursts and their Keep / Rest / Unranked groups. Mark photos keep or reject, accept a whole burst's suggestion, or open a photo to see its face crops. Press `?` for keyboard shortcuts.
- **Run:** choose a folder under your home folder and start the pipeline. You can watch each step live and cancel. Results reload when ranking finishes.
- **Memory cards:** a card shows up next to Home in the Run panel. "Copy and run" copies its new photos (sub-folders included) to the import folder (default `~/Pictures/Cully/<date>`), then runs on the copies, so the card can be wiped afterwards. Photos already in the catalog aren't copied again.
- **Settings:** the **Basic** tab has the everyday settings (burst and event gaps, eye check, how many photos get suggested, folders). **Advanced** has every setting, grouped as Detection, Grouping, Ranking, Models, Hardware and Folders. Each one says when a change takes effect and shows its default. Bad values are refused with the reason. Settings can't change while a run is going, since the run already read them. **Person detector model** (Advanced) lists the YOLO26 and YOLO11 models, nano to extra large. A model that isn't installed has a **Download** button, with progress shown in the Run panel. A custom trained `.pt` file put in `~/.local/share/cully/models/object_detection/` shows up under "Your models". It needs a `person` class, or detection stops with a clear message. Changing the model marks detections out of date (Redo detection).
- **Export:** copies the photos marked keep to the export folder (default `~/Pictures/Cully/Exports`), one folder per event, such as `2026-11-21 14-05`. Photos already there are skipped, so exporting again only adds new keepers. A photo rejected after an export is not removed from the export folder. The copies are rated 3★ (the Kept photo rating setting), which darktable and Lightroom pick up: inside the file for JPEGs, in `IMG.xmp` and `IMG.CR2.xmp` sidecars for RAW. Originals are never changed, and a sidecar Cully didn't write is never overwritten. **Sidecars only** (a choice in the Export popover) copies nothing: it writes a rating file next to each kept or rejected original, so you import the original folders into your editor. JPEG ratings this way reach darktable only, because Lightroom ignores JPEG sidecars. From the command line: `python -m export [DEST]`. This works in either venv.
- **Out of date:** if settings change after photos were processed, a banner says what's out of date. **Re-rank now** redoes sharpness and ranking (seconds). **Redo detection** deletes the stored people and faces of the affected photos and finds them again; it asks first. Keep/reject choices are never touched. From the command line: `python main.py --redo objects` (or `faces`).

### Good to know

- Runs only start when the server itself runs in venv-main. The pipeline needs torch, which venv-faces doesn't have.
- **Run state lives in the server's memory.** If the server stops or restarts mid-run, the pipeline keeps going on its own, but the page loses track of it. Wait for it to finish, or stop it with `pkill -f main.py`. Starting a run again is always safe: every step saves as it goes and skips photos it has already done.
- One run at a time. Starting a second run while one is going gives an error.
- Sub-folders aren't scanned. Run each folder of photos on its own.

### Tests

From `Cully/modules`:

```bash
python -m web.tests.check_api        # every route; --catalog PATH also tests a copy of a real catalog
python -m web.tests.check_runner     # real pipeline runs on 3 photos and a card import (venv-main, about a minute)
python -m web.tests.check_redo       # redo tracking; the real redo run needs venv-main
python -m web.tests.check_catalog
python -m web.tests.check_settings
```

They all use temporary catalogs, never the real one.
