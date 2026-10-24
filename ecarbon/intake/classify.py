"""STEP 7 -- sheet identification and typing, from the page alone.

A three-rung ladder, best source first. Which rung fired is recorded in
`SheetInfo.classified_by`, so the confidence of everything downstream can be
traced back to how well we knew what we were looking at.

  1. Revit page metadata  -- exact, free, no guessing (RESEARCH.md §4a)
  2. Title-block text     -- the sheet number is the largest sheet-number-shaped
                             token on the page; the title sits just above it
  3. unresolved           -- reported as a gap, never guessed

Deliberately NOT used here: the `List of Drawings` PDF. It ships inside the
catalogue packages and would make this trivial, but Landmark's sets may not
include one, and it is our scoring ground truth (ecarbon/bench/sheet_truth.py).
Using it as an input would make the benchmark meaningless. `index_hint()` is
provided separately for production use, where reading it IS the right thing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf

from ecarbon.intake.textrepair import FontRepair, looks_broken
from ecarbon.models import BasisSource, Discipline, SheetType

# A000, A101a, S102, M000, E201A. Two letters occur on civil/landscape sheets.
SHEET_NO_RE = re.compile(r"^([A-Z]{1,2})(\d{2,4})([a-zA-Z])?$")

# Boilerplate that appears in every title block and is never the sheet title.
TITLE_BLOCK_NOISE = (
    "CMHC",
    "HOUSING DESIGN",
    "CATALOGUE",
    "NOT FOR PERMIT",
    "OR CONSTRUCTION",
    "DISCLAIMER",
    "SCALE",
    "DRAWN",
    "CHECKED",
    "PROJECT",
    "SHEET NO",
    "DATE",
    "REVISION",
    "NORTH",
    "SEAL",
    "ISSUED",
    "NO.",
)

# Title -> SheetType. Order matters: the first match wins, so the most specific
# phrases come first. Keys are matched against the upper-cased title.
TYPE_RULES: tuple[tuple[tuple[str, ...], SheetType], ...] = (
    (("ASSEMBLIES SCHEDULE", "ASSEMBLY SCHEDULE", "ASSEMBLIES"), SheetType.ASSEMBLY_SCHEDULE),
    (
        (
            "OPENINGS SCHEDULE",
            "OPENING SCHEDULE",
            "DOOR & WINDOW SCHEDULE",
            "DOOR AND WINDOW SCHEDULE",
            "WINDOW & DOOR SCHEDULE",
            "WINDOW AND DOOR SCHEDULE",
            "WINDOW SCHEDULE",
            "DOOR SCHEDULE",
        ),
        SheetType.OPENING_SCHEDULE,
    ),
    (("TITLE PAGE", "TITLE SHEET"), SheetType.TITLE),
    (("COVER SHEET", "COVER PAGE", "DRAWINGS COVER", "COVER"), SheetType.COVER),
    (("SITE PLAN",), SheetType.SITE_PLAN),
    (("FOUNDATION PLAN", "FOOTING PLAN"), SheetType.FOUNDATION_PLAN),
    (("ROOF PLAN",), SheetType.ROOF_PLAN),
    (("FRAMING PLAN", "FLOOR FRAMING", "ROOF FRAMING"), SheetType.FRAMING_PLAN),
    (("FLOOR PLAN", "SUITE PLAN", "UNIT PLAN"), SheetType.FLOOR_PLAN),
    (("ELEVATION",), SheetType.ELEVATION),
    # "TYPICAL SECTION DETAILS" is a detail sheet, so DETAIL is tested first.
    (("DETAIL",), SheetType.DETAIL),
    (("SECTION",), SheetType.SECTION),
    (("SPECIFICATION", "SPECS"), SheetType.SPECIFICATION),
    (("LEGEND", "GENERAL NOTES", "NOTES", "ABBREVIATION"), SheetType.LEGEND),
    (("SCHEDULE", "MATRIX"), SheetType.SCHEDULE_OTHER),
)

# Mechanical and electrical sheets borrow architectural words ("M100 FOUNDATION
# PLAN"), so discipline overrides the title for those two.
_MEP_OVERRIDE = {Discipline.MECHANICAL: SheetType.MECHANICAL, Discipline.ELECTRICAL: SheetType.ELECTRICAL}


@dataclass
class Span:
    size: float
    x: float
    y: float
    text: str
    font: str = ""
    repaired: bool = False


def _spans(page: pymupdf.Page, repair: FontRepair | None = None) -> list[Span]:
    """Positioned text spans, with glyph-ID text repaired where possible.

    Two passes are needed because the repair shift is solved per font from a
    sample: we have to see all of a font's text before we can decode any of it.
    """
    raw: list[Span] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for s in line.get("spans", []):
                t = s["text"].strip()
                if t:
                    raw.append(
                        Span(round(s["size"], 1), s["bbox"][0], s["bbox"][1], t, s.get("font", ""))
                    )

    fix = repair
    if fix is None:
        fix = FontRepair()
        for s in raw:
            fix.observe(s.font, s.text)

    out: list[Span] = []
    for s in raw:
        text, repaired = fix.repair(s.font, s.text)
        if looks_broken(text):
            # Undecodable: a wrong title is worse than an admitted unknown.
            continue
        out.append(Span(s.size, s.x, s.y, text, s.font, repaired))
    return out


def discipline_of(sheet_no: str | None) -> Discipline:
    if not sheet_no:
        return Discipline.UNKNOWN
    m = SHEET_NO_RE.match(sheet_no.strip().upper())
    head = (m.group(1) if m else sheet_no.strip().upper())[:1]
    try:
        return Discipline(head)
    except ValueError:
        return Discipline.UNKNOWN


def sheet_type_of(title: str | None, discipline: Discipline = Discipline.UNKNOWN) -> SheetType:
    """Map a sheet title to a type. Returns UNKNOWN rather than guessing."""
    if not title:
        return SheetType.UNKNOWN
    up = re.sub(r"\s+", " ", title.upper())

    matched = SheetType.UNKNOWN
    for needles, kind in TYPE_RULES:
        if any(n in up for n in needles):
            matched = kind
            break

    # A mechanical/electrical sheet is only useful to us as MEP, except that a
    # cover or schedule sheet keeps its own type so coverage checks still work.
    if discipline in _MEP_OVERRIDE and matched not in {
        SheetType.COVER,
        SheetType.TITLE,
        SheetType.SPECIFICATION,
        SheetType.LEGEND,
        SheetType.UNKNOWN,
    }:
        return _MEP_OVERRIDE[discipline]
    if matched is SheetType.UNKNOWN and discipline in _MEP_OVERRIDE:
        return _MEP_OVERRIDE[discipline]
    return matched


def _is_noise(text: str) -> bool:
    up = text.upper()
    return any(n in up for n in TITLE_BLOCK_NOISE)


def from_title_block(
    page: pymupdf.Page, repair: FontRepair | None = None
) -> tuple[str | None, str | None]:
    """Rung 2: read the sheet number and title out of the title block.

    The sheet number is the largest sheet-number-shaped token on the page -- on
    these sets it is set at ~51 pt while body text is 8-24 pt. Font size is used
    rather than position because mechanical sheets rotate the page and move the
    title block, so a bottom-right-quadrant rule misses them entirely.
    """
    spans = _spans(page, repair)
    if not spans:
        return None, None

    cands = [s for s in spans if SHEET_NO_RE.match(s.text.upper())]
    if not cands:
        return None, None
    num = max(cands, key=lambda s: s.size)
    # Guard: a sheet number is set much larger than the cross-reference bubbles
    # that share its shape (10 pt and 8 pt on these sets).
    if num.size < 1.8 * min(s.size for s in spans):
        return None, None
    sheet_no = num.text.strip()

    # The title is the nearest run of large, non-boilerplate text to the sheet
    # number. Distance rather than "same column, above" because mechanical and
    # electrical sheets are exported with /Rotate 90, which moves the title
    # block and re-flows its columns -- a column rule silently loses every
    # M- and E- sheet.
    diag = (page.rect.width**2 + page.rect.height**2) ** 0.5
    radius = 0.18 * diag

    def dist(s: Span) -> float:
        return ((s.x - num.x) ** 2 + (s.y - num.y) ** 2) ** 0.5

    near = [
        s
        for s in spans
        if s is not num
        and s.size >= 0.35 * num.size
        and not _is_noise(s.text)
        and dist(s) <= radius
    ]
    if not near:
        return sheet_no, None

    # The title is set at one size; take the size-group containing the closest
    # qualifying span and drop anything else (project name, discipline banner).
    closest = min(near, key=dist)
    block = [s for s in near if abs(s.size - closest.size) < 0.6]
    block.sort(key=lambda s: (round(s.y / max(closest.size, 1.0)), s.x))
    title = re.sub(r"\s+", " ", " ".join(s.text for s in block)).strip(" -–,")
    return sheet_no, title or None


def classify_page(
    page: pymupdf.Page,
    revit_sheet_no: str | None = None,
    revit_title: str | None = None,
    repair: FontRepair | None = None,
) -> tuple[str | None, str | None, SheetType, Discipline, BasisSource | None]:
    """Run the ladder. Returns (sheet_no, title, type, discipline, source)."""
    if revit_sheet_no or revit_title:
        sheet_no, title, src = revit_sheet_no, revit_title, BasisSource.REVIT_METADATA
    else:
        sheet_no, title = from_title_block(page, repair)
        src = BasisSource.VECTOR_PATH if sheet_no else None

    disc = discipline_of(sheet_no)
    return sheet_no, title, sheet_type_of(title, disc), disc, src
