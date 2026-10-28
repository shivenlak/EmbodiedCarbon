"""STEP 19 -- the assemblies schedule, which is where element areas become materials.

Sheet A003 carries every assembly in the building as a layer build-up. From
AB_Fourplex_01, assembly W2:

    3/4" (19mm)      NON-COMBUSTIBLE LIGHT-WEIGHT CLADDING PLACE HOLDER
    1/2" (13mm)      VENTED CAVITY W/ METAL Z-GIRTS @ 400mm O/C
    1" (25mm)        RIGID INSULATION
    VAR              AIR BARRIER, VAPOR PERMEABLE
    5/8" (16mm)      NON-COMBUSTIBLE EXTERIOR SHEATHING
    5 1/2" (140mm)   METAL STUD FRAMING (REFER TO STRUCTURAL)
    5 1/2" (140mm)   STUD CAVITY IN-FILL INSULATION
    VAR              VAPOR CONTROL BARRIER
    5/8" (16mm)      GYPSUM BOARD, TYPE X

This is the unlock for element coverage. A takeoff that knows only
"exterior wall, 309 m2" can price the studs; one that knows the build-up can
price cladding, sheathing, insulation, barriers and gypsum, which is most of
the wall's carbon. The same schedule covers roofs (R), floors (F), foundation
walls (N) and partitions (P) -- 17 assemblies on this one sheet.

### Five things on this sheet that will produce wrong numbers if taken literally

**1. The cavity is one space, not two.** Both W1 and W2 list a 140 mm stud
layer *and* a 140 mm insulation layer. They occupy the same cavity: the
insulation fills the gaps between the studs. Summing both at full wall area
counts 280 mm of material in a 140 mm wall. `Layer.shares_cavity_with` marks
the pair so a caller can split the cavity by framing fraction instead of
double-counting it. This is the single largest error available here.

**2. The unit order flips between assemblies on the same sheet.** W1 reads
`19mm (3/4")`; W2 reads `3/4" (19mm)`. Same sheet, same firm, adjacent
columns. Parsing position rather than meaning gets one of them wrong, which is
the recurring lesson in this codebase appearing for the sixth time.

**3. `PLACE HOLDER` means CMHC left it unspecified.** Cladding and roofing are
deliberately not chosen, because the catalogue is a template. The spelling
varies too -- `PLACE HOLDER` on the walls, `PLACEHOLDER` on the roofs. These
are reported as unspecified, never guessed: cladding is ~12% of a home's
embodied carbon, so inventing one would move the total more than most
measurements.

**4. `VAR` means no thickness is given.** Air and vapour barriers carry no
dimension, so no volume can be computed from them. A caller gets `None` and a
reason, not a zero.

**5. `(REFER TO STRUCTURAL)` means the quantity lives on another sheet.** The
stud framing layer defers to the structural drawings. Counting it here as well
as from the structural takeoff double-counts the framing, so it is flagged
`deferred_to` and excluded from this assembly's own material quantities.

### What this reads, and what it does not

Measured over the catalogue: 31 of 53 designs yield at least one trustworthy
assembly -- Alberta 7/7, BC 7/7, Quebec 7/7, Atlantic 8/9 -- with 280
assemblies kept and 80 refused by `Assembly.implausible`.

Two groups read nothing, for different reasons, and the distinction matters:

* **SKMB (7 designs) publishes no assemblies schedule at all.** Its packages
  carry only `S002 TYPICAL DETAILS`. That is a gap in the source documents,
  not in this parser, and no amount of work here will close it.
* **NOR (9 designs) has its text converted to vector outlines**, so there is
  nothing to read on any sheet.
* **Ontario's five multiplexes have a readable schedule this cannot yet
  parse.** Their sheet is drawn rotated a quarter turn, which `_spans`
  corrects, but their thickness cells are glyph-ID mojibake that
  `intake.textrepair` deliberately refuses: `PP` is `mm` under the 0x1D shift
  and `5,*,',168/$7,215` is `RIGID INSULATION`, but a cell under three
  characters is skipped and any cell containing letters is left alone. That
  second guard is what stops `R-22` becoming `oJOO` across 1465 pages of sheet
  classification, so it is not worth loosening globally for five designs. A
  repair scoped to this module, accepting a shift only when the result parses
  as a thickness or a known material, would be the safe way in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf

from ecarbon.intake.spans import read_spans
from ecarbon.intake.textrepair import repair

# "N - FOUNDATION WALL ASSEMBLIES", "W - EXTERIOR WALL ASSEMBLIES"
_GROUP_RE = re.compile(r"^([A-Z])\s*-\s*(.+?)\s+ASSEMBL", re.I)
# W1, W2, P1a, R3, F5, N1 -- and BC's dotted forms W1.1, R2.1, FW1.1.
#
# Surveyed across every schedule TYPE column in the catalogue: P#, F#, W#, R#,
# N#, C#, S# and the lowercase-suffixed P#a/R#a are universal, while W#.# (28),
# R#.# (21) and FW#.# (14) occur only in BC. Missing the dotted form cost BC
# its exterior wall: with one matchable tag in a 772-point band, tag
# segmentation could not split it and every assembly there merged into a single
# 50-layer object that the plausibility gate then refused.
_TAG_RE = re.compile(r"^([A-Z]{1,2})(\d{1,2})(?:\.\d{1,2})?[a-z]?$")


def tag_prefix(tag: str) -> str:
    """The group a tag belongs to: W1.1 -> W, FW1.1 -> FW, P1a -> P.

    The whole alphabetic prefix, not its first letter. BC's `FW` is a
    foundation wall, and treating it as `F` would make it selectable as the
    floor assembly -- putting a foundation wall's build-up into a ceiling.
    """
    m = _TAG_RE.match(tag.strip())
    return m.group(1).upper() if m else ""
# A metric thickness anywhere in the cell, which is the reliable signal.
_MM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*mm", re.I)
# Imperial: the digits, spaces and slashes immediately before an inch mark.
# Parsed afterwards rather than in the pattern, because the sheet writes whole
# inches (8"), fractions (3/4") and mixed numbers (5 1/2") interchangeably and
# a single pattern for all three silently failed on the whole-inch case.
_IMP_RE = re.compile(r"([\d\s/]+?)\s*(?:\"|in\b)")

# Thickness cells that state there is no thickness.
_NO_THICKNESS = {"VAR", "VARIES", "N/A", "-"}
# A continuation marker, not a layer. "C/W" is "complete with".
_CONTINUATION = {"C/W", "C/W:", "CW"}

_PLACEHOLDER_RE = re.compile(r"PLACE\s?HOLDER", re.I)
# A trailing "complete with", which introduces the next layer rather than
# describing this one.
_CW_TAIL_RE = re.compile(r"\s+C/W:?\s*$", re.I)
_DEFER_RE = re.compile(r"\(?\s*REFER\s+TO\s+(\w+)[^)]*\)?", re.I)
# The framing layer and the insulation that fills the gaps between it.
_FRAMING_RE = re.compile(r"\b(STUD|JOIST|TRUSS|RAFTER)\s+FRAMING\b|\bFRAMING\b", re.I)
# A layer the schedule states is intermittent rather than continuous:
# "WOOD STRAPPING @ 400mm O/C  (38mm WIDE MINIMUM)". Its thickness is the
# depth of the gap it creates, not a solid sheet of material.
_SPACING_RE = re.compile(r"@\s*(\d+(?:\.\d+)?)\s*mm\s*O/?C", re.I)
_WIDTH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*mm\s+WIDE", re.I)
# A layer that is predominantly an air gap.
_CAVITY_GAP_RE = re.compile(r"\b(VENTED\s+)?CAVITY\b|\bAIR\s+SPACE\b", re.I)
_STRAPPING_RE = re.compile(r"STRAPPING|FURRING|Z-?GIRT|CHANNEL", re.I)
_CAVITY_FILL_RE = re.compile(r"CAVITY\s+(IN-?FILL|FILL)|BATT|IN-?FILL\s+INSULATION", re.I)

# Column geometry of the A003 layout. The DESCRIPTION header is centred over
# two sub-columns -- thickness on the left, material on the right -- while an
# assembly's name row sits at the header's own x. Measured identically on every
# table on the sheet: 988.5 header with 952.7/1024.8 cells, and 1830.1 with
# 1794.3/1866.4.
COL_TOL = 14.0
# How far a name column may sit from its own DESCRIPTION header. Wide enough
# for Atlantic's 34 pt offset, narrow enough to exclude the performance column,
# which is 190 pt out on every layout measured.
NAME_COLUMN_WINDOW = 50.0
# Sanity bounds on a parsed assembly. A low-rise wall, roof or floor runs to a
# dozen layers and a few hundred millimetres; well past that means the parse
# merged blocks rather than that the building is unusual.
MAX_PLAUSIBLE_LAYERS = 15
# Tried and rejected on measurement, recorded so it is not retried:
#
# "name looks like a material" is the largest single refusal cause -- 99 of
# 172 across the catalogue -- and 108 refusals still carried three or more
# layers and a stated depth, including an 11-layer 315 mm block on BC_Rowhouse
# that reads exactly like a real exterior wall. The obvious hypothesis is that
# such a block IS a real assembly whose name cell was misread, so keeping it
# and flagging the name would recover 77 assemblies.
#
# It does recover them, and they are wrong. Scored against the IFC's own layer
# sets, assemblies kept this way run a 86.4% median error with **none** of 25
# inside 10%, against 20.1% median and 90 of 223 inside 10% for assemblies
# whose name parsed cleanly. ON_Fourplex_01's R2 is the clearest case: read as
# 124 mm over 5 layers where the model says 490 mm, named "WOOD DECKING", with
# one glyph-shifted layer repeated twice.
#
# So a material-like name is not a caption problem. It means the block's edges
# are in the wrong place, and the build-up inside it is wrong too. The refusal
# stands, and the coverage it costs is coverage we should not want.
MAX_PLAUSIBLE_DEPTH_MM = 800.0
# An assembly "name" that is really one of its own layers, which is what a
# block starting on the wrong row looks like.
#
# `INSULATION` alone is deliberately absent. BC names a genuine wall assembly
# "2x6 WOOD STUD W/ EXTERIOR INSULATION", and an `INSULATION$` rule refused it
# along with its whole group. The tokens kept here are ones that only ever name
# a single layer.
_MATERIAL_LIKE_NAME_RE = re.compile(
    r"GYPSUM|PLACEHOLDER|PLACE\s?HOLDER|AIR\s+BARRIER|VAPOU?R\s+(?:CONTROL|BARRIER)"
    r"|STRAPPING|MEMBRANE|SHEATHING|PLYWOOD|PARGING|JOISTS?\s*@|CONCRETE\s*$"
    # Added after measuring: these slipped through as one-layer "assemblies"
    # on Atlantic and Ontario -- "WOOD STUD FRAMING @ 1'-4"", "BATT INSULATION
    # IN CAVITY", "WOOD DECKING". FRAMING is matched only as a trailing word or
    # before a spacing callout, so a real assembly name like "WOOD FRAMED
    # FLOOR" or "2x6 WOOD STUD W/ EXTERIOR INSULATION" is untouched.
    # A spacing callout is required after FRAMING, because a layer states one
    # ("WOOD STUD FRAMING @ 1'-4"") and a composite assembly name does not
    # ("DOUBLE BRICK MASONRY W/ WOOD STUD FRAMING", Quebec's real W1, which an
    # end-anchored form refused).
    r"|\bBATT\b|\bDECKING\b|STUD\s+FRAMING\s*@|FURRING\s+CHANNEL",
    re.I,
)
# A cell carrying words rather than a dimension: three or more letters in a row.
_WORDY_RE = re.compile(r"[A-Za-z]{3,}")
# The words that make up a schedule table's header row. Used to find a table's
# horizontal extent from the sheet itself rather than from a measured offset.
_HEADER_WORDS = {"TYPE", "DIAGRAM", "DESCRIPTION", "PERFORMANCE", "THICKNESS", "ASSEMBLY"}
# Two spans belong to the same table row within this many points.
ROW_DY = 3.0
# A tag sits vertically within its assembly's block, not at its top.
TAG_DX = 40.0


def _parse_inches(text: str) -> float | None:
    """Inches from a cell, covering 8", 3/4" and 5 1/2" alike."""
    m = _IMP_RE.search(text)
    if not m:
        return None
    total = 0.0
    found = False
    for part in m.group(1).split():
        if "/" in part:
            num, _, den = part.partition("/")
            if num.isdigit() and den.isdigit() and float(den):
                total += float(num) / float(den)
                found = True
        elif part.isdigit():
            total += float(part)
            found = True
    return total if found else None


def parse_thickness(text: str) -> tuple[float | None, str | None]:
    """Millimetres from a thickness cell, in either unit order.

    Returns (mm, note). `mm` is None when the cell states no thickness, and
    `note` records a disagreement between the two unit systems when both are
    given, since the sheet is then contradicting itself.
    """
    t = text.strip().upper()
    if not t or t in _NO_THICKNESS:
        return None, None

    metric = _MM_RE.search(t)
    mm = float(metric.group(1)) if metric else None

    # Imperial, from the part of the cell outside the metric match.
    imperial_src = t.replace(metric.group(0), "") if metric else t
    inches = _parse_inches(imperial_src)

    if mm is None and inches:
        return round(inches * 25.4, 1), "metric not stated; converted from imperial"
    if mm is not None and inches:
        # Both given, so they can be checked against each other.
        drift = abs(mm - inches * 25.4)
        if drift > 3.0:
            return mm, (
                f"sheet states {mm:.0f} mm and {inches:.3f} in, which differ by "
                f"{drift:.0f} mm; the metric value is used"
            )
    return mm, None


@dataclass
class Layer:
    """One layer of an assembly, outside in."""

    index: int
    material: str
    thickness_mm: float | None = None
    note: str | None = None
    # Set when the layer names another discipline's drawings as its source.
    deferred_to: str | None = None
    # Set when the schedule deliberately leaves the material unspecified.
    is_placeholder: bool = False
    # Index of the layer this one shares a cavity with, if any.
    shares_cavity_with: int | None = None
    # Set when the thickness cell is there and says VAR, VARIES, N/A or "-":
    # the drawing declining to give a depth, not a depth we failed to read.
    stated_no_thickness: bool = False

    @property
    def coverage(self) -> tuple[float, str | None]:
        """What fraction of the assembly's area this layer actually covers.

        Strapping, furring and Z-girts run at a spacing, so a 19 mm strapping
        layer is 19 mm deep but only covers width/spacing of the wall. Taking
        it as a solid sheet overstates it about tenfold, and on a steel girt
        that is tonnes of invented metal.
        """
        # Cavity *fill* fills the cavity; it is not the air gap. Without this
        # guard the word "CAVITY" in "STUD CAVITY IN-FILL INSULATION" matches
        # the air-gap rule and drops the largest material in the wall. Its
        # share of the cavity is handled by `shares_cavity_with` instead.
        if self.is_cavity_fill:
            return 1.0, None

        spacing = _SPACING_RE.search(self.material)
        width = _WIDTH_RE.search(self.material)
        if spacing and width:
            frac = float(width.group(1)) / float(spacing.group(1))
            return (
                round(min(frac, 1.0), 4),
                f"intermittent: {width.group(1)}mm wide at {spacing.group(1)}mm on centre",
            )
        if _CAVITY_GAP_RE.search(self.material) or _STRAPPING_RE.search(self.material):
            # Known to be intermittent, but the member size is not given, so
            # no fraction can be computed and none is invented.
            return 0.0, (
                "an intermittent layer whose member width the schedule does not "
                "state, so no volume can be computed for it"
            )
        return 1.0, None

    @property
    def is_framing(self) -> bool:
        return bool(_FRAMING_RE.search(self.material))

    @property
    def is_cavity_fill(self) -> bool:
        return bool(_CAVITY_FILL_RE.search(self.material))

    @property
    def quantifiable(self) -> bool:
        """Whether a volume can be computed for this layer from this sheet."""
        return (
            self.thickness_mm is not None
            and not self.is_placeholder
            and self.deferred_to is None
            and self.coverage[0] > 0.0
        )

    def volume_m3(self, area_m2: float, framing_fraction: float = 0.15) -> float | None:
        """Volume of this layer over `area_m2` of the assembly.

        A layer sharing a cavity takes only its share of it: the framing takes
        `framing_fraction` and the fill takes the rest. Without that split the
        pair would together claim twice the cavity's actual depth.
        """
        if not self.quantifiable:
            return None
        share = 1.0
        if self.shares_cavity_with is not None:
            share = framing_fraction if self.is_framing else (1.0 - framing_fraction)
        return round(area_m2 * (self.thickness_mm / 1000.0) * share * self.coverage[0], 3)


@dataclass
class Assembly:
    """One assembly from the schedule: a tag, a name and its layers."""

    tag: str
    name: str
    group: str = ""
    group_letter: str = ""
    layers: list[Layer] = field(default_factory=list)
    performance: list[str] = field(default_factory=list)
    sheet: str | None = None
    page: int | None = None
    # y of this assembly's name row, used to attach the tag beside its block.
    name_y: float | None = None

    @property
    def total_thickness_mm(self) -> float:
        """Built depth, counting a shared cavity once."""
        seen: set[int] = set()
        total = 0.0
        for layer in self.layers:
            if layer.thickness_mm is None or layer.index in seen:
                continue
            total += layer.thickness_mm
            if layer.shares_cavity_with is not None:
                seen.add(layer.shares_cavity_with)
        return round(total, 1)

    def implausible(self) -> str | None:
        """Why this parse should not be trusted, or None if it looks sound.

        Reading this sheet generically across firms sometimes merges adjacent
        blocks or starts one on a layer row, and the result is structurally
        wrong while looking entirely ordinary: a 47-layer, 1.6 m "VAULTED ROOF"
        on BC_Duplex, and assemblies named "GYPSUM BOARD" on ATL_Sixplex. A
        wrong build-up silently produces wrong quantities, whereas refusing it
        produces a gap that says so, so anything failing these checks is
        reported unreadable instead of used.
        """
        if len(self.layers) > MAX_PLAUSIBLE_LAYERS:
            return (
                f"{len(self.layers)} layers, more than the {MAX_PLAUSIBLE_LAYERS} a "
                f"low-rise assembly has; adjacent blocks on the sheet were probably "
                f"merged"
            )
        if self.total_thickness_mm > MAX_PLAUSIBLE_DEPTH_MM:
            return (
                f"built depth {self.total_thickness_mm:.0f} mm, beyond the "
                f"{MAX_PLAUSIBLE_DEPTH_MM:.0f} mm a low-rise assembly reaches"
            )
        if not self.layers:
            return "no layers found"
        if self.total_thickness_mm <= 0.0:
            # Not one layer states a thickness. No quantity could come from it
            # anyway, and in practice it means the block was split in the wrong
            # place -- BC's FW1.1 came through this way, four layers deep and
            # named "RIGID INSULATION (R-20.0)".
            # Most of these are the drawing's own answer rather than a misread:
            # 41 of the 46 across the catalogue sit on rows whose thickness
            # cell says VAR. Saying "could not be read" there blames the parser
            # for what the drawing chose not to state.
            if any(layer.stated_no_thickness for layer in self.layers):
                return (
                    "the drawing gives its thickness as VAR (varies) rather than a "
                    "depth, so no volume can be computed from the schedule; supply "
                    "the built depth to count it"
                )
            return (
                "no layer states a thickness, so this is either a note block or a "
                "mis-split one rather than an assembly"
            )
        if self.name_is_suspect:
            return (
                f"the name {self.name!r} is a material rather than an assembly, so the "
                f"block began on a layer row and its first layer is missing"
            )
        return None

    @property
    def name_is_suspect(self) -> bool:
        """Whether the name reads like a material rather than an assembly.

        On a thin block this means the block is not an assembly. On a block
        with a real build-up it means only that the name is wrong, which is a
        caption problem, not a quantity problem -- so the quantities are kept
        and the name is reported as unreliable.
        """
        return bool(_MATERIAL_LIKE_NAME_RE.search(self.name))

    @property
    def is_slab_on_grade(self) -> bool:
        """Whether this is the ground slab rather than a suspended floor.

        The F group mixes the two: AB_Fourplex_01's F1 is `SLAB ON GRADE` and
        F2 is the floor between storeys. F1 is also the more referenced of the
        two, so picking by reference count alone puts sub-slab insulation and
        granular fill into a first-floor ceiling -- which on this design was
        the second largest line in the bill.
        """
        return bool(re.search(r"SLAB[\s-]*ON[\s-]*GRADE|GROUND\s+SLAB", self.name, re.I))

    @property
    def unspecified(self) -> list[Layer]:
        """Layers no quantity can be produced for, and why."""
        return [x for x in self.layers if not x.quantifiable]

    def gaps(self) -> list[str]:
        out: list[str] = []
        for layer in self.layers:
            if layer.is_placeholder:
                out.append(
                    f"{self.tag} layer {layer.index + 1} '{layer.material}' is left "
                    f"unspecified by the schedule; no material and no carbon factor "
                    f"can be assigned to it"
                )
            elif layer.deferred_to:
                out.append(
                    f"{self.tag} layer {layer.index + 1} '{layer.material}' defers to "
                    f"the {layer.deferred_to.lower()} drawings and is counted there, "
                    f"not here"
                )
            elif layer.thickness_mm is None:
                out.append(
                    f"{self.tag} layer {layer.index + 1} '{layer.material}' states no "
                    f"thickness, so no volume can be computed for it"
                )
            elif layer.coverage[0] == 0.0:
                out.append(f"{self.tag} layer {layer.index + 1} '{layer.material}' is "
                           f"{layer.coverage[1]}")
        return out


def defer_match(text: str) -> str | None:
    """The discipline a cell defers its quantity to, if it names one."""
    m = _DEFER_RE.search(text)
    return m.group(1).title() if m else None


# Glyph-ID shifts to try on a dimension cell the global repair declines.
# 0x1D explains every affected sheet in the catalogue; the rest are a sweep.
_CELL_SHIFTS = (0x1D, 0x1F, 0x1E, 0x20)


def repair_schedule_cell(text: str) -> str:
    """Recover a schedule cell that `intake.textrepair` deliberately refuses.

    Ontario's five multiplex schedules are glyph-ID encoded, and the whole
    sheet decodes under a single 0x1D shift: `7<3(` is `TYPE`, `9$5` is `VAR`,
    and `\\x16\\x12\\x17\\x05\\x12\\x14\\x1cPP` is `3/4"/19mm`. The global
    repair handles the first two and refuses the third, because `PP` -- which
    is `mm` -- contains letters, and any cell with letters is left alone. That
    guard is what stops `R-22` becoming `oJOO` across 1,465 pages of sheet
    classification, so it is not loosened; this is scoped to schedule cells.

    Two kinds of cell need this. A thickness such as `3/4"/19mm` is refused
    because `PP` contains letters, and an assembly tag such as `W1` is refused
    because it is too short to score as prose, has one digit where a sheet
    number needs two, and contains a letter so it fails the dimension test.

    A shift is accepted only when the result is one of those two things: a real
    numeric thickness, or a well-formed assembly tag. Word-likeness is
    deliberately not enough -- a dimension cell that comes out as prose means
    the shift was wrong, and a wrong thickness is worse than an unread one. A
    cell with no control characters is returned untouched, since it was never
    glyph-ID encoded.
    """
    if not any(ord(c) < 0x20 and c not in "\n\r\t" for c in text):
        return text
    for by in _CELL_SHIFTS:
        cand = "".join(
            chr(o + by) if 0 < (o := ord(c)) < 0x80 else c for c in text
        )
        if parse_thickness(cand)[0] is not None or _TAG_RE.match(cand):
            return cand
    return text


def _spans(page: pymupdf.Page) -> list[tuple[float, float, str]]:
    """(row, column, text) for every span, rotation corrected.

    Delegates to the shared reader so the schedules and the level ladder undo
    page rotation the same way, and passes the scoped cell repair that accepts
    a glyph-ID shift only when it yields a real thickness or tag.
    """
    return read_spans(page, repair_schedule_cell)


def _cluster_x(values: list[float], tol: float = 9.0) -> list[tuple[float, int]]:
    """Group x positions into columns. Returns [(mean x, count)], left first."""
    out: list[list[float]] = []
    for v in sorted(values):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [(sum(c) / len(c), len(c)) for c in out]


def _looks_like_thickness(text: str) -> bool:
    t = text.strip().upper()
    return bool(t) and (t in _NO_THICKNESS or parse_thickness(t)[0] is not None)


def learn_columns(
    cells: list[tuple[float, float, str]], desc_x: float
) -> tuple[float | None, float | None, float | None]:
    """Find the thickness, material and name columns of one schedule table.

    Each firm lays this sheet out differently. Alberta puts the thickness and
    material 36 pt either side of a centred DESCRIPTION header; BC's
    description column is 194 pt wide; Ontario stacks its headers at one x.
    Fixed offsets therefore only ever describe the firm they were measured on,
    which is how this parser first read 7 of 7 Alberta sets and 0 of 7 BC ones.

    So the columns are learned from the cells themselves: positions are
    clustered, the cluster whose contents parse as thicknesses is the thickness
    column, the wordiest one to its right is the material column, and a column
    sitting at the header's own x with neither is the assembly name.
    """
    columns = _cluster_x([x for _, x, _ in cells])
    if not columns:
        return None, None, None

    scored: list[tuple[float, int, float, float]] = []
    for cx, n in columns:
        members = [t for _, x, t in cells if abs(x - cx) <= 9.0]
        if not members:
            continue
        thick = sum(1 for t in members if _looks_like_thickness(t)) / len(members)
        # A thickness cell is never "wordy", even when it is the word VAR.
        # Without this exclusion `VAR` scores as prose -- it is three letters --
        # so a thickness column with several unstated layers crosses the
        # wordiness threshold, is rejected as the thickness column, and is then
        # chosen as the material column because it holds the most cells. That is
        # exactly what happened to Quebec's foundation tables, whose "materials"
        # came out as 1/8"/3mm and 3"/75mm.
        wordy = sum(
            1 for t in members if _WORDY_RE.search(t) and not _looks_like_thickness(t)
        ) / len(members)
        scored.append((cx, n, thick, wordy))
    if not scored:
        return None, None, None

    # The thickness column: mostly dimensions, and never mostly words.
    thickness = max(
        (c for c in scored if c[2] >= 0.5 and c[3] < 0.5), key=lambda c: (c[2], c[1]), default=None
    )
    thick_x = thickness[0] if thickness else None

    # The material column: the wordiest column right of the thickness one,
    # or simply the wordiest if no thickness column was found.
    material_pool = [
        c for c in scored if c[3] >= 0.5 and (thick_x is None or c[0] > thick_x)
    ] or [c for c in scored if c[3] >= 0.5]
    material = max(material_pool, key=lambda c: (c[1], c[3]), default=None)
    mat_x = material[0] if material else None

    # The assembly name sits near the header's own x and is neither of the
    # above. Chosen by how many cells it holds rather than by proximity alone:
    # Atlantic's name column is 34 pt from its DESCRIPTION header with 9 names
    # in it, while a 1-cell noise cluster sits 3 pt away. A 24 pt window picked
    # the noise, so every block began on a layer row and all 10 of its W, R, P
    # and N assemblies were refused as "name is a material".
    name_pool = [
        c
        for c in scored
        if c[0] not in {thick_x, mat_x} and abs(c[0] - desc_x) < NAME_COLUMN_WINDOW
    ]
    name_x = (
        max(name_pool, key=lambda c: (c[1], -abs(c[0] - desc_x)))[0] if name_pool else None
    )
    return thick_x, mat_x, name_x


def _mark_shared_cavities(layers: list[Layer]) -> None:
    """Pair a framing layer with the cavity fill of equal depth beside it.

    Equal thickness plus adjacency is the test, because that is what makes them
    the same space: a 140 mm stud layer next to a 140 mm batt layer is one
    140 mm cavity, while a 140 mm stud next to 25 mm of rigid insulation is two
    separate thicknesses of wall.
    """
    for a, b in zip(layers, layers[1:], strict=False):
        if a.thickness_mm is None or b.thickness_mm is None:
            continue
        if abs(a.thickness_mm - b.thickness_mm) > 1.0:
            continue
        if (a.is_framing and b.is_cavity_fill) or (a.is_cavity_fill and b.is_framing):
            a.shares_cavity_with, b.shares_cavity_with = b.index, a.index


def assemblies_on_page(page: pymupdf.Page, sheet: str | None = None) -> list[Assembly]:
    """Every assembly on one schedule sheet.

    The sheet is several independent tables side by side, so each group's
    column positions are read from its own header row rather than assumed.
    """
    spans = _spans(page)
    # Group banners ("W - EXTERIOR WALL ASSEMBLIES") appear on some firms'
    # sheets and not others, so they enrich the result rather than gate it.
    # Requiring one is what made this parser read 7 of 7 Alberta sets and 0 of
    # 7 BC ones; the group letter is in the tag anyway.
    groups = [(y, x, _GROUP_RE.match(t)) for y, x, t in spans if _GROUP_RE.match(t)]

    # Each DESCRIPTION header starts a table; its x gives the layer columns and
    # its y gives the top of the block.
    headers = [(y, x) for y, x, t in spans if t.upper() == "DESCRIPTION"]
    out: list[Assembly] = []

    for desc_y, desc_x in headers:
        # The group whose header sits above this table and shares its column.
        candidates = [
            (gy, gx, m) for gy, gx, m in groups if gy < desc_y and abs(gx - desc_x) < 500
        ]
        letter, group_name = "", ""
        if candidates:
            _, _, m = max(candidates, key=lambda g: g[0])
            letter, group_name = m.group(1).upper(), m.group(2).strip().title()

        # This table's horizontal extent: from the column left of DESCRIPTION
        # to the one right of it, taken from the header row itself so the width
        # is the sheet's own rather than a number measured on one firm.
        row_headers = sorted(
            x for y, x, t in spans if abs(y - desc_y) <= 12.0 and t.upper() in _HEADER_WORDS
        )
        left = max((x for x in row_headers if x < desc_x - 1), default=desc_x - 240.0)
        right = min((x for x in row_headers if x > desc_x + 1), default=desc_x + 240.0)

        # Where this table ends: the next DESCRIPTION header below it in the
        # same horizontal span.
        nxt = [y for y, x in headers if y > desc_y and left <= x <= right]
        bottom = min(nxt) if nxt else float("inf")

        cells = [
            (y, x, t)
            for y, x, t in spans
            if desc_y < y < bottom and left < x < right and t.upper() not in _HEADER_WORDS
        ]
        if not cells:
            continue

        thick_x, mat_x, name_x = learn_columns(cells, desc_x)
        if mat_x is None:
            continue
        if name_x is None:
            name_x = desc_x

        band = [
            (y, x, t)
            for y, x, t in cells
            if min(
                abs(x - name_x),
                abs(x - mat_x),
                abs(x - thick_x) if thick_x is not None else 1e9,
            )
            < COL_TOL
        ]
        if not band:
            continue

        # Tags live in the TYPE column, which is left of DIAGRAM and so left of
        # this table's own span.
        tag_lo = left - 420.0
        tags = [
            (y, x, t)
            for y, x, t in spans
            if _TAG_RE.match(t) and desc_y < y < bottom and tag_lo <= x <= left
        ]
        first_of_table = len(out)

        thicknesses = (
            {round(y, 1): t for y, x, t in band if abs(x - thick_x) < COL_TOL}
            if thick_x is not None
            else {}
        )
        # Text cells, in sheet order: the names and the material layers. Some
        # firms give the name its own centred column (Alberta), others put it
        # as the first row of the material column (BC).
        text_cells = [
            (y, x, t)
            for y, x, t in band
            if (abs(x - mat_x) < COL_TOL or (name_x is not None and abs(x - name_x) < COL_TOL))
            and t.upper() not in _CONTINUATION
        ]

        # How a new assembly is recognised depends on the layout, and the two
        # strategies disagree on each other's sheets.
        #
        # Where the firm gives the name its own column (Alberta, Quebec,
        # Ontario's ADUs), a cell in that column starts an assembly. That is
        # exact, and segmenting those sheets by tag position instead broke
        # Alberta's P3 -- an assembly whose build-up matches the IFC to the
        # millimetre.
        #
        # Where it does not (BC, Atlantic), the name is simply the first row of
        # the material column, and the tags are what separate one block from
        # the next. The absence of a thickness cannot be used there, because
        # those firms omit the thickness cell for barrier layers rather than
        # writing VAR.
        has_name_column = name_x is not None and abs(name_x - mat_x) > COL_TOL

        blocks: dict[int, list[tuple[float, str]]] = {}
        if has_name_column:
            index = -1
            for y, x, text in text_cells:
                if abs(x - name_x) < COL_TOL:
                    index += 1
                if index >= 0:
                    blocks.setdefault(index, []).append((y, text))
        else:
            # Midpoints between consecutive tags. This is imprecise -- BC
            # prints its tag level with the first layer rather than beside the
            # name, so a midpoint can cut a block's last rows off -- but
            # anchoring relative to the tag row instead was measured and is
            # worse: it splits more blocks, and the extra ones begin on a layer
            # so their "names" come out as "FLOOR FINISH w/ UNDERLAY" or "AT
            # EAVE, VALLEY AND RIDGE". Catalogue-wide that moved built-depth
            # median from 5.8% to 7.9%, exact matches from 48 to 37, and
            # introduced a 1210% worst case. A truncated build-up is a smaller
            # error than a fabricated one.
            tag_ys = sorted(ty for ty, _, _ in tags)
            bounds = [(a + b) / 2 for a, b in zip(tag_ys, tag_ys[1:], strict=False)]
            for y, _x, text in text_cells:
                blocks.setdefault(sum(1 for b in bounds if y > b), []).append((y, text))

        for index in sorted(blocks):
            rows = sorted(blocks[index])
            if not rows:
                continue
            # The topmost row of a block names the assembly; the rest are its
            # layers, outside in.
            name_y_val, name_text = rows[0]
            current = Assembly(
                tag="",
                name=name_text,
                group=group_name,
                group_letter=letter,
                sheet=sheet,
                page=page.number,
                name_y=name_y_val,
            )
            out.append(current)

            for y, text in rows[1:]:
                paired = next(
                    (v for ty, v in thicknesses.items() if abs(ty - y) <= ROW_DY), None
                )
                # A layer with no thickness cell is still a layer; its depth is
                # simply not stated, which is a gap rather than a reason to drop
                # the material from the build-up.
                mm, note = parse_thickness(paired) if paired is not None else (None, None)
                material = _CW_TAIL_RE.sub("", _DEFER_RE.sub("", text)).strip(" ,")
                if not material:
                    # The whole cell was a cross-reference, e.g. F1's bare
                    # "REFER TO STRUCTURAL" under the slab. That annotates the
                    # layer above rather than being a layer of its own.
                    if current.layers and defer_match(text):
                        current.layers[-1].deferred_to = defer_match(text)
                    continue
                defer = _DEFER_RE.search(text)
                current.layers.append(
                    Layer(
                        index=len(current.layers),
                        material=material,
                        thickness_mm=mm,
                        note=note,
                        deferred_to=defer.group(1).title() if defer else None,
                        is_placeholder=bool(_PLACEHOLDER_RE.search(text)),
                        stated_no_thickness=(
                            paired is not None
                            and paired.strip().upper() in _NO_THICKNESS
                        ),
                    )
                )

        _attach_tags(out[first_of_table:], tags)

    for asm in out:
        # The tag carries the group letter, so a sheet with no group banner
        # still resolves its groups. Only the readable group *name* depends on
        # the banner, and that is description, not data.
        if asm.tag:
            # Always from the tag, which is the authoritative source: a banner
            # may sit above a table it does not describe, and BC's FW group
            # must not be read as F.
            asm.group_letter = tag_prefix(asm.tag)
        _mark_shared_cavities(asm.layers)
    return [a for a in out if a.layers and a.tag]


def _attach_tags(assemblies: list[Assembly], tags: list[tuple[float, float, str]]) -> None:
    """Give each assembly of one table the tag sitting beside its block.

    A tag is vertically centred in its own block rather than aligned to the
    assembly's name row, so each tag is assigned to the last assembly whose
    name appears above it.
    """
    # Sorted by y with an explicit key: two assemblies can share a name row,
    # and comparing the tuples would then try to order Assembly objects.
    named = sorted(
        (a for a in assemblies if a.name_y is not None), key=lambda a: a.name_y
    )
    for tag_y, _, tag in sorted(tags):
        above = [a for a in named if a.name_y <= tag_y + ROW_DY]
        if above and not above[-1].tag:
            above[-1].tag = tag


def assemblies_for(design) -> tuple[dict[str, Assembly], list[str]]:
    """Every trustworthy assembly in a design's schedule sheets, by tag.

    Returns (assemblies, rejected) where `rejected` describes each assembly
    whose parse did not survive `Assembly.implausible` and so is reported as
    unreadable rather than used.
    """
    from ecarbon.intake import inventory
    from ecarbon.models import SheetType

    sheets, _, _ = inventory(design.drawings_pdf)
    found: dict[str, Assembly] = {}
    rejected: list[str] = []
    doc = pymupdf.open(design.drawings_pdf)
    try:
        for s in sheets:
            if s.sheet_type is not SheetType.ASSEMBLY_SCHEDULE or not s.readable:
                continue
            for asm in assemblies_on_page(doc[s.page], s.sheet_no):
                if not asm.tag:
                    continue
                reason = asm.implausible()
                if reason:
                    # Read correctly, depth withheld by the drawing: a different
                    # claim from a parse we do not trust, so it is worded as one.
                    verdict = (
                        "was read, but"
                        if reason.startswith("the drawing gives")
                        else "could not be read reliably:"
                    )
                    rejected.append(
                        f"Assembly {asm.tag} on sheet {asm.sheet} {verdict} {reason}. "
                        f"Its materials are not counted."
                    )
                    continue
                found[asm.tag] = asm
    finally:
        doc.close()
    return found, rejected


# A layer's description, in the drawing's words, mapped to the catalogue's
# standardised `CMHC_` material names -- the same names the IFCs use, so one
# table serves both and the factor store needs only one set of keys.
#
# Ordered most specific first: "METAL STUD FRAMING" must not match the wood
# rule, and W2's studs really are steel even though the IFC generalises them to
# CMHC_Wood Framing. Anything not listed resolves to None and is reported as
# unmatched rather than guessed.
_MATERIAL_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"METAL\s+(STUD|Z-?GIRT|FRAMING)|FURRING\s+CHANNEL", re.I), "CMHC_Metal Framing"),
    (re.compile(r"GYPSUM", re.I), "CMHC_Gypsum Board"),
    (re.compile(r"PLYWOOD|EXTERIOR\s+SHEATHING|OSB", re.I), "CMHC_Plywood"),
    (re.compile(r"CAVITY\s+(IN-?FILL|FILL)|BATT|ACOUSTIC", re.I), "CMHC_Insulation, Mineral Wool Semi-Rigid"),
    (re.compile(r"RIGID\s+INSULATION", re.I), "CMHC_Insulation, Rigid"),
    (re.compile(r"CONCRETE|GRADE\s+BEAM|SLAB", re.I), "CMHC_Concrete, CIP"),
    (re.compile(r"WOOD\s+(STUD|STRAPPING|FURRING|FRAMING)|TRUSS|JOIST|LUMBER", re.I), "CMHC_Wood Framing"),
]


def cmhc_material(layer: Layer) -> str | None:
    """The `CMHC_` material name for a layer, or None if it has no match.

    A placeholder layer returns None whatever its words say. `CMHC_Exterior
    Finish Placeholder 01` does have a factor-store mapping, to vinyl siding,
    and following it would silently pick a cladding that CMHC deliberately left
    open -- on roughly 12% of a home's embodied carbon. The choice belongs to
    whoever is costing the building, so the layer is reported unspecified and
    the options are offered instead.
    """
    if layer.is_placeholder or layer.thickness_mm is None:
        return None
    for pattern, name in _MATERIAL_RULES:
        if pattern.search(layer.material):
            return name
    return None


def assembly_tags_used(design) -> dict[str, int]:
    """How often each assembly tag is referenced on the drawings.

    The schedule lists every assembly the catalogue offers, but a given design
    uses only some of them: AB_Fourplex_01's schedule carries W1 and W2, and
    the plans reference W2 sixty-eight times and W1 once. Reference count is
    therefore how the applicable assembly is chosen, rather than taking the
    first one listed.
    """
    import collections

    from ecarbon.intake import inventory
    from ecarbon.models import SheetType

    wanted = {
        SheetType.SECTION,
        SheetType.FLOOR_PLAN,
        SheetType.FOUNDATION_PLAN,
        SheetType.DETAIL,
        SheetType.ELEVATION,
    }
    counts: collections.Counter[str] = collections.Counter()
    sheets, _, _ = inventory(design.drawings_pdf)
    doc = pymupdf.open(design.drawings_pdf)
    try:
        for s in sheets:
            if s.sheet_type not in wanted or not s.readable:
                continue
            for block in doc[s.page].get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        # Same scoped repair as the schedule reader. Ontario's
                        # plan sheets are glyph-ID encoded too, so without it
                        # the tag references stay mojibake, no assembly is ever
                        # selected, and a schedule that now parses goes unused.
                        t = repair_schedule_cell(repair(span["text"].strip())[0])
                        if _TAG_RE.match(t):
                            counts[t] += 1
    finally:
        doc.close()
    return dict(counts)


def dominant_tag(
    tags: dict[str, int],
    letter: str,
    available: set[str],
    exclude: set[str] | None = None,
) -> str | None:
    """The most-referenced assembly of one group that the schedule defines."""
    skip = exclude or set()
    want = letter.upper()
    scoped = {
        t: n
        for t, n in tags.items()
        if tag_prefix(t) == want and t in available and t not in skip
    }
    return max(scoped, key=lambda t: scoped[t]) if scoped else None
