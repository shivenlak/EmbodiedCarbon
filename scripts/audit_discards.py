#!/usr/bin/env python3
"""What each stage throws away, and how much of it looked usable.

Every accuracy bug found in this project so far was a silent discard: a filter
or a threshold removing real data while the stage returned a plausible result
and raised nothing. The list, in order of discovery:

  * Quebec's thickness column read as its material column, because `VAR`
    scored as prose.
  * Ontario's tag references left unrepaired, so a schedule that parsed was
    never used.
  * Atlantic's name column 34 pt from its header, losing to a 1-cell noise
    cluster 3 pt away.
  * Ontario and Atlantic sections drawn a quarter turn from upright, so no
    datum ever paired with its elevation.
  * Interior partitions deleted by a 1000 mm minimum segment length, in a
    group holding 297 segments under 250 mm.
  * `AB_ADU_01` counting one storey twice, reading 15 doors against 9.
  * Every BC IFC declaring its length unit as FOOT.
  * A one-layer name filter tightened for built depth, which took Ontario's
    roof assembly with it -- 42% coverage to 29%.

Scoring reports what survived. None of these would appear in one, because a
discarded thing is not scored. This reports the other side: per design, what
each stage rejected, why, and -- crucially -- how much usable content the
rejected thing still contained. A refusal carrying five layers and a stated
thickness is a different animal from one carrying an empty block.

    python scripts/audit_discards.py             # whole catalogue
    python scripts/audit_discards.py AB QC       # just those regions
"""

from __future__ import annotations

import collections
import sys

from ecarbon.config import discover
from ecarbon.extract.assemblies import assemblies_on_page

# A refusal that still carried this much structure is worth a second look: the
# block was probably real and something about its *name* or its edges was
# wrong, rather than the block not being an assembly at all.
SUBSTANTIAL_LAYERS = 3


def _reason_class(message: str) -> str:
    """Group refusals by cause rather than by wording."""
    lowered = message.lower()
    for needle, label in (
        ("is a material rather than an assembly", "name looks like a material"),
        ("gives its thickness as var", "drawing says VAR"),
        ("no layer states a thickness", "no thickness stated"),
        ("beyond the", "implausibly deep"),
        ("more layers than", "too many layers (blocks merged)"),
        ("no layers found", "empty block"),
    ):
        if needle in lowered:
            return label
    return "other"


def audit(regions: set[str] | None = None) -> int:
    designs = [
        d
        for d in sorted(discover(), key=lambda x: x.key)
        if not regions or d.key.split("_")[0].upper() in regions
    ]
    by_reason: collections.Counter[str] = collections.Counter()
    substantial: list[tuple[str, str, str, int, float]] = []
    totals = collections.Counter()

    for design in designs:
        key = design.key.split("_Technical")[0]
        try:
            import pymupdf

            from ecarbon.intake import inventory
            from ecarbon.models import SheetType

            sheets, _, _ = inventory(design.drawings_pdf)
            doc = pymupdf.open(design.drawings_pdf)
        except Exception as exc:
            print(f"{key:28} CRASHED {exc}")
            continue
        try:
            for sheet in sheets:
                if sheet.sheet_type is not SheetType.ASSEMBLY_SCHEDULE:
                    continue
                if not sheet.readable:
                    continue
                for asm in assemblies_on_page(doc[sheet.page], sheet.sheet_no):
                    if not asm.tag:
                        continue
                    reason = asm.implausible()
                    if reason is None:
                        totals["kept"] += 1
                        continue
                    totals["refused"] += 1
                    label = _reason_class(reason)
                    by_reason[label] += 1
                    n_layers = len(asm.layers or [])
                    depth = asm.total_thickness_mm or 0.0
                    if n_layers >= SUBSTANTIAL_LAYERS and depth > 0:
                        substantial.append((key, asm.tag, label, n_layers, depth))
        except Exception as exc:
            print(f"{key:28} CRASHED {exc}")
        finally:
            doc.close()

    print(f"\n{'':4}{len(designs)} designs · {totals['kept']} assemblies kept · "
          f"{totals['refused']} refused\n")
    print("  Refusals by cause")
    for reason, n in by_reason.most_common():
        print(f"    {n:>4}  {reason}")

    print(
        f"\n  Refused while still carrying {SUBSTANTIAL_LAYERS}+ layers and a "
        f"stated depth\n  (these are the ones where the refusal may be removing "
        f"real quantities)"
    )
    if not substantial:
        print("    none")
    else:
        print(f"    {'design':26} {'tag':5} {'layers':>6} {'depth mm':>9}  cause")
        for key, tag, reason, n_layers, depth in sorted(substantial):
            print(f"    {key[:26]:26} {tag:5} {n_layers:>6} {depth:>9.0f}  {reason}")
        print(
            f"\n    {len(substantial)} such blocks. Each is a block the parser "
            f"read deeply enough to extract layers and a depth from, and then "
            f"dropped whole."
        )
    return 0


if __name__ == "__main__":
    wanted = {a.upper() for a in sys.argv[1:]} or None
    raise SystemExit(audit(wanted))
