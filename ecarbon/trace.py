"""Click-to-trace: given a bill-of-quantities line, where on the sheet it came from.

Criterion 2 asks that every quantity be traceable back to the sheet and detail
it came from. A sheet number in a table is the weak form of that; showing the
reader the actual region is the strong form, and it is also the honest one,
because a highlight that lands on the wrong thing is immediately visible in a
way that a wrong number in a cell is not.

Three kinds of region, and they are *not* equivalent claims:

``measured_geometry``
    The linework that was measured. The strongest trace: the rectangles are the
    walls whose lengths were summed, so the highlight *is* the measurement.

``schedule_row``
    The row of the schedule the figure was read from. The number came from this
    text, so the highlight is its real source, but the quantity was computed
    from it rather than measured off the page.

``sheet_only``
    We can name the sheet but cannot locate the region on it. Reported as such
    instead of highlighting something plausible -- the same discipline the gap
    report applies to everything else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf

from ecarbon.models import TakeoffLine, TakeoffResult

# A partition line's id carries its storey-spanning measurement, so it resolves
# through the geometry rather than through text.
_PARTITION_RE = re.compile(r"^ln-interior-partition", re.I)
# Text that names a thing rather than describing it; searching for a long prose
# detail finds nothing, so the search falls back to the leading tag.
_TAG_RE = re.compile(r"^([A-Z]{1,3}\d+(?:\.\d+)?)\b")

MAX_RECTS = 400


@dataclass
class TraceRegion:
    """Where one line's quantity came from, on one page."""

    page: int
    sheet_no: str | None
    kind: str
    note: str
    rects: list[tuple[float, float, float, float]] = field(default_factory=list)
    page_width: float = 0.0
    page_height: float = 0.0

    @property
    def located(self) -> bool:
        return self.kind != "sheet_only"


def _page_size(doc: pymupdf.Document, page_no: int) -> tuple[float, float]:
    rect = doc[page_no].rect
    return (rect.width, rect.height)


def _search(page: pymupdf.Page, needle: str) -> list[tuple[float, float, float, float]]:
    """Rectangles of a literal string on the page, rotation-corrected by pymupdf."""
    if not needle or len(needle) < 2:
        return []
    try:
        found = page.search_for(needle, quads=False)
    except Exception:
        return []
    return [(r.x0, r.y0, r.x1, r.y1) for r in found[:MAX_RECTS]]


def _text_region(
    doc: pymupdf.Document, line: TakeoffLine
) -> TraceRegion | None:
    """The schedule row or callout whose text produced this quantity."""
    page_no = line.provenance.page
    if page_no is None or page_no >= doc.page_count:
        return None
    page = doc[page_no]
    detail = (line.provenance.detail or "").strip()

    # The full detail first, since that is the exact row. If the detail is a
    # long assembly name the drawing wraps, fall back to its tag, which is what
    # a reader would scan for anyway.
    rects = _search(page, detail)
    found_by = detail
    if not rects:
        tag = _TAG_RE.match(detail)
        for candidate in (tag.group(1) if tag else None, line.assembly_tag):
            if candidate:
                rects = _search(page, candidate)
                if rects:
                    found_by = candidate
                    break
    if not rects:
        return None

    w, h = _page_size(doc, page_no)
    return TraceRegion(
        page=page_no,
        sheet_no=line.provenance.sheet_no,
        kind="schedule_row",
        note=f"Read from {found_by!r} on this sheet.",
        rects=rects,
        page_width=w,
        page_height=h,
    )


def _partition_regions(
    doc: pymupdf.Document, design, line: TakeoffLine
) -> list[TraceRegion]:
    """The partition walls that were measured, per storey."""
    from ecarbon.geometry.partitions import partitions_for

    try:
        measured = partitions_for(design)
    except Exception:
        return []
    out: list[TraceRegion] = []
    for run in measured.runs:
        if not run.rects or run.page >= doc.page_count:
            continue
        w, h = _page_size(doc, run.page)
        out.append(
            TraceRegion(
                page=run.page,
                sheet_no=run.sheet,
                kind="measured_geometry",
                note=(
                    f"{run.n_walls} partition walls measured on this sheet, "
                    f"{run.length_m:.1f} m of run. Every highlighted rectangle is "
                    "one wall whose length is in the total."
                ),
                rects=list(run.rects),
                page_width=w,
                page_height=h,
            )
        )
    return out


def trace_line(design, takeoff: TakeoffResult, line_id: str) -> list[TraceRegion]:
    """Where a line's quantity came from. Empty list if the line is unknown.

    A line can trace to more than one page -- interior partitions are measured
    on every storey -- so this returns a region per page rather than pretending
    one rectangle covers it.
    """
    line = next((ln for ln in takeoff.lines if ln.id == line_id), None)
    if line is None:
        return []

    doc = pymupdf.open(design.drawings_pdf)
    try:
        # 1. An explicit bbox, if an extractor ever records one.
        box = line.provenance.bbox
        if box and line.provenance.page is not None:
            w, h = _page_size(doc, line.provenance.page)
            return [
                TraceRegion(
                    page=line.provenance.page,
                    sheet_no=line.provenance.sheet_no,
                    kind="measured_geometry",
                    note="Recorded by the extractor that measured this quantity.",
                    rects=[box],
                    page_width=w,
                    page_height=h,
                )
            ]

        # 2. Measured linework, where a geometry module kept its coordinates.
        if _PARTITION_RE.match(line_id):
            regions = _partition_regions(doc, design, line)
            if regions:
                return regions

        # 3. The text the figure was read from.
        region = _text_region(doc, line)
        if region is not None:
            return [region]

        # 4. Say so rather than highlight something plausible.
        page_no = line.provenance.page
        if page_no is None or page_no >= doc.page_count:
            return []
        w, h = _page_size(doc, page_no)
        return [
            TraceRegion(
                page=page_no,
                sheet_no=line.provenance.sheet_no,
                kind="sheet_only",
                note=(
                    "This sheet is the source, but the exact region could not be "
                    "located on it. Nothing is highlighted rather than guessing."
                ),
                page_width=w,
                page_height=h,
            )
        ]
    finally:
        doc.close()


def render_page(
    design,
    page_no: int,
    rects: list[tuple[float, float, float, float]] | None = None,
    dpi: int = 110,
) -> bytes:
    """The page as a PNG, with any rectangles drawn over it.

    The highlight is drawn on a copy for display only; nothing is written back
    to the drawings. CMHC's licence forbids redistributing the designs, so this
    output is for the person running the tool and must not be served publicly.
    """
    doc = pymupdf.open(design.drawings_pdf)
    try:
        if page_no >= doc.page_count:
            raise IndexError(f"page {page_no} beyond {doc.page_count}")
        page = doc[page_no]
        for rect in rects or []:
            x0, y0, x1, y1 = rect
            # A measured wall can be a hairline; pad so it stays visible, and
            # draw the outline rather than a fill so the linework stays legible.
            pad = 1.5
            annot = page.add_rect_annot(
                pymupdf.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
            )
            annot.set_colors(stroke=(0.85, 0.15, 0.1))
            annot.set_border(width=1.2)
            annot.set_opacity(0.9)
            annot.update()
        return page.get_pixmap(dpi=dpi).tobytes("png")
    finally:
        doc.close()
