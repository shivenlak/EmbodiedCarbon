"""Stage 1 -- drawing intake: open the set, say what it contains, say what it cannot read."""

from ecarbon.intake.gaps import coverage_gaps, readability_gaps, summarise
from ecarbon.intake.inventory import (
    DrawingSet,
    PageProbe,
    classify_toolchain,
    inventory,
    set_toolchain,
)

__all__ = [
    "DrawingSet",
    "PageProbe",
    "classify_toolchain",
    "coverage_gaps",
    "inventory",
    "readability_gaps",
    "set_toolchain",
    "summarise",
]
