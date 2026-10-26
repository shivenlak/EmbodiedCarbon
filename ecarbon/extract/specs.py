"""STEP 10 -- reading dimensioned specifications out of drawing notes.

Some of the highest-carbon quantities are not measured off the geometry at all;
they are *stated* on the structural sheets, and stating them is more reliable
than inferring them. From AB_Fourplex_01 S201:

    "CONCRETE SLAB ON GRADE TO CONSIST OF 130mm THICK CONCRETE SLAB R/W. 10M @ 300"
    "200x1200 DP. CONC. GRADE BEAM R/W"
    "PILE MINIMUM SIZE SHALL BE 400mmO"

That gives a 130 mm slab and 200 x 1200 grade beams on screw piles. Each is a
direct measurement in the sense the scope means -- read off the drawing, not
assumed -- so the only thing left to measure geometrically is the footprint
area and the beam run length.

### Why this matters more than it looks

The IFC models the same foundation as a single **454 mm** layer of concrete
over the footprint: 136.4 m2 x 0.454 m = 61.9 m3. The real system is about
17.7 m3 of slab plus about 14.4 m3 of grade beam. So the BIM model overstates
foundation concrete by roughly 2x, and the Construction Cost Estimate's
"grade beam construction on screw piles" (RESEARCH S16) agrees with the
drawings, not the model.

Foundations are 32-44% of embodied carbon by two independent references
(S17, docs/element_priority.md), so **for this element the PDF is the better
source than the IFC** -- and the IFC must not be used to score it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ecarbon.intake.textrepair import repair

# "130mm THICK CONCRETE SLAB", "100mm THK. SLAB", "slab ... 130 mm thick"
# Deliberately tight: a loose version matched "100mm FROST INSULATION ...
# UNDER SLAB" on S102 and reported a 100 mm slab where S201 states 130 mm.
_SLAB_RE = re.compile(
    r"(\d{2,4})\s*mm\s*(?:THICK|THK\.?)\s*(?:REINF\.?\s*|CONC(?:RETE)?\.?\s*)*SLAB",
    re.I,
)
# "200x1200 DP. CONC. GRADE BEAM", "GRADE BEAM 250 x 900 DEEP"
# DP./DEEP is REQUIRED. Without it the pattern matched "4-15M x 1200mm LG.
# DOWELS AT ALL PILE TO GRADE BEAM LOCATIONS" and reported a 1200x1200 beam --
# a 6x error on the largest single concrete item.
_BEAM_RE = re.compile(
    r"(\d{2,4})\s*[xX×]\s*(\d{2,4})\s*(?:DP\.?|DEEP)\s*"
    r"(?:CONC(?:RETE)?\.?\s*)?GRADE\s*BEAM",
    re.I,
)
_BEAM_ALT_RE = re.compile(
    r"GRADE\s*BEAM[^.;]{0,20}?(\d{2,4})\s*[xX×]\s*(\d{2,4})\s*(?:DP\.?|DEEP)",
    re.I,
)

# A strip footing's section, as Quebec's S100 states it:
#   "DIMENSIONS AND REINFORCEMENT FOR STRIP FOOTING:
#    FOOTING 750x200 SEE SECTION D   FOOTING 800x200 SEE SECTION A"
#
# `FOOTING` must immediately precede the pair. The grade-beam pattern above
# already learned this lesson the expensive way: a looser form matched
# "4-15M x 1200mm LG. DOWELS AT ALL PILE TO GRADE BEAM LOCATIONS" and reported
# a 1200x1200 beam, a six-fold error on the largest concrete item.
_FOOTING_RE = re.compile(r"FOOTING\s*:?\s*(\d{3,4})\s*[xX×]\s*(\d{2,4})\b", re.I)

# BC states its footings in a schedule table instead, with dual units and the
# metric in brackets, on sheet S001:
#
#   SF1  STRIP  [70 - 90 kg/m3]    2'-0" [600] WD x 18" [450] DP
#   SF2  STRIP  [110 - 150 kg/m3]  2'-0" [600] WD x 10" [250] DP
#   SF3  STRIP  [220 kg/m3]        3'-0" [900] WD x 18" [450] DP
#
# The bracketed millimetre values are taken and the imperial ignored, since
# the two are the same dimension stated twice. The kg/m3 bracket in between is
# a reinforcement rate and must not be read as a dimension, which is why the
# pattern anchors on WD and DP rather than on brackets alone.
_FOOTING_WD_DP_RE = re.compile(
    r"\[\s*(\d{3,4})\s*\]\s*WD\s*[xX×]\s*[^\[\]]{0,12}\[\s*(\d{2,4})\s*\]\s*DP",
    re.I,
)

# A strip footing is wider than it is deep and sits within these bounds. A pair
# outside them is some other dimension that happened to follow the word.
MIN_FOOTING_WIDTH_MM, MAX_FOOTING_WIDTH_MM = 300.0, 2000.0
MIN_FOOTING_DEPTH_MM, MAX_FOOTING_DEPTH_MM = 100.0, 800.0
# Sections differing by more than this in area are different footing types and
# the choice between them starts to matter, so it gets said.
FOOTING_SECTION_SPREAD = 0.25


def footing_sections(text: str) -> list[tuple[float, float]]:
    """Every plausible (width, depth) strip-footing section stated in `text`.

    Sorted smallest area first, deterministically. Where a schedule gives
    several sections it does not say which runs where, and text order is
    arbitrary, so the caller takes the smallest and reports the figure as a
    lower bound. BC's three span 0.15 to 0.405 m2 -- a factor of 2.7 -- so
    picking the largest could overstate the footing concrete nearly threefold.
    Understating with the alternatives named is the recoverable direction.
    """
    out: list[tuple[float, float]] = []
    for pattern in (_FOOTING_RE, _FOOTING_WD_DP_RE):
        for m in pattern.finditer(text):
            w, d = float(m.group(1)), float(m.group(2))
            if not (MIN_FOOTING_WIDTH_MM <= w <= MAX_FOOTING_WIDTH_MM):
                continue
            if not (MIN_FOOTING_DEPTH_MM <= d <= MAX_FOOTING_DEPTH_MM):
                continue
            if d > w:  # a footing is wider than it is deep
                continue
            if (w, d) not in out:
                out.append((w, d))
    return sorted(out, key=lambda wd: wd[0] * wd[1])

# Sheets that define the foundation, most authoritative first. A detail sheet
# shows a condition; the foundation plan and sections state the design.
_SHEET_PRIORITY = ("S2", "S4", "S1", "S3", "S0")


def sheet_rank(sheet: str) -> int:
    up = (sheet or "").upper()
    for i, prefix in enumerate(_SHEET_PRIORITY):
        if up.startswith(prefix):
            return i
    return len(_SHEET_PRIORITY)
# "PILE MINIMUM SIZE SHALL BE 400mmO", "400mm DIA. PILE", "250 DIA SCREW PILE"
_PILE_DIA_RE = re.compile(
    r"(?:PILE[^.]{0,60}?(\d{2,4})\s*mm\s*(?:Ø|DIA|O\b)"
    r"|(\d{2,4})\s*mm\s*(?:Ø|DIA\.?)[^.]{0,30}?PILE)",
    re.I,
)
# "100mm FROST" insulation under grade beams
_FROST_RE = re.compile(r"(\d{2,4})\s*mm\s*FROST", re.I)
# Reinforcement: "10M @ 300 O/C", "4-15M VERTICAL"
_REBAR_SPACING_RE = re.compile(r"(\d{1,2})M\s*@\s*(\d{2,4})\s*(?:mm)?\s*O/?C", re.I)
_REBAR_COUNT_RE = re.compile(r"(\d{1,2})\s*-\s*(\d{1,2})M", re.I)

SCREW_PILE_RE = re.compile(r"SCREW\s*PILE|HELICAL\s*PILE", re.I)
CAST_PILE_RE = re.compile(r"(?:CAST[- ]?IN[- ]?PLACE|CONCRETE)\s*(?:PILE|PIER|CAISSON)", re.I)
STRIP_FOOTING_RE = re.compile(r"(?:STRIP|SPREAD|CONTINUOUS)\s*FOOTING", re.I)


@dataclass
class FoundationSpec:
    """Dimensioned foundation components, as stated on the drawings."""

    slab_thickness_mm: float | None = None
    grade_beam_width_mm: float | None = None
    grade_beam_depth_mm: float | None = None
    footing_width_mm: float | None = None
    footing_depth_mm: float | None = None
    # Other footing sections the drawings state, when more than one exists.
    other_footing_sections: list[tuple[float, float]] = field(default_factory=list)
    pile_diameter_mm: float | None = None
    frost_insulation_mm: float | None = None
    screw_piles: bool = False
    cast_in_place_piles: bool = False
    strip_footings: bool = False
    rebar_notes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    @property
    def system(self) -> str:
        """The foundation system, named rather than assumed."""
        if self.grade_beam_width_mm and self.screw_piles:
            return "grade_beam_on_screw_piles"
        if self.grade_beam_width_mm and self.cast_in_place_piles:
            return "grade_beam_on_cast_piles"
        if self.grade_beam_width_mm:
            return "grade_beam"
        if self.strip_footings:
            return "strip_footing"
        return "unknown"

    @property
    def grade_beam_section_m2(self) -> float | None:
        """Cross-sectional area of a grade beam, m2 per metre of run."""
        if not (self.grade_beam_width_mm and self.grade_beam_depth_mm):
            return None
        return (self.grade_beam_width_mm / 1000.0) * (self.grade_beam_depth_mm / 1000.0)

    def slab_volume_m3(self, footprint_m2: float) -> float | None:
        if self.slab_thickness_mm is None:
            return None
        return footprint_m2 * (self.slab_thickness_mm / 1000.0)

    def grade_beam_volume_m3(self, run_length_m: float) -> float | None:
        section = self.grade_beam_section_m2
        return None if section is None else run_length_m * section

    @property
    def footing_section_m2(self) -> float | None:
        if self.footing_width_mm is None or self.footing_depth_mm is None:
            return None
        return (self.footing_width_mm / 1000.0) * (self.footing_depth_mm / 1000.0)

    def footing_volume_m3(self, run_length_m: float) -> float | None:
        """Strip-footing concrete over a run length."""
        section = self.footing_section_m2
        return None if section is None else run_length_m * section

    @property
    def footing_section_note(self) -> str | None:
        """What to say when the drawings state more than one footing section."""
        if not self.other_footing_sections or self.footing_width_mm is None:
            return None
        chosen = self.footing_section_m2 or 0.0
        areas = [
            (w / 1000.0) * (d / 1000.0) for w, d in self.other_footing_sections
        ] + [chosen]
        if not chosen or (max(areas) - min(areas)) / max(areas) <= FOOTING_SECTION_SPREAD:
            return None
        others = ", ".join(f"{w:.0f}x{d:.0f}" for w, d in self.other_footing_sections)
        return (
            f"The schedule gives more than one strip-footing section "
            f"({self.footing_width_mm:.0f}x{self.footing_depth_mm:.0f} is used; also "
            f"{others}) and does not say which runs where. The smallest is used, so "
            f"this footing volume is a LOWER BOUND -- the largest section would give "
            f"{max(w * d for w, d in self.other_footing_sections) / (self.footing_section_m2 * 1e6):.1f}x "
            f"as much concrete."
        )

    def pile_volume_m3(self, n_piles: int, depth_m: float) -> float | None:
        """Only meaningful for cast-in-place piles.

        A screw pile is a steel product, so counting its displaced volume as
        concrete would invent concrete that is not there -- which is a large
        error on the single biggest carbon item.
        """
        if self.pile_diameter_mm is None or self.screw_piles:
            return None
        r = self.pile_diameter_mm / 2000.0
        return 3.141592653589793 * r * r * depth_m * n_piles

    @property
    def missing(self) -> list[str]:
        """What a foundation takeoff still needs. Feeds the gap report."""
        gaps: list[str] = []
        if self.slab_thickness_mm is None:
            gaps.append("slab thickness not stated")
        if self.system == "unknown":
            gaps.append("foundation system not identified")
        if self.grade_beam_width_mm and not self.grade_beam_depth_mm:
            gaps.append("grade beam depth not stated")
        return gaps


def _first_int(*groups: str | None) -> float | None:
    for g in groups:
        if g:
            try:
                v = float(g)
            except ValueError:
                continue
            if 10 <= v <= 5000:
                return v
    return None


def parse_foundation_spec(texts: dict[str, str]) -> FoundationSpec:
    """Read a foundation specification from structural sheet text.

    `texts` maps a sheet label (e.g. "S201") to that sheet's text, so every
    value can be traced to the sheet it came from -- the traceability the
    scope requires of each quantity.
    """
    spec = FoundationSpec()

    for sheet, raw in sorted(texts.items(), key=lambda kv: (sheet_rank(kv[0]), kv[0])):
        text, _ = repair(raw) if len(raw) < 400 else (raw, False)
        flat = re.sub(r"\s+", " ", text)
        found: list[str] = []

        if spec.slab_thickness_mm is None:
            m = _SLAB_RE.search(flat)
            if m and (v := _first_int(*m.groups())):
                spec.slab_thickness_mm = v
                found.append(f"slab {v:.0f}mm")
            else:
                for other in _SLAB_RE.finditer(flat):
                    if (v := _first_int(*other.groups())):
                        spec.slab_thickness_mm = v
                        found.append(f"slab {v:.0f}mm")
                        break

        if spec.grade_beam_width_mm is None:
            m = _BEAM_RE.search(flat) or _BEAM_ALT_RE.search(flat)
            if m:
                nums = [g for g in m.groups() if g]
                if len(nums) >= 2:
                    w, dp = float(nums[0]), float(nums[1])
                    # A grade beam is deeper than it is wide; some notes give
                    # the pair in the other order.
                    spec.grade_beam_width_mm, spec.grade_beam_depth_mm = min(w, dp), max(w, dp)
                    found.append(f"grade beam {spec.grade_beam_width_mm:.0f}x{spec.grade_beam_depth_mm:.0f}")

        if spec.pile_diameter_mm is None:
            m = _PILE_DIA_RE.search(flat)
            if m and (v := _first_int(*m.groups())):
                spec.pile_diameter_mm = v
                found.append(f"pile dia {v:.0f}mm")

        if spec.frost_insulation_mm is None:
            m = _FROST_RE.search(flat)
            if m and (v := _first_int(m.group(1))):
                spec.frost_insulation_mm = v
                found.append(f"frost insulation {v:.0f}mm")

        if SCREW_PILE_RE.search(flat):
            spec.screw_piles = True
            found.append("screw piles")
        if CAST_PILE_RE.search(flat):
            spec.cast_in_place_piles = True
        if STRIP_FOOTING_RE.search(flat):
            spec.strip_footings = True
            found.append("strip footings")

        if spec.footing_width_mm is None:
            sections = footing_sections(flat)
            if sections:
                spec.footing_width_mm, spec.footing_depth_mm = sections[0]
                spec.other_footing_sections = sections[1:]
                found.append(
                    f"strip footing {spec.footing_width_mm:.0f}x{spec.footing_depth_mm:.0f}"
                )

        for m in _REBAR_SPACING_RE.finditer(flat):
            note = f"{m.group(1)}M @ {m.group(2)} o/c"
            if note not in spec.rebar_notes:
                spec.rebar_notes.append(note)
        for m in _REBAR_COUNT_RE.finditer(flat):
            note = f"{m.group(1)}-{m.group(2)}M"
            if note not in spec.rebar_notes:
                spec.rebar_notes.append(note)

        if found:
            spec.sources.append(f"{sheet}: {', '.join(found)}")

    return spec


# Structural sheets carry the foundation design. Filtering by SHEET TYPE was
# tried first and silently excluded BC and QC entirely, because BC titles its
# foundation plan "PLAN FOUNDATION / MAIN FLOOR" and QC uses "STRUCTURAL
# PLANS", neither of which the type rules matched. Taking every readable
# structural sheet is both simpler and more robust: a spec note is a spec note
# wherever it is drawn.
def structural_texts(design, max_sheets: int = 40) -> dict[str, str]:
    """Text of every readable structural sheet, keyed by sheet number."""
    import pymupdf

    from ecarbon.intake import inventory

    sheets, _, _ = inventory(design.drawings_pdf)
    out: dict[str, str] = {}
    doc = pymupdf.open(design.drawings_pdf)
    try:
        for s in sheets:
            if not s.readable or len(out) >= max_sheets:
                continue
            no = (s.sheet_no or "").upper()
            if no.startswith("S"):
                out[s.sheet_no or f"p{s.page + 1}"] = doc[s.page].get_text("text")
    finally:
        doc.close()
    return out


def foundation_spec_for(design) -> FoundationSpec:
    """Read the foundation specification for one design, end to end."""
    return parse_foundation_spec(structural_texts(design))
