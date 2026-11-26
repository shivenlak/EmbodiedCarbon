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

    def test_a_complete_takeoff_does_not_claim_to_be_partial(self, run):
        """AB_Fourplex_01 reaches every element class once interior partitions
        are measured, so the partial warning must stop firing. The warning
        existing when it should not is the same fault as it missing when it
        should: both mislead."""
        takeoff, _, _ = run
        assert [g for g in takeoff.gaps if "PARTIAL" in g.message] == []

        absent = {
            cls
            for cls in ELEMENT_CARBON_SHARE
            if any(
                g.message.startswith(f"No {cls.value.replace('_', ' ')} is counted")
                for g in takeoff.gaps
            )
        }
        covered, missing = coverage_report(takeoff.lines, absent)
        assert covered == 1.0, "every applicable element class should be reached"
        assert missing == []

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
        # And with every other class reached, nothing is reported missing.
        covered, missing = coverage_report(
            takeoff.lines, {ElementClass.FOUNDATION_WALL}
        )
        assert covered == 1.0
        assert missing == []

    def test_contribution_analysis_is_produced(self, run):
        """Criterion 3 requires contribution analysis by material category."""
        _, carbon, _ = run
        assert carbon.by_material_category
        assert sum(x.pct_of_total for x in carbon.by_material_category) == pytest.approx(
            100.0, abs=1.0
        )


@needs_data
class TestSingleStoreyLimitation:
    def test_a_one_storey_design_reads_its_wall_height_off_the_elevation(self):
        """AB_ADU_01's sections give one floor datum and a ridge, never a
        plate, so the wall stood on an assumed 2.74 m plate. Its elevations
        state U/S ROOF FRAMING at 3.0 m, which levels.py now reads, so the
        wall height is inferred from the drawing (SKMB_ADU_01, whose
        elevations state no plate, still takes the assumed one)."""
        from ecarbon.models import ProjectFacts
        from ecarbon.takeoff.builder import build_takeoff

        t = build_takeoff(
            get_design("AB_ADU_01"),
            ProjectFacts(name="AB_ADU_01", gfa_m2=73.0, gfa_basis="gross", storeys=1),
        )
        wall = next(ln for ln in t.lines if ln.id == "ln-exterior-wall")
        assert wall.confidence.value != "assumed"
        assert not any("wall height is assumed" in a for a in wall.assumptions)
        covered, missing = coverage_report(t.lines)
        assert ElementClass.EXTERIOR_WALL not in missing


@needs_data
def test_a_slab_is_counted_once_and_its_insulation_layer_separately():
    # SK/MB's F1 states 152 mm of rigid insulation under a concrete slab whose
    # thickness it defers to structural; S101's slab schedule states it (S1,
    # 152 mm). The concrete is the one slab, read rather than assumed; the
    # insulation is its own line, not a second slab.
    from ecarbon.takeoff.builder import build_takeoff

    takeoff = build_takeoff(get_design("SKMB_Fourplex_01"))
    slab = [ln for ln in takeoff.lines if ln.id.startswith("ln-slab-on-grade")]
    concrete = [ln for ln in slab if ln.material and "Concrete" in ln.material]
    assert [ln.id for ln in concrete] == ["ln-slab-on-grade"]
    assert concrete[0].confidence is not Confidence.ASSUMED
    assert "152 mm" in concrete[0].description
    assert any(ln.material == "CMHC_Insulation, Rigid" for ln in slab)


@needs_data
def test_an_unreadable_foundation_takes_a_standard_one_marked_assumed():
    # ON_Fourplex_01 outlines its structural sheets' text: nothing about the
    # foundation can be read, so a standard Part 9 one stands in, assumed,
    # and says what a basement would do to it.
    from ecarbon.takeoff.builder import build_takeoff
    from ecarbon.takeoff.framing import UNREAD_FOUNDATION

    t = build_takeoff(get_design("ON_Fourplex_01"))
    by_id = {ln.id: ln for ln in t.lines}
    for lid in ("ln-slab-on-grade", "ln-strip-footing", "ln-foundation-wall"):
        assert by_id[lid].confidence is Confidence.ASSUMED
    assert UNREAD_FOUNDATION in by_id["ln-foundation-wall"].assumptions
    assert not any("cannot be produced" in g.message and "foundation plan" in g.message for g in t.gaps)
    # Said once, not once per foundation note.
    assert sum("Estimated instead" in g.message for g in t.gaps) == 1


@needs_data
def test_a_named_system_is_never_replaced_by_the_standard():
    from ecarbon.takeoff.builder import build_takeoff

    # SK/MB: the scheduled grade beam on screw piles (S101), not a strip footing.
    edge = build_takeoff(get_design("SKMB_Fourplex_01"))
    ids = {ln.id for ln in edge.lines}
    assert "ln-grade-beam" in ids
    assert not ids & {"ln-strip-footing", "ln-foundation-wall"}

    alberta = build_takeoff(get_design("AB_Fourplex_01"))
    assert not {ln.id for ln in alberta.lines} & {"ln-strip-footing", "ln-foundation-wall"}


@needs_data
def test_atlantic_frost_wall_is_counted_on_its_strip_footing():
    from ecarbon.takeoff.builder import build_takeoff

    t = build_takeoff(get_design("ATL_Sixplex"))
    wall = next(ln for ln in t.lines if ln.id == "ln-foundation-wall")
    assert wall.confidence is Confidence.ASSUMED
    assert "203 mm" in wall.basis.note or "203" in wall.description
    assert any(ln.id == "ln-strip-footing" for ln in t.lines)


@needs_data
def test_a_joist_layer_with_no_depth_still_gets_its_joists():
    # ON's F2 names "ENGINEERED WOOD JOIST OR I-JOIST" with an empty
    # thickness cell; the floor had no structure at all.
    from ecarbon.takeoff.builder import build_takeoff

    t = build_takeoff(get_design("ON_Fourplex_01"))
    assert any(ln.id.startswith("ln-floor-joists-f2") for ln in t.lines)
    note = next(g for g in t.gaps if "'ENGINEERED WOOD JOIST OR I-JOIST'" in g.message)
    assert "estimated from a stated standard" in note.message


@needs_data
def test_unmeasurable_partitions_are_assumed_from_floor_area_and_say_so():
    from ecarbon.takeoff.builder import (
        PARTITION_LINE_PREFIX,
        PARTITION_M2_PER_FLOOR_M2,
        build_takeoff,
    )

    # ATL_ADU_01's linework gives 2 m2 of run, a failed reading. (ON_Fourplex_01
    # used to be the example; its schedule depths now read and its run
    # measures 328 m2 against the IFC's 345.)
    t = build_takeoff(get_design("ATL_ADU_01"))
    parts = [ln for ln in t.lines if ln.id.startswith(PARTITION_LINE_PREFIX)]
    assert parts and all(ln.confidence is Confidence.ASSUMED for ln in parts)
    assert any(f"{PARTITION_M2_PER_FLOOR_M2} m2 per m2 of floor" in a for a in parts[0].assumptions)


@needs_data
def test_measured_partitions_are_kept_where_the_linework_reads():
    # Alberta's partitions are measured (median 5.7% against the IFC); the
    # floor-area estimate must never stand in for them.
    from ecarbon.takeoff.builder import PARTITION_LINE_PREFIX, build_takeoff

    t = build_takeoff(get_design("AB_Fourplex_01"))
    parts = [ln for ln in t.lines if ln.id.startswith(PARTITION_LINE_PREFIX)]
    assert parts and all(ln.confidence is Confidence.INFERRED for ln in parts)


def test_standard_stand_ins_name_the_code_of_the_country():
    # A US set's assumed lines cite the IRC, not Canada's Part 9; a Canadian
    # set, or one whose country is unknown, keeps the Part 9 wording exactly.
    from types import SimpleNamespace

    from ecarbon.intake.locale import Locale
    from ecarbon.takeoff.framing import (
        UNREAD_FOUNDATION,
        UNREAD_FOUNDATION_US,
        standard_code,
        unread_foundation_note,
    )

    us = SimpleNamespace(locale=Locale("imperial", "US", "US-CA", []))
    ca = SimpleNamespace(locale=Locale("metric", "CA", "CA-AB", []))
    unknown = SimpleNamespace(locale=None)
    assert standard_code(us) == "IRC"
    assert standard_code(ca) == standard_code(unknown) == "Part 9"
    assert unread_foundation_note(us) == UNREAD_FOUNDATION_US
    assert "Part 9" not in UNREAD_FOUNDATION_US and "frost wall" not in UNREAD_FOUNDATION_US
    assert unread_foundation_note(ca) == unread_foundation_note(unknown) == UNREAD_FOUNDATION


@needs_data
def test_a_family_tag_uses_its_first_scheduled_variant_and_says_so():
    """BC plans tag W1 and R1; the schedule defines only W1.1-W1.2 and
    R1.1-R1.3. The standard wall stood in for a wall the drawings state."""
    from ecarbon.takeoff.builder import build_takeoff

    t = build_takeoff(get_design("BC_Sixplex"))
    ids = {ln.id for ln in t.lines}
    assert any(i.startswith("ln-exterior-wall-w1.1-") for i in ids)
    assert not any(i.startswith("ln-exterior-wall-std-") for i in ids)
    assert any("plans tag W1" in g.message and "W1.1, the first" in g.message for g in t.gaps)


@needs_data
def test_a_refused_main_roof_is_not_priced_as_a_minor_one():
    """ATL_Fourplex_01 Option 2 tags R2a 13 times and the R4 deck 3; R2a is
    refused, so the roof is the assumed standard, not R4 over the footprint."""
    from ecarbon.takeoff.builder import build_takeoff

    t = build_takeoff(get_design("ATL_Fourplex_01_Technical_Design_Package_Option2"))
    ids = {ln.id for ln in t.lines}
    assert not any(i.startswith("ln-roof-assembly-r4-") for i in ids)
    assert any(i.startswith("ln-roof-assembly-std-r-") for i in ids)


@needs_data
def test_demising_walls_are_party_walls_inside_the_partition_run():
    """AB tags its demising wall P3, ATL tags W6; both are priced as party walls
    but keep the partition prefix, so the total without partitions drops them."""
    from ecarbon.takeoff.builder import PARTITION_LINE_PREFIX, build_takeoff

    for key, tag in (("AB_Fourplex_01", "p3"),
                     ("ATL_Fourplex_01_Technical_Design_Package_Option2", "w6")):
        party = [ln for ln in build_takeoff(get_design(key)).lines
                 if ln.element_class.value == "party_wall"]
        assert party and all(ln.id.startswith(PARTITION_LINE_PREFIX) for ln in party)
        assert any(ln.id.startswith(f"{PARTITION_LINE_PREFIX}-{tag}-") for ln in party)


@needs_data
def test_stairs_are_counted_off_the_plans_and_say_how():
    """AB_Fourplex_01's plans label each flight on both floors (4 riser labels,
    1 UP arrow); its IFC has 2 flights."""
    from ecarbon.takeoff.builder import build_takeoff

    st = build_takeoff(get_design("AB_Fourplex_01")).line("ln-stairs")
    assert st.element_class.value == "stair" and st.confidence.value == "assumed"
    assert "2 flight(s) of 16 risers" in st.description
    assert "riser label" in st.basis.note


@needs_data
def test_a_stated_block_foundation_says_it_is_priced_as_cast_concrete():
    from ecarbon.takeoff.builder import build_takeoff

    wall = build_takeoff(get_design("ON_Fourplex_01")).line("ln-foundation-wall")
    assert any("CONCRETE MASONRY UNITS" in a and "overstates" in a for a in wall.assumptions)
