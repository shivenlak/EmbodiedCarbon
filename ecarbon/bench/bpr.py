"""STEP 9 -- the Building Performance Reports.

73 of these ship with the catalogue, one per design per climate zone. They are
CMHC's own published results, and they give us three things:

1. A carbon total and intensity to sanity-check Stage 3 against.
2. Gross AND conditioned floor area, so the intensity denominator is not a
   guess -- and it corroborates the Construction Cost Estimate's gross area
   from a second source (RESEARCH.md S16).
3. **A contribution analysis by building element** -- "Foundations 44%, Upper
   Floors 18%, Interiors 16%, External Walls 10%, Roofs 8%, Windows/Doors 4%,
   Stairs 1%". That is precisely the output criterion 3 asks us to produce, and
   CMHC published it for every design. It is the only element-level carbon
   reference we have.

### :warning: Module scope

The reports state their own scope on the page: **A1-A5, B4-B5, C2-C4**. The
total is therefore NOT comparable with our A1-A3 figure, and the challenge's
own rule forbids summing across different module sets. `BuildingPerformance`
carries `modules` explicitly so nothing downstream can forget.

What A1-A3 *can* be checked against: A1-A5 is an upper bound (A4 transport and
A5 construction are additive), so our A1-A3 total must come in below the
reported A1-A5 figure and be of a plausible proportion to it. The IStructE
guide puts A1-A3 at roughly 50% of A1-C4 (`reference/istructe_*`).

### Parsing

The page is a dashboard, so labels and values are laid out in separate columns
and reading order does not reliably pair them. Values are matched to labels by
POSITION -- nearest numeric span below, then to the right. Page 2 is an image
with no text layer, and holds only definitions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ecarbon.intake.textrepair import looks_broken

# The module scope every one of these reports declares.
REPORT_MODULES = ("A1", "A2", "A3", "A4", "A5", "B4", "B5", "C2", "C3", "C4")

_NUM_RE = re.compile(r"^-?[\d,]+(?:\.\d+)?$")
# "Foundations (44%)", "Windows/Doors (4%)", "Roof & Terraces (23%)"
_BREAKDOWN_RE = re.compile(r"([A-Za-z][A-Za-z/ &']{2,40}?)\s*\((\d{1,3})%\)")

# The element pie shares the page with an energy end-use pie, and the element
# labels vary by region exactly as the schedule names did in Step 7 -- BC
# writes "Roof & Terraces" and "Windows & Doors" where Alberta writes "Roofs
# and Terraces" and "Windows/Doors". An exact whitelist silently returned 3 of
# 5 elements on every BC report, so labels are matched by pattern and
# normalised to canonical keys.
_ENERGY_RE = re.compile(
    r"heating|cooling|ventilation|\bfans\b|lighting|plugload|appliance|equipment", re.I
)
ELEMENT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("foundations", r"foundation"),
    ("upper_floors", r"upper\s*floor"),
    ("roofs", r"roof"),
    ("external_walls", r"(external|exterior)\s*wall"),
    ("windows_doors", r"window.*door|door.*window"),
    ("stairs", r"stair|elevator"),
    ("interiors", r"interior"),
)

# Plausibility bounds. A dashboard has numeric spans everywhere -- chart axes,
# year labels, unrelated metrics -- so every extracted field is bounded. This
# is what catches a gross floor area of "6 m2".
BOUNDS: dict[str, tuple[float, float]] = {
    "gfa_m2": (20.0, 5000.0),
    "conditioned_m2": (20.0, 5000.0),
    "total_ec_kg": (1_000.0, 5_000_000.0),
    "ec_per_gfa": (50.0, 2_000.0),
    "biogenic_kg": (0.0, 2_000_000.0),
    "a1_a5_t": (1.0, 2_000.0),
    "b4_b5_t": (0.0, 2_000.0),
    "c2_c4_t": (0.0, 2_000.0),
    "cumulative_ec_t": (1.0, 5_000.0),
    "cumulative_total_t": (1.0, 50_000.0),
    "total_energy_mwh": (1.0, 5_000.0),
    "oc_per_annum_t": (0.0, 2_000.0),
}


def canonical_element(label: str) -> str | None:
    """Map a legend label to a canonical element key, or None if not an element."""
    if _ENERGY_RE.search(label):
        return None
    low = label.lower()
    for key, pattern in ELEMENT_PATTERNS:
        if re.search(pattern, low):
            return key
    return None
# "Edmonton, AB" / "Yukon, NWT & Nunavut"
_LOCATION_RE = re.compile(r"^([A-Z][A-Za-z.\- ]+,\s*[A-Z]{2,3}(?:\s*&\s*[A-Za-z]+)?)$")
_CZ_RE = re.compile(r"^([1-8][A-C]?)$")


@dataclass
class BuildingPerformance:
    source: str
    design: str | None = None
    location: str | None = None
    climate_zone: str | None = None

    gfa_m2: float | None = None
    conditioned_m2: float | None = None
    storeys: int | None = None
    units: int | None = None

    total_ec_kg: float | None = None
    ec_per_gfa: float | None = None
    biogenic_kg: float | None = None
    a1_a5_t: float | None = None
    b4_b5_t: float | None = None
    c2_c4_t: float | None = None
    cumulative_ec_t: float | None = None
    cumulative_total_t: float | None = None

    total_energy_mwh: float | None = None
    oc_per_annum_t: float | None = None

    hvac: str | None = None
    rsi: dict[str, float] = field(default_factory=dict)
    element_breakdown_pct: dict[str, float] = field(default_factory=dict)

    modules: tuple[str, ...] = REPORT_MODULES
    unreadable: bool = False

    @property
    def module_label(self) -> str:
        return "A1-A5, B4-B5, C2-C4"

    @property
    def intensity_basis(self) -> str:
        """CMHC divides by GROSS floor area, not conditioned."""
        return "gross"

    @property
    def breakdown_sum_pct(self) -> float:
        return sum(self.element_breakdown_pct.values())

    @property
    def element_breakdown_normalised(self) -> dict[str, float]:
        """Element shares rescaled to sum to 100%.

        Some reports' legend percentages do not sum to 100 -- AB_ADU_01 reaches
        182%, and every entry there is the pie-slice value times a constant
        1.82, so the shares are internally consistent but scaled against a
        different denominator. The ratios are what we compare against, so they
        are normalised here and `breakdown_sum_pct` keeps the raw total visible
        rather than hiding the discrepancy.
        """
        total = self.breakdown_sum_pct
        if not total:
            return {}
        return {k: 100.0 * v / total for k, v in self.element_breakdown_pct.items()}

    def a1_a3_upper_bound_kg(self) -> float | None:
        """A1-A5 in kg. Our A1-A3 total must fall below this."""
        return None if self.a1_a5_t is None else self.a1_a5_t * 1000.0

    @property
    def gfa_implied_m2(self) -> float | None:
        """Floor area implied by total / intensity.

        Both of those come from unambiguously labelled fields, so where the
        parsed area disagrees this is the more trustworthy figure.
        """
        if self.total_ec_kg and self.ec_per_gfa:
            return self.total_ec_kg / self.ec_per_gfa
        return None

    @property
    def best_gfa_m2(self) -> float | None:
        """The floor area to divide by, preferring a self-consistent value."""
        implied = self.gfa_implied_m2
        if self.gfa_m2 and implied and abs(self.gfa_m2 - implied) / implied <= 0.02:
            return self.gfa_m2
        return implied or self.gfa_m2

    def consistency(self) -> list[str]:
        """Internal checks on the parse -- a silently wrong number here would
        corrupt every Stage 3 sanity check."""
        problems: list[str] = []
        if self.unreadable:
            return ["report text is not decodable; no values extracted"]
        implied = self.gfa_implied_m2
        if implied and self.gfa_m2 and abs(self.gfa_m2 - implied) / implied > 0.02:
            problems.append(
                f"parsed GFA {self.gfa_m2:.0f} disagrees with total/intensity "
                f"({implied:.0f}); best_gfa_m2 uses the implied value"
            )
        parts = [self.a1_a5_t, self.b4_b5_t, self.c2_c4_t]
        if all(p is not None for p in parts) and self.cumulative_ec_t:
            total = sum(parts)  # type: ignore[arg-type]
            if abs(total - self.cumulative_ec_t) > max(2.0, 0.03 * self.cumulative_ec_t):
                problems.append(
                    f"A1-A5 + B4-B5 + C2-C4 = {total} != cumulative EC {self.cumulative_ec_t}"
                )
        if self.element_breakdown_pct and len(self.element_breakdown_pct) < 4:
            problems.append(
                f"only {len(self.element_breakdown_pct)} element shares found: "
                f"{sorted(self.element_breakdown_pct)}"
            )
        if self.gfa_m2 and self.conditioned_m2 and self.conditioned_m2 > self.gfa_m2 * 1.02:
            problems.append("conditioned area exceeds gross area")
        return problems


@dataclass
class _Span:
    text: str
    x: float
    y: float

    @property
    def number(self) -> float | None:
        if not _NUM_RE.match(self.text):
            return None
        try:
            return float(self.text.replace(",", ""))
        except ValueError:
            return None


def _spans(page) -> list[_Span]:
    out: list[_Span] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for s in line.get("spans", []):
                t = s["text"].strip()
                if t:
                    bb = s["bbox"]
                    out.append(_Span(t, (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2))
    return out


def _value_after(spans: list[_Span], label_pat: str, skip: int = 0) -> float | None:
    """The nth numeric span following a label in READING ORDER.

    Position was tried first and is wrong here: the carbon-over-time chart sits
    beside the metric column and its x-axis year labels (2025...2085) are
    numeric spans a short distance away, so a nearest-value search returns
    2085 for every module figure. Reading order pairs every labelled metric
    with its own value correctly on this template.
    """
    rx = re.compile(label_pat, re.I)
    for i, s in enumerate(spans):
        if not rx.search(s.text):
            continue
        seen = 0
        for nxt in spans[i + 1 : i + 8]:
            v = nxt.number
            if v is None:
                continue
            if seen == skip:
                return v
            seen += 1
    return None


def _value_beside(spans: list[_Span], label_pat: str, max_dy: float = 6.0) -> float | None:
    """The nearest numeric span to the RIGHT of a label on the same line."""
    rx = re.compile(label_pat, re.I)
    best: tuple[float, float] | None = None
    for lab in (s for s in spans if rx.search(s.text)):
        for s in spans:
            v = s.number
            if v is None or abs(s.y - lab.y) > max_dy or s.x <= lab.x:
                continue
            d = s.x - lab.x
            if best is None or d < best[0]:
                best = (d, v)
    return None if best is None else best[1]


def _value_near(spans: list[_Span], label_pat: str, max_dist: float = 70.0) -> float | None:
    """The numeric span closest to a label, preferring below then right.

    Used only for the floor-area pair, whose column headers appear AFTER their
    values in reading order. Kept tight to stay clear of the chart.
    """
    rx = re.compile(label_pat, re.I)
    labels = [s for s in spans if rx.search(s.text)]
    best: tuple[float, float] | None = None
    for lab in labels:
        for s in spans:
            v = s.number
            if v is None or s is lab:
                continue
            dx, dy = s.x - lab.x, s.y - lab.y
            dist = (dx * dx + dy * dy) ** 0.5
            if dist > max_dist:
                continue
            score = dist + abs(dx) * 2.0
            if best is None or score < best[0]:
                best = (score, v)
    return None if best is None else best[1]


@lru_cache(maxsize=128)
def parse_bpr(path: str | Path) -> BuildingPerformance:
    import pymupdf

    doc = pymupdf.open(str(path))
    try:
        spans = _spans(doc[0])
        flat = re.sub(r"\s+", " ", doc[0].get_text("text"))
    finally:
        doc.close()

    bp = BuildingPerformance(source=str(path))
    # NOR_ADU_Municipal_Garage's report embeds fonts with no ToUnicode map and
    # a custom glyph ORDERING (not a constant offset, so textrepair cannot
    # shift it), so its text arrives as mojibake. Say so rather than return an
    # empty record that reads like a successful parse of a blank page.
    if looks_broken(re.sub(r"\s+", " ", flat)[:400]):
        bp.unreadable = True
        bp.design = Path(path).stem.replace("Building Performance Report_", "") or None
        return bp

    name = Path(path).stem
    bp.design = name.replace("Building Performance Report_", "") or None

    for s in spans:
        if bp.location is None and _LOCATION_RE.match(s.text):
            bp.location = s.text
        elif bp.climate_zone is None and _CZ_RE.match(s.text) and len(s.text) == 2:
            bp.climate_zone = s.text

    def put(field: str, value: float | None) -> None:
        """Assign only if the value is plausible for that field."""
        if value is None:
            return
        lo, hi = BOUNDS.get(field, (float("-inf"), float("inf")))
        if lo <= value <= hi:
            setattr(bp, field, value)

    put("total_ec_kg", _value_after(spans, r"Total EC Emissions"))
    bp.ec_per_gfa = _value_after(spans, r"EC\s*/\s*GFA")
    put("biogenic_kg", _value_after(spans, r"Biogenic Carbon"))
    bp.a1_a5_t = _value_after(spans, r"A1\s*.?\s*A5 EC Emissions")
    bp.b4_b5_t = _value_after(spans, r"B4\s*.?\s*B5 EC Emissions")
    bp.c2_c4_t = _value_after(spans, r"C2\s*.?\s*C4 EC Emissions")
    put("cumulative_ec_t", _value_after(spans, r"Cumulative EC Emissions"))
    put("cumulative_total_t", _value_after(spans, r"Cumulative Carbon Emissions"))
    put("total_energy_mwh", _value_after(spans, r"Total Energy"))
    put("oc_per_annum_t", _value_after(spans, r"OC Emissions per Annum"))
    # Layout differs between regions: Alberta puts these values above their
    # column headers, Atlantic puts them to the right on the same line. Both
    # are tried, and BOUNDS rejects the unrelated small numbers nearby.
    put("gfa_m2", _value_beside(spans, r"^Gross \(m") or _value_near(spans, r"^Gross \(m"))
    put("conditioned_m2", _value_beside(spans, r"^Conditioned \(m") or _value_near(spans, r"^Conditioned \(m"))

    # "2 Storey, 4 Unit"
    m = re.search(r"(\d+)\s*Storey.{0,4}?(\d+)\s*Unit", flat, re.I)
    if m:
        bp.storeys, bp.units = int(m.group(1)), int(m.group(2))

    for s_ in spans:
        if re.match(r"^(Natural Gas|Electric|Air Source|Ground Source|Combi)", s_.text, re.I):
            bp.hvac = s_.text.strip()
            break

    # Nominal thermal performance, laid out as label then RSI then imperial.
    for key in ("Roof", "Floor", "Wall", "Door", "Window"):
        v = _value_after(spans, rf"^{key}$")
        if v is not None and 0.0 < v < 100.0:
            bp.rsi[key] = v

    for label, pct in _BREAKDOWN_RE.findall(flat):
        key = canonical_element(label.strip())
        if key:
            bp.element_breakdown_pct[key] = float(pct)

    return bp


def parse_all(designs) -> dict[str, BuildingPerformance]:
    """Every report across a set of Designs, keyed by report filename stem."""
    out: dict[str, BuildingPerformance] = {}
    for d in designs:
        for p in d.bpr:
            bp = parse_bpr(str(p))
            out[Path(p).stem] = bp
    return out
