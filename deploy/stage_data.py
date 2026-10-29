#!/usr/bin/env python3
"""Copy a few plan sets into the deployment build context.

The catalogue is 2.7 GB and licence-restricted. Neither fact allows it into
the repository: the repo is public, so a commit there is ungated distribution
to anyone. The deployment is a different question -- it is gated behind
credentials and the judges can download the same files from CMHC themselves --
so a handful of sets are copied into the build context at deploy time and the
image is built from there.

`deploy/data/` is gitignored. Nothing here changes what may be committed.

Only two files per design are copied: the drawings PDF the pipeline reads, and
the Building Performance Report it takes project facts from. The IFC models,
HOT2000 files and DWGs are ground-truth and benchmarking inputs, used by
scripts/ and tests/ but never by the running service -- a full upload, takeoff,
carbon and trace cycle loads only pymupdf and numpy.

    python deploy/stage_data.py              # the default selection
    python deploy/stage_data.py AB_Sixplex   # or name your own
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Alberta only for the demo: both reach every element class (100% coverage),
# and Alberta is the region Landmark builds in and the one the gate pins.
# Partial coverage elsewhere is not hidden -- benchmark.md publishes it per
# region and FOR_JUDGES.md says the headline is a best case -- but a preloaded
# set reads as "this is what it does", so the preloaded ones are the ones it
# reads fully. AB_Rowhouse_02 is deliberately left out so the live upload in
# the demo is a set this service has never seen.
DEFAULT_SELECTION = (
    "AB_Fourplex_01",
    "AB_Sixplex",
)

HERE = Path(__file__).resolve().parent
STAGE = HERE / "data"


def stage(keys: tuple[str, ...]) -> int:
    from ecarbon.config import discover

    designs = {d.key: d for d in discover()}
    if not designs:
        print("No catalogue found. Set $EC_DATA and try again.", file=sys.stderr)
        return 1

    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    total = 0
    for wanted in keys:
        matches = [d for k, d in designs.items() if wanted.lower() in k.lower()]
        if not matches:
            print(f"  ! no design matching {wanted!r}", file=sys.stderr)
            continue
        design = matches[0]
        package = STAGE / design.package_dir.name
        copied = []

        if design.drawings_pdf is not None:
            target = package / design.drawings_pdf.relative_to(design.package_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(design.drawings_pdf, target)
            copied.append(target)

        for report in design.bpr:
            target = package / report.relative_to(design.package_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(report, target)
            copied.append(target)

        size = sum(p.stat().st_size for p in copied)
        total += size
        print(f"  {design.key[:44]:44} {len(copied)} files  {size / 1e6:>6.1f} MB")

    print(f"\n  {total / 1e6:.1f} MB staged in {STAGE}")
    print("  (gitignored; it is copied into the image at build time)")
    print("\n  Next: EC_DATA=deploy/data python deploy/prebuild.py")
    print("  That saves a takeoff per design so the first request is instant")
    print("  rather than paying 23-177 s to parse the set.")
    return 0


if __name__ == "__main__":
    chosen = tuple(sys.argv[1:]) or DEFAULT_SELECTION
    raise SystemExit(stage(chosen))
