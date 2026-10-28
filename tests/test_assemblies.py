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

        parsed, _rejected = assemblies_for(get_design("AB_Fourplex_01"))
        return parsed

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


class TestColumnLearning:
    """The column geometry is read from the sheet, not measured on one firm.

    The first version of this parser hardcoded Alberta's offsets -- thickness
    36 pt left of a centred DESCRIPTION header, material 36 pt right -- and
    read 7 of 7 Alberta sets and 0 of 7 BC ones. BC's description column is
    194 pt wide and Ontario stacks its headers at one x.
    """

    def test_the_thickness_column_is_found_by_its_contents(self):
        from ecarbon.extract.assemblies import learn_columns

        cells = [
            (100.0, 548.0, '3/4"/19mm'),
            (100.0, 620.0, "VERTICAL LIGHTWEIGHT CLADDING"),
            (110.0, 548.0, '2"/51mm'),
            (110.0, 620.0, "SEMI-RIGID INSULATION"),
            (120.0, 548.0, "2x6/38x140mm"),
            (120.0, 620.0, "WOOD STUD FRAMING"),
        ]
        thick_x, mat_x, _name_x = learn_columns(cells, desc_x=608.0)
        assert thick_x == pytest.approx(548.0, abs=1.0)
        assert mat_x == pytest.approx(620.0, abs=1.0)

    def test_a_centred_name_column_is_distinguished_from_the_material_column(self):
        """Alberta's layout: thickness, name and material in three columns."""
        from ecarbon.extract.assemblies import learn_columns

        cells = [
            (100.0, 988.7, "EXTERIOR ENVELOPE WALL"),
            (110.0, 952.7, "19mm (3/4\")"),
            (110.0, 1024.8, "RIGID INSULATION"),
            (120.0, 952.7, "140mm (5 1/2\")"),
            (120.0, 1024.8, "WOOD STUD FRAMING"),
            (130.0, 952.7, "16mm (5/8\")"),
            (130.0, 1024.8, "GYPSUM BOARD"),
        ]
        thick_x, mat_x, name_x = learn_columns(cells, desc_x=988.5)
        assert thick_x == pytest.approx(952.7, abs=1.0)
        assert mat_x == pytest.approx(1024.8, abs=1.0)
        assert name_x == pytest.approx(988.7, abs=1.0)

    def test_no_cells_yields_no_columns(self):
        from ecarbon.extract.assemblies import learn_columns

        assert learn_columns([], desc_x=100.0) == (None, None, None)


class TestPlausibilityGate:
    """Reading this sheet generically sometimes merges blocks or starts one on
    a layer row. The result is structurally wrong while looking ordinary, so it
    is refused rather than used: a wrong build-up produces wrong quantities
    silently, while refusing produces a gap that says so.
    """

    def assembly(self, name: str, n_layers: int, mm: float) -> Assembly:
        asm = Assembly(tag="X1", name=name)
        asm.layers = [layer("RIGID INSULATION", mm / max(n_layers, 1), i) for i in range(n_layers)]
        return asm

    def test_a_sound_assembly_passes(self):
        assert self.assembly("EXTERIOR ENVELOPE WALL", 9, 229.0).implausible() is None

    def test_too_many_layers_is_refused(self):
        """BC_Duplex produced a 47-layer 'VAULTED ROOF' this way."""
        reason = self.assembly("VAULTED ROOF", 47, 1573.0).implausible()
        assert reason and "layers" in reason

    def test_an_absurd_built_depth_is_refused(self):
        reason = self.assembly("EXTERIOR WALL", 8, 1280.0).implausible()
        assert reason and "depth" in reason

    @pytest.mark.parametrize(
        "name",
        [
            "GYPSUM BOARD, TYPE X",
            "ROOFING PLACEHOLDER",
            "AIR BARRIER, VAPOUR PERMEABLE",
            "PARGING ON FACE OF INSULATION TO 150mm",
        ],
    )
    def test_an_assembly_named_after_a_material_is_refused(self, name):
        """The block began on a layer row, so its first layer is missing."""
        reason = self.assembly(name, 6, 200.0).implausible()
        assert reason and "material rather than an assembly" in reason

    def test_an_empty_assembly_is_refused(self):
        assert Assembly(tag="X1", name="EXTERIOR WALL").implausible() == "no layers found"


@needs_data
class TestAcrossFirms:
    """Each firm lays this sheet out differently, so the test is whether more
    than one of them reads -- and whether Alberta still reads exactly.
    """

    @pytest.mark.parametrize(
        ("design", "at_least"),
        [("AB_Fourplex_01", 17), ("BC_Duplex", 8), ("QC_Fourplex_01", 10), ("ON_ADU_02", 8)],
    )
    def test_several_firms_parse(self, design, at_least):
        from ecarbon.extract.assemblies import assemblies_for

        kept, _rejected = assemblies_for(get_design(design))
        assert len(kept) >= at_least

    def test_alberta_is_unchanged_by_generalising(self):
        """The regression guard. Segmenting by tag position rather than by the
        name column broke Alberta's P3, whose build-up matches the IFC to the
        millimetre."""
        from ecarbon.extract.assemblies import assemblies_for

        kept, rejected = assemblies_for(get_design("AB_Fourplex_01"))
        assert len(kept) == 17
        assert rejected == []
        for tag, ifc_mm in (("P1", 121.0), ("P2", 201.0), ("P3", 235.0)):
            assert kept[tag].total_thickness_mm == pytest.approx(ifc_mm, abs=1.0)

    def test_an_unreliable_parse_is_reported_rather_than_used(self):
        """BC's exterior wall defeats both strategies, so it is refused and the
        reason is on the record."""
        from ecarbon.extract.assemblies import assemblies_for

        kept, rejected = assemblies_for(get_design("BC_Duplex"))
        assert rejected, "BC_Duplex has assemblies that cannot be read reliably"
        for message in rejected:
            assert "could not be read reliably" in message
            assert "not counted" in message
        # And nothing refused leaks into the usable set.
        assert all(a.implausible() is None for a in kept.values())

    def test_a_textless_set_reports_nothing_rather_than_guessing(self):
        """The NOR sets have their text converted to vector outlines."""
        from ecarbon.extract.assemblies import assemblies_for

        kept, _rejected = assemblies_for(get_design("NOR_Fourplex_Municipal"))
        assert kept == {}


class TestTagForms:
    """Tag shapes differ by firm, surveyed across every schedule TYPE column.

    P#, F#, W#, R#, N#, C#, S# and the suffixed P#a are universal; W#.#, R#.#
    and FW#.# occur only in BC. Missing the dotted form cost BC its exterior
    wall: with one matchable tag in a 772-point band, tag segmentation could
    not split it and the whole band merged into a 50-layer object that the
    plausibility gate then refused.
    """

    @pytest.mark.parametrize(
        ("tag", "prefix"),
        [
            ("W2", "W"), ("P1a", "P"), ("F5", "F"), ("N1", "N"),
            ("W1.1", "W"), ("R2.1", "R"), ("FW1.1", "FW"),
        ],
    )
    def test_real_tag_forms_parse(self, tag, prefix):
        from ecarbon.extract.assemblies import tag_prefix

        assert tag_prefix(tag) == prefix

    @pytest.mark.parametrize("text", ["R-22", "A101", "140mm", "W1.1.1", "", "RSI"])
    def test_other_drawing_text_is_not_a_tag(self, text):
        from ecarbon.extract.assemblies import tag_prefix

        assert tag_prefix(text) == ""

    def test_a_two_letter_prefix_is_its_own_group(self):
        """BC's FW is a foundation wall. Reading it as F would make it
        selectable as the floor assembly and put a foundation wall's build-up
        into a ceiling."""
        from ecarbon.extract.assemblies import dominant_tag, tag_prefix

        assert tag_prefix("FW1.1") == "FW"
        tags = {"FW1.1": 9, "F1": 4}
        available = {"FW1.1", "F1"}
        assert dominant_tag(tags, "F", available) == "F1"
        assert dominant_tag(tags, "FW", available) == "FW1.1"


class TestZeroDepthRefusal:
    def test_an_assembly_with_no_stated_thickness_is_refused(self):
        """BC's FW1.1 came through four layers deep, named 'RIGID INSULATION
        (R-20.0)', with not one thickness stated. No quantity could come from
        it and in practice it means the block was split in the wrong place."""
        asm = Assembly(tag="FW1.1", name="RIGID INSULATION (R-20.0)")
        asm.layers = [layer("RIGID INSULATION", None, i) for i in range(4)]
        reason = asm.implausible()
        assert reason and "no layer states a thickness" in reason

    def test_one_stated_layer_is_enough_to_keep_it(self):
        asm = Assembly(tag="W1", name="EXTERIOR ENVELOPE WALL")
        asm.layers = [layer("AIR BARRIER", None, 0), layer("GYPSUM BOARD", 16.0, 1)]
        assert asm.implausible() is None


class TestAssemblyNameFilter:
    def test_a_wall_named_after_its_insulation_is_still_an_assembly(self):
        """BC names a genuine wall '2x6 WOOD STUD W/ EXTERIOR INSULATION'. An
        INSULATION$ rule refused it and its whole group with it."""
        asm = Assembly(tag="W1.1", name="2x6 WOOD STUD W/ EXTERIOR INSULATION")
        asm.layers = [layer("GYPSUM BOARD", 16.0, 0), layer("WOOD STUD FRAMING", 140.0, 1)]
        assert asm.implausible() is None

    @pytest.mark.parametrize(
        "name",
        ["GYPSUM WALL BOARD", "VAPOUR CONTROL BARRIER", "ROOFING PLACEHOLDER"],
    )
    def test_a_single_layer_name_is_still_refused(self, name):
        asm = Assembly(tag="X1", name=name)
        asm.layers = [layer("GYPSUM BOARD", 16.0, 0), layer("WOOD STUD FRAMING", 140.0, 1)]
        reason = asm.implausible()
        assert reason and "material rather than an assembly" in reason
