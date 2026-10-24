"""Glyph-ID text repair.

This one earns a dedicated test file because getting it subtly wrong is worse
than not having it: a wrongly "repaired" sheet number or dimension is a
confident lie, and the whole takeoff inherits it. Every case below is real
text taken from catalogue PDFs.
"""

from __future__ import annotations

import pytest

from ecarbon.intake.textrepair import looks_broken, repair

# Real mojibake from the ON multiplex and ATL Option 2 sets (shift 0x1D).
BROKEN = [
    ("&$7$/2*8(", "CATALOGUE"),
    ("(/(9$7,216", "ELEVATIONS"),
    ("6(&7,216", "SECTIONS"),
    ("522)\x033/$1", "ROOF PLAN"),
    ("0$,1\x03)/225\x033/$1", "MAIN FLOOR PLAN"),
    ("7<3,&$/\x03'(7$,/6", "TYPICAL DETAILS"),
    ("$\x13\x13\x17", "A004"),
    ("$\x14\x13\x14D", "A101a"),
]

# Text that is already correct, or that must never be touched. The dimension
# and sheet-number cases are the dangerous ones: they are short and
# punctuation-heavy, so a naive scorer "fixes" them into plausible nonsense
# ('A003' + 0x20 = 'aPPS', '2592' + 0x1D = 'ORVO').
LEAVE_ALONE = [
    "TYPICAL DETAILS",
    "MAIN FLOOR PLAN",
    "FOUNDATION PLAN",
    "A003",
    "A101a",
    "S102",
    "M000",
    "W2",
    "2592",
    "3000",
    "23' - 0\"",
    "1/4\" = 1'-0\"",
    "9'-10 1/8\"",
    "&",
    "100 mm",
    "R-22",
    "1:48",
]


class TestRepairsRealMojibake:
    @pytest.mark.parametrize(("broken", "want"), BROKEN)
    def test_decodes(self, broken, want):
        got, repaired = repair(broken)
        assert got == want
        assert repaired


class TestNeverCorruptsGoodText:
    @pytest.mark.parametrize("text", LEAVE_ALONE)
    def test_unchanged(self, text):
        got, repaired = repair(text)
        assert got == text
        assert not repaired

    def test_sheet_numbers_survive(self):
        """The regression that made this test file necessary."""
        for n in ("A003", "A101", "S201", "M100", "E400", "A101a"):
            assert repair(n) == (n, False)

    def test_dimensions_survive(self):
        for d in ("2592", "7000", "6453", "23' - 0\"", "8' - 6\"", "3.000"):
            assert repair(d) == (d, False)


class TestBrokennessDetection:
    def test_control_characters_are_broken(self):
        assert looks_broken("$\x13\x13\x17")

    def test_plain_text_is_not_broken(self):
        assert not looks_broken("MAIN FLOOR PLAN")

    def test_empty_is_not_broken(self):
        assert not looks_broken("")


class TestIdempotence:
    @pytest.mark.parametrize(("broken", "want"), BROKEN)
    def test_repairing_twice_is_stable(self, broken, want):
        once, _ = repair(broken)
        twice, again = repair(once)
        assert twice == want
        assert not again


class TestKnownLimits:
    """What repair does and does not guarantee.

    Guaranteed: text containing letters, sheet numbers and dimensions are never
    altered (the cases above). NOT guaranteed: a letter-free run of punctuation
    carries no evidence either way, so a shift may well turn it into
    letters. That is acceptable because such a string can only land in a sheet
    title, where it then fails type classification and is reported as UNKNOWN
    rather than believed -- but it is a real limit, so it is pinned here
    rather than left as a surprise.
    """

    def test_letter_free_punctuation_may_be_shifted(self):
        got, repaired = repair("@@@###@@@")
        assert repaired, "documents the limitation; see the class docstring"
        assert got != "@@@###@@@"

    def test_a_mis_shifted_title_does_not_become_a_sheet_type(self):
        from ecarbon.intake.classify import sheet_type_of
        from ecarbon.models import SheetType

        got, _ = repair("@@@###@@@")
        assert sheet_type_of(got) is SheetType.UNKNOWN

    def test_short_strings_are_never_touched(self):
        for s in ("AB", "12", "&", "x"):
            assert repair(s) == (s, False)
