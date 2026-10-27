"""FastAPI surface.

Serves the real pipeline: every design found under `$EC_DATA` is listed, and
the first request for one runs the extraction stages and the carbon engine.

Takeoffs are built lazily and cached, because building one opens the PDF and
measures the geometry -- a few seconds per design, which is fine on demand and
unacceptable for 53 designs at startup.

    uvicorn ecarbon.api.main:app --reload
"""

from __future__ import annotations

import base64
import os
import re
import secrets
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from ecarbon.carbon.calculate import calculate_carbon
from ecarbon.carbon.store import LocalSnapshotProvider
from ecarbon.models import CarbonResult, Gap, GapCode, SheetInfo, TakeoffResult

# One provider for the process: it owns a SQLite connection and the factor
# snapshot, neither of which is per-request state.
_FACTORS = LocalSnapshotProvider()

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
    # The design this was built from, when there is one. An uploaded set is
    # not in the catalogue, so without this click-to-trace would work for
    # catalogue designs and quietly fail for the customer's own drawings --
    # which are the only ones a pilot actually cares about.
    design: object | None = None
    carbon: CarbonResult = field(init=False)

    def __post_init__(self) -> None:
        self.recompute()

    def recompute(self) -> None:
        # Carbon is derived from the takeoff and never mutates it, so a
        # recompute after an override cannot corrupt the extraction output.
        self.carbon = calculate_carbon(self.takeoff, _FACTORS)
        self._check_intensity()

    def _check_intensity(self) -> None:
        """Surface an impossible intensity beside the other gaps.

        Intensity is the one figure that can be wrong while every quantity
        behind it is right, because it depends on a floor area the drawings
        may not state. The check lives with the gaps rather than inside
        CarbonResult so it reaches the panel the UI shows before any number,
        and so the carbon document stays a pure function of the takeoff.
        """
        from ecarbon.carbon.plausibility import intensity_warning

        code = GapCode.GEOMETRY_AMBIGUOUS
        marker = "kgCO2e/m2 is"
        self.takeoff.gaps = [
            g
            for g in self.takeoff.gaps
            if not (g.code == code and marker in g.message)
        ]
        # The coverage the takeoff itself reports, not a recomputation: the
        # two can differ, and the figure the user is shown is the one that
        # should gate the check.
        coverage = 1.0
        for gap in self.takeoff.gaps:
            found = re.search(r"roughly (\d+)%", gap.message)
            if found:
                coverage = int(found.group(1)) / 100.0
                break
        warning = intensity_warning(self.carbon, self.takeoff.project, coverage)
        if warning is not None:
            self.takeoff.gaps.insert(0, warning)


_PROJECTS: dict[str, Project] = {}

# The catalogue is licence-restricted and cannot be committed, so the service
# must be useful without it: a fixture-backed project is always present. It is
# also what the API tests run against, so they need no 2.7 GB download.
DEMO_ID = "demo"


def _seed_demo() -> None:
    from ecarbon.fixtures import example_takeoff

    _PROJECTS[DEMO_ID] = Project(id=DEMO_ID, takeoff=example_takeoff())


_seed_demo()


def _catalogue() -> dict[str, object]:
    """Designs available on this machine, by key. Empty when $EC_DATA is unset."""
    try:
        from ecarbon.config import discover

        return {d.key: d for d in discover()}
    except Exception:
        return {}


def _resolve(name: str) -> str | None:
    """Match a plan-set name against the catalogue.

    Catalogue keys carry a packaging suffix (`AB_Sixplex_Technical_Design_
    Package`), so a caller naming the design itself must still find it.
    """
    cat = _catalogue()
    if name in cat:
        return name
    lowered = name.lower()
    matches = [k for k in cat if k.lower().startswith(lowered)]
    if len(matches) == 1:
        return matches[0]
    return None


def _build(key: str, stated: CreateProject | None = None) -> Project:
    """Run the pipeline for one design and cache the result.

    `stated` carries the project facts the caller gave. They take precedence
    over anything read from the package, because a floor area the builder
    states is a fact and one we read off a report is a convenience -- and the
    two use different conventions often enough that silently preferring ours
    would make the intensity wrong in a way nobody could see.
    """
    from ecarbon.models import ProjectFacts
    from ecarbon.takeoff.builder import build_takeoff

    design = _catalogue().get(key)
    if design is None:
        raise HTTPException(404, f"no plan set {key!r} under $EC_DATA")

    facts = ProjectFacts(name=(stated.name if stated else None) or key)

    # The Building Performance Report states floor area, storeys and units --
    # project facts a builder would otherwise type in. Never its carbon total,
    # which is A1-A5+B+C and not comparable with our A1-A3 figure.
    try:
        from ecarbon.bench.bpr import parse_bpr

        if design.bpr:
            bp = parse_bpr(str(design.bpr[0]))
            facts.jurisdiction = bp.location
            facts.gfa_m2 = bp.best_gfa_m2
            facts.gfa_basis = "gross"
            facts.storeys = bp.storeys
            facts.units = bp.units
    except Exception:
        pass

    if stated is not None:
        if stated.jurisdiction:
            facts.jurisdiction = stated.jurisdiction
        if stated.gfa_m2:
            facts.gfa_m2 = stated.gfa_m2
            facts.gfa_basis = stated.gfa_basis  # type: ignore[assignment]

    # A floor area in the request is the caller's own figure; one from the
    # Building Performance Report is a stated fact we audit against the
    # drawings. Only the latter is replaced.
    typed_area = bool(stated and stated.gfa_m2)
    p = Project(
        id=key,
        takeoff=build_takeoff(design, facts, trust_stated_gfa=typed_area),
        design=design,
    )
    _PROJECTS[key] = p
    return p


def _get(project_id: str) -> Project:
    if project_id in _PROJECTS:
        return _PROJECTS[project_id]
    if project_id in _catalogue():
        return _build(project_id)
    raise HTTPException(404, f"no project {project_id!r}")


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
    """Every plan set on this machine.

    Carbon is reported only for sets already built, since computing it for the
    whole catalogue would mean opening 53 PDFs to answer a list request.
    """
    out: list[dict[str, object]] = []
    for key in sorted(_catalogue()):
        p = _PROJECTS.get(key)
        out.append(
            {
                "id": key,
                "name": key.replace("_", " "),
                "built": p is not None,
                "total_kg_co2e": p.carbon.total_kg_co2e if p else None,
                "n_lines": len(p.takeoff.lines) if p else None,
            }
        )
    for pid, p in _PROJECTS.items():
        if pid not in _catalogue():
            out.append(
                {
                    "id": pid,
                    "name": p.takeoff.project.name,
                    "built": True,
                    "total_kg_co2e": p.carbon.total_kg_co2e,
                    "n_lines": len(p.takeoff.lines),
                }
            )
    return out


@app.post("/projects", status_code=201)
def create_project(body: CreateProject) -> dict[str, str]:
    """Build a plan set found under $EC_DATA.

    `name` is the design key. Uploading an arbitrary PDF is Step 13; the
    pipeline itself takes any vector set, so this endpoint is the only thing
    standing between it and an upload.
    """
    key = _resolve(body.name)
    if key is not None:
        return {"id": _build(key, stated=body).id}
    raise HTTPException(
        404,
        f"no plan set {body.name!r} under $EC_DATA. "
        f"GET /projects lists what is available.",
    )


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

    Every option comes from the factor store, so a swap can only be offered
    when both the current and the replacement factor are real records with a
    source and a module scope. A swap whose replacement is not in the store is
    not shown rather than estimated.
    """
    p = _get(project_id)
    out: list[Substitution] = []

    for swap in _FACTORS.list_substitutions():
        src = _FACTORS.get_factor(swap["from_factor_id"])
        dst = _FACTORS.get_factor(swap["to_factor_id"])
        if src is None or dst is None:
            continue
        # Only like-for-like module scopes can be compared, for the same reason
        # they cannot be summed.
        if src.modules != dst.modules:
            continue
        for cl in p.carbon.lines:
            if not cl.is_counted or not cl.factor:
                continue
            if cl.factor.factor_id != src.factor_id:
                continue
            delta = cl.quantity * (dst.gwp_value - src.gwp_value)
            out.append(
                Substitution(
                    line_id=cl.line_id,
                    from_material=src.name,
                    to_material=dst.name,
                    delta_kg_co2e=round(delta, 1),
                    pct_of_total=round(100 * delta / p.carbon.total_kg_co2e, 1)
                    if p.carbon.total_kg_co2e
                    else 0.0,
                )
            )

    out.sort(key=lambda s: s.delta_kg_co2e)  # biggest saving first
    return out


@app.get("/projects/{project_id}/export.csv", response_class=PlainTextResponse)
def export_csv(project_id: str) -> PlainTextResponse:
    """The bill of quantities as CSV, with provenance on every row.

    Criterion 5: a spreadsheet row that cannot be traced back to a sheet is
    what this product exists to replace, so sheet, detail, confidence, basis
    and assumptions all travel as columns.
    """
    from ecarbon.report import takeoff_csv

    p = _get(project_id)
    return PlainTextResponse(
        takeoff_csv(p.takeoff, p.carbon),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{project_id}-takeoff.csv"'
        },
    )


@app.get("/projects/{project_id}/report.html", response_class=HTMLResponse)
def export_report(project_id: str) -> HTMLResponse:
    """A printable report a builder could hand to a municipality."""
    from ecarbon.report import report_html

    p = _get(project_id)
    return HTMLResponse(report_html(p.takeoff, p.carbon))


# -- click-to-trace --------------------------------------------------------


class TraceRegionOut(BaseModel):
    """Where one line's quantity came from, on one page.

    `kind` is a claim about strength of evidence and the UI must not flatten
    it: `measured_geometry` means the rectangles are the linework that was
    measured, `schedule_row` means they are the text the figure was read from,
    and `sheet_only` means the region could not be located and nothing is
    highlighted.
    """

    page: int
    sheet_no: str | None = None
    kind: str
    note: str
    rects: list[tuple[float, float, float, float]] = Field(default_factory=list)
    page_width: float = 0.0
    page_height: float = 0.0
    image_url: str | None = None


def _design_for(project_id: str):
    held = _PROJECTS.get(project_id)
    design = getattr(held, "design", None) or _catalogue().get(project_id)
    if design is None:
        raise HTTPException(
            404,
            f"project {project_id!r} has no drawings on this machine, so there is "
            "nothing to trace to. The demo project is fixture-backed; set $EC_DATA "
            "and use a catalogue design to trace a line to its sheet.",
        )
    return design


@app.get("/projects/{project_id}/trace/{line_id}", response_model=list[TraceRegionOut])
def get_trace(project_id: str, line_id: str) -> list[TraceRegionOut]:
    """Criterion 2's strong form: the region of the sheet a quantity came from.

    Returns one entry per page, because a quantity measured on every storey --
    interior partitions -- genuinely comes from more than one sheet.
    """
    from ecarbon.trace import trace_line

    p = _get(project_id)
    try:
        p.takeoff.line(line_id)
    except KeyError:
        raise HTTPException(404, f"no line {line_id!r}") from None

    regions = trace_line(_design_for(project_id), p.takeoff, line_id)
    return [
        TraceRegionOut(
            page=r.page,
            sheet_no=r.sheet_no,
            kind=r.kind,
            note=r.note,
            rects=r.rects,
            page_width=r.page_width,
            page_height=r.page_height,
            image_url=f"/projects/{project_id}/trace/{line_id}/image.png?page={r.page}",
        )
        for r in regions
    ]


@app.get("/projects/{project_id}/trace/{line_id}/image.png")
def get_trace_image(project_id: str, line_id: str, page: int, dpi: int = 110):
    """The source page as a PNG with the measured regions outlined.

    The drawings are licence-restricted: CMHC forbids redistributing them, so
    this renders for the person running the tool and the service must not be
    exposed publicly with a catalogue attached.
    """
    from fastapi.responses import Response

    from ecarbon.trace import render_page, trace_line

    p = _get(project_id)
    design = _design_for(project_id)
    regions = [r for r in trace_line(design, p.takeoff, line_id) if r.page == page]
    if not regions:
        raise HTTPException(404, f"line {line_id!r} does not trace to page {page}")
    rects = [rect for r in regions for rect in r.rects]
    try:
        png = render_page(design, page, rects, dpi=max(40, min(dpi, 300)))
    except IndexError as exc:
        raise HTTPException(404, str(exc)) from None
    return Response(content=png, media_type="image/png")


# -- decisions the drawings leave open -------------------------------------


class ChoiceOption(BaseModel):
    factor_id: str
    name: str
    source: str
    kg_co2e: float


class UnspecifiedChoiceOut(BaseModel):
    """A layer the drawings decline to specify, priced as a range.

    Distinct from a substitution: a substitution replaces a material the
    drawings chose, while this is a choice nobody has made yet. Presenting the
    two the same way would imply a decision exists where none does.
    """

    assembly_tag: str
    category: str
    drawing_says: str
    area_m2: float
    sheet_no: str | None = None
    page: int | None = None
    low_kg_co2e: float
    high_kg_co2e: float
    spread_kg_co2e: float
    note: str
    options: list[ChoiceOption]


@app.get(
    "/projects/{project_id}/unspecified",
    response_model=list[UnspecifiedChoiceOut],
)
def get_unspecified(project_id: str) -> list[UnspecifiedChoiceOut]:
    """Criterion 3's discipline, made actionable.

    These layers carry no carbon in the total because no material has been
    chosen. Rather than defaulting one and saying nothing, each is reported
    with what every available option would cost, ordered by how much the
    decision moves.
    """
    from ecarbon.carbon.unspecified import unspecified_choices
    from ecarbon.extract.assemblies import assemblies_for

    p = _get(project_id)
    design = getattr(p, "design", None) or _catalogue().get(project_id)
    if design is None:
        return []
    assemblies, _refused = assemblies_for(design)
    return [
        UnspecifiedChoiceOut(
            assembly_tag=c.assembly_tag,
            category=c.category,
            drawing_says=c.drawing_says,
            area_m2=c.area_m2,
            sheet_no=c.sheet_no,
            page=c.page,
            low_kg_co2e=c.low_kg_co2e,
            high_kg_co2e=c.high_kg_co2e,
            spread_kg_co2e=c.spread_kg_co2e,
            note=c.note,
            options=[
                ChoiceOption(
                    factor_id=o.factor.factor_id,
                    name=o.name,
                    source=o.factor.source,
                    kg_co2e=o.kg_co2e,
                )
                for o in c.options
            ],
        )
        for c in unspecified_choices(p.takeoff, assemblies, _FACTORS)
    ]


# -- uploading a plan set --------------------------------------------------

# A drawing set is a few hundred vector pages; 120 MB is comfortably above the
# largest in the CMHC catalogue and well below anything that would exhaust
# memory here.
MAX_UPLOAD_BYTES = 120 * 1024 * 1024
_UPLOAD_ROOT: Path | None = None


def _upload_dir() -> Path:
    """A private directory for uploaded sets, outside the repo and $EC_DATA.

    Uploads are untrusted input and are not part of the catalogue: keeping
    them in their own tree means an upload can never be mistaken for a
    licensed CMHC design, and nothing we ship can be overwritten by one.
    """
    global _UPLOAD_ROOT
    if _UPLOAD_ROOT is None:
        _UPLOAD_ROOT = Path(tempfile.mkdtemp(prefix="ecarbon-uploads-"))
    return _UPLOAD_ROOT


@app.post("/projects/upload", status_code=201)
async def upload_project(
    # B008 is suppressed per-argument: calling File()/Form() in the default is
    # how FastAPI declares multipart fields, not an accidental shared default.
    file: UploadFile = File(...),  # noqa: B008
    name: str | None = Form(None),  # noqa: B008
    gfa_m2: float | None = Form(None),  # noqa: B008
    gfa_basis: str | None = Form(None),  # noqa: B008
    storeys: int | None = Form(None),  # noqa: B008
    units: int | None = Form(None),  # noqa: B008
    jurisdiction: str | None = Form(None),  # noqa: B008
) -> dict[str, object]:
    """Run the pipeline on a plan set the caller supplies.

    This is what makes the tool usable on drawings we have never seen, which
    is the only test that counts: the catalogue is a development set, and a
    builder's own sets are the product. Everything downstream -- gap report,
    bill of quantities, click-to-trace, substitutions -- works identically,
    because none of it is specialised to the catalogue.

    The figures a drawing cannot state are asked for rather than guessed.
    Gross floor area in particular decides the intensity per square metre, and
    inferring it from a plan whose extents cover a whole block gave one
    catalogue design an intensity six times its neighbours'.
    """
    from ecarbon.config import Design
    from ecarbon.models import ProjectFacts
    from ecarbon.takeoff.builder import build_takeoff

    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, f"plan set larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
        )
    if not raw.startswith(b"%PDF-"):
        raise HTTPException(
            415,
            "not a PDF. This pipeline reads vector PDF drawing sets; a scan "
            "or an image export carries no geometry to measure.",
        )

    stem = Path(file.filename or "plan-set").stem or "plan-set"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", stem)[:80].strip("-") or "plan-set"
    project_id = f"upload-{uuid.uuid4().hex[:8]}-{safe}"

    # Its own empty directory, so nothing in the set can land beside another
    # upload or anything we ship.
    home = _upload_dir() / project_id
    home.mkdir(parents=True, exist_ok=False)
    pdf = home / f"{safe}.pdf"
    pdf.write_bytes(raw)

    design = Design(
        key=project_id,
        region="UPLOAD",
        package_dir=home,
        drawings_pdf=pdf,
        ifc=None,
        h2k=[],
        bpr=[],
        list_of_drawings=None,
    )
    facts = ProjectFacts(
        name=name or safe,
        jurisdiction=jurisdiction,
        gfa_m2=gfa_m2,
        gfa_basis=gfa_basis or "gross",
        storeys=storeys,
        units=units,
    )
    try:
        takeoff = build_takeoff(design, facts, trust_stated_gfa=gfa_m2 is not None)
    except Exception as exc:
        raise HTTPException(
            422,
            f"could not read this plan set: {exc}. Nothing partial is stored.",
        ) from exc

    project = Project(id=project_id, takeoff=takeoff, design=design)
    _PROJECTS[project_id] = project
    return {
        "id": project_id,
        "n_lines": len(takeoff.lines),
        "n_sheets": len(takeoff.sheets),
        "n_gaps": len(takeoff.gaps),
        "total_kg_co2e": project.carbon.total_kg_co2e,
    }


# -- serving the app itself -------------------------------------------------

# One service serves the API and the built interface from the same origin.
# Two services would mean a CORS surface, two deploys and two things to break
# during a demo, for no benefit when the frontend is 260 kB of static files.
_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"

# Credentials are read from the environment so none is ever committed. With
# neither set the service is open, which is what local development wants; set
# both and every route except the health check requires them.
_AUTH_USER = os.environ.get("ECARBON_USER")
_AUTH_PASSWORD = os.environ.get("ECARBON_PASSWORD")
_OPEN_PATHS = {"/health"}


@app.middleware("http")
async def _require_credentials(request, call_next):
    """HTTP basic auth over the whole service when credentials are configured.

    The drawings this serves are licence-restricted, so an open deployment
    would publish them to anyone who found the URL. Gating the whole origin --
    interface, API and rendered sheets alike -- is the only version of this
    that actually holds, since the trace endpoint returns page images.
    """
    if not (_AUTH_USER and _AUTH_PASSWORD):
        return await call_next(request)
    if request.url.path in _OPEN_PATHS:
        return await call_next(request)

    header = request.headers.get("authorization", "")
    expected = base64.b64encode(
        f"{_AUTH_USER}:{_AUTH_PASSWORD}".encode()
    ).decode()
    supplied = header[6:] if header.lower().startswith("basic ") else ""
    # Compared in constant time so the comparison itself leaks nothing.
    if not secrets.compare_digest(supplied, expected):
        return Response(
            status_code=401,
            content="Credentials required.",
            headers={"WWW-Authenticate": 'Basic realm="ecarbon"'},
        )
    return await call_next(request)


def _mount_interface() -> None:
    """Serve the built interface, if it has been built.

    Mounted last so every API route above wins its path, and with html=True so
    a deep link falls back to index.html rather than 404ing -- the interface is
    a single page and does its own routing.
    """
    if not _WEB_DIST.is_dir():
        return
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_WEB_DIST), html=True), name="web")


_mount_interface()
