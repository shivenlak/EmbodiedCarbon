"""Recover text from subset fonts that ship no ToUnicode map.

Several catalogue sets (the ON multiplex family, ATL_Fourplex_01 Option 2 and
others) embed Type0/Identity-H subset fonts with `/ToUnicode null`. With no map,
a PDF reader can only hand back raw glyph IDs, so `A003 TYPICAL DETAILS` arrives
as `$\\x13\\x13\\x16 7<3,&$/\\x03'(7$,/6`.

Those glyph IDs are ASCII shifted by a constant. We solve for the shift **per
span**, not per font: the same font program appears in a document under many
subset encodings, so a font-wide sample mixes encodings and produces a
confidently wrong answer. A single span is short, but the vocabulary of
construction-drawing text is narrow enough to make the test decisive, and a
wrong shift is rejected rather than guessed.

Without this, sheet identification silently drops to ~40% on the affected sets
while *appearing* to succeed -- the failure mode that makes a takeoff
untrustworthy. Measured effect across the catalogue: sheet-number match rose
from 91.4% to 97.9%, and the worst affected set from 36% to 91%.

Known limit: a letter-free run of punctuation carries no evidence either way,
so it may be shifted into letters. Such a string can only reach a sheet title,
where it then fails type classification and is reported UNKNOWN rather than
believed. See tests/test_textrepair.py::TestKnownLimits.
"""

from __future__ import annotations

import re
from functools import lru_cache

# What text on a construction drawing is actually made of.
_ALLOWED = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789"
    " .,&-/()'\"#:;!?%+=*@_[]<>\n\t"
    "°Ø–—‘’“”"
)

# 0x1D explains every affected set in the CMHC catalogue; the rest are a sweep
# for sets we have not seen. Tried in this order, so the common case is cheap.
_CANDIDATE_SHIFTS = (0x1D, 0x1F, 0x1E, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x29)

_MIN_LEN = 3
# A repaired span must be this word-like, and beat the original by this much,
# before we believe it. Both thresholds are deliberately strict: a wrong title
# is worse than an admitted unknown.
_MIN_WORDLIKE = 0.85
_MIN_GAIN = 0.30
_MIN_LETTER_RUN = 3

# Dimensions, scales and bare numbers are legitimately punctuation-heavy and
# must never be "repaired" -- shifting '2592' yields the plausible-looking
# nonsense 'ORVO'. Anything made only of digits and dimension punctuation is
# left exactly as found.
_NUMERIC_RE = re.compile(r"^[\d.,'\"\-/=:%+ xX°Ø–—]+$")
_LETTER_RUN_RE = re.compile(rf"[A-Za-z]{{{_MIN_LETTER_RUN},}}")
# A repaired sheet number: A003, A101a, S102, M000, E201A.
_SHEET_NO_RE = re.compile(r"^[A-Z]{1,2}\d{2,4}[a-zA-Z]?$")


def looks_broken(text: str) -> bool:
    """True when a string is probably raw glyph IDs rather than characters.

    Used for the fast path and for gap reporting. Note it is deliberately
    conservative: `repair` does not rely on it to decide whether to try.
    """
    if not text:
        return False
    # Control characters other than real whitespace never appear in drawing text.
    if any(ord(c) < 0x20 and c not in "\n\r\t" for c in text):
        return True
    bad = sum(1 for c in text if c not in _ALLOWED)
    return bad / len(text) > 0.34


def _wordlike(text: str) -> float:
    """Fraction of characters that are letters or spaces.

    Drawing titles are almost entirely letters and spaces, while glyph-ID
    mojibake is almost entirely punctuation and digits, so this separates the
    two far more sharply than a general printable-character test.
    """
    if not text:
        return 0.0
    return sum(1 for c in text if c.isalpha() or c == " ") / len(text)


def _shift(text: str, by: int) -> str:
    # Only remap the low range the glyph IDs occupy; leave real characters alone.
    return "".join(chr(o + by) if 0 < (o := ord(c)) < 0x80 else c for c in text)


@lru_cache(maxsize=16384)
def repair(text: str) -> tuple[str, bool]:
    """Return (text, repaired).

    `repaired=False` means either the text was already fine or no shift was
    convincing; `looks_broken` separates those two cases for the caller.
    """
    if len(text) < _MIN_LEN or _NUMERIC_RE.match(text):
        return text, False

    # Anything that already reads correctly is left alone. Without these two
    # guards a valid sheet number is itself shiftable into plausible-looking
    # nonsense -- 'A003' + 0x20 = 'aPPS'.
    if _SHEET_NO_RE.match(text):
        return text, False
    base = _wordlike(text)
    if base >= _MIN_WORDLIKE:
        return text, False

    # Catalogue drawing text is uppercase, and uppercase A-Z, digits and space
    # all map into punctuation or control characters under the inverse shift,
    # so genuine mojibake is letter-free. The single exception is a lowercase
    # sheet-number suffix, which survives as a trailing letter: 'A101a' arrives
    # as '$\x14\x13\x14D'. Any other letter means this is real text we must not
    # touch -- 'R-22' would otherwise "repair" into 'oJOO'.
    alpha_at = [i for i, c in enumerate(text) if c.isalpha()]
    if alpha_at and not (len(alpha_at) == 1 and alpha_at[0] == len(text) - 1 and len(text) >= 5):
        return text, False
    for by in _CANDIDATE_SHIFTS:
        cand = _shift(text, by)
        # Either it reads as words (a sheet title) ...
        title_ok = (
            _wordlike(cand) >= _MIN_WORDLIKE
            and _wordlike(cand) > base + _MIN_GAIN
            and _LETTER_RUN_RE.search(cand)
        )
        # ... or it is a well-formed sheet number, which is too short to score
        # as word-like but is unambiguous in shape.
        if title_ok or _SHEET_NO_RE.match(cand):
            # 0x1D is tried first, so the common case stops here.
            return cand, True
    return text, False


class FontRepair:
    """Kept as a thin, stateless handle so call sites read the same as before.

    Repair is per span and cached globally, so there is no per-document state
    to carry; `broken_fonts` tracking exists only for the gap report.
    """

    def __init__(self) -> None:
        self._undecodable: set[str] = set()
        self._repaired: set[str] = set()

    def learn(self, doc, max_pages: int = 0) -> FontRepair:  # noqa: ARG002
        """No-op. Retained so callers need not care that repair became stateless."""
        return self

    def observe(self, font: str, text: str) -> None:
        pass

    def repair(self, font: str, text: str) -> tuple[str, bool]:
        fixed, ok = repair(text)
        if ok:
            self._repaired.add(font)
        elif looks_broken(text):
            self._undecodable.add(font)
        return fixed, ok

    @property
    def repaired_fonts(self) -> list[str]:
        return sorted(self._repaired)

    @property
    def undecodable_fonts(self) -> list[str]:
        return sorted(self._undecodable)
