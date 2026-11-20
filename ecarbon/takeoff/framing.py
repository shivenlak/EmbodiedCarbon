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


def framing_lines(inputs, built=()) -> tuple[list[TakeoffLine], dict[str, str]]:
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
    fasm = inputs.assembly_for("F", exclude=slab_tags)
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
    rasm = inputs.assembly_for("R")
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
    return lines, covered
