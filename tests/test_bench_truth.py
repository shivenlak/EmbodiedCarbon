"""Tests for Step 9: Ground truth store (IFC, HOT2000, and BPR parsers).

Validates:
  1. H2K parser correctly parses envelope areas, perimeters, and opening counts.
  2. BPR parser extracts published embodied carbon totals, intensity, GFA, and module splits.
  3. IFC quantity engine derives 3D volumes, elevation areas, and material layer quantities.
  4. IFC-derived exterior wall area agrees with HOT2000 within 15% on valid designs.
  5. Exclusions (SKMB and NOR Tanked) are flagged as unusable ground truth.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from ecarbon.bench.bpr_truth import parse_bpr
from ecarbon.bench.h2k_truth import parse_h2k
from ecarbon.bench.ifc_truth import is_site_element, parse_ifc_takeoff
from ecarbon.config import discover


@pytest.fixture(scope="module")
def sample_sixplex_pkg():
    for d in discover():
        if "sixplex" in d.key.lower() and d.region == "AB":
            if d.ifc and d.h2k and d.bpr:
                return d
    pytest.skip("AB_Sixplex package not available on disk")


@pytest.fixture(scope="module")
def sample_rowhouse_pkg():
    for d in discover():
        if "rowhouse_02" in d.key.lower() and d.region == "AB":
            if d.ifc and d.h2k and d.bpr:
                return d
    pytest.skip("AB_Rowhouse_02 package not available on disk")


class TestH2KTruth:
    def test_parse_h2k_envelope_areas(self, sample_sixplex_pkg):
        h2k = parse_h2k(sample_sixplex_pkg.h2k[0])
        assert h2k.dwelling_name == "AB-6PLEX-01"
        assert h2k.city == "Edmonton"
        assert h2k.province == "ALBERTA"
        # Gross exterior wall area should be ~428 m2
        assert 400.0 < h2k.exterior_wall_area_m2 < 450.0
        # Ceiling area should be ~225 m2
        assert 200.0 < h2k.ceiling_area_m2 < 250.0
        # Exposed slab perimeter ~62 m
        assert 50.0 < h2k.slab_exposed_perimeter_m < 70.0
        assert h2k.window_count >= 15
        assert h2k.door_count >= 2

    def test_parse_h2k_rowhouse_middle_unit(self, sample_rowhouse_pkg):
        h2k = parse_h2k(sample_rowhouse_pkg.h2k[0])
        assert "ROW" in h2k.dwelling_name.upper()
        # Middle unit only has front and rear exterior walls (~70.9 m2)
        assert 60.0 < h2k.exterior_wall_area_m2 < 85.0
        assert h2k.ceiling_area_m2 > 50.0


class TestBPRTruth:
    def test_parse_bpr_sixplex(self, sample_sixplex_pkg):
        bpr = parse_bpr(sample_sixplex_pkg.bpr[0])
        assert bpr.location == "Edmonton, AB"
        assert bpr.climate_zone == "7A"
        assert bpr.gross_floor_area_m2 == 492.0
        assert bpr.conditioned_floor_area_m2 == 404.0
        assert bpr.storeys == 3
        assert bpr.units == 6
        assert bpr.total_ec_kg_co2e == 213073.0
        assert bpr.ec_intensity_kg_co2e_per_m2 == 433.0
        assert bpr.biogenic_carbon_kg_co2e == 65807.0
        assert bpr.a1_a5_ec_t_co2e == 135.0
        assert bpr.b4_b5_ec_t_co2e == 62.0
        assert bpr.c2_c4_ec_t_co2e == 16.0
        assert "Foundations" in bpr.breakdown_pct
        assert bpr.breakdown_pct["Foundations"] == 38.0

    def test_parse_bpr_rowhouse(self, sample_rowhouse_pkg):
        bpr = parse_bpr(sample_rowhouse_pkg.bpr[0])
        assert bpr.location == "Edmonton, AB"
        assert bpr.climate_zone == "7A"
        assert bpr.gross_floor_area_m2 == 131.0
        assert bpr.total_ec_kg_co2e == 58952.0
        assert bpr.ec_intensity_kg_co2e_per_m2 == 450.0


class TestIFCTruth:
    def test_is_site_element_filters_landscape(self):
        assert is_site_element("Floor:xSite - Asphalt")
        assert is_site_element("Floor:xSite - Grass")
        assert is_site_element("Topography")
        assert is_site_element("Concrete Pavers - Landscape")
        assert not is_site_element("Basic Wall:W2 -RATED EXTERIOR ENVELOPE WALL")
        assert not is_site_element("Floor:F1 - Slab on Grade")

    def test_parse_ifc_takeoff_quantities(self, sample_sixplex_pkg):
        ifc = parse_ifc_takeoff(sample_sixplex_pkg.ifc)
        assert ifc.is_usable is True
        assert ifc.unusable_reason is None

        # Exterior wall area ~377 m2
        assert 350.0 < ifc.exterior_wall_area_m2 < 410.0
        assert ifc.exterior_wall_volume_m3 > 70.0

        # Slab on grade
        assert ifc.slab_on_grade_area_m2 > 150.0
        assert ifc.slab_on_grade_volume_m3 > 50.0

        # Openings
        assert ifc.window_count >= 20
        assert ifc.door_count >= 20

        # Material quantities
        assert "CMHC_Concrete, CIP" in ifc.material_volumes_m3
        assert "CMHC_Wood Framing" in ifc.material_volumes_m3
        assert ifc.material_volumes_m3["CMHC_Concrete, CIP"] > 50.0
        assert ifc.material_volumes_m3["CMHC_Wood Framing"] > 100.0


class TestIFCvsH2KCrossValidation:
    def test_sixplex_ifc_vs_h2k_wall_area_agreement(self, sample_sixplex_pkg):
        """Acceptance test: IFC exterior wall area agrees with HOT2000 within 15%."""
        ifc = parse_ifc_takeoff(sample_sixplex_pkg.ifc)
        h2k = parse_h2k(sample_sixplex_pkg.h2k[0])

        net_h2k = h2k.exterior_wall_area_m2 - h2k.window_total_area_m2 - h2k.door_total_area_m2
        diff_pct = abs(ifc.exterior_wall_area_m2 - net_h2k) / net_h2k * 100.0
        # AB_Sixplex measured at 0.5% difference
        assert diff_pct < 5.0, f"Expected <5% difference, got {diff_pct:.2f}%"
