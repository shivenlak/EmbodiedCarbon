"""Which region's carbon factors a project should use, and why.

A US plan set priced with Canadian factors is a wrong answer that looks like a
right one. The region comes, in order of trust, from:

1. what the user chose (the "change" control beside the factors line);
2. the drawings' own title block (contract C1, `intake.locale.detect_locale`);
3. the jurisdiction typed when the set was uploaded;
4. nothing: the default (Canadian) factors, exactly as before.

Every answer carries where it came from, so the UI can say "United States
(from the title block)" rather than asserting a region it guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Country names and their codes, for regions the factor store can name.
COUNTRIES = {
    "CA": "Canada",
    "US": "United States",
    "GB": "United Kingdom",
    "IE": "Ireland",
    "AU": "Australia",
    "NZ": "New Zealand",
    "IN": "India",
}

_CA_PROVINCES = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador", "NS": "Nova Scotia", "NT": "Northwest Territories",
    "NU": "Nunavut", "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec",
    "SK": "Saskatchewan", "YT": "Yukon",
}
_US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}
_AU_STATES = {
    "NSW": "New South Wales", "VIC": "Victoria", "QLD": "Queensland", "SA": "South Australia",
    "WA": "Western Australia", "TAS": "Tasmania", "ACT": "Australian Capital Territory",
    "NT": "Northern Territory",
}


@dataclass(frozen=True)
class Region:
    geography: str | None  # "US", "US-CA", "CA-AB", ... or None for the default
    source: str  # "chosen" | "title block" | "jurisdiction" | "default"
    evidence: str = ""

    @property
    def label(self) -> str:
        return label_of(self.geography)


def label_of(geography: str | None) -> str:
    if not geography:
        return "Canada (default factors)"
    country, _, sub = geography.upper().partition("-")
    name = COUNTRIES.get(country, country)
    subs = {"CA": _CA_PROVINCES, "US": _US_STATES, "AU": _AU_STATES}.get(country, {})
    return f"{name} ({subs[sub]})" if sub in subs else name


def from_text(text: str | None) -> str | None:
    """A region from free text such as "Boise, ID 83702", "Edmonton, Alberta",
    "Melbourne VIC 3000" or "USA". None when nothing in it is conclusive."""
    if not text:
        return None
    t = text.strip()
    up = t.upper()
    # Canadian postcode, or a province by code or name.
    if re.search(r"\b[A-Z]\d[A-Z]\s?\d[A-Z]\d\b", up):
        for code, name in _CA_PROVINCES.items():
            if re.search(rf"\b{code}\b", up) or name.upper() in up:
                return f"CA-{code}"
        return "CA"
    for code, name in _CA_PROVINCES.items():
        if name.upper() in up:
            return f"CA-{code}"
    # US state with a ZIP code ("ID 83702"), or a state's full name.
    m = re.search(r"\b([A-Z]{2})\s+\d{5}(?:-\d{4})?\b", up)
    if m and m.group(1) in _US_STATES:
        return f"US-{m.group(1)}"
    for code, name in _US_STATES.items():
        if re.search(rf"\b{name.upper()}\b", up) and name.upper() not in ("GEORGIA",):
            return f"US-{code}"
    # Australian state with a 4-digit postcode, or by name.
    m = re.search(r"\b(NSW|VIC|QLD|SA|WA|TAS|ACT|NT)\s+\d{4}\b", up)
    if m:
        return f"AU-{m.group(1)}"
    for code, name in _AU_STATES.items():
        if name.upper() in up and "AUSTRALIA" in up:
            return f"AU-{code}"
    # A bare province or state code after a comma ("Edmonton, AB").
    m = re.search(r",\s*([A-Z]{2})\s*$", up)
    if m:
        if m.group(1) in _CA_PROVINCES:
            return f"CA-{m.group(1)}"
        if m.group(1) in _US_STATES:
            return f"US-{m.group(1)}"
    # Country names last: the most general claim.
    for code, words in {
        "US": ("UNITED STATES", "USA", "U.S.A"),
        "CA": ("CANADA",),
        "GB": ("UNITED KINGDOM", "ENGLAND", "SCOTLAND", "WALES"),
        "IE": ("IRELAND",),
        "AU": ("AUSTRALIA",),
        "NZ": ("NEW ZEALAND",),
        "IN": ("INDIA",),
    }.items():
        if any(re.search(rf"\b{re.escape(w)}\b", up) for w in words):
            return code
    return None


def detect(design, jurisdiction: str | None = None) -> Region:
    """The region a freshly uploaded set should be priced for."""
    try:
        from ecarbon.intake.locale import detect_locale

        loc = detect_locale(design) if design is not None else None
    except Exception:
        loc = None
    if loc is not None and getattr(loc, "country", None):
        geo = loc.region or loc.country
        return Region(geo, "title block", "; ".join(getattr(loc, "evidence", []) or [])[:200])
    geo = from_text(jurisdiction)
    if geo:
        return Region(geo, "jurisdiction", jurisdiction or "")
    return Region(None, "default")
