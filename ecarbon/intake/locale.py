"""Where a plan set was drawn and in which units (contract C1, docs/finals/SHARED.md).

Stub: every field is None until the real detector lands (A2). Callers must
handle None everywhere, which is also what the real detector returns when the
evidence is too weak to name a country or a unit system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class Locale:
    unit_system: Literal["metric", "imperial", "mixed"] | None
    country: str | None  # ISO 3166-1 alpha-2, e.g. "US", "CA", "AU", "GB", "IN"
    region: str | None  # e.g. "CA-AB", "US-CA", "AU-VIC"
    evidence: list[str] = field(default_factory=list)  # human-readable reasons


def detect_locale(design) -> Locale:
    return Locale(None, None, None, [])
