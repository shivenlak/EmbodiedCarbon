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
