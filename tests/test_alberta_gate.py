"""Alberta regression gate: pin the numbers the sponsor is judged on.

This challenge is sponsored by an Alberta builder and scored finally against
Alberta plan sets nobody has seen. Alberta is therefore the only region whose
numbers must never silently move.

They can. Every extraction module is shared, so a change made for another
province is a change to Alberta's pipeline. Two near-misses in one night:
widening the name-column search for Atlantic silently dropped Quebec's N1
(11 -> 10 assemblies), and tightening the layer-name filter refused Quebec's
genuine W1 until a spacing callout was required. Either could as easily have
hit Alberta, and neither raised an error.

So Alberta's figures are asserted here exactly. If a change moves them, this
file fails and the change gets justified or reverted -- the regions are
independent only as long as something checks.

Numbers measured 2026-10-27. When one legitimately improves, update it here in
the same commit and say why in the message.
"""

from __future__ import annotations

import re

import pytest

try:
    from ecarbon.config import discover, get_design

    _HAVE_DATA = len(discover()) >= 52
except Exception:
    _HAVE_DATA = False

pytestmark = pytest.mark.skipif(
    not _HAVE_DATA, reason="$EC_DATA catalogue not present"
)

# Every Alberta design, with the assemblies its schedule yields and the share
# of the building its bill of quantities reaches.
ALBERTA = {
    # Coverage reached 100% on six of seven when interior partitions became
    # measurable (median 5.7% against the reference models). AB_ADU_01 stays at
    # 53%: a single-storey plan yields fewer than two floor datums, so there is
    # no wall height and therefore no wall, floor or partition area.
    "AB_ADU_01": {"assemblies": 17, "coverage": 53},
    "AB_ADU_02": {"assemblies": 17, "coverage": 100},
    "AB_Fourplex_01": {"assemblies": 17, "coverage": 100},
    "AB_Fourplex_02": {"assemblies": 17, "coverage": 100},
    "AB_Rowhouse_01": {"assemblies": 17, "coverage": 100},
    "AB_Rowhouse_02": {"assemblies": 17, "coverage": 100},
    "AB_Sixplex": {"assemblies": 19, "coverage": 100},
}


def takeoff_for(key: str):
    from ecarbon.bench.bpr import parse_bpr
    from ecarbon.models import ProjectFacts
    from ecarbon.takeoff.builder import build_takeoff

    design = get_design(key)
    bpr = parse_bpr(str(design.bpr[0])) if design.bpr else None
    facts = ProjectFacts(
        name=key,
        jurisdiction=bpr.location if bpr else None,
        gfa_m2=bpr.best_gfa_m2 if bpr else None,
        gfa_basis="gross",
        storeys=bpr.storeys if bpr else None,
        units=bpr.units if bpr else None,
    )
    return build_takeoff(design, facts)


def coverage_of(takeoff) -> int:
    """The percentage the takeoff itself reports, not a recomputation."""
    for gap in takeoff.gaps:
        m = re.search(r"roughly (\d+)%", gap.message)
        if m:
            return int(m.group(1))
    return 100


class TestAlbertaAssemblies:
    @pytest.mark.parametrize("key", sorted(ALBERTA))
    def test_no_alberta_assembly_is_ever_refused(self, key):
        """Alberta's schedules parse cleanly and must stay that way. A refusal
        here means a plausibility gate tightened for another province has
        started rejecting Alberta's work."""
        from ecarbon.extract.assemblies import assemblies_for

        _kept, refused = assemblies_for(get_design(key))
        assert refused == [], f"{key} now refuses: {refused}"

    @pytest.mark.parametrize("key", sorted(ALBERTA))
    def test_assembly_count_holds(self, key):
        from ecarbon.extract.assemblies import assemblies_for

        kept, _refused = assemblies_for(get_design(key))
        assert len(kept) == ALBERTA[key]["assemblies"]

    def test_the_reference_designs_build_up_is_unchanged(self):
        """AB_Fourplex_01's W2 is the wall every number in the pitch comes
        from: 9 layers, 229 mm, cladding unspecified, metal studs deferred,
        and the cavity pair detected."""
        from ecarbon.extract.assemblies import assemblies_for

        kept, _ = assemblies_for(get_design("AB_Fourplex_01"))
        w2 = kept["W2"]
        assert len(w2.layers) == 9
        assert w2.total_thickness_mm == 229.0
        assert w2.layers[0].is_placeholder
        assert w2.layers[5].deferred_to == "Structural"
        assert w2.layers[6].shares_cavity_with == 5

    @pytest.mark.parametrize(
        ("tag", "depth"), [("P1", 121.0), ("P2", 201.0), ("P3", 235.0)]
    )
    def test_partition_depths_still_match_the_ifc(self, tag, depth):
        from ecarbon.extract.assemblies import assemblies_for

        kept, _ = assemblies_for(get_design("AB_Fourplex_01"))
        assert kept[tag].total_thickness_mm == pytest.approx(depth, abs=1.0)


class TestAlbertaGeometry:
    def test_footprint_holds(self):
        from ecarbon.takeoff.builder import gather

        inputs, _sheets, _gaps = gather(get_design("AB_Fourplex_01"), 153.0)
        assert inputs.footprint is not None
        assert inputs.footprint.area_m2 == pytest.approx(154.0, abs=1.0)
        assert inputs.footprint.perimeter_m == pytest.approx(58.0, abs=0.5)
        # Alberta's sheets are upright and its area agrees with the stated
        # floor area, so neither fallback should be engaged.
        assert not inputs.footprint_uncorroborated

    def test_storey_heights_hold(self):
        from ecarbon.extract.levels import storey_heights_for

        sh = storey_heights_for(get_design("AB_Fourplex_01"), floor_assembly_mm=333.0)
        assert sh.storey_heights_m() == [3.0, 3.0]
        assert sh.total_wall_height_m == 6.0
        assert sh.net_wall_height_m == pytest.approx(5.334, abs=0.01)

    def test_the_foundation_is_read_in_full(self):
        """Grade beams on screw piles, with the slab thickness stated."""
        from ecarbon.extract.specs import foundation_spec_for

        spec = foundation_spec_for(get_design("AB_Fourplex_01"))
        assert spec.system == "grade_beam_on_screw_piles"
        assert spec.slab_thickness_mm == 130.0
        assert (spec.grade_beam_width_mm, spec.grade_beam_depth_mm) == (200.0, 1200.0)
        assert spec.screw_piles
        assert not spec.designer_declined
        assert spec.footing_width_mm is None


class TestAlbertaCoverage:
    @pytest.mark.parametrize("key", sorted(ALBERTA))
    def test_coverage_does_not_regress(self, key):
        expected = ALBERTA[key]["coverage"]
        actual = coverage_of(takeoff_for(key))
        assert actual >= expected, f"{key} coverage fell {expected}% -> {actual}%"

    def test_six_of_seven_reach_ninety_one_percent(self):
        """AB_ADU_01 is the single-storey outlier at 53%; the rest are 91%."""
        reached = sum(1 for k in ALBERTA if coverage_of(takeoff_for(k)) >= 91)
        assert reached >= 6


class TestAlbertaQuantities:
    """The reference design's bill of quantities, line by line.

    Every figure quoted in docs/pitch.md and docs/benchmark.md for
    AB_Fourplex_01 traces to these.
    """

    @pytest.fixture(scope="class")
    def takeoff(self):
        return takeoff_for("AB_Fourplex_01")

    def test_the_slab_is_measured_at_twenty_cubic_metres(self, takeoff):
        slab = takeoff.line("ln-slab-on-grade")
        assert slab.quantity == pytest.approx(20.02, abs=0.1)
        assert slab.confidence.value == "measured"
        assert slab.provenance.sheet_no == "S201"

    def test_the_grade_beam_holds(self, takeoff):
        assert takeoff.line("ln-grade-beam").quantity == pytest.approx(13.92, abs=0.1)

    def test_the_exterior_wall_area_holds(self, takeoff):
        assert takeoff.line("ln-exterior-wall").quantity == pytest.approx(309.36, abs=1.0)

    def test_openings_hold(self, takeoff):
        assert takeoff.line("ln-windows").quantity == pytest.approx(35.84, abs=0.5)
        # 40 doors, which is exactly what the IFC models.
        assert takeoff.line("ln-doors").quantity == 40.0

    def test_screw_piles_still_contribute_no_concrete(self, takeoff):
        piles = takeoff.line("ln-screw-piles")
        assert piles.quantity == 0.0
        assert any("steel" in a.lower() for a in piles.assumptions)

    def test_the_carbon_total_holds_both_ways(self, takeoff):
        """Reported with and without the measured partitions, because the
        partition run is the least certain quantity in the bill."""
        from ecarbon.carbon.calculate import calculate_carbon
        from ecarbon.carbon.store import LocalSnapshotProvider
        from ecarbon.takeoff.builder import PARTITION_LINE_PREFIX

        carbon = calculate_carbon(takeoff, LocalSnapshotProvider())
        assert carbon.modules == ["A1", "A2", "A3"]

        by_line = {c.line_id: c for c in carbon.lines}
        partitions = sum(
            by_line[ln.id].kg_co2e
            for ln in takeoff.lines
            if ln.id.startswith(PARTITION_LINE_PREFIX)
            and by_line.get(ln.id)
            and by_line[ln.id].kg_co2e
        )
        # Excluding partitions: the figure every earlier published number used,
        # unchanged, which is how we know nothing else moved.
        assert carbon.total_kg_co2e - partitions == pytest.approx(37536, rel=0.02)
        assert carbon.total_kg_co2e == pytest.approx(48613, rel=0.02)
        assert carbon.intensity_kg_co2e_per_m2 == pytest.approx(158.9, rel=0.02)

    def test_interior_partitions_are_measured_and_say_how_certain(self, takeoff):
        from ecarbon.takeoff.builder import PARTITION_LINE_PREFIX

        lines = [ln for ln in takeoff.lines if ln.id.startswith(PARTITION_LINE_PREFIX)]
        assert lines, "Alberta's partitions should be measured"
        for line in lines:
            # Measured geometry plus a stated depth, so inferred rather than
            # assumed -- but the uncertainty has to travel with the line.
            assert line.confidence.value == "inferred"
            joined = " ".join(line.assumptions)
            assert "median" in joined and "override" in joined

    def test_the_failed_partition_attempts_are_published(self, takeoff):
        """A reader deciding whether to trust the least certain line deserves
        to know four other approaches were tried and rejected first."""
        gaps = [g for g in takeoff.gaps if "least certain quantity" in g.message]
        assert gaps
        assert "350%" in gaps[0].message

    def test_the_total_stays_under_the_published_ceiling(self, takeoff):
        from ecarbon.bench.bpr import parse_bpr
        from ecarbon.carbon.calculate import calculate_carbon
        from ecarbon.carbon.store import LocalSnapshotProvider

        carbon = calculate_carbon(takeoff, LocalSnapshotProvider())
        bpr = parse_bpr(str(get_design("AB_Fourplex_01").bpr[0]))
        assert carbon.total_kg_co2e < bpr.a1_a3_upper_bound_kg()
