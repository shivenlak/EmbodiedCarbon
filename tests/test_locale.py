"""A2: where a set was drawn and in which units (contract C1)."""

from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

import pymupdf
import pytest

from ecarbon.intake.locale import detect_locale, region_of, unit_system_of
from ecarbon.models import (
    Basis,
    BasisSource,
    Confidence,
    ElementClass,
    Provenance,
    TakeoffLine,
    Unit,
)
from ecarbon.takeoff.builder import mark_units


class TestUnitVote:
    def test_too_few_labels_name_nothing(self):
        assert unit_system_of(Counter(metric=5))[0] is None

    def test_a_clear_majority_names_the_system(self):
        assert unit_system_of(Counter(metric=90, imperial=5))[0] == "metric"
        assert unit_system_of(Counter(imperial=90, metric=5))[0] == "imperial"

    def test_dual_labels_make_a_set_mixed(self):
        assert unit_system_of(Counter(metric=60, dual=30))[0] == "mixed"

    def test_no_majority_is_mixed(self):
        assert unit_system_of(Counter(metric=50, imperial=50))[0] == "mixed"


class TestRegionVote:
    def test_a_region_on_two_sheets_is_named(self):
        assert region_of({"US-ID": {0, 1}})[:2] == ("US", "US-ID")

    def test_one_sheet_is_not_enough(self):
        assert region_of({"US-ID": {0}})[:2] == (None, None)

    def test_a_bare_country_is_a_hint_only(self):
        country, region, note = region_of({"US": {0, 1, 2}})
        assert (country, region) == (None, None) and "US" in note

    def test_a_close_rival_country_names_nothing(self):
        assert region_of({"US-WA": {0, 1, 2}, "AU-WA": {3, 4}})[:2] == (None, None)

    def test_regions_of_one_country_are_not_rivals(self):
        assert region_of({"CA-AB": {0, 1, 2}, "CA-BC": {3, 4}})[:2] == ("CA", "CA-AB")


def imperial_set(tmp_path, address: str):
    doc = pymupdf.open()
    for _ in range(2):
        page = doc.new_page(width=1200, height=800)
        for i in range(12):
            page.insert_text((100 + 60 * i, 400), f"{10 + i}'-6\"", fontsize=6)
        page.insert_text((900, 760), "SCALE: 1/4\" = 1'-0\"", fontsize=8)
        page.insert_text((900, 780), address, fontsize=8)
    path = tmp_path / "set.pdf"
    doc.save(path)
    return SimpleNamespace(drawings_pdf=path)


def test_an_imperial_us_set_is_read_as_one(tmp_path):
    loc = detect_locale(imperial_set(tmp_path, "Boise, ID 83702"))
    assert (loc.unit_system, loc.country, loc.region) == ("imperial", "US", "US-ID")


def test_no_drawings_name_nothing():
    assert detect_locale(SimpleNamespace(drawings_pdf=None)).unit_system is None


def line(*sources):
    return TakeoffLine(
        id="ln-x",
        element_class=ElementClass.SLAB_ON_GRADE,
        quantity=1.0,
        unit=Unit.M3,
        confidence=Confidence.MEASURED,
        basis=Basis(sources=list(sources)),
        provenance=Provenance(page=0),
    )


def test_an_imperial_set_rests_on_imperial_text():
    ln = line(BasisSource.VECTOR_PATH, BasisSource.DIM_TEXT_METRIC)
    gaps = mark_units([ln], SimpleNamespace(unit_system="imperial", evidence=["units: 0 metric"]))
    assert ln.basis.sources == [BasisSource.VECTOR_PATH, BasisSource.DIM_TEXT_IMPERIAL]
    assert "feet and inches" in gaps[0].message


@pytest.mark.parametrize("system", ["mixed", "metric", None])
def test_other_sets_keep_their_sources(system):
    ln = line(BasisSource.DIM_TEXT_METRIC)
    assert mark_units([ln], SimpleNamespace(unit_system=system, evidence=[])) == []
    assert ln.basis.sources == [BasisSource.DIM_TEXT_METRIC]


try:
    from ecarbon.config import discover, get_design

    _HAVE_DATA = len(discover()) >= 52
except Exception:
    _HAVE_DATA = False


@pytest.mark.skipif(not _HAVE_DATA, reason="$EC_DATA catalogue not present")
def test_a_cmhc_alberta_set_reads_canada_and_mixed():
    loc = detect_locale(get_design("AB_Fourplex_01"))
    assert (loc.unit_system, loc.country, loc.region) == ("mixed", "CA", "CA-AB")
