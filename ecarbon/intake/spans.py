"""Text spans in reading order, with page rotation undone.

Some sheets are drawn a quarter turn from upright -- Ontario's assemblies
schedules and its building sections both are, with 640 of 644 spans on
ON_Fourplex_01's A001 advancing along (0, -1). Everything downstream of this
reasons about rows and columns: a schedule pairs a thickness with the material
beside it, and a level ladder pairs a datum label with the elevation printed
below it. On a rotated sheet "below" is sideways, so both fail while the text
itself is perfectly readable.

The rotation is therefore undone once, here, rather than special-cased in each
reader. Callers get (row, column, text) in reading order whatever the sheet's
orientation.
"""

from __future__ import annotations

from collections.abc import Callable

import pymupdf

from ecarbon.intake.textrepair import repair

# Direction vectors PyMuPDF reports for a line of text, and the transform that
# puts each back upright. (1, 0) is already upright and needs nothing.
_UPRIGHT = (1.0, 0.0)


def read_spans(
    page: pymupdf.Page, extra_repair: Callable[[str], str] | None = None
) -> list[tuple[float, float, str]]:
    """(row, column, text) for every text span on a page, sorted.

    `extra_repair` is applied after the global text repair, for callers that
    can validate a recovery the global guards decline -- the assemblies reader
    uses it to accept a glyph-ID shift that yields a real thickness or tag.
    """
    rows: list[tuple[float, float, str]] = []
    turns: dict[tuple[float, float], int] = {}

    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            direction = line.get("dir", _UPRIGHT)
            key = (round(direction[0], 1), round(direction[1], 1))
            spans = [s for s in line.get("spans", []) if s["text"].strip()]
            turns[key] = turns.get(key, 0) + len(spans)
            for s in spans:
                text = repair(s["text"].strip())[0]
                if extra_repair is not None:
                    text = extra_repair(text)
                rows.append((s["bbox"][1], s["bbox"][0], text))

    if not rows:
        return []

    # The page's own reading direction, by weight of text rather than by one
    # stray rotated label.
    dominant = max(turns, key=lambda k: turns[k])
    if dominant == (0.0, -1.0):
        # Text advances up the page, so a line of it runs along y: the logical
        # column is -y and the logical row is x.
        rows = [(x, -y, t) for y, x, t in rows]
    elif dominant == (0.0, 1.0):
        rows = [(-x, y, t) for y, x, t in rows]
    elif dominant == (-1.0, 0.0):
        rows = [(-y, -x, t) for y, x, t in rows]
    return sorted(rows)
