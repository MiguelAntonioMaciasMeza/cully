# Cully

Culls photo shoots: finds the people and faces in each photo, groups photos into events and bursts, ranks each burst by sharpness and open eyes, and suggests which frames to keep.

## Web app

Run from `Cully/modules` with **venv-main**:

```bash
../venv-main/bin/python -m web --open                      # the real catalog
../venv-main/bin/python -m web --catalog PATH --port 5000  # another catalog
```

The server listens on `127.0.0.1` only. `--host` with another address needs `--allow-remote`, because anyone on that network could then see your photos.

- **Culling:** browse events, bursts and their Keep / Rest / Unranked groups. Mark photos keep or reject, accept a whole burst's suggestion, or open a photo to see its face crops. Press `?` for keyboard shortcuts.
- **Run:** choose a folder under your home folder and start the pipeline. You can watch each step live and cancel. Results reload when ranking finishes.

### Good to know

- Runs only start when the server itself runs in venv-main. The pipeline needs torch, which venv-faces doesn't have.
- **Run state lives in the server's memory.** If the server stops or restarts mid-run, the pipeline keeps going on its own, but the page loses track of it. Wait for it to finish, or stop it with `pkill -f main.py`. Starting a run again is always safe: every step saves as it goes and skips photos it has already done.
- One run at a time. Starting a second run while one is going gives an error.
- Sub-folders aren't scanned. Run each folder of photos on its own.

### Tests

From `Cully/modules`:

```bash
python -m web.tests.check_api        # every route; --catalog PATH also tests a copy of a real catalog
python -m web.tests.check_runner     # real pipeline runs on 3 photos (venv-main, about a minute)
python -m web.tests.check_catalog
python -m web.tests.check_settings
```

They all use temporary catalogs, never the real one.
