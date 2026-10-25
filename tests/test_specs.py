"""Reading dimensioned specifications out of drawing notes.

The regexes here run over flattened sheet text, where unrelated sentences sit
next to each other, so each one is pinned against the real note it must match
AND against the note that previously fooled it.
"""

from __future__ import annotations

import pytest

from ecarbon.extract.specs import FoundationSpec, parse_foundation_spec

# Verbatim from AB_Fourplex_01 S201.
S201 = """
200x1200 DP. CONC. GRADE BEAM R/W
10M @ 200 O/C MIDDLE E.F.
10M @ 300 O/C STIRRUPS
SCREW PILE BY SCREW PILE SUPPLIER TYP.
CONCRETE SLAB ON GRADE TO CONSIST OF 130mm THICK CONCRETE SLAB R/W. 10M @ 300
PILE MINIMUM SIZE SHALL BE 400mmØ AND REINFORCEMENT SHALL BE 4-15M VERTICAL
UNLESS NOTED OTHERWISE ON DRAWINGS, PROVIDE 4-15M x 1200mm LG. DOWELS AT ALL
PILE TO GRADE BEAM LOCATIONS AND 6-15M x 1200mm LG. DOWELS AT ALL PILE TO
"""
# Verbatim from AB_Fourplex_01 S401.
S401 = """
CONC. GRADE BEAM
PROVIDE 100mm FROST UNDER GRADE BEAMS
300x300x19mm THICK STEEL CAP PLATE WELDED ALL AROUND TO SCREW PILE
"""


class TestAlbertaFoundation:
    @pytest.fixture
    def spec(self) -> FoundationSpec:
        return parse_foundation_spec({"S201": S201, "S401": S401})

    def test_identifies_the_system(self, spec):
        assert spec.system == "grade_beam_on_screw_piles"
        assert spec.screw_piles

    def test_slab_thickness(self, spec):
        """130 mm, not the 100 mm of frost insulation in the same note set."""
        assert spec.slab_thickness_mm == 130.0

    def test_grade_beam_section(self, spec):
        """200x1200, not the 1200 mm dowel length beside 'GRADE BEAM'."""
        assert spec.grade_beam_width_mm == 200.0
        assert spec.grade_beam_depth_mm == 1200.0
        assert spec.grade_beam_section_m2 == pytest.approx(0.24)

    def test_pile_diameter(self, spec):
        assert spec.pile_diameter_mm == 400.0

    def test_frost_insulation_is_not_the_slab(self, spec):
        assert spec.frost_insulation_mm == 100.0
        assert spec.slab_thickness_mm != spec.frost_insulation_mm

    def test_every_value_is_traceable_to_a_sheet(self, spec):
        """Criterion 2 requires each quantity to name its source sheet."""
        assert any("S201" in s for s in spec.sources)
        joined = " ".join(spec.sources)
        assert "slab 130mm" in joined
        assert "grade beam 200x1200" in joined

    def test_nothing_reported_missing(self, spec):
        assert spec.missing == []

    def test_rebar_notes_captured(self, spec):
        assert "10M @ 300 o/c" in spec.rebar_notes
        assert "4-15M" in spec.rebar_notes


class TestRegressionsThatFooledTheRegexes:
    def test_dowel_length_is_not_a_grade_beam_section(self):
        """'4-15M x 1200mm LG. DOWELS AT ALL PILE TO GRADE BEAM LOCATIONS'
        produced a 1200x1200 beam -- a 6x error on the largest concrete item."""
        spec = parse_foundation_spec(
            {"S201": "PROVIDE 4-15M x 1200mm LG. DOWELS AT ALL PILE TO GRADE BEAM LOCATIONS"}
        )
        assert spec.grade_beam_width_mm is None

    def test_frost_insulation_under_a_slab_is_not_the_slab(self):
        spec = parse_foundation_spec({"S102": "PROVIDE 100mm FROST INSULATION UNDER SLAB"})
        assert spec.slab_thickness_mm is None

    def test_the_foundation_plan_outranks_a_detail_sheet(self):
        """S102 showed a 100 mm slab condition while S201 states 130 mm."""
        spec = parse_foundation_spec(
            {
                "S102": "100mm THICK CONCRETE SLAB AT STOOP",
                "S201": "SLAB ON GRADE TO CONSIST OF 130mm THICK CONCRETE SLAB",
            }
        )
        assert spec.slab_thickness_mm == 130.0


class TestScrewPilesAreNotConcrete:
    def test_screw_pile_volume_is_not_offered(self):
        """A screw pile is a steel product. Counting its displaced volume as
        concrete invents concrete on the single biggest carbon item."""
        spec = parse_foundation_spec({"S201": "SCREW PILE, 400mmØ PILE MINIMUM"})
        assert spec.screw_piles
        assert spec.pile_volume_m3(30, 3.0) is None

    def test_cast_in_place_piles_do_get_a_volume(self):
        spec = FoundationSpec(pile_diameter_mm=400.0, cast_in_place_piles=True)
        v = spec.pile_volume_m3(10, 3.0)
        assert v == pytest.approx(10 * 3.141592653589793 * 0.2**2 * 3.0)


class TestDerivedVolumes:
    def test_slab_and_beam_volumes(self):
        spec = parse_foundation_spec({"S201": S201})
        assert spec.slab_volume_m3(136.4) == pytest.approx(17.73, abs=0.05)
        assert spec.grade_beam_volume_m3(60.0) == pytest.approx(14.4, abs=0.05)

    def test_the_ifc_overstates_this_foundation(self):
        """The IFC models the same foundation as one 454 mm concrete layer
        (61.9 m3). The drawings and the cost estimate agree it is a 130 mm slab
        on 200x1200 grade beams, so the IFC must not score this element."""
        spec = parse_foundation_spec({"S201": S201})
        drawn = spec.slab_volume_m3(136.4) + spec.grade_beam_volume_m3(60.0)
        assert drawn == pytest.approx(32.1, abs=0.5)
        assert 61.9 / drawn > 1.8

    def test_missing_values_are_reported_not_defaulted(self):
        spec = parse_foundation_spec({"S201": "SOME UNRELATED NOTE"})
        assert spec.system == "unknown"
        assert spec.slab_volume_m3(100.0) is None
        assert "slab thickness not stated" in spec.missing
        assert "foundation system not identified" in spec.missing


class TestOtherFoundationSystems:
    def test_strip_footings_are_recognised(self):
        spec = parse_foundation_spec({"S201": "CONTINUOUS STRIP FOOTING 600x200"})
        assert spec.strip_footings
        assert spec.system == "strip_footing"

    def test_imperial_and_metric_beam_orders_both_parse(self):
        """Some notes give depth first."""
        spec = parse_foundation_spec({"S201": "GRADE BEAM 1200 x 250 DEEP"})
        assert spec.grade_beam_width_mm == 250.0
        assert spec.grade_beam_depth_mm == 1200.0


class TestSheetTypeWordOrder:
    """A Step 7 gap found by Step 10: filtering structural sheets by TYPE
    excluded BC and QC entirely, because BC titles its foundation plan
    'PLAN FOUNDATION / MAIN FLOOR' and QC uses 'STRUCTURAL PLANS'."""

    @pytest.mark.parametrize(
        ("title", "want"),
        [
            ("PLAN FOUNDATION / MAIN FLOOR", "foundation_plan"),
            ("FOUNDATION PLAN", "foundation_plan"),
            ("STRUCTURAL PLANS", "framing_plan"),
            ("PLAN - ROOF", "roof_plan"),
            ("SCHEDULE - ASSEMBLIES", "assembly_schedule"),
        ],
    )
    def test_word_order_does_not_matter(self, title, want):
        from ecarbon.intake.classify import sheet_type_of

        assert sheet_type_of(title).value == want
