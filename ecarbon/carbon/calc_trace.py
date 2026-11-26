"""How every kgCO2e figure was calculated, step by step (contract C8).

The UX session's first ask: an auditor must be able to see where each number
comes from. `calculate_carbon` keeps only the result and a sentence; this
rebuilds the arithmetic from what the result carries, with the same
`reconcile_units`, and refuses to disagree with it: `explain` asserts its
product equals the line's `kg_co2e`, so a step list can never describe a
calculation other than the one that produced the total.

Words, on purpose: carbon is always "kgCO2e"; plain mass is always
"kg (mass)", because mass is itself a step in the calculation.

models.py is frozen, so this is a separate record the API, the CSV and the
report all read.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from ecarbon.carbon.calculate import STUD_DEPTH_M, _is_framing_by_area, reconcile_units
from ecarbon.extract.assemblies import FRAMING_FRACTION
from ecarbon.models import CarbonLine, FactorRef, TakeoffLine

UNIT_WORDS = {"m2": "m²", "m3": "m³", "m": "m", "kg": "kg (mass)", "each": "each", "100m2": "100 m²"}

# Waste is not applied: CMHC's mapping carries a waste factor, but the bill is
# of what the drawings show. Stated as a step so nobody has to guess.
WASTE_FACTOR = 1.0


def unit_word(u: str) -> str:
    return UNIT_WORDS.get(str(u).lower().replace(" ", ""), str(u))


def _num(v: float) -> str:
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 100:
        return f"{v:,.0f}"
    if a >= 1:
        return f"{v:,.2f}"
    return f"{v:.4g}"


@dataclass
class Step:
    label: str
    value: float | None
    unit: str
    detail: str = ""
    source: str = ""  # where this step's figure comes from


@dataclass
class CalcTrace:
    line_id: str
    counted: bool
    steps: list[Step] = field(default_factory=list)
    formula: str = ""  # one line, recomputable by hand
    kg_co2e: float | None = None
    # The converted quantity the factor multiplies, in the factor's unit.
    converted_quantity: float | None = None
    converted_unit: str = ""
    density_kg_m3: float | None = None
    thickness_m: float | None = None
    # Set when the user chose the material: the factor id they chose.
    material_chosen: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def factor_source(f: FactorRef) -> str:
    """The full citation for a factor, as an auditor would want it."""
    bits = [f.source]
    if f.source_id and f.source_id not in f.source:
        bits.append(f"ref {f.source_id}")
    if f.geography:
        bits.append(f"geography {f.geography}")
    bits.append({"epd": "product EPD", "industry_avg": "industry-average EPD"}.get(
        getattr(f.data_type, "value", f.data_type), "generic factor"))
    if f.valid_to:
        bits.append(f"valid to {f.valid_to}")
    return "; ".join(str(b) for b in bits if b)


_LAYER_RE = re.compile(r"^(\S+) layer (\d+) of (\d+) from the assemblies schedule; ([\d.]+) mm over ([\d.]+) m2")
_SHARE_RE = re.compile(r"takes? (\d+)% of (?:it|the)")
_COVER_RE = re.compile(r"at ([\d.]+)% coverage")
_FRAMING_RE = re.compile(r"Framing: (.+?)\.(?:\s|$)")


def _buildup_step(line: TakeoffLine) -> Step | None:
    """For a layer of a drawn assembly: area x thickness x share, with the
    framing spacing said, so the volume can be checked against the drawing."""
    note = line.basis.note or ""
    m = _LAYER_RE.search(note)
    if not m or line.unit.value != "m3":
        return None
    tag, i, n, mm, area = m.group(1), m.group(2), m.group(3), float(m.group(4)), float(m.group(5))
    parts = [f"{_num(area)} m² × {mm / 1000:.4g} m"]
    share = _SHARE_RE.search(note)
    if share:
        parts.append(f"× {share.group(1)}%")
    cover = _COVER_RE.search(line.description or "")
    if cover:
        parts.append(f"× {cover.group(1)}% coverage")
    detail = " ".join(parts) + f" = {_num(line.quantity)} m³"
    fr = _FRAMING_RE.search(note)
    if fr:
        detail += f". Framing: {fr.group(1)}"
    return Step(
        label=f"From the drawn build-up: {tag} layer {i} of {n}",
        value=line.quantity,
        unit=unit_word("m3"),
        detail=detail,
        source=(line.provenance.sheet_no or f"page {line.provenance.page + 1}") + f", assembly {tag}",
    )


def explain(line: TakeoffLine, cline: CarbonLine | None, chosen: str | None = None) -> CalcTrace:
    """The steps from the drawing to this line's kgCO2e."""
    qty_unit = line.unit.value
    sheet = line.provenance.sheet_no or f"page {line.provenance.page + 1}"
    where = f"{sheet}" + (f", {line.provenance.detail}" if line.provenance.detail else "")
    t = CalcTrace(line_id=line.id, counted=bool(cline and cline.kg_co2e is not None))

    t.steps.append(Step(
        label=f"Quantity read ({line.confidence.value})",
        value=line.quantity,
        unit=unit_word(qty_unit),
        detail=line.basis.note or "",
        source=where,
    ))
    buildup = _buildup_step(line)
    if buildup is not None:
        t.steps.append(buildup)
    qty = line.effective_quantity
    if line.user_override is not None:
        t.steps.append(Step(
            label="Quantity you stated",
            value=qty,
            unit=unit_word(qty_unit),
            detail=line.override_note or "replaces the quantity read",
            source="you",
        ))

    if chosen:
        t.material_chosen = chosen
        t.steps.append(Step(
            label="Material you chose",
            value=None,
            unit="",
            detail=f"replaces the material the drawings name ({line.material or line.element_class.value})",
            source="you",
        ))

    if cline is None or cline.kg_co2e is None or cline.factor is None:
        reason = (cline.missing_reason if cline else None) or "no carbon factor applied"
        t.steps.append(Step(label="Not counted", value=None, unit="", detail=reason))
        t.formula = f"not counted: {reason}"
        return t

    f = cline.factor
    framing = _is_framing_by_area(line, f)
    thickness = STUD_DEPTH_M * FRAMING_FRACTION if framing else None
    conv, note = reconcile_units(qty, line.unit, f.declared_unit, f.density_kg_m3, thickness)
    d_u = f.declared_unit.strip().lower()
    t.converted_quantity, t.converted_unit = conv, unit_word(d_u)
    t.density_kg_m3 = f.density_kg_m3 if "density" in note else None
    t.thickness_m = (thickness or (0.15 if "150 mm" in note else None)) if "thickness" in note or framing else None

    parts = [f"{_num(qty)} {unit_word(qty_unit)}"]
    if conv != qty or d_u != qty_unit.lower():
        if t.density_kg_m3:
            t.steps.append(Step(
                label="Mass, from volume × density",
                value=conv,
                unit=unit_word(d_u),
                detail=f"{_num(qty)} {unit_word(qty_unit)} × {_num(f.density_kg_m3)} kg/m³",
                source=f"density from {f.name} ({f.source})",
            ))
            parts.append(f"× {_num(f.density_kg_m3)} kg/m³ = {_num(conv)} {unit_word(d_u)}")
        elif t.thickness_m:
            src = (
                f"{STUD_DEPTH_M * 1000:.0f} mm stud depth × {FRAMING_FRACTION:.0%} framing fraction (assumed)"
                if framing else ("150 mm, assumed: no thickness stated" if "150 mm" in note else "stated thickness")
            )
            op = "×" if d_u == "m3" else "÷"
            t.steps.append(Step(
                label="Converted to the factor's unit",
                value=conv,
                unit=unit_word(d_u),
                detail=f"{_num(qty)} {unit_word(qty_unit)} {op} {t.thickness_m:.4g} m",
                source=src,
            ))
            parts.append(f"{op} {t.thickness_m:.4g} m = {_num(conv)} {unit_word(d_u)}")
        else:
            t.steps.append(Step(
                label="Converted to the factor's unit",
                value=conv,
                unit=unit_word(d_u),
                detail=cline.conversion_note or note,
            ))
            parts.append(f"= {_num(conv)} {unit_word(d_u)}")

    t.steps.append(Step(
        label="Waste allowance",
        value=WASTE_FACTOR,
        unit="×",
        detail="none applied: the bill is what the drawings show",
    ))

    gwp_unit = f"kgCO₂e per {unit_word(d_u).replace(' (mass)', '')}"
    t.steps.append(Step(
        label=f"Carbon factor: {f.name}",
        value=f.gwp_value,
        unit=gwp_unit,
        detail=(
            f"modules {'+'.join(f.modules)}"
            + (f"; ±{f.uncertainty_pct:.0f}%" if f.uncertainty_pct else "")
            + (f"; {f.attribution}" if f.attribution else "")
        ),
        source=factor_source(f),
    ))
    kg = conv * WASTE_FACTOR * f.gwp_value
    if abs(round(kg, 2) - cline.kg_co2e) > max(0.02, 1e-6 * abs(kg)):
        raise AssertionError(
            f"calc trace for {line.id} gives {kg:.2f} kgCO2e, the result says {cline.kg_co2e:.2f}"
        )
    t.kg_co2e = cline.kg_co2e
    t.steps.append(Step(label="Embodied carbon (A1–A3)", value=cline.kg_co2e, unit="kgCO₂e"))
    parts.append(f"× {_num(f.gwp_value)} {gwp_unit.replace('₂', '2')} = {_num(cline.kg_co2e)} kgCO2e")
    t.formula = " ".join(parts).replace("₂", "2").replace("²", "2").replace("³", "3")
    return t


def explain_all(takeoff, carbon, chosen: dict | None = None) -> dict[str, CalcTrace]:
    by_line = {c.line_id: c for c in carbon.lines}
    chosen = chosen or {}
    return {ln.id: explain(ln, by_line.get(ln.id), chosen.get(ln.id)) for ln in takeoff.lines}
