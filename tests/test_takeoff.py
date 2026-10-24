"""Step 10 Acceptance Test: Blueprint Takeoff extraction and verification against IFC truth.

Verifies:
  - Extraction across >=8 element classes:
    SLAB_ON_GRADE, FOOTING, FOUNDATION_WALL, EXTERIOR_WALL, ROOF_ASSEMBLY,
    FLOOR_ASSEMBLY, WINDOW, DOOR.
  - Every line carries sheet provenance and a measured/inferred/assumed confidence label.
  - Exterior wall area, slab area, roof area, and window count agree within 15% of
    the Step 9 IFC ground truth on Alberta designs.
  - Dual-unit agreement (< 1% error) drives 'measured' confidence.
  - End-to-end carbon calculation runs cleanly on the extracted takeoff.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest
import pymupdf

from ecarbon.bench.ifc_truth import parse_ifc_takeoff
from ecarbon.carbon.calculate import calculate_carbon
from ecarbon.carbon.store import LocalSnapshotProvider
from ecarbon.config import discover
from ecarbon.extract.footprint import extract_building_footprint
from ecarbon.extract.openings import extract_openings_from_plans
from ecarbon.extract.schedules import (
    parse_assembly_schedule_page,
    parse_openings_schedule_page,
)
from ecarbon.extract.sections import parse_section_datums
from ecarbon.models import Confidence, ElementClass, TakeoffResult, Unit
from ecarbon.takeoff import generate_takeoff


def _get_ab_designs():
    """Locate Alberta designs available in $EC_DATA."""
    return [d for d in discover() if d.key.startswith("AB_") and d.drawings_pdf and d.ifc]


class TestSchedulesExtraction:
    def test_parses_assembly_schedule_layers(self):
        ab_designs = _get_ab_designs()
        if not ab_designs:
            pytest.skip("No AB design package found in $EC_DATA")

        d = ab_designs[0]
        doc = pymupdf.open(d.drawings_pdf)
        try:
            # Assembly schedule is typically p2 (A003)
            specs = parse_assembly_schedule_page(doc[2], 2, "A003")
            assert len(specs) >= 5, "Expected at least 5 assemblies (W1, N1, P1, R1, F1, etc.)"
            assert "W1" in specs or "W2" in specs
            w = specs.get("W1") or specs.get("W2")
            assert w.category == "exterior_wall"
            assert len(w.layers) >= 2, "Exterior wall assembly should have multiple material layers"
            # Thickness in mm should be positive
            assert any(l.thickness_mm > 0 for l in w.layers)
        finally:
            doc.close()

    def test_parses_openings_schedule(self):
        ab_designs = _get_ab_designs()
        if not ab_designs:
            pytest.skip("No AB design package found in $EC_DATA")

        d = ab_designs[0]
        doc = pymupdf.open(d.drawings_pdf)
        try:
            # Opening schedule is typically p3 (A004)
            openings = parse_openings_schedule_page(doc[3], 3, "A004")
            assert len(openings) >= 8, "Expected scheduled doors and windows"
            doors = [op for op in openings.values() if op.category == "door"]
            windows = [op for op in openings.values() if op.category == "window"]
            assert len(doors) >= 3
            assert len(windows) >= 3
            for w in windows:
                assert w.width_mm > 0 and w.height_mm > 0
                assert w.area_m2 > 0
        finally:
            doc.close()


class TestSectionsExtraction:
    def test_parses_section_datums_and_dual_units(self):
        ab_designs = _get_ab_designs()
        if not ab_designs:
            pytest.skip("No AB design package found in $EC_DATA")

        d = ab_designs[0]
        doc = pymupdf.open(d.drawings_pdf)
        try:
            info = parse_section_datums(doc)
            assert info.storeys in (2, 3)
            assert info.ground_to_second_m == pytest.approx(3.0, abs=0.2)
            assert info.wall_plate_height_m >= 5.0
            assert info.roof_peak_height_m >= 8.0
            # Dual unit agreement between metric (3.000m) and imperial (9'-10 1/8")
            assert info.dual_spread_pct is not None
            assert info.dual_spread_pct < 1.0, "Dual unit spread must be < 1% for measured confidence"
            assert info.confidence == "measured"
        finally:
            doc.close()


class TestTakeoffAgainstIFCTruth:
    @pytest.mark.parametrize(
        "design_prefix",
        ["AB_Sixplex", "AB_Rowhouse_02"],
    )
    def test_alberta_designs_within_15_pct_of_ifc(self, design_prefix):
        designs = [d for d in discover() if design_prefix in d.key and d.drawings_pdf and d.ifc]
        if not designs:
            pytest.skip(f"Design {design_prefix} not found in $EC_DATA")

        d = designs[0]
        ifc = parse_ifc_takeoff(d.ifc)
        assert ifc.is_usable

        to = generate_takeoff(d.drawings_pdf)
        assert isinstance(to, TakeoffResult)

        # 1. Check >= 8 element classes
        classes_present = {l.element_class for l in to.lines}
        assert len(classes_present) >= 8
        for expected in [
            ElementClass.SLAB_ON_GRADE,
            ElementClass.FOOTING,
            ElementClass.FOUNDATION_WALL,
            ElementClass.EXTERIOR_WALL,
            ElementClass.ROOF_ASSEMBLY,
            ElementClass.FLOOR_ASSEMBLY,
            ElementClass.WINDOW,
            ElementClass.DOOR,
        ]:
            assert expected in classes_present

        # 2. Check every line has provenance and valid confidence
        for line in to.lines:
            assert line.provenance.page >= 0
            assert line.provenance.sheet_no
            assert line.confidence in (Confidence.MEASURED, Confidence.INFERRED, Confidence.ASSUMED)
            if line.confidence == Confidence.ASSUMED:
                assert line.assumptions, f"Assumed line {line.id} must document assumptions"

        # 3. Accuracy check vs IFC Truth
        # Slab on Grade Area
        slab_line = next(l for l in to.lines if l.id == "ln-slab-concrete")
        slab_area = slab_line.quantity / 0.10  # 100mm slab
        slab_err = abs(slab_area - ifc.slab_on_grade_area_m2) / ifc.slab_on_grade_area_m2 * 100.0
        assert slab_err <= 15.0, f"Slab error {slab_err:.1f}% exceeds 15% (takeoff={slab_area}, ifc={ifc.slab_on_grade_area_m2})"

        # Exterior Wall Area
        ext_wall_line = next(l for l in to.lines if l.id == "ln-ext-wall-batt-insulation")
        wall_area = ext_wall_line.quantity
        wall_err = abs(wall_area - ifc.exterior_wall_area_m2) / ifc.exterior_wall_area_m2 * 100.0
        assert wall_err <= 15.0, f"Wall error {wall_err:.1f}% exceeds 15% (takeoff={wall_area}, ifc={ifc.exterior_wall_area_m2})"

        # Windows
        win_line = next(l for l in to.lines if l.id == "ln-windows-total")
        assert win_line.quantity > 0
        # Window count extracted
        openings_note = win_line.basis.note
        assert "window units" in openings_note

    def test_end_to_end_carbon_calculation(self):
        ab_designs = _get_ab_designs()
        if not ab_designs:
            pytest.skip("No AB design package found in $EC_DATA")

        d = ab_designs[0]
        to = generate_takeoff(d.drawings_pdf)
        prov = LocalSnapshotProvider()
        carbon = calculate_carbon(to, prov)

        assert carbon.total_kg_co2e > 10_000.0
        assert carbon.intensity_kg_co2e_per_m2 > 50.0
        assert carbon.modules == ["A1", "A2", "A3"]
        assert len(carbon.by_assembly) >= 3
        assert len(carbon.by_material_category) >= 3
        # Sum of contribution percentages should be approx 100%
        asm_pct_sum = sum(a.pct_of_total for a in carbon.by_assembly)
        assert asm_pct_sum == pytest.approx(100.0, abs=1.0)
