"""Stair flights read off the floor plans.

The plans label each flight "16 RISERS @ 191mm" and mark its foot "UP". A
flight is drawn on the floor it leaves and the one it reaches, so the riser
labels come in pairs. Against the IFC's IfcStairFlight count, max(UP arrows,
riser labels / 2) gives AB_Fourplex_01 2/2, AB_Sixplex 5/5, BC_Fourplex_02
8/8, QC_Sixplex 6 of its 6 stairs; it undercounts AB_Rowhouse_01 (1 of 4),
never over.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass

import pymupdf

from ecarbon.extract.assemblies import TEXT_DICT, repair_schedule_cell
from ecarbon.intake.textrepair import repair

_RISERS_RE = re.compile(r"^(\d{1,2})\s*RISERS?\s*@\s*(\d{2,3}(?:\.\d)?)\s*mm", re.I)
_UP_RE = re.compile(r"^UP\b", re.I)


@dataclass
class Stairs:
    flights: int
    risers: int  # per flight, the median stated
    rise_mm: float
    page: int
    sheet_no: str | None
    bbox: tuple[float, float, float, float] | None
    up_marks: int
    riser_labels: int


def stairs_on_plans(design) -> Stairs | None:
    """The stair flights the floor plans draw, or None when none are labelled."""
    from ecarbon.intake import inventory
    from ecarbon.models import SheetType

    sheets, _, _ = inventory(design.drawings_pdf)
    labels: list[tuple[int, float, int, str | None, tuple]] = []
    ups = 0
    doc = pymupdf.open(design.drawings_pdf)
    try:
        for s in sheets:
            # One plan per storey: a sheet number ending in a letter is an alternative.
            if s.sheet_type is not SheetType.FLOOR_PLAN or not s.readable:
                continue
            if re.search(r"\d[a-z]$", s.sheet_no or ""):
                continue
            for block in doc[s.page].get_text("dict", flags=TEXT_DICT)["blocks"]:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        t = repair_schedule_cell(repair(span["text"].strip())[0])
                        if _UP_RE.match(t):
                            ups += 1
                        m = _RISERS_RE.match(t)
                        if m and 150 <= float(m.group(2)) <= 220:
                            labels.append((int(m.group(1)), float(m.group(2)), s.page,
                                           s.sheet_no, tuple(span["bbox"])))
    finally:
        doc.close()
    flights = max(ups, math.ceil(len(labels) / 2))
    if not labels or not flights:
        return None
    risers = round(statistics.median(n for n, *_ in labels))
    rise = statistics.median(r for _, r, *_ in labels)
    _, _, page, sheet_no, bbox = labels[0]
    return Stairs(flights, risers, rise, page, sheet_no, bbox, ups, len(labels))
