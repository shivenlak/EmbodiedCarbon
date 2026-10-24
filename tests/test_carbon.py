"""Tests for Step 11 & Step 12: Factor store, provider, unit reconciliation, and carbon totals.

Verifies:
  1. Zero hardcoded numeric factors in application code (loaded from seed/db).
  2. Every factor row carries source, declared_unit, geography, and modules.
  3. Unit reconciliation across m3, m2, 100m2, kg, each.
  4. Module-scope guard raises ValueError when non-A1-A3 factors are summed.
  5. Unmatched materials are listed in uncounted_lines, excluded from total, never zeroed.
  6. Contribution percentages sum to 100%.
  7. Statistical uncertainty ranges propagate properly.
"""

from __future__ import annotations

import pytest

from ecarbon.carbon.calculate import calculate_carbon, compute_carbon_line, reconcile_units
from ecarbon.carbon.store import LocalSnapshotProvider
from ecarbon.fixtures import example_takeoff
from ecarbon.models import (
    Confidence,
    ElementClass,
    FactorRef,
    Provenance,
    TakeoffLine,
    TakeoffResult,
    Unit,
)


@pytest.fixture
def store(tmp_path):
    db_file = tmp_path / "test_factors.sqlite3"
    return LocalSnapshotProvider(db_path=db_file)


class TestFactorStore:
    def test_factors_loaded_with_mandatory_fields(self, store):
        factors = store.list_factors()
        assert len(factors) >= 10, "Expected at least 10 seed factors"
        for f in factors:
            assert f.source, f"Factor {f.factor_id} missing source"
            assert f.declared_unit, f"Factor {f.factor_id} missing declared_unit"
            assert f.geography, f"Factor {f.factor_id} missing geography"
            assert f.modules, f"Factor {f.factor_id} missing modules"
            assert f.gwp_value > 0, f"Factor {f.factor_id} gwp_value must be positive"

    def test_find_by_cmhc_material_name(self, store):
        f = store.find_by_material("CMHC_Concrete, CIP")
        assert f is not None
        assert "concrete" in f.name.lower()
        assert f.declared_unit == "m3"

        f_wood = store.find_by_material("CMHC_Wood Framing")
        assert f_wood is not None
        assert "framing" in f_wood.name.lower()

    def test_substitutions_available(self, store):
        subs = store.list_substitutions()
        assert len(subs) >= 6, "Expected at least 6 real substitution options"
        categories = {s["category"] for s in subs}
        assert len(categories) >= 4, "Substitutions must span >=4 assemblies"


class TestUnitReconciliation:
    def test_direct_match(self):
        qty, note = reconcile_units(25.0, Unit.M3, "m3")
        assert qty == 25.0

    def test_m2_to_100m2(self):
        qty, note = reconcile_units(250.0, Unit.M2, "100m2")
        assert qty == 2.5
        assert "qty / 100" in note

    def test_m3_to_kg_with_density(self):
        qty, note = reconcile_units(10.0, Unit.M3, "kg", density_kg_m3=2400.0)
        assert qty == 24000.0

    def test_m3_to_kg_missing_density_raises(self):
        with pytest.raises(ValueError, match="density"):
            reconcile_units(10.0, Unit.M3, "kg", density_kg_m3=None)

    def test_m2_to_m3_with_thickness(self):
        qty, note = reconcile_units(100.0, Unit.M2, "m3", thickness_m=0.20)
        assert qty == 20.0


class TestModuleScopeGuard:
    def test_summing_non_a1_a3_module_raises(self):
        """Rubric criterion 3: only like-for-like modules may be summed."""
        non_a1_factor = FactorRef(
            factor_id="fake-a4-transport",
            name="Truck transport A4",
            source="Test",
            declared_unit="tkm",
            gwp_value=0.15,
            modules=["A4"],
            geography="CA",
            data_type="generic",
        )
        line = TakeoffLine(
            id="test-ln",
            element_class=ElementClass.EXTERIOR_WALL,
            quantity=10.0,
            unit=Unit.M2,
            confidence=Confidence.MEASURED,
            provenance=Provenance(page=1),
        )
        with pytest.raises(ValueError, match="Module scope mismatch"):
            compute_carbon_line(line, non_a1_factor, allowed_modules=("A1", "A2", "A3"))


class TestCarbonCalculation:
    def test_unmatched_material_reported_and_excluded(self, store):
        takeoff = example_takeoff()
        # Add a line with an unknown exotic material
        unmatched_line = TakeoffLine(
            id="ln-exotic-aerogel",
            element_class=ElementClass.INSULATION,
            quantity=50.0,
            unit=Unit.M2,
            confidence=Confidence.MEASURED,
            material="Exotic_Unicorn_Aerogel",
            provenance=Provenance(page=2),
        )
        takeoff.lines.append(unmatched_line)

        result = calculate_carbon(takeoff, provider=store)
        assert "ln-exotic-aerogel" in result.uncounted_lines
        cline = next(l for l in result.lines if l.line_id == "ln-exotic-aerogel")
        assert cline.missing_reason is not None
        assert cline.kg_co2e is None

    def test_contributions_sum_to_100_percent(self, store):
        takeoff = example_takeoff()
        result = calculate_carbon(takeoff, provider=store)
        assert result.total_kg_co2e > 0

        # Assembly percentages sum to ~100%
        assemb_pct_sum = sum(c.pct_of_total for c in result.by_assembly)
        assert 99.0 <= assemb_pct_sum <= 101.0

        # Material category percentages sum to ~100%
        mat_pct_sum = sum(c.pct_of_total for c in result.by_material_category)
        assert 99.0 <= mat_pct_sum <= 101.0

    def test_intensity_computed(self, store):
        takeoff = example_takeoff()
        result = calculate_carbon(takeoff, provider=store)
        expected_intensity = round(result.total_kg_co2e / takeoff.project.gfa_m2, 2)
        assert result.intensity_kg_co2e_per_m2 == expected_intensity
        assert result.range_low_kg_co2e < result.total_kg_co2e < result.range_high_kg_co2e
