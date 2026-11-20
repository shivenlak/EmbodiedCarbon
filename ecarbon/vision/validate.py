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
    return quote.strip() or None


def validate(
    page: pymupdf.Page, sheet_no: str | None, task: Task, answer: dict | None, dpi: int
) -> list[Reading]:
    if not answer or not answer.get("found"):
        return []
    spans = page_spans(page)
    raster = not spans
    out: list[Reading] = []
    for field, q in answer.items():
        if not isinstance(q, dict) or not q.get("quote") or len(q.get("box") or []) != 4:
            continue
        quote = q["quote"].strip()
        value = _value(task, field, quote)
        if value is None:
            log.info("vision drop %s/%s: %r does not parse", task, field, quote)
            continue
        near = box_to_points(page, q["box"], dpi)
        where = sheet_no or f"page {page.number + 1}"
        if raster:
            out.append(
                Reading(
                    field,
                    quote,
                    value,
                    tuple(near),
                    Confidence.INFERRED,
                    f"vision: {where}: '{quote}' ({RASTER_NOTE})",
                )
            )
            continue
        found = locate(spans, quote, near)
        if found is None:
            log.info("vision drop %s/%s: %r not printed near %s", task, field, quote, tuple(near))
            continue
        out.append(
            Reading(
                field,
                quote,
                value,
                tuple(found),
                Confidence.INFERRED,
                f"vision: {where}: '{quote}'",
            )
        )
    return out
