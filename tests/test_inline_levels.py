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
