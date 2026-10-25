"""Footprint detection from vector geometry.

The footprint scales both foundation concrete (area x slab thickness) and
exterior wall area (perimeter x height), so an error here propagates into the
two largest carbon items at once.
"""

from __future__ import annotations

import pytest

from ecarbon.geometry.footprint import Footprint, Segment

try:
    from ecarbon.config import discover, get_design

    _HAVE_DATA = len(discover()) >= 52
except Exception:
    _HAVE_DATA = False

needs_data = pytest.mark.skipif(not _HAVE_DATA, reason="$EC_DATA catalogue not present")


class TestSegmentOrientation:
    def test_horizontal(self):
        assert Segment(1000, 0, 0, 10, 0, 1.0).is_horizontal
        assert not Segment(1000, 0, 0, 10, 0, 1.0).is_vertical

    def test_vertical(self):
        assert Segment(1000, 0, 0, 0, 10, 1.0).is_vertical

    def test_diagonal_is_neither(self):
        s = Segment(1000, 0, 0, 10, 10, 1.0)
        assert not s.is_horizontal and not s.is_vertical

    def test_near_horizontal_tolerated(self):
        """Drafting is not pixel-exact."""
        assert Segment(1000, 0, 0, 100, 2, 1.0).is_horizontal


class TestFootprintGeometry:
    def test_area_and_perimeter(self):
        fp = Footprint(width_m=7.0, depth_m=22.0)
        assert fp.area_m2 == pytest.approx(154.0)
        assert fp.perimeter_m == pytest.approx(58.0)

    def test_plan_is_orientation_free(self):
        """So a rotated plan does not read as a different building."""
        assert Footprint(width_m=22.0, depth_m=7.0).plan_m == (7.0, 22.0)
        assert Footprint(width_m=7.0, depth_m=22.0).plan_m == (7.0, 22.0)

    def test_confidence_requires_two_agreeing_signals(self):
        one = Footprint(width_m=7.0, depth_m=22.0, basis=["vector_path"], agreement_pct=0.5)
        assert not one.confident

        both = Footprint(
            width_m=7.0, depth_m=22.0, basis=["vector_path", "dim_text"], agreement_pct=0.5
        )
        assert both.confident

    def test_poor_agreement_is_not_confident(self):
        fp = Footprint(
            width_m=7.0, depth_m=22.0, basis=["vector_path", "dim_text"], agreement_pct=30.0
        )
        assert not fp.confident

    def test_no_agreement_value_is_not_confident(self):
        fp = Footprint(width_m=7.0, depth_m=22.0, basis=["vector_path", "dim_text"])
        assert not fp.confident


@needs_data
class TestAgainstRealDrawings:
    """The headline claim: geometry and stated dimensions agree with the IFC."""

    def _footprint(self, key: str):
        import pymupdf

        from ecarbon.geometry.footprint import detect_footprint
        from ecarbon.geometry.scale import calibrate
        from ecarbon.intake import inventory
        from ecarbon.models import SheetType

        d = get_design(key)
        sheets, _, _ = inventory(d.drawings_pdf)
        doc = pymupdf.open(d.drawings_pdf)
        try:
            for s in sheets:
                if s.sheet_type is SheetType.FLOOR_PLAN and s.readable:
                    fp = detect_footprint(doc[s.page], calibrate(doc[s.page]))
                    if fp and fp.confident:
                        return fp
        finally:
            doc.close()
        return None

    def test_alberta_fourplex_is_exact(self):
        """7.00 x 22.00 m, matching the IFC envelope to 0.0%."""
        fp = self._footprint("AB_Fourplex_01")
        assert fp is not None
        assert fp.plan_m[0] == pytest.approx(7.00, abs=0.1)
        assert fp.plan_m[1] == pytest.approx(22.00, abs=0.2)
        assert fp.area_m2 == pytest.approx(154.0, rel=0.03)

    def test_sheet_clutter_is_excluded(self):
        """Every long segment on the sheet gives 30.6 x 30.0 m -- border, grid
        lines and dimension lines. The building is 7 x 22."""
        fp = self._footprint("AB_Fourplex_01")
        assert fp is not None
        assert fp.plan_m[1] < 25.0, "sheet border or dimension lines leaked in"

    def test_the_chosen_lineweight_is_the_heaviest_drawn(self):
        """Walls are the section cut, so they carry the heaviest line."""
        fp = self._footprint("AB_Fourplex_01")
        assert fp is not None
        assert fp.stroke_width is not None and fp.stroke_width >= 1.0

    @pytest.mark.parametrize(
        ("key", "want"),
        [
            ("AB_Fourplex_01", (7.00, 22.00)),
            ("AB_ADU_01", (7.60, 9.84)),
            ("ATL_Fourplex_02", (12.72, 21.07)),
            ("BC_Fourplex_01", (6.78, 19.79)),
        ],
    )
    def test_matches_the_ifc_envelope_across_regions(self, key, want):
        fp = self._footprint(key)
        assert fp is not None, f"{key}: no confident footprint"
        for got, exp in zip(fp.plan_m, want, strict=False):
            assert abs(got - exp) / exp < 0.06, f"{key}: {fp.plan_m} vs {want}"

    def test_lineweight_varies_by_firm(self):
        """Which is why the group is chosen by agreement with the stated
        dimensions rather than by a hardcoded stroke width."""
        widths = {
            key: fp.stroke_width
            for key in ("AB_Fourplex_01", "ATL_Fourplex_02", "BC_Fourplex_01")
            if (fp := self._footprint(key))
        }
        assert len(widths) >= 2
        assert len(set(widths.values())) >= 2, f"expected differing weights, got {widths}"


@needs_data
class TestFeedsTheFoundationTakeoff:
    def test_slab_volume_from_footprint_and_stated_thickness(self):
        """The two halves of the foundation takeoff meeting: a stated 130 mm
        slab (from S201) over a measured footprint."""
        from ecarbon.extract.specs import foundation_spec_for

        d = get_design("AB_Fourplex_01")
        spec = foundation_spec_for(d)
        assert spec.slab_thickness_mm == 130.0

        import pymupdf

        from ecarbon.geometry.footprint import detect_footprint
        from ecarbon.geometry.scale import calibrate
        from ecarbon.intake import inventory
        from ecarbon.models import SheetType

        sheets, _, _ = inventory(d.drawings_pdf)
        doc = pymupdf.open(d.drawings_pdf)
        try:
            fp = next(
                f
                for s in sheets
                if s.sheet_type is SheetType.FLOOR_PLAN
                and s.readable
                and (f := detect_footprint(doc[s.page], calibrate(doc[s.page])))
                and f.confident
            )
        finally:
            doc.close()

        slab = spec.slab_volume_m3(fp.area_m2)
        # 154 m2 x 0.130 m = 20.0 m3. The IFC's 454 mm layer claims 61.9 m3.
        assert slab == pytest.approx(20.0, rel=0.1)
        assert slab < 30.0, "the IFC's lumped 454mm slab must not be reproduced"

    def test_grade_beam_run_uses_the_perimeter(self):
        from ecarbon.extract.specs import foundation_spec_for

        spec = foundation_spec_for(get_design("AB_Fourplex_01"))
        fp = Footprint(width_m=7.0, depth_m=22.0)
        beam = spec.grade_beam_volume_m3(fp.perimeter_m)
        assert beam == pytest.approx(58.0 * 0.24, rel=0.01)


class TestAreaHintGuards:
    """The floor-area hint rejects a confidently wrong footprint, but must not
    reject a correct one. Both directions cost real designs when got wrong."""

    def test_aspect_ratio_bound_exists(self):
        from ecarbon.geometry.footprint import MAX_ASPECT_RATIO

        assert 4.0 <= MAX_ASPECT_RATIO <= 8.0

    def test_area_bounds_are_generous_upward(self):
        """Because for a rowhouse the hint describes one unit while the drawing
        shows the block, so a correct footprint is legitimately a multiple."""
        from ecarbon.geometry.footprint import AREA_MAX_MULTIPLE, AREA_MIN_MULTIPLE

        assert AREA_MAX_MULTIPLE >= 2.0
        assert AREA_MIN_MULTIPLE <= 0.5

    def test_area_is_weighted_not_merely_a_tie_break(self):
        """Ranking lexicographically made the area term never fire, since two
        lineweight groups rarely agree to the same decimal."""
        from ecarbon.geometry.footprint import AREA_WEIGHT

        assert AREA_WEIGHT > 0


@needs_data
class TestNorSetsAreRefusedNotGuessed:
    def test_textless_sets_yield_no_footprint(self):
        """The 8 NOR sets have no readable dimension chains, so there is
        nothing to cross-check a lineweight group against. Refusing is correct;
        a footprint from lineweight alone would be a guess."""
        import pymupdf

        from ecarbon.geometry.footprint import detect_footprint
        from ecarbon.geometry.scale import calibrate
        from ecarbon.intake import inventory

        d = get_design("NOR_Fourplex_Municipal")
        sheets, _, _ = inventory(d.drawings_pdf)
        doc = pymupdf.open(d.drawings_pdf)
        try:
            confident = [
                fp
                for s in sheets[:20]
                if s.readable and (fp := detect_footprint(doc[s.page], calibrate(doc[s.page])))
                and fp.confident
            ]
        finally:
            doc.close()
        assert not confident
