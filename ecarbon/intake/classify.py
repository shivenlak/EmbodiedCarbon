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
from pathlib import Path

import pymupdf

from ecarbon.intake.textrepair import FontRepair, looks_broken
from ecarbon.models import BasisSource, Discipline, SheetType

# A000, A101a, S102, M000, E201A. Two letters occur on civil/landscape sheets.
# US sets hyphenate or dot the number instead: A-901, S-1, G-001, A2.1, and
# prefix it with a plan or series number: A3-101, T24-301. A bare single digit
# (A1) stays out: it is the shape of a grid or detail bubble, and so do stair
# arrows (UP14R, DN14R: up or down, fourteen risers). UK ISO 19650 / BS 1192
# numbers lead with project, originator, volume and level before `DR`, then
# the role and number (PRJ-ORG-ZZ-00-DR-A-1001); the role is the discipline.
SHEET_NO_RE = re.compile(
    r"^(?:[A-Z0-9]{2,6}(?:-[A-Z0-9]{1,6}){2,4}-DR-)?"
    r"(?!UP|DN)([A-Z]{1,2})(\d{2,4}|\d{0,2}-\d{1,4}|\d{1,2}\.\d{1,2})([a-zA-Z])?$"
)

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
    # US sets call the schedule "WALL TYPES".
    (("ASSEMBLIES SCHEDULE", "ASSEMBLY SCHEDULE", "ASSEMBLIES", "WALL TYPES"), SheetType.ASSEMBLY_SCHEDULE),
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
    # UK/AU "GENERAL ARRANGEMENT" (GA) plans are the floor plans.
    (("FLOOR PLAN", "SUITE PLAN", "UNIT PLAN", "GENERAL ARRANGEMENT", "GA PLAN"), SheetType.FLOOR_PLAN),
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
    # "ELEVATIONS & SECTIONS": the sections carry the level datums, and every
    # reader of elevations reads sections too.
    if matched is SheetType.ELEVATION and re.search(r"\bSECTIONS?\b", up):
        matched = SheetType.SECTION

    if matched is SheetType.UNKNOWN:
        # Word order varies between firms: BC titles its foundation plan
        # "PLAN FOUNDATION / MAIN FLOOR" and QC uses "STRUCTURAL PLANS", so
        # the phrase rules above miss both. Fall back to co-occurring words.
        matched = _by_cooccurrence(up)

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


# (required words, type). Order matters: the most specific set first.
_COOCCURRENCE_RULES: tuple[tuple[tuple[str, ...], SheetType], ...] = (
    (("FOUNDATION", "PLAN"), SheetType.FOUNDATION_PLAN),
    (("FOOTING", "PLAN"), SheetType.FOUNDATION_PLAN),
    (("ROOF", "PLAN"), SheetType.ROOF_PLAN),
    (("FRAMING", "PLAN"), SheetType.FRAMING_PLAN),
    (("SITE", "PLAN"), SheetType.SITE_PLAN),
    (("ASSEMBL", "SCHED"), SheetType.ASSEMBLY_SCHEDULE),
    (("WINDOW", "SCHED"), SheetType.OPENING_SCHEDULE),
    (("DOOR", "SCHED"), SheetType.OPENING_SCHEDULE),
    (("FLOOR", "PLAN"), SheetType.FLOOR_PLAN),
    (("STRUCTURAL", "PLAN"), SheetType.FRAMING_PLAN),
)


def _by_cooccurrence(up: str) -> SheetType:
    """Type a title by which words appear in it, ignoring their order."""
    for words, kind in _COOCCURRENCE_RULES:
        if all(w in up for w in words):
            return kind
    return SheetType.UNKNOWN


def type_from_file_name(name: str) -> SheetType:
    """A sheet type from the name of the file a set was delivered in.

    Builders send a set as "Floor Layout.pdf", "Roof Layout.pdf",
    "Foundation.pdf", "Mech & Electrical.pdf". Weaker than a title block, so
    callers use it only when the page itself named nothing.
    """
    up = re.sub(r"[_\-\s]+", " ", Path(name).stem.upper())
    if "MECH" in up or "PLUMBING" in up or "HVAC" in up:
        return SheetType.MECHANICAL
    if "ELECTRICAL" in up:
        return SheetType.ELECTRICAL
    if "LAYOUT" in up:
        # A builder's "Floor Layout" / "Roof Layout" is the joist or truss
        # supplier's placement plan, not the architect's floor or roof plan.
        return SheetType.FRAMING_PLAN
    if ("FOUNDATION" in up or "FOOTING" in up) and "PLAN" not in up:
        up += " PLAN"
    return sheet_type_of(up)


def _largest_title(spans: list[Span]) -> str | None:
    """With no sheet number to anchor on, the largest text on the page, when
    it is set well above the body text and names a sheet type.

    Some builders' title blocks carry no sheet number at all, only a big
    "BUILDING ELEVATIONS I" beside a "DRAWING:" label.
    """
    sizes = sorted(s.size for s in spans)
    top = sizes[-1]
    if top < 2 * sizes[len(sizes) // 2]:
        return None
    block = [s for s in spans if abs(s.size - top) < 0.6 and not _is_noise(s.text)]
    block.sort(key=lambda s: (round(s.y / max(top, 1.0)), s.x))
    title = re.sub(r"\s+", " ", " ".join(s.text for s in block)).strip(" -–,")
    return title if sheet_type_of(title) is not SheetType.UNKNOWN else None


# Read off the drawing itself, for sheets whose title block names nothing
# (some carry only a sheet count). Order matters: an electrical
# plan repeats the floor plan's labels, and a foundation plan is cut by
# section markers, so the specific evidence is tested first.
_ROOM_FLOOR_AREA = re.compile(
    r"\b(?:BASEMENT|GROUND|MAIN|FIRST|SECOND|THIRD|UPPER|LOWER)\s+FLOOR\s+AREA\b"
)
_SECTION_LABEL = re.compile(r"^\s*SECTION\s+[A-Z0-9]{1,2}\s*$", re.M)


def type_from_content(text: str) -> tuple[SheetType, str] | None:
    """(type, the evidence) from a page's own text, or None. Never a guess
    from one common word: each rule needs a phrase only that sheet carries."""
    up = text.upper()
    m = re.search(r"\b(?:DRAWING|SHEET)\s+(?:INDEX|LIST)\b", up)
    if m:
        # The index names every other sheet type, so it is tested first.
        return SheetType.COVER, m.group(0)
    # "TRUSS LAYOUT" alone is a cross-reference note on plans and sections.
    m = re.search(r"\b(?:JOIST|TRUSS)\s+PLACEMENT\s+PLAN\b", up)
    if m:
        return SheetType.FRAMING_PLAN, m.group(0)
    # Twice each: a specification lists all three words once.
    if all(up.count(w) >= 2 for w in ("SWITCH", "OUTLET", "SMOKE")):
        return SheetType.ELECTRICAL, "switch, outlet and smoke alarm symbols"
    m = _ROOM_FLOOR_AREA.search(up)
    if m:
        return SheetType.FLOOR_PLAN, m.group(0)
    if up.count("FOOTING") >= 3 and "FOUNDATION WALL" in up:
        return SheetType.FOUNDATION_PLAN, "foundation wall and footing notes"
    m = _SECTION_LABEL.search(up)
    if m:
        return SheetType.SECTION, m.group(0).strip()
    if "ROOF PLAN" in up:
        return SheetType.ROOF_PLAN, "ROOF PLAN"
    return None


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
        return None, _largest_title(spans)
    num = max(cands, key=lambda s: s.size)
    # Guard: a sheet number is set much larger than the cross-reference bubbles
    # that share its shape (10 pt and 8 pt on these sets).
    if num.size < 1.8 * min(s.size for s in spans):
        return None, _largest_title(spans)
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

    if sheet_type_of(title) is SheetType.UNKNOWN:
        # US title blocks set the title vertically in a column of its own,
        # further from the number than boilerplate such as "PUBLIC SET". Only
        # when the nearest text names no sheet type, take the closest large
        # span that does, within a wider radius, with its same-size neighbours.
        wide = sorted(
            (
                s
                for s in spans
                if s is not num
                and s.size >= 0.5 * num.size
                and not _is_noise(s.text)
                and dist(s) <= 0.3 * diag
            ),
            key=dist,
        )
        typed = [s for s in wide if sheet_type_of(s.text) is not SheetType.UNKNOWN]
        # The title-block column first: a drawing heading ("LEGEND") can sit
        # nearer the number than the title above it (Santa Cruz A2-101).
        in_column = [s for s in typed if s.x >= num.x - 3 * num.size]
        hit = (in_column or typed or [None])[0]
        if hit:
            group = [
                s
                for s in wide
                if abs(s.size - hit.size) < 0.6
                and abs(s.x - hit.x) + abs(s.y - hit.y) <= 5 * hit.size
            ]
            group.sort(key=lambda s: (round(s.y / max(hit.size, 1.0)), s.x))
            title = re.sub(r"\s+", " ", " ".join(s.text for s in group)).strip(" -–,")
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
    stype = sheet_type_of(title, disc)
    if stype is SheetType.UNKNOWN and src is not BasisSource.REVIT_METADATA:
        found = type_from_content(page.get_text())
        if found:
            stype = found[0]
            title = f"{title or found[1]} (from drawing content)"
            src = src or BasisSource.VECTOR_PATH
    return sheet_no, title, stype, disc, src
