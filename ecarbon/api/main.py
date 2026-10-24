"""FastAPI surface.

Serves the fixture until the real pipeline lands, so the UI can be built in
parallel. Every endpoint shape here is final; only the data behind it changes.

    uvicorn ecarbon.api.main:app --reload
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ecarbon.fixtures import example_carbon, example_takeoff
from ecarbon.models import CarbonResult, Gap, SheetInfo, TakeoffResult

app = FastAPI(
    title="ecarbon",
    version="0.1.0",
    description="Vector PDF plan set in; traceable bill of quantities and A1-A3 "
    "whole-building carbon out.",
)

# Vite dev server.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass
class Project:
    id: str
    takeoff: TakeoffResult
    carbon: CarbonResult = field(init=False)

    def __post_init__(self) -> None:
        self.recompute()

    def recompute(self) -> None:
        # Swapped for the real carbon engine in Step 12. The contract is that
        # carbon is derived from the takeoff and never mutates it.
        self.carbon = example_carbon(self.takeoff)


_PROJECTS: dict[str, Project] = {}


def _seed() -> Project:
    """One demo project so GET works on a cold start."""
    p = Project(id="demo", takeoff=example_takeoff())
    _PROJECTS[p.id] = p
    return p


_seed()


def _get(project_id: str) -> Project:
    if project_id not in _PROJECTS:
        raise HTTPException(404, f"no project {project_id!r}")
    return _PROJECTS[project_id]


# -- requests / responses --------------------------------------------------


class CreateProject(BaseModel):
    name: str
    jurisdiction: str | None = None
    gfa_m2: float | None = None
    gfa_basis: str = "unknown"


class OverrideQuantity(BaseModel):
    """Stage 2: a human must be able to correct any quantity and see carbon update."""

    quantity: float | None = Field(
        default=None, description="null clears the override and restores the extracted value"
    )
    note: str | None = None


class IntakeSummary(BaseModel):
    project_id: str
    source_file: str
    n_sheets: int
    n_readable: int
    toolchains: dict[str, int]
    gaps: list[Gap]
    sheets: list[SheetInfo]


class Substitution(BaseModel):
    line_id: str
    from_material: str
    to_material: str
    delta_kg_co2e: float
    pct_of_total: float


# -- endpoints -------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


@app.get("/projects")
def list_projects() -> list[dict[str, object]]:
    return [
        {
            "id": p.id,
            "name": p.takeoff.project.name,
            "total_kg_co2e": p.carbon.total_kg_co2e,
            "n_lines": len(p.takeoff.lines),
        }
        for p in _PROJECTS.values()
    ]


@app.post("/projects", status_code=201)
def create_project(body: CreateProject) -> dict[str, str]:
    """Upload lands here in Step 13. For now it clones the fixture so the UI
    can exercise the create -> read -> edit loop."""
    t = example_takeoff()
    t.project.name = body.name
    if body.jurisdiction:
        t.project.jurisdiction = body.jurisdiction
    if body.gfa_m2:
        t.project.gfa_m2 = body.gfa_m2
        t.project.gfa_basis = body.gfa_basis  # type: ignore[assignment]
    pid = uuid.uuid4().hex[:8]
    _PROJECTS[pid] = Project(id=pid, takeoff=t)
    return {"id": pid}


@app.get("/projects/{project_id}/intake", response_model=IntakeSummary)
def get_intake(project_id: str) -> IntakeSummary:
    """Stage 1. Deliberately a separate call from the takeoff: the UI shows the
    gap report BEFORE any number, so nobody reads a total without its caveats."""
    p = _get(project_id)
    counts: dict[str, int] = {}
    for s in p.takeoff.sheets:
        counts[s.toolchain.value] = counts.get(s.toolchain.value, 0) + 1
    return IntakeSummary(
        project_id=p.id,
        source_file=p.takeoff.source_file,
        n_sheets=len(p.takeoff.sheets),
        n_readable=len(p.takeoff.readable_sheets),
        toolchains=counts,
        gaps=p.takeoff.gaps,
        sheets=p.takeoff.sheets,
    )


@app.get("/projects/{project_id}/takeoff", response_model=TakeoffResult)
def get_takeoff(project_id: str) -> TakeoffResult:
    return _get(project_id).takeoff


@app.get("/projects/{project_id}/carbon", response_model=CarbonResult)
def get_carbon(project_id: str) -> CarbonResult:
    return _get(project_id).carbon


@app.post("/projects/{project_id}/lines/{line_id}", response_model=CarbonResult)
def override_line(project_id: str, line_id: str, body: OverrideQuantity) -> CarbonResult:
    """Correct a quantity and get the updated carbon back in one round trip."""
    p = _get(project_id)
    try:
        line = p.takeoff.line(line_id)
    except KeyError:
        raise HTTPException(404, f"no line {line_id!r}") from None
    if body.quantity is not None and body.quantity < 0:
        raise HTTPException(422, "quantity must be >= 0")
    line.user_override = body.quantity
    line.override_note = body.note
    p.recompute()
    return p.carbon


@app.get("/projects/{project_id}/substitutions", response_model=list[Substitution])
def get_substitutions(project_id: str) -> list[Substitution]:
    """Stage 4: ranked by computed impact, never listed arbitrarily.

    Real options arrive in Step 15; the concrete mix swap below uses the
    published Kootenay figures so the ranking is honest from day one.
    """
    from ecarbon.fixtures import FACTOR_CONCRETE_GU, FACTOR_CONCRETE_GUL40

    p = _get(project_id)
    out: list[Substitution] = []
    for cl in p.carbon.lines:
        if cl.factor and cl.factor.factor_id == FACTOR_CONCRETE_GU.factor_id:
            delta = cl.quantity * (
                FACTOR_CONCRETE_GUL40.gwp_value - FACTOR_CONCRETE_GU.gwp_value
            )
            out.append(
                Substitution(
                    line_id=cl.line_id,
                    from_material=FACTOR_CONCRETE_GU.name,
                    to_material=FACTOR_CONCRETE_GUL40.name,
                    delta_kg_co2e=round(delta, 1),
                    pct_of_total=round(100 * delta / p.carbon.total_kg_co2e, 1)
                    if p.carbon.total_kg_co2e
                    else 0.0,
                )
            )
    out.sort(key=lambda s: s.delta_kg_co2e)  # biggest saving first
    return out
