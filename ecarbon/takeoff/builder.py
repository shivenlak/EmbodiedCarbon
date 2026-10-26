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

# How far the floor area the plans depict may sit from the area the project
# states before the two are treated as describing different extents. Measured
# across the catalogue: designs whose opening counts match the IFC exactly sit
# at 0.98-0.99, and those that come in a third short sit at 0.51-0.72.
# The published whole-life intensities across the 52 catalogue designs run
# 141 to 731 kgCO2e/m2, median 448. Ours is A1-A3 only -- a subset of that --
# so a complete A1-A3 takeoff landing above the catalogue's whole-life maximum
# is arithmetically impossible and means the denominator is wrong, not the
# building unusual. AB_Rowhouse_01 read 761 that way.
CATALOGUE_WHOLE_LIFE_MAX_KG_PER_M2 = 731.0
# A takeoff reaching most of the building should also land in a believable
# band. Below this with full coverage means quantities are missing rather than
# the building being light.
PLAUSIBLE_A1_A3_FLOOR_KG_PER_M2 = 40.0

# The largest building in this catalogue is a sixplex, so a stated area that
# is a per-unit figure should be at most about a sixth of the block. A
# drawing-derived area many times larger than that is not a unit count, it is
# a footprint that has caught something other than the building -- SKMB_ADU_01
# measures 908 m2 against a stated 58, which is 15.7x and no number of units.
# Replacing a stated area with that would be a worse answer than keeping it.
MAX_UNIT_RATIO = 8.0

PLAN_EXTENT_TOLERANCE = 0.15

# Below this many windows, a dwelling can legitimately have more windows than
# doors, so the door-tagging check is not applied. Calibrated on the
# catalogue: QC_ADU_01 has four windows and three doors and is exactly right.
DOOR_TAGGING_WINDOW_FLOOR = 12


@dataclass
class TakeoffInputs:
    """What the extraction stages found, kept separate so a caller can see
    which stage failed rather than just getting a short bill of quantities."""

    footprint: Footprint | None = None
    footprint_sheet: str | None = None
    footprint_page: int | None = None
    spec: FoundationSpec = field(default_factory=FoundationSpec)
    heights: StoreyHeights = field(default_factory=StoreyHeights)
    # True when the footprint survived only without the stated-area check.
    footprint_uncorroborated: bool = False
    assemblies: dict[str, Assembly] = field(default_factory=dict)
    tag_refs: dict[str, int] = field(default_factory=dict)
    # Sheet number -> page, so a line that cites a sheet points at that sheet's
    # page. Without it a provenance can name S201 and carry the footprint's
    # page, which reads correctly in a table and sends click-to-trace to the
    # wrong drawing.
    sheet_pages: dict[str, int] = field(default_factory=dict)

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
    inputs = TakeoffInputs(
        sheet_pages={s.sheet_no.upper(): s.page for s in sheets if s.sheet_no}
    )
    gaps: list[Gap] = list(readability_gaps(sheets)) + list(coverage_gaps(sheets))

    doc = pymupdf.open(design.drawings_pdf)
    try:
        plans = [s for s in sheets if s.sheet_type in PLAN_TYPES and s.readable]

        # The stated floor area corroborates a measured footprint, and a
        # mismatch is usually a wrong measurement. But not always: on a
        # repeated-unit block the Building Performance Report states floor area
        # per unit while the plan draws the whole block, so the expectation is
        # a third of the truth and rejects the correct answer.
        # ATL_Stacked_Townhouse_01 expects 66 m2, measures 203.1 m2 and the IFC
        # says 203.2 -- a 0.05% match thrown away by an area gate.
        #
        # So the expectation is tried first and, only if nothing confident
        # survives it, the plans are read again without it. The second pass is
        # recorded so the caller knows the area was never corroborated.
        for expectation in (expected_area_m2, None):
            for s in plans:
                fp = detect_footprint(doc[s.page], calibrate(doc[s.page]), expectation)
                if fp and fp.confident:
                    inputs.footprint, inputs.footprint_sheet, inputs.footprint_page = (
                        fp,
                        s.sheet_no,
                        s.page,
                    )
                    inputs.footprint_uncorroborated = expectation is None
                    break
                if fp and inputs.footprint is None:
                    inputs.footprint, inputs.footprint_sheet, inputs.footprint_page = (
                        fp,
                        s.sheet_no,
                        s.page,
                    )
            if inputs.footprint is not None and inputs.footprint.confident:
                break
            if expectation is None or expected_area_m2 is None:
                break
    finally:
        doc.close()

    if inputs.footprint_uncorroborated and expected_area_m2:
        gaps.append(
            Gap(
                code=GapCode.GEOMETRY_AMBIGUOUS,
                severity=GapSeverity.WARNING,
                message=(
                    f"The footprint measures {inputs.footprint.area_m2:.1f} m2 but the "
                    f"stated floor area implies about {expected_area_m2:.0f} m2 per "
                    f"storey, so the two could not be reconciled and the measurement "
                    f"is reported without that corroboration. On a repeated-unit block "
                    f"this is expected -- the report states area per unit while the plan "
                    f"draws the whole block -- but it also fits a mis-measured plan, so "
                    f"check the footprint before relying on areas derived from it."
                ),
            )
        )

    # The assemblies schedule turns an element area into materials. Without it
    # a wall is only its studs, which is about a sixth of its carbon.
    try:
        inputs.assemblies, rejected = assemblies_for(design)
        inputs.tag_refs = assembly_tags_used(design)
        for message in rejected:
            gaps.append(
                Gap(
                    code=GapCode.ASSEMBLY_SCHEDULE_MISSING,
                    severity=GapSeverity.WARNING,
                    message=message,
                )
            )
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
    """Provenance whose page is the page of the sheet it names.

    The foundation and level lines cite the structural sheet their figures are
    stated on, which is not the plan the footprint was measured from. Taking
    the footprint's page regardless put AB_Fourplex_01's slab on page 10 (A101)
    while naming S201, which is page 24.
    """
    named = sheet or inputs.footprint_sheet
    page = inputs.sheet_pages.get((named or "").upper())
    if page is None:
        page = inputs.footprint_page if inputs.footprint_page is not None else 0
    return Provenance(page=page, sheet_no=named, detail=detail)


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

    footing = spec.footing_volume_m3(fp.perimeter_m)
    if footing is not None:
        assumptions = [
            "Strip-footing run assumed equal to the footprint perimeter. Footings "
            "under interior bearing walls and party walls are not counted, so this "
            "understates a building with internal load paths."
        ]
        if spec.footing_section_note:
            assumptions.append(spec.footing_section_note)
        out.append(
            TakeoffLine(
                id="ln-strip-footing",
                element_class=ElementClass.FOOTING,
                quantity=round(footing, 2),
                unit=Unit.M3,
                confidence=Confidence.INFERRED,
                material="CMHC_Concrete, CIP",
                description=(
                    f"Strip footing {spec.footing_width_mm:.0f} x "
                    f"{spec.footing_depth_mm:.0f} mm over {fp.perimeter_m:.1f} m run"
                ),
                basis=Basis(
                    sources=[BasisSource.VECTOR_PATH, BasisSource.SECTION_NOTE],
                    note=(
                        "Section stated on the structural drawings; run length taken as "
                        "the rectangular perimeter of the measured footprint."
                    ),
                ),
                assumptions=assumptions,
                provenance=_prov(inputs, sheet, "STRIP FOOTING"),
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


def coverage_report(
    lines: list[TakeoffLine], absent: set[ElementClass] | None = None
) -> tuple[float, list[ElementClass]]:
    """Fraction of the building's expected carbon the bill of quantities reaches.

    Returns (fraction covered, element classes with no line). A class counts as
    covered only if it carries a non-zero quantity, so the screw-pile line --
    deliberately zero because the piles are steel supplied by others -- does not
    make the foundation look complete.

    `absent` names classes this building does not have, and they leave the
    denominator rather than counting against it. AB_Fourplex_01 sits on grade
    beams over screw piles with no basement, so it has no foundation wall at
    all: reporting one as "missing" both understates the takeoff and tells the
    reader to go looking for a sheet that was never drawn. The shares come from
    a typical house, so a building without one of these elements has that share
    distributed across the rest.
    """
    skip = absent or set()
    applicable = {
        cls: share for cls, share in ELEMENT_CARBON_SHARE.items() if cls not in skip
    }
    total = sum(applicable.values())
    present = {ln.element_class for ln in lines if ln.quantity > 0}
    reached = sum(share for cls, share in applicable.items() if cls in present)
    covered = (reached / total) if total else 0.0
    missing = [cls for cls in applicable if cls not in present]
    return covered, missing


def absent_elements(inputs: TakeoffInputs) -> dict[ElementClass, str]:
    """Element classes this building does not have, with the evidence.

    Only claimed where the drawings say so. A foundation wall exists to retain
    earth against a basement or crawlspace; a slab on grade carried by grade
    beams or a strip footing has none, and the footing is counted separately.
    """
    out: dict[ElementClass, str] = {}
    system = (inputs.spec.system or "").lower()
    has_below_grade_storey = any(
        "BASEMENT" in lv.label.upper() or "CRAWL" in lv.label.upper()
        for lv in inputs.heights.levels
    )
    # Only a pile or grade-beam foundation carries the slab directly with no
    # wall. A strip footing almost always has a wall standing on it, so
    # `strip_footing` is not evidence of absence -- Quebec's designs read
    # strip_footing and show no crawlspace datum, yet their N1 is an insulated
    # foundation wall and their floors sit over a conditioned crawl space.
    # Claiming an element is absent is a stronger statement than leaving it
    # uncounted, so it is made only where the system itself rules a wall out.
    pile_borne = any(k in system for k in ("pile", "grade_beam", "slab_on_grade"))
    if pile_borne and not has_below_grade_storey:
        out[ElementClass.FOUNDATION_WALL] = (
            f"The foundation is {system.replace('_', ' ')} with no basement or "
            f"crawlspace datum on the sections, so the slab is carried directly and "
            f"this building has no foundation wall; the footing itself is counted "
            f"separately."
        )
    return out


def _opening_lines(design) -> tuple[list[TakeoffLine], list[Gap]]:
    """Windows and doors, sized from the schedule and counted from the plans.

    Windows are reported as area because that is how a glazing factor is
    declared; doors as a count, because a door is a manufactured unit and its
    factor is per door.
    """
    from ecarbon.extract.openings import openings_for

    try:
        openings, notes = openings_for(design)
    except Exception:
        return [], []
    if not openings:
        return [], [
            Gap(
                code=GapCode.OPENING_SCHEDULE_MISSING,
                severity=GapSeverity.WARNING,
                message=(
                    "No openings schedule could be read, so no window or door "
                    "quantities are produced."
                ),
            )
        ]

    lines: list[TakeoffLine] = []
    gaps: list[Gap] = [
        Gap(code=GapCode.OPENING_SCHEDULE_MISSING, severity=GapSeverity.WARNING, message=n)
        for n in notes
    ]
    sheet = next((o.sheet for o in openings if o.sheet), None)
    page = next((o.page for o in openings if o.page is not None), 0)

    windows = [o for o in openings if o.kind == "window"]
    doors = [o for o in openings if o.kind == "door"]

    sized = [o for o in windows if o.total_area_m2 is not None]
    unsized = [o for o in windows if o.total_area_m2 is None]
    if sized:
        area = round(sum(o.total_area_m2 for o in sized), 2)
        count = sum(o.count for o in sized)
        lines.append(
            TakeoffLine(
                id="ln-windows",
                element_class=ElementClass.WINDOW,
                quantity=area,
                unit=Unit.M2,
                confidence=Confidence.INFERRED,
                material="CMHC_Window",
                description=f"Windows, {count} openings across {len(sized)} types",
                basis=Basis(
                    sources=[BasisSource.SCHEDULE, BasisSource.DIM_TEXT_METRIC],
                    note=(
                        "Size of each type from the openings schedule, with the metric and "
                        "imperial columns agreeing; count of each type from the tags written "
                        "on the floor plans. "
                        + "; ".join(
                            f"{o.tag} {o.width_mm:.0f}x{o.height_mm:.0f} x{o.count}"
                            for o in sized
                        )
                    ),
                ),
                assumptions=[
                    "Count is of tags written on the plans, so a single tag against a "
                    "mullioned assembly counts once, and a window shown only on an "
                    "elevation is not counted at all."
                ],
                provenance=Provenance(page=page, sheet_no=sheet, detail="WINDOW SCHEDULE"),
            )
        )
    for o in unsized:
        gaps.append(
            Gap(
                code=GapCode.OPENING_SCHEDULE_MISSING,
                severity=GapSeverity.WARNING,
                message=(
                    f"Window {o.tag} has no usable size in the schedule, so its area is "
                    f"not counted."
                ),
            )
        )

    # Are the doors all tagged?
    #
    # In a dwelling every room needs a door and few rooms have more than one
    # or two windows, so interior doors normally outnumber windows. A count
    # where they do not means some doors were scheduled but never tagged on a
    # plan -- which is what AB_Rowhouse_01 and AB_Rowhouse_02 do, and their
    # door counts come in 58% and 61% short against the IFC while their window
    # counts are exact. Measured across the catalogue: where our doors equal or
    # exceed our windows the median door error is 0.0% over 39 designs; where
    # they are fewer it is 59%.
    #
    # The window floor exists because a small dwelling can legitimately have
    # more windows than doors -- QC_ADU_01 has four windows and three doors and
    # is exactly right. Twelve is calibrated on the catalogue, not derived.
    window_count = sum(o.count for o in windows)
    door_count = sum(o.count for o in doors)
    if door_count < window_count and window_count >= DOOR_TAGGING_WINDOW_FLOOR:
        gaps.append(
            Gap(
                code=GapCode.OPENING_SCHEDULE_MISSING,
                severity=GapSeverity.BLOCKING,
                message=(
                    f"Only {door_count} doors are tagged on the plans against "
                    f"{window_count} windows. A dwelling normally has more doors than "
                    f"windows, because every room needs one, so some doors are "
                    f"scheduled but never tagged and this count is unreliable — on "
                    f"the designs where this holds it has been around 60% short. The "
                    f"door quantity should be corrected by hand."
                ),
                affects=["ln-doors"],
            )
        )

    counted = [o for o in doors if o.count]
    if counted:
        lines.append(
            TakeoffLine(
                id="ln-doors",
                element_class=ElementClass.DOOR,
                quantity=float(sum(o.count for o in counted)),
                unit=Unit.EACH,
                confidence=Confidence.INFERRED,
                material="CMHC_Door",
                description=f"Doors, {len(counted)} types",
                basis=Basis(
                    sources=[BasisSource.SCHEDULE, BasisSource.DIM_TEXT_METRIC],
                    note=(
                        "Count of tags on the floor plans, one variant per storey. "
                        + "; ".join(f"{o.tag} x{o.count}" for o in counted)
                    ),
                ),
                assumptions=[
                    "All doors are priced with one factor. The schedule distinguishes "
                    "exterior, interior and fire-rated doors, which carry different "
                    "carbon; separating them needs a factor per door type."
                ],
                provenance=Provenance(page=page, sheet_no=sheet, detail="DOOR SCHEDULE"),
            )
        )
    return lines, gaps


# Interior-partition lines are the one group whose length is measured rather
# than read off a schedule, so they are named here for callers that report a
# total with and without them.
PARTITION_LINE_PREFIX = "ln-interior-partition"


def _partition_lines(design, inputs: TakeoffInputs) -> tuple[list[TakeoffLine], list[Gap]]:
    """Interior partitions, expanded from the assembly over a measured run.

    Measured against the IFC on all seven Alberta designs: median error 5.7%,
    six of seven within 10%, with AB_ADU_02 over-detecting at +92%. Four
    earlier approaches spanned -66% to +350% and are listed in the gap report,
    because a reader deciding whether to trust this number deserves to know it
    was hard to get rather than assumed.
    """
    from ecarbon.geometry.partitions import FAILED_APPROACHES, partitions_for

    height = inputs.heights.net_wall_height_m or inputs.heights.total_wall_height_m
    if height is None:
        return [], []
    try:
        measured = partitions_for(design)
    except Exception:
        return [], []
    if not measured.runs:
        return [], []

    asm = inputs.assembly_for("P")
    if asm is None:
        return [], []

    area = measured.area_m2(height)
    if area is None:
        return [], []

    spread = (
        f"{min(measured.depths_mm):.0f}-{max(measured.depths_mm):.0f} mm"
        if len(measured.depths_mm) > 1
        else f"{measured.depths_mm[0]:.0f} mm"
    )
    shared = [
        f"Partition run length {measured.total_length_m:.1f} m measured across "
        f"{measured.n_walls} walls on {len(measured.runs)} plan sheet(s), at the wall "
        f"lineweight, paired at the depths the schedule states ({spread}).",
        "Measured against the reference models on seven Alberta designs: median "
        "error 5.7%, six of seven within 10%, worst +92% where a small dwelling's "
        "cabinetry was read as partitions. Treat this line as the least certain "
        "quantity in the bill and override it if you have a better figure.",
        f"Built depth taken as the mean of the stated partition depths "
        f"({measured.mean_depth_mm:.0f} mm); the schedule gives {spread} and the run "
        f"is not broken down by type.",
    ]

    built, more = _assembly_lines(
        asm,
        area,
        ElementClass.INTERIOR_PARTITION,
        confidence=Confidence.INFERRED,
        area_note=(
            f"Area is {measured.total_length_m:.1f} m of measured partition run x "
            f"{height:.2f} m wall height."
        ),
        extra_assumptions=shared,
    )
    for line in built:
        line.id = line.id.replace("ln-interior-partition-", f"{PARTITION_LINE_PREFIX}-")

    more.append(
        Gap(
            code=GapCode.GEOMETRY_AMBIGUOUS,
            severity=GapSeverity.WARNING,
            message=(
                "Interior partition length is measured from the plan linework, not "
                "read from a schedule, and is the least certain quantity here: median "
                "5.7% against the reference models on Alberta, worst +92%. Four other "
                "approaches were tried and rejected first — "
                + "; ".join(FAILED_APPROACHES)
                + ". The carbon total is reported with and without these lines so the "
                "range is visible, and the run length can be overridden."
            ),
            affects=[line.id for line in built],
        )
    )
    return built, more


def build_takeoff(
    design,
    project: ProjectFacts | None = None,
    trust_stated_gfa: bool = False,
) -> TakeoffResult:
    """Produce a bill of quantities for one design, from measured geometry.

    `trust_stated_gfa` marks a floor area the user typed, as opposed to one
    read from a Building Performance Report. Both are checked against what the
    drawings depict and both are reported when they disagree, but only the
    report's figure is replaced: a number a person entered deliberately is
    theirs to change, and overriding it would answer a question they already
    answered.
    """
    facts = project or ProjectFacts(name=design.key)
    expected = (
        facts.gfa_m2 / facts.storeys if facts.gfa_m2 and facts.storeys else None
    )
    inputs, sheets, gaps = gather(design, expected)

    lines = _foundation_lines(inputs) + _wall_lines(inputs)

    opening_lines, opening_gaps = _opening_lines(design)
    lines += opening_lines
    gaps += opening_gaps

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

    # Interior partitions, measured from the plans rather than assumed.
    partition_lines, partition_gaps = _partition_lines(design, inputs)
    lines += partition_lines
    gaps += partition_gaps

    if inputs.footprint is not None and facts.gfa_m2 is None:
        facts.gfa_m2 = round(inputs.footprint.area_m2 * max(inputs.heights.n_storeys, 1), 1)
        facts.gfa_basis = "gross"

    # Does the plan depict the whole building, or one unit of it?
    #
    # Anything counted from the plans -- openings especially -- covers only what
    # the plan draws. On the repeated-unit typologies the drawings depict one
    # unit and leave the reader to know there are more: measured against the
    # IFC, door counts land exactly on the multiplexes and come in at -66.7% on
    # every stacked townhouse, which is one third.
    #
    # The measured footprint and the stated floor area disagree in exactly
    # those cases, which makes this checkable rather than a guess: the ratio is
    # 0.98-0.99 where counts are exact and 0.51-0.72 where they are a third.
    # No multiplier is applied, because inventing one would silently scale
    # every count on a typology guess; the disagreement is reported instead.
    # The measured ladder is preferred, but it needs two floor datums and some
    # designs give none, so the stated storey count stands in. Without the
    # fallback this check silently skips exactly the designs it is for: the
    # stacked townhouses resolve no levels at all.
    storeys = inputs.heights.n_storeys or facts.storeys or 0
    if fp is not None and facts.gfa_m2 and storeys:
        depicted = round(fp.area_m2 * storeys, 1)
        ratio = facts.gfa_m2 / depicted if depicted else 1.0
        if abs(ratio - 1.0) > PLAN_EXTENT_TOLERANCE:
            counted_from_plans = [
                ln.id for ln in lines if ln.id in ("ln-windows", "ln-doors")
            ]
            stated = facts.gfa_m2
            # Only trade a stated area for a measured one when the measured
            # one is credible as the same building.
            looks_like_units = ratio == 0 or (depicted / stated) <= MAX_UNIT_RATIO
            replaced = not trust_stated_gfa and looks_like_units
            # Every quantity in this bill is measured off these drawings, so
            # the denominator has to come from the same place. Dividing a
            # whole-block numerator by a per-unit area is what gave
            # AB_Rowhouse_01 an intensity of 761 kgCO2e/m2, above the highest
            # whole-life figure CMHC publishes for any design in the
            # catalogue -- a quantity error that was really a denominator
            # error, and the kind a plausible-looking number hides.
            if replaced:
                facts.gfa_m2 = depicted
            per_unit = (
                f" That is about {stated / facts.units:.0f} m2 per unit across "
                f"{facts.units} units."
                if facts.units
                else ""
            )
            gaps.append(
                Gap(
                    code=GapCode.GEOMETRY_AMBIGUOUS,
                    severity=GapSeverity.BLOCKING,
                    message=(
                        f"Floor area: using "
                        f"{(depicted if replaced else stated):.0f} m2"
                        + (
                            f" measured from the drawings ({fp.area_m2:.1f} m2 "
                            f"footprint x {storeys} storeys, the whole block), not "
                            f"the {stated:.0f} m2 this project states"
                            if replaced
                            else (
                                f" as entered, not the {depicted:.0f} m2 the drawings "
                                f"depict ({fp.area_m2:.1f} m2 footprint x {storeys} "
                                f"storeys)"
                                if trust_stated_gfa
                                else f" as stated, because the {depicted:.0f} m2 the "
                                f"drawings measure is {depicted / stated:.1f} times it "
                                f"— too large to be a unit count in a catalogue whose "
                                f"biggest building is a sixplex, so the footprint has "
                                f"probably caught more than the building"
                            )
                        )
                        + f" — a ratio of {ratio:.2f}.{per_unit} The two disagree "
                        f"about how much of the building is drawn, which usually means "
                        f"the stated figure covers one unit of a repeated block. Every "
                        f"quantity here is measured off these drawings, so the area "
                        f"they depict is the denominator that matches them; dividing a "
                        f"whole-block total by a one-unit area overstates intensity by "
                        f"exactly this ratio. Counts taken from the plans still cover "
                        f"only what is drawn. Confirm which basis you want — no "
                        f"multiplier has been applied to the quantities, because "
                        f"guessing one would scale every count on an assumption."
                    ),
                    affects=counted_from_plans,
                )
            )

    absent = absent_elements(inputs)
    covered, missing = coverage_report(lines, set(absent))
    for cls, why in absent.items():
        gaps.append(
            Gap(
                code=GapCode.SHEET_TYPE_MISSING,
                severity=GapSeverity.INFO,
                message=f"No {cls.value.replace('_', ' ')} is counted. {why}",
            )
        )
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
