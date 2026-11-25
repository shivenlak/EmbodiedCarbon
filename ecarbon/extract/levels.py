"""STEP 10 -- storey levels from the section datums.

Section sheets carry a level ladder: a label with its elevation on the line
directly below. From AB_Fourplex_01 A300:

    TOP OF ROOF        7.873 m
    T/O F/F SECOND     3.000 m
    GROUND FLOOR       0.000 m
    ASSUMED GRADE      (no elevation -- a reference line, not a level)
    T/O F/F BASEMENT   (no elevation on this design)

Multiply the footprint perimeter by the wall height these imply and you have
exterior wall area, the second largest carbon item at ~20% after concrete.

### Two heights, and they differ by 20%

A floor-to-floor height is not a wall height. On AB_Fourplex_01:

    perimeter 58.0 m x floor-to-floor 6.00 m  =  348 m2   (gross, QS convention)
    IFC W2 exterior envelope                  =  288 m2
    HOT2000 above-grade wall records          =  291 m2

The two references agree with each other and sit 20% below the floor-to-floor
figure, because each storey's wall stops at the underside of the floor above:
HOT2000 records 2.667 m and 2.515 m against a 3.000 m floor-to-floor, and
3.000 - 2.667 = 0.333 m, which is the floor assembly depth.

Neither number is wrong. A quantity surveyor measures gross floor-to-floor; an
energy model measures the thermal envelope. Which one a reference takeoff uses
is a convention we cannot see in advance (RESEARCH S16), so BOTH are reported
with the basis named, and the caller picks. Silently choosing one would make us
look 20% out against half the references in the world.
"""

from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field

import pymupdf

from ecarbon.intake.spans import TEXT_DICT, read_spans

# "3.000 m", "7.873m", "0.000 m / 0""
# SK/MB also prints a whole-metre datum without decimals: "0 m | 0' 0\"".
_ELEV_RE = re.compile(r"^(-?\d{1,3}(?:\.\d{2,3})?)\s*m\b(?!m)")
# Feet and inches, as North American sections print them: 10'-1 1/2", -8'-6".
_ELEV_IMPERIAL_RE = re.compile(r"^([-+±]?)\s*(\d{1,3}'\s*-?\s*\d{1,2}(?:\s+\d{1,2}/\d{1,2})?\")$")
# Inches alone count only signed or zero ("-8\"", "0\""); a bare 8" is a dimension.
_ELEV_INCHES_RE = re.compile(r"^(?:([-+±])\s*(\d{1,2}(?:\s+\d{1,2}/\d{1,2})?)|(0))\"$")
# A datum label. Deliberately broad; `is_floor_level` decides what counts.
_LEVEL_LABEL_RE = re.compile(
    # T/O CONCRETE / T/O SLAB: SK/MB's ground datum is the top of the slab.
    r"(?i)\b(T/O\s*F/F|T/O\s*(?:CONC(?:RETE)?|SLAB)|TOP\s+OF|U/S\s*OF|GROUND\s+FLOOR|MAIN\s+FLOOR|SECOND|THIRD|FOURTH"
    r"|BASEMENT|ROOF|TRUSS|PLATE|CEILING|GRADE|LEVEL\s*\d)\b"
)
# Labels that mark a reference line rather than a constructed floor level.
_NOT_A_FLOOR_RE = re.compile(r"(?i)\b(GRADE|FOOTING|U/S|UNDERSIDE|DATUM|CEILING)\b")
# Labels that are the top of the structure rather than a floor.
_ROOF_RE = re.compile(r"(?i)\b(TOP\s+OF\s+ROOF|ROOF|TRUSS|PLATE)\b")
# The top of the wall: a one-storey house's wall height, with no floor above.
# The top of the wall: a plate datum, or the underside of the roof framing
# that bears on it (NOR's single-storey sections: "U/S ROOF FRAMING EL 2.505").
_PLATE_RE = re.compile(r"(?i)\bPLATE\b|\bU\s*[/.]\s*S\.?\s+(?:OF\s+)?ROOF\s+FRAMING\b")

# A datum's elevation sits within this many points below its label. Kept
# tight for a plain metric figure: 16 pt paired AB_ADU_02's "2546 CEILING"
# note with a 2.540 m figure below it.
ELEV_DY_MAX = 14.0
# SK/MB prints every datum dual-unit ("2.744 m | 9' 0"") at a larger text
# size, 21 pt under its label; that format alone gets the wider reach.
DUAL_ELEV_DY_MAX = 24.0
_DUAL_ELEV_RE = re.compile(r"^-?\d{1,3}(?:\.\d{1,3})?\s*m\s*\|\s*-?\d")
# Imperial ladders set the elevation a touch lower (14.04 pt seen).
IMPERIAL_DY_MAX = 16.0
ELEV_DX_MAX = 40.0
# Imperial ladders centre the elevation under a wider label (up to ~55 pt
# right of its start) and sit beside floor-depth dimensions that can be nearer
# than the datum; storey_heights_for's per-label vote drops those strays.
IMPERIAL_DX_LEFT = 20.0
IMPERIAL_DX_RIGHT = 60.0
# Floor datums closer than this are one floor read in two datum systems
# (a sheet can carry the level set twice, a few inches apart).
SAME_FLOOR_M = 0.25

# Plausible floor-to-floor height, metres.
MIN_STOREY_M = 2.1
MAX_STOREY_M = 6.0


@dataclass(frozen=True)
class Level:
    label: str
    elevation_m: float
    sheet: str | None = None

    @property
    def is_roof(self) -> bool:
        return bool(_ROOF_RE.search(self.label))

    @property
    def is_floor(self) -> bool:
        """A constructed floor level, as opposed to a reference line."""
        if _NOT_A_FLOOR_RE.search(self.label):
            return False
        return not self.is_roof


@dataclass
class StoreyHeights:
    levels: list[Level] = field(default_factory=list)
    floor_assembly_mm: float | None = None
    sources: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # The top storey's wall height where the drawing states it (a "SECOND
    # FLOOR WALL HEIGHT" note), used instead of copying the storey below.
    top_storey_m: float | None = None

    @property
    def floors(self) -> list[Level]:
        out: list[Level] = []
        for lv in sorted((x for x in self.levels if x.is_floor), key=lambda x: x.elevation_m):
            if not out or lv.elevation_m - out[-1].elevation_m >= SAME_FLOOR_M:
                out.append(lv)
        return out

    @property
    def roof_level_m(self) -> float | None:
        roofs = [lv.elevation_m for lv in self.levels if lv.is_roof]
        return max(roofs) if roofs else None

    @property
    def n_storeys(self) -> int:
        return max(len(self.floors), 1) if self.floors else 0

    def storey_heights_m(self) -> list[float]:
        """Floor-to-floor height of each storey, lowest first.

        The topmost storey has no floor datum above it, so its height is taken
        from the storey below and recorded in `notes` as inferred. Using the
        roof level instead would include the roof slope, which on
        AB_Fourplex_01 is 1.87 m of pitch above the top plate.
        """
        floors = self.floors
        if len(floors) == 1:
            plates = [
                lv.elevation_m
                for lv in self.levels
                if _PLATE_RE.search(lv.label) and lv.elevation_m > floors[0].elevation_m
            ]
            h = round(min(plates) - floors[0].elevation_m, 3) if plates else None
            return [h] if h is not None and MIN_STOREY_M <= h <= MAX_STOREY_M else []
        if len(floors) < 2:
            return []
        heights = [
            round(b.elevation_m - a.elevation_m, 3)
            for a, b in zip(floors, floors[1:], strict=False)
        ]
        heights = [h for h in heights if MIN_STOREY_M <= h <= MAX_STOREY_M]
        if not heights:
            return []
        # One more storey than there are gaps between floor datums.
        top = self.top_storey_m if self.top_storey_m is not None else heights[-1]
        heights.append(top)
        return heights

    @property
    def total_wall_height_m(self) -> float | None:
        """Gross floor-to-floor wall height, summed over storeys."""
        hs = self.storey_heights_m()
        return round(sum(hs), 3) if hs else None

    @property
    def net_wall_height_m(self) -> float | None:
        """Wall height less the floor assembly at each level above the first.

        This is the thermal-envelope basis: on AB_Fourplex_01 it reproduces
        HOT2000's 2.667 m + 2.515 m rather than 3.000 m + 3.000 m.
        """
        hs = self.storey_heights_m()
        if not hs or self.floor_assembly_mm is None:
            return None
        if len(self.floors) == 1:
            # A one-storey height runs floor to top plate: no floor to deduct.
            return hs[0]
        # A stated top-storey wall height already stops under the roof: no floor in it.
        floors_in = len(hs) - (1 if self.top_storey_m is not None else 0)
        deduction = (self.floor_assembly_mm / 1000.0) * floors_in
        return round(max(sum(hs) - deduction, 0.0), 3)

    def wall_area_m2(self, perimeter_m: float, basis: str = "gross") -> float | None:
        """Exterior wall area. `basis` is 'gross' (floor to floor) or 'net'."""
        h = self.total_wall_height_m if basis == "gross" else self.net_wall_height_m
        return None if h is None else round(perimeter_m * h, 1)

    @property
    def missing(self) -> list[str]:
        gaps: list[str] = []
        if len(self.floors) < 2 and not self.storey_heights_m():
            gaps.append("fewer than two floor datums found; storey height unknown")
        if self.floor_assembly_mm is None:
            gaps.append("floor assembly depth unknown; net wall height unavailable")
        return gaps


def _elevation_m(text: str) -> float | None:
    """A datum's elevation in metres, metric or feet-and-inches, or None."""
    m = _ELEV_RE.match(text)
    if m:
        return float(m.group(1))
    from ecarbon.geometry.scale import parse_imperial

    m = _ELEV_INCHES_RE.match(text.strip())
    if m:
        if m.group(3):
            return 0.0
        mm = parse_imperial(m.group(2) + '"')
        return None if mm is None else round((-mm if m.group(1) == "-" else mm) / 1000.0, 3)
    m = _ELEV_IMPERIAL_RE.match(text.strip())
    if not m:
        return None
    # parse_imperial refuses anything under 20 mm as noise; a 0'-0" datum is real.
    mm = 0.0 if re.fullmatch(r"0'\s*-?\s*0\"", m.group(2)) else parse_imperial(m.group(2))
    if mm is None:
        return None
    return round((-mm if m.group(1) == "-" else mm) / 1000.0, 3)


# A datum printed with its label in one span, as US sections and UK/AU/DE
# drawings do: `8'-0" PLATE HEIGHT`, `0'-0" FINISHED FLOOR`, `T.O. PLATE
# 9'-1 1/8"`, `FIN. FLR. EL. 100'-0"`, `FFL +3.000`, `RL 12.450`, `OKFF ±0,00`.
# Only labels that name a floor or the top plate: an inline `TOP OF TRELLIS`
# or `TOP OF COLUMN` would otherwise count as a floor.
_INLINE_LABEL = (
    r"(?:FIN(?:ISHED|\.)?\s*(?:FLOOR|FLR)\.?|F\.?F\.?L\.?|SSL|OKFF|SUB-?FLOOR"
    r"|(?:T\.?\s*O\.?|TOP\s+OF)\s*(?:SUB-?)?(?:FLOOR|PLATE|SLAB)|PLATE(?:\s+HEIGHT|\s+HT\.?)?)"
)
_FT_IN = r"(\d{1,3}'\s*-?\s*\d{1,2}(?:\s+\d{1,2}/\d{1,2})?\")"
_INLINE_LEAD_RE = re.compile(rf"^([-+±]?)\s*{_FT_IN}\s+({_INLINE_LABEL})$", re.I)
_INLINE_TRAIL_RE = re.compile(rf"^({_INLINE_LABEL})\s*(?:EL\.?\s*)?([-+±]?)\s*{_FT_IN}$", re.I)
# Metric needs an explicit datum code, so CMHC's "3.000 m" ladders are untouched.
# A bare AU `RL 12.450` could be a ridge or an eave, so it needs its FFL.
_INLINE_METRIC_RE = re.compile(r"^(FFL|SSL|OKFF)\s*(?:RL\s*)?([-+±]?\s*\d{1,3}[.,]\d{2,3})$", re.I)


def inline_level(text: str) -> tuple[str, float] | None:
    """(label, elevation m) from a span that carries both, or None."""
    t = re.sub(r"\s+", " ", text.strip())
    m = _INLINE_METRIC_RE.match(t)
    if m:
        value = m.group(2).replace(" ", "").replace(",", ".").replace("±", "")
        return m.group(1).upper(), float(value)
    m = _INLINE_LEAD_RE.match(t)
    sign, ftin, label = (m.group(1), m.group(2), m.group(3)) if m else (None, None, None)
    if not m:
        m = _INLINE_TRAIL_RE.match(t)
        if not m:
            return None
        label, sign, ftin = m.group(1), m.group(2), m.group(3)
    elev = _elevation_m(f"{sign}{ftin}")
    return None if elev is None else (label.upper(), elev)


# Glyph-ID shifts to try on a span the global repair declines (see
# extract/assemblies.repair_schedule_cell; 0x1D is Ontario's).
_SPAN_SHIFTS = (0x1D, 0x1F, 0x1E, 0x20)
_LABEL_TEXT_RE = re.compile(r"^[A-Z0-9 /.\-]+$")


def repair_level_span(text: str) -> str:
    """Recover a section span the global text repair refuses.

    Ontario's sections are glyph-ID encoded like its schedules. The global
    repair decodes "GROUND FLOOR" and "T/O F/F SECOND" but refuses
    "T/O F/F THIRD" and every "10.500 m/ 34'-5 3/8\"" value, so the ladder
    stopped at the second floor and a three-storey building was read as two.
    A shift is accepted only when it yields a level label in capitals or an
    elevation that parses, never mere word-likeness.
    """
    if not any(ord(c) < 0x20 and c not in "\n\r\t" for c in text):
        return text
    for by in _SPAN_SHIFTS:
        cand = "".join(chr(o + by) if 0 < (o := ord(c)) < 0x80 else c for c in text)
        if _elevation_m(cand) is not None:
            return cand
        if _LEVEL_LABEL_RE.search(cand) and _LABEL_TEXT_RE.match(cand.strip()):
            return cand
    return text


def levels_on_page(page: pymupdf.Page, sheet: str | None = None) -> list[Level]:
    """Level datums on one section sheet."""
    # Rotation-corrected, because a datum's elevation is printed on the line
    # *below* its label and on a sheet drawn a quarter turn from upright
    # "below" is sideways. Ontario's sections are rotated exactly like its
    # schedules, so every label was found and no elevation ever paired with
    # one: the ladder came back empty while the text was perfectly readable.
    spans = read_spans(page, repair_level_span)

    out: list[Level] = []
    for y, x, text in spans:
        inline = inline_level(text)
        if inline is not None:
            out.append(Level(label=inline[0], elevation_m=inline[1], sheet=sheet))
            continue
        if not _LEVEL_LABEL_RE.search(text) or _elevation_m(text) is not None:
            continue
        # The elevation sits on the line directly below its label.
        best: tuple[float, float] | None = None
        for y2, x2, t2 in spans:
            dy = y2 - y
            if not (0 < dy <= max(IMPERIAL_DY_MAX, DUAL_ELEV_DY_MAX)):
                continue
            elev = _elevation_m(t2)
            if elev is None:
                continue
            dx = x2 - x
            if _ELEV_RE.match(t2):
                reach = DUAL_ELEV_DY_MAX if _DUAL_ELEV_RE.match(t2) else ELEV_DY_MAX
                if dy > reach or abs(dx) > ELEV_DX_MAX:
                    continue
            elif dy > IMPERIAL_DY_MAX or not -IMPERIAL_DX_LEFT <= dx <= IMPERIAL_DX_RIGHT:
                continue
            if best is None or dy < best[0]:
                best = (dy, elev)
        if best is not None:
            out.append(Level(label=re.sub(r"\s+", " ", text), elevation_m=best[1], sheet=sheet))
    return out


def outvote_strays(levels: list[Level]) -> list[Level]:
    """A label drawn several times keeps the elevation most copies agree on; a
    copy paired with a nearby dimension instead is outvoted. Ties keep all."""

    def key(lv: Level) -> str:
        # "-SECOND FLOOR" and "Second Floor" are one label.
        return re.sub(r"[^A-Z0-9]+", " ", lv.label.upper()).strip()

    votes = collections.Counter((key(lv), lv.elevation_m) for lv in levels)
    top: dict[str, int] = collections.defaultdict(int)
    for (label, _), n in votes.items():
        top[label] = max(top[label], n)
    return [lv for lv in levels if votes[(key(lv), lv.elevation_m)] == top[key(lv)]]


# Alberta builders' elevations label each storey's wall height beside its
# dimension instead of a datum ladder: MAIN FLOOR WALL HEIGHT, SECOND FLOOR
# WALL HEIGHT and FLOOR THICKNESS, each beside a feet-inches figure.
_WALL_HEIGHT_RE = re.compile(r"^(MAIN|GROUND|FIRST|SECOND|THIRD)\s+FLOOR\s+WALL\s+HEIGHT$", re.I)
_FLOOR_THICKNESS_RE = re.compile(r"^FLOOR\s+THICKNESS$", re.I)
_FT_IN_ONLY_RE = re.compile(r"^\d{1,2}'\s*-?\s*\d{1,2}(?:\s+\d{1,2}/\d{1,2})?\"$")
_STOREY_ORDER = {"MAIN": 1, "GROUND": 1, "FIRST": 1, "SECOND": 2, "THIRD": 3}
# The figure sits in the dimension column beside its label (about 15 pt on
# the Landmark sets), measured from the figure's centre to the label's box.
WALL_HEIGHT_REACH_PT = 40.0


def wall_heights_on_page(page: pymupdf.Page) -> tuple[dict[int, float], float | None]:
    """({storey: wall height m}, floor thickness m) from wall-height notes."""
    from ecarbon.geometry.scale import parse_imperial

    spans = []
    for block in page.get_text("dict", flags=TEXT_DICT)["blocks"]:
        for line in block.get("lines", []):
            for sp in line["spans"]:
                t = re.sub(r"\s+", " ", sp["text"]).strip()
                if t:
                    spans.append((t, sp["bbox"]))
    figures = [(t, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for t, b in spans if _FT_IN_ONLY_RE.match(t)]

    def nearest(box) -> float | None:
        def dist(f) -> float:
            dx = max(box[0] - f[1], 0.0, f[1] - box[2])
            dy = max(box[1] - f[2], 0.0, f[2] - box[3])
            return (dx * dx + dy * dy) ** 0.5

        best = min(figures, key=dist, default=None)
        if best is None or dist(best) > WALL_HEIGHT_REACH_PT:
            return None
        mm = parse_imperial(best[0])
        return None if mm is None else round(mm / 1000.0, 3)

    heights: dict[int, float] = {}
    thickness = None
    for t, box in spans:
        m = _WALL_HEIGHT_RE.match(t)
        if m:
            h = nearest(box)
            if h is not None and MIN_STOREY_M <= h <= MAX_STOREY_M:
                heights.setdefault(_STOREY_ORDER[m.group(1).upper()], h)
        elif _FLOOR_THICKNESS_RE.match(t) and thickness is None:
            th = nearest(box)
            if th is not None and 0.15 <= th <= 0.6:
                thickness = th
    return heights, thickness


def storey_heights_for(design, floor_assembly_mm: float | None = None) -> StoreyHeights:
    """Read the level ladder from a design's section sheets."""
    from ecarbon.intake import inventory
    from ecarbon.models import SheetType

    sheets, _, _ = inventory(design.drawings_pdf)
    result = StoreyHeights(floor_assembly_mm=floor_assembly_mm)
    doc = pymupdf.open(design.drawings_pdf)
    try:
        for s in sheets:
            if s.sheet_type is not SheetType.SECTION or not s.readable:
                continue
            found = levels_on_page(doc[s.page], s.sheet_no)
            if found:
                result.levels.extend(found)
                result.sources.append(
                    f"{s.sheet_no}: " + ", ".join(f"{lv.label} {lv.elevation_m}m" for lv in found[:6])
                )
    finally:
        doc.close()

    result.levels = outvote_strays(result.levels)

    if not result.storey_heights_m():
        _from_wall_heights(design, sheets, result)

    hs = result.storey_heights_m()
    if len(hs) >= 2:
        result.notes.append(
            f"top storey height inferred as {hs[-1]} m from the storey below; "
            "no plate datum above it"
        )
    return result


def _from_wall_heights(design, sheets, result: StoreyHeights) -> None:
    """Where no datum ladder reads: storey wall heights stated on the elevations
    or sections. Floors are stacked as wall height plus the stated floor
    thickness; with no thickness stated, nothing is built (it would be a guess).
    Any readable sheet: the label is specific, and Landmark's elevations carry
    no title the classifier can type."""
    doc = pymupdf.open(design.drawings_pdf)
    try:
        for s in sheets:
            if not s.readable:
                continue
            heights, thickness = wall_heights_on_page(doc[s.page])
            storeys = sorted(heights)
            if not storeys or storeys != list(range(1, len(storeys) + 1)):
                continue
            if len(storeys) > 1 and thickness is None:
                continue
            elev, levels = 0.0, []
            for n in storeys:
                levels.append(Level(label=f"STOREY {n} FLOOR (from wall height)", elevation_m=round(elev, 3), sheet=s.sheet_no))
                elev += heights[n] + (thickness or 0.0)
            # The top storey's wall stops at its plate, under no floor.
            levels.append(Level(label="TOP PLATE (from wall height)", elevation_m=round(elev - (thickness or 0.0), 3), sheet=s.sheet_no))
            result.levels = levels
            if len(storeys) > 1:
                result.top_storey_m = heights[storeys[-1]]
                result.floor_assembly_mm = round(thickness * 1000.0, 1)
            result.sources.append(
                f"{s.sheet_no or f'p{s.page + 1}'}: wall heights "
                + ", ".join(f"storey {n} {heights[n]} m" for n in storeys)
                + (f", floor thickness {thickness} m" if thickness else "")
            )
            result.notes.append(
                "storey heights from the wall heights stated on the drawings rather than a "
                "datum ladder; each lower storey adds the stated floor thickness"
            )
            return
    finally:
        doc.close()
