"""The API shape is final even though the data behind it is still the fixture.
These tests pin the shape so T can build the UI against it safely."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ecarbon.api.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_intake_is_separate_from_the_numbers(client):
    """The UI shows the gap report before any total, so intake is its own call."""
    r = client.get("/projects/demo/intake")
    assert r.status_code == 200
    body = r.json()
    assert body["n_sheets"] >= 1
    assert "gaps" in body and "toolchains" in body
    assert "total_kg_co2e" not in body


def test_takeoff_lines_carry_provenance_and_confidence(client):
    for line in client.get("/projects/demo/takeoff").json()["lines"]:
        assert line["confidence"] in {"measured", "inferred", "assumed"}
        assert line["provenance"]["page"] is not None
        if line["confidence"] == "assumed":
            assert line["assumptions"]


def test_carbon_reports_total_intensity_and_modules(client):
    c = client.get("/projects/demo/carbon").json()
    assert c["total_kg_co2e"] > 0
    assert c["intensity_kg_co2e_per_m2"] > 0
    assert c["modules"] == ["A1", "A2", "A3"]


def test_missing_factors_are_listed_not_hidden(client):
    c = client.get("/projects/demo/carbon").json()
    assert c["uncounted_lines"]
    for lid in c["uncounted_lines"]:
        line = next(x for x in c["lines"] if x["line_id"] == lid)
        assert line["missing_reason"]
        assert line["kg_co2e"] is None


def test_override_updates_carbon_then_clears(client):
    before = client.get("/projects/demo/carbon").json()["total_kg_co2e"]
    after = client.post(
        "/projects/demo/lines/ln-slab-main", json={"quantity": 45.0, "note": "from S201"}
    ).json()["total_kg_co2e"]
    assert after > before
    restored = client.post("/projects/demo/lines/ln-slab-main", json={"quantity": None}).json()
    assert restored["total_kg_co2e"] == pytest.approx(before)


def test_override_does_not_mutate_the_extracted_value(client):
    client.post("/projects/demo/lines/ln-slab-main", json={"quantity": 99.0})
    line = next(
        x for x in client.get("/projects/demo/takeoff").json()["lines"] if x["id"] == "ln-slab-main"
    )
    assert line["user_override"] == 99.0
    assert line["quantity"] != 99.0, "the extracted quantity must survive an override"
    client.post("/projects/demo/lines/ln-slab-main", json={"quantity": None})


def test_substitutions_are_ranked_by_computed_impact(client):
    subs = client.get("/projects/demo/substitutions").json()
    assert subs, "at least the concrete mix swap should be offered"
    assert subs == sorted(subs, key=lambda s: s["delta_kg_co2e"])
    # Lower-carbon mix must reduce, not increase.
    assert subs[0]["delta_kg_co2e"] < 0


def test_bad_requests(client):
    assert client.get("/projects/nope/carbon").status_code == 404
    assert client.post("/projects/demo/lines/nope", json={"quantity": 1}).status_code == 404
    assert client.post("/projects/demo/lines/ln-slab-main", json={"quantity": -1}).status_code == 422


def test_create_project_then_read_it_back(client):
    pid = client.post("/projects", json={"name": "AB_Sixplex", "gfa_m2": 500.0,
                                         "gfa_basis": "gross"}).json()["id"]
    t = client.get(f"/projects/{pid}/takeoff").json()
    assert t["project"]["name"] == "AB_Sixplex"
    assert t["project"]["gfa_m2"] == 500.0
    c = client.get(f"/projects/{pid}/carbon").json()
    assert c["intensity_kg_co2e_per_m2"] == pytest.approx(c["total_kg_co2e"] / 500.0, rel=1e-2)
