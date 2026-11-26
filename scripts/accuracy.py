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
# Per-type IFC concrete with modelled layer thickness (scripts/ifc_concrete.py).
IFC_CONCRETE = ROOT / "out" / "ifc_concrete.json"
# An IFC slab whose concrete layer is thicker than this is the whole floor
# build-up tagged as concrete, not a slab: 15 models carry 454 mm.
IFC_SLAB_PLAUSIBLE_MM = 300
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


def _concrete_split(takeoff) -> tuple[float, float]:
    """Our concrete m3 as (slab, everything else)."""
    slab = other = 0.0
    for ln in takeoff.lines:
        if ln.material != "CMHC_Concrete, CIP" or ln.unit.value != "m3":
            continue
        if ln.element_class.value == "slab_on_grade":
            slab += ln.effective_quantity
        else:
            other += ln.effective_quantity
    return slab, other


def score(design, truth: dict, provider, ifc_conc: dict | None = None) -> dict:
    t0 = time.time()
    takeoff = build_takeoff(design, facts_for(design))
    carbon = calculate_carbon(takeoff, provider)
    # The complete estimate (A1-A5): what CMHC's figure is actually comparable to.
    from ecarbon.carbon.complete import complete_estimate
    from ecarbon.carbon.unspecified import unspecified_choices
    from ecarbon.extract.assemblies import assemblies_for

    try:
        decisions = unspecified_choices(takeoff, assemblies_for(design)[0], provider)
    except Exception:
        decisions = []
    complete = complete_estimate(takeoff, carbon, provider, decisions)
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

    # Concrete, split so the IFC's slab artefact does not pose as a shortfall.
    our_slab, our_other = _concrete_split(takeoff)
    ic = (ifc_conc or {}).get(design.key) or {}
    ifc_slab = ic.get("IfcSlab")
    slab_ok = bool(ifc_slab) and max(ifc_slab[1] or [0]) <= IFC_SLAB_PLAUSIBLE_MM
    ifc_other = (ic.get("IfcWall") or [0])[0] + ic.get("IfcFooting_solid", 0.0)
    concrete = {
        "slab": {
            "ours": round(our_slab, 2),
            "ifc": ifc_slab[0] if ifc_slab else None,
            "ifc_layer_mm": ifc_slab[1] if ifc_slab else None,
            "comparable": slab_ok,
            "err_pct": pct(our_slab, ifc_slab[0]) if slab_ok and our_slab else None,
        },
        "walls_and_footings": {
            "ours": round(our_other, 2),
            "ifc": round(ifc_other, 2) if ic else None,
            "err_pct": pct(our_other, ifc_other) if ic and ifc_other and our_other else None,
        },
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
    # Per square metre, because a report can cover one unit of a block the
    # drawings show whole (AB_Rowhouse_01: the report's 74 m2 is one unit of
    # a 143 m2-footprint block), and totals across different scopes compare
    # nothing. Ours over our measured floor area, theirs over theirs.
    fp_m2 = footprint_m2(takeoff)
    storeys = takeoff.project.storeys or 1
    our_gfa = fp_m2 * storeys if fp_m2 else None
    bpr_gfa = truth.get("bpr_gfa_m2")
    ours_int = total / our_gfa if our_gfa and total else None
    bpr_int = a1_a5_kg / bpr_gfa if a1_a5_kg and bpr_gfa else None

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
            "concrete": concrete,
        },
        "carbon": {
            "ours_a1_a3_kg": round(total, 0),
            "bpr_a1_a5_kg": a1_a5_kg,
            "ratio_to_a1_a5": round(total / a1_a5_kg, 3) if a1_a5_kg and total else None,
            "complete_a1_a5_kg": round(complete.total_kg_co2e, 0) if total else None,
            "complete_ratio_to_a1_a5": (
                round(complete.total_kg_co2e / a1_a5_kg, 3) if a1_a5_kg and total else None
            ),
            "ours_kg_m2": round(ours_int, 1) if ours_int else None,
            "bpr_a1_a5_kg_m2": round(bpr_int, 1) if bpr_int else None,
            "intensity_ratio": round(ours_int / bpr_int, 3) if ours_int and bpr_int else None,
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
    qty["slab concrete vs IFC (plausible IFC slabs only)"] = [
        r["quantities"].get("concrete", {}).get("slab", {}).get("err_pct") for r in rows
    ]
    qty["foundation walls + footings concrete vs IFC"] = [
        r["quantities"].get("concrete", {}).get("walls_and_footings", {}).get("err_pct") for r in rows
    ]
    for m in COMPARABLE_MATERIALS:
        qty[f"{m.replace('CMHC_', '')} volume vs IFC model"] = [
            r["quantities"]["materials_m3"].get(m, {}).get("err_pct") for r in rows
        ]
    out["quantity_error_pct"] = {k: s for k, v in qty.items() if (s := _spread(v))}
    out["reference_notes"] = [
        "The energy model (HOT2000) measures the thermal envelope, often for one unit of a "
        "multi-unit block, so its wall area is not compared; its ceiling area stands in for "
        "the footprint and its window area for the windows.",
        "15 IFC models tag the whole 454 mm slab build-up as concrete where the drawings "
        "state 100-130 mm; those slabs are left out of the slab comparison.",
        "The IFC model is not ground truth either: on AB_Fourplex_01 it omits the 76 mm "
        "below-grade rigid insulation that the drawings' F1 slab assembly calls for, so a "
        "rigid-insulation 'over-count' there is the model's gap, not ours.",
        "Material gaps the tool already reports as not counted: floor joists and roof "
        "trusses (wood framing), foundation walls (concrete), steel studs, and the "
        "cladding and roofing placeholders.",
    ]

    ratios = [r["carbon"]["ratio_to_a1_a5"] for r in rows if r["carbon"]["ratio_to_a1_a5"]]

    def bands(xs):
        return {
            "n": len(xs),
            "median_ratio": round(statistics.median(xs), 2) if xs else None,
            "within_10pct": sum(0.9 <= x <= 1.1 for x in xs),
            "within_20pct": sum(0.8 <= x <= 1.2 for x in xs),
            "within_30pct": sum(0.7 <= x <= 1.3 for x in xs),
        }

    # Against CMHC's A1-A5, like for like: the counted A1-A3, and the complete
    # estimate (open decisions at mid-range, rebar, A4, A5), all assumed additions.
    out["carbon_vs_cmhc"] = {
        "counted_a1_a3": bands(ratios),
        "complete_a1_a5": bands(
            [r["carbon"]["complete_ratio_to_a1_a5"] for r in rows if r["carbon"].get("complete_ratio_to_a1_a5")]
        ),
    }
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
    irs = [r["carbon"].get("intensity_ratio") for r in rows if r["carbon"].get("intensity_ratio")]
    out["intensity_vs_cmhc_a1_a5"] = (
        {
            "n": len(irs),
            "median_ratio": round(statistics.median(irs), 2),
            "q1": round(sorted(irs)[len(irs) // 4], 2),
            "q3": round(sorted(irs)[(3 * len(irs)) // 4], 2),
            "note": (
                "Our kg CO2e per m2 of measured floor area over CMHC's A1-A5 per m2 of "
                "its own floor area: robust to a report that covers one unit of a "
                "block the drawings show whole."
            ),
        }
        if irs
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
            "intensity_ratio_median": (
                round(statistics.median(ys), 2)
                if (ys := [r["carbon"].get("intensity_ratio") for r in rs if r["carbon"].get("intensity_ratio")])
                else None
            ),
            "carbon_ratio_median": (
                round(statistics.median(xs), 2)
                if (xs := [r["carbon"]["ratio_to_a1_a5"] for r in rs if r["carbon"]["ratio_to_a1_a5"]])
                else None
            ),
        }
        for reg, rs in sorted(by_region.items())
    }
    # Landmark results never enter this public file (their drawings are confidential).
    for name in ("blind_holdout",):
        f = ROOT / "out" / f"{name}.json"
        if f.is_file():
            data = json.loads(f.read_text())
            out[name] = data.get("summary") if isinstance(data, dict) else _blind_summary(data)
    return out


def _blind_summary(rows: list[dict]) -> dict:
    """score_blind.py writes one row per set (contract C6); the panel shows
    counts and medians, never a set's name."""
    fps = [abs(r["footprint_err_pct"]) for r in rows if r.get("footprint_err_pct") is not None]
    return {
        "sets": len(rows),
        "countries": sorted({r.get("country") for r in rows if r.get("country")}),
        "footprint_read": len(fps),
        "footprint_err_median_pct": round(statistics.median(fps), 1) if fps else None,
        "footprint_within_10pct": sum(e <= 10 for e in fps),
        "storeys_right": sum(bool(r.get("storeys_ok")) for r in rows),
        "openings_exact": sum(r.get("openings_err") == 0 for r in rows),
        "full_bill": sum((r.get("coverage_pct") or 0) >= 50 for r in rows),
        "nothing_read": sum(not r.get("coverage_pct") for r in rows),
        "vision": any(r.get("vision_used") for r in rows),
        "scored": "once, after the 25 Nov freeze, rules only",
    }


def main(argv: list[str]) -> int:
    truth = {t["key"]: t for t in json.loads(TRUTH.read_text())}
    designs = [get_design(argv[0])] if argv else list(discover())
    provider = LocalSnapshotProvider()
    ifc_conc = json.loads(IFC_CONCRETE.read_text()) if IFC_CONCRETE.is_file() else None
    rows = []
    for d in designs:
        if d.key not in truth:
            continue
        try:
            row = score(d, truth[d.key], provider, ifc_conc)
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
