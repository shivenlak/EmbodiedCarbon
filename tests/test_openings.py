"""Windows and doors: size from the schedule, count from the plans.

The quantity is the product of two different sheets, and the counting half is
where the error lives -- a plan set contains alternative versions of the same
storey, and summing them all counts that floor twice.
"""

from __future__ import annotations

import pytest

from ecarbon.extract.openings import (
    OPENING_TAG_RE,
    Opening,
    base_sheet,
    parse_ft_in,
)

try:
    from ecarbon.config import discover, get_design

    _HAVE_DATA = len(discover()) >= 52
except Exception:
    _HAVE_DATA = False

needs_data = pytest.mark.skipif(not _HAVE_DATA, reason="$EC_DATA catalogue not present")


class TestSheetVariants:
    @pytest.mark.parametrize(
        ("sheet", "want"),
        [("A101a", "A101"), ("A101", "A101"), ("A102", "A102"), ("S201", "S201")],
    )
    def test_a_trailing_letter_marks_a_variant_of_the_base_sheet(self, sheet, want):
        assert base_sheet(sheet) == want

    def test_no_sheet_number_is_handled(self):
        assert base_sheet(None) is None


class TestTagPattern:
    @pytest.mark.parametrize("tag", ["DA01", "DB02", "DD04", "WA01", "WB03", "WC01"])
    def test_real_tags_match(self, tag):
        assert OPENING_TAG_RE.match(tag)

    @pytest.mark.parametrize("text", ["W2", "P3", "A101", "DOOR", "140mm", "D1"])
    def test_other_drawing_text_does_not(self, text):
        """An assembly tag like W2 must not be read as a window instance."""
        assert not OPENING_TAG_RE.match(text)


class TestImperialCells:
    @pytest.mark.parametrize(
        ("text", "mm"),
        [("3'-0\"", 914.4), ("7'-8 1/2\"", 2349.5), ("6'-8\"", 2032.0), ("2'-4\"", 711.2)],
    )
    def test_feet_and_inches_convert(self, text, mm):
        assert parse_ft_in(text) == pytest.approx(mm, abs=1.0)

    @pytest.mark.parametrize("text", ["914", "N/A", "45 min", ""])
    def test_other_cells_are_not_dimensions(self, text):
        assert parse_ft_in(text) is None

    def test_the_two_unit_columns_agree_on_a_real_row(self):
        """DA01 states 914 mm and 3'-0", which is the sheet checking itself."""
        assert abs(914.0 - parse_ft_in("3'-0\"")) < 1.0


class TestOpeningArithmetic:
    def opening(self, **kw) -> Opening:
        base = {"tag": "WB01", "kind": "window", "width_mm": 600.0, "height_mm": 1200.0}
        return Opening(**{**base, **kw})

    def test_area_is_width_times_height(self):
        assert self.opening().area_m2 == pytest.approx(0.72, abs=0.001)

    def test_total_area_multiplies_by_the_count(self):
        o = self.opening()
        o.counts = {"A101": 12, "A102": 6}
        assert o.count == 18
        assert o.total_area_m2 == pytest.approx(12.96, abs=0.01)

    def test_a_tag_with_no_size_yields_no_area(self):
        o = self.opening(width_mm=None)
        o.counts = {"A101": 4}
        assert o.area_m2 is None
        assert o.total_area_m2 is None

    def test_an_uncounted_tag_contributes_nothing(self):
        assert self.opening().count == 0
        assert self.opening().total_area_m2 == 0.0


@needs_data
class TestAgainstTheRealSchedule:
    @pytest.fixture(scope="class")
    def result(self):
        from ecarbon.extract.openings import openings_for

        return openings_for(get_design("AB_Fourplex_01"))

    def test_both_schedules_are_read(self, result):
        openings, _notes = result
        assert len(openings) == 15
        assert sum(1 for o in openings if o.kind == "door") == 8
        assert sum(1 for o in openings if o.kind == "window") == 7

    def test_every_opening_has_a_size(self, result):
        openings, _notes = result
        for o in openings:
            assert o.width_mm and o.height_mm, f"{o.tag} has no size"

    def test_the_door_count_matches_the_ifc_exactly(self, result):
        """40 doors from two sheets of a PDF, against 40 in the 3D model."""
        openings, _notes = result
        doors = sum(o.count for o in openings if o.kind == "door")
        assert doors == 40

    def test_the_window_count_is_close_and_the_shortfall_is_honest(self, result):
        """38 against the IFC's 42. A tag written once against a mullioned
        assembly counts once, which is stated on the line rather than fixed by
        inflating the number."""
        openings, _notes = result
        windows = sum(o.count for o in openings if o.kind == "window")
        assert windows == 38
        assert abs(windows - 42) / 42 < 0.11

    def test_alternative_plans_of_one_storey_are_not_both_counted(self, result):
        """A101 and A101a are accessibility options for the same floor.
        Counting both gives 56 windows and 70 doors for a building with 42
        and 40."""
        openings, notes = result
        assert any("alternative versions of the same storey" in n for n in notes)
        assert any("A101a" in n for n in notes)
        # No tag is counted on both variants of one storey.
        for o in openings:
            bases = {b for b in o.counts}
            assert "A101a" not in bases, f"{o.tag} counted on the variant sheet too"

    def test_door_types_are_not_confused_with_the_diagram_labels(self, result):
        """The sheet carries a DOOR TYPES diagram whose labels share y bands
        with the schedule rows, and it put 'DOOR TYPE A' on the DD04 row."""
        openings, _notes = result
        by_tag = {o.tag: o for o in openings}
        assert by_tag["DD04"].type_name == "DOOR TYPE D"
        assert by_tag["DA01"].type_name == "DOOR TYPE A"

    def test_fire_ratings_are_captured_where_stated(self, result):
        openings, _notes = result
        by_tag = {o.tag: o for o in openings}
        assert by_tag["DA02"].fire_rating == "45 min"


@needs_data
class TestInTheTakeoff:
    def test_windows_and_doors_reach_the_bill_of_quantities(self):
        from ecarbon.models import ProjectFacts, Unit
        from ecarbon.takeoff.builder import build_takeoff, coverage_report

        t = build_takeoff(
            get_design("AB_Fourplex_01"),
            ProjectFacts(name="AB_Fourplex_01", gfa_m2=306.0, gfa_basis="gross", storeys=2),
        )
        window = t.line("ln-windows")
        door = t.line("ln-doors")
        # Windows priced by area, doors by the unit, because that is how each
        # factor is declared.
        assert window.unit is Unit.M2
        assert window.quantity == pytest.approx(35.84, abs=0.5)
        assert door.unit is Unit.EACH
        assert door.quantity == 40.0
        for line in (window, door):
            assert line.provenance.sheet_no == "A004"
            assert line.assumptions

        covered, missing = coverage_report(t.lines)
        assert covered >= 0.8
        from ecarbon.models import ElementClass

        assert ElementClass.WINDOW not in missing
        assert ElementClass.DOOR not in missing
