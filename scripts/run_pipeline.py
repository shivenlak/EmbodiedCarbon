#!/usr/bin/env python
"""Run the whole pipeline on every design and report what comes out.

    python scripts/run_pipeline.py              # all 53
    python scripts/run_pipeline.py AB_Sixplex   # one

This is the end-to-end check behind two rubric bars: that the intake opens any
set in the catalogue without crashing, and that a set runs through to a carbon
number with no code changes. It is also where the coverage and intensity
distributions in docs/benchmark.md come from.

A crash here is a failure. A design that produces no quantities but reports why
is not -- that is the intended behaviour on the textless sets, and the two are
counted separately.
"""

from __future__ import annotations

import statistics
import sys
import time
import traceback

from ecarbon.carbon.calculate import calculate_carbon
from ecarbon.carbon.store import LocalSnapshotProvider
from ecarbon.config import discover, get_design
from ecarbon.models import ProjectFacts
from ecarbon.takeoff.builder import (
    ELEMENT_CARBON_SHARE,
    build_takeoff,
    coverage_report,
)

FACTORS = LocalSnapshotProvider()


def facts_for(design) -> ProjectFacts:
    """Project facts a builder would type in, read from the package when there."""
    facts = ProjectFacts(name=design.key)
    try:
        from ecarbon.bench.bpr import parse_bpr

        if design.bpr:
            bpr = parse_bpr(str(design.bpr[0]))
            facts = ProjectFacts(
                name=design.key,
                jurisdiction=bpr.location,
                gfa_m2=bpr.best_gfa_m2,
                gfa_basis="gross",
                storeys=bpr.storeys,
                units=bpr.units,
            )
    except Exception:
        pass
    return facts


def main(argv: list[str]) -> int:
    designs = [get_design(argv[0])] if argv else list(discover())

    print(
        f"{'design':30} {'secs':>5} {'lines':>5} {'cov':>5} {'kgCO2e':>10} "
        f"{'kg/m2':>7} {'gaps':>5} {'blk':>4}  note"
    )

    crashed: list[tuple[str, str]] = []
    silent: list[str] = []
    coverages: list[float] = []
    intensities: list[float] = []
    seconds: list[float] = []

    for d in designs:
        key = d.key.split("_Technical")[0][:30]
        start = time.monotonic()
        try:
            takeoff = build_takeoff(d, facts_for(d))
            carbon = calculate_carbon(takeoff, FACTORS)
            # Read the absent classes off the takeoff's own gaps rather than
            # calling gather() again, which would re-run every extraction
            # stage and triple the time this script reports.
            absent = {
                cls
                for cls in ELEMENT_CARBON_SHARE
                if any(
                    g.message.startswith(f"No {cls.value.replace('_', ' ')} is counted")
                    for g in takeoff.gaps
                )
            }
            covered, _missing = coverage_report(takeoff.lines, absent)
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - start
            crashed.append((key, f"{type(exc).__name__}: {exc}"))
            print(f"{key:30} {elapsed:>5.1f} {'CRASH':>5}  {type(exc).__name__}")
            traceback.print_exc(limit=1, file=sys.stderr)
            continue

        elapsed = time.monotonic() - start
        seconds.append(elapsed)
        blocking = sum(1 for g in takeoff.gaps if g.severity.value == "blocking")

        if not takeoff.lines:
            silent.append(key)
            note = "no quantities" + ("" if takeoff.gaps else " AND NO GAPS")
            print(
                f"{key:30} {elapsed:>5.1f} {0:>5} {'-':>5} {'-':>10} {'-':>7} "
                f"{len(takeoff.gaps):>5} {blocking:>4}  {note}"
            )
            continue

        coverages.append(covered)
        if carbon.intensity_kg_co2e_per_m2:
            intensities.append(carbon.intensity_kg_co2e_per_m2)
        print(
            f"{key:30} {elapsed:>5.1f} {len(takeoff.lines):>5} {covered:>4.0%} "
            f"{carbon.total_kg_co2e:>10,.0f} "
            f"{carbon.intensity_kg_co2e_per_m2 or 0:>7.1f} "
            f"{len(takeoff.gaps):>5} {blocking:>4}"
        )

    n = len(designs)
    print(f"\n{n} designs run.")
    print(f"  crashed:                 {len(crashed)}")
    print(f"  produced quantities:     {len(coverages)}")
    print(f"  produced none, with gaps:{len(silent)}")

    if seconds:
        print(
            f"  seconds per design: median {statistics.median(seconds):.1f}  "
            f"worst {max(seconds):.1f}"
        )
    if coverages:
        print(
            f"  element coverage: median {statistics.median(coverages):.0%}  "
            f"best {max(coverages):.0%}  worst {min(coverages):.0%}"
        )
    if intensities:
        print(
            f"  intensity kgCO2e/m2: median {statistics.median(intensities):.1f}  "
            f"range {min(intensities):.1f}-{max(intensities):.1f}"
        )
        # The published whole-life figures span 141-731 kgCO2e/m2 for A1-A5+B+C,
        # so an A1-A3 subset well above that range would be impossible.
        over = [i for i in intensities if i > 731]
        if over:
            print(f"  WARNING: {len(over)} design(s) exceed the published whole-life ceiling")

    if crashed:
        print("\nCrashes, which are failures:")
        for key, why in crashed:
            print(f"   {key:30} {why[:90]}")
    if silent:
        print(f"\nProduced no quantities but reported why ({len(silent)}):")
        print("   " + ", ".join(silent))

    return 1 if crashed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
