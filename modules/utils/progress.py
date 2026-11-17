"""
File: Cully/modules/utils/progress.py
Description: A one-line progress display for pipeline loops, written to stderr so it doesn't mix
with normal output. Off unless asked for, so tests and scripts stay quiet. With use_json() it sends
JSON lines instead, for the web app.
Author: Miguel Macias
Date: 2026-11-16
"""

import json
import sys
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from time import perf_counter
from typing import TextIO, TypeVar

T = TypeVar("T")

JSON_INTERVAL = 0.1  # seconds between progress events, about 10 a second

# Set by use_json(); when set, progress goes out as JSON lines instead of a terminal line
_json_out: TextIO | None = None


def use_json(stream: TextIO) -> None:
    """Sends progress as one JSON object per line to stream."""
    global _json_out
    _json_out = stream


def emit(event: str, **fields) -> None:
    """Writes one JSON event line, when JSON mode is on."""
    if _json_out is None:
        return
    _json_out.write(json.dumps({"event": event, **fields}) + "\n")
    _json_out.flush()


def _clock(seconds: float) -> str:
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes}:{seconds:02d}"


def track(
    items: Iterable[T],
    label: str,
    enabled: bool = False,
    total: int | None = None,
    describe: Callable[[T], str] | None = None,
) -> Iterator[T]:
    """Tracks total progress of the step we are on and written out into the terminal    """
    if not enabled:
        yield from items
        return

    if total is None:
        total = len(items) if hasattr(items, "__len__") else 0  # type: ignore[arg-type]
    start = perf_counter()
    done = 0
    json_mode = _json_out is not None
    last_emit = -JSON_INTERVAL
    # A redrawn line only makes sense on a terminal, so print nothing when output goes to a file
    live = sys.stderr.isatty() and not json_mode

    def draw(current: str = "") -> None:
        elapsed = perf_counter() - start
        if total:
            left = _clock(elapsed / done * (total - done)) if done else "?:??"
            line = f"  {label} {done}/{total} ({done * 100 // total}%) {_clock(elapsed)} elapsed, ~{left} left"
        else:
            line = f"  {label} {done} {_clock(elapsed)} elapsed"
        if current:
            line += f"  {current}"
        # Pad to clear leftovers from a longer previous line
        sys.stderr.write("\r" + line[:120].ljust(120))
        sys.stderr.flush()

    try:
        for item in items:
            if json_mode:
                # Throttled, a fast step would otherwise flood the reader
                now = perf_counter()
                if now - last_emit >= JSON_INTERVAL:
                    emit("progress", step=label, done=done, total=total,
                         file=describe(item) if describe else "")
                    last_emit = now
            elif live:
                draw(describe(item) if describe else "")
            yield item
            done += 1
        # Always send the final count
        emit("progress", step=label, done=done, total=total, file="")
    finally:
        if live:
            sys.stderr.write("\r" + " " * 120 + "\r")  # clear the line, the step prints its own summary
            sys.stderr.flush()


def file_name(path: str | Path | None) -> str:
    """Short name for a photo path, for track's describe."""
    return Path(path).name if path else ""
