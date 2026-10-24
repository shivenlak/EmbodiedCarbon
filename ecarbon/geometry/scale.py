"""STEP 8 -- scale calibration: how many real millimetres one PDF point is.

Everything downstream is multiplied by this number, so an error here corrupts
every quantity by a constant factor and nothing else in the pipeline reveals
it. It therefore gets three independent sources and a reported spread, not a
single lookup.

Sources, strongest first:

  1. DIMENSION CHAINS (primary). Dimension text sits at the midpoint of the run
     it annotates, so in a chain of consecutive dimensions the page gap between
     two labels equals half of each value. Each adjacent pair yields an
     independent estimate; a floor plan gives 40+ of them. On AB_Fourplex_01
     A101 that is 42 estimates agreeing to +/-0.03%. Self-validating: the
     agreement IS the evidence.

  2. SCALE TEXT. `SCALE: 1/4" = 1'-0"` or `1:50` in the title block or under a
     viewport. One value, no internal check, and often blank or stale.

  3. /VP VIEWPORT MATRIX. Some exports embed a world-to-page transform with
     `/UNITS (mm)`. Exact in principle, present on only 23 of 53 sets, and its
     unit convention needs calibrating against a known dimension before it can
     be trusted -- so it corroborates, it does not lead.

A sheet is frequently MULTI-SCALE -- a plan at 1:50 beside details at 1:10 --
so candidates are clustered and the dominant cluster is returned with the
others reported. Measuring a wall on a detail with the plan's scale would be
wrong by 5x, silently.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from enum import StrEnum

import pymupdf

from ecarbon.intake.textrepair import repair

PT_TO_MM = 25.4 / 72.0
MM_PER_FOOT = 304.8
MM_PER_INCH = 25.4

# A dimension label is small text; titles and notes are larger.
MAX_DIM_FONT_PT = 14.0
# Chain membership: labels on one dimension line share a coordinate this closely.
CHAIN_TOL_PT = 3.5
# Two candidate scales belong to the same cluster within this relative spread.
CLUSTER_REL = 0.04
# Below this page gap, label placement jitter dominates.
MIN_GAP_PT = 5.0
# Plausible architectural scales, in mm of world per PDF point.
MIN_MM_PER_PT = 0.3  # ~1:1
MAX_MM_PER_PT = 900.0  # ~1:2500 (site plans)


# Architectural drawings are produced at conventional scales. A derived ratio
# that matches none of them is evidence the "chain" was not a dimension chain --
# a schedule's size column reads as one and yields a meaningless 1:418.
STANDARD_RATIOS = (
    # metric
    5, 10, 20, 25, 50, 75, 100, 125, 200, 250, 500, 1000, 1250, 2500,
    # imperial, as ratios: 3"=1', 1.5"=1', 1"=1', 3/4", 1/2", 3/8", 1/4", 3/16", 1/8", 1/16"
    4, 8, 12, 16, 24, 32, 48, 64, 96, 192,
)
# How far from a standard scale we still accept.
STANDARD_TOL_PCT = 4.0


def nearest_standard_ratio(ratio: float) -> tuple[float, float]:
    """Closest conventional scale and the relative error to it, in percent."""
    best = min(STANDARD_RATIOS, key=lambda r: abs(r - ratio) / r)
    return float(best), 100.0 * abs(best - ratio) / best


class ScaleSource(StrEnum):
    DIMENSION_CHAIN = "dimension_chain"
    SCALE_TEXT = "scale_text"
    VIEWPORT_MATRIX = "viewport_matrix"
    NONE = "none"


# --------------------------------------------------------------------------
# Dimension text parsing
# --------------------------------------------------------------------------

# 7000   915mm   (SKMB writes the unit, most regions do not)
_METRIC_RE = re.compile(r"^(\d{2,6})\s*(?:mm)?$", re.I)
_METRIC_M_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*m$", re.I)
# 23' - 0"   9'-10 1/8"   7' 10"   14'-3"   12'   3 7/8"   (and in [brackets])
_IMPERIAL_RE = re.compile(
    r"""^(?:
          (?P<ft>\d+)\s*'                          # feet, optionally with ...
          (?:\s*-?\s*
             (?P<in>\d+)?\s*
             (?:(?P<n>\d+)\s*/\s*(?P<d>\d+))?\s*
             "?
          )?
        | (?P<in2>\d+)?\s*(?:(?P<n2>\d+)\s*/\s*(?P<d2>\d+))?\s*"   # inches only
        )$""",
    re.X,
)
# Dual-unit in one label. Three separators are in use across the catalogue:
#   800 / 2'-7 1/2"      (AB, ON: slash)
#   915mm  [3'-0"]       (SKMB: brackets)
#   2000 (6'-6 3/4")     (parenthesised)
_DUAL_RE = re.compile(r"^(\d{2,6}\s*(?:mm)?)\s*(?:/|\[|\()\s*([^\]\)]+)[\]\)]?$", re.I)

# SCALE: 1/4" = 1'-0"   |   SCALE: 1:50   |   1/8"=1'0"
_SCALE_RATIO_RE = re.compile(r"1\s*:\s*(\d{1,4})")
_SCALE_IMPERIAL_RE = re.compile(
    r"(?:(\d+)\s*/\s*(\d+)|(\d+))\s*\"?\s*=\s*(\d+)\s*'\s*-?\s*(\d+)?\s*\"?"
)


def parse_metric(text: str) -> float | None:
    """A millimetre dimension, in mm. Accepts bare number, 'mm' suffix, or decimal 'm'."""
    t = text.strip()
    m = _METRIC_RE.match(t)
    if m:
        v = float(m.group(1))
        return v if 20.0 <= v <= 100_000.0 else None
    mm = _METRIC_M_RE.match(t)
    if mm:
        v = float(mm.group(1)) * 1000.0
        return v if 20.0 <= v <= 100_000.0 else None
    return None


def parse_imperial(text: str) -> float | None:
    """A feet-and-inches dimension, in mm. Tolerates [brackets]."""
    t = text.strip().strip("[]()").strip()
    m = _IMPERIAL_RE.match(t)
    if not m:
        return None
    g = m.groupdict()
    mm = float(g["ft"]) * MM_PER_FOOT if g["ft"] else 0.0
    inches = g["in"] or g["in2"]
    if inches:
        mm += float(inches) * MM_PER_INCH
    num, den = (g["n"] or g["n2"]), (g["d"] or g["d2"])
    if num and den and float(den):
        mm += float(num) / float(den) * MM_PER_INCH
    return mm if 20.0 <= mm <= 100_000.0 else None


def parse_dimension(text: str) -> tuple[float | None, str]:
    """Parse any dimension label. Returns (mm, which_unit_system)."""
    t = text.strip()

    # Multiline dual dimension blocks (stacked imperial / metric or metric / imperial)
    lines = [l.strip() for l in t.splitlines() if l.strip()]
    if len(lines) == 2:
        m1 = parse_metric(lines[0])
        i1 = parse_imperial(lines[1])
        if m1 and i1:
            return (m1, "dual") if abs(m1 - i1) / m1 < 0.03 else (None, "conflict")
        m2 = parse_metric(lines[1])
        i2 = parse_imperial(lines[0])
        if m2 and i2:
            return (m2, "dual") if abs(m2 - i2) / m2 < 0.03 else (None, "conflict")

    # Slash-separated dual dimension (metric / imperial OR imperial / metric)
    if "/" in t:
        parts = t.split("/", 1)
        p0, p1 = parts[0].strip(), parts[1].strip()
        m0 = parse_metric(p0)
        i1 = parse_imperial(p1)
        if m0 and i1:
            return (m0, "dual") if abs(m0 - i1) / m0 < 0.03 else (None, "conflict")
        i0 = parse_imperial(p0)
        m1 = parse_metric(p1)
        if i0 and m1:
            return (m1, "dual") if abs(i0 - m1) / m1 < 0.03 else (None, "conflict")

    dual = _DUAL_RE.match(t)
    if dual:
        metric = parse_metric(dual.group(1))
        imperial = parse_imperial(dual.group(2))
        if metric and imperial:
            # Both present in one label: prefer metric, but only if they agree.
            return (metric, "dual") if abs(metric - imperial) / metric < 0.02 else (None, "conflict")
        return (metric or imperial, "dual" if (metric or imperial) else "none")

    v = parse_metric(t)
    if v:
        return v, "metric"
    v = parse_imperial(t)
    if v:
        return v, "imperial"
    return None, "none"


def parse_scale_text(text: str) -> float | None:
    """`1:50` or `1/4" = 1'-0"` to mm of world per PDF point."""
    t = re.sub(r"\s+", " ", text.strip())
    m = _SCALE_RATIO_RE.search(t)
    if m:
        ratio = float(m.group(1))
        return ratio * PT_TO_MM if MIN_MM_PER_PT <= ratio * PT_TO_MM <= MAX_MM_PER_PT else None
    m = _SCALE_IMPERIAL_RE.search(t)
    if m:
        num, den, whole, ft, inch = m.groups()
        paper_in = float(whole) if whole else float(num) / float(den)
        world_in = float(ft) * 12.0 + (float(inch) if inch else 0.0)
        if paper_in <= 0:
            return None
        ratio = world_in / paper_in
        mm_per_pt = ratio * PT_TO_MM
        return mm_per_pt if MIN_MM_PER_PT <= mm_per_pt <= MAX_MM_PER_PT else None
    return None


# --------------------------------------------------------------------------
# Collecting dimension labels off a page
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DimLabel:
    x: float
    y: float
    value_mm: float
    text: str
    unit_system: str
    size: float


def find_dimension_labels(page: pymupdf.Page) -> list[DimLabel]:
    """Every parseable dimension label on the page, at its centre point."""
    out: list[DimLabel] = []
    try:
        blocks = page.get_text("dict")["blocks"]
    except Exception:
        return out
    for block in blocks:
        for line in block.get("lines", []):
            for s in line.get("spans", []):
                raw = s.get("text", "").strip()
                if not raw or s.get("size", 0) > MAX_DIM_FONT_PT:
                    continue
                text, _ = repair(raw)
                value, system = parse_dimension(text)
                if value is None:
                    continue
                bb = s["bbox"]
                out.append(
                    DimLabel(
                        x=(bb[0] + bb[2]) / 2.0,
                        y=(bb[1] + bb[3]) / 2.0,
                        value_mm=value,
                        text=text,
                        unit_system=system,
                        size=round(s.get("size", 0.0), 1),
                    )
                )
    return out


def _chains(labels: list[DimLabel], axis: str) -> list[list[DimLabel]]:
    """Group labels sharing a coordinate into dimension chains.

    A vertical chain shares x and varies in y; a horizontal chain the reverse.
    Grouping is on the shared coordinate, so it works regardless of whether the
    text itself is rotated.
    """
    shared = (lambda d: d.x) if axis == "vertical" else (lambda d: d.y)
    varying = (lambda d: d.y) if axis == "vertical" else (lambda d: d.x)
    groups: dict[int, list[DimLabel]] = {}
    for d in labels:
        groups.setdefault(round(shared(d) / CHAIN_TOL_PT), []).append(d)
    out = []
    for g in groups.values():
        if len(g) >= 3:
            out.append(sorted(g, key=varying))
    return out


def _candidates(labels: list[DimLabel]) -> list[float]:
    """One scale estimate per adjacent pair in every chain.

    A dimension label is centred on the run it annotates, so the page distance
    between two adjacent labels spans half of each -- hence the mean of the two
    values over the measured gap.
    """
    out: list[float] = []
    for axis in ("vertical", "horizontal"):
        varying = (lambda d: d.y) if axis == "vertical" else (lambda d: d.x)
        for chain in _chains(labels, axis):
            for a, b in zip(chain, chain[1:], strict=False):
                gap = abs(varying(b) - varying(a))
                if gap < MIN_GAP_PT:
                    continue
                mm_per_pt = ((a.value_mm + b.value_mm) / 2.0) / gap
                if MIN_MM_PER_PT <= mm_per_pt <= MAX_MM_PER_PT:
                    out.append(mm_per_pt)
    return out


def _robust_spread(values: list[float]) -> float:
    """p90 - p10. Resistant to the handful of labels whose placement is off."""
    if len(values) < 3:
        return max(values) - min(values) if values else 0.0
    v = sorted(values)
    lo = v[int(0.10 * (len(v) - 1))]
    hi = v[int(0.90 * (len(v) - 1))]
    return hi - lo


@dataclass(frozen=True)
class Chain:
    """A run of consecutive dimension labels along one dimension line."""

    axis: str
    total_mm: float
    n: int
    span_pt: float
    shared_coord: float

    @property
    def implied_mm_per_pt(self) -> float | None:
        """Scale from the chain as a whole, independent of per-pair estimates.

        The chain's labels span from the first midpoint to the last, which is
        the total minus half the first and half the last run.
        """
        return self.total_mm / self.span_pt if self.span_pt else None


def dimension_chains(page: pymupdf.Page) -> list[Chain]:
    """Every dimension chain on the page, longest total first.

    The longest chain across a floor plan is normally the building's overall
    run, which is what makes it comparable with an IFC extent.
    """
    labels = find_dimension_labels(page)
    out: list[Chain] = []
    for axis in ("vertical", "horizontal"):
        varying = (lambda d: d.y) if axis == "vertical" else (lambda d: d.x)
        shared = (lambda d: d.x) if axis == "vertical" else (lambda d: d.y)
        for chain in _chains(labels, axis):
            total = sum(d.value_mm for d in chain)
            span = abs(varying(chain[-1]) - varying(chain[0]))
            # Labels are centred on their runs, so the measured span covers the
            # total less half of the first and last.
            inner = total - (chain[0].value_mm + chain[-1].value_mm) / 2.0
            if span > MIN_GAP_PT and inner > 0:
                out.append(
                    Chain(
                        axis=axis,
                        total_mm=total,
                        n=len(chain),
                        span_pt=span / inner * total if inner else span,
                        shared_coord=shared(chain[0]),
                    )
                )
    return sorted(out, key=lambda c: -c.total_mm)


def overall_extent_mm(page: pymupdf.Page) -> tuple[float | None, float | None]:
    """Largest chain total in each axis -- the building's overall run.

    Compared against the IFC envelope extent, this validates the scale AND the
    dimension reading at once, without the pipeline ever touching the IFC.
    """
    chains = dimension_chains(page)
    v = max((c.total_mm for c in chains if c.axis == "vertical"), default=None)
    h = max((c.total_mm for c in chains if c.axis == "horizontal"), default=None)
    return h, v


def _cluster(values: list[float]) -> list[list[float]]:
    """Split candidates into scale clusters, largest first.

    A sheet often carries a plan and details at different scales; without this
    the median lands between them and is wrong for both.
    """
    if not values:
        return []
    vals = sorted(values)
    clusters: list[list[float]] = [[vals[0]]]
    for v in vals[1:]:
        ref = statistics.median(clusters[-1])
        if abs(v - ref) / ref <= CLUSTER_REL:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return sorted(clusters, key=len, reverse=True)


# --------------------------------------------------------------------------
# The estimate
# --------------------------------------------------------------------------


@dataclass
class ScaleEstimate:
    mm_per_pt: float | None
    source: ScaleSource
    n_samples: int = 0
    spread_pct: float | None = None
    secondary: list[float] = field(default_factory=list)
    corroborated_by: list[ScaleSource] = field(default_factory=list)
    disagreement_pct: float | None = None
    note: str = ""

    @property
    def ratio(self) -> float | None:
        """Drawing scale denominator: 50.0 means 1:50."""
        return None if self.mm_per_pt is None else self.mm_per_pt / PT_TO_MM

    @property
    def is_multi_scale(self) -> bool:
        return bool(self.secondary)

    @property
    def off_standard_pct(self) -> float | None:
        """Distance from the nearest conventional architectural scale."""
        r = self.ratio
        return None if r is None else nearest_standard_ratio(r)[1]

    @property
    def is_standard(self) -> bool:
        off = self.off_standard_pct
        return off is not None and off <= STANDARD_TOL_PCT

    @property
    def trustworthy(self) -> bool:
        """Tight agreement across many samples, or confirmed by a second source.

        A single-source estimate with no internal spread to check is explicitly
        not trustworthy; it is reported with a gap instead. A ratio matching no
        conventional scale is rejected outright, because that is the signature
        of a schedule column mistaken for a dimension chain.
        """
        if self.mm_per_pt is None or not self.is_standard:
            return False
        if self.source is ScaleSource.DIMENSION_CHAIN:
            return self.n_samples >= 4 and (self.spread_pct or 100.0) <= 1.0
        return bool(self.corroborated_by)

    def mm(self, points: float) -> float | None:
        return None if self.mm_per_pt is None else points * self.mm_per_pt

    def m2(self, points2: float) -> float | None:
        """Page area in square points to real square metres."""
        if self.mm_per_pt is None:
            return None
        return points2 * (self.mm_per_pt**2) / 1_000_000.0


def scale_from_text(page: pymupdf.Page) -> float | None:
    """Second source: a stated scale anywhere on the sheet."""
    try:
        blocks = page.get_text("dict")["blocks"]
    except Exception:
        return None
    found: list[float] = []
    for block in blocks:
        for line in block.get("lines", []):
            joined = " ".join(s.get("text", "") for s in line.get("spans", []))
            text, _ = repair(joined)
            v = parse_scale_text(text)
            if v:
                found.append(v)
    if not found:
        return None
    return statistics.median(found)


def scale_from_viewport(page: pymupdf.Page) -> float | None:
    """Third source: an embedded /VP world-to-page matrix, where present.

    The matrix is read but its unit convention is NOT assumed -- the value is
    returned for corroboration only, and `calibrate` never promotes it to the
    primary. Confirming the convention against a known dimension is a separate
    task; until then treating it as authoritative would be a guess wearing a
    precise-looking number.
    """
    try:
        content = page.read_contents()
    except Exception:
        return None
    best: float | None = None
    for raw in re.findall(rb"/VP\s*\[([^\]]*)\]", content):
        try:
            nums = [float(x) for x in raw.split()]
        except ValueError:
            continue
        if len(nums) < 16 or not nums[0]:
            continue
        candidate = abs(nums[0])
        if MIN_MM_PER_PT <= candidate <= MAX_MM_PER_PT:
            best = candidate if best is None else max(best, candidate)
    return best


def calibrate(page: pymupdf.Page) -> ScaleEstimate:
    """Resolve the scale for one page from all available sources."""
    labels = find_dimension_labels(page)
    cands = _candidates(labels)
    clusters = _cluster(cands)
    min_secondary = max(3, int(0.08 * len(cands)))

    stated = scale_from_text(page)
    viewport = scale_from_viewport(page)

    if clusters:
        primary = clusters[0]
        med = statistics.median(primary)
        # p10-p90 rather than min-max: a couple of mis-placed labels in a
        # 90-sample chain should not make a 0.05% agreement look like 5%.
        spread = 100.0 * _robust_spread(primary) / med if med else None
        est = ScaleEstimate(
            mm_per_pt=med,
            source=ScaleSource.DIMENSION_CHAIN,
            n_samples=len(primary),
            spread_pct=spread,
            # Only a substantial cluster is a real second scale on the sheet.
            # Stray labels always produce one- and two-sample clusters, and
            # reporting those as "this sheet has 4 scales" is noise.
            secondary=[
                round(statistics.median(c), 4) for c in clusters[1:5] if len(c) >= min_secondary
            ],
        )
        # Corroboration: a second source within 2% is confirmation, further
        # away is a reportable disagreement rather than something to average.
        for src, val in ((ScaleSource.SCALE_TEXT, stated), (ScaleSource.VIEWPORT_MATRIX, viewport)):
            if val is None:
                continue
            delta = 100.0 * abs(val - med) / med
            if delta <= 2.0:
                est.corroborated_by.append(src)
            elif est.disagreement_pct is None or delta > est.disagreement_pct:
                est.disagreement_pct = round(delta, 1)
                est.note = f"{src.value} implies {val:.3f} mm/pt, {delta:.0f}% from the measured scale"
        if est.is_multi_scale:
            est.note = (
                est.note + "; " if est.note else ""
            ) + f"sheet carries {1 + len(est.secondary)} scales"
        return est

    if stated is not None:
        return ScaleEstimate(
            mm_per_pt=stated,
            source=ScaleSource.SCALE_TEXT,
            n_samples=1,
            note="no dimension chains found; scale taken from stated text and unverified",
        )

    if viewport is not None:
        return ScaleEstimate(
            mm_per_pt=viewport,
            source=ScaleSource.VIEWPORT_MATRIX,
            n_samples=1,
            note="only a /VP matrix was available; unit convention unconfirmed",
        )

    return ScaleEstimate(
        mm_per_pt=None,
        source=ScaleSource.NONE,
        note=f"no scale evidence on this page ({len(labels)} dimension labels found)",
    )
