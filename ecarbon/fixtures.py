"""A realistic TakeoffResult/CarbonResult pair, so the carbon and UI work can
start before extraction produces anything.

Numbers are plausible for AB_Fourplex_01 (Edmonton, 306 m2 GFA, 2 storey,
4 unit -- from its Building Performance Report). They are NOT a real takeoff.
Anything built against this must still work when the real extractor swaps in,
which is the whole point of pinning the contract here.

    python scripts/make_fixture.py        # writes tests/fixtures/*.json
"""

from __future__ import annotations

from datetime import date

from ecarbon.models import (
    Basis,
    BasisSource,
    CarbonLine,
    CarbonResult,
    Confidence,
    Contribution,
    Discipline,
    ElementClass,
    FactorRef,
    Gap,
    GapCode,
    GapSeverity,
    ProjectFacts,
    Provenance,
    SheetInfo,
    SheetType,
    TakeoffLine,
    TakeoffResult,
    Toolchain,
    Unit,
)

# Concrete factors are the real published values from the Kootenay Material
# Impact Guide (docs/element_priority.md); they make the swap demo honest.
FACTOR_CONCRETE_GU = FactorRef(
    factor_id="koot-concrete-gu-30",
    name="Concrete, Portland Type GU, 30 MPa",
    source="Kootenay Construction Material Impact Guide (2026)",
    source_id="concrete/portland-gu/30mpa",
    declared_unit="m3",
    gwp_value=276.0,
    modules=["A1", "A2", "A3"],
    geography="CA-BC",
    data_type="industry_avg",
    valid_from=date(2026, 2, 20),
    uncertainty_pct=15.0,
    attribution="Builders for Climate Action / City of Nelson, funded by FortisBC",
    density_kg_m3=2400.0,
)

FACTOR_CONCRETE_GUL40 = FactorRef(
    factor_id="koot-concrete-gul40-25",
    name="Concrete, Portland-Limestone GUL + 40% fly ash, 25 MPa",
    source="Kootenay Construction Material Impact Guide (2026)",
    source_id="concrete/gul-40-flyash/25mpa",
    declared_unit="m3",
    gwp_value=175.0,
    modules=["A1", "A2", "A3"],
    geography="CA-BC",
    data_type="industry_avg",
    valid_from=date(2026, 2, 20),
    uncertainty_pct=15.0,
    attribution="Builders for Climate Action / City of Nelson, funded by FortisBC",
    density_kg_m3=2400.0,
)

FACTOR_BATT = FactorRef(
    factor_id="koot-cavity-insul-fibreglass-r13",
    name="Cavity insulation, fibreglass batt, R-13",
    source="Kootenay Construction Material Impact Guide (2026)",
    declared_unit="100m2",
    gwp_value=430.0,
    modules=["A1", "A2", "A3"],
    geography="CA-BC",
    data_type="industry_avg",
    uncertainty_pct=20.0,
    attribution="Builders for Climate Action / City of Nelson",
)


def example_takeoff() -> TakeoffResult:
    return TakeoffResult(
        project=ProjectFacts(
            name="AB_Fourplex_01",
            jurisdiction="Edmonton, AB (NBC(AE) 2020, CZ 7A)",
            gfa_m2=306.0,
            gfa_basis="gross",
            storeys=2,
            units=4,
            known_product_specs={},
        ),
        source_file="AB_Fourplex_01_Drawings.pdf",
        extracted_at=date(2026, 10, 23),
        duration_s=41.2,
        sheets=[
            SheetInfo(
                page=2,
                sheet_no="A003",
                title="ASSEMBLIES SCHEDULE",
                discipline=Discipline.ARCHITECTURAL,
                sheet_type=SheetType.ASSEMBLY_SCHEDULE,
                toolchain=Toolchain.REVIT_TAGGED,
                width_in=36.0,
                height_in=24.0,
                classified_by=BasisSource.REVIT_METADATA,
                n_paths=9_812,
                n_text=1_204,
            ),
            SheetInfo(
                page=10,
                sheet_no="A101",
                title="MAIN FLOOR PLAN - ACCESSIBLE READY",
                discipline=Discipline.ARCHITECTURAL,
                sheet_type=SheetType.FLOOR_PLAN,
                toolchain=Toolchain.REVIT_TAGGED,
                width_in=36.0,
                height_in=24.0,
                scale=8.4667,
                scale_source=BasisSource.DIM_TEXT_METRIC,
                classified_by=BasisSource.REVIT_METADATA,
                n_paths=22_140,
                n_text=419,
            ),
            SheetInfo(
                page=20,
                sheet_no="S201",
                title="FOUNDATION PLAN",
                discipline=Discipline.STRUCTURAL,
                sheet_type=SheetType.FOUNDATION_PLAN,
                toolchain=Toolchain.FLATTENED,
                width_in=36.0,
                height_in=24.0,
                scale=8.4667,
                scale_source=BasisSource.DIM_TEXT_IMPERIAL,
                n_paths=18_003,
                n_text=362,
            ),
        ],
        gaps=[
            Gap(
                code=GapCode.SECTION_DETAIL_MISSING,
                severity=GapSeverity.WARNING,
                message="Assembly 'P3' is tagged on A300 but has no row in the A003 "
                "assemblies schedule; its layer build-up is unknown.",
                page=16,
                sheet_no="A300",
                affects=["ln-exterior-wall-p3"],
            ),
            Gap(
                code=GapCode.PROJECT_FACT_REQUIRED,
                severity=GapSeverity.INFO,
                message="Conditioned floor area basis was not stated on the drawings; "
                "gross floor area was supplied by the user and is used for intensity.",
            ),
        ],
        lines=[
            TakeoffLine(
                id="ln-slab-main",
                element_class=ElementClass.SLAB_ON_GRADE,
                quantity=30.6,
                unit=Unit.M3,
                confidence=Confidence.MEASURED,
                material="CMHC_Concrete",
                assembly_tag="N1",
                description="Slab on grade, 100 mm, main floor footprint",
                basis=Basis(
                    sources=[
                        BasisSource.VECTOR_PATH,
                        BasisSource.DIM_TEXT_METRIC,
                        BasisSource.DIM_TEXT_IMPERIAL,
                    ],
                    agreement=0.012,
                    note="Footprint polygon area agreed with both dimension strings to 1.2%.",
                ),
                provenance=Provenance(
                    page=20, sheet_no="S201", detail="FOUNDATION PLAN",
                    bbox=(1180.0, 420.0, 2010.0, 1150.0),
                ),
            ),
            TakeoffLine(
                id="ln-exterior-wall-w2",
                element_class=ElementClass.EXTERIOR_WALL,
                quantity=271.4,
                unit=Unit.M2,
                confidence=Confidence.MEASURED,
                material="CMHC_Wood Framing",
                assembly_tag="W2",
                description="W2 rated exterior envelope wall, gross area less openings",
                basis=Basis(
                    sources=[BasisSource.VECTOR_PATH, BasisSource.SECTION_NOTE, BasisSource.HOT2000],
                    agreement=0.043,
                    note="Perimeter x storey height from A300 datums; HOT2000 envelope "
                    "area within 4.3%.",
                ),
                provenance=Provenance(
                    page=10, sheet_no="A101", detail="1/A101",
                    bbox=(640.0, 300.0, 2180.0, 1320.0),
                ),
            ),
            TakeoffLine(
                id="ln-exterior-wall-p3",
                element_class=ElementClass.EXTERIOR_WALL,
                quantity=18.0,
                unit=Unit.M2,
                confidence=Confidence.ASSUMED,
                assembly_tag="P3",
                description="P3 wall area; build-up unknown",
                assumptions=[
                    "P3 has no row in the A003 assemblies schedule; assumed identical "
                    "to P2 (2x6 stud) pending a readable detail.",
                ],
                basis=Basis(
                    sources=[BasisSource.VECTOR_PATH, BasisSource.DEFAULT_RULE],
                    note="Area measured; material composition defaulted.",
                ),
                provenance=Provenance(page=16, sheet_no="A300", detail="2/A300"),
            ),
            TakeoffLine(
                id="ln-cavity-insulation-w2",
                element_class=ElementClass.INSULATION,
                quantity=271.4,
                unit=Unit.M2,
                confidence=Confidence.INFERRED,
                material="CMHC_Batt Insulation",
                assembly_tag="W2",
                description="R-22 batt in W2 stud cavity, from the W2 layer build-up",
                basis=Basis(
                    sources=[BasisSource.SCHEDULE, BasisSource.VECTOR_PATH],
                    note="Area inherited from ln-exterior-wall-w2; layer from A003.",
                ),
                provenance=Provenance(page=2, sheet_no="A003", detail="W2 row"),
            ),
        ],
    )


def example_carbon(takeoff: TakeoffResult | None = None) -> CarbonResult:
    t = takeoff or example_takeoff()
    slab = t.line("ln-slab-main")
    wall = t.line("ln-exterior-wall-w2")
    insul = t.line("ln-cavity-insulation-w2")

    slab_kg = slab.effective_quantity * FACTOR_CONCRETE_GU.gwp_value
    insul_kg = insul.effective_quantity / 100.0 * FACTOR_BATT.gwp_value

    lines = [
        CarbonLine(
            line_id=slab.id,
            quantity=slab.effective_quantity,
            unit=slab.unit,
            factor=FACTOR_CONCRETE_GU,
            kg_co2e=round(slab_kg, 1),
            conversion_note="m3 x kgCO2e/m3, declared unit matches directly.",
        ),
        CarbonLine(
            line_id=insul.id,
            quantity=insul.effective_quantity,
            unit=insul.unit,
            factor=FACTOR_BATT,
            kg_co2e=round(insul_kg, 1),
            conversion_note="Declared unit is 100m2; quantity divided by 100.",
        ),
        CarbonLine(
            line_id=wall.id,
            quantity=wall.effective_quantity,
            unit=wall.unit,
            factor=None,
            missing_reason="No A1-A3 factor yet mapped for CMHC_Wood Framing at the "
            "assembly level; the W2 build-up must be expanded into its layers first. "
            "This line is reported and excluded from the total.",
        ),
    ]

    total = sum(ln.kg_co2e or 0.0 for ln in lines if ln.is_counted)
    return CarbonResult(
        takeoff_source=t.source_file,
        modules=["A1", "A2", "A3"],
        total_kg_co2e=round(total, 1),
        intensity_kg_co2e_per_m2=round(total / t.project.gfa_m2, 1) if t.project.gfa_m2 else None,
        intensity_basis="gross",
        lines=lines,
        by_assembly=[
            Contribution(key="N1 foundation", kg_co2e=round(slab_kg, 1),
                         pct_of_total=round(100 * slab_kg / total, 1)),
            Contribution(key="W2 exterior envelope", kg_co2e=round(insul_kg, 1),
                         pct_of_total=round(100 * insul_kg / total, 1)),
        ],
        by_material_category=[
            Contribution(key="concrete", kg_co2e=round(slab_kg, 1),
                         pct_of_total=round(100 * slab_kg / total, 1)),
            Contribution(key="insulation", kg_co2e=round(insul_kg, 1),
                         pct_of_total=round(100 * insul_kg / total, 1)),
        ],
        uncounted_lines=[wall.id],
        range_low_kg_co2e=round(total * 0.85, 1),
        range_high_kg_co2e=round(total * 1.15, 1),
    )
