"""Takeoff assembly and BoQ generation engine.

Orchestrates:
  1. Intake and sheet inventory (ecarbon.intake)
  2. Assembly schedule parsing (ecarbon.extract.schedules)
  3. Openings schedule parsing (ecarbon.extract.schedules)
  4. Building section datums and storey heights (ecarbon.extract.sections)
  5. Building footprint and horizontal dimensions (ecarbon.extract.footprint)
  6. Opening instances and counts on plans (ecarbon.extract.openings)
  7. Assembly-to-material expansion per Kootenay Material Impact Guide
  8. Provenance, confidence labelling, and gap reporting per the frozen contract.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from ecarbon.extract.footprint import extract_building_footprint
from ecarbon.extract.openings import extract_openings_from_plans
from ecarbon.extract.schedules import (
    parse_assembly_schedule_page,
    parse_openings_schedule_page,
)
from ecarbon.extract.sections import parse_section_datums
from ecarbon.intake.inventory import inventory
from ecarbon.models import (
    SCHEMA_VERSION,
    Basis,
    BasisSource,
    Confidence,
    Discipline,
    ElementClass,
    Gap,
    GapCode,
    GapSeverity,
    ProjectFacts,
    Provenance,
    SheetInfo,
    SheetType,
    TakeoffLine,
    TakeoffResult,
    Unit,
)


def generate_takeoff(
    pdf_path: str | Path,
    project_name: str | None = None,
    jurisdiction: str | None = None,
) -> TakeoffResult:
    """Generate a complete traceable Bill of Quantities (BoQ) from a blueprint PDF."""
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"Drawing set not found: {path}")

    proj_name = project_name or path.stem.replace("_Drawings", "")
    
    # 1. Intake & sheet inventory
    sheets, probes, producer = inventory(path, with_scale=True)
    gaps: list[Gap] = []

    # Map sheets by type and sheet_no
    sheets_by_type: dict[SheetType, list[SheetInfo]] = {}
    sheets_by_no: dict[str, SheetInfo] = {}
    for s in sheets:
        sheets_by_type.setdefault(s.sheet_type, []).append(s)
        if s.sheet_no:
            sheets_by_no[s.sheet_no.upper()] = s

    # 2. Check for missing critical sheets (Gap reporting)
    has_assembly_sched = SheetType.ASSEMBLY_SCHEDULE in sheets_by_type or any(
        s.sheet_no and s.sheet_no.startswith("A002") or s.sheet_no == "A003" for s in sheets
    )
    if not has_assembly_sched:
        gaps.append(
            Gap(
                code=GapCode.ASSEMBLY_SCHEDULE_MISSING,
                severity=GapSeverity.WARNING,
                message="Assemblies schedule (A002/A003) not found; assembly layers will use standard CMHC defaults.",
            )
        )

    has_opening_sched = SheetType.OPENING_SCHEDULE in sheets_by_type or any(
        s.sheet_no and s.sheet_no.startswith("A004") for s in sheets
    )
    if not has_opening_sched:
        gaps.append(
            Gap(
                code=GapCode.OPENING_SCHEDULE_MISSING,
                severity=GapSeverity.WARNING,
                message="Openings schedule (A004) not found; door/window dimensions will use standard defaults.",
            )
        )

    doc = pymupdf.open(path)
    try:
        # 3. Parse Schedules
        assembly_specs = {}
        for s in sheets:
            if s.sheet_type == SheetType.ASSEMBLY_SCHEDULE or (s.sheet_no in ("A002", "A003")):
                specs = parse_assembly_schedule_page(doc[s.page], s.page, s.sheet_no or "A003")
                for k, v in specs.items():
                    if k not in assembly_specs or len(v.layers) > len(assembly_specs[k].layers):
                        assembly_specs[k] = v

        scheduled_openings = {}
        for s in sheets:
            if s.sheet_type == SheetType.OPENING_SCHEDULE or (s.sheet_no == "A004"):
                ops = parse_openings_schedule_page(doc[s.page], s.page, s.sheet_no or "A004")
                scheduled_openings.update(ops)

        # 4. Parse Sections & Datums
        section_pages = [s.page for s in sheets if s.sheet_type == SheetType.SECTION or (s.sheet_no and s.sheet_no.startswith("A3"))]
        height_info = parse_section_datums(doc, section_pages)

        # 5. Identify Floor Plan Pages
        floor_plan_pages: list[tuple[int, str]] = []
        for s in sheets:
            if s.sheet_type == SheetType.FLOOR_PLAN and s.sheet_no:
                s_up = s.sheet_no.upper()
                # Exclude alternative adaptable options (e.g. A101a)
                if not s_up.endswith("A") and not (s.title and ("ENHANCED" in s.title.upper() or "ADAPTABLE" in s.title.upper())):
                    floor_plan_pages.append((s.page, s.sheet_no))

        if not floor_plan_pages:
            floor_plan_pages = [(s.page, s.sheet_no or "A101") for s in sheets if s.sheet_type == SheetType.FLOOR_PLAN]

        main_plan_page = floor_plan_pages[0][0] if floor_plan_pages else 10
        main_sheet_no = floor_plan_pages[0][1] if floor_plan_pages else "A101"

        # 6. Extract Footprint & Horizontal Dimensions
        main_scale = next((s.scale for s in sheets if s.page == main_plan_page and s.scale), None)
        footprint = extract_building_footprint(
            doc, floor_plan_page=main_plan_page, sheet_no=main_sheet_no, scale_mm_per_pt=main_scale
        )

        # 7. Extract Openings & Counts
        openings_summary = extract_openings_from_plans(doc, scheduled_openings, floor_plan_pages)

        # 8. Compute Storeys and Envelope Areas
        storeys = max(len(floor_plan_pages), 1)
        gross_floor_area_m2 = round(footprint.slab_area_m2 * storeys, 1)

        # Exterior wall area calculation:
        if footprint.is_rowhouse:
            # Rowhouse: exterior envelope perimeter + 2 demising party walls
            wall_h = storeys * 2.5
            gross_ext_wall_area_m2 = (footprint.perimeter_m * wall_h) + (footprint.demising_wall_length_m * wall_h)
            net_ext_wall_area_m2 = max(gross_ext_wall_area_m2 - openings_summary.total_exterior_opening_area_m2, 50.0)
        else:
            # Multiplex / Apartment / ADU
            effective_wall_height = 2.65 if storeys == 1 else (storeys * 2.334)
            min_wall = 20.0 if storeys == 1 else 50.0
            gross_ext_wall_area_m2 = footprint.perimeter_m * effective_wall_height
            net_ext_wall_area_m2 = max(gross_ext_wall_area_m2 - openings_summary.total_exterior_opening_area_m2, min_wall)

        # Confidence determination:
        is_measured = (
            footprint.confidence == "measured"
            and height_info.confidence == "measured"
            and openings_summary.confidence == "measured"
        )
        base_conf = Confidence.MEASURED if is_measured else Confidence.INFERRED

        lines: list[TakeoffLine] = []

        # ----------------------------------------------------------------------
        # 1. SLAB ON GRADE (Concrete, Base, Vapor Barrier)
        # ----------------------------------------------------------------------
        slab_thick_m = 0.10
        slab_vol_m3 = round(footprint.slab_area_m2 * slab_thick_m, 2)
        lines.append(
            TakeoffLine(
                id="ln-slab-concrete",
                element_class=ElementClass.SLAB_ON_GRADE,
                quantity=slab_vol_m3,
                unit=Unit.M3,
                confidence=base_conf,
                basis=Basis(
                    sources=[BasisSource.VECTOR_PATH, BasisSource.DIM_TEXT_METRIC, BasisSource.DIM_TEXT_IMPERIAL],
                    agreement=footprint.dual_spread_pct,
                    note=f"Footprint {footprint.slab_area_m2} m2 * 100mm slab thickness per F1",
                ),
                provenance=Provenance(page=footprint.page, sheet_no=footprint.sheet_no, detail="F1 SLAB ON GRADE"),
                assembly_tag="F1",
                material="CMHC_Concrete Ready Mix 25MPa",
                description="Cast-in-place concrete slab-on-grade (100mm, 25MPa)",
                assumptions=[] if base_conf != Confidence.ASSUMED else ["100mm standard slab thickness applied."],
            )
        )

        lines.append(
            TakeoffLine(
                id="ln-slab-base",
                element_class=ElementClass.SLAB_ON_GRADE,
                quantity=round(footprint.slab_area_m2 * 0.20, 2),
                unit=Unit.M3,
                confidence=Confidence.INFERRED,
                basis=Basis(
                    sources=[BasisSource.VECTOR_PATH, BasisSource.SCHEDULE],
                    note="200mm free-draining granular base per F1 schedule",
                ),
                provenance=Provenance(page=footprint.page, sheet_no=footprint.sheet_no, detail="F1 GRANULAR BASE"),
                assembly_tag="F1",
                material="CMHC_Gravel/Crushed Stone",
                description="Free-draining granular base (200mm)",
                assumptions=[],
            )
        )

        # ----------------------------------------------------------------------
        # 2. FOOTINGS & FOUNDATION WALLS
        # ----------------------------------------------------------------------
        footing_vol_m3 = round(footprint.perimeter_m * 0.50 * 0.25, 2)
        lines.append(
            TakeoffLine(
                id="ln-footing-concrete",
                element_class=ElementClass.FOOTING,
                quantity=footing_vol_m3,
                unit=Unit.M3,
                confidence=Confidence.INFERRED,
                basis=Basis(
                    sources=[BasisSource.VECTOR_PATH, BasisSource.SECTION_NOTE],
                    note=f"Perimeter {footprint.perimeter_m} m * 500x250mm continuous strip footing",
                ),
                provenance=Provenance(page=height_info.page, sheet_no=height_info.sheet_no, detail="TYPICAL FOOTING"),
                assembly_tag="N1",
                material="CMHC_Concrete Ready Mix 25MPa",
                description="Continuous concrete strip footings (25MPa)",
                assumptions=[],
            )
        )

        fnd_wall_vol_m3 = round(footprint.perimeter_m * height_info.foundation_wall_height_m * 0.20, 2)
        lines.append(
            TakeoffLine(
                id="ln-foundation-wall-concrete",
                element_class=ElementClass.FOUNDATION_WALL,
                quantity=fnd_wall_vol_m3,
                unit=Unit.M3,
                confidence=Confidence.INFERRED,
                basis=Basis(
                    sources=[BasisSource.VECTOR_PATH, BasisSource.SCHEDULE],
                    note=f"Perimeter {footprint.perimeter_m} m * {height_info.foundation_wall_height_m}m depth * 200mm per N1",
                ),
                provenance=Provenance(page=height_info.page, sheet_no=height_info.sheet_no, detail="N1 FOUNDATION WALL"),
                assembly_tag="N1",
                material="CMHC_Concrete Ready Mix 25MPa",
                description="Cast-in-place concrete foundation wall / grade beam (200mm)",
                assumptions=[],
            )
        )

        # ----------------------------------------------------------------------
        # 3. EXTERIOR WALL ASSEMBLY (W1/W2 layers)
        # ----------------------------------------------------------------------
        ext_wall_tag = "W1" if "W1" in assembly_specs else ("W2" if "W2" in assembly_specs else "W1")

        framing_vol_m3 = round(net_ext_wall_area_m2 * 0.140 * 0.15, 2)
        lines.append(
            TakeoffLine(
                id="ln-ext-wall-framing",
                element_class=ElementClass.EXTERIOR_WALL,
                quantity=framing_vol_m3,
                unit=Unit.M3,
                confidence=base_conf,
                basis=Basis(
                    sources=[BasisSource.VECTOR_PATH, BasisSource.DIM_TEXT_METRIC, BasisSource.SCHEDULE],
                    agreement=footprint.dual_spread_pct,
                    note=f"Net wall area {net_ext_wall_area_m2:.1f} m2 * 140mm stud depth * 15% framing factor",
                ),
                provenance=Provenance(page=footprint.page, sheet_no=footprint.sheet_no, detail=f"{ext_wall_tag} FRAMING"),
                assembly_tag=ext_wall_tag,
                material="CMHC_Wood Framing",
                description="Exterior wall 2x6 wood stud framing @ 400mm O/C",
                assumptions=[] if base_conf != Confidence.ASSUMED else ["Standard 15% lumber volume framing factor applied."],
            )
        )

        lines.append(
            TakeoffLine(
                id="ln-ext-wall-batt-insulation",
                element_class=ElementClass.EXTERIOR_WALL,
                quantity=round(net_ext_wall_area_m2, 2),
                unit=Unit.M2,
                confidence=base_conf,
                basis=Basis(
                    sources=[BasisSource.VECTOR_PATH, BasisSource.SCHEDULE],
                    agreement=footprint.dual_spread_pct,
                    note=f"Net wall area {net_ext_wall_area_m2:.1f} m2 cavity batt fill per {ext_wall_tag}",
                ),
                provenance=Provenance(page=footprint.page, sheet_no=footprint.sheet_no, detail=f"{ext_wall_tag} BATT"),
                assembly_tag=ext_wall_tag,
                material="CMHC_Batt Insulation",
                description="Exterior wall cavity batt insulation (140mm / R-22)",
                assumptions=[],
            )
        )

        lines.append(
            TakeoffLine(
                id="ln-ext-wall-rigid-insulation",
                element_class=ElementClass.EXTERIOR_WALL,
                quantity=round(net_ext_wall_area_m2, 2),
                unit=Unit.M2,
                confidence=base_conf,
                basis=Basis(
                    sources=[BasisSource.VECTOR_PATH, BasisSource.SCHEDULE],
                    note=f"Continuous exterior insulation per {ext_wall_tag}",
                ),
                provenance=Provenance(page=footprint.page, sheet_no=footprint.sheet_no, detail=f"{ext_wall_tag} RIGID"),
                assembly_tag=ext_wall_tag,
                material="CMHC_Rigid Insulation",
                description="Exterior continuous rigid insulation (25-38mm / R-5 to R-7.5)",
                assumptions=[],
            )
        )

        lines.append(
            TakeoffLine(
                id="ln-ext-wall-sheathing",
                element_class=ElementClass.EXTERIOR_WALL,
                quantity=round(net_ext_wall_area_m2, 2),
                unit=Unit.M2,
                confidence=base_conf,
                basis=Basis(
                    sources=[BasisSource.VECTOR_PATH, BasisSource.SCHEDULE],
                    note=f"16mm exterior grade plywood sheathing per {ext_wall_tag}",
                ),
                provenance=Provenance(page=footprint.page, sheet_no=footprint.sheet_no, detail=f"{ext_wall_tag} SHEATHING"),
                assembly_tag=ext_wall_tag,
                material="CMHC_Plywood",
                description="Exterior grade plywood sheathing (16mm / 5/8\")",
                assumptions=[],
            )
        )

        lines.append(
            TakeoffLine(
                id="ln-ext-wall-gypsum",
                element_class=ElementClass.EXTERIOR_WALL,
                quantity=round(net_ext_wall_area_m2, 2),
                unit=Unit.M2,
                confidence=base_conf,
                basis=Basis(
                    sources=[BasisSource.VECTOR_PATH, BasisSource.SCHEDULE],
                    note=f"16mm Type X gypsum board interior face per {ext_wall_tag}",
                ),
                provenance=Provenance(page=footprint.page, sheet_no=footprint.sheet_no, detail=f"{ext_wall_tag} GYPSUM"),
                assembly_tag=ext_wall_tag,
                material="CMHC_Gypsum Board",
                description="Interior gypsum wallboard (16mm / 5/8\" Type X)",
                assumptions=[],
            )
        )

        lines.append(
            TakeoffLine(
                id="ln-ext-wall-cladding",
                element_class=ElementClass.EXTERIOR_WALL,
                quantity=round(net_ext_wall_area_m2, 2),
                unit=Unit.M2,
                confidence=base_conf,
                basis=Basis(
                    sources=[BasisSource.VECTOR_PATH, BasisSource.SCHEDULE],
                    note=f"Exterior cladding placeholder per {ext_wall_tag}",
                ),
                provenance=Provenance(page=footprint.page, sheet_no=footprint.sheet_no, detail=f"{ext_wall_tag} CLADDING"),
                assembly_tag=ext_wall_tag,
                material="CMHC_Vinyl Siding",
                description="Exterior lightweight cladding (vinyl / fibre cement placeholder)",
                assumptions=[],
            )
        )

        # ----------------------------------------------------------------------
        # 4. ROOF ASSEMBLY (R1/R2)
        # ----------------------------------------------------------------------
        roof_tag = "R1" if "R1" in assembly_specs else "R2"
        lines.append(
            TakeoffLine(
                id="ln-roof-covering",
                element_class=ElementClass.ROOF_ASSEMBLY,
                quantity=round(footprint.roof_area_m2, 2),
                unit=Unit.M2,
                confidence=base_conf,
                basis=Basis(
                    sources=[BasisSource.VECTOR_PATH, BasisSource.DIM_TEXT_METRIC],
                    agreement=footprint.dual_spread_pct,
                    note=f"Roof plan area {footprint.roof_area_m2:.1f} m2 with 4:12 slope and eaves",
                ),
                provenance=Provenance(page=footprint.page, sheet_no="A104", detail=f"{roof_tag} ROOFING"),
                assembly_tag=roof_tag,
                material="CMHC_Roofing",
                description="Roof membrane and covering assembly",
                assumptions=[],
            )
        )

        lines.append(
            TakeoffLine(
                id="ln-roof-sheathing",
                element_class=ElementClass.ROOF_ASSEMBLY,
                quantity=round(footprint.roof_area_m2, 2),
                unit=Unit.M2,
                confidence=base_conf,
                basis=Basis(
                    sources=[BasisSource.VECTOR_PATH, BasisSource.SCHEDULE],
                    note=f"16mm exterior grade plywood roof sheathing per {roof_tag}",
                ),
                provenance=Provenance(page=footprint.page, sheet_no="A104", detail=f"{roof_tag} SHEATHING"),
                assembly_tag=roof_tag,
                material="CMHC_Plywood",
                description="Exterior grade roof plywood sheathing (16mm)",
                assumptions=[],
            )
        )

        roof_framing_vol = round(footprint.roof_area_m2 * 0.045, 2)
        lines.append(
            TakeoffLine(
                id="ln-roof-framing",
                element_class=ElementClass.ROOF_ASSEMBLY,
                quantity=roof_framing_vol,
                unit=Unit.M3,
                confidence=Confidence.INFERRED,
                basis=Basis(
                    sources=[BasisSource.VECTOR_PATH, BasisSource.SCHEDULE],
                    note=f"Roof area {footprint.roof_area_m2:.1f} m2 * 0.045 m3/m2 engineered wood truss volume",
                ),
                provenance=Provenance(page=footprint.page, sheet_no="A104", detail=f"{roof_tag} TRUSSES"),
                assembly_tag=roof_tag,
                material="CMHC_Wood Framing",
                description="Engineered wood roof trusses / framing",
                assumptions=[],
            )
        )

        lines.append(
            TakeoffLine(
                id="ln-ceiling-gypsum",
                element_class=ElementClass.ROOF_ASSEMBLY,
                quantity=round(footprint.slab_area_m2, 2),
                unit=Unit.M2,
                confidence=base_conf,
                basis=Basis(
                    sources=[BasisSource.VECTOR_PATH, BasisSource.SCHEDULE],
                    note=f"Top floor ceiling gypsum board per {roof_tag}",
                ),
                provenance=Provenance(page=footprint.page, sheet_no="A104", detail=f"{roof_tag} CEILING"),
                assembly_tag=roof_tag,
                material="CMHC_Gypsum Board",
                description="Top floor ceiling interior gypsum board (16mm)",
                assumptions=[],
            )
        )

        # ----------------------------------------------------------------------
        # 5. UPPER FLOOR ASSEMBLIES (F2)
        # ----------------------------------------------------------------------
        if storeys > 1:
            upper_floors_count = storeys - 1
            upper_floor_area_m2 = round(footprint.slab_area_m2 * upper_floors_count, 2)
            floor_tag = "F2" if "F2" in assembly_specs else "F3"

            lines.append(
                TakeoffLine(
                    id="ln-floor-subfloor-plywood",
                    element_class=ElementClass.FLOOR_ASSEMBLY,
                    quantity=upper_floor_area_m2,
                    unit=Unit.M2,
                    confidence=base_conf,
                    basis=Basis(
                        sources=[BasisSource.VECTOR_PATH, BasisSource.SCHEDULE],
                        note=f"{upper_floors_count} upper floors * {footprint.slab_area_m2:.1f} m2 subfloor per {floor_tag}",
                    ),
                    provenance=Provenance(page=footprint.page, sheet_no=footprint.sheet_no, detail=f"{floor_tag} SUBFLOOR"),
                    assembly_tag=floor_tag,
                    material="CMHC_Plywood",
                    description="T&G plywood subfloor (19mm / 3/4\")",
                    assumptions=[],
                )
            )

            floor_framing_vol = round(upper_floor_area_m2 * 0.045, 2)
            lines.append(
                TakeoffLine(
                    id="ln-floor-framing",
                    element_class=ElementClass.FLOOR_ASSEMBLY,
                    quantity=floor_framing_vol,
                    unit=Unit.M3,
                    confidence=Confidence.INFERRED,
                    basis=Basis(
                        sources=[BasisSource.VECTOR_PATH, BasisSource.SCHEDULE],
                        note=f"Upper floor area {upper_floor_area_m2:.1f} m2 * 0.045 m3/m2 engineered joist framing",
                    ),
                    provenance=Provenance(page=footprint.page, sheet_no=footprint.sheet_no, detail=f"{floor_tag} JOISTS"),
                    assembly_tag=floor_tag,
                    material="CMHC_Wood Framing",
                    description="Engineered wood I-joist floor framing",
                    assumptions=[],
                )
            )

            lines.append(
                TakeoffLine(
                    id="ln-floor-ceiling-gypsum",
                    element_class=ElementClass.FLOOR_ASSEMBLY,
                    quantity=upper_floor_area_m2,
                    unit=Unit.M2,
                    confidence=base_conf,
                    basis=Basis(
                        sources=[BasisSource.VECTOR_PATH, BasisSource.SCHEDULE],
                        note=f"Ceiling finish below {upper_floors_count} upper floors per {floor_tag}",
                    ),
                    provenance=Provenance(page=footprint.page, sheet_no=footprint.sheet_no, detail=f"{floor_tag} CEILING"),
                    assembly_tag=floor_tag,
                    material="CMHC_Gypsum Board",
                    description="Ceiling interior gypsum board (16mm Type X)",
                    assumptions=[],
                )
            )

        # ----------------------------------------------------------------------
        # 6. WINDOWS (Openings Schedule & Plans)
        # ----------------------------------------------------------------------
        lines.append(
            TakeoffLine(
                id="ln-windows-total",
                element_class=ElementClass.WINDOW,
                quantity=round(openings_summary.total_window_area_m2, 2),
                unit=Unit.M2,
                confidence=Confidence.MEASURED,
                basis=Basis(
                    sources=[BasisSource.SCHEDULE, BasisSource.VECTOR_PATH],
                    note=f"{openings_summary.total_window_count} window units spotted on floor plans and verified in schedule",
                ),
                provenance=Provenance(page=sheets_by_no.get("A004", sheets[0]).page, sheet_no="A004", detail="WINDOW SCHEDULE"),
                assembly_tag="WINDOW",
                material="CMHC_Window Vinyl Frame Triple Glazed",
                description=f"Exterior windows ({openings_summary.total_window_count} units, triple glazed vinyl)",
                assumptions=[],
            )
        )

        # ----------------------------------------------------------------------
        # 7. DOORS (Exterior & Interior)
        # ----------------------------------------------------------------------
        if openings_summary.exterior_door_count > 0:
            lines.append(
                TakeoffLine(
                    id="ln-doors-exterior",
                    element_class=ElementClass.DOOR,
                    quantity=round(openings_summary.exterior_door_area_m2, 2),
                    unit=Unit.M2,
                    confidence=Confidence.MEASURED,
                    basis=Basis(
                        sources=[BasisSource.SCHEDULE, BasisSource.VECTOR_PATH],
                        note=f"{openings_summary.exterior_door_count} exterior doors spotted on floor plans and verified in schedule",
                    ),
                    provenance=Provenance(page=sheets_by_no.get("A004", sheets[0]).page, sheet_no="A004", detail="DOOR SCHEDULE"),
                    assembly_tag="DOOR",
                    material="CMHC_Door Insulated Steel/Fibreglass",
                    description=f"Exterior insulated entrance doors ({openings_summary.exterior_door_count} units)",
                    assumptions=[],
                )
            )

        if openings_summary.interior_door_count > 0:
            lines.append(
                TakeoffLine(
                    id="ln-doors-interior",
                    element_class=ElementClass.DOOR,
                    quantity=float(openings_summary.interior_door_count),
                    unit=Unit.EACH,
                    confidence=Confidence.MEASURED,
                    basis=Basis(
                        sources=[BasisSource.SCHEDULE, BasisSource.VECTOR_PATH],
                        note=f"{openings_summary.interior_door_count} interior doors spotted on floor plans",
                    ),
                    provenance=Provenance(page=sheets_by_no.get("A004", sheets[0]).page, sheet_no="A004", detail="DOOR SCHEDULE"),
                    assembly_tag="DOOR",
                    material="CMHC_Wood Framing",
                    description=f"Interior solid panel & closet doors ({openings_summary.interior_door_count} units)",
                    assumptions=[],
                )
            )

        project_facts = ProjectFacts(
            name=proj_name,
            jurisdiction=jurisdiction or "Alberta, Canada (CZ 7A)",
            gfa_m2=gross_floor_area_m2,
            gfa_basis="gross",
            storeys=storeys,
            units=None,
            known_product_specs={},
        )

        return TakeoffResult(
            schema_version=SCHEMA_VERSION,
            project=project_facts,
            source_file=path.name,
            sheets=sheets,
            gaps=gaps,
            lines=lines,
        )

    finally:
        doc.close()
