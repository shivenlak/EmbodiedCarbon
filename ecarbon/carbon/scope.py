"""What the estimate includes, element by element, as an LCA report declares it.

The NRC National Guidelines for Whole-Building LCA ask an assessment to state
"which building elements are included" (section 2.5) and give the list to use:
Appendix B, Table 9, by UniFormat code. A practitioner doing this from scratch
would walk that list and say, for each element, what was counted and what was
not. This does the same walk over the takeoff:

- **counted**: priced lines from the drawings (measured or inferred);
- **estimated**: priced, but at least one line is a stated standard (assumed);
- **open decision**: the drawings leave the product open (cladding, roofing,
  floor finish); priced at mid-range in the complete estimate, not the total;
- **added**: a stated rule in the complete estimate (rebar, A4, A5);
- **not counted / not included**: said, with the reason.

It also lists every layer the drawings *name* that no line prices (membranes,
underlays, air gaps), from the takeoff's own gaps, so a reader can see that
nothing on the drawings was silently skipped.

Nothing here changes a number. It reads the takeoff, the carbon result and the
complete estimate, and the rows' kgCO2e add up to them.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

COUNTED = "counted"
ESTIMATED = "estimated"
OPEN = "open decision"
ADDED = "added"
NOT_COUNTED = "not counted"
NOT_INCLUDED = "not included"
INSIDE = "counted elsewhere"

_LAYER_GAP_RE = re.compile(r"^(\S+) layer \d+ '([^']+)'(.*)$", re.S)
# Schedule rows that are not a material: air gaps, and wrapped fragments of
# the cell above ("MEET NBC 9.30.1.1.", "BELOW GRADE", "PLATE @ 1").
_NOT_A_MATERIAL_RE = re.compile(
    r"^(MEET|BELOW|ABOVE|PLATE|COORDINATED|REFER|SEE|PER|AS\s|TO\s|@)|^VENTING$|AIR\s+SPACE|SPACE\s+BETWEEN"
    r"|^(VENTED\s+)?CAVITY(?!.*(GIRT|FURRING|STRAPPING))", re.I)
# A structural layer deferred to the structural drawings is priced on its own
# line (concrete by the foundation lines, joists and trusses by the framing
# estimate), so its deferral is not a missing material.
_PRICED_ELSEWHERE_RE = re.compile(r"CONCRETE|JOIST|TRUSS|STRUCTURE|FRAMING|STUD", re.I)


@dataclass
class ScopeRow:
    code: str  # UniFormat level 3 (NRC Table 9)
    element: str
    status: str
    kg_co2e: float | None  # counted A1-A3, or the complete estimate's figure
    in_total: bool  # True when kg_co2e is part of the counted total
    lines: int
    detail: str


@dataclass
class NotPriced:
    assembly: str
    layer: str
    reason: str


@dataclass
class Scope:
    rows: list[ScopeRow] = field(default_factory=list)
    not_priced: list[NotPriced] = field(default_factory=list)
    source: str = (
        "NRC National Guidelines for Whole-Building Life Cycle Assessment, "
        "Appendix B, Table 9 (building model scope, UniFormat)"
    )

    def to_dict(self) -> dict:
        return asdict(self)


def _is_pile(ln) -> bool:
    return "pile" in ln.id or "pile" in (ln.material or "").lower()


def _is_concrete(ln) -> bool:
    return "concrete" in (ln.material or "").lower()


# (code, element, which takeoff lines belong to it)
_ELEMENTS = [
    ("A1010", "Standard foundations (footings)", lambda ln: ln.element_class.value == "footing" and not _is_pile(ln)),
    ("A1020", "Special foundations (piles)", _is_pile),
    ("A2010", "Walls for subgrade enclosures (foundation walls)", lambda ln: ln.element_class.value == "foundation_wall"),
    ("A4010", "Standard slabs-on-grade", lambda ln: ln.element_class.value == "slab_on_grade" and _is_concrete(ln)),
    ("A4090", "Slab-on-grade supplementary components (sub-slab insulation)",
     lambda ln: ln.element_class.value == "slab_on_grade" and not _is_concrete(ln)),
    ("B1010", "Floor construction", lambda ln: ln.element_class.value == "floor_assembly"),
    ("B1020", "Roof construction", lambda ln: ln.element_class.value == "roof_assembly"),
    ("B1080", "Stairs", lambda ln: ln.element_class.value == "stair"),
    ("B2010", "Exterior walls", lambda ln: ln.element_class.value in ("exterior_wall", "cladding", "insulation")),
    ("B2020", "Exterior windows", lambda ln: ln.element_class.value == "window"),
    ("B2050", "Doors, exterior and interior (C1030)", lambda ln: ln.element_class.value == "door"),
    ("C1010", "Interior partitions and party walls", lambda ln: ln.element_class.value in ("interior_partition", "party_wall")),
]

# Open decisions by the factor-store category they price.
_OPEN_CODES = {"Cladding": ("B2010", "Exterior wall cladding"), "Roofing": ("B3010", "Roofing"),
               "Flooring": ("C2030", "Flooring")}

_NOT_INCLUDED = [
    ("C2010", "Wall finishes (paint)",
     "not estimated: the drawings state no finish and the factor store holds no paint factor"),
    ("D", "Services: plumbing, HVAC, electrical, fire protection",
     "not estimated: an architectural plan set carries no services quantities; the guideline "
     "lists them, and a full LCA would add them from the mechanical and electrical drawings"),
    ("E2010", "Fixed furnishings (cabinets, millwork)",
     "not estimated: not quantified on the drawings"),
    ("A90", "Excavation and site preparation",
     "not estimated: little material; the guideline counts its energy in A5, and A5 here covers "
     "construction losses only"),
]


def _reason(rest: str) -> str:
    rest = rest.strip().lstrip(",").strip()
    if "left unspecified" in rest:
        return "left open by the drawings (an open decision)"
    if "defers" in rest or "Structural" in rest or "structural" in rest:
        return "quantity deferred to another discipline's drawings"
    if "VAR" in rest:
        return "thickness given as varies, so no volume"
    if "no thickness" in rest:
        return "no thickness stated, so no volume (a sheet or membrane)"
    if "intermittent" in rest:
        return "intermittent layer with no member width, so no volume"
    if "no factor" in rest or "holds no" in rest:
        return "sized, but no carbon factor for this material in the store"
    return rest[:120]


def scope_declaration(takeoff, carbon, complete=None) -> Scope:
    """Walk NRC Table 9 over this takeoff. `complete` is a CompleteEstimate."""
    kg = {c.line_id: c.kg_co2e for c in carbon.lines}
    sc = Scope()
    used: set[str] = set()

    for code, element, belongs in _ELEMENTS:
        mine = [ln for ln in takeoff.lines if ln.id not in used and belongs(ln)]
        used.update(ln.id for ln in mine)
        priced = [ln for ln in mine if kg.get(ln.id) is not None]
        total = round(sum(kg[ln.id] for ln in priced), 1)
        if not mine:
            sc.rows.append(ScopeRow(code, element, NOT_COUNTED, None, False, 0,
                                    "none on the drawings, or none could be read"))
            continue
        if not priced:
            sc.rows.append(ScopeRow(code, element, NOT_COUNTED, None, False, len(mine),
                                    f"{len(mine)} line(s) read, none could be priced"))
            continue
        assumed = [ln for ln in priced if ln.confidence.value == "assumed"]
        status = ESTIMATED if assumed else COUNTED
        how = ", ".join(sorted({ln.confidence.value for ln in priced}))
        detail = f"{len(priced)} priced line(s) ({how})"
        if assumed:
            detail += f"; {len(assumed)} from a stated standard"
        sc.rows.append(ScopeRow(code, element, status, total, True, len(priced), detail))

    # Gypsum ceilings sit inside the floor and roof build-ups.
    ceil = [ln for ln in takeoff.lines if ln.element_class.value in ("floor_assembly", "roof_assembly")
            and "gypsum" in (ln.material or "").lower() and kg.get(ln.id) is not None]
    sc.rows.append(ScopeRow(
        "C2050", "Ceiling finishes", INSIDE if ceil else NOT_COUNTED, None, False, len(ceil),
        "the gypsum ceiling layers, counted within floor and roof construction" if ceil
        else "no ceiling layer read",
    ))

    leftover = [ln for ln in takeoff.lines if ln.id not in used and kg.get(ln.id) is not None]
    if leftover:
        sc.rows.append(ScopeRow("—", "Other", COUNTED, round(sum(kg[ln.id] for ln in leftover), 1),
                                True, len(leftover), ", ".join(ln.description[:40] for ln in leftover[:3])))

    items = complete.items if complete is not None else []
    for it in items:
        if it.key.startswith("open-"):
            cat = it.label.split(",")[0]
            code, element = _OPEN_CODES.get(cat, ("—", cat))
            sc.rows.append(ScopeRow(code, element, OPEN, it.kg_co2e, False, 0,
                                    f"{it.basis}; in the complete estimate, not the counted total"))
        elif it.key == "rebar":
            sc.rows.append(ScopeRow("A1010/A2010", "Reinforcing steel", ADDED, it.kg_co2e, False, 0, it.basis))
        elif it.key == "a4":
            sc.rows.append(ScopeRow("A4", "Transport to site (module A4)", ADDED, it.kg_co2e, False, 0, it.basis))
        elif it.key == "a5":
            sc.rows.append(ScopeRow("A5", "Construction losses (module A5)", ADDED, it.kg_co2e, False, 0, it.basis))
    have = {r.code for r in sc.rows}
    for code, element in _OPEN_CODES.values():
        if code not in have and code != "B2010":
            sc.rows.append(ScopeRow(code, element, NOT_COUNTED, None, False, 0,
                                    "the drawings name no product and no option was priced"))
    for code, element, why in _NOT_INCLUDED:
        sc.rows.append(ScopeRow(code, element, NOT_INCLUDED, None, False, 0, why))

    seen: set[tuple[str, str]] = set()
    for g in takeoff.gaps:
        m = _LAYER_GAP_RE.match(g.message)
        if not m:
            continue
        tag, layer, rest = m.groups()
        reason = _reason(rest)
        if reason.startswith("left open") or "estimated from" in rest:
            continue  # an open decision, or framing estimated on its own line
        if _NOT_A_MATERIAL_RE.search(layer.strip()):
            continue
        if reason.startswith("quantity deferred") and _PRICED_ELSEWHERE_RE.search(layer):
            continue
        if re.search(r"FLOOR\s+FINISH", layer, re.I) and any(r.code == "C2030" and r.status == OPEN for r in sc.rows):
            continue  # priced as the floor-finish decision
        if (layer.upper(), reason) in seen:
            continue
        seen.add((layer.upper(), reason))
        sc.not_priced.append(NotPriced(tag, layer, reason))
    return sc
