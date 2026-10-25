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
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf

from ecarbon.intake.textrepair import repair

# "N - FOUNDATION WALL ASSEMBLIES", "W - EXTERIOR WALL ASSEMBLIES"
_GROUP_RE = re.compile(r"^([A-Z])\s*-\s*(.+?)\s+ASSEMBL", re.I)
# W1, W2, P1a, R3, F5, N1
_TAG_RE = re.compile(r"^[A-Z]\d{1,2}[a-z]?$")
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
THICKNESS_DX = 36.0
MATERIAL_DX = 36.0
# Half the gap between sub-columns, so the three never overlap.
COL_TOL = 14.0
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


def _spans(page: pymupdf.Page) -> list[tuple[float, float, str]]:
    out: list[tuple[float, float, str]] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for s in line.get("spans", []):
                t = s["text"].strip()
                if t:
                    out.append((s["bbox"][1], s["bbox"][0], repair(t)[0]))
    return sorted(out)


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
    groups = [(y, x, _GROUP_RE.match(t)) for y, x, t in spans if _GROUP_RE.match(t)]
    if not groups:
        return []

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

        thick_x = desc_x - THICKNESS_DX
        mat_x = desc_x + MATERIAL_DX
        # Everything in this table's own three columns, below its header.
        band = [
            (y, x, t)
            for y, x, t in spans
            if y > desc_y
            and min(abs(x - desc_x), abs(x - thick_x), abs(x - mat_x)) < COL_TOL
        ]
        # Stop at the next table in the same column.
        nxt = [y for y, x in headers if y > desc_y and abs(x - desc_x) < COL_TOL]
        if nxt:
            band = [(y, x, t) for y, x, t in band if y < min(nxt)]
        if not band:
            continue

        tags = [
            (y, t)
            for y, x, t in spans
            if _TAG_RE.match(t) and desc_y < y and abs(x - (desc_x - 393)) < TAG_DX
        ]

        # Walk the band: a description with no thickness beside it is an
        # assembly name and starts a new block; one with a thickness is a layer.
        thicknesses = {round(y, 1): t for y, x, t in band if abs(x - thick_x) < COL_TOL}
        current: Assembly | None = None
        for y, x, text in band:
            is_name = abs(x - desc_x) < COL_TOL
            is_material = abs(x - mat_x) < COL_TOL
            if not (is_name or is_material):
                continue
            if text.upper() in _CONTINUATION:
                continue
            paired = next(
                (v for ty, v in thicknesses.items() if abs(ty - y) <= ROW_DY), None
            )
            if is_name and paired is None:
                # An assembly name: centred under the header, no thickness.
                current = Assembly(
                    tag="",
                    name=text,
                    group=group_name,
                    group_letter=letter,
                    sheet=sheet,
                    page=page.number,
                )
                out.append(current)
                continue
            if current is None:
                continue
            # A material with no thickness cell beside it is still a layer; its
            # thickness is simply not stated, which is a gap, not a reason to
            # drop the material from the build-up.
            mm, note = parse_thickness(paired) if paired is not None else (None, None)
            material = _CW_TAIL_RE.sub("", _DEFER_RE.sub("", text)).strip(" ,")
            if not material:
                # The whole cell was a cross-reference, e.g. F1's bare "REFER
                # TO STRUCTURAL" sitting under the slab. That annotates the
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
                )
            )

        # Attach each tag to the assembly whose vertical block contains it.
        for i, asm in enumerate(out):
            if asm.tag or asm.group_letter != letter:
                continue
            top = min((lay_y for lay_y, _, _ in band), default=desc_y)
            lo = top if i == 0 else None
            _ = lo  # block bounds come from the name rows below
        _attach_tags(out, tags, letter)

    for asm in out:
        _mark_shared_cavities(asm.layers)
    return [a for a in out if a.layers]


def _attach_tags(assemblies: list[Assembly], tags: list[tuple[float, str]], letter: str) -> None:
    """Give each assembly in this group the tag that sits in its block."""
    group = [a for a in assemblies if a.group_letter == letter]
    untagged = [a for a in group if not a.tag]
    free = [t for t in sorted(tags) if t[1].upper().startswith(letter)]
    # Both lists are in sheet order, so position is the pairing.
    for asm, (_, tag) in zip(untagged, free, strict=False):
        asm.tag = tag


def assemblies_for(design) -> dict[str, Assembly]:
    """Every assembly in a design's schedule sheets, by tag."""
    from ecarbon.intake import inventory
    from ecarbon.models import SheetType

    sheets, _, _ = inventory(design.drawings_pdf)
    found: dict[str, Assembly] = {}
    doc = pymupdf.open(design.drawings_pdf)
    try:
        for s in sheets:
            if s.sheet_type is not SheetType.ASSEMBLY_SCHEDULE or not s.readable:
                continue
            for asm in assemblies_on_page(doc[s.page], s.sheet_no):
                if asm.tag:
                    found[asm.tag] = asm
    finally:
        doc.close()
    return found


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
                        t = repair(span["text"].strip())[0]
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
    scoped = {
        t: n
        for t, n in tags.items()
        if t.upper().startswith(letter) and t in available and t not in skip
    }
    return max(scoped, key=lambda t: scoped[t]) if scoped else None
