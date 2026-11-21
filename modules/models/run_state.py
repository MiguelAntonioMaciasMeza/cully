"""
File: Cully/modules/models/run_state.py
Description: The state of one pipeline run started from the web app, as the page shows it.
Author: Miguel Macias
Date: 2026-11-21
"""

from collections import deque
from dataclasses import dataclass, field

LOG_LINES_SHOWN = 50


@dataclass
class FinishedStep:
    """One step that ended, with main.py's one-line result"""
    step: str
    result: str
    seconds: float


@dataclass
class RunState:
    """Everything the page needs to draw a run. version goes up on every change."""
    running: bool = False
    folder: str | None = None
    steps: list[str] = field(default_factory=list)
    current_step: str | None = None
    done: int = 0
    total: int = 0
    file: str = ""
    finished: list[FinishedStep] = field(default_factory=list)
    summary: dict | None = None  # main.py's "done" event: bursts, candidates, unranked
    cancelled: bool = False
    exit_code: int | None = None
    error: str | None = None
    log: deque[str] = field(default_factory=lambda: deque(maxlen=200))
    started_at: float | None = None  # epoch seconds
    step_started_at: float | None = None
    version: int = 0

    def to_dict(self) -> dict:
        """Returns back the state as JSON-ready values, with only the last log lines"""
        return {
            "running": self.running,
            "folder": self.folder,
            "steps": list(self.steps),
            "current_step": self.current_step,
            "done": self.done,
            "total": self.total,
            "file": self.file,
            "finished": [vars(step).copy() for step in self.finished],
            "summary": self.summary,
            "cancelled": self.cancelled,
            "exit_code": self.exit_code,
            "error": self.error,
            "log": list(self.log)[-LOG_LINES_SHOWN:],
            "started_at": self.started_at,
            "step_started_at": self.step_started_at,
            "version": self.version,
        }
