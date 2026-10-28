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


class TestWallRoleClassification:
    """By the WORDS in the tag, not its code prefix. A W* prefix rule found
    11 m2 of soffit bulkhead on AB_ADU_01 and missed 129 m2 of envelope named
    'CPH-2-STANDARD EXTERIOR ENVELOPE WALL'."""

    @pytest.mark.parametrize(
        ("tag", "role"),
        [
            ("CPH-2-STANDARD EXTERIOR ENVELOPE WALL", "exterior"),
            # ATL and QC describe envelope walls by their FRAMING, not their
            # position, so a flat "STUD -> interior" rule read every one of
            # them as interior and dropped those designs to 0.21-0.47 of
            # their HOT2000 wall area.
            ("W1* - 2x6 Stud w Wood Shingles Cladding", "exterior"),
            ("W2 - 2x6 Stud w Metal Cladding", "exterior"),
            ("W1 - 2x6 Stud w Brick", "exterior"),
            ("W1a - 2x6 Stud w Double Brick", "exterior"),
            ("W1 - Exterior Envelope Wall, Cladding 1", "exterior"),
            ("W3 - Balcony Wall", "exterior"),
            ("W7", "exterior"),
            # ... but a W prefix is not sufficient on its own: these separate
            # units or are clad on both faces, so they have no outdoor side.
            ("W8 - RATED DEMISING", "interior"),
            ("W3 - 2x4 Stud w Metal Cladding (both sides) 2", "interior"),
            ("W9 - 2x8 Stud w Metal Cladding_(both sides)", "interior"),
            ("P4 - Demising wall", "interior"),
            ("P5 - Plumbing Chase", "interior"),
            ("P1a - 2x4 Furring wall", "interior"),
            ("P3 - Asymmetric Rated Wall (Stairs)", "interior"),
            ("N1B - Foundation_no insulation", "foundation"),
            ("W1 -STANDARD EXTERIOR ENVELOPE WALL - SOFFIT BULKHEAD", "exterior"),
            ("W2 -RATED EXTERIOR ENVELOPE WALL", "exterior"),
            ("W2-STANDARD EXTERIOR ENVELOPE WALL", "exterior"),
            ("N1 - Foundation", "foundation"),
            ("P1 - 2x4 Stud", "interior"),
            ("P2 - 2x6 Stud (Rated)", "interior"),
            ("P3 - Rated Wall", "interior"),
            ("P3 - Demising Wall, Non-Load Bearing (Rated)", "interior"),
            ("P5 - 2x6 PLUMBING WALL", "interior"),
            ("P5 - 2x4 Stud - Plumbing chase", "interior"),
        ],
    )
    def test_roles(self, tag, role):
        from ecarbon.bench.ifc_quantities import wall_role

        assert wall_role(tag) == role

    def test_a_bare_w_code_still_reads_as_envelope(self):
        from ecarbon.bench.ifc_quantities import wall_role

        assert wall_role("W4") == "exterior"

    def test_roles_partition_the_total(self):
        from ecarbon.bench.ifc_quantities import wall_role

        tags = ["W2 -RATED EXTERIOR ENVELOPE WALL", "N1 - Foundation", "P1 - 2x4 Stud"]
        assert {wall_role(t) for t in tags} == {"exterior", "foundation", "interior"}


@needs_data
class TestWallRoleOnRealModels:
    def test_adu_envelope_is_not_missed(self):
        """The regression: 11 m2 instead of 175 m2."""
        from ecarbon.bench.ifc_quantities import model_quantities

        q = model_quantities(str(get_design("AB_ADU_01").ifc))
        assert q.exterior_wall_area_m2() > 100

    def test_roles_sum_to_the_whole(self):
        from ecarbon.bench.ifc_quantities import model_quantities

        q = model_quantities(str(get_design("AB_Fourplex_01").ifc))
        by_role = q.area_by_role()
        total = sum(q.area_by_tag("IfcWall").values())
        assert sum(by_role.values()) == pytest.approx(total)
        assert set(by_role) <= {"exterior", "foundation", "interior"}


class TestManifestTiering:
    """The tier is the binding constraint on using a design for quantity
    scoring, so these rules decide what our accuracy claims rest on."""

    def _truth(self, **kw):
        from ecarbon.bench.manifest import DesignTruth

        base = dict(key="X", region="AB", typology="fourplex", ifc_geometry_coverage=1.0)
        return DesignTruth(**{**base, **kw})

    def test_corroborated_agreement_is_gold(self):
        from ecarbon.bench.manifest import Tier, _tier

        t = self._truth(wall_agreement_pct=1.2)
        assert _tier(t) == Tier.GOLD
        t.tier = _tier(t)
        assert t.scoreable_for_quantities

    def test_wide_disagreement_is_still_scoreable(self):
        """HOT2000 agreement annotates the reference; it does not gate it.

        HOT2000 models the thermal envelope and, for rowhouses, a single unit,
        so it legitimately disagrees with a complete architectural model.
        Gating on it discarded 25 designs with perfect geometry.
        """
        from ecarbon.bench.manifest import Tier, _tier

        t = self._truth(wall_agreement_pct=41.0)
        t.tier = _tier(t)
        assert t.tier == Tier.SILVER
        assert t.scoreable_for_quantities
        # The disagreement is recorded, not discarded.
        assert t.wall_agreement_pct == 41.0

    def test_no_second_source_is_silver_not_gold(self):
        """The 7 BC designs ship Step Code checklists instead of HOT2000, so
        complete geometry with nothing to corroborate it is scoreable but not
        the highest confidence."""
        from ecarbon.bench.manifest import Tier, _tier

        t = self._truth(wall_agreement_pct=None)
        assert _tier(t) == Tier.SILVER
        t.tier = _tier(t)
        assert t.scoreable_for_quantities

    def test_geometry_coverage_is_the_real_gate(self):
        from ecarbon.bench.manifest import Tier, _tier

        t = self._truth(ifc_geometry_coverage=0.26, wall_agreement_pct=1.0)
        assert _tier(t) == Tier.GEOMETRY_ONLY
        t.tier = _tier(t)
        assert not t.scoreable_for_quantities

    def test_unreadable_pdf_is_robustness_regardless_of_ifc(self):
        """The 8 NOR sets have perfect IFCs and textless PDFs, so they are
        scored on reporting what they cannot read, not on accuracy."""
        from ecarbon.bench.manifest import Tier, _tier

        t = self._truth(flags=["pdf_text_unreadable"], wall_agreement_pct=0.5)
        assert _tier(t) == Tier.ROBUSTNESS

    def test_a1_a3_ceiling_comes_from_a1_a5(self):
        t = self._truth(bpr_a1_a5_t=107.0)
        assert t.a1_a3_ceiling_kg == pytest.approx(107_000.0)


class TestManifestRoundTrip:
    def test_save_and_load(self, tmp_path):
        from ecarbon.bench.manifest import DesignTruth, load_manifest, save_manifest

        rows = [
            DesignTruth(key="A", region="AB", typology="fourplex", tier="gold"),
            DesignTruth(key="B", region="BC", typology="adu", tier="silver", flags=["no_hot2000"]),
        ]
        p = save_manifest(rows, tmp_path / "t.json")
        back = load_manifest(p)
        assert [r.key for r in back] == ["A", "B"]
        assert back[1].flags == ["no_hot2000"]

    def test_summary_mentions_every_populated_tier(self):
        from ecarbon.bench.manifest import DesignTruth, summarise

        rows = [
            DesignTruth(key="A", region="AB", typology="x", tier="gold"),
            DesignTruth(key="B", region="AB", typology="x", tier="robustness"),
        ]
        s = summarise(rows)
        assert "gold" in s and "robustness" in s and "2 designs" in s


class TestIfcLengthUnits:
    """Attribute lengths are in the file's own unit, and the catalogue differs.

    Alberta and Quebec declare MILLI/METRE; **every BC model declares FOOT**.
    Reading `IfcMaterialLayer.LayerThickness` raw gave BC partition build-ups
    of 0.40 to 1.20 "mm" and scored a correct 172 mm wall as 34,300% in error
    against a 0.50 ft layer set that is really 152.4 mm. Correcting it moved
    the catalogue-wide median built-depth error from 22.1% to 5.8%.

    Geometry read through ifcopenshell's engine with world coordinates is not
    affected, because it arrives in metres whatever the file says -- which is
    why the footprint and scale benchmarks were never wrong.
    """

    @pytest.mark.parametrize(
        ("name", "prefix", "want"),
        [("METRE", "MILLI", 1.0), ("METRE", None, 1000.0)],
    )
    def test_si_units(self, name, prefix, want):
        from ecarbon.bench.ifc_quantities import length_scale_to_mm

        class Unit:
            UnitType = "LENGTHUNIT"
            Name = name
            Prefix = prefix

            def is_a(self, what):
                return what == "IfcSIUnit"

        class Model:
            def by_type(self, _):
                return [type("A", (), {"Units": [Unit()]})()]

        assert length_scale_to_mm(Model()) == want

    def test_feet_are_converted(self):
        """0.50 ft is 152.4 mm, not 0.50 mm."""
        from ecarbon.bench.ifc_quantities import length_scale_to_mm

        class Base:
            Name = "METRE"
            Prefix = None

        class Factor:
            ValueComponent = type("V", (), {"wrappedValue": 0.3048})()
            UnitComponent = Base()

        class Unit:
            UnitType = "LENGTHUNIT"
            ConversionFactor = Factor()

            def is_a(self, what):
                return what == "IfcConversionBasedUnit"

        class Model:
            def by_type(self, _):
                return [type("A", (), {"Units": [Unit()]})()]

        scale = length_scale_to_mm(Model())
        assert scale == pytest.approx(304.8, abs=0.1)
        assert 0.50 * scale == pytest.approx(152.4, abs=0.1)

    def test_an_unreadable_unit_falls_back_to_millimetres(self):
        """The catalogue's majority convention and the Revit export default."""
        from ecarbon.bench.ifc_quantities import length_scale_to_mm

        class Model:
            def by_type(self, _):
                raise RuntimeError("no units")

        assert length_scale_to_mm(Model()) == 1.0


@needs_data
class TestUnitsOnTheRealModels:
    def test_the_catalogue_is_not_consistent_about_length_units(self):
        import ifcopenshell

        from ecarbon.bench.ifc_quantities import length_scale_to_mm

        scales = {}
        for key in ("AB_Fourplex_01", "BC_Duplex", "QC_Fourplex_01"):
            design = get_design(key)
            scales[key] = length_scale_to_mm(ifcopenshell.open(str(design.ifc)))
        assert scales["AB_Fourplex_01"] == 1.0
        assert scales["QC_Fourplex_01"] == 1.0
        assert scales["BC_Duplex"] == pytest.approx(304.8, abs=0.1)

    def test_a_bc_partition_comes_back_as_a_real_wall(self):
        """BC_Duplex P1 is 15.88 + 88.9 + 15.88 = 120.7 mm, a 2x4 partition.
        Unscaled it read 0.40 mm."""
        import ifcopenshell

        from ecarbon.bench.ifc_quantities import material_layers

        model = ifcopenshell.open(str(get_design("BC_Duplex").ifc))
        depths = []
        for wall in model.by_type("IfcWall"):
            name = wall.Name or ""
            if ":" not in name:
                continue
            if not name.split(":")[1].strip().startswith("P1"):
                continue
            layers = material_layers(wall)
            if layers:
                depths.append(sum(t for _m, t in layers))
        assert depths, "no P1 partition found in BC_Duplex"
        assert min(depths) == pytest.approx(120.7, abs=1.0)
