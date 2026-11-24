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


# Framing notes and stud spacing (A3: nominal lumber, framing fraction).
from ecarbon.extract.assemblies import FRAMING_FRACTION, Layer, stud_note_assemblies_on_page  # noqa: E402


def test_a_framing_note_gives_the_nominal_stud_depth_and_spacing():
    page = legend_page(("NOTE", 'ALL EXTERIOR STUDS TO BE 2x6 @ 16" O.C.'))
    (wall,) = stud_note_assemblies_on_page(page, "S1")
    assert wall.tag == "W1" and wall.from_legend
    (studs,) = wall.layers
    assert studs.thickness_mm == 140.0 and studs.is_framing
    assert studs.framing_share == FRAMING_FRACTION  # 16" is 406 mm, the standard


def test_an_au_framing_note_reads_depth_first():
    page = legend_page(("NOTE", "EXTERIOR WALL STUDS SHALL BE 90x45 @ 600 CRS"))
    (wall,) = stud_note_assemblies_on_page(page)
    assert wall.layers[0].thickness_mm == 90.0
    assert wall.layers[0].framing_share < FRAMING_FRACTION


def test_nailing_and_stud_grade_notes_are_not_wall_specs():
    page = legend_page(
        ("NOTE", '2X STUDS @ 16" O.C. - SEE STRUCTURAL'),
        ("NOTE", "PROVIDE 2X6 TRIMMER & 2X6 KING STUD EACH END"),
        ("NOTE", '16d Com @ 16" o.c. FN OR 10d Box'),
    )
    assert stud_note_assemblies_on_page(page) == []


def test_stud_spacing_sets_the_framing_share():
    share = lambda m: Layer(0, m, 140.0).framing_share  # noqa: E731
    assert share("WOOD STUD FRAMING") == FRAMING_FRACTION
    assert share("WOOD STUD FRAMING @406mm O/C") == FRAMING_FRACTION
    assert share('WOOD STUD FRAMING @ 24" O.C.') == round(38 / 609.6 + 0.15 - 38 / 400, 4)
    assert share("WOOD STUD FRAMING @ 300 CRS") > FRAMING_FRACTION
