"""A stated floor area that the footprint's extents overshoot means the plan is not a rectangle."""

from ecarbon.takeoff.builder import stated_area_sf


def test_reads_the_conditioned_area_each_us_set_states():
    assert stated_area_sf(['1/4"=1\'-0" 2 Bed 2 Bath 909 SQ. FT. CRAFTSMAN FLOOR PLAN']) == 909
    assert stated_area_sf(["2 Bedroom 2 Bath Plan - 909 s.f."]) == 909
    assert stated_area_sf(["PLAN 1 484 SF CONDITIONED"]) == 484
    assert stated_area_sf(["CONDITIONED PLAN 2 FLOOR 637 SF"]) == 637
    assert stated_area_sf(["1,244 SQ. FT."]) == 1244


def test_porches_vents_and_loads_are_not_floor_areas():
    texts = [
        "UNCONDITIONED PORCH 85 SF",
        "UNCONDITIONED PLAN 3 FRONT PORCH 185 SF",
        "PLAN 1 552 SF 1.84 SF 0.92 SF",
        "235 SF",
        "AEFFECTIVE = 10 sf 28 sf 30 sf",
        "SNOW LOADING: 63 PSF",
    ]
    assert stated_area_sf(texts) is None


def test_two_different_areas_are_ambiguous():
    assert stated_area_sf(["PLAN 1 484 SF CONDITIONED", "PLAN 3 851 SF CONDITIONED"]) is None
    assert stated_area_sf(["499 SQ. FT.", "Studio - 499s.f."]) == 499
