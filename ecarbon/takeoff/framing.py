"""Floor joists and roof framing the architectural set defers to the structure.

Every CMHC floor and roof assembly names its framing ("ENGINEERED WOOD JOIST
OR I-JOIST", "PRE FABRICATED ROOF TRUSS", "WOOD ROOF FRAMING") and then defers
it to the structural drawings, which state no quantity for it. Leaving it out
was honest but left the largest wood quantity in the building at zero, so the
total read a fraction of a professional assessment (median 20% of CMHC's own
A1-A5 across the catalogue; wood framing -97% against the IFC models).

These lines estimate that framing from a stated standard, applied to geometry
that IS measured: the floor area (footprint x suspended floors), the roof's
span (the footprint's short side) and its rise (the section's roof datum).
Every line is ASSUMED, says exactly which standard it assumed, and replaces
the "not counted" note with a pointer to itself. A structural framing plan
that states the real member, depth or spacing should replace the standard.
"""

from __future__ import annotations

import math
import re

from ecarbon.extract.levels import Level, StoreyHeights
from ecarbon.models import (
    Basis,
    BasisSource,
    Confidence,
    ElementClass,
    Provenance,
    TakeoffLine,
    Unit,
)

# I-joist, the commonest residential section: 302 mm (11-7/8") deep, 63 x 38 mm
# lumber or LVL flanges top and bottom, 9.5 mm OSB web, at 400 mm (16") centres.
IJOIST_DEPTH_MM = 302.0
IJOIST_FLANGE_W_MM = 63.0
IJOIST_FLANGE_T_MM = 38.0
IJOIST_WEB_MM = 9.5
JOIST_SPACING_MM = 400.0
# Solid-sawn joist or rafter: 38 x 235 mm (2x10) at 400 mm.
SAWN_W_MM = 38.0
SAWN_D_MM = 235.0
# Rim boards, blocking and doubled members around openings.
FRAMING_EXTRAS = 0.10

# Light wood truss: 38 x 89 mm (2x4) chords and webs, at 610 mm (24") centres,
# Fink (W) web pattern, 600 mm overhang each side.
TRUSS_MEMBER_M2 = 0.038 * 0.089
TRUSS_SPACING_M = 0.61
TRUSS_OVERHANG_M = 0.6
# The common Part 9 slab-on-grade, where the drawings draw one but state no thickness.
STANDARD_SLAB_MM = 100.0
# A frost wall on strip footings: Part 9's common frost depth, 200 mm out of
# the ground, 200 mm thick (NBC Table 9.15.4.2.A, two or more storeys).
STANDARD_FROST_MM = 1200.0
ABOVE_GRADE_MM = 200.0
STANDARD_FOUNDATION_WALL_MM = 200.0
# A strip footing drawn with no section: 600 x 200 mm, the common Part 9 footing.
STANDARD_FOOTING_MM = (600.0, 200.0)

# When the sections give no roof datum: a 4:12 pitch.
DEFAULT_PITCH = 4.0 / 12.0

LUMBER = "CMHC_Wood Framing"
OSB = "sheathing_osb_13mm"
STEEL = "cold_formed_steel_framing"

# Cold-formed steel wall framing, the standard section for a 140 mm envelope
# stud: 600S162-43 (6 in web, 1-5/8 in flange, 1/2 in lip, 18 ga, 1.146 mm
# design thickness) at 400 mm centres, 600T125-43 tracks top and bottom of
# each storey, +15% for jambs, headers, kings and bridging.
STEEL_DENSITY = 7850.0
STUD_DEVELOPED_MM = (152.4 + 2 * 41.3 + 2 * 12.7)  # web + 2 flanges + 2 lips
TRACK_DEVELOPED_MM = (152.4 + 2 * 31.75)  # web + 2 legs
CFS_T_MM = 1.146
STEEL_EXTRAS = 0.15


def steel_kg_per_m2_wall(storey_height_m: float = 3.0) -> float:
    """Steel per m2 of wall: studs at 400 mm, two tracks per storey, extras."""
    kg_m = lambda dev_mm: dev_mm / 1000 * CFS_T_MM / 1000 * STEEL_DENSITY  # noqa: E731
    studs = kg_m(STUD_DEVELOPED_MM) * (1000.0 / JOIST_SPACING_MM)
    tracks = kg_m(TRACK_DEVELOPED_MM) * 2 / max(storey_height_m, 2.0)
    return (studs + tracks) * (1 + STEEL_EXTRAS)

_JOIST_RE = re.compile(r"\bJOIST", re.I)
_IJOIST_RE = re.compile(r"\bI-?\s?JOIST|ENGINEERED WOOD JOIST", re.I)
_TRUSS_RE = re.compile(r"\bTRUSS", re.I)
_RAFTER_RE = re.compile(r"\bRAFTER|ROOF FRAMING", re.I)


def _deferred_framing(asm):
    """The deferred framing layer of an assembly, if it has one."""
    for layer in asm.layers:
        mat = layer.material or ""
        if layer.deferred_to and (_JOIST_RE.search(mat) or _TRUSS_RE.search(mat) or _RAFTER_RE.search(mat)):
            return layer
    return None


def roof_rise_m(heights) -> tuple[float | None, str]:
    """Ridge height above the top plate from the section datums, if stated."""
    if heights is not None and heights.roof_level_m is not None and heights.floors:
        hs = heights.storey_heights_m()
        if hs:
            r = heights.roof_level_m - heights.floors[0].elevation_m - sum(hs)
            if 0.3 <= r <= 6.0:
                return r, f"the section's roof datum, {r:.2f} m above the top plate"
    return None, ""


def _ijoist_per_m2() -> tuple[float, float]:
    """(lumber flange m3, OSB web m3) of I-joists per m2 of floor."""
    per_m = 1000.0 / JOIST_SPACING_MM  # metres of joist per m2 of floor
    flanges = 2 * (IJOIST_FLANGE_W_MM / 1000) * (IJOIST_FLANGE_T_MM / 1000)
    web = (IJOIST_WEB_MM / 1000) * ((IJOIST_DEPTH_MM - 2 * IJOIST_FLANGE_T_MM) / 1000)
    k = 1 + FRAMING_EXTRAS
    return flanges * per_m * k, web * per_m * k


def _sawn_per_m2(slope_factor: float = 1.0) -> float:
    per_m = 1000.0 / JOIST_SPACING_MM
    return (SAWN_W_MM / 1000) * (SAWN_D_MM / 1000) * per_m * slope_factor * (1 + FRAMING_EXTRAS)


def fink_truss_m3(span_m: float, rise_m: float) -> float:
    """Timber in one Fink (W) truss: chords, four webs, overhangs."""
    half = span_m / 2
    top = 2 * (math.hypot(half, rise_m) + TRUSS_OVERHANG_M)
    w1 = math.hypot(span_m / 12, rise_m / 2)
    w2 = math.hypot(span_m / 6, rise_m)
    return (span_m + top + 2 * (w1 + w2)) * TRUSS_MEMBER_M2


def _line(id_, cls, qty, material, desc, note, assumptions, prov) -> TakeoffLine:
    return TakeoffLine(
        id=id_,
        element_class=cls,
        quantity=round(qty, 3),
        unit=Unit.M3,
        confidence=Confidence.ASSUMED,
        material=material,
        description=desc,
        basis=Basis(sources=[BasisSource.DEFAULT_RULE, BasisSource.VECTOR_PATH], note=note),
        assumptions=assumptions,
        provenance=prov,
    )


def framing_lines(inputs, built=(), standard=None) -> tuple[list[TakeoffLine], dict[str, str]]:
    """Estimated joist, roof and steel-stud framing lines, and {note marker:
    line id} so the caller can replace each "not counted" note with a
    pointer. `built` is the bill so far (the steel estimate needs the wall
    area the wall line measured)."""
    fp = inputs.footprint
    if fp is None:
        return [], {}
    lines: list[TakeoffLine] = []
    covered: dict[str, str] = {}
    # Each estimate traces to the schedule row that names what it stands in
    # for ("ENGINEERED WOOD JOIST OR I-JOIST"), on the assemblies sheet: the
    # one place the drawings say anything about it.
    def prov(asm, layer):
        return Provenance(
            page=asm.page if asm.page is not None else (inputs.footprint_page or 0),
            sheet_no=asm.sheet,
            detail=(layer.material or asm.tag)[:80],
        )

    # ---- floor joists, over every suspended floor ---------------------------
    upper = max(inputs.heights.n_storeys - 1, 0)
    slab_tags = {t for t, a in inputs.assemblies.items() if a.is_slab_on_grade}
    fasm = inputs.assembly_for("F", exclude=slab_tags) or (standard or {}).get("F")
    flayer = _deferred_framing(fasm) if fasm is not None else None
    if flayer is not None and upper > 0 and _JOIST_RE.search(flayer.material or ""):
        area = fp.area_m2 * upper
        marker = f"{fasm.tag} layer {flayer.index + 1} '{flayer.material}'"
        common = [
            f"The drawings name '{flayer.material}' in {fasm.tag} and defer it to the "
            f"structural drawings, which give no quantity; this is a standard, not a reading.",
            f"Applied to {area:.1f} m2: the {fp.area_m2:.1f} m2 footprint over {upper} "
            f"suspended floor{'s' if upper > 1 else ''}.",
            f"Includes {FRAMING_EXTRAS:.0%} for rim boards, blocking and doubled members.",
        ]
        if _IJOIST_RE.search(flayer.material or ""):
            flange, web = _ijoist_per_m2()
            std = (
                f"{IJOIST_DEPTH_MM:.0f} mm (11-7/8\") I-joists at {JOIST_SPACING_MM:.0f} mm "
                f"centres: {IJOIST_FLANGE_W_MM:.0f} x {IJOIST_FLANGE_T_MM:.0f} mm flanges, "
                f"{IJOIST_WEB_MM} mm OSB web"
            )
            fid = f"ln-floor-joists-{fasm.tag.lower()}-flanges"
            lines.append(_line(
                fid, ElementClass.FLOOR_ASSEMBLY, flange * area, LUMBER,
                f"Floor joist flanges ({fasm.tag}), estimated: {std}",
                f"Assumed standard: {std}, over the measured floor area.",
                common + ["Flanges priced as sawn lumber; LVL flanges would differ."],
                prov(fasm, flayer),
            ))
            lines.append(_line(
                f"ln-floor-joists-{fasm.tag.lower()}-webs", ElementClass.FLOOR_ASSEMBLY,
                web * area, OSB,
                f"Floor joist webs ({fasm.tag}), estimated: {IJOIST_WEB_MM} mm OSB",
                f"Assumed standard: {std}, over the measured floor area.",
                common, prov(fasm, flayer),
            ))
            covered[marker] = fid
        else:
            std = f"38 x 235 mm (2x10) joists at {JOIST_SPACING_MM:.0f} mm centres"
            fid = f"ln-floor-joists-{fasm.tag.lower()}"
            lines.append(_line(
                fid, ElementClass.FLOOR_ASSEMBLY, _sawn_per_m2() * area, LUMBER,
                f"Floor joists ({fasm.tag}), estimated: {std}",
                f"Assumed standard: {std}, over the measured floor area.",
                common, prov(fasm, flayer),
            ))
            covered[marker] = fid

    # ---- roof framing ------------------------------------------------------
    rasm = inputs.assembly_for("R") or (standard or {}).get("R")
    rlayer = _deferred_framing(rasm) if rasm is not None else None
    if rlayer is not None:
        mat = rlayer.material or ""
        marker = f"{rasm.tag} layer {rlayer.index + 1} '{mat}'"
        span, length = sorted((fp.width_m, fp.depth_m))
        rise, rise_src = roof_rise_m(inputs.heights)
        if rise is None:
            rise = span / 2 * DEFAULT_PITCH
            rise_src = f"a 4:12 pitch assumed ({rise:.2f} m), since the sections give no roof datum"
        if _TRUSS_RE.search(mat):
            n = math.ceil(length / TRUSS_SPACING_M) + 1
            per = fink_truss_m3(span, rise)
            std = (
                f"{n} Fink trusses at {TRUSS_SPACING_M * 1000:.0f} mm centres, 38 x 89 mm "
                f"(2x4) members, {TRUSS_OVERHANG_M * 1000:.0f} mm overhangs"
            )
            fid = f"ln-roof-trusses-{rasm.tag.lower()}"
            lines.append(_line(
                fid, ElementClass.ROOF_ASSEMBLY, per * n, LUMBER,
                f"Roof trusses ({rasm.tag}), estimated: {n} trusses over a {span:.1f} m span",
                (
                    f"Assumed standard: {std}. Span is the measured footprint's short side "
                    f"({span:.2f} m), run its long side ({length:.2f} m), and the rise "
                    f"{rise_src}."
                ),
                [
                    f"The drawings name '{mat}' in {rasm.tag} and defer it to the structural "
                    f"drawings, which give no quantity; this is a standard, not a reading.",
                    "A gable roof spanning the short side is assumed; a hip roof or girder "
                    "trusses would differ. Steel gusset plates are not counted.",
                ],
                prov(rasm, rlayer),
            ))
            covered[marker] = fid
        elif _RAFTER_RE.search(mat) or _JOIST_RE.search(mat):
            slope = math.hypot(span / 2, rise) / (span / 2)
            std = f"38 x 235 mm (2x10) rafters or joists at {JOIST_SPACING_MM:.0f} mm centres"
            fid = f"ln-roof-framing-{rasm.tag.lower()}"
            lines.append(_line(
                fid, ElementClass.ROOF_ASSEMBLY, _sawn_per_m2(slope) * fp.area_m2, LUMBER,
                f"Roof framing ({rasm.tag}), estimated: {std}",
                (
                    f"Assumed standard: {std}, over the {fp.area_m2:.1f} m2 footprint on the "
                    f"slope ({slope:.2f}x plan), with the rise {rise_src}."
                ),
                [
                    f"The drawings name '{mat}' in {rasm.tag} and defer it to the structural "
                    f"drawings, which give no quantity; this is a standard, not a reading.",
                    f"Includes {FRAMING_EXTRAS:.0%} for blocking and doubled members.",
                ],
                prov(rasm, rlayer),
            ))
            covered[marker] = fid

    # ---- steel studs in the exterior wall ----------------------------------
    # The wall line is left uncounted when its assembly frames in steel (the
    # store had no steel factor, and pricing steel as timber would be wrong).
    # Now there is one (SFIA), so the steel is estimated from the standard
    # section over the wall area the wall line measured.
    wall = next((ln for ln in built if ln.id == "ln-exterior-wall"), None)
    wasm = inputs.assembly_for("W")
    steel = None
    if wasm is not None:
        steel = next(
            (x for x in wasm.layers if x.is_framing and re.search(r"\b(METAL|STEEL)\b", x.material or "", re.I)),
            None,
        )
    if wall is not None and steel is not None and wall.quantity > 0:
        hs = inputs.heights.storey_heights_m() if inputs.heights else []
        h = sum(hs) / len(hs) if hs else 3.0
        per = steel_kg_per_m2_wall(h)
        std = (
            f"600S162-43 (6 in, 18 ga) studs at {JOIST_SPACING_MM:.0f} mm centres with "
            f"600T125-43 tracks top and bottom of each {h:.2f} m storey, "
            f"+{STEEL_EXTRAS:.0%} for jambs, headers and bridging: {per:.1f} kg/m2"
        )
        fid = f"ln-exterior-wall-steel-studs-{wasm.tag.lower()}"
        lines.append(TakeoffLine(
            id=fid,
            element_class=ElementClass.EXTERIOR_WALL,
            quantity=round(per * wall.quantity, 1),
            unit=Unit.KG,
            confidence=Confidence.ASSUMED,
            material=STEEL,
            description=f"Steel studs and tracks ({wasm.tag}), estimated: {per:.1f} kg/m2 of wall",
            basis=Basis(
                sources=[BasisSource.DEFAULT_RULE, BasisSource.VECTOR_PATH],
                note=f"Assumed standard: {std}, over the {wall.quantity:.1f} m2 of exterior wall measured.",
            ),
            assumptions=[
                f"The drawings frame {wasm.tag} with '{steel.material}' "
                f"({steel.thickness_mm or 140:.0f} mm) but give no gauge, spacing or member; "
                f"this is a standard section, not a reading.",
                "A load-bearing wall in a heavier gauge (16 ga, 1.438 mm) would carry about 25% "
                "more steel; a 20 ga (0.836 mm) infill wall about 27% less.",
            ],
            provenance=prov(wasm, steel),
        ))
        covered["no steel stud factor"] = fid

    # ---- the ground slab, when no thickness is specified --------------------
    # Two cases, both ASSUMED and never passed off as a reading:
    # - the drawings show a slab on a foundation they call generic and leave
    #   to the end user's engineer (Atlantic): the thickness drawn on that
    #   generic detail, "as drawn";
    # - a slab-on-grade assembly is drawn but no sheet states its thickness
    #   (BC, most of QC): 100 mm, the common Part 9 slab (NBC 9.16.4.3 sets a
    #   75 mm minimum).
    spec = inputs.spec
    # A slab is already counted if the spec gave one ("ln-slab-on-grade") or
    # the slab assembly's own concrete layer stated its thickness
    # ("ln-slab-on-grade-<tag>-l<n>", e.g. SK/MB's F1 "152 mm"): the assumed
    # slab must not stack a second one on top.
    has_slab = any(
        ln.id == "ln-slab-on-grade"
        or (ln.id.startswith("ln-slab-on-grade-") and ln.material
            and "concrete" in ln.material.lower())
        for ln in built
    )
    if not has_slab and spec is not None:
        generic = getattr(spec, "generic_slab_mm", None)
        drawn_slab = inputs.slab_assembly is not None
        # Strip footings carry a slab on grade or a basement slab; without a
        # slab the ground floor would have nothing to stand on.
        on_footings = bool(getattr(spec, "strip_footings", False))
        if generic or drawn_slab or on_footings:
            t_mm = generic or STANDARD_SLAB_MM
            why = (
                f"{t_mm:.0f} mm as drawn on the generic foundation detail; the drawings "
                f"leave the foundation to the end user's engineer, so replace this with "
                f"the designed slab"
                if generic
                else (
                    f"{t_mm:.0f} mm, the common Part 9 slab-on-grade (NBC 9.16.4.3 sets a "
                    f"75 mm minimum): "
                    + (
                        f"{inputs.slab_assembly.tag} draws a slab on grade"
                        if drawn_slab
                        else "the drawings show strip footings, which carry a ground or basement slab"
                    )
                    + " but no sheet read states its thickness"
                )
            )
            asm = inputs.slab_assembly
            lines.append(TakeoffLine(
                id="ln-slab-on-grade",
                element_class=ElementClass.SLAB_ON_GRADE,
                quantity=round(fp.area_m2 * t_mm / 1000.0, 2),
                unit=Unit.M3,
                confidence=Confidence.ASSUMED,
                material="CMHC_Concrete, CIP",
                description=f"Slab on grade, {t_mm:.0f} mm over {fp.area_m2:.1f} m2 footprint (assumed)",
                basis=Basis(
                    sources=[BasisSource.DEFAULT_RULE, BasisSource.VECTOR_PATH],
                    note=f"Thickness assumed: {why}. Area is the measured footprint.",
                ),
                assumptions=[
                    f"Slab thickness {why}.",
                    "Thickenings under bearing walls and at the perimeter are not counted.",
                ],
                provenance=(
                    Provenance(page=asm.page or 0, sheet_no=asm.sheet, detail=f"{asm.tag} {asm.name}"[:80])
                    if asm is not None
                    else Provenance(page=page_of_footprint(inputs), sheet_no=inputs.footprint_sheet,
                                    detail="SLAB ON GRADE")
                ),
            ))
            covered["slab thickness not stated"] = "ln-slab-on-grade"
            covered["foundation is the end user's to design"] = "ln-slab-on-grade"

    # ---- strip footings drawn without a section ----------------------------
    has_footing = any(ln.id.startswith("ln-strip-footing") for ln in built)
    if spec is not None and not has_footing and getattr(spec, "strip_footings", False) and fp.perimeter_m:
        w, d = STANDARD_FOOTING_MM
        lines.append(TakeoffLine(
            id="ln-strip-footing",
            element_class=ElementClass.FOOTING,
            quantity=round(fp.perimeter_m * w * d / 1e6, 2),
            unit=Unit.M3,
            confidence=Confidence.ASSUMED,
            material="CMHC_Concrete, CIP",
            description=f"Strip footing {w:.0f} x {d:.0f} mm over {fp.perimeter_m:.1f} m run (assumed section)",
            basis=Basis(
                sources=[BasisSource.DEFAULT_RULE, BasisSource.VECTOR_PATH],
                note=(
                    f"The drawings show strip footings but no section; {w:.0f} x {d:.0f} mm is the "
                    f"common Part 9 footing for a two- or three-storey wood frame. Run is the "
                    f"measured footprint perimeter."
                ),
            ),
            assumptions=[
                "Footing section assumed, not read; the structural design governs.",
                "Run taken as the rectangular footprint perimeter; footings under interior "
                "bearing and party walls are not counted.",
            ],
            provenance=Provenance(
                page=page_of_footprint(inputs), sheet_no=inputs.footprint_sheet,
                detail="STRIP FOOTING",
            ),
        ))

    # ---- the foundation wall on strip footings ------------------------------
    # A strip footing sits at frost depth with a concrete wall up to the slab;
    # a footing with nothing on it cannot carry the building. No sheet states
    # the wall as a quantity, so it is estimated, ASSUMED, from what is stated.
    has_fwall = any(ln.element_class is ElementClass.FOUNDATION_WALL for ln in built)
    if spec is not None and not has_fwall and getattr(spec, "strip_footings", False) and fp.perimeter_m:
        depth = getattr(spec, "frost_depth_mm", None)
        thick = getattr(spec, "foundation_wall_mm", None)
        h_m = ((depth or STANDARD_FROST_MM) + ABOVE_GRADE_MM) / 1000.0
        t_mm = thick or STANDARD_FOUNDATION_WALL_MM
        depth_src = (
            f"the stated frost protection depth ({depth:.0f} mm)"
            if depth
            else f"a {STANDARD_FROST_MM:.0f} mm frost depth (assumed; none stated)"
        )
        thick_src = (
            f"the stated foundation wall schedule ({t_mm:.0f} mm)"
            if thick
            else f"{t_mm:.0f} mm (assumed; none stated)"
        )
        lines.append(TakeoffLine(
            id="ln-foundation-wall",
            element_class=ElementClass.FOUNDATION_WALL,
            quantity=round(fp.perimeter_m * h_m * t_mm / 1000.0, 2),
            unit=Unit.M3,
            confidence=Confidence.ASSUMED,
            material="CMHC_Concrete, CIP",
            description=(
                f"Foundation wall on strip footings, {t_mm:.0f} mm x {h_m:.2f} m over "
                f"{fp.perimeter_m:.1f} m perimeter (assumed)"
            ),
            basis=Basis(
                sources=[BasisSource.DEFAULT_RULE, BasisSource.SECTION_NOTE, BasisSource.VECTOR_PATH],
                note=(
                    f"Height is {depth_src} plus {ABOVE_GRADE_MM:.0f} mm above grade; "
                    f"thickness {thick_src}; run is the measured footprint perimeter."
                ),
            ),
            assumptions=[
                "The drawings show strip footings, which carry a concrete wall from "
                "frost depth to the slab, but state no wall height or quantity.",
                "A frost wall is assumed, not a full basement: a basement wall is about "
                "twice as tall, so if the building has a basement this understates it.",
                "Run taken as the rectangular footprint perimeter; interior bearing "
                "and party walls are not counted.",
            ],
            provenance=Provenance(
                page=page_of_footprint(inputs), sheet_no=inputs.footprint_sheet,
                detail="FOUNDATION WALL",
            ),
        ))
    return lines, covered


def page_of_footprint(inputs) -> int:
    return inputs.footprint_page if inputs.footprint_page is not None else 0


# ---- a single storey with no wall height --------------------------------------
# A one-storey ADU's sections state the floor and the top of the roof, never
# the wall plate, so its wall height is unknown and every wall line was lost.
SINGLE_STOREY_PLATE_M = 2.74  # 9 ft plate, the common single-storey wall height


class AssumedSingleStorey(StoreyHeights):
    """One storey whose wall height is an assumed standard, under a stated ridge."""

    assumed = True

    def __init__(self, floor: Level, roof_levels: list[Level], floor_assembly_mm=None):
        ridge = max(lv.elevation_m for lv in roof_levels) - floor.elevation_m
        self._h = round(min(SINGLE_STOREY_PLATE_M, ridge - 1.0), 3)
        super().__init__(
            levels=[floor, *roof_levels],
            floor_assembly_mm=floor_assembly_mm,
            sources=[],
            notes=[
                f"Single storey: the sections state the floor and the top of the roof "
                f"({ridge:.2f} m above it) but no wall plate, so the wall height is assumed "
                f"{self._h:.2f} m (a 9 ft plate, capped 1 m under the stated ridge)."
            ],
        )

    def storey_heights_m(self) -> list[float]:
        return [self._h]

    @property
    def missing(self) -> list[str]:
        return []


def single_storey_fallback(heights):
    """Heights for a one-floor set whose sections give only floor and ridge."""
    if heights is None or heights.storey_heights_m():
        return None
    floors = heights.floors
    roofs = [lv for lv in heights.levels if lv.is_roof]
    if len(floors) != 1 or not roofs:
        return None
    if max(lv.elevation_m for lv in roofs) - floors[0].elevation_m < 3.0:
        return None
    return AssumedSingleStorey(floors[0], roofs, heights.floor_assembly_mm)


def mark_assumed_heights(inputs, built) -> None:
    """Lines resting on an assumed wall height are ASSUMED, and say why."""
    if not getattr(inputs.heights, "assumed", False):
        return
    why = inputs.heights.notes[0]
    for ln in built:
        if ln.element_class in (ElementClass.EXTERIOR_WALL, ElementClass.INTERIOR_PARTITION):
            if ln.confidence is not Confidence.ASSUMED:
                ln.confidence = Confidence.ASSUMED
            if why not in ln.assumptions:
                ln.assumptions = [*ln.assumptions, why]


# ---- standard Part 9 assemblies, where the drawings' own cannot be read ------
# When a set's assemblies schedule cannot be read for an element (BC's
# exterior wall is refused as unreliable; Ontario's roof is not found; SK/MB
# reads none), the element still has its area but no layers, so its
# insulation, sheathing and gypsum went uncounted. A standard Part 9 build-up
# stands in, ASSUMED, expanded by the builder's own _assembly_lines so the
# materials and factors map exactly as for a drawn schedule. The drawn
# assembly always wins where it is read.
STANDARD_ASSEMBLIES = {
    "W": (
        "STANDARD WOOD-FRAME EXTERIOR WALL (assumed)",
        [
            ("EXTERIOR SHEATHING, OSB", 11.0, None),
            ("WOOD STUD FRAMING 38x140 @ 400", 140.0, 2),
            ("STUD CAVITY IN-FILL INSULATION (R-20)", 140.0, 1),
            ("GYPSUM BOARD", 13.0, None),
        ],
    ),
    "R": (
        "STANDARD TRUSSED ROOF WITH ATTIC INSULATION (assumed)",
        [
            ("EXTERIOR GRADE PLYWOOD ROOF SHEATHING", 16.0, None),
            ("PRE FABRICATED ROOF TRUSS", None, None),
            ("CAVITY FILL ATTIC INSULATION (R-50)", 300.0, None),
            ("GYPSUM BOARD CEILING", 13.0, None),
        ],
    ),
    "F": (
        "STANDARD WOOD-FRAMED FLOOR (assumed)",
        [
            ("T&G PLYWOOD SUBFLOOR", 19.0, None),
            ("ENGINEERED WOOD JOIST OR I-JOIST", None, None),
            ("ACOUSTIC BATT IN-FILL INSULATION", 89.0, None),
            ("GYPSUM BOARD CEILING", 13.0, None),
        ],
    ),
}


def _standard_assembly(letter: str, inputs):
    from ecarbon.extract.assemblies import Assembly, Layer

    name, rows = STANDARD_ASSEMBLIES[letter]
    layers = []
    for i, (mat, t, partner) in enumerate(rows):
        lay = Layer(index=i, material=mat, thickness_mm=t)
        if t is None:
            lay.deferred_to = "Structural"
        if partner is not None:
            lay.shares_cavity_with = partner
        layers.append(lay)
    return Assembly(
        tag=f"STD-{letter}",
        name=name,
        group="Standard (assumed)",
        group_letter=letter,
        layers=layers,
        sheet=inputs.footprint_sheet,
        page=page_of_footprint(inputs),
    )


def standard_assembly_lines(inputs, built, expand):
    """Layer lines from standard assemblies for elements whose own assembly
    could not be read. `expand` is builder._assembly_lines. Returns (lines,
    gaps, {letter: assembly used})."""
    from ecarbon.models import Gap, GapCode, GapSeverity

    fp = inputs.footprint
    lines: list[TakeoffLine] = []
    gaps: list = []
    used: dict = {}
    if fp is None:
        return lines, gaps, used
    std_note = (
        "No assembly of this element could be read from the drawings' schedule, so a "
        "standard Part 9 build-up is assumed; replace it with the drawn assembly."
    )

    wall = next((ln for ln in built if ln.id == "ln-exterior-wall"), None)
    if wall is not None and inputs.assembly_for("W") is None:
        asm = _standard_assembly("W", inputs)
        made, more = expand(
            asm, wall.quantity, ElementClass.EXTERIOR_WALL, confidence=Confidence.ASSUMED,
            area_note=f"Area is the {wall.quantity:.1f} m2 of exterior wall measured.",
            extra_assumptions=[std_note],
        )
        lines += made
        gaps += more
        used["W"] = asm

    if inputs.assembly_for("R") is None:
        asm = _standard_assembly("R", inputs)
        made, more = expand(
            asm, fp.area_m2, ElementClass.ROOF_ASSEMBLY, confidence=Confidence.ASSUMED,
            area_note=f"Area taken as the {fp.area_m2:.1f} m2 footprint.",
            extra_assumptions=[std_note],
        )
        lines += made
        gaps += more
        used["R"] = asm

    upper = max(inputs.heights.n_storeys - 1, 0) if inputs.heights else 0
    slab_tags = {t for t, a in inputs.assemblies.items() if a.is_slab_on_grade}
    if upper > 0 and inputs.assembly_for("F", exclude=slab_tags) is None:
        asm = _standard_assembly("F", inputs)
        made, more = expand(
            asm, fp.area_m2 * upper, ElementClass.FLOOR_ASSEMBLY, confidence=Confidence.ASSUMED,
            area_note=f"Area is the {fp.area_m2:.1f} m2 footprint over {upper} suspended floors.",
            extra_assumptions=[std_note],
        )
        lines += made
        gaps += more
        used["F"] = asm

    # The deferred joist/truss layers are estimated by framing_lines, not
    # reported as missing here.
    gaps = [g for g in gaps if "defers to the structural" not in g.message]
    if used:
        gaps.append(Gap(
            code=GapCode.ASSEMBLY_SCHEDULE_MISSING,
            severity=GapSeverity.WARNING,
            message=(
                "Standard Part 9 assemblies are assumed for "
                + ", ".join({"W": "the exterior wall", "R": "the roof", "F": "the floors"}[k] for k in used)
                + " because the drawings' own could not be read: "
                + "; ".join(f"{a.tag} {a.name}" for a in used.values())
                + ". Their layers are marked assumed."
            ),
            affects=[ln.id for ln in lines],
        ))
    return lines, gaps, used
