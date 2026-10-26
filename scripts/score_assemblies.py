#!/usr/bin/env python
"""Score the assemblies schedule: what parses, what is refused, and why.

    python scripts/score_assemblies.py            # every design
    python scripts/score_assemblies.py AB_Sixplex # one design

There is no numeric truth for a layer build-up, so this reports coverage and
refusals rather than an error percentage, plus one real comparison: built
depth against the IFC's own `IfcMaterialLayerSet` where both exist.

The refusal count is as much the result as the parse count. Reading this sheet
generically across firms sometimes merges adjacent blocks or starts one on a
layer row, and the output is structurally wrong while looking ordinary, so
anything failing `Assembly.implausible` is reported unreadable instead of
used.
"""

from __future__ import annotations

import collections
import statistics
import sys

from ecarbon.config import discover, get_design
from ecarbon.extract.assemblies import assemblies_for


def region_of(key: str) -> str:
    return key.split("_")[0].upper()


def ifc_depths(design) -> tuple[dict[str, float], dict[str, list[float]]]:
    """Built depth per assembly tag from the IFC's material layer sets.

    Returns (unambiguous depths, ambiguous tags with their variants). One tag
    can carry several different layer sets -- AB_Fourplex_01 models P2 both as
    a 165.1 mm plain partition and a 201 mm rated one -- and taking whichever
    appears first scores against an arbitrary pick. Our P2 is the rated
    build-up and matches 201 mm exactly, so choosing the nearest variant would
    flatter us and choosing the first penalised us by 22%. Neither is a
    measurement, so such tags are excluded from the statistics and reported
    separately, the same way a degraded IFC is.
    """
    if design.ifc is None:
        return {}, {}
    try:
        import ifcopenshell

        from ecarbon.bench.ifc_quantities import material_layers

        f = ifcopenshell.open(str(design.ifc))
    except Exception:
        return {}, {}

    seen: dict[str, set[float]] = collections.defaultdict(set)
    for element in list(f.by_type("IfcWall")) + list(f.by_type("IfcSlab")):
        name = element.Name or ""
        if ":" not in name:
            continue
        # "Basic Wall:W2 -RATED EXTERIOR ENVELOPE WALL:6595017" -> W2
        tag = name.split(":")[1].strip().split()[0].strip("-").upper()
        layers = material_layers(element)
        if not layers:
            continue
        seen[tag].add(round(sum(th for _m, th in layers), 1))

    unambiguous: dict[str, float] = {}
    ambiguous: dict[str, list[float]] = {}
    for tag, depths in seen.items():
        # Within a millimetre is the same build-up rounded differently.
        spread = max(depths) - min(depths)
        if len(depths) == 1 or spread <= 1.0:
            unambiguous[tag] = statistics.fmean(depths)
        else:
            ambiguous[tag] = sorted(depths)
    return unambiguous, ambiguous


def main(argv: list[str]) -> int:
    designs = [get_design(argv[0])] if argv else list(discover())

    kept_total = refused_total = 0
    by_region: collections.Counter[str] = collections.Counter()
    region_total: collections.Counter[str] = collections.Counter()
    depth_errors: list[float] = []
    exact = 0
    ambiguous_total = 0
    reasons: collections.Counter[str] = collections.Counter()

    print(f"{'design':40} {'kept':>5} {'refs':>5}  groups   vs IFC")
    for d in designs:
        region = region_of(d.key)
        region_total[region] += 1
        try:
            kept, refused = assemblies_for(d)
        except Exception as exc:  # noqa: BLE001
            print(f"{d.key[:40]:40} {'error':>5}  {type(exc).__name__}")
            continue

        kept_total += len(kept)
        refused_total += len(refused)
        if kept:
            by_region[region] += 1
        for message in refused:
            # The reason is the clause after the colon.
            tail = message.split(": ", 1)[-1]
            if "layers" in tail:
                reasons["too many layers"] += 1
            elif "depth" in tail:
                reasons["implausible built depth"] += 1
            elif "material rather than" in tail:
                reasons["name is one of its own layers"] += 1
            else:
                reasons["other"] += 1

        truth, ambiguous = ifc_depths(d)
        compared: list[str] = []
        for tag, asm in sorted(kept.items()):
            if tag.upper() not in truth:
                continue
            ours, theirs = asm.total_thickness_mm, truth[tag.upper()]
            if theirs <= 0:
                continue
            err = abs(ours - theirs) / theirs * 100.0
            depth_errors.append(err)
            if err < 0.5:
                exact += 1
            compared.append(f"{tag} {err:.0f}%")

        ambiguous_total += sum(1 for t in ambiguous if t in {k.upper() for k in kept})
        letters = "".join(sorted({a.group_letter for a in kept.values()}))
        print(
            f"{d.key[:40]:40} {len(kept):>5} {len(refused):>5}  {letters or '-':7}  "
            f"{' '.join(compared[:4])}"
        )

    print(f"\nAssemblies kept {kept_total}, refused as unreliable {refused_total}.")
    print("Designs with at least one trustworthy assembly, by region:")
    for region in sorted(region_total):
        print(f"   {region:6} {by_region[region]:>3} / {region_total[region]}")
    total_with = sum(by_region.values())
    print(f"   {'total':6} {total_with:>3} / {sum(region_total.values())}")

    if reasons:
        print("\nWhy an assembly was refused:")
        for reason, n in reasons.most_common():
            print(f"   {n:>3}  {reason}")

    if depth_errors:
        print(f"\nBuilt depth vs the IFC's material layer sets, on {len(depth_errors)} assemblies:")
        print(
            f"   median {statistics.median(depth_errors):.1f}%   "
            f"mean {statistics.fmean(depth_errors):.1f}%   "
            f"worst {max(depth_errors):.1f}%   "
            f"exact {exact}/{len(depth_errors)}   "
            f"within 10% {sum(1 for e in depth_errors if e <= 10)}/{len(depth_errors)}"
        )
        if ambiguous_total:
            print(
                f"   excluded {ambiguous_total} tag(s) the IFC models with more than one "
                f"build-up, where there is no single depth to compare against"
            )
    else:
        print("\nNo assembly could be compared against an IFC layer set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
