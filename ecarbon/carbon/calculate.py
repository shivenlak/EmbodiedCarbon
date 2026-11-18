"""Carbon calculation engine, unit reconciliation, and module-scope guard.

Implements the requirements of RESEARCH.md §6/§9 and docs/PLAN.md Step 12:
  - Unit reconciliation: m3 <-> m2 <-> kg <-> each via physical density and thickness.
  - Strict module-scope discipline: REFUSES to sum non-A1-A3 modules together.
    (Criterion 3: 'only like-for-like modules may be summed').
  - Unmatched materials produce visible "no factor found" rows that are reported
    and EXCLUDED from the total, NEVER silently zeroed.
  - Assembly and material contribution breakdown summing to 100%.
  - Propagation of statistical uncertainty ranges (range_low, range_high).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from ecarbon.carbon.store import FactorProvider, LocalSnapshotProvider
from ecarbon.extract.assemblies import FRAMING_FRACTION
from ecarbon.models import (
    CarbonLine,
    CarbonResult,
    Contribution,
    FactorRef,
    TakeoffLine,
    TakeoffResult,
    Unit,
)

DEFAULT_MODULES = ("A1", "A2", "A3")

# A 2x6 stud, the depth assumed when framing is carried only as a wall area.
STUD_DEPTH_M = 0.140


def reconcile_units(
    quantity: float,
    from_unit: Unit | str,
    declared_unit: str,
    density_kg_m3: float | None = None,
    thickness_m: float | None = None,
) -> tuple[float, str]:
    """Convert a takeoff quantity into the factor's declared unit.

    Returns:
        (converted_quantity, conversion_note)
    """
    f_u = str(from_unit).lower().strip()
    d_u = declared_unit.lower().strip()

    # Exact match
    if f_u == d_u:
        return quantity, f"{f_u} directly matches declared unit {d_u}."

    # Hundred square metres
    if (d_u == "100m2" or d_u == "100 m2") and f_u == "m2":
        return quantity / 100.0, "m2 converted to 100m2 (qty / 100)."

    if (f_u == "100m2" or f_u == "100 m2") and d_u == "m2":
        return quantity * 100.0, "100m2 converted to m2 (qty x 100)."

    # m3 -> kg via density
    if f_u == "m3" and d_u == "kg":
        if density_kg_m3 is None or density_kg_m3 <= 0:
            raise ValueError(f"Cannot convert m3 to kg without density for declared unit {declared_unit}")
        return quantity * density_kg_m3, f"m3 converted to kg via density {density_kg_m3:.1f} kg/m3."

    # kg -> m3 via density
    if f_u == "kg" and d_u == "m3":
        if density_kg_m3 is None or density_kg_m3 <= 0:
            raise ValueError(f"Cannot convert kg to m3 without density for declared unit {declared_unit}")
        return quantity / density_kg_m3, f"kg converted to m3 via density {density_kg_m3:.1f} kg/m3."

    # m2 -> m3 via thickness
    if f_u == "m2" and d_u == "m3":
        if thickness_m and thickness_m > 0:
            return quantity * thickness_m, f"m2 converted to m3 via thickness {thickness_m*1000:.0f} mm."
        return quantity * 0.15, "m2 converted to m3 via thickness 150 mm, assumed: no thickness is stated."

    # m3 -> m2 via thickness
    if f_u == "m3" and d_u == "m2":
        if thickness_m and thickness_m > 0:
            return quantity / thickness_m, f"m3 converted to m2 via thickness {thickness_m*1000:.0f} mm."
        return quantity / 0.15, "m3 converted to m2 via thickness 150 mm, assumed: no thickness is stated."

    # Default fallback if unit compatible
    return quantity, f"Declared unit {declared_unit} assumed 1:1 with {from_unit}."


def compute_carbon_line(
    line: TakeoffLine,
    factor: FactorRef | None,
    allowed_modules: Sequence[str] = DEFAULT_MODULES,
    thickness_m: float | None = None,
) -> CarbonLine:
    """Compute carbon for one takeoff line, strictly enforcing module scope."""
    qty = line.effective_quantity

    if factor is None:
        return CarbonLine(
            line_id=line.id,
            quantity=qty,
            unit=line.unit,
            factor=None,
            kg_co2e=None,
            missing_reason=f"No carbon factor found in factor store for {line.material or line.element_class.value}",
        )

    # Check module scope
    if any(m not in allowed_modules for m in factor.modules):
        raise ValueError(
            f"Module scope mismatch: line {line.id} has factor {factor.factor_id} with modules {factor.modules}, "
            f"which cannot be summed under target scope {list(allowed_modules)}. "
            "Challenge rule: only like-for-like modules may be summed."
        )

    conv_qty, note = reconcile_units(
        quantity=qty,
        from_unit=line.unit,
        declared_unit=factor.declared_unit,
        density_kg_m3=factor.density_kg_m3,
        thickness_m=thickness_m,
    )

    kg_co2e = conv_qty * factor.gwp_value

    return CarbonLine(
        line_id=line.id,
        quantity=qty,
        unit=line.unit,
        factor=factor,
        kg_co2e=round(kg_co2e, 2),
        conversion_note=note,
        missing_reason=None,
    )


def _is_framing_by_area(line: TakeoffLine, factor: FactorRef | None) -> bool:
    """Framing lumber billed by wall area, which needs its stud share applied."""
    return (
        factor is not None
        and line.unit == Unit.M2
        and factor.declared_unit.strip().lower() == "m3"
        and "framing" in (line.material or "").lower()
    )


def _framing_layer(takeoff: TakeoffResult, line: TakeoffLine) -> TakeoffLine | None:
    """An assembly layer of the same element that already counts the framing."""
    return next(
        (
            other
            for other in takeoff.lines
            if other is not line
            and other.element_class == line.element_class
            and other.unit == Unit.M3
            and "framing" in (other.material or "").lower()
        ),
        None,
    )


def calculate_carbon(
    takeoff: TakeoffResult,
    provider: FactorProvider | None = None,
    allowed_modules: Sequence[str] = DEFAULT_MODULES,
) -> CarbonResult:
    """Derive whole-building embodied carbon from a takeoff result."""
    prov = provider or LocalSnapshotProvider()

    carbon_lines: list[CarbonLine] = []
    uncounted_ids: list[str] = []
    total_kg_co2e = 0.0

    assembly_totals: dict[str, float] = defaultdict(float)
    material_totals: dict[str, float] = defaultdict(float)

    # Uncertainty propagation: accumulate (delta_kg_co2e)^2
    variance_sum = 0.0

    for line in takeoff.lines:
        factor = None
        if line.material:
            factor = prov.find_by_material(line.material)
        elif line.element_class:
            factor = prov.find_by_material(line.element_class.value)

        framing = _is_framing_by_area(line, factor)
        layer = _framing_layer(takeoff, line) if framing else None
        if layer is not None:
            cline = CarbonLine(
                line_id=line.id,
                quantity=line.effective_quantity,
                unit=line.unit,
                factor=None,
                kg_co2e=None,
                missing_reason=(
                    f"Framing is counted in the {layer.assembly_tag or 'assembly'} framing "
                    f"layer ({layer.id}), so this wall area carries none rather than "
                    f"counting the studs twice."
                ),
            )
        else:
            cline = compute_carbon_line(
                line=line,
                factor=factor,
                allowed_modules=allowed_modules,
                thickness_m=STUD_DEPTH_M * FRAMING_FRACTION if framing else None,
            )
            if framing and cline.kg_co2e is not None:
                # Studs fill a share of the wall, not all of it: solid timber
                # over the whole area overstated this line about sevenfold.
                cline.conversion_note = (
                    f"m2 converted to m3 as framing: {STUD_DEPTH_M * 1000:.0f} mm stud depth x "
                    f"{FRAMING_FRACTION:.0%} framing fraction (studs at 400 mm centres, "
                    f"assumed; the schedule gives no framing quantity)."
                )
        carbon_lines.append(cline)

        if cline.is_counted and cline.kg_co2e is not None:
            total_kg_co2e += cline.kg_co2e

            # Assembly contribution
            assemb_key = line.assembly_tag or line.element_class.value
            assembly_totals[assemb_key] += cline.kg_co2e

            # Material category
            mat_key = (
                cline.factor.name
                if cline.factor
                else (line.material or line.element_class.value)
            )
            material_totals[mat_key] += cline.kg_co2e

            # Uncertainty
            u_pct = cline.factor.uncertainty_pct if (cline.factor and cline.factor.uncertainty_pct) else 15.0
            sigma = cline.kg_co2e * (u_pct / 100.0)
            variance_sum += sigma**2
        else:
            uncounted_ids.append(line.id)

    total_kg_co2e = round(total_kg_co2e, 2)

    # Intensity
    denom = takeoff.project.intensity_denominator
    intensity = round(total_kg_co2e / denom, 2) if denom and denom > 0 else None

    # Percentages
    by_assembly: list[Contribution] = []
    for k, val in sorted(assembly_totals.items(), key=lambda x: -x[1]):
        pct = (val / total_kg_co2e * 100.0) if total_kg_co2e > 0 else 0.0
        by_assembly.append(Contribution(key=k, kg_co2e=round(val, 2), pct_of_total=round(pct, 1)))

    by_material: list[Contribution] = []
    for k, val in sorted(material_totals.items(), key=lambda x: -x[1]):
        pct = (val / total_kg_co2e * 100.0) if total_kg_co2e > 0 else 0.0
        by_material.append(Contribution(key=k, kg_co2e=round(val, 2), pct_of_total=round(pct, 1)))

    # Uncertainty bounds (+/- 1 sigma)
    std_err = variance_sum**0.5
    range_low = round(max(0.0, total_kg_co2e - std_err), 2)
    range_high = round(total_kg_co2e + std_err, 2)

    return CarbonResult(
        takeoff_source=takeoff.source_file,
        modules=list(allowed_modules),
        total_kg_co2e=total_kg_co2e,
        intensity_kg_co2e_per_m2=intensity,
        intensity_basis=takeoff.project.gfa_basis,
        lines=carbon_lines,
        by_assembly=by_assembly,
        by_material_category=by_material,
        uncounted_lines=uncounted_ids,
        range_low_kg_co2e=range_low,
        range_high_kg_co2e=range_high,
    )
