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

from ecarbon.intake.spans import read_spans

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
_PLATE_RE = re.compile(r"(?i)\bPLATE\b")

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
        top = heights[-1]
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
        deduction = (self.floor_assembly_mm / 1000.0) * len(hs)
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


def levels_on_page(page: pymupdf.Page, sheet: str | None = None) -> list[Level]:
    """Level datums on one section sheet."""
    # Rotation-corrected, because a datum's elevation is printed on the line
    # *below* its label and on a sheet drawn a quarter turn from upright
    # "below" is sideways. Ontario's sections are rotated exactly like its
    # schedules, so every label was found and no elevation ever paired with
    # one: the ladder came back empty while the text was perfectly readable.
    spans = read_spans(page)

    out: list[Level] = []
    for y, x, text in spans:
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

    hs = result.storey_heights_m()
    if len(hs) >= 2:
        result.notes.append(
            f"top storey height inferred as {hs[-1]} m from the storey below; "
            "no plate datum above it"
        )
    return result
