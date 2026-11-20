"""Quote-and-locate: a vision answer is kept only if it can show its source.

On a vector page the quote must be in the page's own text, at or near where
the model says it is; otherwise it is dropped and the drop logged. On a raster
page there is no text to check, so the answer is kept but capped at INFERRED.
Numbers come from parsing the quote, never from the model.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import pymupdf

from ecarbon.geometry.scale import parse_dimension, parse_scale_text
from ecarbon.intake.textrepair import repair
from ecarbon.models import Confidence
from ecarbon.vision.tasks import Task

log = logging.getLogger(__name__)

# How far outside the model's box (in points) the quoted text may sit.
NEAR_PT = 36.0
RASTER_NOTE = "read from an image; not verifiable against text"


@dataclass(frozen=True)
class Reading:
    field: str
    quote: str
    value: float | str
    bbox: tuple[float, float, float, float]  # PDF points, unrotated page
    confidence: Confidence
    note: str


def _norm(text: str) -> str:
    return re.sub(r"[\s’′]+", "", text).replace("″", '"').upper()


def box_to_points(page: pymupdf.Page, box: list[float], dpi: int) -> pymupdf.Rect:
    """A pixel box on the rendered (rotated) image, as unrotated PDF points."""
    r = pymupdf.Rect(box) * (72.0 / dpi)
    r = r * page.derotation_matrix
    r.normalize()
    return r


def page_spans(page: pymupdf.Page) -> list[tuple[pymupdf.Rect, str]]:
    # read_spans drops the boxes, which locating needs; same repair, kept here.
    return [
        (pymupdf.Rect(s["bbox"]), repair(s["text"].strip())[0])
        for block in page.get_text("dict")["blocks"]
        for line in block.get("lines", [])
        for s in line.get("spans", [])
        if s["text"].strip()
    ]


def locate(spans, quote: str, near: pymupdf.Rect) -> pymupdf.Rect | None:
    """Where `quote` is printed, if it is printed near `near`."""
    zone = pymupdf.Rect(near.x0 - NEAR_PT, near.y0 - NEAR_PT, near.x1 + NEAR_PT, near.y1 + NEAR_PT)
    hits = sorted(
        ((r, t) for r, t in spans if r.intersects(zone)), key=lambda rt: (rt[0].y0, rt[0].x0)
    )
    want = _norm(quote)
    if not want:
        return None
    # One span, or a run of neighbours (a dimension can be split across spans).
    for i in range(len(hits)):
        joined, rect = "", pymupdf.Rect(hits[i][0])
        for r, t in hits[i : i + 4]:
            joined += _norm(t)
            rect |= r
            if want in joined:
                return rect
    return None


def _value(task: Task, field: str, quote: str) -> float | str | None:
    if task is Task.SCALE:
        return parse_scale_text(quote)
    if task is Task.FOOTPRINT:
        return parse_dimension(quote)[0]
    if task is Task.LEVELS:
        from ecarbon.extract.levels import _LEVEL_LABEL_RE, _elevation_m

        if field == "label":
            return quote if _LEVEL_LABEL_RE.search(quote) else None
        return _elevation_m(quote)
    return quote.strip() or None


def _check(page, spans, where: str, task: Task, field: str, q, dpi: int) -> Reading | None:
    """One quoted field, located in the page text (or capped on a raster page)."""
    if not isinstance(q, dict) or not q.get("quote") or len(q.get("box") or []) != 4:
        return None
    quote = q["quote"].strip()
    value = _value(task, field, quote)
    if value is None:
        log.info("vision drop %s/%s: %r does not parse", task, field, quote)
        return None
    near = box_to_points(page, q["box"], dpi)
    if not spans:
        return Reading(
            field,
            quote,
            value,
            tuple(near),
            Confidence.INFERRED,
            f"vision: {where}: '{quote}' ({RASTER_NOTE})",
        )
    found = locate(spans, quote, near)
    if found is None:
        log.info("vision drop %s/%s: %r not printed near %s", task, field, quote, tuple(near))
        return None
    return Reading(
        field, quote, value, tuple(found), Confidence.INFERRED, f"vision: {where}: '{quote}'"
    )


def validate(
    page: pymupdf.Page, sheet_no: str | None, task: Task, answer: dict | None, dpi: int
) -> list[Reading]:
    if not answer or not answer.get("found"):
        return []
    spans = page_spans(page)
    where = sheet_no or f"page {page.number + 1}"
    if task is Task.LEVELS:
        # A datum counts only when both its label and its elevation check out;
        # the reading is the elevation, named by its label.
        out = []
        for datum in answer.get("datums") or []:
            label = _check(page, spans, where, task, "label", datum.get("label"), dpi)
            elev = _check(page, spans, where, task, "elevation", datum.get("elevation"), dpi)
            if label and elev:
                note = f"vision: {where}: '{label.quote}' '{elev.quote}'"
                if not spans:
                    note += f" ({RASTER_NOTE})"
                out.append(
                    Reading(label.quote, elev.quote, elev.value, elev.bbox, elev.confidence, note)
                )
        return out
    readings = (_check(page, spans, where, task, f, q, dpi) for f, q in answer.items())
    return [r for r in readings if r is not None]
