"""The assemblies schedule, which is where element areas become materials.

Every rule here was written because the literal reading of the sheet produces
a wrong number, and most of them are worth more than a measurement
improvement: the cavity rule alone is a factor of two on the largest material
in a wall.
"""

from __future__ import annotations

import pytest

from ecarbon.extract.assemblies import (
    Assembly,
    Layer,
    cmhc_material,
    dominant_tag,
    parse_thickness,
)

try:
    from ecarbon.config import discover, get_design

    _HAVE_DATA = len(discover()) >= 52
except Exception:
    _HAVE_DATA = False

needs_data = pytest.mark.skipif(not _HAVE_DATA, reason="$EC_DATA catalogue not present")


class TestParseThickness:
    @pytest.mark.parametrize(
        ("text", "mm"),
        [
            ("19mm (3/4\")", 19.0),   # metric first, as W1 writes it
            ("3/4\" (19mm)", 19.0),   # imperial first, as W2 writes it
            ("5 1/2\" (140mm)", 140.0),
            ("140mm (5 1/2\")", 140.0),
            ("8\" (200mm)", 200.0),
            ("3/8\" (10mm)", 10.0),
        ],
    )
    def test_both_unit_orders_give_the_same_answer(self, text, mm):
        """W1 and W2 sit in adjacent columns of one sheet and disagree on
        which unit comes first. Parsing by position gets one of them wrong."""
        assert parse_thickness(text)[0] == mm

    @pytest.mark.parametrize("text", ["VAR", "VARIES", "", "N/A", "-"])
    def test_a_cell_stating_no_thickness_yields_none(self, text):
        assert parse_thickness(text)[0] is None

    def test_imperial_only_is_converted_and_said_so(self):
        mm, note = parse_thickness('5 1/2"')
        assert mm == pytest.approx(139.7, abs=0.1)
        assert note and "imperial" in note

    def test_the_two_unit_systems_are_checked_against_each_other(self):
        """A cell giving both is a free agreement check on the drawing."""
        mm, note = parse_thickness('1" (90mm)')
        assert mm == 90.0
        assert note and "differ" in note


def layer(material: str, mm: float | None = None, index: int = 0) -> Layer:
    return Layer(index=index, material=material, thickness_mm=mm)


class TestLayerClassification:
    @pytest.mark.parametrize(
        "material",
        [
            "LIGHT-WEIGHT CLADDING PLACE HOLDER",  # walls, two words
            "ROOFING PLACEHOLDER",                 # roofs, one word
        ],
    )
    def test_placeholders_are_caught_in_both_spellings(self, material):
        lay = Layer(index=0, material=material, thickness_mm=19.0, is_placeholder=True)
        assert not lay.quantifiable
        assert cmhc_material(lay) is None

    def test_a_placeholder_never_resolves_to_a_material(self):
        """`CMHC_Exterior Finish Placeholder 01` does have a factor mapping, to
        vinyl siding. Following it would pick a cladding CMHC left open, on
        about 12% of a home's embodied carbon."""
        lay = Layer(
            index=0,
            material="NON-COMBUSTIBLE LIGHT-WEIGHT CLADDING PLACE HOLDER",
            thickness_mm=19.0,
            is_placeholder=True,
        )
        assert cmhc_material(lay) is None

    def test_a_deferred_layer_produces_no_volume(self):
        """Counting it here and on the structural takeoff double-counts it."""
        lay = Layer(
            index=0, material="WOOD STUD FRAMING", thickness_mm=140.0, deferred_to="Structural"
        )
        assert not lay.quantifiable
        assert lay.volume_m3(100.0) is None

    def test_metal_studs_are_not_called_wood(self):
        """The IFC generalises W2's framing to CMHC_Wood Framing; the drawing
        says METAL STUD FRAMING, and W2 is the non-combustible rated wall."""
        assert cmhc_material(layer("METAL STUD FRAMING", 140.0)) == "CMHC_Metal Framing"
        assert cmhc_material(layer("WOOD STUD FRAMING", 140.0)) == "CMHC_Wood Framing"

    def test_an_unmatched_material_returns_none_rather_than_a_guess(self):
        assert cmhc_material(layer("FREE-DRAINING GRANULAR BASE", 200.0)) is None
        assert cmhc_material(layer("FOUNDATION DAMP PROOFING", 2.0)) is None


class TestIntermittentLayers:
    def test_strapping_covers_only_its_share_of_the_wall(self):
        """'WOOD STRAPPING @ 400mm O/C (38mm WIDE MINIMUM)' is 9.5% of the
        area, not a solid sheet. Taking it solid overstates it tenfold."""
        lay = layer('WOOD STRAPPING @ 400mm O/C  (38mm WIDE MINIMUM)', 19.0)
        coverage, note = lay.coverage
        assert coverage == pytest.approx(0.095, abs=0.001)
        assert note and "intermittent" in note
        assert lay.volume_m3(100.0) == pytest.approx(100 * 0.019 * 0.095, abs=0.01)

    def test_a_cavity_with_no_member_size_yields_no_volume(self):
        """A vented cavity is mostly air. W2's '13mm VENTED CAVITY W/ METAL
        Z-GIRTS' taken solid is tonnes of invented steel."""
        lay = layer("VENTED CAVITY W/ METAL Z-GIRTS @ 400mm O/C", 13.0)
        assert lay.coverage[0] == 0.0
        assert not lay.quantifiable
        assert lay.volume_m3(100.0) is None

    def test_cavity_fill_is_not_an_air_gap(self):
        """A real regression: the word CAVITY in 'STUD CAVITY IN-FILL
        INSULATION' matched the air-gap rule and silently dropped the largest
        material in the wall."""
        lay = layer("STUD CAVITY IN-FILL INSULATION", 140.0)
        assert lay.coverage[0] == 1.0
        assert lay.quantifiable
        assert lay.volume_m3(100.0) == pytest.approx(14.0, abs=0.01)


class TestSharedCavity:
    def build(self) -> Assembly:
        asm = Assembly(tag="W1", name="EXTERIOR ENVELOPE WALL")
        asm.layers = [
            layer("WOOD STUD FRAMING", 140.0, 0),
            layer("STUD CAVITY IN-FILL INSULATION", 140.0, 1),
        ]
        asm.layers[0].shares_cavity_with = 1
        asm.layers[1].shares_cavity_with = 0
        return asm

    def test_the_pair_splits_one_cavity_rather_than_claiming_two(self):
        asm = self.build()
        framing = asm.layers[0].volume_m3(100.0, 0.15)
        fill = asm.layers[1].volume_m3(100.0, 0.15)
        assert framing == pytest.approx(100 * 0.140 * 0.15, abs=0.01)
        assert fill == pytest.approx(100 * 0.140 * 0.85, abs=0.01)
        # Together they fill the cavity exactly once.
        assert framing + fill == pytest.approx(100 * 0.140, abs=0.01)

    def test_built_depth_counts_a_shared_cavity_once(self):
        assert self.build().total_thickness_mm == 140.0


class TestFloorGroupSplit:
    def test_a_slab_on_grade_is_not_a_suspended_floor(self):
        """The F group mixes them. Picking by reference count alone put
        sub-slab insulation into a first-floor ceiling, and it was the second
        largest line in the bill."""
        slab = Assembly(tag="F1", name="SLAB ON GRADE")
        floor = Assembly(tag="F3", name="FLOOR BETWEEN UNITS")
        assert slab.is_slab_on_grade
        assert not floor.is_slab_on_grade

    def test_dominant_tag_can_exclude_the_slab(self):
        tags = {"F1": 16, "F3": 10, "F2": 9}
        available = {"F1", "F2", "F3"}
        assert dominant_tag(tags, "F", available) == "F1"
        assert dominant_tag(tags, "F", available, exclude={"F1"}) == "F3"

    def test_a_group_with_nothing_available_returns_none(self):
        assert dominant_tag({"W2": 68}, "R", {"W2"}) is None


@needs_data
class TestAgainstTheRealSchedule:
    @pytest.fixture(scope="class")
    def parsed(self):
        from ecarbon.extract.assemblies import assemblies_for

        return assemblies_for(get_design("AB_Fourplex_01"))

    def test_every_group_on_the_sheet_is_found(self, parsed):
        assert len(parsed) == 17
        letters = {a.group_letter for a in parsed.values()}
        assert letters == {"N", "R", "W", "F", "P"}

    def test_the_exterior_wall_build_up_is_read_in_full(self, parsed):
        w2 = parsed["W2"]
        assert len(w2.layers) == 9
        assert w2.layers[0].is_placeholder          # cladding, left open
        assert w2.layers[5].deferred_to == "Structural"  # metal studs
        assert w2.layers[6].shares_cavity_with == 5      # the cavity pair
        assert w2.layers[8].thickness_mm == 16.0         # gypsum

    @pytest.mark.parametrize(("tag", "ifc_mm"), [("P1", 121.0), ("P3", 235.0), ("P2", 201.0)])
    def test_built_depth_matches_the_ifc_layer_set(self, parsed, tag, ifc_mm):
        """Independent confirmation: these come from the drawing, the
        comparison from the IFC's own IfcMaterialLayerSet."""
        assert parsed[tag].total_thickness_mm == pytest.approx(ifc_mm, abs=1.0)

    def test_the_applicable_wall_is_chosen_by_reference_count(self):
        from ecarbon.extract.assemblies import assembly_tags_used

        tags = assembly_tags_used(get_design("AB_Fourplex_01"))
        # The plans reference W2 many times and W1 once.
        assert tags.get("W2", 0) > 20
        assert tags.get("W2", 0) > tags.get("W1", 0)

    def test_unquantifiable_layers_are_each_explained(self, parsed):
        for asm in parsed.values():
            messages = asm.gaps()
            assert len(messages) == len(asm.unspecified)
            for message in messages:
                assert asm.tag in message
