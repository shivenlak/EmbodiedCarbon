"""Where a plan set was drawn and in which units (contract C1, docs/finals/SHARED.md).

Scoped to North America (24 Nov decision): it tells the United States from
Canada, and the state or province where the sheets say so. Every answer
carries the evidence it was drawn from, and a weak or split vote returns None
rather than a guess, so callers keep handling None everywhere.

Evidence, strongest first:
- an address: a ZIP after a state code ("CA 92025"), a Canadian postcode, a
  state or province named in full (via `carbon.region.from_text`);
- the building code cited: CBC / CRC / IRC / IBC / Title 24 are American,
  NBC / OBC / BCBC / ABC / NBC(AE) are Canadian.
Units come from the dimension strings: feet-and-inches against millimetres.
"""

from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class Locale:
    unit_system: Literal["metric", "imperial", "mixed"] | None
    country: str | None  # ISO 3166-1 alpha-2, e.g. "US", "CA"
    region: str | None  # e.g. "CA-AB", "US-CA"
    evidence: list[str] = field(default_factory=list)  # human-readable reasons


_US_CODE_RE = re.compile(
    r"\b(?:20\d\d\s+)?(?:CALIFORNIA\s+(?:BUILDING|RESIDENTIAL)\s+CODE|CBC|CRC|IRC|IBC|TITLE\s+24)\b"
)
_CA_CODE_RE = re.compile(
    r"\b(?:NATIONAL\s+BUILDING\s+CODE(?:\s+OF\s+CANADA)?|NBC|NBCC|OBC|BCBC|ONTARIO\s+BUILDING\s+CODE"
    r"|ALBERTA\s+BUILDING\s+CODE|CODE\s+DE\s+CONSTRUCTION)\b"
)
_FT_IN_RE = re.compile(r"\b\d{1,3}'\s*-\s*\d{1,2}(?:\s+\d/\d{1,2})?\"")
_MM_RE = re.compile(r"\b\d{2,5}\s*mm\b", re.I)
# Pages read: the title block repeats on every sheet, so a few suffice.
MAX_PAGES = 8


def locale_from_texts(texts: list[str]) -> Locale:
    """The locale from page texts; separated from the PDF for testing."""
    from ecarbon.carbon.region import from_text

    regions: collections.Counter[str] = collections.Counter()
    codes: collections.Counter[str] = collections.Counter()
    ft_in = mm = 0
    for raw in texts:
        up = re.sub(r"\s+", " ", raw).upper()
        if (geo := from_text(up)) and geo[:2] in ("US", "CA"):
            regions[geo] += 1
        codes["US"] += len(_US_CODE_RE.findall(up))
        codes["CA"] += len(_CA_CODE_RE.findall(up))
        ft_in += len(_FT_IN_RE.findall(raw))
        mm += len(_MM_RE.findall(raw))

    evidence: list[str] = []
    by_country: collections.Counter[str] = collections.Counter()
    for geo, n in regions.items():
        by_country[geo[:2]] += 2 * n  # an address outweighs a code citation
    for c, n in codes.items():
        by_country[c] += min(n, 3)
    country = None
    if by_country:
        (top, a), *rest = by_country.most_common()
        b = rest[0][1] if rest else 0
        if a >= 2 and a >= 2 * b:
            country = top
    region = None
    if country:
        subs = [(g, n) for g, n in regions.most_common() if g.startswith(country + "-")]
        if subs:
            region = subs[0][0]
            evidence.append(f"{region} named on {subs[0][1]} sheet(s)")
        if codes[country]:
            evidence.append(f"{codes[country]} citation(s) of {'US' if country == 'US' else 'Canadian'} building codes")

    unit = None
    if ft_in or mm:
        if ft_in >= 3 * max(mm, 1):
            unit = "imperial"
        elif mm >= 3 * max(ft_in, 1):
            unit = "metric"
        else:
            unit = "mixed"
        evidence.append(f"{ft_in} feet-and-inches and {mm} millimetre dimension strings")
    return Locale(unit, country, region, evidence)


def detect_locale(design) -> Locale:
    import pymupdf

    try:
        doc = pymupdf.open(design.drawings_pdf)
    except Exception:
        return Locale(None, None, None, [])
    try:
        texts = [doc[i].get_text("text") for i in range(min(len(doc), MAX_PAGES))]
    finally:
        doc.close()
    return locale_from_texts(texts)
