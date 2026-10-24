"""Scale calibration.

A wrong scale multiplies every downstream quantity by a constant factor and
nothing else in the pipeline reveals it, so the parsing is pinned case by case
and the calibration is checked against IFC ground truth.
"""

from __future__ import annotations

import pytest

from ecarbon.geometry.scale import (
    PT_TO_MM,
    ScaleEstimate,
    ScaleSource,
    parse_dimension,
    parse_imperial,
    parse_metric,
    parse_scale_text,
)


class TestMetricDimensions:
    @pytest.mark.parametrize(
        ("text", "want"),
        [
            ("7000", 7000.0),
            ("6453", 6453.0),
            ("98", 98.0),
            ("915mm", 915.0),  # SKMB writes the unit
            ("915 mm", 915.0),
            ("98MM", 98.0),
        ],
    )
    def test_parses(self, text, want):
        assert parse_metric(text) == pytest.approx(want)

    @pytest.mark.parametrize("text", ["2", "5", "A101", "", "SCALE", "1.5", "100001"])
    def test_rejects(self, text):
        assert parse_metric(text) is None

    def test_rejects_implausible_runs(self):
        # Below 20mm or above 100m is a callout or a sheet number, not a run.
        assert parse_metric("10") is None
        assert parse_metric("999999") is None


class TestImperialDimensions:
    @pytest.mark.parametrize(
        ("text", "want"),
        [
            ("23' - 0\"", 7010.4),
            ("9'-10 1/8\"", 3000.4),
            ("14'-3\"", 4343.4),
            ("7' 10\"", 2387.6),
            ("[3'-0\"]", 914.4),  # SKMB brackets its imperial
            ("[4'-7 3/8\"]", 1406.5),
            ("3 7/8\"", 98.4),  # inches only
        ],
    )
    def test_parses(self, text, want):
        assert parse_imperial(text) == pytest.approx(want, abs=1.0)

    @pytest.mark.parametrize("text", ["A101", "W2", "", "SECTIONS"])
    def test_rejects(self, text):
        assert parse_imperial(text) is None


class TestDualUnitLabels:
    """Three separators are in use across the catalogue, and the two values
    being present in one label is a free cross-check on our own parsing."""

    @pytest.mark.parametrize(
        ("text", "want"),
        [
            ("800 / 2'-7 1/2\"", 800.0),  # AB, ON
            ("1500 / 4'-11\"", 1500.0),
            ("915mm  [3'-0\"]", 915.0),  # SKMB
            ("2000 (6'-6 3/4\")", 2000.0),
        ],
    )
    def test_prefers_metric_when_both_agree(self, text, want):
        value, system = parse_dimension(text)
        assert value == pytest.approx(want)
        assert system == "dual"

    def test_rejects_when_the_two_units_disagree(self):
        # A label claiming two different lengths is corrupt; believing either
        # half would be a guess.
        value, system = parse_dimension("7000 / 2'-0\"")
        assert value is None
        assert system == "conflict"


class TestScaleText:
    @pytest.mark.parametrize(
        ("text", "ratio"),
        [
            ("SCALE: 1:50", 50.0),
            ("1:100", 100.0),
            ('1/4" = 1\'-0"', 48.0),
            ('SCALE: 1/8"=1\'0"', 96.0),
            ('3/16" = 1\'-0"', 64.0),
        ],
    )
    def test_parses(self, text, ratio):
        mm_per_pt = parse_scale_text(text)
        assert mm_per_pt is not None
        assert mm_per_pt / PT_TO_MM == pytest.approx(ratio, rel=0.01)

    @pytest.mark.parametrize("text", ["AS INDICATED", "SCALE:", "", "NOT TO SCALE"])
    def test_rejects(self, text):
        assert parse_scale_text(text) is None


class TestEstimateSemantics:
    def test_ratio_conversion(self):
        est = ScaleEstimate(mm_per_pt=50.0 * PT_TO_MM, source=ScaleSource.DIMENSION_CHAIN)
        assert est.ratio == pytest.approx(50.0)

    def test_many_tight_samples_are_trustworthy(self):
        est = ScaleEstimate(
            mm_per_pt=17.62, source=ScaleSource.DIMENSION_CHAIN, n_samples=98, spread_pct=0.39
        )
        assert est.trustworthy

    def test_few_samples_are_not_trustworthy(self):
        est = ScaleEstimate(
            mm_per_pt=17.62, source=ScaleSource.DIMENSION_CHAIN, n_samples=2, spread_pct=0.1
        )
        assert not est.trustworthy

    def test_wide_spread_is_not_trustworthy(self):
        est = ScaleEstimate(
            mm_per_pt=17.62, source=ScaleSource.DIMENSION_CHAIN, n_samples=50, spread_pct=6.4
        )
        assert not est.trustworthy

    def test_stated_text_alone_is_not_trustworthy(self):
        """One number with nothing to check it against is not evidence."""
        est = ScaleEstimate(mm_per_pt=17.64, source=ScaleSource.SCALE_TEXT, n_samples=1)
        assert not est.trustworthy

    def test_stated_text_corroborated_is_trustworthy(self):
        est = ScaleEstimate(
            mm_per_pt=17.64,
            source=ScaleSource.SCALE_TEXT,
            n_samples=1,
            corroborated_by=[ScaleSource.DIMENSION_CHAIN],
        )
        assert est.trustworthy

    def test_no_scale_converts_nothing(self):
        est = ScaleEstimate(mm_per_pt=None, source=ScaleSource.NONE)
        assert not est.trustworthy
        assert est.mm(100.0) is None
        assert est.m2(100.0) is None
        assert est.ratio is None

    def test_area_conversion_squares_the_scale(self):
        est = ScaleEstimate(mm_per_pt=10.0, source=ScaleSource.DIMENSION_CHAIN)
        # 100 pt^2 * 100 mm^2/pt^2 = 10,000 mm^2 = 0.01 m^2
        assert est.m2(100.0) == pytest.approx(0.01)

    def test_length_conversion(self):
        est = ScaleEstimate(mm_per_pt=17.62, source=ScaleSource.DIMENSION_CHAIN)
        assert est.mm(100.0) == pytest.approx(1762.0)


# -- against the real catalogue --------------------------------------------

try:
    from ecarbon.config import discover, get_design

    _HAVE_DATA = len(discover()) >= 52
except Exception:
    _HAVE_DATA = False

needs_data = pytest.mark.skipif(not _HAVE_DATA, reason="$EC_DATA catalogue not present")


@needs_data
class TestAgainstRealDrawings:
    def test_alberta_fourplex_is_1_to_50(self):
        import pymupdf

        from ecarbon.geometry.scale import calibrate

        d = get_design("AB_Fourplex_01")
        doc = pymupdf.open(d.drawings_pdf)
        try:
            est = calibrate(doc[10])  # A101 MAIN FLOOR PLAN
        finally:
            doc.close()
        assert est.source is ScaleSource.DIMENSION_CHAIN
        assert est.ratio == pytest.approx(50.0, rel=0.01)
        assert est.n_samples >= 40
        assert est.spread_pct is not None and est.spread_pct < 1.0
        assert est.trustworthy

    def test_bc_uses_imperial_1_to_48(self):
        """BC draws at 1/4" = 1'-0"; a hardcoded metric scale would be 4% out."""
        import pymupdf

        from ecarbon.geometry.scale import calibrate
        from ecarbon.intake import inventory
        from ecarbon.models import SheetType

        d = get_design("BC_Fourplex_01")
        sheets, _, _ = inventory(d.drawings_pdf)
        plan = next(s for s in sheets if s.sheet_type is SheetType.FLOOR_PLAN)
        doc = pymupdf.open(d.drawings_pdf)
        try:
            est = calibrate(doc[plan.page])
        finally:
            doc.close()
        assert est.ratio == pytest.approx(48.0, rel=0.01)

    def test_ifc_envelope_excludes_site_elements(self):
        """Landscape slabs would inflate AB_Fourplex_01 from 7x22m to 31x46m."""
        from ecarbon.bench.ifc_truth import building_bbox

        bbox = building_bbox(str(get_design("AB_Fourplex_01").ifc))
        assert bbox is not None
        short, long = bbox.plan_mm
        assert short == pytest.approx(7000.0, abs=200.0)
        assert long == pytest.approx(22000.0, abs=300.0)

    def test_parsed_dimensions_match_ifc_envelope(self):
        """The end-to-end claim: what we read off the page matches reality."""
        import pymupdf

        from ecarbon.bench.ifc_truth import building_bbox
        from ecarbon.geometry.scale import find_dimension_labels
        from ecarbon.intake import inventory
        from ecarbon.models import SheetType

        d = get_design("AB_Fourplex_01")
        bbox = building_bbox(str(d.ifc))
        sheets, _, _ = inventory(d.drawings_pdf)
        plans = [s for s in sheets if s.sheet_type is SheetType.FLOOR_PLAN][:3]
        doc = pymupdf.open(d.drawings_pdf)
        try:
            values = [
                lbl.value_mm for s in plans for lbl in find_dimension_labels(doc[s.page])
            ]
        finally:
            doc.close()
        for target in bbox.plan_mm:
            closest = min(values, key=lambda v: abs(v - target))
            assert abs(closest - target) / target < 0.02, f"{target}mm not found among labels"


class TestStandardScaleGuard:
    """A ratio matching no conventional scale is the signature of a schedule
    column read as a dimension chain. AB_Fourplex_01's openings schedule
    produced 1:418 before this guard existed."""

    @pytest.mark.parametrize("ratio", [50.0, 48.0, 100.0, 20.0, 16.0, 96.0, 10.0])
    def test_conventional_scales_accepted(self, ratio):
        est = ScaleEstimate(
            mm_per_pt=ratio * PT_TO_MM,
            source=ScaleSource.DIMENSION_CHAIN,
            n_samples=50,
            spread_pct=0.3,
        )
        assert est.is_standard
        assert est.trustworthy

    @pytest.mark.parametrize("ratio", [418.5, 37.0, 1.7, 700.0])
    def test_nonsense_ratios_rejected(self, ratio):
        est = ScaleEstimate(
            mm_per_pt=ratio * PT_TO_MM,
            source=ScaleSource.DIMENSION_CHAIN,
            n_samples=50,
            spread_pct=0.3,
        )
        assert not est.is_standard
        assert not est.trustworthy, "tight agreement on a non-standard ratio is still wrong"

    def test_near_miss_is_tolerated(self):
        """Measurement noise puts 1:50 at 1:49.9; that must still pass."""
        est = ScaleEstimate(
            mm_per_pt=49.9 * PT_TO_MM,
            source=ScaleSource.DIMENSION_CHAIN,
            n_samples=98,
            spread_pct=0.39,
        )
        assert est.is_standard

    def test_nearest_standard(self):
        from ecarbon.geometry.scale import nearest_standard_ratio

        assert nearest_standard_ratio(49.9)[0] == 50.0
        assert nearest_standard_ratio(48.2)[0] == 48.0
        assert nearest_standard_ratio(15.6)[0] == 16.0
        assert nearest_standard_ratio(418.5)[1] > 4.0


@needs_data
class TestSchedulesHaveNoScale:
    def test_openings_schedule_is_not_given_a_scale(self):
        from ecarbon.config import get_design
        from ecarbon.intake import inventory
        from ecarbon.models import SheetType

        sheets, _, _ = inventory(get_design("AB_Fourplex_01").drawings_pdf, with_scale=True)
        for s in sheets:
            if s.sheet_type in {SheetType.OPENING_SCHEDULE, SheetType.ASSEMBLY_SCHEDULE}:
                assert s.scale is None, f"{s.sheet_no} is a table, not a scaled drawing"

    def test_plans_do_get_a_scale(self):
        from ecarbon.config import get_design
        from ecarbon.intake import inventory
        from ecarbon.models import SheetType

        sheets, _, _ = inventory(get_design("AB_Fourplex_01").drawings_pdf, with_scale=True)
        plans = [s for s in sheets if s.sheet_type is SheetType.FLOOR_PLAN]
        assert plans and all(s.scale for s in plans)
        for s in plans:
            assert 17.0 < s.scale < 18.0  # 1:50 metric
