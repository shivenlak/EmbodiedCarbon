"""The bill of quantities, and the carbon it produces end to end.

Two properties matter more than the numbers: nothing in the takeoff is a
constant, and a partial takeoff announces itself as partial.
"""

from __future__ import annotations

import pytest

from ecarbon.models import Confidence, ElementClass
from ecarbon.takeoff.builder import ELEMENT_CARBON_SHARE, coverage_report

try:
    from ecarbon.config import discover, get_design

    _HAVE_DATA = len(discover()) >= 52
except Exception:
    _HAVE_DATA = False

needs_data = pytest.mark.skipif(not _HAVE_DATA, reason="$EC_DATA catalogue not present")


class TestCoverageReport:
    def test_shares_sum_to_about_one(self):
        assert 0.95 <= sum(ELEMENT_CARBON_SHARE.values()) <= 1.05

    def test_empty_takeoff_covers_nothing(self):
        covered, missing = coverage_report([])
        assert covered == 0.0
        assert len(missing) == len(ELEMENT_CARBON_SHARE)

    def test_zero_quantity_lines_do_not_count_as_coverage(self):
        """The screw-pile line is deliberately 0 m3 because the piles are
        steel supplied by others; it must not make the foundation look done."""
        from ecarbon.models import Basis, Provenance, TakeoffLine, Unit

        line = TakeoffLine(
            id="ln-screw-piles",
            element_class=ElementClass.FOOTING,
            quantity=0.0,
            unit=Unit.M3,
            confidence=Confidence.ASSUMED,
            assumptions=["steel, by supplier"],
            basis=Basis(),
            provenance=Provenance(page=1),
        )
        covered, missing = coverage_report([line])
        assert covered == 0.0
        assert ElementClass.FOOTING in missing


@needs_data
class TestEndToEnd:
    @pytest.fixture(scope="class")
    def run(self):
        from ecarbon.bench.bpr import parse_bpr
        from ecarbon.carbon.calculate import calculate_carbon
        from ecarbon.carbon.store import LocalSnapshotProvider
        from ecarbon.models import ProjectFacts
        from ecarbon.takeoff.builder import build_takeoff

        d = get_design("AB_Fourplex_01")
        bp = parse_bpr(str(d.bpr[0]))
        facts = ProjectFacts(
            name=d.key, gfa_m2=bp.best_gfa_m2, gfa_basis="gross",
            storeys=bp.storeys, units=bp.units,
        )
        takeoff = build_takeoff(d, facts)
        carbon = calculate_carbon(takeoff, LocalSnapshotProvider())
        return takeoff, carbon, bp

    def test_produces_a_bill_of_quantities(self, run):
        takeoff, _, _ = run
        assert len(takeoff.lines) >= 4
        ids = {ln.id for ln in takeoff.lines}
        assert "ln-slab-on-grade" in ids
        assert "ln-exterior-wall" in ids

    def test_every_line_is_traceable_to_a_sheet(self, run):
        """Criterion 2: every quantity traceable to its source sheet."""
        takeoff, _, _ = run
        for ln in takeoff.lines:
            assert ln.provenance.sheet_no, f"{ln.id} has no sheet"
            assert ln.provenance.detail

    def test_confidence_is_labelled_and_assumptions_documented(self, run):
        takeoff, _, _ = run
        labels = {ln.confidence for ln in takeoff.lines}
        assert Confidence.MEASURED in labels
        assert Confidence.INFERRED in labels
        for ln in takeoff.lines:
            if ln.confidence is Confidence.ASSUMED:
                assert ln.assumptions, f"{ln.id} is assumed but documents nothing"

    def test_the_slab_is_measured_not_assumed(self, run):
        """Footprint measured from geometry, thickness stated on S201."""
        takeoff, _, _ = run
        slab = takeoff.line("ln-slab-on-grade")
        assert slab.confidence is Confidence.MEASURED
        assert slab.provenance.sheet_no == "S201"

    def test_concrete_matches_the_drawings_not_the_ifc(self, run):
        """The IFC models this foundation as one 454 mm layer, 61.9 m3. The
        drawings say a 130 mm slab on 200x1200 grade beams, about 32 m3."""
        takeoff, _, _ = run
        concrete = sum(
            ln.quantity
            for ln in takeoff.lines
            if ln.unit.value == "m3" and "Concrete" in (ln.material or "")
        )
        assert 25.0 < concrete < 45.0
        assert concrete < 50.0, "the IFC's lumped 454mm slab must not be reproduced"

    def test_screw_piles_contribute_no_concrete(self, run):
        takeoff, carbon, _ = run
        piles = takeoff.line("ln-screw-piles")
        assert piles.quantity == 0.0
        assert any("steel" in a.lower() for a in piles.assumptions)
        assert piles.id in carbon.uncounted_lines

    def test_carbon_is_a1_a3_only(self, run):
        _, carbon, _ = run
        assert carbon.modules == ["A1", "A2", "A3"]
        assert carbon.total_kg_co2e > 0

    def test_carbon_stays_below_the_published_a1_a5_ceiling(self, run):
        """A1-A3 is a subset of A1-A5, so exceeding it would be impossible."""
        _, carbon, bp = run
        assert carbon.total_kg_co2e < bp.a1_a3_upper_bound_kg()

    def test_missing_factors_are_reported_not_zeroed(self, run):
        _, carbon, _ = run
        assert carbon.uncounted_lines
        for lid in carbon.uncounted_lines:
            line = next(c for c in carbon.lines if c.line_id == lid)
            assert line.missing_reason
            assert line.kg_co2e is None

    def test_a_partial_takeoff_says_so(self, run):
        """A low carbon total that does not announce itself as partial is
        indistinguishable from a good result."""
        takeoff, _, _ = run
        partial = [g for g in takeoff.gaps if "PARTIAL" in g.message]
        assert partial, "no gap warns that the carbon total is partial"

        # Reconstruct the figure from the takeoff's own output rather than
        # recomputing it with different arguments. Classes this building does
        # not have leave the denominator, and the builder says which in its
        # own gaps -- so calling coverage_report() without them gave a
        # different percentage than the one reported, which is how this test
        # caught the inconsistency.
        absent = {
            cls
            for cls in ELEMENT_CARBON_SHARE
            if any(
                g.message.startswith(f"No {cls.value.replace('_', ' ')} is counted")
                for g in takeoff.gaps
            )
        }
        covered, missing = coverage_report(takeoff.lines, absent)
        assert 0.0 < covered < 1.0
        assert missing
        assert f"{covered:.0%}" in partial[0].message

    def test_an_element_the_building_lacks_is_not_called_missing(self, run):
        """This design sits on grade beams over screw piles with no basement,
        so it has no foundation wall and the grade beam is already counted as a
        footing. Reporting one as missing both understates the takeoff and
        sends the reader looking for a sheet nobody drew."""
        takeoff, _, _ = run
        # The variant note also ends "...only A101 is counted.", so match the
        # absence gap's actual shape rather than a loose substring.
        absent = [
            g
            for g in takeoff.gaps
            if g.message.startswith("No ") and " is counted." in g.message
        ]
        assert any("foundation wall" in g.message for g in absent)
        for gap in absent:
            assert gap.severity.value == "info"
            # The claim is only made where the drawings support it.
            assert "screw piles" in gap.message or "footing" in gap.message
        partial = next(g for g in takeoff.gaps if "PARTIAL" in g.message)
        assert "foundation wall" not in partial.message

    def test_contribution_analysis_is_produced(self, run):
        """Criterion 3 requires contribution analysis by material category."""
        _, carbon, _ = run
        assert carbon.by_material_category
        assert sum(x.pct_of_total for x in carbon.by_material_category) == pytest.approx(
            100.0, abs=1.0
        )


@needs_data
class TestSingleStoreyLimitation:
    def test_a_one_storey_design_reports_no_exterior_wall(self):
        """Storey height needs two floor datums, and a single-storey plan has
        one. The wall is omitted and gap-reported rather than guessed from the
        roof level, which would include the roof pitch."""
        from ecarbon.models import ProjectFacts
        from ecarbon.takeoff.builder import build_takeoff

        t = build_takeoff(
            get_design("AB_ADU_01"),
            ProjectFacts(name="AB_ADU_01", gfa_m2=73.0, gfa_basis="gross", storeys=1),
        )
        assert not any(ln.id == "ln-exterior-wall" for ln in t.lines)
        covered, missing = coverage_report(t.lines)
        assert ElementClass.EXTERIOR_WALL in missing
        assert any("exterior wall" in g.message for g in t.gaps)
