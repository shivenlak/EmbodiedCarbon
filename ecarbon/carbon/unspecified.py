"""Decisions the drawings leave open, priced as a range rather than guessed.

Some assemblies name a layer without choosing its material. AB_Fourplex_01's
W2 carries "NON-COMBUSTIBLE LIGHT-WEIGHT CLADDING PLACE HOLDER" and its R2
carries "ROOFING PLACEHOLDER": the designer has deferred the choice, not
forgotten it.

There are three things a tool can do with that, and only one of them is
honest. It can pick a material and say nothing, which is what a default
mapping would do and what criterion 3 exists to forbid. It can drop the layer
and report a total that is quietly missing a real part of the building, which
is what we did before this module. Or it can say what the drawing says, show
what each available option would cost in carbon, and let the range stand until
somebody decides.

A spread here is not a failure of extraction. It is the actual state of the
design, and a builder choosing cladding is choosing between these numbers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ecarbon.models import FactorRef, TakeoffResult

# What a placeholder layer is a placeholder *for*. Matched against the layer
# text the schedule states, so an assembly that spells it differently is
# reported as unspecified-but-uncategorised rather than mis-assigned.
_CATEGORY_WORDS: tuple[tuple[str, str], ...] = (
    ("Cladding", r"CLAD|SIDING|EXTERIOR\s+FINISH|RAINSCREEN|VENEER"),
    ("Roofing", r"ROOF(?!\s*TRUSS)|SHINGLE|MEMBRANE"),
    ("Interior Finishes", r"INTERIOR\s+FINISH|WALL\s+FINISH"),
)


@dataclass
class Option:
    """One material the open decision could be settled with."""

    factor: FactorRef
    kg_co2e: float

    @property
    def name(self) -> str:
        return self.factor.name


@dataclass
class UnspecifiedChoice:
    """A layer the drawings decline to specify, with what each option costs."""

    assembly_tag: str
    category: str
    drawing_says: str
    area_m2: float
    sheet_no: str | None = None
    page: int | None = None
    options: list[Option] = field(default_factory=list)

    @property
    def low_kg_co2e(self) -> float:
        return round(min(o.kg_co2e for o in self.options), 1) if self.options else 0.0

    @property
    def high_kg_co2e(self) -> float:
        return round(max(o.kg_co2e for o in self.options), 1) if self.options else 0.0

    @property
    def spread_kg_co2e(self) -> float:
        return round(self.high_kg_co2e - self.low_kg_co2e, 1)

    @property
    def note(self) -> str:
        return (
            f"The drawings state {self.drawing_says!r} rather than naming a "
            f"material, so this is a decision still open to the builder, not a "
            f"reading failure. Over {self.area_m2:.0f} m2 the options in the "
            f"factor store span {self.low_kg_co2e:,.0f} to "
            f"{self.high_kg_co2e:,.0f} kgCO2e. Nothing is added to the total "
            f"until one is chosen."
        )


def _category_for(text: str) -> str | None:
    upper = text.upper()
    for category, pattern in _CATEGORY_WORDS:
        if re.search(pattern, upper):
            return category
    return None


def _area_for_assembly(takeoff: TakeoffResult, tag: str) -> float | None:
    """The element area this assembly covers, from its own built layers.

    Each layer line is area x layer thickness, so dividing one back out
    recovers the area the assembly was applied over. Taking it from the
    takeoff rather than recomputing it means the range is quoted over exactly
    the surface the rest of the bill used.
    """
    best: float | None = None
    for line in takeoff.lines:
        if (line.assembly_tag or "").upper() != tag.upper():
            continue
        if line.unit.value != "m3":
            continue
        thickness = (line.basis.note or "") if line.basis else ""
        m = re.search(r"(\d+(?:\.\d+)?)\s*mm", thickness)
        if not m:
            continue
        mm = float(m.group(1))
        if mm <= 0:
            continue
        area = line.quantity / (mm / 1000.0)
        # Layers of one assembly share an area; take the median-ish value by
        # preferring the first, and ignore a layer whose note named some other
        # millimetre figure.
        if best is None or abs(area - best) / max(best, 1.0) < 0.02:
            best = area if best is None else best
    return best


def unspecified_choices(
    takeoff: TakeoffResult, assemblies: dict, factors
) -> list[UnspecifiedChoice]:
    """Open material decisions in the assemblies this design actually uses.

    Only assemblies that produced lines are considered, so a schedule entry the
    building does not use is not presented as a decision anybody has to make.
    """
    used = {
        (ln.assembly_tag or "").upper() for ln in takeoff.lines if ln.assembly_tag
    }
    by_category = _factors_by_category(factors)

    out: list[UnspecifiedChoice] = []
    for tag, assembly in assemblies.items():
        if tag.upper() not in used:
            continue
        area = _area_for_assembly(takeoff, tag)
        if area is None or area <= 0:
            continue
        for layer in getattr(assembly, "layers", []):
            if not getattr(layer, "is_placeholder", False):
                continue
            category = _category_for(layer.material or "")
            if category is None:
                continue
            candidates = by_category.get(category, [])
            options = [
                Option(factor=f, kg_co2e=round(area * f.gwp_value, 1))
                for f in candidates
                if f.declared_unit == "m2"
            ]
            if not options:
                continue
            options.sort(key=lambda o: o.kg_co2e)
            out.append(
                UnspecifiedChoice(
                    assembly_tag=tag,
                    category=category,
                    drawing_says=(layer.material or "").strip(),
                    area_m2=round(area, 1),
                    sheet_no=getattr(assembly, "sheet", None),
                    page=getattr(assembly, "page", None),
                    options=options,
                )
            )
    out.sort(key=lambda c: c.spread_kg_co2e, reverse=True)
    return out


def _factors_by_category(factors) -> dict[str, list[FactorRef]]:
    """Store factors grouped by the category its mappings assign them.

    Read through the provider rather than the database so an alternative
    provider -- EC3, when it is wired -- answers the same question.
    """
    grouped: dict[str, list[FactorRef]] = {}
    categories = getattr(factors, "factor_categories", None)
    if callable(categories):
        mapping = categories()
    else:
        mapping = {}
    for factor in factors.list_factors():
        category = mapping.get(factor.factor_id)
        if category:
            grouped.setdefault(category, []).append(factor)
    return grouped
