"""STEP 19b -- windows and doors, from the openings schedule plus the plans.

Sheet A004 carries two tables. From AB_Fourplex_01:

    TAG    TYPE          METRIC (mm)    IMPERIAL
    DA01   DOOR TYPE A   914 x 2350     3'-0" x 7'-8 1/2"     N/A
    DA02   DOOR TYPE A   914 x 2350     3'-0" x 7'-8 1/2"     45 min
    WB01   WINDOW TYPE B  ...

The schedule gives each tag's size but not how many of them the building has.
That count is on the floor plans, where the tag is written against every
opening, so the quantity is the product of two different sheets: size from the
schedule, count from the plans.

### Alternative plans of the same floor double the count

AB_Fourplex_01 has three readable plan sheets:

    A101   MAIN FLOOR PLAN - ACCESSIBLE READY         18 windows, 24 doors
    A101a  MAIN FLOOR PLAN - ENHANCED ACCESSIBILITY   18 windows, 30 doors
    A102   SECOND FLOOR PLAN                          20 windows, 16 doors

A101 and A101a are two versions of the *same storey*, offered as accessibility
options. Summing every plan sheet counts the main floor twice and yields 56
windows and 70 doors for a building that has 42 and 40.

The sheet number says which is which: a trailing lowercase letter marks a
variant of the base sheet, so plan sheets are grouped by base number and only
one of each group is counted. Taking the base variant gives **40 doors against
the IFC's 40, exactly**, and 38 windows against 42.

The remaining window shortfall is honest and reported: a tag written once
against a mullioned assembly, or a window shown only on an elevation, is not
counted here. Which accessibility option a builder actually builds is their
decision, so the choice is recorded as an assumption on every line rather than
hidden -- it is worth 6 doors on this design.

### Dual units are a free check

Every row states both metric and imperial, so the two can be compared: 914 mm
against 3'-0" agrees to 0.4 mm. A row where they disagree is the sheet
contradicting itself and is reported rather than averaged.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

from ecarbon.extract.assemblies import _parse_inches, _spans

# DA01, DB02, WA01, WC01 -- discipline letter, type letter, instance number.
OPENING_TAG_RE = re.compile(r"^([DW])([A-Z])(\d{2})$")
# A trailing lowercase letter marks a variant of the base sheet: A101a of A101.
_VARIANT_SUFFIX_RE = re.compile(r"^([A-Z]{1,2}\d{2,4})[a-z]$")

# A bare millimetre dimension in a schedule cell: 914, 2350.
_MM_CELL_RE = re.compile(r"^(\d{3,5})$")
# 3'-0", 7'-8 1/2"
_FT_IN_RE = re.compile(r"^(\d+)'\s*-\s*([\d\s/]+)\"$")

# Metric and imperial for one opening may disagree by this much before the
# sheet is treated as contradicting itself.
UNIT_TOLERANCE_MM = 5.0
# Plausible opening dimensions, to reject a stray number in a comments column.
MIN_OPENING_MM = 300.0
MAX_OPENING_MM = 4000.0
# Two cells belong to the same schedule row within this many points.
ROW_DY = 3.5


def base_sheet(sheet_no: str | None) -> str | None:
    """The sheet a variant belongs to: A101a -> A101, A101 -> A101."""
    if not sheet_no:
        return None
    m = _VARIANT_SUFFIX_RE.match(sheet_no)
    return m.group(1) if m else sheet_no


def parse_ft_in(text: str) -> float | None:
    """Millimetres from a feet-and-inches cell, or None."""
    m = _FT_IN_RE.match(text.strip())
    if not m:
        return None
    inches = _parse_inches(m.group(2) + '"')
    return round((float(m.group(1)) * 12.0 + (inches or 0.0)) * 25.4, 1)


@dataclass
class Opening:
    """One row of the door or window schedule."""

    tag: str
    kind: str  # "door" or "window"
    type_name: str = ""
    width_mm: float | None = None
    height_mm: float | None = None
    fire_rating: str | None = None
    note: str | None = None
    sheet: str | None = None
    page: int | None = None
    # Instances of this tag found on the plans, by base sheet number.
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return sum(self.counts.values())

    @property
    def area_m2(self) -> float | None:
        if self.width_mm is None or self.height_mm is None:
            return None
        return round((self.width_mm / 1000.0) * (self.height_mm / 1000.0), 4)

    @property
    def total_area_m2(self) -> float | None:
        area = self.area_m2
        return None if area is None else round(area * self.count, 3)


def _rows(spans: list[tuple[float, float, str]], top: float, bottom: float) -> dict[float, list]:
    """Schedule cells between two y bounds, grouped into rows."""
    out: dict[float, list] = {}
    for y, x, t in spans:
        if not (top < y < bottom):
            continue
        key = next((k for k in out if abs(k - y) <= ROW_DY), y)
        out.setdefault(key, []).append((x, t))
    for cells in out.values():
        cells.sort()
    return out


def openings_on_page(page: pymupdf.Page, sheet: str | None = None) -> list[Opening]:
    """Every door and window row on one openings-schedule sheet."""
    spans = _spans(page)
    # The two tables are stacked, each under its own title.
    titles = [
        (y, t.upper())
        for y, _x, t in spans
        if t.upper() in ("DOOR SCHEDULE", "WINDOW SCHEDULE")
    ]
    if not titles:
        return []
    titles.sort()

    out: list[Opening] = []
    for i, (title_y, title) in enumerate(titles):
        kind = "door" if title.startswith("DOOR") else "window"
        bottom = titles[i + 1][0] if i + 1 < len(titles) else float("inf")

        for _key, cells in sorted(_rows(spans, title_y, bottom).items()):
            tags = [(x, t) for x, t in cells if OPENING_TAG_RE.match(t)]
            if not tags:
                continue
            tag_x, tag = tags[0]
            if tag[0] != kind[0].upper():
                continue
            # Only cells in the table itself. The sheet also carries a DOOR
            # TYPES diagram far to the left whose labels share these y bands,
            # and it put "DOOR TYPE A" on the DD04 row.
            cells = [(x, t) for x, t in cells if x >= tag_x - 20.0]

            # Metric cells, then imperial, left to right as the header orders.
            metric = [
                float(m.group(1))
                for _x, t in cells
                if (m := _MM_CELL_RE.match(t))
                and MIN_OPENING_MM <= float(m.group(1)) <= MAX_OPENING_MM
            ]
            imperial = [v for _x, t in cells if (v := parse_ft_in(t)) is not None]
            type_name = next(
                (t for _x, t in cells if t.upper().startswith(("DOOR TYPE", "WINDOW TYPE"))),
                "",
            )
            rating = next(
                (t for _x, t in cells if re.match(r"^(N/A|\d+\s*min|\d+\s*hr)", t, re.I)), None
            )

            width = metric[0] if len(metric) >= 1 else None
            height = metric[1] if len(metric) >= 2 else None
            note = None

            # The imperial pair is an independent statement of the same sizes.
            if width is not None and len(imperial) >= 1:
                drift = abs(width - imperial[0])
                if drift > UNIT_TOLERANCE_MM:
                    note = (
                        f"schedule states {width:.0f} mm and {imperial[0]:.0f} mm "
                        f"({drift:.0f} mm apart) for the width; the metric value is used"
                    )
            if height is None and len(imperial) >= 2:
                height = imperial[1]
                note = "height taken from the imperial column; metric not stated"

            out.append(
                Opening(
                    tag=tag,
                    kind=kind,
                    type_name=type_name,
                    width_mm=width,
                    height_mm=height,
                    fire_rating=rating,
                    note=note,
                    sheet=sheet,
                    page=page.number,
                )
            )
    return out


def count_on_plans(design, openings: list[Opening]) -> tuple[dict[str, str], list[str]]:
    """Count each tag's instances on the plans, one variant per storey.

    Returns (chosen sheet per base number, notes). The counts are written onto
    the `Opening` objects.
    """
    from ecarbon.intake import inventory
    from ecarbon.models import SheetType

    sheets, _, _ = inventory(design.drawings_pdf)
    plans = [
        s
        for s in sheets
        if s.sheet_type in (SheetType.FLOOR_PLAN, SheetType.FOUNDATION_PLAN) and s.readable
    ]
    by_tag = {o.tag: o for o in openings}

    # Group alternative plans of one storey, and prefer the base sheet.
    groups: dict[str, list] = {}
    for s in plans:
        groups.setdefault(base_sheet(s.sheet_no) or f"p{s.page}", []).append(s)

    chosen: dict[str, str] = {}
    notes: list[str] = []
    doc = pymupdf.open(design.drawings_pdf)
    try:
        for base, members in sorted(groups.items()):
            members.sort(key=lambda s: (s.sheet_no != base, s.sheet_no or ""))
            pick = members[0]
            chosen[base] = pick.sheet_no or f"page {pick.page + 1}"
            if len(members) > 1:
                others = ", ".join(str(m.sheet_no) for m in members[1:])
                notes.append(
                    f"Sheets {pick.sheet_no} and {others} are alternative versions of the "
                    f"same storey, so only {pick.sheet_no} is counted. Counting both would "
                    f"double that floor's openings. Which option is built is the builder's "
                    f"decision and changes the count."
                )
            found = Counter(
                t for _y, _x, t in _spans(doc[pick.page]) if OPENING_TAG_RE.match(t)
            )
            for tag, n in found.items():
                if tag in by_tag:
                    by_tag[tag].counts[chosen[base]] = n
    finally:
        doc.close()
    return chosen, notes


def openings_for(design) -> tuple[list[Opening], list[str]]:
    """Every scheduled opening with its instance count, plus any notes."""
    from ecarbon.intake import inventory
    from ecarbon.models import SheetType

    sheets, _, _ = inventory(design.drawings_pdf)
    found: list[Opening] = []
    doc = pymupdf.open(design.drawings_pdf)
    try:
        for s in sheets:
            if s.sheet_type is not SheetType.OPENING_SCHEDULE or not s.readable:
                continue
            found.extend(openings_on_page(doc[s.page], s.sheet_no))
    finally:
        doc.close()

    notes: list[str] = []
    if found:
        _chosen, notes = count_on_plans(design, found)
    return found, notes
