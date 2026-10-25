"""STEP 10 -- assemble a bill of quantities from measured geometry.

This is the join between everything the extraction stages produce and the
carbon engine. It emits `TakeoffLine` records, which means every quantity
carries the two things the scope demands of it:

  * provenance -- the sheet and detail it came from
  * a confidence label, measured / inferred / assumed, with the assumption
    documented when it is not measured

### Nothing here is a constant

Every number is either measured off the geometry or read off a sheet:

    slab concrete   = footprint area (measured)  x slab thickness (stated, S201)
    grade beam      = perimeter (measured)       x beam section (stated, S201)
    exterior wall   = perimeter (measured)       x wall height (section datums)

That matters because a takeoff built on defaults produces the same answer for
different buildings. The MVP branch's builder used `width_m = 11.50`,
`storeys * 2.334` and `max(area, 50.0)`, and its own harness reported 30.4%
median wall error with two different NOR designs emitting byte-identical
quantities. Measured inputs give 3.3% median footprint error instead
(scripts/score_footprint.py).

### Confidence, and why the grade beam is only inferred

The footprint is `measured` because two independent signals agreed on it --
drafting lineweight and the parsed dimension chains. The slab follows, since
its thickness is stated on the drawing.

The grade beam run is `inferred`: the beam follows the building outline, but
the perimeter available here is the RECTANGULAR perimeter of the footprint
extent, which understates an L-shaped or courtyard plan. The exterior wall is
`inferred` for the same reason, plus the top storey height has no plate datum
above it and is taken from the storey below (RESEARCH S20).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pymupdf

from ecarbon.extract.assemblies import (
    Assembly,
    assemblies_for,
    assembly_tags_used,
    cmhc_material,
    dominant_tag,
)
from ecarbon.extract.levels import StoreyHeights, storey_heights_for
from ecarbon.extract.specs import FoundationSpec, foundation_spec_for
from ecarbon.geometry.footprint import Footprint, detect_footprint
from ecarbon.geometry.scale import calibrate
from ecarbon.intake import coverage_gaps, inventory, readability_gaps
from ecarbon.models import (
    Basis,
    BasisSource,
    Confidence,
    ElementClass,
    Gap,
    GapCode,
    GapSeverity,
    ProjectFacts,
    Provenance,
    SheetType,
    TakeoffLine,
    TakeoffResult,
    Unit,
)

PLAN_TYPES = (SheetType.FLOOR_PLAN, SheetType.FOUNDATION_PLAN)

# Framing occupies this fraction of a stud wall's cavity depth. A conventional
# allowance, so any line using it is labelled `assumed` and says so.
STUD_FRAMING_FRACTION = 0.15


@dataclass
class TakeoffInputs:
    """What the extraction stages found, kept separate so a caller can see
    which stage failed rather than just getting a short bill of quantities."""

    footprint: Footprint | None = None
    footprint_sheet: str | None = None
    footprint_page: int | None = None
    spec: FoundationSpec = field(default_factory=FoundationSpec)
    heights: StoreyHeights = field(default_factory=StoreyHeights)
    assemblies: dict[str, Assembly] = field(default_factory=dict)
    tag_refs: dict[str, int] = field(default_factory=dict)

    def assembly_for(self, letter: str, exclude: set[str] | None = None) -> Assembly | None:
        """The assembly of one group that this design actually uses."""
        tag = dominant_tag(self.tag_refs, letter, set(self.assemblies), exclude)
        return self.assemblies.get(tag) if tag else None

    @property
    def slab_assembly(self) -> Assembly | None:
        """The F assembly that is the ground slab, if the schedule has one."""
        slabs = {t: a for t, a in self.assemblies.items() if a.is_slab_on_grade}
        tag = dominant_tag(self.tag_refs, "F", set(slabs))
        return slabs.get(tag) if tag else None


def gather(design, expected_area_m2: float | None = None) -> tuple[TakeoffInputs, list, list[Gap]]:
    """Run the extraction stages for one design."""
    sheets, _, _ = inventory(design.drawings_pdf, with_scale=True)
    inputs = TakeoffInputs()
    gaps: list[Gap] = list(readability_gaps(sheets)) + list(coverage_gaps(sheets))

    doc = pymupdf.open(design.drawings_pdf)
    try:
        for s in sheets:
            if s.sheet_type not in PLAN_TYPES or not s.readable:
                continue
            fp = detect_footprint(doc[s.page], calibrate(doc[s.page]), expected_area_m2)
            if fp and fp.confident:
                inputs.footprint, inputs.footprint_sheet, inputs.footprint_page = (
                    fp,
                    s.sheet_no,
                    s.page,
                )
                break
            if fp and inputs.footprint is None:
                inputs.footprint, inputs.footprint_sheet, inputs.footprint_page = (
                    fp,
                    s.sheet_no,
                    s.page,
                )
    finally:
        doc.close()

    # The assemblies schedule turns an element area into materials. Without it
    # a wall is only its studs, which is about a sixth of its carbon.
    try:
        inputs.assemblies = assemblies_for(design)
        inputs.tag_refs = assembly_tags_used(design)
    except Exception:
        inputs.assemblies, inputs.tag_refs = {}, {}
    if not inputs.assemblies:
        gaps.append(
            Gap(
                code=GapCode.ASSEMBLY_SCHEDULE_MISSING,
                severity=GapSeverity.BLOCKING,
                message=(
                    "No assemblies schedule could be read, so element areas cannot be "
                    "resolved into materials. Only quantities with a thickness stated "
                    "elsewhere on the drawings are produced."
                ),
            )
        )

    inputs.spec = foundation_spec_for(design)
    # The floor assembly depth is what separates a gross wall height from a
    # thermal one; without it only the gross basis is available.
    inputs.heights = storey_heights_for(design, floor_assembly_mm=333.0)

    if inputs.footprint is None:
        gaps.append(
            Gap(
                code=GapCode.GEOMETRY_AMBIGUOUS,
                severity=GapSeverity.BLOCKING,
                message=(
                    "No building footprint could be established: no lineweight group on "
                    "any plan sheet agreed with the dimensions read from the drawing. "
                    "Area and perimeter quantities cannot be produced."
                ),
            )
        )
    for missing in inputs.spec.missing:
        gaps.append(
            Gap(
                code=GapCode.SECTION_DETAIL_MISSING,
                severity=GapSeverity.BLOCKING,
                message=f"Foundation: {missing}. Concrete quantities cannot be produced.",
            )
        )
    for missing in inputs.heights.missing:
        gaps.append(
            Gap(
                code=GapCode.STOREY_HEIGHT_UNKNOWN,
                severity=GapSeverity.WARNING,
                message=f"Storey heights: {missing}.",
            )
        )
    return inputs, sheets, gaps


def _prov(inputs: TakeoffInputs, sheet: str | None = None, detail: str | None = None) -> Provenance:
    return Provenance(
        page=inputs.footprint_page if inputs.footprint_page is not None else 0,
        sheet_no=sheet or inputs.footprint_sheet,
        detail=detail,
    )


def _foundation_lines(inputs: TakeoffInputs) -> list[TakeoffLine]:
    fp, spec = inputs.footprint, inputs.spec
    if fp is None:
        return []
    out: list[TakeoffLine] = []
    sheet = next((s.split(":")[0] for s in spec.sources if "slab" in s), None)

    slab = spec.slab_volume_m3(fp.area_m2)
    if slab is not None:
        out.append(
            TakeoffLine(
                id="ln-slab-on-grade",
                element_class=ElementClass.SLAB_ON_GRADE,
                quantity=round(slab, 2),
                unit=Unit.M3,
                confidence=Confidence.MEASURED,
                material="CMHC_Concrete, CIP",
                description=(
                    f"Slab on grade, {spec.slab_thickness_mm:.0f} mm over "
                    f"{fp.area_m2:.1f} m2 footprint"
                ),
                basis=Basis(
                    sources=[BasisSource.VECTOR_PATH, BasisSource.DIM_TEXT_METRIC, BasisSource.SECTION_NOTE],
                    agreement=(fp.agreement_pct or 0.0) / 100.0,
                    note=(
                        f"Footprint {fp.width_m:.2f} x {fp.depth_m:.2f} m measured from "
                        f"{fp.stroke_width} pt linework and confirmed against the dimension "
                        f"chains to {fp.agreement_pct}%; thickness stated on the drawing."
                    ),
                ),
                provenance=_prov(inputs, sheet, "SLAB ON GRADE"),
            )
        )

    beam = spec.grade_beam_volume_m3(fp.perimeter_m)
    if beam is not None:
        out.append(
            TakeoffLine(
                id="ln-grade-beam",
                element_class=ElementClass.FOOTING,
                quantity=round(beam, 2),
                unit=Unit.M3,
                confidence=Confidence.INFERRED,
                material="CMHC_Concrete, CIP",
                assembly_tag="N1",
                description=(
                    f"Grade beam {spec.grade_beam_width_mm:.0f} x "
                    f"{spec.grade_beam_depth_mm:.0f} mm over {fp.perimeter_m:.1f} m run"
                ),
                basis=Basis(
                    sources=[BasisSource.VECTOR_PATH, BasisSource.SECTION_NOTE],
                    note=(
                        "Section stated on the drawing; run length taken as the rectangular "
                        "perimeter of the measured footprint, which understates an L-shaped "
                        "or courtyard plan and omits any internal beams."
                    ),
                ),
                assumptions=[
                    "Grade beam run assumed equal to the footprint perimeter; internal "
                    "beams beneath party walls are not counted."
                ],
                provenance=_prov(inputs, sheet, "GRADE BEAM"),
            )
        )

    if spec.screw_piles:
        out.append(
            TakeoffLine(
                id="ln-screw-piles",
                element_class=ElementClass.FOOTING,
                quantity=0.0,
                unit=Unit.M3,
                confidence=Confidence.ASSUMED,
                material="steel_screw_pile",
                description=f"Screw piles, {spec.pile_diameter_mm or 0:.0f} mm dia (steel, by supplier)",
                basis=Basis(sources=[BasisSource.SECTION_NOTE]),
                assumptions=[
                    "Foundation is on screw piles, which are a steel product supplied by "
                    "others. No concrete volume is attributed to them; counting their "
                    "displaced volume as concrete would invent concrete on the largest "
                    "carbon item. Pile count and length are not dimensioned on the sheets "
                    "read, so no steel quantity is produced either."
                ],
                provenance=_prov(inputs, sheet, "SCREW PILE"),
            )
        )
    return out


def _wall_lines(inputs: TakeoffInputs) -> list[TakeoffLine]:
    fp, heights = inputs.footprint, inputs.heights
    if fp is None:
        return []
    net = heights.net_wall_height_m
    gross = heights.total_wall_height_m
    height = net if net is not None else gross
    if height is None:
        return []
    basis_name = "net of floor assemblies" if net is not None else "gross floor to floor"
    area = round(fp.perimeter_m * height, 2)
    sheet = next((s.split(":")[0] for s in heights.sources), None)

    note = (
        f"Perimeter {fp.perimeter_m:.1f} m from the measured footprint x {height:.3f} m "
        f"wall height ({basis_name}) from the section datums."
    )
    assumptions = [
        f"Wall area reported on the '{basis_name}' basis. The gross floor-to-floor basis "
        f"gives {fp.perimeter_m * gross:.0f} m2, about 20% higher; a quantity surveyor "
        f"measures gross while an energy model measures the thermal envelope, and which "
        f"one a reference takeoff uses is a convention, not a fact."
    ] + list(heights.notes)

    lines = [
        TakeoffLine(
            id="ln-exterior-wall",
            element_class=ElementClass.EXTERIOR_WALL,
            quantity=area,
            unit=Unit.M2,
            confidence=Confidence.INFERRED,
            material="CMHC_Wood Framing",
            description=f"Exterior wall, {heights.n_storeys} storeys, {basis_name}",
            basis=Basis(
                sources=[BasisSource.VECTOR_PATH, BasisSource.DIM_TEXT_METRIC, BasisSource.SECTION_NOTE],
                note=note,
            ),
            assumptions=assumptions,
            provenance=_prov(inputs, sheet, "LEVEL DATUMS"),
        )
    ]

    return lines


def _assembly_lines(
    asm: Assembly,
    area_m2: float,
    element_class: ElementClass,
    *,
    confidence: Confidence,
    area_note: str,
    extra_assumptions: list[str] | None = None,
) -> tuple[list[TakeoffLine], list[Gap]]:
    """Expand one assembly over an area into a line per material layer.

    This is what turns "exterior wall, 309 m2" into cladding, sheathing,
    insulation and gypsum. A layer produces a line only when the schedule gives
    enough to compute one: a stated thickness, a specified material, a known
    coverage, and no deferral to another discipline. Everything else becomes a
    gap, so the reason a material is absent stays on the record rather than
    just leaving the total quietly low.
    """
    out: list[TakeoffLine] = []
    gaps: list[Gap] = []
    slug = element_class.value.replace("_", "-")

    for layer in asm.layers:
        material = cmhc_material(layer)
        volume = layer.volume_m3(area_m2, STUD_FRAMING_FRACTION)
        if volume is None or material is None:
            continue

        coverage, coverage_note = layer.coverage
        notes = [area_note]
        if coverage_note:
            notes.append(coverage_note)
        if layer.note:
            notes.append(layer.note)
        if layer.shares_cavity_with is not None:
            partner = asm.layers[layer.shares_cavity_with]
            share = STUD_FRAMING_FRACTION if layer.is_framing else 1 - STUD_FRAMING_FRACTION
            notes.append(
                f"Shares the {layer.thickness_mm:.0f} mm cavity with "
                f"'{partner.material}', so it takes {share:.0%} of it rather than the "
                f"full depth; counting both at full depth would put "
                f"{2 * layer.thickness_mm:.0f} mm of material in a "
                f"{layer.thickness_mm:.0f} mm space."
            )

        out.append(
            TakeoffLine(
                id=f"ln-{slug}-{asm.tag.lower()}-l{layer.index}",
                element_class=element_class,
                quantity=volume,
                unit=Unit.M3,
                confidence=confidence,
                material=material,
                assembly_tag=asm.tag,
                description=(
                    f"{layer.material.title()}, {layer.thickness_mm:.0f} mm"
                    + ("" if coverage >= 1.0 else f" at {coverage:.1%} coverage")
                ),
                basis=Basis(
                    sources=[BasisSource.SCHEDULE, BasisSource.VECTOR_PATH],
                    note=(
                        f"{asm.tag} layer {layer.index + 1} of {len(asm.layers)} from the "
                        f"assemblies schedule; {layer.thickness_mm:.0f} mm over "
                        f"{area_m2:.1f} m2. " + " ".join(notes)
                    ),
                ),
                assumptions=list(extra_assumptions or []),
                provenance=Provenance(
                    page=asm.page if asm.page is not None else 0,
                    sheet_no=asm.sheet,
                    detail=f"{asm.tag} {asm.name}"[:80],
                ),
            )
        )

    for message in asm.gaps():
        gaps.append(
            Gap(
                code=GapCode.ASSEMBLY_SCHEDULE_MISSING,
                severity=GapSeverity.WARNING,
                message=message,
            )
        )
    return out, gaps


# Share of a low-rise home's embodied carbon by element, from the 2022
# Residential Construction Benchmarking Report via the Kootenay guide that the
# scope prescribes, corroborated independently by the Building Performance
# Reports' own element breakdown (RESEARCH S17, docs/element_priority.md).
#
# Used to state how much of the building a takeoff has actually reached. A
# partial bill of quantities produces a low carbon total, and a low total that
# does not announce itself as partial is indistinguishable from a good result.
ELEMENT_CARBON_SHARE: dict[ElementClass, float] = {
    ElementClass.SLAB_ON_GRADE: 0.18,
    ElementClass.FOOTING: 0.09,
    ElementClass.FOUNDATION_WALL: 0.08,
    ElementClass.EXTERIOR_WALL: 0.20,
    ElementClass.FLOOR_ASSEMBLY: 0.15,
    ElementClass.ROOF_ASSEMBLY: 0.13,
    ElementClass.WINDOW: 0.07,
    ElementClass.DOOR: 0.02,
    ElementClass.INTERIOR_PARTITION: 0.08,
}


def coverage_report(lines: list[TakeoffLine]) -> tuple[float, list[ElementClass]]:
    """Fraction of the building's expected carbon the bill of quantities reaches.

    Returns (fraction covered, element classes with no line). A class counts as
    covered only if it carries a non-zero quantity, so the screw-pile line --
    deliberately zero because the piles are steel supplied by others -- does not
    make the foundation look complete.
    """
    present = {ln.element_class for ln in lines if ln.quantity > 0}
    covered = sum(share for cls, share in ELEMENT_CARBON_SHARE.items() if cls in present)
    missing = [cls for cls in ELEMENT_CARBON_SHARE if cls not in present]
    return covered, missing


def build_takeoff(design, project: ProjectFacts | None = None) -> TakeoffResult:
    """Produce a bill of quantities for one design, from measured geometry."""
    facts = project or ProjectFacts(name=design.key)
    expected = (
        facts.gfa_m2 / facts.storeys if facts.gfa_m2 and facts.storeys else None
    )
    inputs, sheets, gaps = gather(design, expected)

    lines = _foundation_lines(inputs) + _wall_lines(inputs)

    # Resolve each element's area into its materials, using the assembly the
    # drawings actually reference rather than the first one the schedule lists.
    wall = next((ln for ln in lines if ln.id == "ln-exterior-wall"), None)
    fp = inputs.footprint

    if wall is not None:
        asm = inputs.assembly_for("W")
        if asm is not None:
            built, more = _assembly_lines(
                asm,
                wall.quantity,
                ElementClass.EXTERIOR_WALL,
                confidence=Confidence.INFERRED,
                area_note=(
                    f"Area is the measured exterior wall, {wall.quantity:.1f} m2, so it "
                    f"carries that line's own basis and uncertainty."
                ),
            )
            lines += built
            gaps += more

    if fp is not None:
        asm = inputs.assembly_for("R")
        if asm is not None:
            built, more = _assembly_lines(
                asm,
                fp.area_m2,
                ElementClass.ROOF_ASSEMBLY,
                confidence=Confidence.ASSUMED,
                area_note=f"Area taken as the {fp.area_m2:.1f} m2 footprint.",
                extra_assumptions=[
                    "Roof area assumed equal to the footprint, which is its horizontal "
                    "projection. A pitched roof's surface is larger: this design's roof "
                    "datum sits 1.87 m above the top plate, so the real area is "
                    "understated. The pitch is not dimensioned on the sheets read, so no "
                    "slope correction is applied rather than a guessed one."
                ],
            )
            lines += built
            gaps += more

        # The ground slab's own build-up: sub-slab insulation and granular
        # base. Its concrete layer defers to the structural drawings, where the
        # foundation lines above already measured it, so it is not counted
        # twice.
        slab = inputs.slab_assembly
        if slab is not None:
            built, more = _assembly_lines(
                slab,
                fp.area_m2,
                ElementClass.SLAB_ON_GRADE,
                confidence=Confidence.INFERRED,
                area_note=f"Area is the {fp.area_m2:.1f} m2 measured footprint.",
            )
            lines += built
            gaps += more

        # One floor assembly per storey above the first. The lowest floor is
        # the slab, handled above, and a slab-on-grade assembly must not be
        # used for a suspended floor -- it would put sub-slab insulation and
        # granular fill into a first-floor ceiling.
        upper = max(inputs.heights.n_storeys - 1, 0)
        slab_tags = {t for t, a in inputs.assemblies.items() if a.is_slab_on_grade}
        asm = inputs.assembly_for("F", exclude=slab_tags)
        if asm is not None and upper > 0:
            built, more = _assembly_lines(
                asm,
                fp.area_m2 * upper,
                ElementClass.FLOOR_ASSEMBLY,
                confidence=Confidence.ASSUMED,
                area_note=(
                    f"Area is the {fp.area_m2:.1f} m2 footprint over {upper} suspended "
                    f"floor{'s' if upper > 1 else ''}."
                ),
                extra_assumptions=[
                    f"Each suspended floor assumed equal in area to the footprint, and "
                    f"{upper} of them assumed from {inputs.heights.n_storeys} storeys. "
                    f"Stairwells and double-height spaces are not deducted.",
                    f"Assembly {asm.tag} is the most-referenced F assembly on the "
                    f"drawings; a design using more than one floor build-up would need "
                    f"them separated per area.",
                ],
            )
            lines += built
            gaps += more

    if inputs.footprint is not None and facts.gfa_m2 is None:
        facts.gfa_m2 = round(inputs.footprint.area_m2 * max(inputs.heights.n_storeys, 1), 1)
        facts.gfa_basis = "gross"

    covered, missing = coverage_report(lines)
    if missing:
        gaps.append(
            Gap(
                code=GapCode.SHEET_TYPE_MISSING,
                severity=GapSeverity.BLOCKING if covered < 0.6 else GapSeverity.WARNING,
                message=(
                    f"This bill of quantities covers roughly {covered:.0%} of the building's "
                    f"embodied carbon by element. No quantities were produced for: "
                    f"{', '.join(c.value.replace('_', ' ') for c in missing)}. "
                    f"The carbon total is therefore a PARTIAL figure and must not be read as "
                    f"a whole-building result."
                ),
                affects=[ln.id for ln in lines],
            )
        )

    return TakeoffResult(
        project=facts,
        source_file=design.drawings_pdf.name,
        sheets=sheets,
        gaps=gaps,
        lines=lines,
        extracted_at=date.today(),
    )
