#!/usr/bin/env python
"""Score window and door counts against the IFC models.

    python scripts/score_openings.py            # every design
    python scripts/score_openings.py AB_Sixplex # one design

The IFC is an independent representation of the same building, so its
`IfcWindow` and `IfcDoor` counts are a genuine check on a count derived from
tags written on a PDF. It is not perfect truth -- it is a second opinion, and
where the two disagree the report says so rather than picking a winner.

Designs whose IFC carries no semantic openings are reported `no truth` and
excluded from the error statistics rather than counted as zero error. The 7
SKMB models are pure B-rep with no element types at all (RESEARCH S5).
"""

from __future__ import annotations

import statistics
import sys

import ifcopenshell

from ecarbon.config import discover, get_design
from ecarbon.extract.openings import openings_for


def ifc_counts(design) -> tuple[int | None, int | None]:
    if design.ifc is None:
        return None, None
    try:
        f = ifcopenshell.open(str(design.ifc))
    except Exception:
        return None, None
    windows = len(f.by_type("IfcWindow"))
    doors = len(f.by_type("IfcDoor"))
    # A model with neither has no semantic openings to compare against.
    if windows == 0 and doors == 0:
        return None, None
    return windows, doors


def pct_error(ours: int, truth: int) -> float | None:
    return None if truth == 0 else 100.0 * (ours - truth) / truth


def main(argv: list[str]) -> int:
    designs = [get_design(argv[0])] if argv else list(discover())

    print(
        f"{'design':34} {'win':>5} {'ifc':>5} {'err%':>7}   "
        f"{'door':>5} {'ifc':>5} {'err%':>7}  variants"
    )
    win_errors: list[float] = []
    door_errors: list[float] = []
    no_truth = 0
    nothing_read = 0

    for d in designs:
        key = d.key.split("_Technical")[0][:34]
        try:
            openings, notes = openings_for(d)
        except Exception as exc:  # noqa: BLE001
            print(f"{key:34} {'error':>5}  {type(exc).__name__}")
            nothing_read += 1
            continue

        ours_w = sum(o.count for o in openings if o.kind == "window")
        ours_d = sum(o.count for o in openings if o.kind == "door")
        truth_w, truth_d = ifc_counts(d)

        if not openings:
            print(f"{key:34} {'-':>5} {'-':>5} {'no sched':>7}")
            nothing_read += 1
            continue
        if truth_w is None:
            print(
                f"{key:34} {ours_w:>5} {'-':>5} {'no truth':>8}   "
                f"{ours_d:>5} {'-':>5} {'no truth':>8}"
            )
            no_truth += 1
            continue

        ew = pct_error(ours_w, truth_w)
        ed = pct_error(ours_d, truth_d)
        if ew is not None:
            win_errors.append(abs(ew))
        if ed is not None:
            door_errors.append(abs(ed))
        print(
            f"{key:34} {ours_w:>5} {truth_w:>5} {ew:>+7.1f}   "
            f"{ours_d:>5} {truth_d:>5} {ed:>+7.1f}  {len(notes)}"
        )

    def summarise(label: str, errors: list[float]) -> None:
        if not errors:
            print(f"  {label}: nothing scoreable")
            return
        within10 = sum(1 for e in errors if e <= 10.0)
        within25 = sum(1 for e in errors if e <= 25.0)
        print(
            f"  {label}: median {statistics.median(errors):.1f}%  "
            f"mean {statistics.fmean(errors):.1f}%  worst {max(errors):.1f}%  "
            f"within 10% {within10}/{len(errors)}  within 25% {within25}/{len(errors)}"
        )

    print(f"\nScored against IFC on {len(win_errors)} designs.")
    summarise("windows", win_errors)
    summarise("doors   ", door_errors)
    print(
        f"  excluded: {no_truth} with no semantic openings in the IFC, "
        f"{nothing_read} with no readable openings schedule"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
