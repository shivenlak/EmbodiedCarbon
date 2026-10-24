"""Stage 1 ground truth: the `List of Drawings` PDF shipped in each package.

51 of 52 packages include one (ATL_Fourplex_03 does not). It is a clean
two-column table -- SHEET # | SHEET TITLE -- with the same layout in all seven
regions, so it gives us free labelled data for scoring sheet identification.

This is SCORING ONLY. ecarbon/intake/classify.py never reads it; see the note
at the top of that module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from ecarbon.intake.classify import SHEET_NO_RE, discipline_of, sheet_type_of
from ecarbon.models import Discipline, SheetType

# Sheet numbers appear at x~72-78 and titles at x~132-149 in every region, so a
# split a little past the widest sheet-number column separates the two cleanly.
COLUMN_SPLIT_X = 120.0

# "A006-A009", "A200-A201", "A003-A004", "S102-S104"
RANGE_RE = re.compile(r"^([A-Z]{1,2})(\d{2,4})\s*[-–]\s*([A-Z]{1,2})?(\d{2,4})$")


@dataclass(frozen=True)
class TruthSheet:
    sheet_no: str
    title: str
    discipline: Discipline
    sheet_type: SheetType


def _expand(token: str) -> list[str]:
    """'A006-A009' -> ['A006','A007','A008','A009'].

    Ranges are how the catalogue lists repeated detail sheets, so a set with
    'A006-A009 TYP. DETAILS' really contains four pages with that title.
    """
    tok = token.strip().upper().replace(" ", "")
    m = RANGE_RE.match(tok)
    if not m:
        return [token.strip()] if SHEET_NO_RE.match(tok) else []
    prefix, start, prefix2, end = m.groups()
    if prefix2 and prefix2 != prefix:
        return [f"{prefix}{start}", f"{prefix2}{end}"]
    width = len(start)
    try:
        lo, hi = int(start), int(end)
    except ValueError:
        return [tok]
    if hi < lo or hi - lo > 40:
        return [f"{prefix}{start}", f"{prefix}{end}"]
    return [f"{prefix}{str(n).zfill(width)}" for n in range(lo, hi + 1)]


def parse_list_of_drawings(path: str | Path) -> list[TruthSheet]:
    """Read one List of Drawings PDF into a flat list of expected sheets."""
    doc = pymupdf.open(path)
    rows: dict[tuple[int, float], list[tuple[float, str]]] = {}
    try:
        for pno in range(doc.page_count):
            for x0, y0, _x1, _y1, word, *_ in doc[pno].get_text("words"):
                # Bucket by y so a wrapped table row stays one row. 5pt is below
                # the ~16-24pt row pitch and above intra-row jitter.
                rows.setdefault((pno, round(y0 / 5.0) * 5.0), []).append((x0, word))
    finally:
        doc.close()

    out: list[TruthSheet] = []
    for (_pno, _y), cells in sorted(rows.items()):
        left = [w for x, w in sorted(cells) if x < COLUMN_SPLIT_X]
        right = [w for x, w in sorted(cells) if x >= COLUMN_SPLIT_X]
        if not left or not right:
            continue
        numbers = _expand("".join(left))
        if not numbers:
            continue
        title = re.sub(r"\s+", " ", " ".join(right)).strip()
        if not title or title.upper() in {"SHEET TITLE", "TITLE PAGE"} and len(numbers) == 0:
            continue
        for sheet_no in numbers:
            disc = discipline_of(sheet_no)
            out.append(
                TruthSheet(
                    sheet_no=sheet_no,
                    title=title,
                    discipline=disc,
                    sheet_type=sheet_type_of(title, disc),
                )
            )

    # The header row ("SHEET # | SHEET TITLE") never matches a sheet number, and
    # the "000 TITLE PAGE" row does, legitimately -- it is page 1 of the set.
    seen: set[str] = set()
    uniq: list[TruthSheet] = []
    for t in out:
        if t.sheet_no not in seen:
            seen.add(t.sheet_no)
            uniq.append(t)
    return uniq


def truth_for(design) -> list[TruthSheet]:
    """Ground truth for one Design, or [] if the package has no index sheet."""
    if not design.list_of_drawings:
        return []
    return parse_list_of_drawings(design.list_of_drawings)
