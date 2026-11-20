#!/usr/bin/env python3
"""How accurate is it: our takeoff and carbon against independent references.

    python scripts/accuracy.py                 # all CMHC designs; writes both files
    python scripts/accuracy.py AB_Fourplex_01  # one design, printed

Three independent references ship with every CMHC package, each made by
professionals with nothing to do with this tool:

- the **IFC model** (the architect's BIM): material volumes, wall areas;
- the **HOT2000 energy model** (an energy advisor's): above-grade wall,
  ceiling and window areas;
- the **Building Performance Report** (CMHC's own LCA): carbon by element and
  the A1-A5 total.

Quantity error and carbon gap are reported separately, because they have
different causes: a wrong measurement versus a scope we do not count. Mixing
them is how a tool hides one behind the other.

Writes:
- `out/accuracy_cmhc.json`: per-design detail. Local only (out/ is ignored),
  because it quotes CMHC's per-design figures.
- `web/src/accuracy.json`: aggregates only (medians, spreads, counts), which
  the app's "How accurate is it" panel shows and which is safe to commit.

Holdout and Landmark results are merged in from their own runs when present
(`out/blind_holdout.json`, `out/landmark_compare.json`); nothing is invented
when they are not.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ecarbon.carbon.calculate import calculate_carbon  # noqa: E402
from ecarbon.carbon.store import LocalSnapshotProvider  # noqa: E402
from ecarbon.config import discover, get_design  # noqa: E402
from ecarbon.takeoff.builder import build_takeoff  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from run_pipeline import facts_for  # noqa: E402

TRUTH = ROOT / "out" / "ground_truth.json"
DETAIL = ROOT / "out" / "accuracy_cmhc.json"
SUMMARY = ROOT / "web" / "src" / "accuracy.json"

# Our element classes against the Building Performance Report's elements.
BPR_ELEMENT = {
    "slab_on_grade": "foundations",
    "footing": "foundations",
    "foundation_wall": "foundations",
    "floor_assembly": "upper_floors",
    "roof_assembly": "roofs",
    "exterior_wall": "external_walls",
    "insulation": "external_walls",
    "cladding": "external_walls",
    "window": "windows_doors",
    "door": "windows_doors",
    "stair": "stairs",
    "interior_partition": "interiors",
    "party_wall": "interiors",
}

# Materials both we and the IFC name the same way, compared by volume.
COMPARABLE_MATERIALS = (
    "CMHC_Concrete, CIP",
    "CMHC_Gypsum Board",
    "CMHC_Insulation, Rigid",
    "CMHC_Insulation, Batt",
    "CMHC_Plywood",
    "CMHC_Wood Framing",
)


def pct(ours: float | None, ref: float | None) -> float | None:
    if ours is None or not ref:
        return None
    return round(100.0 * (ours - ref) / ref, 1)


def footprint_m2(takeoff) -> float | None:
    for ln in takeoff.lines:
        if ln.id == "ln-slab-on-grade":
            m = re.search(r"over ([\d.]+) m2 footprint", ln.description or "")
            if m:
                return float(m.group(1))
    return None


def score(design, truth: dict, provider) -> dict:
    t0 = time.time()
    takeoff = build_takeoff(design, facts_for(design))
    carbon = calculate_carbon(takeoff, provider)
    lines = {ln.id: ln for ln in takeoff.lines}
    q = lambda lid: lines[lid].effective_quantity if lid in lines else None  # noqa: E731

    # Material volumes: our layer lines (m3) by CMHC material name.
    ours_vol: dict[str, float] = {}
    for ln in takeoff.lines:
        if ln.unit.value == "m3" and ln.material:
            ours_vol[ln.material] = ours_vol.get(ln.material, 0.0) + ln.effective_quantity
    ifc_vol = truth.get("material_volumes_m3") or {}
    materials = {
        m: {"ours": round(ours_vol[m], 2), "ifc": ifc_vol[m], "err_pct": pct(ours_vol[m], ifc_vol[m])}
        for m in COMPARABLE_MATERIALS
        if m in ours_vol and ifc_vol.get(m)
    }

    # Carbon by Building Performance Report element.
    by_elem: dict[str, float] = {}
    for cl in carbon.lines:
        if cl.kg_co2e is None:
            continue
        cls = lines[cl.line_id].element_class.value
        key = BPR_ELEMENT.get(cls)
        if key:
            by_elem[key] = by_elem.get(key, 0.0) + cl.kg_co2e
    total = carbon.total_kg_co2e or 0.0
    ours_share = {k: round(100.0 * v / total, 1) for k, v in by_elem.items()} if total else {}
    bpr_share = truth.get("bpr_element_pct") or {}

    # The architect's own quantities at OUR factors: separates "we measured
    # less" from "CMHC used other factors and modules". Framing layers are
    # left out, because the IFC models them as solid timber the full depth of
    # the cavity, which is not a timber volume.
    ifc_kg, ifc_priced = 0.0, []
    for mat, vol in ifc_vol.items():
        if not vol or "Framing" in mat:
            continue
        f = provider.find_by_material(mat)
        if f is None or f.declared_unit != "m3":
            continue
        ifc_kg += vol * f.gwp_value
        ifc_priced.append(mat)
    ours_same_scope = sum(
        cl.kg_co2e
        for cl in carbon.lines
        if cl.kg_co2e is not None
        and lines[cl.line_id].material in ifc_priced
    )
    a1_a5_kg = (truth.get("bpr_a1_a5_t") or 0) * 1000.0 or None

    return {
        "key": design.key,
        "region": truth.get("region"),
        "seconds": round(time.time() - t0, 1),
        "lines": len(takeoff.lines),
        "quantities": {
            "exterior_wall_m2": {
                "ours": q("ln-exterior-wall"),
                "ifc_gross": truth.get("exterior_wall_gross_m2"),
                "h2k_above_grade": truth.get("h2k_above_grade_wall_m2"),
                "err_vs_ifc_pct": pct(q("ln-exterior-wall"), truth.get("exterior_wall_gross_m2")),
                "err_vs_h2k_pct": pct(q("ln-exterior-wall"), truth.get("h2k_above_grade_wall_m2")),
            },
            "footprint_m2": {
                "ours": footprint_m2(takeoff),
                "h2k_ceiling": truth.get("h2k_ceiling_m2"),
                "err_vs_h2k_pct": pct(footprint_m2(takeoff), truth.get("h2k_ceiling_m2")),
            },
            "window_m2": {
                "ours": q("ln-windows"),
                "h2k": truth.get("h2k_window_m2"),
                "err_vs_h2k_pct": pct(q("ln-windows"), truth.get("h2k_window_m2")),
            },
            "materials_m3": materials,
        },
        "carbon": {
            "ours_a1_a3_kg": round(total, 0),
            "bpr_a1_a5_kg": a1_a5_kg,
            "ratio_to_a1_a5": round(total / a1_a5_kg, 3) if a1_a5_kg and total else None,
            "ifc_at_our_factors_kg": round(ifc_kg, 0) if ifc_priced else None,
            "ours_same_materials_kg": round(ours_same_scope, 0) if ifc_priced else None,
            "ifc_materials_priced": ifc_priced,
            "ours_share_pct": ours_share,
            "bpr_share_pct": bpr_share,
        },
    }


def _spread(xs: list[float]) -> dict | None:
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    xs.sort()
    q1 = xs[len(xs) // 4]
    q3 = xs[(3 * len(xs)) // 4]
    return {
        "n": len(xs),
        "median": round(statistics.median(xs), 1),
        "q1": round(q1, 1),
        "q3": round(q3, 1),
        "within_10pct": sum(1 for x in xs if abs(x) <= 10),
    }


def summarise(rows: list[dict]) -> dict:
    out: dict = {"generated": time.strftime("%Y-%m-%d"), "designs": len(rows)}
    qty = {
        "exterior wall area vs IFC model": [r["quantities"]["exterior_wall_m2"]["err_vs_ifc_pct"] for r in rows],
        "footprint vs energy model ceiling": [r["quantities"]["footprint_m2"]["err_vs_h2k_pct"] for r in rows],
        "window area vs energy model": [r["quantities"]["window_m2"]["err_vs_h2k_pct"] for r in rows],
    }
    for m in COMPARABLE_MATERIALS:
        qty[f"{m.replace('CMHC_', '')} volume vs IFC model"] = [
            r["quantities"]["materials_m3"].get(m, {}).get("err_pct") for r in rows
        ]
    out["quantity_error_pct"] = {k: s for k, v in qty.items() if (s := _spread(v))}
    out["reference_notes"] = [
        "The energy model (HOT2000) measures the thermal envelope, often for one unit of a "
        "multi-unit block, so its wall area is not compared; its ceiling area stands in for "
        "the footprint and its window area for the windows.",
        "The IFC model is not ground truth either: on AB_Fourplex_01 it omits the 76 mm "
        "below-grade rigid insulation that the drawings' F1 slab assembly calls for, so a "
        "rigid-insulation 'over-count' there is the model's gap, not ours.",
        "Material gaps the tool already reports as not counted: floor joists and roof "
        "trusses (wood framing), foundation walls (concrete), steel studs, and the "
        "cladding and roofing placeholders.",
    ]

    ratios = [r["carbon"]["ratio_to_a1_a5"] for r in rows if r["carbon"]["ratio_to_a1_a5"]]
    same = [
        (r["carbon"]["ours_same_materials_kg"], r["carbon"]["ifc_at_our_factors_kg"])
        for r in rows
        if r["carbon"].get("ifc_at_our_factors_kg")
    ]
    ratios_same = [o / i for o, i in same if i and o]
    out["carbon_vs_ifc_same_factors"] = (
        {
            "n": len(ratios_same),
            "median_ratio": round(statistics.median(ratios_same), 2),
            "q1": round(sorted(ratios_same)[len(ratios_same) // 4], 2),
            "q3": round(sorted(ratios_same)[(3 * len(ratios_same)) // 4], 2),
            "note": (
                "Our carbon over the architect's IFC quantities priced with OUR factors, "
                "for the materials both name (concrete, gypsum, insulation, sheathing; "
                "framing excluded because the IFC models it as solid layers). This "
                "isolates quantity error from factor and module differences."
            ),
        }
        if ratios_same
        else None
    )
    out["carbon_vs_cmhc_a1_a5"] = (
        {
            "n": len(ratios),
            "median_ratio": round(statistics.median(ratios), 2),
            "q1": round(sorted(ratios)[len(ratios) // 4], 2),
            "q3": round(sorted(ratios)[(3 * len(ratios)) // 4], 2),
            "note": (
                "Our A1-A3 total over CMHC's reported A1-A5 for the same design. Below 1 "
                "is expected (A4 transport and A5 construction are not counted) and "
                "the rest of the gap is scope we flag as not counted: cladding and "
                "roofing placeholders, joists, trusses, steel studs, foundation walls."
            ),
        }
        if ratios
        else None
    )

    # Element shares: mean absolute difference in percentage points, per element.
    diffs: dict[str, list[float]] = {}
    for r in rows:
        ours, bpr = r["carbon"]["ours_share_pct"], r["carbon"]["bpr_share_pct"]
        if not ours or not bpr:
            continue
        for k, v in bpr.items():
            diffs.setdefault(k, []).append(round(ours.get(k, 0.0) - v, 1))
    out["element_share_diff_points"] = {
        k: {"n": len(v), "median": round(statistics.median(v), 1)} for k, v in diffs.items()
    }

    by_region: dict[str, list[dict]] = {}
    for r in rows:
        by_region.setdefault(r["region"] or "?", []).append(r)
    out["by_region"] = {
        reg: {
            "designs": len(rs),
            "wall_vs_ifc": _spread([r["quantities"]["exterior_wall_m2"]["err_vs_ifc_pct"] for r in rs]),
            "with_carbon": sum(1 for r in rs if (r["carbon"]["ours_a1_a3_kg"] or 0) > 0),
            "carbon_ratio_median": (
                round(statistics.median(xs), 2)
                if (xs := [r["carbon"]["ratio_to_a1_a5"] for r in rs if r["carbon"]["ratio_to_a1_a5"]])
                else None
            ),
        }
        for reg, rs in sorted(by_region.items())
    }
    for name in ("blind_holdout", "landmark_compare"):
        f = ROOT / "out" / f"{name}.json"
        if f.is_file():
            out[name] = json.loads(f.read_text()).get("summary")
    return out


def main(argv: list[str]) -> int:
    truth = {t["key"]: t for t in json.loads(TRUTH.read_text())}
    designs = [get_design(argv[0])] if argv else list(discover())
    provider = LocalSnapshotProvider()
    rows = []
    for d in designs:
        if d.key not in truth:
            continue
        try:
            row = score(d, truth[d.key], provider)
        except Exception as exc:  # one bad set must not hide the rest
            print(f"{d.key:44} FAILED {exc}")
            continue
        rows.append(row)
        qq, cc = row["quantities"], row["carbon"]
        print(
            f"{d.key[:44]:44} {row['seconds']:5.1f}s lines {row['lines']:3}  "
            f"wall {qq['exterior_wall_m2']['err_vs_ifc_pct']!s:>6}%  "
            f"fp {qq['footprint_m2']['err_vs_h2k_pct']!s:>6}%  "
            f"win {qq['window_m2']['err_vs_h2k_pct']!s:>6}%  "
            f"A1-A3/A1-A5 {cc['ratio_to_a1_a5']}"
        )
    if argv:
        print(json.dumps(rows[0], indent=1) if rows else "no truth for that design")
        return 0
    DETAIL.parent.mkdir(exist_ok=True)
    DETAIL.write_text(json.dumps(rows, indent=1))
    SUMMARY.write_text(json.dumps(summarise(rows), indent=1) + "\n")
    print(f"\nwrote {DETAIL} (local) and {SUMMARY}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
