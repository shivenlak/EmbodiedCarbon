"""Step 23: Variants as deltas engine.

Enables builders to rapidly compare design variants (e.g. Option 1 vs Option 2,
alternate facades, or layout variations) by computing a line-by-line delta
bill of quantities and embodied carbon differential.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from ecarbon.carbon.calculate import calculate_carbon
from ecarbon.carbon.store import FactorProvider, LocalSnapshotProvider
from ecarbon.models import CarbonResult, Confidence, ElementClass, TakeoffLine, TakeoffResult, Unit
from ecarbon.takeoff.builder import generate_takeoff


@dataclass
class LineDelta:
    line_id: str
    element_class: str
    assembly_tag: str | None
    material: str | None
    change_type: str  # "added" | "removed" | "modified" | "unchanged"
    base_quantity: float | None
    variant_quantity: float | None
    quantity_delta: float
    unit: str
    base_kg_co2e: float | None
    variant_kg_co2e: float | None
    carbon_delta_kg_co2e: float
    confidence: str
    description: str


@dataclass
class VariantDeltaResult:
    base_project_name: str
    variant_project_name: str
    base_total_kg_co2e: float
    variant_total_kg_co2e: float
    net_carbon_delta_kg_co2e: float
    net_carbon_pct_change: float
    base_intensity_kg_per_m2: float | None
    variant_intensity_kg_per_m2: float | None
    delta_intensity_kg_per_m2: float | None
    added_lines_count: int
    removed_lines_count: int
    modified_lines_count: int
    unchanged_lines_count: int
    lines: list[LineDelta]
    by_assembly_delta: dict[str, float]
    by_element_delta: dict[str, float]
    summary: str

    def to_dict(self) -> dict:
        return asdict(self)


def compute_variant_delta(
    base_takeoff: TakeoffResult,
    variant_takeoff: TakeoffResult,
    provider: FactorProvider | None = None,
) -> VariantDeltaResult:
    """Compute line-by-line and whole-building embodied carbon delta between two variants."""
    prov = provider or LocalSnapshotProvider()
    base_carbon = calculate_carbon(base_takeoff, prov)
    variant_carbon = calculate_carbon(variant_takeoff, prov)

    base_lines_map: dict[str, TakeoffLine] = {l.id: l for l in base_takeoff.lines}
    var_lines_map: dict[str, TakeoffLine] = {l.id: l for l in variant_takeoff.lines}

    base_c_map: dict[str, float] = {
        cl.line_id: (cl.kg_co2e or 0.0) for cl in base_carbon.lines
    }
    var_c_map: dict[str, float] = {
        cl.line_id: (cl.kg_co2e or 0.0) for cl in variant_carbon.lines
    }

    all_line_ids = sorted(set(base_lines_map.keys()) | set(var_lines_map.keys()))

    lines: list[LineDelta] = []
    added_count = 0
    removed_count = 0
    modified_count = 0
    unchanged_count = 0

    by_assembly_delta: dict[str, float] = {}
    by_element_delta: dict[str, float] = {}

    for lid in all_line_ids:
        b_line = base_lines_map.get(lid)
        v_line = var_lines_map.get(lid)

        b_qty = b_line.effective_quantity if b_line else None
        v_qty = v_line.effective_quantity if v_line else None

        b_kg = base_c_map.get(lid, 0.0) if b_line else None
        v_kg = var_c_map.get(lid, 0.0) if v_line else None

        ref_line = v_line or b_line
        assert ref_line is not None

        elem_cls = ref_line.element_class.value if isinstance(ref_line.element_class, ElementClass) else str(ref_line.element_class)
        tag = ref_line.assembly_tag
        mat = ref_line.material
        unit_str = ref_line.unit.value if isinstance(ref_line.unit, Unit) else str(ref_line.unit)
        desc = ref_line.description or elem_cls
        conf = (ref_line.confidence.value if isinstance(ref_line.confidence, Confidence) else str(ref_line.confidence))

        if b_line is None:
            # Added in variant
            change_type = "added"
            q_delta = round(v_qty or 0.0, 2)
            c_delta = round(v_kg or 0.0, 2)
            added_count += 1
        elif v_line is None:
            # Removed in variant
            change_type = "removed"
            q_delta = round(-(b_qty or 0.0), 2)
            c_delta = round(-(b_kg or 0.0), 2)
            removed_count += 1
        else:
            diff_q = abs((v_qty or 0.0) - (b_qty or 0.0))
            if diff_q > 0.001 or b_line.material != v_line.material:
                change_type = "modified"
                q_delta = round((v_qty or 0.0) - (b_qty or 0.0), 2)
                c_delta = round((v_kg or 0.0) - (b_kg or 0.0), 2)
                modified_count += 1
            else:
                change_type = "unchanged"
                q_delta = 0.0
                c_delta = 0.0
                unchanged_count += 1

        lines.append(
            LineDelta(
                line_id=lid,
                element_class=elem_cls,
                assembly_tag=tag,
                material=mat,
                change_type=change_type,
                base_quantity=round(b_qty, 2) if b_qty is not None else None,
                variant_quantity=round(v_qty, 2) if v_qty is not None else None,
                quantity_delta=q_delta,
                unit=unit_str,
                base_kg_co2e=round(b_kg, 2) if b_kg is not None else None,
                variant_kg_co2e=round(v_kg, 2) if v_kg is not None else None,
                carbon_delta_kg_co2e=c_delta,
                confidence=conf,
                description=desc,
            )
        )

        # Accumulate breakdown
        if abs(c_delta) > 0.01:
            grp_assemb = tag or elem_cls
            by_assembly_delta[grp_assemb] = round(by_assembly_delta.get(grp_assemb, 0.0) + c_delta, 2)
            by_element_delta[elem_cls] = round(by_element_delta.get(elem_cls, 0.0) + c_delta, 2)

    net_c_delta = round(variant_carbon.total_kg_co2e - base_carbon.total_kg_co2e, 2)
    pct_change = (
        round((net_c_delta / base_carbon.total_kg_co2e) * 100.0, 2)
        if base_carbon.total_kg_co2e > 0
        else 0.0
    )

    base_intens = base_carbon.intensity_kg_co2e_per_m2
    var_intens = variant_carbon.intensity_kg_co2e_per_m2
    delta_intens = round(var_intens - base_intens, 2) if (var_intens is not None and base_intens is not None) else None

    direction = "increase" if net_c_delta > 0 else "reduction"
    summary = (
        f"Variant {variant_takeoff.project.name} vs Base {base_takeoff.project.name}: "
        f"{abs(net_c_delta):,.1f} kg CO2e ({abs(pct_change):.1f}%) {direction} "
        f"({modified_count} modified, {added_count} added, {removed_count} removed lines)."
    )

    return VariantDeltaResult(
        base_project_name=base_takeoff.project.name,
        variant_project_name=variant_takeoff.project.name,
        base_total_kg_co2e=base_carbon.total_kg_co2e,
        variant_total_kg_co2e=variant_carbon.total_kg_co2e,
        net_carbon_delta_kg_co2e=net_c_delta,
        net_carbon_pct_change=pct_change,
        base_intensity_kg_per_m2=base_intens,
        variant_intensity_kg_per_m2=var_intens,
        delta_intensity_kg_per_m2=delta_intens,
        added_lines_count=added_count,
        removed_lines_count=removed_count,
        modified_lines_count=modified_count,
        unchanged_lines_count=unchanged_count,
        lines=lines,
        by_assembly_delta=by_assembly_delta,
        by_element_delta=by_element_delta,
        summary=summary,
    )


def compare_variant_pdfs(
    base_pdf: str | Path,
    variant_pdf: str | Path,
    provider: FactorProvider | None = None,
) -> VariantDeltaResult:
    """Generate both takeoffs and produce variant delta in <30 seconds."""
    base_to = generate_takeoff(base_pdf)
    var_to = generate_takeoff(variant_pdf)
    return compute_variant_delta(base_to, var_to, provider)
