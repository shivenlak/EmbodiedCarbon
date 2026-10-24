"""Step 21: Statistical uncertainty propagation and sensitivity ranking.

Propagates:
  1. Carbon factor statistical uncertainty (EPD uncertainty_pct from BEAM / EC3)
  2. Quantity measurement uncertainty based on confidence labels:
     - MEASURED:  +/- 5%
     - INFERRED:  +/- 15%
     - ASSUMED:   +/- 30%

Calculates combined 95% confidence intervals (1.96 * sigma) and ranks
assumptions by their contribution to the total variance (sensitivity ranking).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from ecarbon.models import CarbonResult, Confidence, TakeoffResult

# Measurement uncertainty standard deviations by confidence class
QUANTITY_UNCERTAINTY_MAP: dict[Confidence, float] = {
    Confidence.MEASURED: 5.0,   # +/- 5%
    Confidence.INFERRED: 15.0,  # +/- 15%
    Confidence.ASSUMED: 30.0,   # +/- 30%
}


@dataclass
class SensitivityDriver:
    rank: int
    line_id: str
    element_class: str
    material: str
    quantity: float
    unit: str
    confidence: str
    kg_co2e: float
    factor_uncertainty_pct: float
    quantity_uncertainty_pct: float
    combined_sigma_kg_co2e: float
    variance_contribution_pct: float
    assumption: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class UncertaintyReport:
    total_kg_co2e: float
    std_err_sigma_kg_co2e: float
    range_68_low_kg_co2e: float   # 1 sigma
    range_68_high_kg_co2e: float
    range_95_low_kg_co2e: float   # 1.96 sigma
    range_95_high_kg_co2e: float
    relative_uncertainty_pct: float
    top_drivers: list[SensitivityDriver]
    summary: str

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "top_drivers": [d.to_dict() for d in self.top_drivers],
        }


def analyze_uncertainty(
    takeoff: TakeoffResult,
    carbon: CarbonResult,
) -> UncertaintyReport:
    """Perform rigorous uncertainty propagation and sensitivity analysis."""
    lines_by_id = {l.id: l for l in takeoff.lines}
    
    driver_candidates: list[dict] = []
    total_variance = 0.0

    for cl in carbon.lines:
        if not cl.is_counted or cl.kg_co2e is None or cl.kg_co2e <= 0.0:
            continue

        tl = lines_by_id.get(cl.line_id)
        if not tl:
            continue

        # 1. Factor uncertainty
        u_factor = cl.factor.uncertainty_pct if (cl.factor and cl.factor.uncertainty_pct) else 15.0

        # 2. Quantity uncertainty
        conf = tl.confidence if isinstance(tl.confidence, Confidence) else Confidence(tl.confidence)
        u_qty = QUANTITY_UNCERTAINTY_MAP.get(conf, 15.0)

        # 3. Combined fractional uncertainty: sqrt(u_factor^2 + u_qty^2)
        u_comb_pct = math.sqrt(u_factor**2 + u_qty**2)

        # 4. Standard error sigma in kg CO2e
        sigma_kg = cl.kg_co2e * (u_comb_pct / 100.0)
        var_line = sigma_kg**2
        total_variance += var_line

        # Primary assumption explanation
        primary_assumption = ""
        if tl.assumptions:
            primary_assumption = tl.assumptions[0]
        elif conf == Confidence.ASSUMED:
            primary_assumption = f"Standard assumption applied for {tl.material or tl.element_class.value}."
        elif conf == Confidence.INFERRED:
            primary_assumption = f"Inferred from drawing schedules and typical build-up."
        else:
            primary_assumption = f"Directly measured from vector blueprint dimension chains."

        driver_candidates.append(
            {
                "line_id": cl.line_id,
                "element_class": tl.element_class.value if hasattr(tl.element_class, "value") else str(tl.element_class),
                "material": cl.factor.name if cl.factor else (tl.material or "Unknown"),
                "quantity": tl.effective_quantity,
                "unit": tl.unit.value if hasattr(tl.unit, "value") else str(tl.unit),
                "confidence": conf.value,
                "kg_co2e": round(cl.kg_co2e, 2),
                "factor_uncertainty_pct": round(u_factor, 1),
                "quantity_uncertainty_pct": round(u_qty, 1),
                "sigma_kg": round(sigma_kg, 2),
                "var_line": var_line,
                "assumption": primary_assumption,
            }
        )

    std_err = math.sqrt(total_variance) if total_variance > 0 else 0.0
    rel_unc = (std_err / carbon.total_kg_co2e * 100.0) if carbon.total_kg_co2e > 0 else 0.0

    # Sort drivers by variance contribution descending
    driver_candidates.sort(key=lambda x: -x["var_line"])

    top_drivers: list[SensitivityDriver] = []
    for rank, d in enumerate(driver_candidates[:8], 1):
        pct_var = (d["var_line"] / total_variance * 100.0) if total_variance > 0 else 0.0
        top_drivers.append(
            SensitivityDriver(
                rank=rank,
                line_id=d["line_id"],
                element_class=d["element_class"],
                material=d["material"],
                quantity=d["quantity"],
                unit=d["unit"],
                confidence=d["confidence"],
                kg_co2e=d["kg_co2e"],
                factor_uncertainty_pct=d["factor_uncertainty_pct"],
                quantity_uncertainty_pct=d["quantity_uncertainty_pct"],
                combined_sigma_kg_co2e=d["sigma_kg"],
                variance_contribution_pct=round(pct_var, 1),
                assumption=d["assumption"],
            )
        )

    top3_names = ", ".join(f"{d.material} ({d.variance_contribution_pct:.0f}%)" for d in top_drivers[:3])
    summary = (
        f"Whole-building A1-A3 carbon estimate is {carbon.total_kg_co2e:,.0f} kg CO2e "
        f"[95% CI: {max(0.0, carbon.total_kg_co2e - 1.96 * std_err):,.0f} - "
        f"{carbon.total_kg_co2e + 1.96 * std_err:,.0f} kg CO2e, +/-{1.96 * rel_unc:.1f}%]. "
        f"Top uncertainty drivers: {top3_names}."
    )

    return UncertaintyReport(
        total_kg_co2e=round(carbon.total_kg_co2e, 2),
        std_err_sigma_kg_co2e=round(std_err, 2),
        range_68_low_kg_co2e=round(max(0.0, carbon.total_kg_co2e - std_err), 2),
        range_68_high_kg_co2e=round(carbon.total_kg_co2e + std_err, 2),
        range_95_low_kg_co2e=round(max(0.0, carbon.total_kg_co2e - 1.96 * std_err), 2),
        range_95_high_kg_co2e=round(carbon.total_kg_co2e + 1.96 * std_err, 2),
        relative_uncertainty_pct=round(rel_unc, 1),
        top_drivers=top_drivers,
        summary=summary,
    )
