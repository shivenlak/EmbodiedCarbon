"""Takeoffs computed ahead of time, loaded at request time.

Parsing a drawing set costs about 23 seconds on a shared core and 177 for the
largest in the catalogue. That cost used to fall on whoever opened the link
first, and again after every restart, because the only cache was in memory.
For a service whose job is to be opened and looked at, that is the wrong
moment to pay it.

`deploy/prebuild.py` writes these files at image-build time; this module reads
them. The split matters: generating them needs the whole pipeline, loading
them needs only the model, so the running image carries no build-time code.

The takeoff is a pydantic model and round-trips through JSON exactly, so a
prebuilt answer is the same object a live parse produces -- verified by
comparison, not assumed. Carbon is still computed on load, because it is cheap
and because it must follow the current factor store rather than a snapshot
taken whenever the image happened to be built.
"""

from __future__ import annotations

from pathlib import Path

PREBUILT_DIRNAME = "_prebuilt"


def prebuilt_path(data_root: Path, key: str) -> Path:
    return Path(data_root) / PREBUILT_DIRNAME / f"{key}.json"


def load_prebuilt(data_root: Path, key: str, drawings_pdf: Path | None = None):
    """A saved takeoff, if one exists and is not older than its drawings.

    The mtime check is what keeps this honest: a prebuilt file older than the
    PDF beside it is stale, and serving it would let the deployment and the
    repository quietly disagree about what a design contains. A corrupt or
    unreadable cache returns None, because it must never be worse than having
    no cache at all.
    """
    from ecarbon.models import TakeoffResult

    path = prebuilt_path(data_root, key)
    try:
        if not path.is_file():
            return None
        if drawings_pdf is not None and Path(drawings_pdf).is_file():
            if path.stat().st_mtime < Path(drawings_pdf).stat().st_mtime:
                return None
        return TakeoffResult.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None
