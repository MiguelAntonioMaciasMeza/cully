# Cully

Culls photo shoots: finds the people and faces in each photo, groups photos into events and bursts, ranks each burst by sharpness and open eyes, and suggests which frames to keep.

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
- **Settings:** the **Basic** tab has the everyday settings (burst and event gaps, eye check, how many photos get suggested, folders). **Advanced** has every setting, grouped as Detection, Grouping, Ranking, Models, Hardware and Folders. Each one says when a change takes effect and shows its default. Bad values are refused with the reason. Settings can't change while a run is going, since the run already read them.
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
