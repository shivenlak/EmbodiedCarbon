"""Carbon factors by region (B4).

A US plan set priced with Canadian factors is a wrong answer that looks right.
These pin that: no region means today's numbers exactly; a region with its own
factor uses it; a region without one falls back to the default, says so on the
line and widens the range; and the region is per workspace.
"""

from __future__ import annotations

import pytest

from ecarbon.carbon.calculate import FOREIGN_FACTOR_EXTRA_PCT, calculate_carbon
from ecarbon.carbon.region import from_text, label_of
from ecarbon.carbon.store import LocalSnapshotProvider, same_country

try:
    from ecarbon.config import discover

    _HAVE_DATA = len(discover()) >= 52
except Exception:
    _HAVE_DATA = False
needs_data = pytest.mark.skipif(not _HAVE_DATA, reason="$EC_DATA catalogue not present")


@pytest.mark.parametrize(
    ("text", "geo"),
    [
        ("Boise, ID 83702", "US-ID"),
        ("Escondido, California", "US-CA"),
        ("USA", "US"),
        ("Edmonton, AB", "CA-AB"),
        ("Edmonton, Alberta T5J 0N3", "CA-AB"),
        ("Vancouver BC V6B 1A1", "CA-BC"),
        ("Melbourne VIC 3000", "AU-VIC"),
        ("Victoria, Australia", "AU-VIC"),
        ("London, United Kingdom", "GB"),
        ("somewhere", None),
        ("", None),
        (None, None),
    ],
)
def test_a_place_becomes_a_region_or_nothing(text, geo):
    assert from_text(text) == geo


def test_labels_say_where():
    assert label_of(None) == "Canada (default factors)"
    assert label_of("US-ID") == "United States (Idaho)"
    assert label_of("CA-AB") == "Canada (Alberta)"


def test_same_country():
    assert same_country("CA-AB", "CA")
    assert same_country("US", "US-CA")
    assert not same_country("CA-AB", "US")
    assert not same_country(None, "US")


class TestLookup:
    @pytest.fixture(scope="class")
    def store(self):
        return LocalSnapshotProvider()

    def test_no_region_is_the_old_lookup(self, store):
        assert store.find_by_material("CMHC_Concrete, CIP").factor_id == "koot-concrete-gu-30"

    def test_a_region_with_its_own_factor_gets_it(self, store):
        f = store.find_by_material("CMHC_Concrete, CIP", "US-CA")
        assert f.factor_id == "nrmca-v4-4000-00"
        assert f.geography == "US"

    def test_a_region_without_one_falls_back(self, store):
        # No Australian rows yet: the default (Canadian) factor is returned.
        f = store.find_by_material("CMHC_Concrete, CIP", "AU-VIC")
        assert f.factor_id == "koot-concrete-gu-30"

    def test_expired_factors_say_so(self, store):
        # Two US rows are the most recent industry averages but have lapsed;
        # that must be on the record, not hidden.
        for fid in ("awc-cwc-na-softwood-lumber-2020", "ga-type-x-2020"):
            f = store.get_factor(fid)
            assert f.valid_to is not None
            assert "EXPIRED" in (f.attribution or "")


@needs_data
class TestPricingABuilding:
    @pytest.fixture(scope="class")
    def takeoff(self):
        from ecarbon.config import get_design
        from ecarbon.takeoff.builder import build_takeoff

        return build_takeoff(get_design("AB_Fourplex_01"))

    def test_no_region_is_bit_identical(self, takeoff):
        p = LocalSnapshotProvider()
        assert (
            calculate_carbon(takeoff, p).model_dump_json()
            == calculate_carbon(takeoff, p, geography=None).model_dump_json()
        )

    def test_us_pricing_uses_us_factors_and_flags_the_rest(self, takeoff):
        p = LocalSnapshotProvider()
        base = calculate_carbon(takeoff, p)
        us = calculate_carbon(takeoff, p, geography="US")
        slab = next(line for line in us.lines if line.line_id == "ln-slab-on-grade")
        assert slab.factor.factor_id == "nrmca-v4-4000-00"
        fallback = [ln for ln in us.lines if ln.conversion_note and "No US factor" in ln.conversion_note]
        assert fallback, "materials without a US factor must say so"
        for ln in fallback:
            assert ln.factor.geography.startswith("CA")
        # A fallback widens the range; it never narrows it.
        assert (us.range_high_kg_co2e - us.total_kg_co2e) > (
            base.range_high_kg_co2e - base.total_kg_co2e
        )
        assert FOREIGN_FACTOR_EXTRA_PCT > 0

    def test_an_alberta_project_is_priced_as_today(self, takeoff):
        p = LocalSnapshotProvider()
        assert calculate_carbon(takeoff, p, geography="CA-AB").total_kg_co2e == pytest.approx(
            calculate_carbon(takeoff, p).total_kg_co2e
        )


@needs_data
class TestRegionEndpoint:
    PID = "AB_Fourplex_01_Technical_Design_Package"

    def test_choosing_a_region_reprices_one_workspace(self):
        from fastapi.testclient import TestClient

        from ecarbon.api.main import _sign, app

        c = TestClient(app)
        me = {"x-ecarbon-session": _sign("region-me")}
        them = {"x-ecarbon-session": _sign("region-them")}
        r = c.get(f"/projects/{self.PID}/region", headers=me).json()
        assert r["geography"] is None and r["source"] == "default"
        assert any(o["geography"] == "US" for o in r["options"])
        base = c.get(f"/projects/{self.PID}/carbon", headers=them).json()["total_kg_co2e"]

        r = c.post(f"/projects/{self.PID}/region", json={"geography": "US"}, headers=me).json()
        assert r["geography"] == "US" and r["source"] == "chosen"
        assert c.get(f"/projects/{self.PID}/carbon", headers=me).json()["total_kg_co2e"] > base
        assert c.get(f"/projects/{self.PID}/carbon", headers=them).json()["total_kg_co2e"] == base

        # A place name works too, and clearing goes back to the default.
        r = c.post(f"/projects/{self.PID}/region", json={"geography": "Boise, ID 83702"}, headers=me)
        assert r.json()["geography"] == "US-ID"
        c.post(f"/projects/{self.PID}/region", json={"geography": None}, headers=me)
        assert c.get(f"/projects/{self.PID}/carbon", headers=me).json()["total_kg_co2e"] == base

    def test_nonsense_is_refused(self):
        from fastapi.testclient import TestClient

        from ecarbon.api.main import _sign, app

        r = TestClient(app).post(
            f"/projects/{self.PID}/region",
            json={"geography": "the moon"},
            headers={"x-ecarbon-session": _sign("region-bad")},
        )
        assert r.status_code == 422
