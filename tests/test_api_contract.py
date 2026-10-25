"""The fields the web UI actually reads must survive serialisation.

This exists because of a real bug. `CarbonLine.is_counted` and
`CarbonResult.coverage_pct` are Python *properties*, so they are absent from
the JSON the API returns. The UI keyed "was this line counted?" off
`is_counted`, which was therefore always undefined, and every quantity
rendered as "not counted" while the total sat correct beside it -- a display
that disagrees with its own total, from code that raised nothing and passed
every test.

So: assert the shape of the payload, not just the values behind it.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ecarbon.api.main import app
from ecarbon.carbon.calculate import calculate_carbon
from ecarbon.carbon.store import LocalSnapshotProvider
from ecarbon.fixtures import example_takeoff


@pytest.fixture(scope="module")
def payloads():
    takeoff = example_takeoff()
    carbon = calculate_carbon(takeoff, LocalSnapshotProvider())
    # Round-trip through JSON exactly as the API does.
    return (
        json.loads(takeoff.model_dump_json()),
        json.loads(carbon.model_dump_json()),
    )


class TestCarbonPayload:
    def test_a_counted_line_is_distinguishable_from_an_uncounted_one(self, payloads):
        _, carbon = payloads
        counted = [line for line in carbon["lines"] if line["kg_co2e"] is not None]
        uncounted = [line for line in carbon["lines"] if line["kg_co2e"] is None]
        assert counted, "no line carries a figure"
        assert uncounted, "the fixture should include one unmatched material"
        for line in uncounted:
            assert line["missing_reason"], "an uncounted line must say why"

    def test_uncounted_ids_match_the_lines_without_a_figure(self, payloads):
        _, carbon = payloads
        by_absence = {line["line_id"] for line in carbon["lines"] if line["kg_co2e"] is None}
        assert set(carbon["uncounted_lines"]) == by_absence

    def test_module_scope_is_present_and_a1_a3(self, payloads):
        """A carbon figure without its module scope is not a figure."""
        _, carbon = payloads
        assert carbon["modules"] == ["A1", "A2", "A3"]

    def test_headline_numbers_are_present(self, payloads):
        _, carbon = payloads
        for key in ("total_kg_co2e", "intensity_kg_co2e_per_m2", "intensity_basis"):
            assert carbon[key] is not None, f"{key} missing from the payload"

    def test_contribution_rows_carry_what_the_chart_draws(self, payloads):
        _, carbon = payloads
        assert carbon["by_material_category"]
        for row in carbon["by_material_category"]:
            assert {"key", "kg_co2e", "pct_of_total"} <= set(row)

    def test_each_counted_line_carries_its_factor_and_attribution(self, payloads):
        """Criterion 3: a number a builder can defend names its source."""
        _, carbon = payloads
        for line in carbon["lines"]:
            if line["kg_co2e"] is None:
                continue
            factor = line["factor"]
            assert factor, f"{line['line_id']} has a figure but no factor"
            for key in ("source", "declared_unit", "geography", "modules", "attribution"):
                assert factor.get(key), f"factor for {line['line_id']} has no {key}"


class TestTakeoffPayload:
    def test_every_line_carries_provenance_and_confidence(self, payloads):
        takeoff, _ = payloads
        assert takeoff["lines"]
        for line in takeoff["lines"]:
            assert line["confidence"] in {"measured", "inferred", "assumed"}
            assert "provenance" in line
            assert "page" in line["provenance"]

    def test_assumed_lines_ship_their_assumptions(self, payloads):
        takeoff, _ = payloads
        for line in takeoff["lines"]:
            if line["confidence"] == "assumed":
                assert line["assumptions"], f"{line['id']} is assumed but says nothing"

    def test_gaps_carry_a_severity_the_ui_can_sort_on(self, payloads):
        takeoff, _ = payloads
        for gap in takeoff["gaps"]:
            assert gap["severity"] in {"blocking", "warning", "info"}
            assert gap["message"]


class TestEndpointsTheUiCalls:
    @pytest.fixture(scope="class")
    def client(self):
        return TestClient(app)

    def test_health(self, client):
        assert client.get("/health").status_code == 200

    def test_projects_lists_with_an_id_and_a_name(self, client):
        rows = client.get("/projects").json()
        assert isinstance(rows, list)
        for row in rows:
            assert row["id"] and row["name"]

    def test_an_unknown_project_is_a_404_not_a_crash(self, client):
        assert client.get("/projects/not-a-real-set/takeoff").status_code == 404

    def test_an_unknown_line_override_is_a_404(self, client):
        rows = client.get("/projects").json()
        if not rows:
            pytest.skip("no plan sets available on this machine")
        res = client.post(
            f"/projects/{rows[0]['id']}/lines/ln-does-not-exist", json={"quantity": 1.0}
        )
        assert res.status_code == 404

    def test_a_negative_quantity_is_rejected(self, client):
        rows = client.get("/projects").json()
        if not rows:
            pytest.skip("no plan sets available on this machine")
        res = client.post(
            f"/projects/{rows[0]['id']}/lines/ln-slab-on-grade", json={"quantity": -5.0}
        )
        assert res.status_code in {404, 422}
