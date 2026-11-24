"""Where a plan set was drawn and in which units (contract C1, docs/finals/SHARED.md).

Every field is None when the evidence is too weak to name it; callers handle
None everywhere. What was seen goes into `evidence` either way.

- unit system: a vote of every dimension label (`scale.parse_dimension`) and
  scale note (`1:100` vs `1/4" = 1'-0"`) across the set. A bare number under
  1000 is no vote: US sheets are full of "24" and "250" that parse as mm.
- country and region: title-block lines read with `region.from_text`. Only a
  hit naming a state or province (a postcode, or the name itself) counts, and
  it must repeat on two sheets: a title block is on every sheet, a stray word
  in a note is not.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

import pymupdf

from ecarbon.geometry.scale import _SCALE_IMPERIAL_RE, _SCALE_RATIO_RE, parse_dimension
from ecarbon.intake.spans import join_rows, read_spans

# Fewer votes than this names no unit system.
MIN_UNIT_VOTES = 10
# One system's share of the votes to be called that system; below it, mixed.
UNIT_MAJORITY = 0.8
# Dual-dimensioned labels ("2440 [8'-0"]") above this share make a set mixed.
DUAL_SHARE = 0.2
# Sheets a region must appear on, and its lead over the next country.
MIN_REGION_PAGES = 2
# Sheets read, evenly spaced: a title block repeats on every one, and reading
# all 46 of a CMHC set doubled the locale's cost for the same answer.
MAX_SHEETS = 12
_BARE_SMALL = re.compile(r"^\d{1,3}$")


@dataclass(frozen=True)
class Locale:
    unit_system: Literal["metric", "imperial", "mixed"] | None
    country: str | None  # ISO 3166-1 alpha-2, e.g. "US", "CA", "AU", "GB", "IN"
    region: str | None  # e.g. "CA-AB", "US-CA", "AU-VIC"
    evidence: list[str] = field(default_factory=list)  # human-readable reasons


def detect_locale(design) -> Locale:
    pdf = getattr(design, "drawings_pdf", None)
    if pdf is None:
        return Locale(None, None, None, ["no drawings"])
    # The builder and the upload's region both ask; read the file once.
    return _detect(str(pdf), Path(pdf).stat().st_mtime)


@lru_cache(maxsize=64)
def _detect(pdf: str, _mtime: float) -> Locale:
    votes: Counter[str] = Counter()
    pages_by_geo: dict[str, set[int]] = {}
    with pymupdf.open(pdf) as doc:
        step = max(1, len(doc) / MAX_SHEETS)
        for n in sorted({int(k * step) for k in range(min(len(doc), MAX_SHEETS))}):
            page = doc[n]
            spans = read_spans(page)
            for _, _, text in spans:
                value, system = parse_dimension(text)
                if value is not None and not (system == "metric" and _BARE_SMALL.match(text)):
                    votes[system] += 1
            for line in join_rows(spans):
                if _SCALE_RATIO_RE.search(line):
                    votes["metric"] += 1
                elif _SCALE_IMPERIAL_RE.search(line):
                    votes["imperial"] += 1
                geo = _geo(line)
                if geo:
                    pages_by_geo.setdefault(geo, set()).add(page.number)
    units, unit_note = unit_system_of(votes)
    country, region, geo_note = region_of(pages_by_geo)
    return Locale(units, country, region, [unit_note, geo_note])


def unit_system_of(votes: Counter[str]) -> tuple[str | None, str]:
    m, i, d = votes["metric"], votes["imperial"], votes["dual"]
    n = m + i + d
    note = f"units: {m} metric, {i} imperial, {d} dual-dimensioned labels and scale notes"
    if n < MIN_UNIT_VOTES:
        return None, note + " (too few to say)"
    if d / n > DUAL_SHARE:
        return "mixed", note
    if m / n >= UNIT_MAJORITY:
        return "metric", note
    if i / n >= UNIT_MAJORITY:
        return "imperial", note
    return "mixed", note


def region_of(pages_by_geo: dict[str, set[int]]) -> tuple[str | None, str | None, str]:
    """The region on the most sheets, if it is on enough of them and leads the
    next country by two to one. Hits naming only a country are evidence only."""
    hits = sorted(
        ((g, len(p)) for g, p in pages_by_geo.items() if "-" in g),
        key=lambda gp: -gp[1],
    )
    if not hits:
        weak = ", ".join(sorted(pages_by_geo)) or "nothing"
        return None, None, f"place: no state or province in the title blocks (hints: {weak})"
    geo, n = hits[0]
    country = geo.split("-")[0]
    rival = max((k for g, k in hits if not g.startswith(country + "-")), default=0)
    note = "place: " + ", ".join(f"{g} on {k} sheets" for g, k in hits[:4])
    if n < MIN_REGION_PAGES or n < 2 * rival:
        return None, None, note + " (not conclusive)"
    return country, geo, note


def _geo(line: str) -> str | None:
    from ecarbon.carbon.region import from_text  # shared parser (B); lazy: region imports us

    # shortcut: dimension-like lines ("1200 SA 3000") are skipped by the digit
    # share; a title-block address is mostly letters.
    if sum(c.isdigit() for c in line) > 0.5 * len(line):
        return None
    return from_text(line)
