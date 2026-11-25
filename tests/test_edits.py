"""UX session, 25 Nov: edit any line's material and thickness, add your own
materials or upload the builder's list, and see every figure's calculation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ecarbon.api.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _line(client, line_id):
    return next(x for x in client.get("/projects/demo/carbon").json()["lines"] if x["line_id"] == line_id)


def _counted_m3_line(client):
    return next(
        x for x in client.get("/projects/demo/carbon").json()["lines"]
        if x["kg_co2e"] and x["factor"]["declared_unit"] == "m3" and x["unit"] == "m3"
    )


def test_every_line_has_a_calculation_that_reproduces_it(client):
    calc = client.get("/projects/demo/calc").json()
    carbon = client.get("/projects/demo/carbon").json()
    for cl in carbon["lines"]:
        tr = calc[cl["line_id"]]
        assert tr["counted"] == (cl["kg_co2e"] is not None)
        if tr["counted"]:
            assert tr["kg_co2e"] == pytest.approx(cl["kg_co2e"])
            assert tr["steps"][-1]["unit"] == "kgCO₂e"


def test_a_typed_material_prices_the_line_exactly(client):
    ln = _counted_m3_line(client)
    r = client.post("/projects/demo/materials", json={
        "name": "Test concrete, 25% slag", "declared_unit": "m3", "gwp_value": 200.0,
        "source": "Supplier EPD", "epd_id": "EPD-TEST-1",
    })
    assert r.status_code == 200, r.text
    fid = r.json()["factor_id"]
    after = client.post(f"/projects/demo/lines/{ln['line_id']}", json={"factor_id": fid}).json()
    new = next(x for x in after["lines"] if x["line_id"] == ln["line_id"])
    assert new["factor"]["factor_id"] == fid
    assert new["kg_co2e"] == pytest.approx(ln["quantity"] * 200.0, abs=0.02)
    steps = client.get(f"/projects/demo/lines/{ln['line_id']}/calc").json()["steps"]
    assert any("Entered by you" in s["source"] for s in steps)
    # The quantity is untouched by a material edit, and null restores the factor found.
    back = client.post(f"/projects/demo/lines/{ln['line_id']}", json={"factor_id": None}).json()
    assert next(x for x in back["lines"] if x["line_id"] == ln["line_id"])["kg_co2e"] == pytest.approx(ln["kg_co2e"])


def test_a_material_in_another_unit_is_refused_with_a_reason(client):
    ln = _counted_m3_line(client)
    fid = client.post("/projects/demo/materials", json={
        "name": "Per-each widget", "declared_unit": "each", "gwp_value": 5, "source": "test",
    }).json()["factor_id"]
    r = client.post(f"/projects/demo/lines/{ln['line_id']}", json={"factor_id": fid})
    assert r.status_code == 422 and "declared per each" in r.json()["detail"]


def test_a_library_upload_reports_bad_rows_and_keeps_the_good_ones(client):
    csv_text = (
        "name,category,declared_unit,gwp_kgco2e_per_unit,density_kg_m3,source,epd_id,valid_to\n"
        "Good batt,insulation,m3,30,40,Supplier A,EPD-A,2029-01-01\n"
        "Bad row,insulation,furlongs,3,,Supplier B,,\n"
    )
    r = client.post(
        "/projects/demo/materials/upload",
        files={"file": ("library.csv", csv_text.encode(), "text/csv")},
    ).json()
    assert r["added"] == ["Good batt"]
    assert len(r["errors"]) == 1 and r["errors"][0].startswith("row 3")
    mats = client.get("/projects/demo/materials").json()
    assert mats[0]["origin"] == "yours"
    assert any(m["name"] == "Good batt" and "Builder library: library.csv" in m["source"] for m in mats)


def test_the_template_downloads():
    text = TestClient(app).get("/materials/template.csv").text
    assert text.startswith("name,category,declared_unit,gwp_kgco2e_per_unit")


def test_the_csv_export_carries_the_calculation(client):
    text = client.get("/projects/demo/export.csv").text
    assert text.startswith("# project,")
    assert "calculation" in text and "gwp_value" in text and "kgCO2e" in text


def test_a_thickness_edit_scales_the_layer_volume():
    from types import SimpleNamespace

    from ecarbon.api.main import _drawn_thickness_mm

    layer = SimpleNamespace(unit=SimpleNamespace(value="m3"), description="Stud cavity batt, 140 mm")
    assert _drawn_thickness_mm(layer) == 140
    area = SimpleNamespace(unit=SimpleNamespace(value="m2"), description="Exterior wall, 140 mm studs")
    assert _drawn_thickness_mm(area) is None  # only a layer volume scales with thickness
