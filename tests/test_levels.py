"""Storey levels from section datums, and the wall area they imply.

Exterior wall is ~20% of embodied carbon, second only to concrete, and its
area is perimeter x wall height -- so the height basis matters as much as the
measurement.
"""

from __future__ import annotations

import pytest

from ecarbon.extract.levels import Level, StoreyHeights

try:
    from ecarbon.config import discover, get_design

    _HAVE_DATA = len(discover()) >= 52
except Exception:
    _HAVE_DATA = False

needs_data = pytest.mark.skipif(not _HAVE_DATA, reason="$EC_DATA catalogue not present")


def two_storey() -> StoreyHeights:
    return StoreyHeights(
        levels=[
            Level("GROUND FLOOR", 0.0, "A300"),
            Level("T/O F/F SECOND", 3.0, "A300"),
            Level("TOP OF ROOF", 7.873, "A300"),
        ],
        floor_assembly_mm=333.0,
    )


class TestLevelClassification:
    def test_floors_are_floors(self):
        assert Level("GROUND FLOOR", 0.0).is_floor
        assert Level("T/O F/F SECOND", 3.0).is_floor

    def test_roof_is_not_a_floor(self):
        lv = Level("TOP OF ROOF", 7.873)
        assert lv.is_roof
        assert not lv.is_floor

    def test_reference_lines_are_not_floors(self):
        """'ASSUMED GRADE' marks a datum, not a constructed level."""
        assert not Level("ASSUMED GRADE", -0.5).is_floor
        assert not Level("U/S OF FOOTING", -1.2).is_floor


class TestStoreyHeights:
    def test_floor_to_floor_from_consecutive_datums(self):
        assert two_storey().storey_heights_m() == [3.0, 3.0]

    def test_top_storey_is_inferred_from_the_one_below(self):
        """Using the roof level instead would include the roof pitch -- 1.87 m
        of it on AB_Fourplex_01."""
        sh = two_storey()
        assert sh.storey_heights_m()[-1] == 3.0
        assert sh.total_wall_height_m == 6.0
        # Not the roof level, which is 7.873.
        assert sh.total_wall_height_m < sh.roof_level_m

    def test_roof_level_is_available_separately(self):
        assert two_storey().roof_level_m == 7.873

    def test_implausible_storey_heights_are_discarded(self):
        sh = StoreyHeights(
            levels=[Level("GROUND FLOOR", 0.0), Level("T/O F/F SECOND", 0.4)]
        )
        assert sh.storey_heights_m() == []
        assert sh.total_wall_height_m is None

    def test_a_single_floor_datum_yields_nothing(self):
        sh = StoreyHeights(levels=[Level("GROUND FLOOR", 0.0)])
        assert sh.storey_heights_m() == []
        assert "fewer than two floor datums" in sh.missing[0]

    def test_duplicate_datums_from_repeated_sections_collapse(self):
        """A301 repeats the same ladder three times, once per section."""
        sh = StoreyHeights(
            levels=[Level("GROUND FLOOR", 0.0)] * 3 + [Level("T/O F/F SECOND", 3.0)] * 3
        )
        assert len(sh.floors) == 2
        assert sh.storey_heights_m() == [3.0, 3.0]


class TestTwoWallHeightBases:
    """A floor-to-floor height is not a wall height, and the two differ by
    20%. Which one a reference takeoff uses is a convention we cannot see, so
    both are reported with the basis named."""

    def test_gross_is_floor_to_floor(self):
        assert two_storey().total_wall_height_m == 6.0

    def test_net_deducts_the_floor_assembly(self):
        """Reproduces HOT2000's 2.667 + 2.515 = 5.182 rather than 3.0 + 3.0."""
        net = two_storey().net_wall_height_m
        assert net == pytest.approx(5.334, abs=0.01)
        assert abs(net - 5.182) / 5.182 < 0.05

    def test_net_is_unavailable_without_the_floor_depth(self):
        sh = StoreyHeights(
            levels=[Level("GROUND FLOOR", 0.0), Level("T/O F/F SECOND", 3.0)]
        )
        assert sh.net_wall_height_m is None
        assert any("floor assembly depth" in m for m in sh.missing)

    def test_wall_area_differs_by_basis(self):
        sh = two_storey()
        gross = sh.wall_area_m2(58.0, "gross")
        net = sh.wall_area_m2(58.0, "net")
        assert gross == pytest.approx(348.0, abs=1)
        assert net == pytest.approx(309.4, abs=1)
        assert gross > net

    def test_the_net_basis_is_closer_to_both_references(self):
        """IFC W2 = 287.6 m2, HOT2000 above-grade = 290.6 m2."""
        sh = two_storey()
        net, gross = sh.wall_area_m2(58.0, "net"), sh.wall_area_m2(58.0, "gross")
        for ref in (287.6, 290.6):
            assert abs(net - ref) < abs(gross - ref)


@needs_data
class TestAgainstRealSections:
    def test_alberta_fourplex_levels(self):
        from ecarbon.extract.levels import storey_heights_for

        sh = storey_heights_for(get_design("AB_Fourplex_01"), floor_assembly_mm=333.0)
        elevations = sorted({lv.elevation_m for lv in sh.levels})
        assert 0.0 in elevations
        assert 3.0 in elevations
        assert sh.roof_level_m == pytest.approx(7.873, abs=0.01)
        assert sh.storey_heights_m() == [3.0, 3.0]

    def test_the_inference_is_recorded(self):
        """The scope requires assumptions to be documented and viewable."""
        from ecarbon.extract.levels import storey_heights_for

        sh = storey_heights_for(get_design("AB_Fourplex_01"), floor_assembly_mm=333.0)
        assert any("inferred" in n for n in sh.notes)

    def test_levels_are_traceable_to_a_sheet(self):
        from ecarbon.extract.levels import storey_heights_for

        sh = storey_heights_for(get_design("AB_Fourplex_01"))
        assert sh.sources
        assert any("A30" in s for s in sh.sources)
        assert all(lv.sheet for lv in sh.levels)


class TestElevationsSurviveTextRepair:
    """A real textrepair bug found here: '7.873 m' became 'XOYXTA\\x8e'.

    The single-trailing-letter exception that lets 'A101a' through also let
    every unit-suffixed dimension through to be shifted into nonsense, which
    silently emptied the level ladder on every design.
    """

    @pytest.mark.parametrize(
        "text", ["7.873 m", "3.000 m", "0.000 m", "-1.200 m", "915mm", "130mm", "12025"]
    )
    def test_dimensions_with_units_are_untouched(self, text):
        from ecarbon.intake.textrepair import repair

        assert repair(text) == (text, False)

    @pytest.mark.parametrize(
        ("broken", "want"),
        [("&$7$/2*8(", "CATALOGUE"), ("$\x13\x13\x17", "A004"), ("$\x14\x13\x14D", "A101a")],
    )
    def test_mojibake_still_repairs(self, broken, want):
        from ecarbon.intake.textrepair import repair

        assert repair(broken)[0] == want


class TestImperialDatums:
    """North American sections print datums in feet and inches, not metres."""

    @pytest.mark.parametrize(
        ("text", "want"),
        [
            ("3.000 m", 3.0),
            ("10'-1 1/2\"", 3.086),
            ("-8'-6\"", -2.591),
            ("20'-0\"", 6.096),
            ("0'-0\"", 0.0),
            ("0\"", 0.0),
            ("-6\"", -0.152),
            ("6\"", None),  # a bare inch figure is a dimension, not a datum
            ("2X6", None),
        ],
    )
    def test_elevation_text(self, text, want):
        from ecarbon.extract.levels import _elevation_m

        assert _elevation_m(text) == want

    def test_a_datum_centred_under_a_wide_label_is_paired(self):
        import pymupdf

        from ecarbon.extract.levels import levels_on_page

        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((100, 100), "TOP OF PLATE HEIGHT", fontsize=8)
        page.insert_text((145, 112), "8' - 1\"", fontsize=8)
        page.insert_text((300, 112), "12'-0\"", fontsize=8)  # another ladder's, far right
        assert [lv.elevation_m for lv in levels_on_page(page)] == [2.464]

    def test_a_copy_paired_with_a_nearby_dimension_is_outvoted(self):
        from ecarbon.extract.levels import outvote_strays

        got = outvote_strays(
            [
                Level("SECOND FLOOR", 3.086),
                Level("-Second Floor", 3.086),
                Level("-SECOND FLOOR", 0.356),  # a floor-depth dimension, nearer
                Level("ROOF", 6.0),
            ]
        )
        assert sorted({lv.elevation_m for lv in got}) == [3.086, 6.0]

    def test_one_floor_in_two_datum_systems_is_one_floor(self):
        sh = StoreyHeights(
            levels=[
                Level("GROUND FLOOR", -3.0),
                Level("GROUND FLOOR (B)", -2.85),
                Level("MAIN FLOOR", 0.0),
                Level("MAIN FLOOR (B)", 0.15),
                Level("SECOND FLOOR", 3.0),
            ]
        )
        assert [lv.elevation_m for lv in sh.floors] == [-3.0, 0.0, 3.0]
        assert sh.storey_heights_m()[:2] == [3.0, 3.0]

    def test_one_storey_takes_its_height_from_the_plate(self):
        sh = StoreyHeights(levels=[Level("GROUND FLOOR", 0.0), Level("PLATE HEIGHT", 2.464)])
        assert sh.storey_heights_m() == [2.464]
        assert not any("floor datums" in m for m in sh.missing)

    def test_one_storey_without_a_plate_stays_unknown(self):
        sh = StoreyHeights(levels=[Level("GROUND FLOOR", 0.0), Level("TOP OF ROOF", 5.0)])
        assert sh.storey_heights_m() == []
        assert "fewer than two floor datums" in sh.missing[0]

    def test_a_plate_height_has_no_floor_to_deduct(self):
        sh = StoreyHeights(
            levels=[Level("GROUND FLOOR", 0.0), Level("PLATE HEIGHT", 2.464)], floor_assembly_mm=333.0
        )
        assert sh.net_wall_height_m == 2.464

    def test_a_metric_elevation_past_14pt_stays_unpaired(self):
        # The 16 pt reach is for imperial ladders; widening it for metric paired
        # AB_ADU_02's "2546 CEILING" note with a 2.540 m figure below it.
        import pymupdf

        from ecarbon.extract.levels import levels_on_page

        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((100, 100), "2546 CEILING", fontsize=8)
        page.insert_text((100, 115), "2.540 m", fontsize=8)
        assert levels_on_page(page) == []

    def test_a_ceiling_datum_is_not_a_floor(self):
        assert not Level("2546 CEILING", 2.54).is_floor


def test_a_single_storey_wall_tops_out_at_the_underside_of_the_roof_framing():
    from ecarbon.extract.levels import Level, StoreyHeights

    for roof in ("U/S ROOF FRAMING", "U.S. ROOF FRAMING"):
        h = StoreyHeights(
            levels=[Level("T/O F/F GROUND", 0.0, "A300"), Level(roof, 2.505, "A300")],
            floor_assembly_mm=333,
        )
        assert h.storey_heights_m() == [2.505]


class TestGlyphShiftedSections:
    """Ontario's sections are glyph-ID encoded (0x1D). The global repair
    decodes some spans and refuses others, which cut the ladder at the second
    floor of a three-storey building."""

    def test_a_refused_label_and_elevation_are_recovered(self):
        from ecarbon.extract.levels import _elevation_m, repair_level_span

        assert repair_level_span("7\x122\x03)\x12)\x037+,5'") == "T/O F/F THIRD"
        value = repair_level_span("\x14\x13\x11\x18\x13\x13\x03P\x12\x03\x16\x17\n\x10\x18\x03\x16\x12\x1b\x05")
        assert _elevation_m(value) == 10.5

    def test_plain_text_and_unrecoverable_spans_are_left_alone(self):
        from ecarbon.extract.levels import repair_level_span

        assert repair_level_span("GROUND FLOOR") == "GROUND FLOOR"
        assert repair_level_span("\x01\x02\x03") == "\x01\x02\x03"


@needs_data
def test_ontario_multiplexes_read_three_storeys():
    from ecarbon.extract.levels import storey_heights_for

    h = storey_heights_for(get_design("ON_Sixplex"))
    assert h.n_storeys == 3


def test_a_dotted_top_of_slab_is_the_floor_under_a_plate():
    """US marker: T.O.S. 0'-0" under PLATE 8'-1" gives one 8'-1" storey."""
    import pymupdf

    from ecarbon.extract.levels import levels_on_page

    doc = pymupdf.open()
    page = doc.new_page(width=600, height=400)
    for y, text in ((100, "PLATE"), (112, "8' - 1\""), (240, "T.O.S."), (252, "0' - 0\"")):
        page.insert_text((300, y), text, fontsize=8)
    levels = levels_on_page(page)
    assert StoreyHeights(levels=levels).storey_heights_m() == [2.464]


class TestValueFirstDatums:
    """US sections print the value before the label in one span."""

    def test_a_plate_and_floor_read_value_first(self):
        from ecarbon.extract.levels import _LEAD_LABEL_RE, _LEADING_ELEV_RE

        m = _LEADING_ELEV_RE.match('8\'-0" PLATE HEIGHT')
        assert m and _LEAD_LABEL_RE.fullmatch(m.group(2))
        m = _LEADING_ELEV_RE.match('0\'-0" FINISHED FLOOR')
        assert m and _LEAD_LABEL_RE.fullmatch(m.group(2))

    @pytest.mark.parametrize("text", ['8\'-0" TOP OF TRELLIS', '7\'-4" BOTTOM OF BEAM', '0\'-8" TOP OF COLUMN'])
    def test_other_tops_are_not_levels(self, text):
        from ecarbon.extract.levels import _LEAD_LABEL_RE, _LEADING_ELEV_RE

        m = _LEADING_ELEV_RE.match(text)
        assert not (m and _LEAD_LABEL_RE.fullmatch(m.group(2)))


class TestTopOfSlabDatum:
    """Santa Cruz's sections: 'T.O.S. 0'-0"' and 'PLATE 8'-1"'."""

    def test_top_of_slab_at_zero_is_the_floor(self):
        from ecarbon.extract.levels import Level, StoreyHeights

        h = StoreyHeights(levels=[Level("T.O.S.", 0.0), Level("PLATE", 2.464)])
        assert h.n_storeys == 1
        assert h.storey_heights_m() == [2.464]

    def test_top_of_steel_above_zero_is_not_a_floor(self):
        from ecarbon.extract.levels import Level

        assert not Level("T.O.S.", 3.1).is_floor


class TestStoreysFromFloorPlans:
    """No level on any section: the storeys the floor plans name, at a stated
    standard height, assumed."""

    def _sheets(self, *titles):
        from types import SimpleNamespace

        return [SimpleNamespace(sheet_type=SimpleNamespace(value="floor_plan"), title=t) for t in titles]

    def test_one_plan_is_one_assumed_storey(self):
        from ecarbon.extract.levels import StoreyHeights
        from ecarbon.takeoff.framing import SINGLE_STOREY_PLATE_M, no_datum_single_storey

        h = no_datum_single_storey(StoreyHeights(), self._sheets("FOUNDATION, FLOOR AND ROOF PLANS"), object())
        assert h.assumed and h.storey_heights_m() == [SINGLE_STOREY_PLATE_M]

    def test_ground_and_second_are_two(self):
        from ecarbon.extract.levels import StoreyHeights
        from ecarbon.takeoff.framing import no_datum_single_storey

        h = no_datum_single_storey(StoreyHeights(), self._sheets("FLOOR PLAN", "SECOND FLOOR PLAN"), object())
        assert h.n_storeys == 2 and len(h.storey_heights_m()) == 2

    def test_nothing_is_assumed_where_a_level_was_read_or_plans_are_unclear(self):
        from ecarbon.extract.levels import Level, StoreyHeights
        from ecarbon.takeoff.framing import no_datum_single_storey

        assert no_datum_single_storey(StoreyHeights(levels=[Level("MAIN FLOOR", 0.0)]), self._sheets("FLOOR PLAN"), object()) is None
        assert no_datum_single_storey(StoreyHeights(), self._sheets("FLOOR PLAN", "BASEMENT PLAN"), object()) is None
        assert no_datum_single_storey(StoreyHeights(), self._sheets("FLOOR PLAN", "FLOOR PLAN"), object()) is None
        assert no_datum_single_storey(StoreyHeights(), self._sheets("FLOOR PLAN"), None) is None
