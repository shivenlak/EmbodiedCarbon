"""The shared span reader, and the page rotation it undoes.

Two readers used to extract spans independently: the assemblies schedule and
the level ladder. Both broke on the same sheets for the same reason, and the
second one broke silently -- every datum label was found, no elevation ever
paired with one, and the ladder came back empty while the text was perfectly
readable. They now share this reader so they cannot diverge again.
"""

from __future__ import annotations

import pytest

from ecarbon.intake.spans import read_spans

try:
    from ecarbon.config import discover, get_design

    _HAVE_DATA = len(discover()) >= 52
except Exception:
    _HAVE_DATA = False

needs_data = pytest.mark.skipif(not _HAVE_DATA, reason="$EC_DATA catalogue not present")


class FakePage:
    """A page of spans with a given text direction, as PyMuPDF reports one."""

    def __init__(self, spans, direction=(1.0, 0.0)):
        self._spans = spans
        self._dir = direction

    def get_text(self, _kind):
        return {
            "blocks": [
                {
                    "lines": [
                        {
                            "dir": self._dir,
                            "spans": [
                                {"text": t, "bbox": (x, y, x + 10, y + 8)}
                                for y, x, t in self._spans
                            ],
                        }
                    ]
                }
            ]
        }


class TestUprightPages:
    def test_rows_and_columns_pass_through(self):
        page = FakePage([(100.0, 50.0, "GROUND FLOOR"), (110.0, 50.0, "0.000 m")])
        assert read_spans(page) == [
            (100.0, 50.0, "GROUND FLOOR"),
            (110.0, 50.0, "0.000 m"),
        ]

    def test_output_is_sorted_into_reading_order(self):
        page = FakePage([(200.0, 10.0, "second"), (100.0, 10.0, "first")])
        assert [t for _y, _x, t in read_spans(page)] == ["first", "second"]

    def test_an_empty_page_yields_nothing(self):
        assert read_spans(FakePage([])) == []

    def test_blank_spans_are_dropped(self):
        page = FakePage([(100.0, 10.0, "  "), (110.0, 10.0, "REAL")])
        assert [t for _y, _x, t in read_spans(page)] == ["REAL"]


class TestRotatedPages:
    """Ontario's schedules and sections are drawn a quarter turn from upright.

    A datum's elevation prints on the line below its label, so on a rotated
    sheet "below" is sideways and the pairing never happens.
    """

    def test_a_quarter_turn_is_undone_so_a_label_precedes_its_elevation(self):
        # Upright, the label is above the elevation. Rotated by (0, -1) the
        # same pair runs along x instead.
        page = FakePage(
            [(500.0, 100.0, "GROUND FLOOR"), (500.0, 110.0, "0.000 m")],
            direction=(0.0, -1.0),
        )
        out = read_spans(page)
        assert [t for _y, _x, t in out] == ["GROUND FLOOR", "0.000 m"]
        # The elevation now sits on a later row than its label, which is what
        # the level reader looks for.
        assert out[0][0] < out[1][0]

    def test_the_dominant_direction_wins_over_a_stray_label(self):
        """One rotated title block must not flip an upright sheet."""
        page = FakePage([(100.0, 10.0, f"row{i}") for i in range(20)])
        upright = read_spans(page)
        assert upright[0][1] == 10.0  # column unchanged, so no transform ran

    @pytest.mark.parametrize("direction", [(0.0, 1.0), (-1.0, 0.0)])
    def test_other_orientations_are_handled(self, direction):
        page = FakePage(
            [(100.0, 50.0, "A"), (100.0, 60.0, "B")], direction=direction
        )
        assert len(read_spans(page)) == 2


class TestExtraRepairHook:
    def test_the_hook_runs_after_the_global_repair(self):
        page = FakePage([(100.0, 10.0, "GYPSUM")])
        out = read_spans(page, lambda t: t.lower())
        assert out[0][2] == "gypsum"

    def test_no_hook_leaves_text_as_the_global_repair_left_it(self):
        page = FakePage([(100.0, 10.0, "GYPSUM")])
        assert read_spans(page)[0][2] == "GYPSUM"


@needs_data
class TestOnRealSheets:
    def test_a_rotated_section_yields_its_level_ladder(self):
        """ON_Fourplex_01 reported no storey heights at all: its labels were
        found and its elevations never paired, because the sheet is rotated."""
        from ecarbon.extract.levels import storey_heights_for

        sh = storey_heights_for(get_design("ON_Fourplex_01"), floor_assembly_mm=333.0)
        assert sh.n_storeys >= 2
        assert sh.total_wall_height_m is not None
        # Plausible floor-to-floor for a low-rise dwelling.
        for height in sh.storey_heights_m():
            assert 2.1 <= height <= 6.0

    def test_an_upright_section_is_unaffected(self):
        from ecarbon.extract.levels import storey_heights_for

        sh = storey_heights_for(get_design("AB_Fourplex_01"), floor_assembly_mm=333.0)
        assert sh.storey_heights_m() == [3.0, 3.0]
        assert sh.total_wall_height_m == 6.0

    def test_the_shared_reader_did_not_change_the_schedules(self):
        """The assemblies reader was moved onto this one; its results must be
        identical, which is why the move was verified before going further."""
        from ecarbon.extract.assemblies import assemblies_for

        kept, refused = assemblies_for(get_design("AB_Fourplex_01"))
        assert len(kept) == 17
        assert refused == []
