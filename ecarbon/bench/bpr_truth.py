"""Building Performance Report (BPR) ground truth parser.

Each CMHC technical package ships an Energy and Carbon folder containing a
Building Performance Report PDF published by Ha/f Climate Design.

These reports publish whole-life carbon and embodied carbon results calculated
under standard Canadian residential baseline assumptions (A1-A5, B4-B5, C2-C4).

As established in RESEARCH.md §6 and docs/PLAN.md Step 9, these numbers provide:
  - An empirical upper bound on whole-building embodied carbon
  - Realistic carbon intensity ranges (141 to 731 kgCO2e/m2 across the catalogue)
  - Gross and conditioned floor areas (GFA)
  - Module split targets (A1-A5 vs B4-B5 vs C2-C4)
  - A benchmark for Stage 3 validation and demo day module reconciliation
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class BPRTruth:
    file_path: Path
    location: str | None
    climate_zone: str | None
    gross_floor_area_m2: float | None
    conditioned_floor_area_m2: float | None
    storeys: int | None
    units: int | None

    # Carbon metrics
    total_ec_kg_co2e: float | None
    ec_intensity_kg_co2e_per_m2: float | None
    biogenic_carbon_kg_co2e: float | None

    # Module splits (in metric tonnes CO2e as published)
    a1_a5_ec_t_co2e: float | None
    b4_b5_ec_t_co2e: float | None
    c2_c4_ec_t_co2e: float | None

    # Assembly breakdown percentages if present
    breakdown_pct: dict[str, float] = field(default_factory=dict)


def _parse_num(s: str) -> float | None:
    cleaned = s.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_bpr(pdf_path: str | Path) -> BPRTruth:
    """Extract embodied carbon metrics and building specs from a BPR PDF."""
    import pymupdf

    path = Path(pdf_path)
    doc = pymupdf.open(str(path))
    if len(doc) == 0:
        raise ValueError(f"Empty PDF: {path}")

    # Extract text from page 0 (all relevant metrics are on page 1)
    text = doc[0].get_text()

    # Normalise whitespace and special unicode characters (like , ,  used for parentheses/hyphens)
    clean_text = (
        text.replace("\ue081", "(")
        .replace("\ue082", ")")
        .replace("\ue088", "-")
        .replace("–", "-")
        .replace("—", "-")
    )

    # 1. Total EC Emissions (kgCO2e)
    total_ec = None
    m_ec = re.search(r"Total EC Emissions [^\n]*\n([\d,]+)", clean_text, re.I)
    if m_ec:
        total_ec = _parse_num(m_ec.group(1))

    # 2. EC / GFA (kgCO2e/m2)
    ec_gfa = None
    m_gfa_i = re.search(r"EC/\s*GFA [^\n]*\n([\d,]+)", clean_text, re.I)
    if m_gfa_i:
        ec_gfa = _parse_num(m_gfa_i.group(1))

    # 3. Biogenic Carbon (kgCO2e)
    biogenic = None
    m_bio = re.search(r"Biogenic Carbon [^\n]*\n([\d,]+)", clean_text, re.I)
    if m_bio:
        biogenic = _parse_num(m_bio.group(1))

    # 4. A1-A5, B4-B5, C2-C4 module EC emissions (tCO2e)
    a1_a5 = None
    m_a1 = re.search(r"A1\s*-\s*A5\s*EC\s*Emissions[^\n]*\n([\d,]+)", clean_text, re.I)
    if m_a1:
        a1_a5 = _parse_num(m_a1.group(1))

    b4_b5 = None
    m_b4 = re.search(r"B4\s*-\s*B5\s*EC\s*Emissions[^\n]*\n([\d,]+)", clean_text, re.I)
    if m_b4:
        b4_b5 = _parse_num(m_b4.group(1))

    c2_c4 = None
    m_c2 = re.search(r"C2\s*-\s*C4\s*EC\s*Emissions[^\n]*\n([\d,]+)", clean_text, re.I)
    if m_c2:
        c2_c4 = _parse_num(m_c2.group(1))

    # 5. Location and Climate Zone
    location = None
    cz = None
    m_loc = re.search(r"([A-Z][a-zA-Z\.\- ]{1,30},\s*[A-Z]{2})\n([1-8][A-C]?)", clean_text)
    if m_loc:
        location = m_loc.group(1).strip()
        cz = m_loc.group(2).strip()
    else:
        m_cz = re.search(r"\b([1-8][A-C]?)\b", clean_text)
        if m_cz:
            cz = m_cz.group(1)

    # 6. Storeys and Units
    storeys = None
    units = None
    m_su = re.search(r"(\d+)\s*Storey[s]?,\s*(\d+)\s*Unit", clean_text, re.I)
    if m_su:
        storeys = int(m_su.group(1))
        units = int(m_su.group(2))

    # 7. Floor Area: Gross and Conditioned
    gfa = None
    cfa = None
    # Usually in the block:
    # Edmonton, AB \n 7A \n 492 \n 404 \n 3 Storey, 6 Unit
    # Or near Gross (m2) / Conditioned (m2)
    m_area_block = re.search(
        rf"{re.escape(cz)}\n(\d+)\n(\d+)\n(?:\d+\s*Storey)", clean_text
    ) if cz else None
    if m_area_block:
        gfa = _parse_num(m_area_block.group(1))
        cfa = _parse_num(m_area_block.group(2))
    else:
        m_g = re.search(r"Gross\s*\(m2\)\s*\n?(\d+)", clean_text, re.I)
        if m_g:
            gfa = _parse_num(m_g.group(1))
        m_c = re.search(r"Conditioned\s*\(m2\)\s*\n?(\d+)", clean_text, re.I)
        if m_c:
            cfa = _parse_num(m_c.group(1))

    # 8. Assembly contributions breakdown
    breakdown: dict[str, float] = {}
    for line in clean_text.split("\n"):
        m_cat = re.search(r"([A-Za-z\s/]+)\s*\((\d+)%\)", line)
        if m_cat:
            cat_name = m_cat.group(1).strip()
            pct_val = float(m_cat.group(2))
            breakdown[cat_name] = pct_val

    return BPRTruth(
        file_path=path,
        location=location,
        climate_zone=cz,
        gross_floor_area_m2=gfa,
        conditioned_floor_area_m2=cfa,
        storeys=storeys,
        units=units,
        total_ec_kg_co2e=total_ec,
        ec_intensity_kg_co2e_per_m2=ec_gfa,
        biogenic_carbon_kg_co2e=biogenic,
        a1_a5_ec_t_co2e=a1_a5,
        b4_b5_ec_t_co2e=b4_b5,
        c2_c4_ec_t_co2e=c2_c4,
        breakdown_pct=breakdown,
    )
