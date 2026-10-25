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
