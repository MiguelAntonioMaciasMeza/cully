"""
File: Cully/modules/web/runner.py
Description: Starts main.py as a subprocess for the web app and tracks its state from the JSON progress
lines. One run at a time. The server never imports the pipeline, all the heavy models live in the child.
Author: Miguel Macias
Date: 2026-11-21
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from models.run_state import FinishedStep, RunState

MODULES = Path(__file__).resolve().parents[1]
KILL_AFTER = 5.0  # seconds between SIGTERM and SIGKILL on cancel
RESTART_HINT = "Steps save as they go, so you can start the run again."


class RunBusy(Exception):
    """Raised when a run is started while another one is still going."""


class Runner:
    """Runs main.py (or the export) with --progress-json and keeps a RunState the API can read or wait on."""

    def __init__(self, catalog_path: str | Path | None = None, modules_dir: Path = MODULES,
                 settings_path: str | Path | None = None):
        self.catalog_path = catalog_path
        self.settings_path = settings_path  # the same settings the server reads
        self.modules_dir = modules_dir
        self.state = RunState()
        self.process: subprocess.Popen | None = None
        #One lock for the state. notify_all wakes anyone waiting for a change (the SSE stream)
        self.changed = threading.Condition()

    def _bump(self) -> None:
        """Marks the state as changed. Call while holding self.changed."""
        self.state.version += 1
        self.changed.notify_all()

    def start(self, folder: Path | None, steps: list[str], embeddings: bool = False,
              import_to: Path | None = None, redo: str | None = None, export_to: Path | None = None,
              export_mode: str | None = None, redo_all: bool = False) -> None:
        """Starts a run in the background. folder can be None for catalog-only runs (redo, re-rank).
        With export_mode, runs the export (python -m export) instead of main.py. Raises RunBusy if one is already going."""
        if export_mode is not None:
            #Export loads no models, it's its own small script
            args = ["-m", "export", "--mode", export_mode]
            if export_to is not None:
                args.append(str(export_to))
            self._launch(args + self._catalog_args(), None, ["export"])
            return
        args = ["main.py"]
        if folder is not None:
            args.append(str(folder))
        args += ["--steps", ",".join(steps)]
        if embeddings:
            args.append("--embeddings")
        if import_to is not None:
            args += ["--import-to", str(import_to)]
        if redo is not None:
            args += ["--redo", redo]
            if redo_all:
                args.append("--all")
        self._launch(args + self._catalog_args(), folder, steps)

    def download_model(self, name: str, folder: Path) -> None:
        """Downloads an official YOLO model in the background, shown like a one-step run"""
        self._launch(["-m", "detector.download_model", name, "--folder", str(folder)], None, ["download"])

    def _catalog_args(self) -> list[str]:
        """The catalog and settings this server uses, so runs work on the same ones"""
        args = []
        if self.catalog_path:
            args += ["--catalog", str(self.catalog_path)]
        if self.settings_path:
            args += ["--settings", str(self.settings_path)]
        return args

    def _launch(self, args: list[str], folder: Path | None, steps: list[str]) -> None:
        """Starts python args with --progress-json and follows it. Raises RunBusy if a run is going"""
        command = [sys.executable, "-u", *args, "--progress-json"]
        with self.changed:
            if self.state.running:
                raise RunBusy("A run is already going")
            #Own session (process group), so cancel can stop the run and anything it starts
            self.process = subprocess.Popen(
                command, cwd=self.modules_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1, start_new_session=True,
            )
            self.state = RunState(
                running=True, folder=str(folder) if folder is not None else None, steps=list(steps),
                started_at=time.time(), version=self.state.version,
            )
            self._bump()
            process = self.process

        log_reader = threading.Thread(target=self._read_log, args=(process,), daemon=True)
        log_reader.start()
        threading.Thread(target=self._read_events, args=(process, log_reader), daemon=True).start()
        print(f"[runner.py] Started {' '.join(args[:2])} on {folder or 'the catalog'} (pid {process.pid})")

    def _read_log(self, process: subprocess.Popen) -> None:
        """Keeps main.py's stderr as the run's log"""
        assert process.stderr is not None
        for line in process.stderr:
            with self.changed:
                self.state.log.append(line.rstrip())
                self._bump()

    def _read_events(self, process: subprocess.Popen, log_reader: threading.Thread) -> None:
        """Turns main.py's JSON lines into state, then records how the run ended"""
        assert process.stdout is not None
        for line in process.stdout:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = None
            with self.changed:
                if isinstance(event, dict):
                    self._apply(event)
                else:
                    self.state.log.append(line.rstrip())
                self._bump()

        code = process.wait()
        log_reader.join(timeout=5)
        with self.changed:
            self._finish(code)
            self._bump()
        print(f"[runner.py] Run ended with exit code {code}")

    def _apply(self, event: dict) -> None:
        """Updates the state from one progress event. Call while holding self.changed."""
        state = self.state
        match event.get("event"):
            case "step_start":
                state.current_step = event.get("step")
                state.done, state.total, state.file = 0, 0, ""
                state.step_started_at = time.time()
            case "progress":
                state.done = event.get("done", 0)
                state.total = event.get("total", 0)
                state.file = event.get("file", "")
            case "step_end":
                state.finished.append(FinishedStep(event.get("step", ""), event.get("result", ""), event.get("seconds", 0)))
                state.current_step = None
            case "done":
                state.summary = {k: v for k, v in event.items() if k != "event"}

    def _finish(self, code: int) -> None:
        """Records the exit code and, for a failed run, why. Call while holding self.changed."""
        state = self.state
        state.running = False
        state.current_step = None
        state.file = ""
        state.exit_code = code
        if state.cancelled:
            state.error = f"Run cancelled. {RESTART_HINT}"
        elif code != 0:
            #A negative code means the child was killed by that signal (a crash)
            reason = f"stopped by signal {-code}" if code < 0 else f"exit code {code}"
            state.error = f"The run failed ({reason}). {RESTART_HINT}"

    def cancel(self) -> bool:
        """Stops the run: SIGTERM, then SIGKILL if it's still going. Returns back False if nothing was running"""
        with self.changed:
            process = self.process
            if not self.state.running or process is None:
                return False
            self.state.cancelled = True
            self._bump()
        _signal_group(process, signal.SIGTERM)
        timer = threading.Timer(KILL_AFTER, self._kill_if_alive, args=(process,))
        timer.daemon = True
        timer.start()
        return True

    @staticmethod
    def _kill_if_alive(process: subprocess.Popen) -> None:
        if process.poll() is None:
            print("[runner.py] Run ignored SIGTERM, sending SIGKILL")
            _signal_group(process, signal.SIGKILL)

    def snapshot(self) -> dict:
        """Returns back the current state as a dict"""
        with self.changed:
            return self.state.to_dict()

    def wait_for_change(self, version: int, timeout: float) -> dict:
        """Returns back the state once its version differs from version, or after timeout seconds"""
        with self.changed:
            self.changed.wait_for(lambda: self.state.version != version, timeout)
            return self.state.to_dict()


def _signal_group(process: subprocess.Popen, sig: signal.Signals) -> None:
    """Sends sig to the run's whole process group. Ignores a group that's already gone."""
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass
