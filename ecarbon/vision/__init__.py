"""A fallback reader, used only where the rules came back empty.

Off unless ECARBON_VISION is set. Every value it returns has been located in
the page's own text (or, on a raster page, is capped at INFERRED and says so).
"""

from __future__ import annotations

import pymupdf

from ecarbon.vision.cache import cached_read
from ecarbon.vision.providers import provider_from_env
from ecarbon.vision.tasks import Task
from ecarbon.vision.validate import Reading, validate

DPI = 110  # as trace.render_page

__all__ = ["DPI", "Reading", "Task", "read_page", "provider_from_env"]


def read_page(provider, page: pymupdf.Page, sheet_no: str | None, task: Task) -> list[Reading]:
    png = page.get_pixmap(dpi=DPI).tobytes("png")
    return validate(page, sheet_no, task, cached_read(provider, png, task), DPI)
