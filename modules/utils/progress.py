"""
File: Cully/modules/utils/progress.py
Description: A one-line progress display for pipeline loops, written to stderr so it doesn't mix
with normal output. Off unless asked for, so tests and scripts stay quiet.
Author: Miguel Macias
Date: 2026-11-16
"""

import sys
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from time import perf_counter
from typing import TypeVar

T = TypeVar("T")


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
    # A redrawn line only makes sense on a terminal, so print nothing when output goes to a file
    live = sys.stderr.isatty()

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
            if live:
                draw(describe(item) if describe else "")
            yield item
            done += 1
    finally:
        if live:
            sys.stderr.write("\r" + " " * 120 + "\r")  # clear the line, the step prints its own summary
            sys.stderr.flush()


def file_name(path: str | Path | None) -> str:
    """Short name for a photo path, for track's describe."""
    return Path(path).name if path else ""
