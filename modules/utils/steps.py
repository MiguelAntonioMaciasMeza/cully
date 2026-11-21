"""
File: Cully/modules/utils/steps.py
Description: The pipeline's step names in run order. Kept apart from main.py so the web server can
know them without importing main.py (which loads torch).
Author: Miguel Macias
Date: 2026-11-21
"""

STEPS = ["scan", "objects", "faces", "landmarks", "embeddings", "sharpness", "ranking"]


def default_steps(embeddings: bool) -> list[str]:
    """Returns back every step in order, with embeddings only when asked for"""
    return [step for step in STEPS if step != "embeddings" or embeddings]
