"""Unit tests for Step 21: Uncertainty ranges and sensitivity ranking."""


from ecarbon.carbon.calculate import calculate_carbon
from ecarbon.carbon.store import LocalSnapshotProvider
from ecarbon.carbon.uncertainty import analyze_uncertainty
from ecarbon.fixtures import example_takeoff


def test_uncertainty_analysis_bounds_and_ranking():
    to = example_takeoff()
    prov = LocalSnapshotProvider()
    carb = calculate_carbon(to, prov)

    report = analyze_uncertainty(to, carb)

    assert report.total_kg_co2e == carb.total_kg_co2e
    assert report.std_err_sigma_kg_co2e > 0.0
    # 95% CI encompasses total
    assert report.range_95_low_kg_co2e < report.total_kg_co2e < report.range_95_high_kg_co2e
    # 68% CI is inside 95% CI
    assert report.range_95_low_kg_co2e <= report.range_68_low_kg_co2e
    assert report.range_68_high_kg_co2e <= report.range_95_high_kg_co2e
    # Top drivers ranked properly
    assert len(report.top_drivers) >= 3
    # Check that variance contributions decrease with rank
    v_prev = 100.0
    for d in report.top_drivers:
        assert d.variance_contribution_pct <= v_prev
        v_prev = d.variance_contribution_pct
        assert d.combined_sigma_kg_co2e > 0.0
        assert d.assumption != ""
