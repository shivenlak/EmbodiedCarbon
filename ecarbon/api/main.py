"""FastAPI surface.

Serves the fixture until the real pipeline lands, so the UI can be built in
parallel. Every endpoint shape here is final; only the data behind it changes.

    uvicorn ecarbon.api.main:app --reload
"""

from __future__ import annotations

import csv
import io
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import pandas as pd
from pydantic import BaseModel, Field

from ecarbon.carbon.calculate import calculate_carbon
from ecarbon.carbon.store import LocalSnapshotProvider
from ecarbon.fixtures import example_takeoff
from ecarbon.models import CarbonResult, Gap, SheetInfo, TakeoffResult
from ecarbon.takeoff.builder import generate_takeoff

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
        self.carbon = calculate_carbon(self.takeoff)


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
    """Create project from body or clone fixture."""
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


@app.post("/projects/upload", status_code=201)
async def upload_project(file: UploadFile = File(...)) -> dict[str, str]:
    """Upload a vector PDF blueprint and run automated takeoff pipeline."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported.")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        shutil.copyfileobj(file.file, tmp)

    try:
        takeoff = generate_takeoff(tmp_path, project_name=file.filename.replace(".pdf", ""))
        pid = uuid.uuid4().hex[:8]
        _PROJECTS[pid] = Project(id=pid, takeoff=takeoff)
        return {"id": pid}
    except Exception as exc:
        raise HTTPException(500, f"Extraction failed: {exc}") from exc
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


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
    """Stage 4: ranked by computed impact, never listed arbitrarily."""
    p = _get(project_id)
    prov = LocalSnapshotProvider()
    subs_defs = prov.list_substitutions()
    out: list[Substitution] = []

    for s in subs_defs:
        from_f = prov.get_factor(s["from_factor_id"])
        to_f = prov.get_factor(s["to_factor_id"])
        if not from_f or not to_f:
            continue

        for cl in p.carbon.lines:
            if cl.factor and cl.factor.factor_id == from_f.factor_id:
                delta = cl.quantity * (to_f.gwp_value - from_f.gwp_value)
                out.append(
                    Substitution(
                        line_id=cl.line_id,
                        from_material=from_f.name,
                        to_material=to_f.name,
                        delta_kg_co2e=round(delta, 1),
                        pct_of_total=round(100 * delta / p.carbon.total_kg_co2e, 1)
                        if p.carbon.total_kg_co2e
                        else 0.0,
                    )
                )

    out.sort(key=lambda item: item.delta_kg_co2e)  # biggest saving first
    return out


@app.get("/projects/{project_id}/export/csv")
def export_csv(project_id: str) -> Response:
    """Export traceable Bill of Quantities with carbon factors to CSV."""
    p = _get(project_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "line_id", "element_class", "assembly_tag", "material",
        "extracted_quantity", "effective_quantity", "unit", "confidence",
        "page", "sheet_no", "detail", "assumptions",
        "factor_id", "factor_name", "declared_unit", "gwp_value",
        "kg_co2e", "conversion_note", "missing_reason"
    ])

    cline_map = {cl.line_id: cl for cl in p.carbon.lines}

    for ln in p.takeoff.lines:
        cl = cline_map.get(ln.id)
        f = cl.factor if cl else None
        writer.writerow([
            ln.id,
            ln.element_class.value,
            ln.assembly_tag or "",
            ln.material or "",
            ln.quantity,
            ln.effective_quantity,
            ln.unit.value,
            ln.confidence.value,
            ln.provenance.page,
            ln.provenance.sheet_no or "",
            ln.provenance.detail or "",
            "; ".join(ln.assumptions),
            f.factor_id if f else "",
            f.name if f else "",
            f.declared_unit if f else "",
            f.gwp_value if f else "",
            cl.kg_co2e if cl and cl.kg_co2e is not None else "",
            cl.conversion_note if cl else "",
            cl.missing_reason if cl and cl.missing_reason else "",
        ])

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={project_id}_boq.csv"},
    )


@app.get("/projects/{project_id}/export/xlsx")
def export_xlsx(project_id: str) -> Response:
    """Export traceable Bill of Quantities with carbon factors to Excel (.xlsx)."""
    p = _get(project_id)
    cline_map = {cl.line_id: cl for cl in p.carbon.lines}

    rows = []
    for ln in p.takeoff.lines:
        cl = cline_map.get(ln.id)
        f = cl.factor if cl else None
        rows.append({
            "Line ID": ln.id,
            "Element Class": ln.element_class.value,
            "Assembly Tag": ln.assembly_tag or "",
            "Material": ln.material or "",
            "Extracted Qty": ln.quantity,
            "Effective Qty": ln.effective_quantity,
            "Unit": ln.unit.value,
            "Confidence": ln.confidence.value,
            "Sheet Number": ln.provenance.sheet_no or "",
            "Page": ln.provenance.page,
            "Detail": ln.provenance.detail or "",
            "Assumptions": "; ".join(ln.assumptions),
            "Carbon Factor": f.name if f else "",
            "Declared Unit": f.declared_unit if f else "",
            "GWP Value": f.gwp_value if f else None,
            "Embodied Carbon (kgCO2e)": cl.kg_co2e if cl else None,
            "Conversion Note": cl.conversion_note if cl else "",
            "Missing Reason": cl.missing_reason if cl else "",
        })

    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Bill of Quantities", index=False)
        summary_rows = [
            {"Metric": "Project Name", "Value": p.takeoff.project.name},
            {"Metric": "Total Embodied Carbon (kgCO2e)", "Value": p.carbon.total_kg_co2e},
            {"Metric": "Embodied Carbon Intensity (kgCO2e/m2)", "Value": p.carbon.intensity_kg_co2e_per_m2},
            {"Metric": "Intensity Basis", "Value": p.carbon.intensity_basis},
            {"Metric": "Gross Floor Area (m2)", "Value": p.takeoff.project.gfa_m2},
            {"Metric": "Module Scope", "Value": "-".join(p.carbon.modules)},
            {"Metric": "Coverage (%)", "Value": round(p.carbon.coverage_pct, 1)},
        ]
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)

    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={project_id}_boq.xlsx"},
    )
