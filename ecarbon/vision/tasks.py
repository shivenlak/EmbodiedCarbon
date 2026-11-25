"""What vision is asked, one schema and one prompt per task.

Every answer carries `quote` (the text exactly as printed) and `box` (where,
in pixels of the image sent), so `validate` can check it against the page's
own text. The model is never asked to measure or convert: numbers are parsed
out of the quote by the same parsers the rules use.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

# Bump when a prompt or schema changes; it is part of the cache key. A task
# whose prompt changed alone gets its own entry, so the other tasks' saved
# answers (the demo's, shipped in the image) stay valid.
PROMPT_VERSION = "2"
TASK_VERSIONS = {"footprint": "3"}  # 3: the porch rule


class Task(StrEnum):
    SHEET = "sheet"
    SCALE = "scale"
    FOOTPRINT = "footprint"
    LEVELS = "levels"


class Quoted(BaseModel):
    quote: str = Field(description="The text exactly as printed on the sheet.")
    box: list[float] = Field(description="Pixel box [x0, y0, x1, y1] of that text in the image.")


class SheetAnswer(BaseModel):
    found: bool
    sheet_no: Quoted | None = None
    title: Quoted | None = None


class ScaleAnswer(BaseModel):
    found: bool
    scale: Quoted | None = None


class FootprintAnswer(BaseModel):
    found: bool
    width: Quoted | None = None
    depth: Quoted | None = None


class Datum(BaseModel):
    label: Quoted
    elevation: Quoted


class LevelsAnswer(BaseModel):
    found: bool
    datums: list[Datum] = []


_NOT_THERE = (
    "If it is not printed on this sheet, answer found: false. That is the right "
    "answer whenever it is not there; never estimate, measure or convert. "
    "Every quote must be copied character for character from the sheet, and "
    "box is the pixel rectangle around that text in this image."
)

PROMPTS: dict[Task, str] = {
    Task.SHEET: (
        "This is one sheet of an architectural drawing set. Read the sheet number "
        "(e.g. A101) and the sheet title from the title block. " + _NOT_THERE
    ),
    Task.SCALE: (
        "This is one sheet of an architectural drawing set. Find the drawing scale "
        "note for the main floor plan on it, e.g. '1:50' or '1/4\" = 1'-0\"'. " + _NOT_THERE
    ),
    Task.FOOTPRINT: (
        "This is a floor plan. Find the two OVERALL exterior dimension strings: the "
        "longest dimension running across the whole building in each direction "
        "(width and depth), not a room or partial run. Measure the enclosed "
        "building: where an outer string also spans an open porch, deck or patio, "
        "take the string that stops at the exterior wall. Quote each dimension "
        "string as printed. " + _NOT_THERE
    ),
    Task.LEVELS: (
        "This is a building section or elevation. List every level datum: the label "
        "(e.g. 'MAIN FLOOR', 'T/O PLATE', 'SECOND FLOOR') and the elevation printed "
        "with it (e.g. '3.000 m' or 10'-1 1/2\"), each quoted separately as printed. " + _NOT_THERE
    ),
}

SCHEMAS: dict[Task, type[BaseModel]] = {
    Task.SHEET: SheetAnswer,
    Task.SCALE: ScaleAnswer,
    Task.FOOTPRINT: FootprintAnswer,
    Task.LEVELS: LevelsAnswer,
}
