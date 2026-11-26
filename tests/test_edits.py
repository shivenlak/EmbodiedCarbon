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


def test_your_spec_is_kept_and_exported(client):
    swaps = client.get("/projects/demo/substitutions").json()
    if not swaps:
        pytest.skip("the fixture offers no swap")
    sw = swaps[0]
    spec = client.post("/projects/demo/scenario", json={"swaps": {sw["line_id"]: sw["to_material"]}, "picks": {}}).json()
    assert spec["rows"][0]["delta_kg_co2e"] == pytest.approx(sw["delta_kg_co2e"])
    assert spec["spec_kg_co2e"] == pytest.approx(spec["counted_kg_co2e"] + sw["delta_kg_co2e"], abs=0.01)
    assert client.get("/projects/demo/scenario").json()["swaps"] == {sw["line_id"]: sw["to_material"]}
    text = client.get("/projects/demo/export.csv").text
    assert "# your specification total kgCO2e" in text
    page = client.get("/projects/demo/report.html").text
    assert "Your specification" in page and "Audit trail" in page


try:
    from ecarbon.config import discover

    _HAVE_DATA = len(discover()) >= 52
except Exception:
    _HAVE_DATA = False


@pytest.mark.skipif(not _HAVE_DATA, reason="$EC_DATA catalogue not present")
def test_leaving_partition_walls_out_on_the_plan_reprices_and_says_so():
    from ecarbon.api.main import _sign

    c = TestClient(app)
    me = {"x-ecarbon-session": _sign("walls-me")}
    pid = "AB_Fourplex_01_Technical_Design_Package"
    w = c.get(f"/projects/{pid}/partitions", headers=me).json()
    assert w["editable"] and w["n_walls"] > 10
    for pg in w["pages"]:  # each sheet's walls sum to the length the bill used
        assert sum(x["length_m"] for x in pg["walls"]) == pytest.approx(pg["length_m"], abs=0.05)
    base = c.get(f"/projects/{pid}/carbon", headers=me).json()["total_kg_co2e"]
    out = [w["pages"][0]["walls"][0]["id"]]
    after = c.post(f"/projects/{pid}/partitions", json={"excluded": out}, headers=me).json()
    assert after["total_kg_co2e"] < base
    line = next(x for x in c.get(f"/projects/{pid}/takeoff", headers=me).json()["lines"]
                if x["id"].startswith("ln-interior-partition") and x["user_override"] is not None)
    assert "1 of" in line["override_note"] and "walls left out" in line["override_note"]
    back = c.post(f"/projects/{pid}/partitions", json={"excluded": []}, headers=me).json()
    assert back["total_kg_co2e"] == pytest.approx(base)
    assert c.post(f"/projects/{pid}/partitions", json={"excluded": ["p0-w999"]}, headers=me).status_code == 404


def test_the_complete_estimate_adds_labelled_items_to_an_unchanged_count(client):
    carbon = client.get("/projects/demo/carbon").json()
    c = client.get("/projects/demo/complete").json()
    assert c["counted_kg_co2e"] == pytest.approx(carbon["total_kg_co2e"])
    assert c["modules"] == "A1-A5"
    assert c["total_kg_co2e"] == pytest.approx(c["counted_kg_co2e"] + sum(i["kg_co2e"] for i in c["items"]), abs=0.5)
    assert c["low_kg_co2e"] <= c["total_kg_co2e"] <= c["high_kg_co2e"]
    for i in c["items"]:
        assert i["basis"] and i["source"] and i["low_kg_co2e"] <= i["kg_co2e"] <= i["high_kg_co2e"]
    assert {"a4", "a5"} <= {i["key"] for i in c["items"]}


def test_floor_finish_is_an_open_decision_priced_from_the_kootenay_guide():
    from ecarbon.carbon.store import LocalSnapshotProvider
    from ecarbon.carbon.unspecified import FLOORING, _factors_by_category, floor_finish_choice
    from ecarbon.fixtures import example_takeoff

    t = example_takeoff()
    t.project.gfa_m2 = 100.0
    ch = floor_finish_choice(t, _factors_by_category(LocalSnapshotProvider()))
    assert ch is not None and ch.category == FLOORING
    assert ch.low_kg_co2e == pytest.approx(685.0) and ch.high_kg_co2e == pytest.approx(2050.0)


def test_the_scope_declaration_walks_every_element_and_adds_up(client):
    """An LCA states which elements it includes (NRC guideline, Table 9). Every
    counted kgCO2e sits in exactly one row, and what is not included says why."""
    c = client.get("/projects/demo/complete").json()
    total = client.get("/projects/demo/carbon").json()["total_kg_co2e"]
    sc = c["scope"]
    assert "Table 9" in sc["source"]
    codes = {r["code"] for r in sc["rows"]}
    assert {"A1010", "A4010", "B1010", "B1020", "B2010", "B2020", "C1010", "D"} <= codes
    in_total = sum(r["kg_co2e"] for r in sc["rows"] if r["in_total"])
    assert in_total == pytest.approx(total, abs=1.0)
    added = sum(r["kg_co2e"] for r in sc["rows"] if not r["in_total"] and r["kg_co2e"] is not None)
    assert total + added == pytest.approx(c["total_kg_co2e"], abs=1.0)
    for r in sc["rows"]:
        assert r["status"] and r["detail"]
    # Membranes the drawings name are listed, never silently dropped.
    assert all(n["reason"] for n in sc["not_priced"])


def test_the_csv_and_report_carry_the_scope(client):
    csv = client.get("/projects/demo/export.csv").text
    assert "# scope declared against" in csv and "#   D Services" in csv
    html = client.get("/projects/demo/report.html").text
    assert "What is included" in html
