"""Answers on disk, so a page is paid for once.

Keyed by the image, the task, the prompt version and the model. Landmark pages
set ECARBON_VISION_CACHE under ~/ec-data/landmark/ so their answers stay out
of the shared cache.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from ecarbon.vision.tasks import PROMPT_VERSION, TASK_VERSIONS, Task


def cache_dir() -> Path:
    return Path(
        os.environ.get("ECARBON_VISION_CACHE", Path.home() / ".cache" / "ecarbon" / "vision")
    ).expanduser()


def max_classify_pages() -> int:
    """Pages vision may classify (Task.SHEET) where the rules typed none."""
    return int(os.environ.get("ECARBON_VISION_MAX_CLASSIFY", "60"))


def max_pages() -> int:
    return int(os.environ.get("ECARBON_VISION_MAX_PAGES", "12"))


def key(png: bytes, task: Task, provider: str, model: str) -> str:
    h = hashlib.sha256(png)
    h.update(f"|{task}|{TASK_VERSIONS.get(task, PROMPT_VERSION)}|{provider}/{model}".encode())
    return h.hexdigest()


def cached_read(provider, png: bytes, task: Task) -> dict | None:
    name = f"{key(png, task, provider.name, provider.model)}.json"
    path = cache_dir() / name
    # A read-only store to copy answers from, so staging a deployment carries
    # only the answers its own sets use (deploy/prebuild.py).
    seed = os.environ.get("ECARBON_VISION_SEED")
    if not path.exists() and seed and (Path(seed).expanduser() / name).exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((Path(seed).expanduser() / name).read_text())
    if path.exists():
        return json.loads(path.read_text())
    answer = provider.read(png, task)
    # A failed call is not cached, so a retry can succeed.
    if answer is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(answer))
    return answer
