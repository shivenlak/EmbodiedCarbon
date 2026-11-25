"""A3: a datum printed with its label in one span (US, UK, AU, DE)."""

from __future__ import annotations

import pytest

from ecarbon.extract.levels import Level, StoreyHeights, inline_level


@pytest.mark.parametrize(
    ("text", "label", "elev"),
    [
        ('8\'-0" PLATE HEIGHT', "PLATE HEIGHT", 2.438),
        ('0\'-0" FINISHED FLOOR', "FINISHED FLOOR", 0.0),
        ('T.O. PLATE 9\'-1 1/8"', "T.O. PLATE", 2.772),
        ('FIN. FLR. EL. 100\'-0"', "FIN. FLR.", 30.48),
        ("FFL +3.000", "FFL", 3.0),
        ("FFL RL 12.450", "FFL", 12.45),
        ("OKFF ±0,00", "OKFF", 0.0),
    ],
)
def test_inline_datums(text, label, elev):
    assert inline_level(text) == (label, elev)


@pytest.mark.parametrize(
    "text", ['8\'-0" TOP OF TRELLIS', '2\'-9" TOP OF COLUMN', "3.000 m", "RL 12.450", "FFL"]
)
def test_not_a_floor_or_plate_datum(text):
    assert inline_level(text) is None


def test_a_relative_100_ft_datum_gives_the_same_storey():
    """`100'-0"` is the floor at ±0; only the difference to the plate is used."""
    levels = [inline_level('FIN. FLR. EL. 100\'-0"'), inline_level('TOP OF PLATE EL. 109\'-1"')]
    sh = StoreyHeights(levels=[Level(lb, e) for lb, e in levels])
    assert sh.storey_heights_m() == [2.769]


def test_wall_height_notes_give_storeys_and_floor_thickness():
    """Alberta builders label each storey's wall height beside its dimension."""
    import pymupdf

    from ecarbon.extract.levels import wall_heights_on_page

    doc = pymupdf.open()
    page = doc.new_page(width=1200, height=800)
    for y, label, fig in [
        (200, "SECOND FLOOR WALL HEIGHT", "8'-0\""),
        (300, "FLOOR THICKNESS", "1'-0\""),
        (400, "MAIN FLOOR WALL HEIGHT", "9'-0\""),
    ]:
        page.insert_text((120, y), fig, fontsize=7)
        page.insert_text((150, y), label, fontsize=7)
    page.insert_text((900, 400), "38'-0\"", fontsize=7)  # a dimension far away is not a height
    heights, thickness = wall_heights_on_page(page)
    assert heights == {1: 2.743, 2: 2.438}
    assert thickness == 0.305


def test_a_stated_top_storey_is_not_copied_from_below():
    sh = StoreyHeights(
        levels=[Level("STOREY 1 FLOOR", 0.0), Level("STOREY 2 FLOOR", 3.048)],
        floor_assembly_mm=305.0,
        top_storey_m=2.438,
    )
    assert sh.storey_heights_m() == [3.048, 2.438]
    assert sh.net_wall_height_m == 5.181  # one floor in the stack, not two
