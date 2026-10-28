"""STEP 9 capstone -- the per-design ground-truth manifest.

Joins all three reference sources for every design and, crucially, decides
whether each design is fit to score against. `docs/PLAN.md` asks for exactly
this: "a per-design data-quality check ... and exclude weak ground truth from
accuracy scoring".

The tiering matters because the catalogue's quality is not uniform, and
averaging over it would hide the real error:

  GOLD    IFC geometry complete, PDF readable, and HOT2000 corroborates the
          wall area within 15%. Highest confidence in the reference itself.
  SILVER  IFC geometry complete and PDF readable, but HOT2000 either is absent
          (the 7 BC designs ship Step Code checklists instead) or measures a
          different basis. The IFC is still a sound takeoff reference; the
          disagreement is recorded in `wall_agreement_pct`.
  GEOMETRY_ONLY  IFC geometry degraded (the 7 Vectorworks exports). Still
          fully usable for PDF-extraction scoring, which needs no IFC.
  ROBUSTNESS     The PDF has no readable text (the 8 NOR sets). Scored on
          whether we correctly REPORT what we cannot read, not on accuracy.

GOLD and SILVER are both scoreable; the tier says how much to trust the
reference, not whether to use it. `flags` records everything observed, and
`wall_agreement_pct` is a documented uncertainty ON THE GROUND TRUTH rather
than a pass/fail -- see `_tier` for why that distinction was forced.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path


class Tier(StrEnum):
    GOLD = "gold"
    SILVER = "silver"
    BRONZE = "bronze"
    GEOMETRY_ONLY = "geometry_only"
    ROBUSTNESS = "robustness"


# Agreement thresholds between the IFC and HOT2000 wall areas.
GOLD_AGREEMENT_PCT = 5.0
SILVER_AGREEMENT_PCT = 15.0


@dataclass
class DesignTruth:
    key: str
    region: str
    typology: str

    # -- drawing set ------------------------------------------------------
    n_pages: int = 0
    n_readable_pages: int = 0
    dominant_toolchain: str = "unknown"
    has_list_of_drawings: bool = False

    # -- IFC --------------------------------------------------------------
    ifc_geometry_coverage: float | None = None
    n_walls: int = 0
    exterior_wall_gross_m2: float | None = None
    exterior_wall_net_m2: float | None = None
    foundation_wall_m2: float | None = None
    slab_volume_m3: float | None = None
    footing_volume_m3: float | None = None
    concrete_volume_m3: float | None = None
    n_inferred_build_ups: int = 0
    material_volumes_m3: dict[str, float] = field(default_factory=dict)
    area_by_tag_m2: dict[str, float] = field(default_factory=dict)

    # -- HOT2000 ----------------------------------------------------------
    h2k_wall_m2: float | None = None
    h2k_above_grade_wall_m2: float | None = None
    h2k_foundation_wall_m2: float | None = None
    h2k_ceiling_m2: float | None = None
    h2k_window_m2: float | None = None

    # -- Building Performance Report --------------------------------------
    bpr_gfa_m2: float | None = None
    bpr_conditioned_m2: float | None = None
    bpr_total_ec_kg: float | None = None
    bpr_ec_per_gfa: float | None = None
    bpr_a1_a5_t: float | None = None
    bpr_element_pct: dict[str, float] = field(default_factory=dict)
    bpr_modules: str = ""

    # -- verdict ----------------------------------------------------------
    wall_agreement_pct: float | None = None
    tier: str = Tier.BRONZE
    flags: list[str] = field(default_factory=list)

    @property
    def scoreable_for_quantities(self) -> bool:
        return self.tier in (Tier.GOLD, Tier.SILVER)

    @property
    def a1_a3_ceiling_kg(self) -> float | None:
        """Our A1-A3 total must come in below the published A1-A5 figure."""
        return None if self.bpr_a1_a5_t is None else self.bpr_a1_a5_t * 1000.0


def _agreement_pct(a: float | None, b: float | None) -> float | None:
    if not a or not b:
        return None
    return 100.0 * abs(a - b) / b


def build_design_truth(design) -> DesignTruth:
    """Assemble every reference source for one design."""
    from ecarbon.bench.bpr import parse_bpr
    from ecarbon.bench.hot2000 import parse_hot2000
    from ecarbon.bench.ifc_quantities import model_quantities
    from ecarbon.bench.ifc_truth import geometry_coverage
    from ecarbon.intake import inventory, set_toolchain
    from ecarbon.models import Toolchain

    t = DesignTruth(key=design.key, region=design.region, typology=design.typology)
    t.has_list_of_drawings = design.list_of_drawings is not None

    # -- drawing set
    if design.drawings_pdf:
        try:
            sheets, _, _ = inventory(design.drawings_pdf)
            t.n_pages = len(sheets)
            t.n_readable_pages = sum(1 for s in sheets if s.readable)
            dom = set_toolchain(sheets)
            t.dominant_toolchain = dom.value
            if dom is Toolchain.DISTILLER_OUTLINED:
                t.flags.append("pdf_text_unreadable")
        except Exception as exc:  # noqa: BLE001
            t.flags.append(f"pdf_inventory_failed: {type(exc).__name__}")

    # -- IFC
    if design.ifc:
        try:
            cov = geometry_coverage(str(design.ifc))
            t.ifc_geometry_coverage = round(cov.fraction, 4)
            if not cov.usable:
                t.flags.append(f"ifc_geometry_degraded_{cov.fraction*100:.0f}pct")
            q = model_quantities(str(design.ifc))
            t.n_walls = len(q.by_type("IfcWall"))
            t.exterior_wall_gross_m2 = round(q.exterior_wall_area_m2(True), 1)
            t.exterior_wall_net_m2 = round(q.exterior_wall_area_m2(False), 1)
            t.foundation_wall_m2 = round(q.foundation_wall_area_m2(True), 1)
            t.slab_volume_m3 = round(q.volume_by_type("IfcSlab"), 2)
            t.footing_volume_m3 = round(q.volume_by_type("IfcFooting"), 2)
            t.n_inferred_build_ups = q.n_inferred
            mats = q.volume_by_material()
            t.material_volumes_m3 = {k: round(v, 2) for k, v in sorted(mats.items())}
            t.concrete_volume_m3 = round(
                sum(v for k, v in mats.items() if "concrete" in k.lower()), 2
            )
            t.area_by_tag_m2 = {k: round(v, 1) for k, v in sorted(q.area_by_tag("IfcWall").items())}
            if q.unassigned:
                t.flags.append(f"ifc_elements_without_geometry_{len(q.unassigned)}")
        except Exception as exc:  # noqa: BLE001
            t.flags.append(f"ifc_failed: {type(exc).__name__}")

    # -- HOT2000
    if design.h2k:
        try:
            h = parse_hot2000(str(design.h2k[0]))
            t.h2k_wall_m2 = round(h.wall_area_m2, 1)
            t.h2k_above_grade_wall_m2 = round(h.above_grade_wall_area_m2, 1)
            t.h2k_foundation_wall_m2 = round(h.foundation_wall_area_m2, 1)
            t.h2k_ceiling_m2 = round(h.ceiling_area_m2, 1)
            t.h2k_window_m2 = round(h.window_area_m2, 1)
        except Exception as exc:  # noqa: BLE001
            t.flags.append(f"hot2000_failed: {type(exc).__name__}")
    else:
        # The 7 BC designs ship Step Code checklists instead (RESEARCH S6).
        t.flags.append("no_hot2000")

    # -- Building Performance Report
    if design.bpr:
        bp = parse_bpr(str(design.bpr[0]))
        if bp.unreadable:
            t.flags.append("bpr_unreadable")
        else:
            t.bpr_gfa_m2 = bp.best_gfa_m2
            t.bpr_conditioned_m2 = bp.conditioned_m2
            t.bpr_total_ec_kg = bp.total_ec_kg
            t.bpr_ec_per_gfa = bp.ec_per_gfa
            t.bpr_a1_a5_t = bp.a1_a5_t
            t.bpr_element_pct = {k: round(v, 1) for k, v in bp.element_breakdown_normalised.items()}
            t.bpr_modules = bp.module_label

    # -- verdict
    # Compare like with like: the IFC's W* plus N* tags against HOT2000's wall
    # records, which lump the above-grade envelope with the foundation.
    ifc_walls = None
    if t.exterior_wall_gross_m2 is not None and t.foundation_wall_m2 is not None:
        ifc_walls = t.exterior_wall_gross_m2 + t.foundation_wall_m2
    t.wall_agreement_pct = _agreement_pct(ifc_walls, t.h2k_wall_m2)
    if t.wall_agreement_pct is not None:
        t.wall_agreement_pct = round(t.wall_agreement_pct, 2)

    # The sources do not always describe the same building. For rowhouses the
    # Building Performance Report and HOT2000 model ONE UNIT while the IFC
    # models the whole terrace: AB_Rowhouse_02's BPR gives 131 m2 for 1 unit,
    # and the Construction Cost Estimate gives 394 m2 for the 3-unit block --
    # 131 x 3 = 393. So the IFC/HOT2000 wall ratio comes out at 6-8x and the
    # design is unusable as a cross-validated benchmark until the multiplier is
    # established per design. Named explicitly rather than left as a bad score.
    if ifc_walls and t.h2k_wall_m2:
        ratio = ifc_walls / t.h2k_wall_m2
        if ratio >= 2.5:
            t.flags.append(f"source_extent_mismatch_ratio_{ratio:.1f}x")

    t.tier = _tier(t)
    return t


def _tier(t: DesignTruth) -> str:
    """Pick the binding constraint on using this design for quantity scoring.

    The gate is the IFC: complete geometry plus a readable PDF. HOT2000
    agreement is an annotation, NOT a gate.

    That was the opposite of the first design, and the data forced the change.
    Gating on agreement assumed a disagreement meant our parsing was wrong.
    Three genuine bugs were found and fixed that way -- the wall-role prefix
    rule, its flat-keyword replacement, and the rowhouse extent mismatch -- and
    the median disagreement still sat at 29% on exterior wall area alone. It
    does not shrink further because the two sources genuinely measure different
    things:

      * HOT2000 models the THERMAL envelope only, so walls bounding a garage,
        breezeway or unheated store are excluded while the IFC counts them.
      * Its wall height is the thermal height, not the structural height.
      * For rowhouses and stacked townhouses it models ONE UNIT while the IFC
        models the whole block (confirmed against the cost estimate, S18).

    Gating on agreement therefore threw away 25 designs with perfect
    architectural models because a second source with a different measurement
    basis disagreed with them. The IFC is the architect's own model with 100%
    buildable geometry; it is the right reference for a takeoff. HOT2000's
    agreement, where it exists, is extra confidence -- and where it does not,
    the disagreement is recorded rather than used to disqualify.

    This raises the scoreable set from 13 designs to 38.
    """
    if "pdf_text_unreadable" in t.flags:
        return Tier.ROBUSTNESS
    if t.ifc_geometry_coverage is None or t.ifc_geometry_coverage < 0.90:
        return Tier.GEOMETRY_ONLY
    agree = t.wall_agreement_pct
    if agree is not None and agree <= SILVER_AGREEMENT_PCT:
        return Tier.GOLD
    return Tier.SILVER


def build_manifest(designs) -> list[DesignTruth]:
    return [build_design_truth(d) for d in designs]


def save_manifest(rows: list[DesignTruth], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([asdict(r) for r in rows], indent=1, sort_keys=False) + "\n")
    return out


def load_manifest(path: str | Path) -> list[DesignTruth]:
    rows = json.loads(Path(path).read_text())
    return [DesignTruth(**r) for r in rows]


def summarise(rows: list[DesignTruth]) -> str:
    from collections import Counter

    tiers = Counter(r.tier for r in rows)
    lines = [f"{len(rows)} designs"]
    for tier in Tier:
        n = tiers.get(tier, 0)
        if n:
            lines.append(f"  {tier.value:14} {n:3}")
    scoreable = [r for r in rows if r.scoreable_for_quantities]
    lines.append(f"  -> scoreable for quantities: {len(scoreable)}")
    agree = sorted(r.wall_agreement_pct for r in rows if r.wall_agreement_pct is not None)
    if agree:
        lines.append(
            f"  wall agreement: median {agree[len(agree)//2]:.1f}%, worst {agree[-1]:.1f}%"
        )
    return "\n".join(lines)
