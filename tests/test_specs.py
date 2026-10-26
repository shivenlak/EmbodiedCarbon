"""Reading dimensioned specifications out of drawing notes.

The regexes here run over flattened sheet text, where unrelated sentences sit
next to each other, so each one is pinned against the real note it must match
AND against the note that previously fooled it.
"""

from __future__ import annotations

import pytest

from ecarbon.extract.specs import FoundationSpec, parse_foundation_spec

try:
    from ecarbon.config import discover, get_design

    _HAVE_DATA = len(discover()) >= 52
except Exception:
    _HAVE_DATA = False

needs_data = pytest.mark.skipif(not _HAVE_DATA, reason="$EC_DATA catalogue not present")

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


class TestStripFootingSections:
    """Quebec states its footings as `FOOTING 750x200` on the structural plan.

    Alberta states a grade beam instead, which is why this went unparsed for
    so long: the foundation parser was calibrated on one firm's wording, and
    every QC, BC and Atlantic design came back with a system but no
    dimensions -- slab and footing together being 27% of a home's carbon.
    """

    def test_the_real_quebec_string(self):
        from ecarbon.extract.specs import footing_sections

        found = footing_sections(
            "DIMENSIONS AND REINFORCEMENT FOR STRIP FOOTING: FOOTING 750x200 "
            "SEE SECTION D FOOTING 800x200 SEE SECTION A S2 PILASTER"
        )
        assert found == [(750.0, 200.0), (800.0, 200.0)]

    def test_the_dowel_string_that_burned_the_beam_pattern(self):
        """A looser grade-beam pattern once matched this and reported a
        1200x1200 beam -- a six-fold error on the largest concrete item."""
        from ecarbon.extract.specs import footing_sections

        assert footing_sections(
            "4-15M x 1200mm LG. DOWELS AT ALL PILE TO GRADE BEAM LOCATIONS"
        ) == []

    def test_a_footing_is_wider_than_it_is_deep(self):
        from ecarbon.extract.specs import footing_sections

        assert footing_sections("FOOTING 200x750") == []

    @pytest.mark.parametrize("text", ["FOOTING 50x20", "FOOTING 5000x3000", "FOOTING 900x900"])
    def test_implausible_sections_are_rejected(self, text):
        from ecarbon.extract.specs import footing_sections

        assert footing_sections(text) == []

    def test_volume_is_section_times_run(self):
        from ecarbon.extract.specs import FoundationSpec

        spec = FoundationSpec(footing_width_mm=750.0, footing_depth_mm=200.0)
        assert spec.footing_section_m2 == pytest.approx(0.15, abs=0.001)
        assert spec.footing_volume_m3(54.9) == pytest.approx(8.235, abs=0.01)

    def test_no_section_yields_no_volume(self):
        from ecarbon.extract.specs import FoundationSpec

        assert FoundationSpec().footing_volume_m3(50.0) is None

    def test_similar_sections_pass_without_comment(self):
        """750x200 and 800x200 differ by 6%, which does not change the answer."""
        from ecarbon.extract.specs import FoundationSpec

        spec = FoundationSpec(
            footing_width_mm=750.0,
            footing_depth_mm=200.0,
            other_footing_sections=[(800.0, 200.0)],
        )
        assert spec.footing_section_note is None

    def test_a_wide_spread_between_sections_is_reported(self):
        from ecarbon.extract.specs import FoundationSpec

        spec = FoundationSpec(
            footing_width_mm=600.0,
            footing_depth_mm=200.0,
            other_footing_sections=[(1500.0, 400.0)],
        )
        note = spec.footing_section_note
        assert note and "more than one strip-footing section" in note
        assert "1500x400" in note


@needs_data
class TestStripFootingsOnRealDesigns:
    @pytest.mark.parametrize(
        ("design", "width", "depth"),
        [("QC_Fourplex_01", 750.0, 200.0), ("QC_Sixplex", 900.0, 250.0)],
    )
    def test_quebec_footings_are_read(self, design, width, depth):
        from ecarbon.extract.specs import foundation_spec_for

        spec = foundation_spec_for(get_design(design))
        assert spec.footing_width_mm == width
        assert spec.footing_depth_mm == depth

    def test_alberta_still_reads_a_grade_beam_and_no_strip_footing(self):
        """Alberta sits on grade beams over screw piles; adding the footing
        pattern must not invent a second foundation for it."""
        from ecarbon.extract.specs import foundation_spec_for

        spec = foundation_spec_for(get_design("AB_Fourplex_01"))
        assert spec.grade_beam_width_mm == 200.0
        assert spec.footing_width_mm is None
        assert spec.system == "grade_beam_on_screw_piles"

    def test_the_footing_reaches_the_bill_of_quantities(self):
        from ecarbon.models import ElementClass, ProjectFacts, Unit
        from ecarbon.takeoff.builder import build_takeoff

        takeoff = build_takeoff(
            get_design("QC_Fourplex_01"),
            ProjectFacts(name="QC_Fourplex_01", gfa_m2=366.0, gfa_basis="gross", storeys=2),
        )
        line = takeoff.line("ln-strip-footing")
        assert line.element_class is ElementClass.FOOTING
        assert line.unit is Unit.M3
        assert line.quantity > 0
        assert line.provenance.sheet_no
        # The run length is the footprint perimeter, which omits interior
        # bearing walls, and the line has to say so.
        assert any("interior bearing" in a for a in line.assumptions)


class TestFootingScheduleTables:
    """BC states its footings in a schedule rather than inline.

    From sheet S001, with the metric in brackets beside the imperial:

        SF1  STRIP  [70 - 90 kg/m3]    2'-0" [600] WD x 18" [450] DP
        SF2  STRIP  [110 - 150 kg/m3]  2'-0" [600] WD x 10" [250] DP
        SF3  STRIP  [220 kg/m3]        3'-0" [900] WD x 18" [450] DP
    """

    BC_TEXT = (
        "REMARKS AS MARKED ON PLANS SF2 STRIP [110 - 150 kg/m3] 2'-0\" [600] WD x "
        "10\" [250] DP AS MARKED ON PLANS SF3 STRIP [220 kg/m3] 3'-0\" [900] WD x "
        "18\" [450] DP SF1 PF1 FOOTING SCHEDULE STRIP PAD [70 - 90 kg/m3] "
        "[220 kg/m3] 2'-0\" [600] WD x 18\" [450] DP"
    )

    def test_the_real_bc_schedule(self):
        from ecarbon.extract.specs import footing_sections

        assert footing_sections(self.BC_TEXT) == [
            (600.0, 250.0),
            (600.0, 450.0),
            (900.0, 450.0),
        ]

    def test_a_reinforcement_rate_is_not_a_dimension(self):
        """[110 - 150 kg/m3] sits between the dimensions. Reading a bracket as
        a dimension is the same class of error as the 1200mm LG. DOWELS one."""
        from ecarbon.extract.specs import footing_sections

        assert footing_sections('FW2 [110 - 150 kg/m3] 10" [250mm]') == []

    def test_sections_come_back_smallest_first(self):
        """Deterministic, because text order is arbitrary and the schedule does
        not say which section runs where."""
        from ecarbon.extract.specs import footing_sections

        found = footing_sections(self.BC_TEXT)
        areas = [w * d for w, d in found]
        assert areas == sorted(areas)

    def test_the_smallest_is_used_and_called_a_lower_bound(self):
        """BC's three sections span 0.15 to 0.405 m2, a factor of 2.7.
        Overstating footing concrete threefold is the unrecoverable direction."""
        from ecarbon.extract.specs import FoundationSpec, footing_sections

        found = footing_sections(self.BC_TEXT)
        spec = FoundationSpec(
            footing_width_mm=found[0][0],
            footing_depth_mm=found[0][1],
            other_footing_sections=found[1:],
        )
        assert (spec.footing_width_mm, spec.footing_depth_mm) == (600.0, 250.0)
        note = spec.footing_section_note
        assert note and "LOWER BOUND" in note
        assert "900x450" in note


@needs_data
class TestFootingSchedulesOnRealDesigns:
    @pytest.mark.parametrize("design", ["BC_Duplex", "BC_Sixplex", "BC_Fourplex_01"])
    def test_bc_footings_are_read(self, design):
        from ecarbon.extract.specs import foundation_spec_for

        spec = foundation_spec_for(get_design(design))
        assert (spec.footing_width_mm, spec.footing_depth_mm) == (600.0, 250.0)
        assert spec.other_footing_sections
        assert "LOWER BOUND" in (spec.footing_section_note or "")

    def test_quebec_is_unaffected_by_the_table_pattern(self):
        from ecarbon.extract.specs import foundation_spec_for

        spec = foundation_spec_for(get_design("QC_Fourplex_01"))
        assert (spec.footing_width_mm, spec.footing_depth_mm) == (750.0, 200.0)

    def test_alberta_still_has_no_strip_footing(self):
        from ecarbon.extract.specs import foundation_spec_for

        spec = foundation_spec_for(get_design("AB_Fourplex_01"))
        assert spec.footing_width_mm is None
        assert spec.system == "grade_beam_on_screw_piles"
