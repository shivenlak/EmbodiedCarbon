"""A3: US wall legends, a sentence per wall type instead of a tagged schedule."""

from __future__ import annotations

import pymupdf

from ecarbon.extract.assemblies import legend_assemblies_on_page


def legend_page(*rows: tuple[str, str]) -> pymupdf.Page:
    doc = pymupdf.open()
    page = doc.new_page(width=1200, height=800)
    for i, (label, text) in enumerate(rows):
        y = 100 + 20 * i
        page.insert_text((20, y), "UNRELATED NOTE IN ANOTHER COLUMN", fontsize=6)
        page.insert_text((900, y), label, fontsize=6)
        page.insert_text((950, y), text, fontsize=6)
    return page


def by_tag(page):
    return {a.tag: a for a in legend_assemblies_on_page(page, "A1-101")}


def test_a_legend_gives_the_stated_stud_depth_and_names_the_rest():
    got = by_tag(
        legend_page(
            ("EXTERIOR", '- 5 1/2" WOOD STUD W/ PLYWOOD SHEATHING AND FINISH, SEE'),
            ("INTERIOR", '- 3 1/2" WOOD STUD W/ ONE LAYER GYP. WALL BOARD EACH SIDE.'),
        )
    )
    wall, part = got["W1"], got["P1"]
    assert wall.from_legend and "untagged" in wall.name
    assert [(x.material, x.thickness_mm) for x in wall.layers] == [
        ("WOOD STUD FRAMING", 139.7),
        ("PLYWOOD SHEATHING", None),  # no thickness stated, so none is given
    ]
    assert wall.layers[0].is_framing
    assert [(x.material, x.thickness_mm) for x in part.layers] == [
        ("WOOD STUD FRAMING", 88.9),
        ("ONE LAYER GYPSUM WALL BOARD", None),
    ]


def test_the_first_line_of_each_kind_is_the_standard_wall():
    got = by_tag(
        legend_page(
            ("EXTERIOR", '- 5 1/2" WOOD STUD W/ PLYWOOD SHEATHING'),
            ("EXTERIOR", '- 1 HOUR FIRE RATED - 3 1/2" WOOD STUD W/ PLYWOOD'),
        )
    )
    assert got["W1"].layers[0].thickness_mm == 139.7


def test_a_fire_rating_before_the_depth_still_reads():
    got = by_tag(legend_page(("EXTERIOR", '- 1 HOUR FIRE RATED - 5 1/2" WOOD STUD W/ PLYWOOD')))
    assert got["W1"].layers[0].thickness_mm == 139.7


def test_a_note_mentioning_exterior_studs_is_not_a_legend():
    page = legend_page(("NOTE", "APPLIED OVER STUDS OR SHEATHING OF ALL EXTERIOR WALLS"))
    assert legend_assemblies_on_page(page) == []
