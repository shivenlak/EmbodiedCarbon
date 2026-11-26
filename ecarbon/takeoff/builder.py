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

import math
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pymupdf

from ecarbon.extract.assemblies import (
    STEEL_RE,
    Assembly,
    assemblies_for,
    assembly_tags_used,
    cmhc_material,
    dominant_tag,
)
from ecarbon.extract.levels import (
    LadderFooting,
    Level,
    StoreyHeights,
    footing_on_ladder,
    storey_heights_for,
)
from ecarbon.extract.specs import FoundationSpec, foundation_spec_for
from ecarbon.geometry.footprint import REFUSE_PCT, Footprint, detect_footprint
from ecarbon.geometry.scale import ScaleEstimate, ScaleSource, calibrate
from ecarbon.intake import coverage_gaps, inventory, readability_gaps
from ecarbon.intake.classify import discipline_of, sheet_type_of
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
from ecarbon.takeoff.framing import (
    framing_lines,
    mark_assumed_heights,
    no_datum_single_storey,
    single_storey_fallback,
    standard_assembly_lines,
    standard_code,
)
from ecarbon.takeoff.overrides import (
    _FROM_FOOTPRINT,
    _FROM_HEIGHTS,
    StatedFootprint,
    StatedStoreyHeights,
    footprint_from_polygon,
    label_stated,
)
from ecarbon.vision import Reading, Task, provider_from_env, read_page
from ecarbon.vision.cache import max_classify_pages, max_pages
from ecarbon.vision.validate import RASTER_NOTE

PLAN_TYPES = (SheetType.FLOOR_PLAN, SheetType.FOUNDATION_PLAN)


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
# measured 908 m2 against a stated 58 before the footprint reader separated
# drawings, which is 15.7x and no number of units.
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
    # Top of footing measured off a datum ladder that prints no elevation for it.
    ladder_footing: LadderFooting | None = None
    # The same, counted on floor plans only: how the partition run is split by type.
    plan_tag_refs: dict[str, int] = field(default_factory=dict)
    # Sheet number -> page, so a line that cites a sheet points at that sheet's
    # page. Without it a provenance can name S201 and carry the footprint's
    # page, which reads correctly in a table and sends click-to-trace to the
    # wrong drawing.
    sheet_pages: dict[str, int] = field(default_factory=dict)
    # What vision read (contract C3), and which model; empty when it did not run.
    vision: list[Reading] = field(default_factory=list)
    vision_levels: list[Reading] = field(default_factory=list)
    vision_levels_page: int | None = None
    vision_by: str | None = None
    vision_sheets: int = 0
    # A4 cross-check: vision agreeing with a rules footprint, for the line notes.
    vision_check: str | None = None
    # Sheet types vision read from title blocks the rules could not (page ->
    # (sheet no, type)); typed by the same title rules as the text reader.
    vision_types: dict | None = None
    # Where the set was drawn (intake.locale, contract C1); None when unsure.
    locale: object | None = None

    def assembly_for(self, letter: str, exclude: set[str] | None = None) -> Assembly | None:
        """The assembly of one group that this design actually uses."""
        tag = dominant_tag(self.tag_refs, letter, set(self.assemblies), exclude)
        # The group's most-referenced tag was refused: a minor assembly must not
        # stand in for it (ATL_Fourplex_01 would price its R2a roof as the R4 deck).
        top = dominant_tag(self.tag_refs, letter, set(self.tag_refs), exclude)
        if tag and self.tag_refs[top] > self.tag_refs[tag] and top not in self.assemblies:
            return None
        return self.assemblies.get(tag) if tag else None

    @property
    def slab_assembly(self) -> Assembly | None:
        """The F assembly that is the ground slab, if the schedule has one."""
        slabs = {t: a for t, a in self.assemblies.items() if a.is_slab_on_grade}
        tag = dominant_tag(self.tag_refs, "F", set(slabs))
        if tag:
            return slabs.get(tag)
        # The plans never tag the slab (Atlantic's F1 "SLAB ON GRADE" is in the
        # schedule but not called out): the schedule's own slab-on-grade
        # assembly is still the slab, when it is the only one.
        return next(iter(slabs.values())) if len(slabs) == 1 else None


def _roof_area_note(levels) -> str:
    """The roof-area assumption, with this design's own ridge height when known."""
    rise = None
    if levels is not None and levels.roof_level_m is not None and levels.floors:
        hs = levels.storey_heights_m()
        if hs:
            r = levels.roof_level_m - levels.floors[0].elevation_m - sum(hs)
            rise = r if 0.3 <= r <= 6.0 else None
    where = (
        f"this design's roof datum sits {rise:.2f} m above the top plate"
        if rise is not None
        else "the sections read give no roof datum above the top plate"
    )
    return (
        "Roof area assumed equal to the footprint, which is its horizontal "
        f"projection. A pitched roof's surface is larger: {where}, so the real "
        "area is understated. The pitch is not dimensioned on the sheets read, so "
        "no slope correction is applied rather than a guessed one."
    )


def gather(
    design, expected_area_m2: float | None = None, overrides=None
) -> tuple[TakeoffInputs, list, list[Gap]]:
    """Run the extraction stages for one design.

    `overrides` (`takeoff.overrides.Overrides`, contract C2) carries what the
    user stated where the drawings could not be read: a scale per page, a
    traced footprint, storey heights. None means extraction alone.
    """
    sheets, _, _ = inventory(design.drawings_pdf, with_scale=True)
    inputs = TakeoffInputs(
        sheet_pages={s.sheet_no.upper(): s.page for s in sheets if s.sheet_no}
    )
    gaps: list[Gap] = list(readability_gaps(sheets)) + list(coverage_gaps(sheets))

    doc = pymupdf.open(design.drawings_pdf)
    try:
        plans = [s for s in sheets if s.sheet_type in PLAN_TYPES and s.readable]

        # C2 hook (scale): a page the user set a scale on is read as a plan
        # even when classification missed it, and with the user's scale.
        stated_scale = dict(overrides.scale_mm_per_pt) if overrides else {}
        if stated_scale:
            by_page = {s.page: s for s in sheets}
            plans = [by_page[p] for p in stated_scale if p in by_page] + [
                s for s in plans if s.page not in stated_scale
            ]

        def scale_for(page_no: int):
            if page_no in stated_scale:
                return ScaleEstimate(
                    mm_per_pt=stated_scale[page_no],
                    source=ScaleSource.NONE,
                    note="stated by the user from a dimension they read",
                )
            return calibrate(doc[page_no])

        # C2 hook (footprint): a traced outline replaces detection outright.
        if overrides is not None and overrides.footprint is not None:
            fp_page, corners = overrides.footprint
            mm_per_pt = stated_scale.get(fp_page) or calibrate(doc[fp_page]).mm_per_pt
            if mm_per_pt:
                by_page = {s.page: s for s in sheets}
                inputs.footprint = footprint_from_polygon(corners, mm_per_pt)
                inputs.footprint_page = fp_page
                inputs.footprint_sheet = getattr(by_page.get(fp_page), "sheet_no", None)
                plans = []
            else:
                gaps.append(
                    Gap(
                        code=GapCode.SCALE_NOT_FOUND,
                        severity=GapSeverity.BLOCKING,
                        message=(
                            f"The outline traced on page {fp_page + 1} cannot be measured "
                            f"until that page has a scale. Set the scale from a dimension "
                            f"you can read on it first."
                        ),
                    )
                )

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
        refused: list[str] = []
        for expectation in (expected_area_m2, None):
            for s in plans:
                fp = detect_footprint(doc[s.page], scale_for(s.page), expectation)
                if fp and (fp.agreement_pct or 0.0) > REFUSE_PCT:
                    refused.append(f"{s.sheet_no or f'p{s.page + 1}'}: {fp.width_m} x {fp.depth_m} m, {fp.agreement_pct:.0f}% from its dimensions")
                    fp = None
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

        if refused and inputs.footprint is None:
            gaps.append(
                Gap(
                    code=GapCode.GEOMETRY_AMBIGUOUS,
                    severity=GapSeverity.WARNING,
                    message=(
                        "An outline was found but its own dimension strings contradict it, "
                        "so it is not used as the footprint: "
                        + "; ".join(dict.fromkeys(refused))
                        + ". Trace the outline or set the footprint to measure it."
                    ),
                )
            )

        # A4: vision only where the rules found no footprint at all. Raster
        # sheets are tried too, since those are where the rules cannot read.
        provider = provider_from_env() if inputs.footprint is None else None
        if provider is not None:
            inputs.vision_by = f"{provider.name} ({provider.model})"
            for s in _vision_candidates(provider, doc, sheets, inputs, PLAN_TYPES)[: max_pages()]:
                inputs.vision_sheets += 1
                got = {r.field: r for r in read_page(provider, doc[s.page], s.sheet_no, Task.FOOTPRINT)}
                if "width" in got and "depth" in got:
                    w, d = got["width"], got["depth"]
                    inputs.footprint = Footprint(
                        width_m=round(w.value / 1000.0, 3),
                        depth_m=round(d.value / 1000.0, 3),
                        basis=[w.note, d.note],
                    )
                    inputs.footprint_sheet, inputs.footprint_page = s.sheet_no, s.page
                    inputs.vision = [w, d]
                    break

        # A4 cross-check: a rules footprint nothing corroborated gets one vision
        # read of its own sheet. The rules value stays; vision only agrees or not.
        weak = inputs.footprint is not None and not inputs.vision and (
            not inputs.footprint.confident or inputs.footprint_uncorroborated
        )
        check = provider_from_env() if weak and inputs.footprint_page is not None else None
        if check is not None:
            inputs.vision_sheets += 1
            page = doc[inputs.footprint_page]
            got = {r.field: r for r in read_page(check, page, inputs.footprint_sheet, Task.FOOTPRINT)}
            if "width" in got and "depth" in got:
                said = cross_check_footprint(
                    inputs.footprint, got["width"], got["depth"], f"{check.name} ({check.model})"
                )
                if isinstance(said, Gap):
                    gaps.append(said)
                else:
                    inputs.vision_check = said
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
        inputs.plan_tag_refs = assembly_tags_used(design, plans_only=True)
        for tag, asm in inputs.assemblies.items():
            if asm.from_legend:  # no tag on the plans to count; the legend is the reference
                inputs.tag_refs.setdefault(tag, 1)
        # BC plans tag the family ("W1", 21 times) while the schedule defines
        # only its variants (W1.1-W1.3, one per energy step). The family's
        # references go to its first variant, and the choice is said.
        for refs in (inputs.tag_refs, inputs.plan_tag_refs):
            for fam in list(refs):
                variants = sorted(t for t in inputs.assemblies if t.startswith(fam + "."))
                if fam in inputs.assemblies or not variants:
                    continue
                refs[variants[0]] = refs.get(variants[0], 0) + refs.pop(fam)
                if refs is inputs.tag_refs:
                    rejected.append(
                        f"The plans tag {fam} but the schedule defines only its variants "
                        f"({', '.join(variants)}); {variants[0]}, the first, is used for it. "
                        f"Choose another if the project builds a different variant."
                    )
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
    if inputs.spec.strip_footings and inputs.spec.foundation_wall_height_mm is None:
        try:
            lf = footing_on_ladder(design)
        except Exception:  # a refinement only; the frost-depth estimate stands
            lf = None
        # The same range a stated wall height must fall in; BC's 0.6 m crawlspace
        # footing stays on the frost-depth estimate.
        if lf and 1.5 <= -lf.elevation_m <= 3.6:
            inputs.ladder_footing = lf
            inputs.spec.foundation_wall_height_mm = round(-lf.elevation_m * 1000)
            inputs.spec.sources.append(
                f"{lf.sheet_no}: T/O FOOTING drawn at {lf.elevation_m:.2f} m on the datum ladder"
            )
    # The floor assembly depth is what separates a gross wall height from a
    # thermal one; without it only the gross basis is available.
    inputs.heights = storey_heights_for(design, floor_assembly_mm=333.0)
    # One storey, floor and ridge only: the wall height is an assumed standard.
    single = single_storey_fallback(inputs.heights)
    if single is not None:
        inputs.heights = single
    # C2 hook (heights): what the user typed replaces the section datums.
    if overrides is not None and overrides.storey_heights_m:
        inputs.heights = StatedStoreyHeights(overrides.storey_heights_m, floor_assembly_mm=333.0)
    elif not inputs.heights.storey_heights_m():
        _vision_levels(design, sheets, inputs)
    # No level on any section and one floor plan: one storey, height assumed.
    if not inputs.heights.storey_heights_m():
        nodatum = no_datum_single_storey(inputs.heights, sheets, inputs.footprint)
        if nodatum is not None:
            inputs.heights = nodatum

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
    shape = _shape_gap(design, inputs)
    if shape is not None:
        gaps.append(shape)
    return inputs, sheets, gaps


# A US set states its conditioned area: "909 SQ. FT." in a plan title, "Plan - 909 s.f.",
# "PLAN 1 484 SF CONDITIONED", "CONDITIONED PLAN 2 FLOOR 637 SF". Attic vent and
# porch areas ("235 SF", "UNCONDITIONED PORCH 85 SF") are not matched.
_AREA_N = r"(?<![\d,.])(\d{1,2},\d{3}|\d{3,5})"
_STATED_AREA = re.compile(
    _AREA_N + r"\s*(?:SQ\.\s*FT\.|S\.F\.|SF\s+CONDITIONED)|CONDITIONED\b.{0,30}?" + _AREA_N + r"\s*SF\b",
    re.I,
)


def stated_area_sf(texts) -> float | None:
    """The one floor area a set states in square feet, or None if none or several."""
    found = {
        float(n.replace(",", ""))
        for t in texts
        if "UNCONDITIONED" not in t.upper()
        for m in _STATED_AREA.finditer(t)
        for n in m.groups()
        if n
    }
    return found.pop() if len(found) == 1 else None


def _shape_gap(design, inputs: TakeoffInputs) -> Gap | None:
    """Warn when the stated area says the building is not its bounding rectangle.

    The footprint is the overall width by depth, so an L or a notched porch is
    priced as the full rectangle. Single storey only: on a taller building the
    stated area may be the sum of its floors.
    """
    fp = inputs.footprint
    if fp is None or isinstance(fp, StatedFootprint) or inputs.heights.n_storeys != 1:
        return None
    doc = pymupdf.open(design.drawings_pdf)
    try:
        texts = [" ".join(b[4].split()) for page in doc for b in page.get_text("blocks")]
    finally:
        doc.close()
    sf = stated_area_sf(texts)
    if sf is None:
        return None
    stated, drawn = sf * 0.09290304, fp.area_m2
    if abs(drawn - stated) / stated <= 0.10:
        return None
    return Gap(
        code=GapCode.GEOMETRY_AMBIGUOUS,
        severity=GapSeverity.WARNING,
        message=(
            f"The drawings state {sf:,.0f} sq ft ({stated:.1f} m2), but the footprint's overall "
            f"extents, {fp.width_m:.2f} x {fp.depth_m:.2f} m, enclose {drawn:.1f} m2. The plan "
            "is probably not a rectangle (an L, a notch, a porch), and quantities from the "
            "footprint use the full extents. Trace the outline to measure it as drawn."
        ),
    )


def _footprint_where(inputs: TakeoffInputs) -> str:
    """The footprint's sheet number, or its page on an unnumbered sheet ("p11")."""
    return inputs.footprint_sheet or f"p{(inputs.footprint_page or 0) + 1}"


_VISION_WANTED = (*PLAN_TYPES, SheetType.SECTION, SheetType.ELEVATION)


def _listed_pages(drawings_pdf: str) -> dict[int, int]:
    """Pages to classify first (page -> rank), from the set's own List of Drawings.

    Only an order: vision still reads each title block, so a wrong hint costs
    a call, never a wrong type. CMHC sets list sheet i on page i + 1 (an
    unlisted cover comes first) until an unlisted sheet shifts the rest.
    shortcut: +1, then +0; read the offset off the first title if another publisher differs.
    """
    from ecarbon.bench.sheet_truth import parse_list_of_drawings

    lists = sorted(Path(drawings_pdf).parent.rglob("*List of Drawings*.pdf")) if drawings_pdf else []
    if not lists:
        return {}
    try:
        listed = parse_list_of_drawings(lists[0])
    except Exception:  # a hint only; an unreadable list changes nothing
        return {}
    wanted = [i for i, t in enumerate(listed) if t.sheet_type in _VISION_WANTED]
    pages = [i + 1 for i in wanted] + [i for i in wanted]
    return {p: rank for rank, p in enumerate(dict.fromkeys(pages))}


def _vision_candidates(provider, doc, sheets, inputs: TakeoffInputs, types) -> list:
    """Sheets of `types` for vision to read.

    The rules' own classification first. Where it typed none of them (an
    image-only set, or a title block it cannot parse), vision reads each
    unclassified page's title block (Task.SHEET, validated like any answer)
    and the title is typed by the same rules as text. The sheets returned
    carry that sheet number and type; the inventory itself is unchanged.
    """
    ruled = [s for s in sheets if s.sheet_type in types]
    if ruled:
        return ruled
    if inputs.vision_types is None:
        inputs.vision_types = {}
        unknown = [s for s in sheets if s.sheet_type is SheetType.UNKNOWN]
        hint = _listed_pages(doc.name)
        unknown.sort(key=lambda s: hint.get(s.page, len(hint)))
        for s in unknown[: max_classify_pages()]:
            got = {r.field: r for r in read_page(provider, doc[s.page], s.sheet_no, Task.SHEET)}
            if "title" not in got:
                continue
            no = got["sheet_no"].value if "sheet_no" in got else s.sheet_no
            stype = sheet_type_of(str(got["title"].value), discipline_of(no))
            if stype is not SheetType.UNKNOWN:
                inputs.vision_types[s.page] = (no, stype)
    by_page = {s.page: s for s in sheets}
    return [
        by_page[p].model_copy(update={"sheet_no": no, "sheet_type": t})
        for p, (no, t) in sorted(inputs.vision_types.items())
        if t in types
    ]


CROSS_CHECK_PCT = 2.0


def cross_check_footprint(fp: Footprint, w: Reading, d: Reading, by: str) -> str | Gap:
    """Compare the rules footprint with a vision read of the same sheet.

    Agreement comes back as a phrase for the line notes; disagreement as a
    WARNING naming both, never silently resolved. Orientation is ignored, since a
    plan's width and depth are only which string the reader took first.
    """
    rules = sorted((fp.width_m, fp.depth_m))
    seen = sorted((w.value / 1000.0, d.value / 1000.0))
    off = max(abs(a - b) / a * 100.0 for a, b in zip(rules, seen, strict=True))
    said = f"{seen[0]:.2f} x {seen[1]:.2f} m ({w.quote} x {d.quote})"
    if off <= CROSS_CHECK_PCT:
        return f"The overall extents agree with {by} reading the dimension strings: {said}."
    return Gap(
        code=GapCode.GEOMETRY_AMBIGUOUS,
        severity=GapSeverity.WARNING,
        message=(
            f"The footprint measured from the linework, {rules[0]:.2f} x {rules[1]:.2f} m, "
            f"disagrees by {off:.0f}% with {by} reading the dimension strings on the same "
            f"sheet: {said}. The measured value is used; check which is right."
        ),
    )


def _vision_levels(design, sheets, inputs: TakeoffInputs) -> None:
    """A4: vision for the level datums, only where the sections gave no height."""
    provider = provider_from_env()
    budget = max_pages() - inputs.vision_sheets
    if provider is None or budget <= 0:
        return
    inputs.vision_by = f"{provider.name} ({provider.model})"
    doc = pymupdf.open(design.drawings_pdf)
    try:
        wanted = (SheetType.SECTION, SheetType.ELEVATION)
        found_sheets = _vision_candidates(provider, doc, sheets, inputs, wanted)
        # Sections first: their datums are the drawn ones; elevations repeat them.
        found_sheets.sort(key=lambda s: s.sheet_type is not SheetType.SECTION)
        for s in found_sheets[:budget]:
            inputs.vision_sheets += 1
            # one section sheet repeats its datums in every cut; one reading each
            got = list({r.note: r for r in read_page(provider, doc[s.page], s.sheet_no, Task.LEVELS)}.values())
            found = StoreyHeights(
                levels=[Level(r.field, r.value, s.sheet_no) for r in got],
                floor_assembly_mm=inputs.heights.floor_assembly_mm,
                sources=[r.note for r in got],
            )
            if found.storey_heights_m():
                inputs.heights, inputs.vision_levels = found, got
                inputs.vision_levels_page = s.page
                return
    finally:
        doc.close()


def _vision_check_phrase(readings) -> str:
    """How far a vision reading was checked: in the text, or only an image."""
    if any(RASTER_NOTE in r.note for r in readings):
        return (
            "the sheet has no usable text layer, so the quotes were read from an image of it "
            "and could not be checked against the drawing's text."
        )
    return "each quote was located in the drawing's text."


def mark_units(lines: list[TakeoffLine], locale) -> list[Gap]:
    """A2: on a set drawn in feet and inches, the dimension text each line
    rests on was imperial, not metric. Mixed (CMHC) and unknown sets keep
    their sources exactly as they were."""
    if locale.unit_system != "imperial":
        return []
    for line in lines:
        line.basis.sources = [
            BasisSource.DIM_TEXT_IMPERIAL if s is BasisSource.DIM_TEXT_METRIC else s
            for s in line.basis.sources
        ]
    # models.py is frozen, so there is no units code; this is the nearest.
    return [
        Gap(
            code=GapCode.GEOMETRY_AMBIGUOUS,
            severity=GapSeverity.INFO,
            message=(
                "Drawn in feet and inches; quantities converted to SI. "
                + "; ".join(e for e in locale.evidence if e.startswith("units"))
            ),
        )
    ]


def label_vision(lines: list[TakeoffLine], inputs: TakeoffInputs) -> None:
    """Mark every line resting on a vision-read value, in place (C3).

    A line on a vision footprint was written as if the footprint were
    measured off the linework; it was not, so that claim is replaced. A line
    on vision-read heights keeps its own note behind the vision quotes.
    """
    for line in lines:
        if inputs.vision_check and line.element_class in _FROM_FOOTPRINT and line.quantity:
            note = f"{line.basis.note} {inputs.vision_check}".strip()
            line.basis = line.basis.model_copy(update={"note": note})
        fp = bool(inputs.vision) and line.element_class in _FROM_FOOTPRINT
        lv = bool(inputs.vision_levels) and line.element_class in _FROM_HEIGHTS
        if not (fp or lv) or line.quantity == 0:
            continue
        note, sources, agreement = line.basis.note, list(line.basis.sources), line.basis.agreement
        assumptions, bbox = list(line.assumptions), line.provenance.bbox
        if fp:
            imperial = "'" in inputs.vision[0].quote
            sources = [BasisSource.DIM_TEXT_IMPERIAL if imperial else BasisSource.DIM_TEXT_METRIC]
            agreement = None
            note = (
                "; ".join(r.note for r in inputs.vision)
                + f". Footprint {inputs.footprint.width_m:.2f} x {inputs.footprint.depth_m:.2f} m "
                "from the overall dimension strings; the linework did not confirm it."
            )
            assumptions.append(
                f"Footprint read by {inputs.vision_by} from the overall dimensions on "
                f"{_footprint_where(inputs)}; "
                + _vision_check_phrase(inputs.vision)
            )
            if line.provenance.page == inputs.footprint_page:
                bbox = inputs.vision[0].bbox
        if lv:
            if BasisSource.SECTION_NOTE not in sources:
                sources.append(BasisSource.SECTION_NOTE)
            heights = ", ".join(f"{h:.2f}" for h in inputs.heights.storey_heights_m())
            note = (
                "; ".join(r.note for r in inputs.vision_levels)
                + f". Storey heights {heights} m from these datums. {note}"
            ).strip()
            assumptions.append(
                f"Level datums read by {inputs.vision_by}; "
                + _vision_check_phrase(inputs.vision_levels)
            )
            if bbox is None and line.provenance.page == inputs.vision_levels_page:
                bbox = inputs.vision_levels[0].bbox
        line.basis = line.basis.model_copy(
            update={"sources": sources, "agreement": agreement, "note": note}
        )
        line.assumptions = assumptions
        line.provenance = line.provenance.model_copy(update={"bbox": bbox})
        if line.confidence is Confidence.MEASURED:
            line.confidence = Confidence.INFERRED


def _prov(inputs: TakeoffInputs, sheet: str | None = None, detail: str | None = None) -> Provenance:
    """Provenance whose page is the page of the sheet it names.

    The foundation and level lines cite the structural sheet their figures are
    stated on, which is not the plan the footprint was measured from. Taking
    the footprint's page regardless put AB_Fourplex_01's slab on page 10 (A101)
    while naming S201, which is page 24.
    """
    named = sheet or inputs.footprint_sheet
    page = inputs.sheet_pages.get((named or "").upper())
    if page is None and re.fullmatch(r"p\d+", named or ""):
        page = int(named[1:]) - 1  # an unnumbered sheet, labelled by structural_texts
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

    # Screw piles beside strip footings and no grade beam carry a deck or porch
    # (Landmark's basements), not the house.
    if spec.screw_piles and spec.system != "strip_footing":
        dia = f", {spec.pile_diameter_mm:.0f} mm dia" if spec.pile_diameter_mm else ""
        out.append(
            TakeoffLine(
                id="ln-screw-piles",
                element_class=ElementClass.FOOTING,
                quantity=0.0,
                unit=Unit.M3,
                confidence=Confidence.ASSUMED,
                material="steel_screw_pile",
                description=f"Screw piles{dia} (steel, by supplier)",
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
    if len(heights.floors) == 1:
        basis_name = "floor to top plate"
    area = round(fp.perimeter_m * height, 2)
    # a vision source reads "vision: A300: 'T/O ROOF' ...", so its sheet is the second field
    sheet = next((s.removeprefix("vision:").split(":")[0].strip() for s in heights.sources), None)

    note = (
        f"Perimeter {fp.perimeter_m:.1f} m from the measured footprint x {height:.3f} m "
        f"wall height ({basis_name}) from the section datums."
    )
    assumptions = [
        "One storey: the wall runs from the floor datum to the top-plate datum, so the "
        "gross and net bases are the same height."
        if len(heights.floors) == 1
        else f"Wall area reported on the '{basis_name}' basis. The gross floor-to-floor basis "
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


_FW_NAME_RE = re.compile(r"(?i)\bFOUNDATION\s+WALL\b")
_FW_RUN_RE = re.compile(r"x ([\d.]+) m over ([\d.]+) m")


def _foundation_wall_assembly(inputs):
    """The drawings' foundation-wall build-up: BC's FW1.x, Ontario's N1, or an
    assembly named FOUNDATION WALL. The most-referenced one, as for walls."""
    for letter in ("FW", "N", "FDN", "FND"):
        asm = inputs.assembly_for(letter)
        if asm is not None:
            return asm
    # Not tagged on the plans: the schedule's own foundation assembly, named
    # FOUNDATION (WALL) and made of concrete (Atlantic's N1 "FOUNDATION").
    named = [
        a for a in inputs.assemblies.values()
        if (_FW_NAME_RE.search(a.name or "") or re.fullmatch(r"(?i)\s*FOUNDATION\s*", a.name or ""))
        and any("CONCRETE" in (lay.material or "").upper() for lay in a.layers)
        and not a.is_slab_on_grade
    ]
    if not named:
        return None
    refs = inputs.tag_refs or {}
    return max(named, key=lambda a: refs.get(a.tag, 0))


def _foundation_wall_layers(inputs, built):
    """The foundation wall's other layers over its area: the rigid insulation,
    drainage board and dampproofing the drawings' foundation-wall assembly
    states. The concrete is already a line of its own, so it is skipped.

    The area is the foundation wall line's own height x run, so these layers
    are ASSUMED whenever that wall is, and inherit its reason.
    """
    wall = next((ln for ln in built if ln.id == "ln-foundation-wall"), None)
    asm = _foundation_wall_assembly(inputs) if wall is not None else None
    if asm is None:
        return [], []
    m = _FW_RUN_RE.search(wall.description or "")
    if not m:
        return [], []
    height, run = float(m.group(1)), float(m.group(2))
    area = round(height * run, 2)
    made, more = _assembly_lines(
        asm,
        area,
        ElementClass.FOUNDATION_WALL,
        confidence=Confidence.ASSUMED if wall.confidence is Confidence.ASSUMED else Confidence.INFERRED,
        area_note=(
            f"Area is the foundation wall's {height:.2f} m height x {run:.1f} m run "
            f"(ln-foundation-wall)."
        ),
        extra_assumptions=[
            f"Layers from {asm.tag} {asm.name}, the drawings' foundation-wall assembly; "
            f"the concrete is counted on ln-foundation-wall, not again here.",
            *wall.assumptions[:1],
        ],
    )
    made = [ln for ln in made if "CONCRETE" not in (ln.material or "").upper()]
    return made, [g for g in more if "defers to the structural" not in g.message]


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
        # The framing's stated spacing sets the split, for it and for the fill beside it.
        framing = layer if layer.is_framing or layer.shares_cavity_with is None else asm.layers[layer.shares_cavity_with]
        fraction = framing.framing_share
        volume = layer.volume_m3(area_m2, fraction)
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
            share = fraction if layer.is_framing else 1 - fraction
            notes.append(
                f"Shares the {layer.thickness_mm:.0f} mm cavity with "
                f"'{partner.material}', so it takes {share:.0%} of it rather than the "
                f"full depth; counting both at full depth would put "
                f"{2 * layer.thickness_mm:.0f} mm of material in a "
                f"{layer.thickness_mm:.0f} mm space."
            )
        elif layer.is_framing:
            notes.append(
                f"Studs at centres take {fraction:.0%} of the "
                f"{layer.thickness_mm:.0f} mm depth; the rest of the cavity is empty."
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
    from ecarbon.extract.openings import ONE_PER_ROW, PLAN_LABEL_NOTE, openings_for

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
    if sheet is None and openings:
        sheet = f"p{page + 1}"  # an unnumbered sheet, labelled as _prov labels one

    windows =[o for o in openings if o.kind == "window"]
    doors = [o for o in openings if o.kind == "door"]

    # A US schedule states its own quantities (or numbers each opening), so
    # the count is the schedule's rather than the plan tags'.
    from_schedule = any(o.counted_by_schedule for o in openings)
    per_row = any(ONE_PER_ROW in o.counts for o in openings)
    count_note = (
        "count of each type from the schedule's own quantity column"
        if from_schedule
        else "count of each type from the tags written on the floor plans"
    )
    from_labels = any(o.note == PLAN_LABEL_NOTE for o in openings)
    if from_labels:
        count_note = "count of each size from the labels written at the openings on the floor plans"
    size_sources = [BasisSource.SCHEDULE, BasisSource.DIM_TEXT_IMPERIAL if from_schedule else BasisSource.DIM_TEXT_METRIC]
    if from_labels:
        size_sources = [BasisSource.DIM_TEXT_IMPERIAL]
    count_assumptions = (
        [
            "A numbered schedule lists each opening once, so each numbered row is "
            "counted as one opening."
        ]
        if per_row
        else []
    )
    for o in openings:
        if o.width_mm is not None and o.height_mm is not None and not o.count and from_schedule:
            gaps.append(
                Gap(
                    code=GapCode.OPENING_SCHEDULE_MISSING,
                    severity=GapSeverity.WARNING,
                    message=(
                        f"{o.kind.capitalize()} type {o.tag} is scheduled but the schedule "
                        f"states no quantity for it, so it is not counted."
                    ),
                )
            )

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
                    sources=size_sources,
                    note=(
                        (
                            "No schedule: size of each opening from the width-over-height label "
                            "at it on the plan, in feet and inches; "
                            if from_labels
                            else "Size of each type from the openings schedule, in feet and inches; "
                            if from_schedule
                            else "Size of each type from the openings schedule, with the metric "
                            "and imperial columns agreeing; "
                        )
                        + count_note
                        + ". "
                        + "; ".join(
                            f"{o.tag} {o.width_mm:.0f}x{o.height_mm:.0f} x{o.count}"
                            for o in sized
                        )
                    ),
                ),
                assumptions=count_assumptions
                if from_schedule
                else [
                    "Count is of size labels written on the plans, one plan per storey, so "
                    "an opening drawn without its label is not counted. A label 6'-5\" or "
                    "taller is taken as a door."
                ]
                if from_labels
                else [
                    "Count is of tags written on the plans, so a single tag against a "
                    "mullioned assembly counts once, and a window shown only on an "
                    "elevation is not counted at all."
                ],
                provenance=Provenance(page=page, sheet_no=sheet, detail="SIZE LABELS ON PLAN" if from_labels else "WINDOW SCHEDULE"),
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
                    sources=size_sources,
                    note=(
                        (
                            "Count of width-over-height labels at the doors on the floor plans, "
                            "one plan per storey; interior and exterior doors are not told apart. "
                            if from_labels
                            else "Count from the door schedule. "
                            if from_schedule
                            else "Count of tags on the floor plans, one variant per storey. "
                        )
                        + "; ".join(f"{o.tag} x{o.count}" for o in counted)
                    ),
                ),
                assumptions=count_assumptions + [
                    "All doors are priced with one factor. The schedule distinguishes "
                    "exterior, interior and fire-rated doors, which carry different "
                    "carbon; separating them needs a factor per door type."
                ],
                provenance=Provenance(page=page, sheet_no=sheet, detail="SIZE LABELS ON PLAN" if from_labels else "DOOR SCHEDULE"),
            )
        )
    return lines, gaps


# Interior-partition lines are the one group whose length is measured rather
# than read off a schedule, so they are named here for callers that report a
# total with and without them.
PARTITION_LINE_PREFIX = "ln-interior-partition"
_PARTY_RE = re.compile(r"\b(DEMISING|PARTY)\b", re.I)


def _is_party_wall(asm) -> bool:
    """A demising (party) wall between units, by the schedule's own name."""
    return bool(_PARTY_RE.search(asm.name or ""))


# Partition wall area per m2 of floor, where the plans' linework cannot be
# measured: the median over the 38 CMHC reference models (IFC wall area by
# P-type tag over the Building Performance Report's GFA) in AB, ATL, NOR, ON
# and QC. BC's models carry their areas in the wrong unit and SK/MB's model
# few partitions, so neither is used. Per design it runs 0.6 to 4.1.
PARTITION_M2_PER_FLOOR_M2 = 1.35
PARTITION_RATIO_RANGE = (0.6, 4.1)
PARTITION_MIN_SHARE = 0.15


def _partition_estimate_m2(inputs: TakeoffInputs, n_storeys: int) -> float | None:
    fp = inputs.footprint
    if fp is None or not n_storeys:
        return None
    return round(PARTITION_M2_PER_FLOOR_M2 * fp.area_m2 * n_storeys, 1)


def _assumed_partition_lines(
    inputs: TakeoffInputs, height: float, n_storeys: int, measured_m2: float | None
) -> tuple[list[TakeoffLine], list[Gap]]:
    """Partitions from the floor area, ASSUMED, when they cannot be measured."""
    from ecarbon.takeoff.framing import _standard_assembly

    est = _partition_estimate_m2(inputs, n_storeys)
    if not est:
        return [], []
    drawn = inputs.assembly_for("P")
    asm = drawn or _standard_assembly("P", inputs)
    floor = inputs.footprint.area_m2 * n_storeys
    lo, hi = PARTITION_RATIO_RANGE
    why = (
        "no partition run could be measured off the plan linework"
        if measured_m2 is None
        else f"the plan linework gave only {measured_m2:.0f} m2, under 15% of this, "
        f"which is a failed reading rather than the building's partitions"
    )
    assumptions = [
        f"Partition area assumed at {PARTITION_M2_PER_FLOOR_M2} m2 per m2 of floor "
        f"({floor:.0f} m2: the {inputs.footprint.area_m2:.1f} m2 footprint over "
        f"{n_storeys} storey{'s' if n_storeys > 1 else ''}), because {why}.",
        f"{PARTITION_M2_PER_FLOOR_M2} is the median of 38 CMHC reference models; a single "
        f"design runs {lo} to {hi}, so this line can be off by half or by double. "
        f"Override it with the measured run where you have one.",
    ]
    if drawn is None:
        assumptions.append(
            "No partition assembly could be read either, so a standard 38 x 89 mm stud "
            "partition with gypsum both faces is assumed."
        )
    def expand(a, extra, area=est, cls=ElementClass.INTERIOR_PARTITION, note=""):
        return _assembly_lines(
            a,
            area,
            cls,
            confidence=Confidence.ASSUMED,
            area_note=f"Area assumed from the floor area: {est:.0f} m2 of partition wall{note}.",
            extra_assumptions=assumptions + extra,
        )

    # The same split by floor-plan tag count the measured run uses, so a
    # demising wall is priced as itself rather than as P1.
    mix = (_partition_mix(None, inputs) if drawn is not None else None) or [(asm, 1.0, 0.0)]
    if len(mix) > 1:
        split = ", ".join(f"{a.tag} {inputs.plan_tag_refs[a.tag]}" for a, _s, _m in mix)
        assumptions.append(
            f"It is split across the partition types in proportion to how often the "
            f"floor plans tag each ({split})."
        )
    built, more = [], []
    for a, share, _m in mix:
        part = round(est * share, 2)
        cls = ElementClass.PARTY_WALL if _is_party_wall(a) else ElementClass.INTERIOR_PARTITION
        note = f", {share:.0%} of it {a.tag} by tag count" if len(mix) > 1 else ""
        made, gaps = expand(a, [], part, cls, note)
        more += gaps
        if drawn is not None:
            from ecarbon.takeoff.framing import missing_layer_lines

            faces, _ = missing_layer_lines(
                "P", made, inputs, _assembly_lines, part, cls, Confidence.ASSUMED,
                f"Area assumed from the floor area: {part:.0f} m2 of {a.tag} partition wall.",
                assumptions,
            )
            made += faces
        built += made
    if not built and drawn is not None:
        # The drawn assembly states no layer depth that gives a volume.
        built, more = expand(_standard_assembly("P", inputs), [
            f"{drawn.tag} gives no layer a volume can be computed for, so a standard "
            f"38 x 89 mm stud partition with gypsum both faces is assumed."
        ])
    if not built:
        return [], more
    for line in built:
        line.id = re.sub(r"^ln-(interior-partition|party-wall)-", f"{PARTITION_LINE_PREFIX}-", line.id)
    more.append(
        Gap(
            code=GapCode.GEOMETRY_AMBIGUOUS,
            severity=GapSeverity.WARNING,
            message=(
                f"Interior partitions could not be measured ({why}), so their area is "
                f"assumed from the floor area at {PARTITION_M2_PER_FLOOR_M2} m2 per m2, the "
                f"median of the CMHC reference models (one design runs {lo} to {hi}). "
                f"The carbon total is reported with and without these lines."
            ),
            affects=[line.id for line in built],
        )
    )
    return built, more


def _partition_mix(measured, inputs: TakeoffInputs) -> list[tuple] | None:
    """[(assembly, share of the run, metres)]: the measured run split across
    the schedule's P types by how often the plans tag each one.

    Pricing the whole run as the commonest type (the old rule) left out every
    insulated demising wall. Tag shares were checked against the IFC's wall
    area by type, counting floor plans only: AB_Fourplex_01 P1/P2/P3
    70/17/8% vs 61/21/15%, AB_Sixplex P1/P3 50/30% vs 65/22%,
    AB_Rowhouse_01 P1/P3 69/23% vs 64/28%. Counting every sheet put 40 points
    too much on the demising walls, which sections repeat. The depth each wall
    was paired at was tried too and put 263 m2 on AB_Fourplex_01's P3 against
    the IFC's 63, so it is not used for this.
    """
    refs = inputs.plan_tag_refs
    p_asms = {
        t: a for t, a in inputs.assemblies.items()
        if refs.get(t) and (t.upper().startswith("P") or _is_party_wall(a))
    }
    total = sum(refs[t] for t in p_asms)
    if len(p_asms) < 2 or not total:
        return None
    run = measured.total_length_m if measured is not None else 0.0
    return [
        (p_asms[t], refs[t] / total, run * refs[t] / total)
        for t in sorted(p_asms, key=lambda t: (-refs[t], t))
    ]


def _partition_lines(design, inputs: TakeoffInputs) -> tuple[list[TakeoffLine], list[Gap]]:
    """Interior partitions, expanded from the assembly over a measured run.

    Measured against the IFC on all seven Alberta designs: median error 5.7%,
    six of seven within 10%, with AB_ADU_02 over-detecting at +92%. Four
    earlier approaches spanned -66% to +350% and are listed in the gap report,
    because a reader deciding whether to trust this number deserves to know it
    was hard to get rather than assumed.
    """
    from ecarbon.geometry.partitions import FAILED_APPROACHES, partitions_for

    # The run is summed over every storey's plan, so each metre of it stands one
    # storey tall, not the whole building. Multiplying by the summed height
    # counted the partitions once per storey: AB_Rowhouse_02 read 1,203 m2
    # against the IFC's 576, AB_Sixplex 2,029 against 738.
    building_height = inputs.heights.net_wall_height_m or inputs.heights.total_wall_height_m
    n_storeys = len(inputs.heights.storey_heights_m())
    if building_height is None or n_storeys == 0:
        return [], []
    height = building_height / n_storeys
    try:
        measured = partitions_for(design)
    except Exception:
        measured = None

    asm = inputs.assembly_for("P")
    area = measured.area_m2(height) if measured is not None and measured.runs else None
    estimate = _partition_estimate_m2(inputs, n_storeys)
    # The linework measure is tuned on Alberta's lineweights and elsewhere can
    # find nothing, or a few stray metres (ON_Sixplex: 6 m of run in a 450 m2
    # building). Below 15% of the floor-area estimate it is a failed reading,
    # not a small building's partitions (QC's ADUs, at about a quarter, are
    # genuinely sparse: their models carry 0.6 m2 per m2, and are kept).
    if asm is None or area is None or (estimate and area < PARTITION_MIN_SHARE * estimate):
        return _assumed_partition_lines(inputs, height, n_storeys, area)

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

    from ecarbon.takeoff.framing import missing_layer_lines

    mix = _partition_mix(measured, inputs) or [(asm, 1.0, measured.total_length_m)]
    if len(mix) > 1:
        split = ", ".join(f"{a.tag} {inputs.plan_tag_refs[a.tag]}" for a, _s, _m in mix)
        shared[2] = (
            f"The run is not measured by type, so it is split across the partition "
            f"types in proportion to how often the floor plans tag each ({split}). On the "
            f"Alberta reference models this tracks each type's area to within about "
            f"15 points of share."
        )
    built, more = [], []
    for a, share, metres in mix:
        part = round(area * share, 2)
        cls = ElementClass.PARTY_WALL if _is_party_wall(a) else ElementClass.INTERIOR_PARTITION
        made, gaps = _assembly_lines(
            a,
            part,
            cls,
            confidence=Confidence.INFERRED,
            area_note=(
                f"Area is {metres:.1f} m of "
                + (f"the measured partition run ({share:.0%}, {a.tag}'s share by tag count) x "
                   if len(mix) > 1 else "measured partition run x ")
                + f"{height:.2f} m mean storey wall height ({building_height:.2f} m over "
                f"{n_storeys} storeys), since each storey's run stands one storey tall."
            ),
            extra_assumptions=shared,
        )
        faces, _ = missing_layer_lines(
            "P", made, inputs, _assembly_lines, part, cls,
            Confidence.ASSUMED, f"Area is the {part:.1f} m2 of {a.tag} partition measured.",
        )
        built += made + faces
        more += gaps
    for line in built:
        # A party wall's share comes out of the same measured run, so it keeps
        # the partition prefix: the total "without partitions" still drops it.
        line.id = re.sub(r"^ln-(interior-partition|party-wall)-", f"{PARTITION_LINE_PREFIX}-", line.id)

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


_MASONRY_RE = re.compile(r"\b(MASONRY|CMU|CONCRETE\s+BLOCK)", re.I)


def _name_masonry_foundation(lines: list[TakeoffLine], inputs: TakeoffInputs) -> None:
    """Say so when the foundation wall line stands in for a stated block wall.

    ON_Fourplex_01's N1 states 190 mm concrete masonry units; the store has no
    masonry factor, so the line prices solid cast concrete, which overstates it.
    """
    wall = next((ln for ln in lines if ln.id == "ln-foundation-wall"), None)
    asm = inputs.assembly_for("N")
    layer = next((lay for lay in asm.layers if _MASONRY_RE.search(lay.material)), None) if asm else None
    if wall is None or layer is None:
        return
    depth = f"{layer.thickness_mm:.0f} mm " if layer.thickness_mm else ""
    wall.assumptions.append(
        f"{asm.tag} states the foundation wall as {depth}'{layer.material}', but no masonry "
        f"factor is in the store, so it is priced as solid cast-in-place concrete. A "
        f"hollow-core block wall carries less, so this line overstates it."
    )


def _name_ladder_footing(lines: list[TakeoffLine], inputs: TakeoffInputs) -> None:
    """Say the wall height was measured off the datum ladder, not printed."""
    lf = inputs.ladder_footing
    wall = next((ln for ln in lines if ln.id == "ln-foundation-wall"), None)
    if lf is None or wall is None:
        return
    wall.assumptions.append(
        f"The height is measured, not printed: sheet {lf.sheet_no} labels T/O FOOTING on its "
        f"datum ladder with no elevation, and where it is drawn puts it {-lf.elevation_m:.2f} m "
        f"below the ground floor. The wall is taken as running from there to the ground floor."
    )


# A standard timber stair: three 38 x 286 mm (2x12) stringers, 38 mm treads
# 254 mm deep, 914 mm (36") wide. Only the count and risers are read.
STAIR_WIDTH_M, STAIR_RUN_M, STAIR_TREAD_M, STRINGER_M2 = 0.914, 0.254, 0.038, 0.038 * 0.286


def _stair_lines(design) -> list[TakeoffLine]:
    """Stair flights counted off the floor plans, priced as a standard timber stair."""
    from ecarbon.extract.stairs import stairs_on_plans

    try:
        st = stairs_on_plans(design)
    except Exception:
        return []
    if st is None:
        return []
    n = st.risers
    stringer = math.hypot((n - 1) * STAIR_RUN_M, n * st.rise_mm / 1000)
    per = 3 * STRINGER_M2 * stringer + (n - 1) * STAIR_WIDTH_M * STAIR_RUN_M * STAIR_TREAD_M
    return [TakeoffLine(
        id="ln-stairs",
        element_class=ElementClass.STAIR,
        quantity=round(per * st.flights, 3),
        unit=Unit.M3,
        confidence=Confidence.ASSUMED,
        material="CMHC_Wood Framing",
        description=f"Stairs, estimated: {st.flights} flight(s) of {n} risers @ {st.rise_mm:.0f} mm",
        basis=Basis(
            sources=[BasisSource.DEFAULT_RULE],
            note=(
                f"Flights counted off the floor plans: {st.up_marks} UP arrow(s) and "
                f"{st.riser_labels} riser label(s), each flight labelled on the floor it leaves "
                f"and the one it reaches, so the larger of the arrows and half the labels. "
                f"Risers per flight are the median stated."
            ),
        ),
        assumptions=[
            "Assumed standard: three 38 x 286 mm (2x12) stringers, 38 mm treads 254 mm deep, "
            "914 mm wide, all timber; a concrete or steel stair would be far heavier.",
            "On the CMHC models this count matched the IFC's flights or fell short, never "
            "over (AB_Rowhouse_01 reads 1 of 4); landings, handrails and guards are not counted.",
        ],
        provenance=Provenance(page=st.page, sheet_no=st.sheet_no, detail="stair riser label", bbox=st.bbox),
    )]


def build_takeoff(
    design,
    project: ProjectFacts | None = None,
    trust_stated_gfa: bool = False,
    progress=None,
    overrides=None,
) -> TakeoffResult:
    """Produce a bill of quantities for one design, from measured geometry.

    `trust_stated_gfa` marks a floor area the user typed, as opposed to one
    read from a Building Performance Report. Both are checked against what the
    drawings depict and both are reported when they disagree, but only the
    report's figure is replaced: a number a person entered deliberately is
    theirs to change, and overriding it would answer a question they already
    answered.

    `progress(stage, detail)` is told as each stage finishes, with what it
    found, so an upload can show its real progress rather than a spinner.

    `overrides` are user-stated inputs (contract C2); every line resting on
    one is labelled as stated rather than measured.
    """
    tell = progress or (lambda stage, detail: None)
    facts = project or ProjectFacts(name=design.key)
    expected = (
        facts.gfa_m2 / facts.storeys if facts.gfa_m2 and facts.storeys else None
    )
    inputs, sheets, gaps = gather(design, expected, overrides=overrides)
    try:
        from ecarbon.intake.locale import detect_locale

        inputs.locale = detect_locale(design)
    except Exception:
        inputs.locale = None
    tell(
        "sheets",
        f"{len(sheets)} sheets classified, {sum(1 for s in sheets if s.readable)} readable",
    )
    if inputs.vision_sheets:
        tell("vision", f"{inputs.vision_sheets} sheets")

    lines = _foundation_lines(inputs) + _wall_lines(inputs)
    fp = inputs.footprint
    tell(
        "geometry",
        f"footprint {fp.area_m2:,.0f} m2 off sheet {_footprint_where(inputs)}"
        if fp
        else "no footprint could be measured",
    )

    opening_lines, opening_gaps = _opening_lines(design)
    lines += opening_lines
    gaps += opening_gaps
    tell("openings", f"{len(opening_lines)} window and door lines from the schedules")

    # Resolve each element's area into its materials, using the assembly the
    # drawings actually reference rather than the first one the schedule lists.
    wall = next((ln for ln in lines if ln.id == "ln-exterior-wall"), None)

    if wall is not None:
        asm = inputs.assembly_for("W")
        steel = asm and next((x for x in asm.layers if x.is_framing and STEEL_RE.search(x.material)), None)
        if steel is not None:
            # The store holds only timber framing; pricing steel studs as wood
            # would put a confident wrong number on the line.
            wall.material = "Steel Stud Framing"
            wall.assumptions.append(
                f"{asm.tag} frames with '{steel.material}'. The factor store has no "
                f"steel stud factor, so this framing is not counted rather than "
                f"priced as timber."
            )
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
                extra_assumptions=[_roof_area_note(inputs.heights)],
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

    # Floor joists and roof framing the assemblies defer to the structure,
    # estimated from a stated standard over measured geometry (framing.py).
    # Each one replaces its "not counted" note with a pointer to its line.
    # Elements whose own assembly could not be read take a standard Part 9
    # build-up, ASSUMED (framing.py); the drawn assembly wins where read.
    std_lines, std_gaps, std_used = standard_assembly_lines(inputs, lines, _assembly_lines)
    lines += std_lines
    gaps += std_gaps
    framed, covered = framing_lines(inputs, lines, std_used)
    lines += framed
    fw_lines, fw_gaps = _foundation_wall_layers(inputs, lines)
    lines += fw_lines
    gaps += fw_gaps
    _name_masonry_foundation(lines, inputs)
    _name_ladder_footing(lines, inputs)
    lines += _stair_lines(design)
    for gap in gaps:
        for marker, line_id in covered.items():
            if marker in gap.message and gap.message.startswith("Foundation:"):
                # Say exactly what is now estimated and what is still missing.
                ids = {ln.id for ln in lines} | {ln.id for ln in framed}
                framed_ids = {ln.id for ln in framed}
                done = []
                if "ln-slab-on-grade" in framed_ids:
                    done.append("the slab on ln-slab-on-grade")
                if "ln-thickened-edge" in framed_ids:
                    done.append("a thickened slab edge on ln-thickened-edge")
                if "ln-strip-footing" in framed_ids:
                    done.append("a strip footing on ln-strip-footing")
                if "ln-foundation-wall" in framed_ids:
                    done.append(
                        ("a stem wall" if standard_code(inputs) == "IRC" else "a frost wall")
                        + " on ln-foundation-wall"
                    )
                done = done or [f"the slab on {line_id}"]
                edge = "ln-thickened-edge" in ids
                left = [] if edge or any(i.startswith("ln-strip-footing") for i in ids) else ["footings"]
                if "ln-foundation-wall" not in ids and not edge:
                    left.append("foundation walls")
                gap.message = (
                    f"{gap.message.replace(' Concrete quantities cannot be produced.', '').rstrip('.')}. "
                    f"Estimated instead (assumed): {' and '.join(done)}."
                    + (f" Still uncounted: {', '.join(left)}." if left else "")
                    + " Replace with the foundation design where it is known."
                )
                gap.severity = GapSeverity.WARNING
                gap.affects = [line_id]
                break
            if marker in gap.message and (
                "not counted" in gap.message or "no volume can be computed" in gap.message
            ):
                what = re.split(
                    r" defers to | states no thickness| gives its thickness as", gap.message
                )[0].split(";")[0]
                gap.message = (
                    f"{what}: the drawings give no quantity for it, so it is estimated "
                    f"from a stated standard on {line_id} (assumed) rather than left "
                    f"out. Replace it with the structural drawings' member, gauge, "
                    f"depth and spacing where those are known."
                )
                gap.severity = GapSeverity.INFO
                gap.affects = [line_id]

    # Two "Foundation:" notes rewritten to the same estimate say it twice;
    # keep the first. And the missing-foundation-plan note no longer holds
    # that nothing could be produced once a standard stands in.
    said: set[str] = set()
    kept = []
    for gap in gaps:
        if gap.message.startswith("Foundation:") and "Estimated instead" in gap.message:
            tail = gap.message.split("Estimated instead", 1)[1]
            if tail in said:
                continue
            said.add(tail)
        kept.append(gap)
    gaps[:] = kept
    assumed_fdn = [
        ln.id for ln in framed
        if ln.id in ("ln-slab-on-grade", "ln-strip-footing", "ln-foundation-wall", "ln-thickened-edge")
    ]
    if assumed_fdn:
        for gap in gaps:
            if gap.message.startswith("No readable foundation plan"):
                gap.message = gap.message.replace(
                    ", so those quantities cannot be produced.",
                    ", so those quantities cannot be read. A standard foundation is "
                    f"assumed in their place ({', '.join(assumed_fdn)}); replace it "
                    "with the foundation design.",
                )
                gap.severity = GapSeverity.WARNING
                gap.affects = assumed_fdn
    # A set with no schedule sheet can still state its openings and walls
    # elsewhere (plan size labels, a wall legend, an energy table); the
    # missing-sheet note must not say nothing was produced when it was.
    instead = {
        "No readable opening schedule": (
            [ln.id for ln in lines if ln.id in ("ln-windows", "ln-doors")],
            "the windows and doors are read from the size labels on the plans instead",
        ),
        "No readable assembly schedule": (
            [ln.id for ln in lines if ln.id.startswith("ln-exterior-wall-")
             and ln.confidence != Confidence.ASSUMED],
            "the exterior wall is read from the drawings' own wall notes instead; "
            "other assemblies are assumed where noted",
        ),
    }
    # A sheet the rules could not read may still have been read as an image.
    for start, readings, classes, what in (
        ("No readable floor plan", inputs.vision, _FROM_FOOTPRINT, "footprint was"),
        ("No readable section", inputs.vision_levels, _FROM_HEIGHTS, "storey heights were"),
    ):
        if readings:
            sheet = readings[0].note.split(":")[1].strip()
            instead[start] = (
                [ln.id for ln in lines if ln.element_class in classes],
                f"the {what} read by AI from the image of {sheet}, "
                "which cannot be checked against text",
            )
    for gap in gaps:
        for start, (ids, how) in instead.items():
            if gap.message.startswith(start) and ids:
                gap.message = gap.message.replace(
                    ", so those quantities cannot be produced.", f"; {how} ({', '.join(ids[:4])})."
                )
                gap.severity = GapSeverity.WARNING
                gap.affects = ids

    tell("assemblies", f"{len(inputs.assemblies)} assemblies resolved into their layers")

    # Interior partitions, measured from the plans rather than assumed.
    partition_lines, partition_gaps = _partition_lines(design, inputs)
    lines += partition_lines
    gaps += partition_gaps
    tell("partitions", f"{len(partition_lines)} partition lines off the plan linework")

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

    if inputs.locale is not None:
        gaps += mark_units(lines, inputs.locale)

    # Every wall and partition on an assumed storey height says so.
    mark_assumed_heights(inputs, lines)
    label_vision(lines, inputs)
    label_stated(lines, overrides)

    return TakeoffResult(
        project=facts,
        source_file=design.drawings_pdf.name,
        sheets=sheets,
        gaps=gaps,
        lines=lines,
        extracted_at=date.today(),
    )
