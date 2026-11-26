"""A complete estimate beside the counted total: what a whole-building LCA adds.

The counted total is what the drawings state, A1-A3. A whole-building figure
such as CMHC's Building Performance Reports (A1-A5) also carries what the
drawings leave open and what happens between factory and finished building.
Comparing the two directly reads our number as half right; most of the gap is
scope, not error. This adds, each as its own labelled, ASSUMED item:

- the open decisions (cladding, roofing, floor finish) at the middle of the
  range their options span;
- reinforcing steel in the footings and foundation walls at stated typical
  rates (Kootenay guide, steel rebar per metre);
- A4, transport to site: mass x a 100 km haul (the NRC National Guidelines'
  worked example) x 0.1 kgCO2e per tonne-km (a typical diesel truck, assumed);
- A5, construction losses: each line's A1-A3 x CMHC's own waste rate for its
  material category.

The counted total never changes. Every figure here is a stated rule over a
counted or measured quantity, so the calculation stays auditable.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

HAUL_KM = 100.0
TRUCK_KG_PER_TKM = 0.1
REBAR_15M_PER_M = 1.34  # kgCO2e per m, Kootenay: 134 per 100 m of 15 mm steel rebar
FOOTING_BARS = 2  # 2-15M continuous in a strip footing
WALL_BARS = 4  # 4-15M horizontal in a foundation wall
# A product declared per m2 with a density: mass from a nominal 10 mm.
THIN_PRODUCT_M = 0.01
DEFAULT_WASTE = 0.05
SEED = Path(__file__).with_name("seed_factors.json")


@dataclass
class Item:
    key: str
    label: str
    kg_co2e: float
    low_kg_co2e: float
    high_kg_co2e: float
    basis: str  # how it was calculated, one sentence
    source: str


@dataclass
class CompleteEstimate:
    counted_kg_co2e: float
    items: list[Item] = field(default_factory=list)

    @property
    def total_kg_co2e(self) -> float:
        return round(self.counted_kg_co2e + sum(i.kg_co2e for i in self.items), 1)

    @property
    def low_kg_co2e(self) -> float:
        return round(self.counted_kg_co2e + sum(i.low_kg_co2e for i in self.items), 1)

    @property
    def high_kg_co2e(self) -> float:
        return round(self.counted_kg_co2e + sum(i.high_kg_co2e for i in self.items), 1)

    def to_dict(self) -> dict:
        return {
            "counted_kg_co2e": self.counted_kg_co2e,
            "total_kg_co2e": self.total_kg_co2e,
            "low_kg_co2e": self.low_kg_co2e,
            "high_kg_co2e": self.high_kg_co2e,
            "modules": "A1-A5",
            "items": [asdict(i) for i in self.items],
        }


def _waste_by_category() -> dict[str, float]:
    maps = json.loads(SEED.read_text())["cmhc_mappings"]
    return {v["category"]: v["waste_factor"] for v in maps.values()}


def _run_m(description: str | None) -> float | None:
    m = re.search(r"over ([\d.]+) m(?:\s|$| run| perimeter)", description or "")
    return float(m.group(1)) if m else None


def complete_estimate(takeoff, carbon, provider, decisions=(), traces=None) -> CompleteEstimate:
    """The counted total plus the stated additions above, each an Item."""
    from ecarbon.carbon.calc_trace import explain_all

    traces = traces or explain_all(takeoff, carbon)
    cats = provider.factor_categories()
    waste = _waste_by_category()
    est = CompleteEstimate(counted_kg_co2e=carbon.total_kg_co2e)

    # Open decisions at their midpoint, their own range as the item's range.
    for c in decisions:
        lo, hi = c.low_kg_co2e, c.high_kg_co2e
        if hi <= 0:
            continue
        est.items.append(Item(
            key=f"open-{c.assembly_tag}-{c.category}".lower(),
            label=f"{c.category}, not specified on the drawings",
            kg_co2e=round((lo + hi) / 2, 1), low_kg_co2e=lo, high_kg_co2e=hi,
            basis=f"middle of the options over {c.area_m2:.0f} m2 ({lo:,.0f} to {hi:,.0f} kgCO2e)",
            source="the factor store's options for this category",
        ))

    # Rebar in footings and foundation walls, at stated typical rates.
    rebar_m = 0.0
    for ln in takeoff.lines:
        run = _run_m(ln.description)
        if run is None:
            continue
        if ln.element_class.value == "footing":
            rebar_m += run * FOOTING_BARS
        elif ln.element_class.value == "foundation_wall":
            rebar_m += run * WALL_BARS
    if rebar_m:
        kg = rebar_m * REBAR_15M_PER_M
        est.items.append(Item(
            key="rebar", label="Reinforcing steel in footings and foundation walls",
            kg_co2e=round(kg, 1), low_kg_co2e=round(kg * 0.5, 1), high_kg_co2e=round(kg * 2, 1),
            basis=(f"{rebar_m:.0f} m of 15 mm bar ({FOOTING_BARS} continuous in each footing, "
                   f"{WALL_BARS} horizontal in each foundation wall) x {REBAR_15M_PER_M} kgCO2e/m; "
                   f"the structural drawings govern"),
            source="Kootenay Construction Material Impact Guide (2026), steel rebar per 100 m",
        ))

    # A4 transport and A5 construction losses, line by line.
    mass_kg = a5 = 0.0
    for cl in carbon.lines:
        if cl.kg_co2e is None or cl.factor is None:
            continue
        tr = traces.get(cl.line_id)
        dens = cl.factor.density_kg_m3
        if tr is not None and tr.converted_quantity is not None:
            unit = tr.converted_unit
            if unit.startswith("kg"):
                mass_kg += tr.converted_quantity
            elif unit == "m³" and dens:
                mass_kg += tr.converted_quantity * dens
            elif unit == "m²" and dens:
                mass_kg += tr.converted_quantity * THIN_PRODUCT_M * dens
        a5 += cl.kg_co2e * waste.get(cats.get(cl.factor.factor_id, ""), DEFAULT_WASTE)
    if mass_kg:
        kg = mass_kg / 1000 * HAUL_KM * TRUCK_KG_PER_TKM
        est.items.append(Item(
            key="a4", label="A4 transport to site",
            kg_co2e=round(kg, 1), low_kg_co2e=round(kg * 0.5, 1), high_kg_co2e=round(kg * 3, 1),
            basis=(f"{mass_kg / 1000:,.1f} t of counted material x {HAUL_KM:.0f} km x "
                   f"{TRUCK_KG_PER_TKM} kgCO2e per tonne-km (typical diesel truck, assumed)"),
            source="NRC National Guidelines for Whole-Building LCA (method; 100 km haul as in its worked example)",
        ))
    if a5:
        est.items.append(Item(
            key="a5", label="A5 construction losses (waste)",
            kg_co2e=round(a5, 1), low_kg_co2e=round(a5 * 0.5, 1), high_kg_co2e=round(a5 * 2, 1),
            basis="each counted line's A1-A3 x the waste rate for its material (concrete 5%, framing 10%, ...)",
            source="CMHC material mappings (waste factors); site energy not included",
        ))
    return est
