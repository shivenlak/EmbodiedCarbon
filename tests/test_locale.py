"""Where a set was drawn, North America only (intake/locale.py)."""

from __future__ import annotations

from ecarbon.intake.locale import locale_from_texts


def test_a_california_set_is_us_ca():
    loc = locale_from_texts([
        "ESCONDIDO, CA 92025 2022 CALIFORNIA RESIDENTIAL CODE (CRC) 2022 CBC TITLE 24",
        "PLATE HEIGHT 8' - 1\" GROUND FLOOR 0' - 0\" 22'-0\" 14'-6\"",
    ])
    assert (loc.country, loc.region) == ("US", "US-CA")
    assert loc.evidence


def test_a_canadian_set_is_canada():
    loc = locale_from_texts(["EDMONTON, ALBERTA T5J 0N3", "NATIONAL BUILDING CODE OF CANADA 2019 NBC 9.16"])
    assert loc.country == "CA" and loc.region == "CA-AB"


def test_no_evidence_is_no_answer():
    loc = locale_from_texts(["GENERAL NOTES 1. VERIFY ALL DIMENSIONS ON SITE."])
    assert loc.country is None and loc.region is None


def test_the_frost_depth_follows_the_region():
    from types import SimpleNamespace

    from ecarbon.intake.locale import Locale
    from ecarbon.takeoff.framing import (
        STANDARD_FROST_MM,
        US_FROST_MM,
        US_WARM_FROST_MM,
        assumed_frost_mm,
    )

    def at(country, region):
        return assumed_frost_mm(SimpleNamespace(locale=Locale(None, country, region, [])))[0]

    assert at("US", "US-CA") == US_WARM_FROST_MM
    assert at("US", "US-MN") == US_FROST_MM
    assert at("CA", "CA-AB") == STANDARD_FROST_MM
    assert assumed_frost_mm(SimpleNamespace(locale=None))[0] == STANDARD_FROST_MM


def test_the_publishers_office_and_the_licence_law_are_not_the_site():
    """Every CMHC set, Saskatchewan's included, carries CMHC's Ottawa address and an
    Ontario governing-law clause; neither says where the building goes."""
    from ecarbon.intake.locale import locale_from_texts

    cover = "CMHC\n700 MONTREAL ROAD, OTTAWA, ONTARIO K1A 0P7\n\nNATIONAL BUILDING CODE OF CANADA"
    terms = "GOVERNED BY, CONSTRUED AND INTERPRETED IN ACCORDANCE WITH THE LAWS OF\nTHE PROVINCE OF ONTARIO AND THE APPLICABLE LAWS OF CANADA."
    loc = locale_from_texts([cover, terms, "NBC 9.10.14"])
    assert (loc.country, loc.region) == ("CA", None)


def test_slab_on_grade_beside_a_postcode_shaped_tag_is_not_ontario():
    from ecarbon.intake.locale import locale_from_texts

    sheet = "P1A 2X4 INTERIOR PARTITION\nSLAB ON GRADE\nNBC 9.30.\n\nREGINA, SK S4P 3Y2"
    assert locale_from_texts([sheet, sheet]).region == "CA-SK"
