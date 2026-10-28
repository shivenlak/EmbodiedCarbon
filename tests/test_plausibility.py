"""Intensity is only as good as its denominator.

Every quantity in a bill can be right to the millimetre and the kgCO2e/m2
still be nonsense, because the floor area is a project fact the drawings may
not state. That is a failure mode with no symptom: nothing in the takeoff
looks wrong, because nothing in the takeoff is wrong.
"""

from __future__ import annotations

import pytest

from ecarbon.carbon.plausibility import (
    CATALOGUE_MAX,
    IMPLAUSIBLY_LOW_BELOW,
    intensity_warning,
)
from ecarbon.models import CarbonResult, ProjectFacts

try:
    from ecarbon.config import discover, get_design

    _HAVE_DATA = len(discover()) >= 52
except Exception:
    _HAVE_DATA = False

needs_data = pytest.mark.skipif(not _HAVE_DATA, reason="$EC_DATA catalogue not present")


def carbon(total: float, intensity: float | None) -> CarbonResult:
    return CarbonResult(
        takeoff_source="test",
        total_kg_co2e=total,
        intensity_kg_co2e_per_m2=intensity,
    )


class TestTheBandComesFromTheCatalogue:
    def test_the_ceiling_is_the_published_whole_life_maximum(self):
        """Ours is A1-A3, a subset of whole life, so the catalogue's highest
        whole-life figure is a ceiling we cannot legitimately exceed."""
        assert CATALOGUE_MAX == 731.0


class TestAnImpossibleIntensityIsReported:
    def test_above_the_whole_life_ceiling_is_blocking(self):
        gap = intensity_warning(carbon(56_343, 761.0), ProjectFacts(name="x", gfa_m2=74.0))
        assert gap is not None
        assert gap.severity.value == "blocking"
        assert "not possible" in gap.message

    def test_it_says_what_area_would_make_the_total_work(self):
        """A reader with the drawings in front of them can check that number
        against the building, which a bare 'implausible' cannot."""
        gap = intensity_warning(carbon(56_343, 761.0), ProjectFacts(name="x", gfa_m2=74.0))
        implied = 56_343 / CATALOGUE_MAX
        assert f"{implied:.0f} m2" in gap.message

    def test_it_blames_the_denominator_rather_than_the_quantities(self):
        gap = intensity_warning(carbon(56_343, 761.0), ProjectFacts(name="x", gfa_m2=74.0))
        assert "quantities may be right" in gap.message

    def test_an_ordinary_intensity_is_not_reported(self):
        assert intensity_warning(carbon(48_613, 158.9), ProjectFacts(name="x")) is None

    def test_the_catalogue_maximum_itself_is_allowed(self):
        assert intensity_warning(carbon(1.0, CATALOGUE_MAX), None) is None


class TestAnImplausiblyLowIntensity:
    def test_a_nearly_complete_takeoff_that_is_too_light_warns(self):
        gap = intensity_warning(
            carbon(2_000, 12.0), ProjectFacts(name="x", gfa_m2=400.0), coverage=1.0
        )
        assert gap is not None
        assert gap.severity.value == "warning"
        assert "site plan" in gap.message

    def test_a_partial_takeoff_is_not_scolded_for_being_light(self):
        """A 29% bill produces a 29% total. That is the gap report's job to
        say, and saying it twice adds nothing."""
        assert (
            intensity_warning(
                carbon(2_000, 12.0), ProjectFacts(name="x", gfa_m2=400.0), coverage=0.29
            )
            is None
        )

    def test_without_a_coverage_figure_nothing_is_claimed(self):
        assert intensity_warning(carbon(2_000, 12.0), ProjectFacts(name="x")) is None

    def test_the_floor_is_below_every_published_figure(self):
        assert IMPLAUSIBLY_LOW_BELOW < 141.0


class TestNoIntensityNoClaim:
    @pytest.mark.parametrize("value", [None, 0.0, -1.0])
    def test_a_missing_or_impossible_value_is_silent(self, value):
        assert intensity_warning(carbon(100.0, value), None) is None


@needs_data
class TestTheDenominatorFollowsTheDrawings:
    """AB_Rowhouse_01 is the design this work exists for: its bill is measured
    off drawings depicting the whole block, while its Building Performance
    Report states 74 m2 and one unit."""

    def takeoff_for(self, key):
        from ecarbon.bench.bpr import parse_bpr
        from ecarbon.takeoff.builder import build_takeoff

        design = get_design(key)
        bpr = parse_bpr(str(design.bpr[0]))
        facts = ProjectFacts(
            name=key,
            gfa_m2=bpr.best_gfa_m2,
            gfa_basis="gross",
            storeys=bpr.storeys,
            units=bpr.units,
        )
        return build_takeoff(design, facts), facts, bpr

    def test_the_stated_area_is_replaced_by_the_measured_block(self):
        takeoff, facts, bpr = self.takeoff_for("AB_Rowhouse_01")
        assert facts.gfa_m2 != bpr.best_gfa_m2, "the stated area should not stand"
        assert facts.gfa_m2 > bpr.best_gfa_m2

    def test_the_swap_is_reported_with_both_figures(self):
        """Replacing a project fact silently would be worse than the error it
        corrects."""
        takeoff, _, bpr = self.takeoff_for("AB_Rowhouse_01")
        gaps = [g for g in takeoff.gaps if g.message.startswith("Floor area: using")]
        assert gaps, "the substitution must be reported"
        assert gaps[0].severity.value == "blocking"
        assert f"{bpr.best_gfa_m2:.0f} m2 this project states" in gaps[0].message
        assert "Confirm which basis" in gaps[0].message

    def test_the_intensity_is_now_possible(self):
        from ecarbon.carbon.calculate import calculate_carbon
        from ecarbon.carbon.store import LocalSnapshotProvider

        takeoff, facts, _ = self.takeoff_for("AB_Rowhouse_01")
        result = calculate_carbon(takeoff, LocalSnapshotProvider())
        assert result.intensity_kg_co2e_per_m2 < CATALOGUE_MAX
        assert intensity_warning(result, facts, coverage=1.0) is None

    def test_a_design_that_agrees_is_left_alone(self):
        """AB_Fourplex_01's stated area matches what its drawings depict, so
        nothing should be substituted and nothing reported."""
        takeoff, facts, bpr = self.takeoff_for("AB_Fourplex_01")
        assert facts.gfa_m2 == bpr.best_gfa_m2
        assert not [
            g for g in takeoff.gaps if g.message.startswith("Floor area: using")
        ]


@needs_data
class TestAMeasuredAreaIsNotAlwaysBetter:
    """Replacing a stated area with a measured one is only an improvement when
    the measurement is credible as the same building.

    SKMB_ADU_01 measures a 908 m2 footprint against a stated 58 m2. The
    pipeline already reports that the two cannot be reconciled, and the first
    version of this work swapped the denominator anyway -- turning a
    questionable number into a certainly wrong one.
    """

    def built(self, key):
        from ecarbon.bench.bpr import parse_bpr
        from ecarbon.takeoff.builder import build_takeoff

        design = get_design(key)
        bpr = parse_bpr(str(design.bpr[0]))
        facts = ProjectFacts(
            name=key,
            gfa_m2=bpr.best_gfa_m2,
            gfa_basis="gross",
            storeys=bpr.storeys,
            units=bpr.units,
        )
        return build_takeoff(design, facts), bpr

    def test_a_footprint_too_large_to_be_a_unit_count_is_not_used(self):
        takeoff, bpr = self.built("SKMB_ADU_01")
        assert takeoff.project.gfa_m2 == bpr.best_gfa_m2
        gaps = [g for g in takeoff.gaps if g.message.startswith("Floor area: using")]
        assert gaps and "too large to be a unit count" in gaps[0].message

    def test_a_plausible_unit_ratio_is_still_used(self):
        """AB_Rowhouse_01's block is 3.9x its stated area -- a unit count, and
        the case this whole check exists to fix."""
        takeoff, bpr = self.built("AB_Rowhouse_01")
        assert takeoff.project.gfa_m2 > bpr.best_gfa_m2
        assert takeoff.project.gfa_m2 == pytest.approx(286, abs=2)

    def test_the_ratio_bound_follows_the_catalogue(self):
        from ecarbon.takeoff.builder import MAX_UNIT_RATIO

        # The largest building here is a sixplex, so a per-unit area should be
        # at most about a sixth of the block, with slack.
        assert 6.0 <= MAX_UNIT_RATIO <= 10.0
