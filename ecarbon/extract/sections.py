"""Extraction of building section datums, storey heights, and vertical dimensions.

Parses sheets classified as SheetType.SECTION (A300, A301, S301, etc.) for:
  - GROUND FLOOR / FINISH GRADE (0.000 m)
  - T/O F/F SECOND (Top of Finished Floor Second)
  - T/O F/F THIRD (Top of Finished Floor Third)
  - U/S ROOF FRAMING / ROOF MIDPOINT / TOP OF ROOF
  - T/O FOOTING / B/O FOOTING

Verifies dual-unit agreement (metric vs imperial) to establish confidence:
  - If metric (e.g. 3.000 m) and imperial (e.g. 9'-10 1/8") agree within 1%,
    confidence is 'measured' and agreement is recorded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from ecarbon.geometry.scale import parse_dimension, parse_imperial


@dataclass
class SectionDatum:
    name: str  # e.g. "T/O F/F SECOND", "TOP OF ROOF", "GROUND FLOOR"
    elevation_m: float  # elevation above ground in metres
    metric_str: str = ""
    imperial_str: str = ""
    dual_agreement_pct: float | None = None
    page: int = 0
    sheet_no: str = ""
    bbox: tuple[float, float, float, float] | None = None


@dataclass
class StoreyHeightInfo:
    """Vertical extents of the building."""

    storeys: int  # count of above-grade storeys (e.g. 2, 3)
    ground_to_second_m: float = 3.0
    second_to_third_m: float | None = None
    wall_plate_height_m: float = 6.0  # top of highest wall plate / ceiling framing
    roof_peak_height_m: float = 9.0  # ridge / top of roof
    foundation_wall_height_m: float = 1.2  # below-grade grade-to-footing height
    datums: list[SectionDatum] = field(default_factory=list)
    confidence: str = "inferred"  # measured if dual agreement verified
    dual_spread_pct: float | None = None
    page: int = 0
    sheet_no: str = ""


_DATUM_PATTERNS = [
    (re.compile(r"GROUND\s+FLOOR|FINISH\s+GRADE|ASSUMED\s+GRADE", re.I), "GROUND_FLOOR", 0.0),
    (re.compile(r"T/O\s+F/F\s+SECOND|SECOND\s+FLOOR|2ND\s+FLOOR", re.I), "SECOND_FLOOR", 3.0),
    (re.compile(r"T/O\s+F/F\s+THIRD|THIRD\s+FLOOR|3RD\s+FLOOR", re.I), "THIRD_FLOOR", 6.0),
    (re.compile(r"U/S\s+ROOF\s+FRAMING|T/O\s+WALL\s+PLATE|CEILING", re.I), "WALL_PLATE", 6.0),
    (re.compile(r"ROOF\s+MIDPOINT", re.I), "ROOF_MIDPOINT", 9.0),
    (re.compile(r"TOP\s+OF\s+ROOF|T/O\s+ROOF|ROOF\s+RIDGE", re.I), "ROOF_TOP", 9.0),
    (re.compile(r"T/O\s+FOOTING|B/O\s+FOOTING", re.I), "FOOTING", -1.2),
]

_METRIC_RE = re.compile(r"(\d+(?:\.\d+)?)\s*m\b", re.I)
_IMPERIAL_RE = re.compile(r"(\d+)\'\s*-\s*(\d+(?:\s+\d+/\d+|\.\d+)?)\"|\b(\d+)\'", re.I)


def parse_section_datums(doc: pymupdf.Document, section_page_indices: list[int] | None = None) -> StoreyHeightInfo:
    """Parse section sheets in the document to derive storey heights and roof elevation."""
    if section_page_indices is None:
        section_page_indices = []
        for i, page in enumerate(doc):
            txt = page.get_text()
            if "SECTION" in txt.upper() and any(k in txt.upper() for k in ("T/O", "U/S", "TOP OF", "F/F", "ROOF")):
                section_page_indices.append(i)

    if not section_page_indices:
        # Fallback default residential 2-storey heights
        return StoreyHeightInfo(
            storeys=2,
            ground_to_second_m=3.0,
            wall_plate_height_m=6.0,
            roof_peak_height_m=8.5,
            foundation_wall_height_m=1.2,
            confidence="assumed",
        )

    datums: list[SectionDatum] = []
    best_sheet_no = "A300"
    best_page = section_page_indices[0]

    for p_idx in section_page_indices:
        page = doc[p_idx]
        blocks = page.get_text("blocks")
        for b in blocks:
            text = b[4].strip()
            for pat, datum_type, default_val in _DATUM_PATTERNS:
                if pat.search(text):
                    m_val = None
                    m_str = ""
                    m_match = _METRIC_RE.search(text)
                    if m_match:
                        try:
                            m_val = float(m_match.group(1))
                            m_str = m_match.group(0)
                        except ValueError:
                            pass

                    imp_val_mm = None
                    imp_str = ""
                    imp_match = _IMPERIAL_RE.search(text)
                    if imp_match:
                        imp_str = imp_match.group(0)
                        imp_val_mm = parse_imperial(imp_str)

                    # Compute agreement if both present
                    agree_pct = None
                    if m_val is not None and imp_val_mm is not None and m_val > 0:
                        m_in_mm = m_val * 1000.0
                        agree_pct = abs(m_in_mm - imp_val_mm) / m_in_mm * 100.0

                    elev = m_val if m_val is not None else default_val
                    datums.append(
                        SectionDatum(
                            name=datum_type,
                            elevation_m=elev,
                            metric_str=m_str,
                            imperial_str=imp_str,
                            dual_agreement_pct=agree_pct,
                            page=p_idx,
                            sheet_no=best_sheet_no,
                            bbox=(b[0], b[1], b[2], b[3]),
                        )
                    )
                    break

    # Consolidate datums by datum type
    elevations: dict[str, list[float]] = {}
    agreements: list[float] = []
    for d in datums:
        elevations.setdefault(d.name, []).append(d.elevation_m)
        if d.dual_agreement_pct is not None:
            agreements.append(d.dual_agreement_pct)

    has_third = "THIRD_FLOOR" in elevations and max(elevations["THIRD_FLOOR"]) > 4.5
    storeys = 3 if has_third else 2

    ground_to_second = 3.0
    if "SECOND_FLOOR" in elevations:
        sec = [e for e in elevations["SECOND_FLOOR"] if e > 0.5]
        if sec:
            ground_to_second = round(sum(sec) / len(sec), 3)

    second_to_third = None
    if has_third:
        third = [e for e in elevations["THIRD_FLOOR"] if e > 4.5]
        if third:
            third_elev = sum(third) / len(third)
            second_to_third = round(third_elev - ground_to_second, 3)

    # Wall plate / ceiling height
    wall_plate = ground_to_second * storeys
    if "WALL_PLATE" in elevations:
        wp = [e for e in elevations["WALL_PLATE"] if e > ground_to_second]
        if wp:
            wall_plate = round(sum(wp) / len(wp), 3)
    elif has_third and second_to_third:
        wall_plate = ground_to_second + second_to_third + 3.0

    # Roof peak
    roof_peak = wall_plate + 2.5
    if "ROOF_TOP" in elevations:
        rt = [e for e in elevations["ROOF_TOP"] if e > wall_plate]
        if rt:
            roof_peak = round(sum(rt) / len(rt), 3)
    elif "ROOF_MIDPOINT" in elevations:
        rm = [e for e in elevations["ROOF_MIDPOINT"] if e > wall_plate]
        if rm:
            roof_peak = round(sum(rm) / len(rm) * 1.15, 3)

    # Footing / foundation wall height
    fnd_height = 1.2
    if "FOOTING" in elevations:
        ftg = [abs(e) for e in elevations["FOOTING"] if abs(e) > 0.3]
        if ftg:
            fnd_height = round(sum(ftg) / len(ftg), 3)

    avg_agreement = sum(agreements) / len(agreements) if agreements else None
    confidence = "measured" if (avg_agreement is not None and avg_agreement < 1.0) else "inferred"

    return StoreyHeightInfo(
        storeys=storeys,
        ground_to_second_m=ground_to_second,
        second_to_third_m=second_to_third,
        wall_plate_height_m=wall_plate,
        roof_peak_height_m=roof_peak,
        foundation_wall_height_m=fnd_height,
        datums=datums,
        confidence=confidence,
        dual_spread_pct=avg_agreement,
        page=best_page,
        sheet_no=best_sheet_no,
    )
