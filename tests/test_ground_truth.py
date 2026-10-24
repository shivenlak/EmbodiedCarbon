"""The IFC and HOT2000 ground-truth store.

These numbers are what Stage 2 will be scored against, so a silent error here
would make every later accuracy claim meaningless. Each test below pins a trap
that was found by measuring, not by reading the spec.
"""

from __future__ import annotations

import pytest

from ecarbon.bench.ifc_quantities import assembly_tag, short_tag

try:
    from ecarbon.config import discover, get_design

    _HAVE_DATA = len(discover()) >= 52
except Exception:
    _HAVE_DATA = False

needs_data = pytest.mark.skipif(not _HAVE_DATA, reason="$EC_DATA catalogue not present")


class TestTagParsing:
    @pytest.mark.parametrize(
        ("name", "full", "code"),
        [
            ("Basic Wall:W2 -RATED EXTERIOR ENVELOPE WALL:6595017", "W2 -RATED EXTERIOR ENVELOPE WALL", "W2"),
            ("Basic Wall:P1 - 2x4 Stud:6991756", "P1 - 2x4 Stud", "P1"),
            ("Basic Wall:N1 - Foundation:6792590", "N1 - Foundation", "N1"),
            ("Floor:F1 - Slab on Grade:5926577", "F1 - Slab on Grade", "F1"),
            ("Basic Roof:R2 - Exterior Envelope Roof:5919600", "R2 - Exterior Envelope Roof", "R2"),
        ],
    )
    def test_extracts_the_drawing_tag(self, name, full, code):
        """The middle segment is the same tag used on the drawings and in the
        A003 assemblies schedule -- the link that makes IFC and PDF comparable."""
        assert assembly_tag(name) == full
        assert short_tag(name) == code

    def test_handles_names_without_a_type_segment(self):
        assert assembly_tag("600x200mm") == "600x200mm"
        assert assembly_tag(None) == "?"


@needs_data
class TestWallDoubleCounting:
    def test_ifcwall_already_includes_standardcase(self):
        """Adding the two gives 166 walls for a building that has 92."""
        import ifcopenshell

        f = ifcopenshell.open(str(get_design("AB_Fourplex_01").ifc))
        walls = f.by_type("IfcWall")
        standard = f.by_type("IfcWallStandardCase")
        assert len(walls) == 92
        assert {e.id() for e in standard} <= {e.id() for e in walls}

    def test_quantified_wall_count_is_not_doubled(self):
        from ecarbon.bench.ifc_quantities import model_quantities

        q = model_quantities(str(get_design("AB_Fourplex_01").ifc))
        assert len(q.by_type("IfcWall")) == 92


@needs_data
class TestInferredBuildUps:
    def test_walls_without_a_material_association_are_recovered(self):
        """Nine W2 exterior walls declare no material. Skipping them yields
        78 m2 of envelope for a 7 x 22 m two-storey building."""
        from ecarbon.bench.ifc_quantities import model_quantities

        q = model_quantities(str(get_design("AB_Fourplex_01").ifc))
        assert q.n_inferred >= 15, "the inferred-build-up fallback is not firing"
        assert q.exterior_wall_area_m2() > 250, "envelope area collapsed; fallback broken"

    def test_inferred_elements_are_flagged(self):
        from ecarbon.bench.ifc_quantities import model_quantities

        q = model_quantities(str(get_design("AB_Fourplex_01").ifc))
        inferred = [e for e in q.elements if e.thickness_inferred]
        assert inferred
        # Every inferred element must still name the tag it borrowed from.
        assert all(e.tag and e.tag != "?" for e in inferred)


@needs_data
class TestVolumeWithoutBuildUp:
    def test_footings_yield_volume_even_with_no_layer_set(self):
        """Dropping them discarded concrete, the largest carbon contributor."""
        from ecarbon.bench.ifc_quantities import model_quantities

        q = model_quantities(str(get_design("AB_Fourplex_01").ifc))
        footings = q.by_type("IfcFooting")
        assert len(footings) == 6
        assert q.volume_by_type("IfcFooting") > 1.0
        # No build-up means no thickness, so area must be None rather than guessed.
        assert all(f.gross_area_m2 is None for f in footings)
        assert q.no_build_up


@needs_data
class TestGrossVersusNet:
    def test_exterior_walls_are_effectively_gross(self):
        """Window voids are not cut from W2, so this figure is a gross area and
        net-of-openings needs the opening schedule subtracted explicitly."""
        from ecarbon.bench.ifc_quantities import model_quantities

        q = model_quantities(str(get_design("AB_Fourplex_01").ifc))
        gross = q.exterior_wall_area_m2(gross=True)
        net = q.exterior_wall_area_m2(gross=False)
        assert abs(gross - net) / gross < 0.02

    def test_interior_walls_do_show_door_voids(self):
        from ecarbon.bench.ifc_quantities import model_quantities

        q = model_quantities(str(get_design("AB_Fourplex_01").ifc))
        by_tag_gross = q.area_by_tag("IfcWall", gross=True)
        by_tag_net = q.area_by_tag("IfcWall", gross=False)
        p1 = next(t for t in by_tag_gross if t.startswith("P1"))
        assert by_tag_net[p1] < by_tag_gross[p1] * 0.9


@needs_data
class TestHot2000:
    def test_wall_area_is_height_times_perimeter(self):
        """A <Wall> record has no 'area' attribute; reading one yields zero."""
        from ecarbon.bench.hot2000 import parse_hot2000

        h = parse_hot2000(str(get_design("AB_Fourplex_01").h2k[0]))
        assert h.wall_area_m2 > 300
        assert all(s.perimeter_m for s in h.surfaces if s.kind == "Wall")

    def test_walls_split_into_above_grade_and_foundation(self):
        from ecarbon.bench.hot2000 import parse_hot2000

        h = parse_hot2000(str(get_design("AB_Fourplex_01").h2k[0]))
        assert h.above_grade_wall_area_m2 == pytest.approx(290.6, abs=5)
        assert h.foundation_wall_area_m2 == pytest.approx(63.4, abs=5)
        assert h.above_grade_wall_area_m2 + h.foundation_wall_area_m2 == pytest.approx(
            h.wall_area_m2, rel=1e-6
        )

    def test_ceiling_carries_a_real_area_attribute(self):
        from ecarbon.bench.hot2000 import parse_hot2000

        h = parse_hot2000(str(get_design("AB_Fourplex_01").h2k[0]))
        assert h.ceiling_area_m2 > 100

    def test_r_values_are_available_for_assembly_checks(self):
        from ecarbon.bench.hot2000 import parse_hot2000

        r = parse_hot2000(str(get_design("AB_Fourplex_01").h2k[0])).r_values()
        assert r.get("Wall", 0) > 3.0  # RSI, Alberta Tier 3

    def test_every_non_bc_design_has_a_parseable_hot2000(self):
        from ecarbon.bench.hot2000 import parse_hot2000

        checked = 0
        for d in discover():
            if not d.h2k:
                assert d.region == "BC", f"{d.key} unexpectedly has no HOT2000"
                continue
            h = parse_hot2000(str(d.h2k[0]))
            assert h.surfaces, f"{d.key} parsed no surfaces"
            checked += 1
        assert checked >= 45


@needs_data
class TestCrossValidation:
    """The headline Step 9 claim: two independent sources agree to ~1%."""

    def test_ifc_and_hot2000_agree_on_wall_area(self):
        from ecarbon.bench.hot2000 import parse_hot2000
        from ecarbon.bench.ifc_quantities import model_quantities

        d = get_design("AB_Fourplex_01")
        q = model_quantities(str(d.ifc))
        h = parse_hot2000(str(d.h2k[0]))

        ifc_total = q.exterior_wall_area_m2() + q.foundation_wall_area_m2()
        assert abs(ifc_total - h.wall_area_m2) / h.wall_area_m2 < 0.03

    def test_they_agree_on_the_above_grade_envelope(self):
        from ecarbon.bench.hot2000 import parse_hot2000
        from ecarbon.bench.ifc_quantities import model_quantities

        d = get_design("AB_Fourplex_01")
        ifc = model_quantities(str(d.ifc)).exterior_wall_area_m2()
        h2k = parse_hot2000(str(d.h2k[0])).above_grade_wall_area_m2
        assert abs(ifc - h2k) / h2k < 0.03


@needs_data
class TestMaterialVolumes:
    """Per-material volume is the Stage 3 input, and CMHC's naming is
    standardised across the whole catalogue, so one mapping table covers it."""

    def test_materials_use_the_cmhc_prefix(self):
        from ecarbon.bench.ifc_quantities import model_quantities

        vols = model_quantities(str(get_design("AB_Fourplex_01").ifc)).volume_by_material()
        assert vols
        assert sum(1 for m in vols if m.startswith("CMHC_")) >= len(vols) - 1

    def test_concrete_and_framing_dominate_by_volume(self):
        from ecarbon.bench.ifc_quantities import model_quantities

        vols = model_quantities(str(get_design("AB_Fourplex_01").ifc)).volume_by_material()
        top = [m for m, _ in sorted(vols.items(), key=lambda kv: -kv[1])[:3]]
        assert any("Concrete" in m for m in top)
        assert any("Framing" in m or "Wood" in m for m in top)

    def test_layer_volumes_reconcile_with_element_area(self):
        """Per-layer volume is area x layer thickness by construction; this
        guards against the two drifting apart."""
        from ecarbon.bench.ifc_quantities import model_quantities

        q = model_quantities(str(get_design("AB_Fourplex_01").ifc))
        checked = 0
        for e in q.elements:
            if not e.layers or e.gross_area_m2 is None:
                continue
            want = e.gross_area_m2 * (e.thickness_mm / 1000.0)
            assert sum(layer.volume_m3 for layer in e.layers) == pytest.approx(want, rel=1e-6)
            checked += 1
        assert checked > 50


class TestBprLabelNormalisation:
    """Element labels vary by region exactly as the schedule names did in
    Step 7: BC writes 'Roof & Terraces' and 'Windows & Doors' where Alberta
    writes 'Roofs and Terraces' and 'Windows/Doors'. An exact whitelist
    silently returned 3 of 5 elements on every BC report."""

    @pytest.mark.parametrize(
        ("label", "want"),
        [
            ("Foundations", "foundations"),
            ("Upper Floors", "upper_floors"),
            ("Roofs and Terraces", "roofs"),
            ("Roof & Terraces", "roofs"),
            ("External Walls", "external_walls"),
            ("Windows/Doors", "windows_doors"),
            ("Windows & Doors", "windows_doors"),
            ("Stairs/Elevators", "stairs"),
            ("Interiors", "interiors"),
        ],
    )
    def test_element_labels(self, label, want):
        from ecarbon.bench.bpr import canonical_element

        assert canonical_element(label) == want

    @pytest.mark.parametrize(
        "label",
        [
            "Space Heating",
            "Space Cooling",
            "Domestic Water Heating",
            "Water Heating",
            "Ventilation",
            "Fans",
            "Lighting, Plugloads & Appliances",
        ],
    )
    def test_energy_labels_are_excluded(self, label):
        """The energy end-use pie shares the page with the element pie."""
        from ecarbon.bench.bpr import canonical_element

        assert canonical_element(label) is None


class TestBprModuleScope:
    def test_reports_are_not_a1_a3(self):
        """The headline total spans A1-A5 + B4-B5 + C2-C4. Comparing it
        like-for-like with our A1-A3 figure is what criterion 3 forbids."""
        from ecarbon.bench.bpr import REPORT_MODULES, BuildingPerformance

        bp = BuildingPerformance(source="x")
        assert bp.modules == REPORT_MODULES
        assert "A4" in bp.modules and "C4" in bp.modules
        assert bp.module_label == "A1-A5, B4-B5, C2-C4"
        assert bp.modules != ("A1", "A2", "A3")

    def test_a1_a5_is_an_upper_bound_for_a1_a3(self):
        from ecarbon.bench.bpr import BuildingPerformance

        bp = BuildingPerformance(source="x", a1_a5_t=107.0)
        assert bp.a1_a3_upper_bound_kg() == pytest.approx(107_000.0)


class TestBprNormalisation:
    def test_shares_are_rescaled_to_100(self):
        """AB_ADU_01's legend sums to 182%, every entry a constant 1.82x the
        pie slice, so the ratios are sound but the scale is not."""
        from ecarbon.bench.bpr import BuildingPerformance

        bp = BuildingPerformance(
            source="x",
            element_breakdown_pct={"foundations": 60.0, "upper_floors": 37.0, "roofs": 85.0},
        )
        assert bp.breakdown_sum_pct == pytest.approx(182.0)
        norm = bp.element_breakdown_normalised
        assert sum(norm.values()) == pytest.approx(100.0)
        # Ordering and ratios survive normalisation.
        assert norm["foundations"] / norm["upper_floors"] == pytest.approx(60.0 / 37.0)

    def test_empty_breakdown_normalises_to_empty(self):
        from ecarbon.bench.bpr import BuildingPerformance

        assert BuildingPerformance(source="x").element_breakdown_normalised == {}


class TestBprFloorArea:
    def test_implied_area_is_preferred_when_parsed_disagrees(self):
        """Total and intensity are both unambiguously labelled, so where a
        parsed area disagrees the implied one is more trustworthy."""
        from ecarbon.bench.bpr import BuildingPerformance

        bp = BuildingPerformance(source="x", total_ec_kg=32601.0, ec_per_gfa=563.0, gfa_m2=55.0)
        assert bp.gfa_implied_m2 == pytest.approx(57.9, abs=0.2)
        assert bp.best_gfa_m2 == pytest.approx(57.9, abs=0.2)
        assert bp.consistency()

    def test_parsed_area_is_kept_when_consistent(self):
        from ecarbon.bench.bpr import BuildingPerformance

        bp = BuildingPerformance(source="x", total_ec_kg=162043.0, ec_per_gfa=530.0, gfa_m2=306.0)
        assert bp.best_gfa_m2 == 306.0
        assert bp.consistency() == []


@needs_data
class TestBprAgainstRealReports:
    def test_alberta_fourplex_matches_the_published_figures(self):
        from ecarbon.bench.bpr import parse_bpr

        bp = parse_bpr(str(get_design("AB_Fourplex_01").bpr[0]))
        assert bp.location == "Edmonton, AB"
        assert bp.climate_zone == "7A"
        assert bp.gfa_m2 == 306.0
        assert bp.conditioned_m2 == 303.0
        assert bp.storeys == 2 and bp.units == 4
        assert bp.total_ec_kg == 162_043.0
        assert bp.ec_per_gfa == 530.0
        assert bp.biogenic_kg == 46_695.0
        assert (bp.a1_a5_t, bp.b4_b5_t, bp.c2_c4_t) == (107.0, 42.0, 12.0)
        assert bp.rsi["Wall"] == pytest.approx(6.1)
        assert bp.element_breakdown_pct["foundations"] == 44.0
        assert bp.consistency() == []

    def test_chart_axis_labels_are_not_mistaken_for_values(self):
        """A nearest-value search returned 2085 -- a year on the x-axis -- for
        every module figure, because the chart sits beside the metric column."""
        from ecarbon.bench.bpr import parse_bpr

        bp = parse_bpr(str(get_design("AB_Fourplex_01").bpr[0]))
        for v in (bp.a1_a5_t, bp.b4_b5_t, bp.c2_c4_t, bp.cumulative_ec_t):
            assert v is not None and v < 1000

    def test_bc_reports_find_all_five_elements(self):
        from ecarbon.bench.bpr import parse_bpr

        bp = parse_bpr(str(get_design("BC_ADU_02").bpr[0]))
        assert len(bp.element_breakdown_pct) >= 5
        assert "roofs" in bp.element_breakdown_pct
        assert "windows_doors" in bp.element_breakdown_pct

    def test_the_whole_catalogue_parses_or_says_why(self):
        from ecarbon.bench.bpr import parse_bpr

        rows = [parse_bpr(str(p)) for d in discover() for p in d.bpr]
        assert len(rows) >= 73
        readable = [b for b in rows if not b.unreadable]
        # One report (NOR_ADU_Municipal_Garage) embeds fonts with a custom
        # glyph ordering and is reported unreadable rather than silently empty.
        assert len(readable) >= 72
        assert all(b.total_ec_kg and b.best_gfa_m2 for b in readable)
        assert sum(1 for b in readable if len(b.element_breakdown_pct) >= 5) >= 65

    def test_unreadable_reports_are_flagged_not_silently_empty(self):
        from ecarbon.bench.bpr import parse_bpr

        bp = parse_bpr(str(get_design("NOR_ADU_Municipal_Garage").bpr[0]))
        assert bp.unreadable
        assert bp.total_ec_kg is None
        assert "not decodable" in bp.consistency()[0]

    def test_intensity_spans_the_range_research_measured(self):
        from ecarbon.bench.bpr import parse_bpr

        vals = [
            b.ec_per_gfa
            for d in discover()
            for p in d.bpr
            if (b := parse_bpr(str(p))).ec_per_gfa
        ]
        assert min(vals) == pytest.approx(141, abs=5)
        assert max(vals) == pytest.approx(731, abs=5)
