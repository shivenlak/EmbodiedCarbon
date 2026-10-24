"""The data contract is the one thing both work tracks depend on. These tests
pin the behaviour the rubric scores, not just the field names."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ecarbon.fixtures import example_carbon, example_takeoff
from ecarbon.models import (
    CarbonLine,
    Confidence,
    ElementClass,
    Provenance,
    TakeoffLine,
    TakeoffResult,
    Unit,
)


def _line(**kw) -> TakeoffLine:
    base = dict(
        id="x",
        element_class=ElementClass.EXTERIOR_WALL,
        quantity=10.0,
        unit=Unit.M2,
        confidence=Confidence.MEASURED,
        provenance=Provenance(page=1),
    )
    return TakeoffLine(**{**base, **kw})


class TestAssumptionsMustBeDocumented:
    """Scope: 'Assumptions must be documented and viewable to the user.'"""

    def test_assumed_without_assumption_is_rejected(self):
        with pytest.raises(ValidationError, match="documents no assumption"):
            _line(confidence=Confidence.ASSUMED)

    def test_assumed_with_assumption_is_accepted(self):
        ln = _line(confidence=Confidence.ASSUMED, assumptions=["defaulted to P2 build-up"])
        assert ln.assumptions

    def test_measured_needs_no_assumption(self):
        assert _line(confidence=Confidence.MEASURED).assumptions == []


class TestHumanCorrection:
    """Scope: 'Allow a human to correct any quantity and have the carbon result
    update. An estimator who cannot override the machine will not trust it.'"""

    def test_override_wins(self):
        ln = _line(quantity=10.0, user_override=12.5)
        assert ln.effective_quantity == 12.5
        assert ln.is_overridden

    def test_no_override_uses_extracted(self):
        ln = _line(quantity=10.0)
        assert ln.effective_quantity == 10.0
        assert not ln.is_overridden

    def test_override_of_zero_is_respected(self):
        # 0.0 is falsy; the implementation must not treat it as "no override".
        ln = _line(quantity=10.0, user_override=0.0)
        assert ln.effective_quantity == 0.0
        assert ln.is_overridden


class TestNoSilentSubstitution:
    """Scope: 'Where data is missing, does the tool say so rather than
    substitute silently?'"""

    def test_carbon_line_without_factor_needs_a_reason(self):
        with pytest.raises(ValidationError, match="missing_reason"):
            CarbonLine(line_id="x", quantity=1.0, unit=Unit.M2)

    def test_missing_reason_is_enough(self):
        cl = CarbonLine(
            line_id="x", quantity=1.0, unit=Unit.M2, missing_reason="no EPD for this product"
        )
        assert not cl.is_counted

    def test_uncounted_lines_are_excluded_from_total_but_listed(self):
        carbon = example_carbon()
        assert carbon.uncounted_lines, "fixture should exercise the missing-factor path"
        counted = sum(ln.kg_co2e or 0.0 for ln in carbon.lines if ln.is_counted)
        assert carbon.total_kg_co2e == pytest.approx(counted, rel=1e-3)
        for line_id in carbon.uncounted_lines:
            match = [ln for ln in carbon.lines if ln.line_id == line_id]
            assert match and match[0].missing_reason


class TestTakeoffIntegrity:
    def test_duplicate_line_ids_rejected(self):
        with pytest.raises(ValidationError, match="duplicate"):
            TakeoffResult(
                project=example_takeoff().project,
                source_file="f.pdf",
                lines=[_line(id="dup"), _line(id="dup")],
            )

    def test_negative_quantity_rejected(self):
        with pytest.raises(ValidationError):
            _line(quantity=-1.0)

    def test_every_line_has_provenance(self):
        for ln in example_takeoff().lines:
            assert ln.provenance.page is not None


class TestFixtureRoundTrip:
    """T builds the UI against this; it must survive JSON both ways."""

    def test_takeoff_round_trip(self):
        t = example_takeoff()
        assert TakeoffResult.model_validate_json(t.model_dump_json()) == t

    def test_carbon_round_trip(self):
        from ecarbon.models import CarbonResult

        c = example_carbon()
        assert CarbonResult.model_validate_json(c.model_dump_json()) == c

    def test_intensity_is_reported(self):
        c = example_carbon()
        assert c.intensity_kg_co2e_per_m2 and c.intensity_kg_co2e_per_m2 > 0
        assert c.intensity_basis == "gross"

    def test_modules_are_a1_a3_only(self):
        assert example_carbon().modules == ["A1", "A2", "A3"]

    def test_every_counted_factor_declares_its_scope(self):
        for ln in example_carbon().lines:
            if ln.factor:
                f = ln.factor
                assert f.source and f.declared_unit and f.geography and f.modules
                assert f.data_type in {"epd", "industry_avg", "generic"}

    def test_contributions_sum_to_total(self):
        c = example_carbon()
        assert sum(x.pct_of_total for x in c.by_material_category) == pytest.approx(100.0, abs=0.5)
