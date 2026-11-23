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
# Claude rejects an image over 10 MB; a large NOR sheet renders at 14.2 MB.
MAX_PNG_BYTES = 9_000_000

__all__ = ["DPI", "Reading", "Task", "read_page", "render", "provider_from_env"]


def read_page(provider, page: pymupdf.Page, sheet_no: str | None, task: Task) -> list[Reading]:
    png, dpi = render(page)
    return validate(page, sheet_no, task, cached_read(provider, png, task), dpi)


def render(page: pymupdf.Page) -> tuple[bytes, int]:
    """The page as PNG at DPI, or at a lower dpi if that is too large to send.

    Returns the dpi used, which validate needs to map boxes back to points."""
    dpi = DPI
    png = page.get_pixmap(dpi=dpi).tobytes("png")
    while len(png) > MAX_PNG_BYTES and dpi > 40:
        dpi = int(dpi * (MAX_PNG_BYTES / len(png)) ** 0.5 * 0.95)
        png = page.get_pixmap(dpi=dpi).tobytes("png")
    return png, dpi
