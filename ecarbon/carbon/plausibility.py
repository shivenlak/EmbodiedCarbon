"""Is this intensity possible? A check on the denominator, not the building.

Intensity is the one figure where a wrong answer looks entirely ordinary. The
quantities can be right to the millimetre and the result still be nonsense,
because kgCO2e per square metre is only as good as the square metres.

AB_Rowhouse_01 is the case this exists for. Its bill of quantities is measured
off the drawings and covers the whole block; its Building Performance Report
states 74 m2 and one unit. Dividing one by the other gives 761 kgCO2e/m2 for
an A1-A3 figure, when the highest *whole-life* intensity CMHC publishes for
any design in the catalogue is 731. A number above that is not a heavy
building, it is a denominator error -- and nothing in the takeoff would catch
it, because every quantity feeding it is correct.

The band comes from the catalogue's own published figures across 52 designs:
141 to 731 kgCO2e/m2 whole life, median 448. A1-A3 is a subset of whole life,
so our figure must sit below a design's own published total and, for a takeoff
that reaches most of the building, well inside the band.
"""

from __future__ import annotations

from ecarbon.models import CarbonResult, Gap, GapCode, GapSeverity, ProjectFacts

# Published whole-life intensity across the catalogue (kgCO2e/m2).
CATALOGUE_MIN = 141.0
CATALOGUE_MAX = 731.0
CATALOGUE_MEDIAN = 448.0

# Our A1-A3 figure is a subset of whole life. Above the catalogue's whole-life
# maximum is arithmetically impossible whatever the coverage.
IMPOSSIBLE_ABOVE = CATALOGUE_MAX

# A takeoff reaching this much of the building should land in a believable
# band; below that, a low intensity is explained by the missing elements and
# saying so twice adds nothing.
COVERAGE_FOR_LOW_CHECK = 0.9
IMPLAUSIBLY_LOW_BELOW = 40.0


def intensity_warning(
    carbon: CarbonResult,
    facts: ProjectFacts | None = None,
    coverage: float | None = None,
) -> Gap | None:
    """A gap when the intensity cannot be right, or None when it is believable.

    `coverage` is the share of the building the bill reaches, 0-1, so a low
    intensity from a deliberately partial takeoff is not reported as a fault.
    """
    intensity = carbon.intensity_kg_co2e_per_m2
    if not intensity or intensity <= 0:
        return None

    gfa = facts.gfa_m2 if facts else None
    denominator = (
        f" The denominator is {gfa:.0f} m2." if gfa else ""
    )

    if intensity > IMPOSSIBLE_ABOVE:
        implied = carbon.total_kg_co2e / IMPOSSIBLE_ABOVE
        return Gap(
            code=GapCode.GEOMETRY_AMBIGUOUS,
            severity=GapSeverity.BLOCKING,
            message=(
                f"Intensity of {intensity:.0f} kgCO2e/m2 is not possible. This is "
                f"an A1-A3 figure, a subset of whole life, and the highest "
                f"whole-life intensity published for any design in this catalogue "
                f"is {CATALOGUE_MAX:.0f}.{denominator} The quantities may be right "
                f"while the floor area is wrong -- that combination is what a "
                f"per-unit area under a whole-block takeoff produces. For this "
                f"total to be plausible the building would need at least "
                f"{implied:.0f} m2. Confirm the floor area and its basis."
            ),
        )

    if (
        coverage is not None
        and coverage >= COVERAGE_FOR_LOW_CHECK
        and intensity < IMPLAUSIBLY_LOW_BELOW
    ):
        return Gap(
            code=GapCode.GEOMETRY_AMBIGUOUS,
            severity=GapSeverity.WARNING,
            message=(
                f"Intensity of {intensity:.0f} kgCO2e/m2 is far below the "
                f"{CATALOGUE_MIN:.0f}-{CATALOGUE_MAX:.0f} range this catalogue "
                f"publishes, on a takeoff that reaches {coverage:.0%} of the "
                f"building.{denominator} A nearly complete bill should not be this "
                f"light, so either the floor area is too large -- a site plan read "
                f"as a footprint does this -- or quantities are being counted over "
                f"too small a share of the building."
            ),
        )
    return None
