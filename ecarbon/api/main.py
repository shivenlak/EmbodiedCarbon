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
import contextvars
import hashlib
import hmac
import os
import re
import secrets
import tempfile
import threading
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
    # What the user stated where the drawings could not be read (contract C2).
    # Held so a later calibration adds to earlier ones rather than replacing them.
    overrides: object | None = None
    # Whose carbon factors to use ("US", "CA-AB", ...); None is the default
    # (Canadian) set, exactly as before. `region_source` says how it was set.
    geography: str | None = None
    region_source: str = "default"
    # The user's material choices (line id -> factor id) and their own
    # materials (typed, or from the builder's uploaded list). Kept on the
    # project, so they survive a rebuild after "Help it read this".
    material_edits: dict = field(default_factory=dict)
    user_factors: dict = field(default_factory=dict)
    library_files: list = field(default_factory=list)
    # "Your spec": swaps tried (line id -> material) and choices made for the
    # placeholders (decision key -> factor id). A what-if beside the counted
    # total, kept here so it survives a reload and goes into the exports.
    scenario: dict = field(default_factory=lambda: {"swaps": {}, "picks": {}})
    # Partition walls the user excluded on the plan (wall ids, see /partitions).
    excluded_walls: set = field(default_factory=set)
    carbon: CarbonResult = field(init=False)

    def __post_init__(self) -> None:
        self.recompute()

    def recompute(self) -> None:
        # Carbon is derived from the takeoff and never mutates it, so a
        # recompute after an override cannot corrupt the extraction output.
        from ecarbon.carbon.user_factors import EDIT_MARK

        takeoff = self.takeoff
        if self.material_edits:
            # Priced on a copy, so the extraction output itself never changes:
            # the line keeps the material the drawings name, and the chosen
            # factor answers it.
            takeoff = self.takeoff.model_copy(deep=True)
            for ln in takeoff.lines:
                fid = self.material_edits.get(ln.id)
                if fid:
                    ln.material = f"{ln.material or ln.element_class.value}{EDIT_MARK}{fid}"
        self.carbon = calculate_carbon(
            takeoff, self.factors, geography=self.geography
        )
        self._check_intensity()

    @property
    def factors(self):
        from ecarbon.carbon.user_factors import ProjectFactors

        return ProjectFactors(_FACTORS, self.user_factors)

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

# Parsing one drawing set peaks near 900 MB, and FastAPI runs sync endpoints
# on a 40-thread pool, so two simultaneous builds are enough to exhaust any
# machine this would sensibly run on. Measured on the deployment: a second
# build arriving during QC_Sixplex killed the machine outright, which also
# throws away every design cached before it. Heavy work is therefore
# serialised -- a visitor may wait, but the service stays up.
_BUILD_LOCK = threading.Lock()

# The massing view re-reads the drawings to recover footprint, datums and
# partition positions -- about 20 s on a shared core, which the prebuilt
# takeoff does nothing to avoid because it stores quantities rather than
# geometry. Held per project so only the first viewer pays, the same bargain
# the takeoff cache makes.
_MASSING: dict[str, object] = {}

# Tracing a partition line recomputes the partition geometry from the
# drawings, about 16 s, because the prebuilt takeoff stores quantities rather
# than the rectangles they were measured from. Held per line: this is the
# moment a demo is built around and the first press should not be the slow
# one. Rendered sheets are held too -- a 36x24 inch page at 150 dpi is 1.2 MB
# and about 3 s to produce.
_TRACE: dict[tuple[str, str], object] = {}
_SHEET_PNG: dict[tuple[str, str, int, int, bool], bytes] = {}
_THUMB_PNG: dict[tuple[str, str, int, int, bool], bytes] = {}

# The open decisions re-read the assemblies schedule to find the layers the
# drawings decline to specify -- about 5 s, every call, because unlike the
# massing and the traces this had no cache at all. Warming it did nothing for
# exactly that reason.
_UNSPECIFIED: dict[str, object] = {}

# The catalogue is licence-restricted and cannot be committed, so the service
# must be useful without it: a fixture-backed project is always present. It is
# also what the API tests run against, so they need no 2.7 GB download.
DEMO_ID = "demo"


def _seed_demo() -> None:
    from ecarbon.fixtures import example_takeoff

    _PROJECTS[DEMO_ID] = Project(id=DEMO_ID, takeoff=example_takeoff())


_seed_demo()


# -- workspaces -------------------------------------------------------------
#
# Every visitor works in their own workspace: a signed-in account ("u:name")
# or a guest ("g:<random>"). Requests without a token -- curl, the API docs --
# share one "public" workspace. Before this, a quantity corrected by one
# visitor was corrected for everyone, and an upload appeared in every
# visitor's list.
#
# The bundled plan sets stay shared and cached, because building one costs
# 20-200 s and they are the same for everybody. The first correction a
# workspace makes forks its own copy of that project; uploads belong to the
# workspace that uploaded them and do not exist for anyone else.
#
# All of it is held in memory, like every other cache here: a restart clears
# accounts, corrections and uploads alike. The bundled sets come back on
# their own, prebuilt into the image.

_SECRET = (os.environ.get("ECARBON_SECRET") or secrets.token_hex(32)).encode()
_WORKSPACE: contextvars.ContextVar[str] = contextvars.ContextVar(
    "ecarbon_workspace", default="public"
)
_USERS: dict[str, str] = {}  # username -> "salt_hex$hash_hex"
_OWNER: dict[str, str] = {}  # upload id -> the workspace that uploaded it
_FORKS: dict[tuple[str, str], Project] = {}  # (workspace, project) -> its copy
_MAX_FORKS = 600  # a bound, so a stream of guests cannot grow memory forever


def _sign(workspace: str) -> str:
    mac = hmac.new(_SECRET, workspace.encode(), hashlib.sha256).hexdigest()[:40]
    return f"{workspace}.{mac}"


def _verify(token: str) -> str | None:
    workspace, _, mac = token.rpartition(".")
    if not workspace or not mac:
        return None
    expected = _sign(workspace).rpartition(".")[2]
    return workspace if hmac.compare_digest(mac, expected) else None


class _WorkspaceMiddleware:
    """Reads the session token and sets the workspace for this request.

    Pure ASGI rather than BaseHTTPMiddleware, so the context variable is set
    in the same context the endpoint (and its worker thread) runs in. The
    token may ride the query string, because an <img src> and a download link
    cannot carry a header.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        token = ""
        for name, value in scope.get("headers") or []:
            if name == b"x-ecarbon-session":
                token = value.decode("latin-1")
                break
        if not token:
            from urllib.parse import parse_qs

            qs = parse_qs((scope.get("query_string") or b"").decode("latin-1"))
            token = (qs.get("session") or [""])[0]
        workspace = (_verify(token) if token else None) or "public"
        reset = _WORKSPACE.set(workspace)
        try:
            await self.app(scope, receive, send)
        finally:
            _WORKSPACE.reset(reset)


app.add_middleware(_WorkspaceMiddleware)


def _visible(project_id: str) -> None:
    """An upload exists only for the workspace that made it."""
    owner = _OWNER.get(project_id)
    if owner is not None and owner != _WORKSPACE.get():
        raise HTTPException(404, f"no project {project_id!r}")


def _own(project_id: str) -> Project:
    """This workspace's copy of a project, made on its first change."""
    p = _get(project_id)
    if project_id in _OWNER:
        return p  # an upload is already private to its owner
    key = (_WORKSPACE.get(), project_id)
    fork = _FORKS.get(key)
    if fork is None:
        if len(_FORKS) >= _MAX_FORKS:
            _FORKS.pop(next(iter(_FORKS)))
        fork = Project(
            id=p.id,
            takeoff=p.takeoff.model_copy(deep=True),
            design=p.design,
            geography=p.geography,
            region_source=p.region_source,
            material_edits=dict(p.material_edits),
            user_factors=dict(p.user_factors),
            library_files=list(p.library_files),
            scenario={"swaps": dict(p.scenario["swaps"]), "picks": dict(p.scenario["picks"])},
            excluded_walls=set(p.excluded_walls),
        )
        _FORKS[key] = fork
    return fork


def _data_root():
    from ecarbon.config import data_root

    return data_root()


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

    # A takeoff saved at image-build time, when there is one and the caller
    # has not supplied facts of their own. Parsing a set costs about 23
    # seconds on a shared core and 177 for the largest, and that cost used to
    # fall on whoever opened the link first -- and again after every restart,
    # because the only cache was in memory.
    prebuilt = None
    if stated is None:
        try:
            from ecarbon.prebuilt import load_prebuilt

            prebuilt = load_prebuilt(
                Path(_data_root()), key, getattr(design, "drawings_pdf", None)
            )
        except Exception:
            prebuilt = None

    with _BUILD_LOCK:
        # Re-check inside the lock: several requests can queue on the same
        # design, and the first through should be the only one to build it.
        if key in _PROJECTS:
            return _PROJECTS[key]
        p = Project(
            id=key,
            takeoff=prebuilt
            or build_takeoff(design, facts, trust_stated_gfa=typed_area),
            design=design,
        )
    _PROJECTS[key] = p
    return p


def _get(project_id: str) -> Project:
    _visible(project_id)
    fork = _FORKS.get((_WORKSPACE.get(), project_id))
    if fork is not None:
        return fork
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
    """Stage 2: a human must be able to correct any quantity and see carbon update.

    Since the UX session (25 Nov) also the material and the layer thickness.
    Only the fields sent are changed: a material edit leaves the quantity alone.
    """

    quantity: float | None = Field(
        default=None, description="null clears the override and restores the extracted value"
    )
    note: str | None = None
    factor_id: str | None = Field(
        default=None, description="price this line with this factor; null restores the one found"
    )
    thickness_mm: float | None = Field(
        default=None, description="a layer's thickness; scales the volume by new / drawn thickness"
    )


class NewMaterial(BaseModel):
    """A material the user types in, with the source an auditor would ask for."""

    name: str
    declared_unit: str
    gwp_value: float = Field(description="kgCO2e per declared unit, A1-A3")
    density_kg_m3: float | None = None
    source: str = Field(description="EPD or database the factor comes from")
    epd_id: str | None = None
    valid_to: str | None = None
    category: str | None = None


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
    # The factor to apply, so a swap can be applied to the line itself
    # (POST /lines/{id} with factor_id) and carried into the exports.
    to_factor_id: str | None = None


# -- endpoints -------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    """Deliberately async, so it is answered on the event loop itself.

    A sync endpoint is run on a worker thread, and those threads are a finite
    pool that long builds can exhaust -- at which point the health check
    cannot get a thread, Fly concludes the app is dead and restarts it,
    throwing away every design cached so far. The liveness probe must not
    queue behind the work it is reporting on.
    """
    return {"status": "ok", "version": app.version}


@app.get("/projects")
def list_projects() -> list[dict[str, object]]:
    """Every plan set on this machine.

    Carbon is reported only for sets already built, since computing it for the
    whole catalogue would mean opening 53 PDFs to answer a list request.
    """
    out: list[dict[str, object]] = []
    ws = _WORKSPACE.get()
    for key in sorted(_catalogue()):
        p = _FORKS.get((ws, key)) or _PROJECTS.get(key)
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
        # The fixture is a four-line stand-in named after AB_Fourplex_01. Beside
        # the real design it read as a second AB_Fourplex_01 at a third of the
        # real total, so it is listed only when there is no real data to show.
        # /projects/demo still answers either way; the API tests depend on it.
        if pid == DEMO_ID and _catalogue():
            continue
        if _OWNER.get(pid, ws) != ws:
            continue
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


@app.get("/projects/{project_id}/calc")
def get_calc(project_id: str) -> dict:
    """How every line's kgCO2e was calculated, step by step (contract C8).

    One call for the whole bill, so every number in the interface can open its
    own calculation without a round trip. Each trace reproduces its line's
    kgCO2e exactly or the request fails: a wrong explanation is worse than none.
    """
    from ecarbon.carbon.calc_trace import explain_all

    p = _get(project_id)
    return {k: v.to_dict() for k, v in explain_all(p.takeoff, p.carbon, p.material_edits).items()}


@app.get("/projects/{project_id}/lines/{line_id}/calc")
def get_line_calc(project_id: str, line_id: str) -> dict:
    from ecarbon.carbon.calc_trace import explain

    p = _get(project_id)
    try:
        line = p.takeoff.line(line_id)
    except KeyError:
        raise HTTPException(404, f"no line {line_id!r}") from None
    cline = next((c for c in p.carbon.lines if c.line_id == line_id), None)
    return explain(line, cline, p.material_edits.get(line_id)).to_dict()


@app.post("/projects/{project_id}/lines/{line_id}", response_model=CarbonResult)
def override_line(project_id: str, line_id: str, body: OverrideQuantity) -> CarbonResult:
    """Correct a quantity and get the updated carbon back in one round trip.

    The correction lands in this workspace's own copy of the project, so it
    is never a correction for every other visitor too.
    """
    p = _own(project_id)
    try:
        line = p.takeoff.line(line_id)
    except KeyError:
        raise HTTPException(404, f"no line {line_id!r}") from None
    sent = body.model_fields_set
    if "quantity" in sent:
        if body.quantity is not None and body.quantity < 0:
            raise HTTPException(422, "quantity must be >= 0")
        line.user_override = body.quantity
        line.override_note = body.note
    if "thickness_mm" in sent and body.thickness_mm is not None:
        drawn = _drawn_thickness_mm(line)
        if drawn is None:
            raise HTTPException(422, "this line states no thickness to change")
        if body.thickness_mm <= 0:
            raise HTTPException(422, "thickness must be more than zero")
        line.user_override = round(line.quantity * body.thickness_mm / drawn, 4)
        line.override_note = (
            f"stated: thickness {drawn:g} -> {body.thickness_mm:g} mm, so the volume is "
            f"{line.quantity:g} x {body.thickness_mm:g} / {drawn:g}"
        )
    if "factor_id" in sent:
        if body.factor_id is None:
            p.material_edits.pop(line_id, None)
        else:
            f = p.factors.get_factor(body.factor_id)
            if f is None:
                raise HTTPException(404, f"no material {body.factor_id!r}")
            if f.declared_unit.strip().lower() not in _convertible(line.unit.value, f):
                raise HTTPException(
                    422,
                    f"{f.name} is declared per {f.declared_unit}; this line is in {line.unit.value}"
                    + (" and the material states no density" if f.declared_unit == "kg" else ""),
                )
            p.material_edits[line_id] = body.factor_id
    p.recompute()
    return p.carbon


def _drawn_thickness_mm(line) -> float | None:
    """A layer's thickness as its description states it ("Gypsum Board, 13 mm")."""
    if line.unit.value != "m3":
        return None
    m = re.findall(r"(\d+(?:\.\d+)?)\s*mm\b", line.description or "")
    return float(m[-1]) if m else None


def _convertible(unit: str, f) -> set[str]:
    """Declared units a line in `unit` can be priced in."""
    ok = {unit}
    if unit == "m3":
        ok |= {"kg"} if f.density_kg_m3 else set()
        ok |= {"m2"}
    if unit == "m2":
        ok |= {"m3", "100m2"}
    if unit == "kg" and f.density_kg_m3:
        ok |= {"m3"}
    return ok


@app.get("/projects/{project_id}/materials")
def list_materials(project_id: str) -> list[dict]:
    """Every material a line can be priced with: the project's own first
    (typed or from the builder's list), then Canadian factors, then the rest."""
    p = _get(project_id)

    def row(f, origin):
        return {
            "factor_id": f.factor_id, "name": f.name, "declared_unit": f.declared_unit,
            "gwp_value": f.gwp_value, "source": f.source, "source_id": f.source_id,
            "geography": f.geography, "data_type": f.data_type,
            "density_kg_m3": f.density_kg_m3, "origin": origin,
        }

    own = [row(f, "yours") for f in p.user_factors.values()]
    base = _FACTORS.list_factors()
    ca = [row(f, "Canada") for f in base if (f.geography or "").upper().startswith("CA")]
    rest = [row(f, "other") for f in base if not (f.geography or "").upper().startswith("CA")]
    return own + sorted(ca, key=lambda r: r["name"]) + sorted(rest, key=lambda r: r["name"])


@app.post("/projects/{project_id}/materials")
def add_material(project_id: str, body: NewMaterial) -> dict:
    from datetime import date as _date

    from ecarbon.carbon.user_factors import user_factor

    p = _own(project_id)
    try:
        f = user_factor(
            body.name, body.declared_unit, body.gwp_value,
            source=f"Entered by you: {body.source}".strip(),
            density_kg_m3=body.density_kg_m3, epd_id=body.epd_id,
            valid_to=_date.fromisoformat(body.valid_to) if body.valid_to else None,
            category=body.category,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    p.user_factors[f.factor_id] = f
    return {"factor_id": f.factor_id, "name": f.name}


class Scenario(BaseModel):
    swaps: dict[str, str] = Field(default_factory=dict, description="line id -> material swapped to")
    picks: dict[str, str] = Field(default_factory=dict, description="'<tag>-<category>' -> factor id")


def _spec(project_id: str) -> dict:
    """The user's specification, priced: every swap and choice with its delta."""
    p = _get(project_id)
    sc = p.scenario
    rows = []
    for sw in get_substitutions(project_id):
        if sc["swaps"].get(sw.line_id) == sw.to_material:
            rows.append({
                "kind": "swap", "ref": sw.line_id, "from": sw.from_material,
                "to": sw.to_material, "delta_kg_co2e": sw.delta_kg_co2e,
            })
    for c in get_unspecified(project_id):
        fid = sc["picks"].get(f"{c.assembly_tag}-{c.category}")
        o = next((o for o in c.options if o.factor_id == fid), None)
        if o:
            rows.append({
                "kind": "choice", "ref": f"{c.assembly_tag} {c.category}",
                "from": f"placeholder ({c.drawing_says})", "to": o.name,
                "delta_kg_co2e": o.kg_co2e,
            })
    base = p.carbon.total_kg_co2e
    return {
        "swaps": sc["swaps"], "picks": sc["picks"], "rows": rows,
        "counted_kg_co2e": base,
        "spec_kg_co2e": round(base + sum(r["delta_kg_co2e"] for r in rows), 2),
    }


@app.get("/projects/{project_id}/scenario")
def get_scenario(project_id: str) -> dict:
    return _spec(project_id)


@app.post("/projects/{project_id}/scenario")
def set_scenario(project_id: str, body: Scenario) -> dict:
    p = _own(project_id)
    p.scenario = {"swaps": dict(body.swaps), "picks": dict(body.picks)}
    return _spec(project_id)


# -- partitions on the plan, one wall at a time (UX session, 25 Nov) ---------

_WALLS: dict[str, dict] = {}
_WALL_NOTE = "stated: partition walls excluded on the plan"


def _walls(project_id: str) -> dict:
    """Every measured partition wall with an id, its rectangle and its length.

    Each rectangle the measurement kept is one wall. Its length is its share
    of the run measured on that sheet, by the rectangle's long side, so the
    walls of a sheet sum exactly to the length the bill used.
    """
    if project_id in _WALLS:
        return _WALLS[project_id]
    import pymupdf

    from ecarbon.geometry.partitions import partitions_for

    p = _get(project_id)
    design = getattr(p, "design", None) or _catalogue().get(project_id)
    out = {"pages": [], "total_m": 0.0}
    if design is None:
        return out
    try:
        measured = partitions_for(design)
    except Exception:
        measured = None
    if measured is None or not measured.runs:
        _WALLS[project_id] = out
        return out
    doc = pymupdf.open(design.drawings_pdf)
    try:
        for run in measured.runs:
            longs = [max(r[2] - r[0], r[3] - r[1]) for r in run.rects]
            tot = sum(longs) or 1.0
            order = sorted(range(len(run.rects)), key=lambda i: (round(run.rects[i][1]), run.rects[i][0]))
            page = doc[run.page]
            out["pages"].append({
                "page": run.page, "sheet_no": run.sheet,
                "page_width": page.rect.width, "page_height": page.rect.height,
                "length_m": run.length_m,
                "walls": [
                    {"id": f"p{run.page}-w{n}", "rect": list(run.rects[i]),
                     "length_m": round(run.length_m * longs[i] / tot, 3)}
                    for n, i in enumerate(order)
                ],
            })
    finally:
        doc.close()
    out["total_m"] = round(sum(pg["length_m"] for pg in out["pages"]), 2)
    _WALLS[project_id] = out
    return out


def _partition_lines(p) -> list:
    """The partition lines a wall exclusion scales: the measured ones only. A
    partition area assumed from the floor area has no walls to exclude."""
    return [
        ln for ln in p.takeoff.lines
        if ln.id.startswith("ln-interior-partition") and ln.confidence.value != "assumed"
    ]


@app.get("/projects/{project_id}/partitions")
def get_partitions(project_id: str) -> dict:
    p = _get(project_id)
    w = _walls(project_id)
    excluded = p.excluded_walls
    lengths = {wall["id"]: wall["length_m"] for pg in w["pages"] for wall in pg["walls"]}
    counted = sum(v for k, v in lengths.items() if k not in excluded)
    return {
        "pages": [
            {**pg, "walls": [{**wall, "excluded": wall["id"] in excluded} for wall in pg["walls"]]}
            for pg in w["pages"]
        ],
        "n_walls": len(lengths),
        "n_counted": sum(1 for k in lengths if k not in excluded),
        "total_m": w["total_m"],
        "counted_m": round(counted, 2),
        "editable": bool(lengths) and bool(_partition_lines(p)),
    }


class WallChoice(BaseModel):
    excluded: list[str] = Field(default_factory=list, description="wall ids to leave out")


@app.post("/projects/{project_id}/partitions", response_model=CarbonResult)
def set_partitions(project_id: str, body: WallChoice) -> CarbonResult:
    """Leave walls out (or put them back): every measured partition line is
    scaled by the share of the measured length still counted, and says so."""
    p = _own(project_id)
    w = _walls(project_id)
    lengths = {wall["id"]: wall["length_m"] for pg in w["pages"] for wall in pg["walls"]}
    unknown = [x for x in body.excluded if x not in lengths]
    if unknown:
        raise HTTPException(404, f"no partition wall {unknown[0]!r}")
    lines = _partition_lines(p)
    if not lines:
        raise HTTPException(409, "the partitions here are estimated from the floor area, not measured wall by wall")
    p.excluded_walls = set(body.excluded)
    total = sum(lengths.values()) or 1.0
    kept = total - sum(lengths[x] for x in p.excluded_walls)
    share = kept / total
    for ln in lines:
        mine = (ln.override_note or "").startswith(_WALL_NOTE)
        if not p.excluded_walls:
            if mine:
                ln.user_override, ln.override_note = None, None
            continue
        if ln.user_override is not None and not mine:
            continue  # a quantity the user typed wins over the wall count
        ln.user_override = round(ln.quantity * share, 4)
        ln.override_note = (
            f"{_WALL_NOTE}: {len(p.excluded_walls)} of {len(lengths)} walls left out, "
            f"{kept:.1f} of {total:.1f} m counted, so {ln.quantity:g} x {share:.3f}"
        )
    p.recompute()
    return p.carbon


@app.get("/materials/template.csv", response_class=PlainTextResponse)
def material_template() -> PlainTextResponse:
    from ecarbon.carbon.user_factors import template_csv

    return PlainTextResponse(
        template_csv(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="material-library-template.csv"'},
    )


@app.post("/projects/{project_id}/materials/upload")
async def upload_materials(project_id: str, file: UploadFile = File(...)) -> dict:  # noqa: B008
    """The builder's own list of materials they can buy, with their factors."""
    from ecarbon.carbon.user_factors import read_material_list

    p = _own(project_id)
    content = await file.read()
    if len(content) > 5_000_000:
        raise HTTPException(413, "a material list over 5 MB is not a list")
    added, errors = read_material_list(content, file.filename or "materials.csv")
    for f in added:
        p.user_factors[f.factor_id] = f
    if added:
        p.library_files.append(file.filename or "materials.csv")
    return {"added": [f.name for f in added], "errors": errors}


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
            # In the factor's unit (m3, kg, ...), as the line was calculated:
            # the takeoff quantity is in m2 for a wall billed by area.
            from ecarbon.carbon.calc_trace import explain

            conv = explain(p.takeoff.line(cl.line_id), cl).converted_quantity or cl.quantity
            if src.declared_unit.strip().lower() != dst.declared_unit.strip().lower():
                continue
            delta = conv * (dst.gwp_value - src.gwp_value)
            out.append(
                Substitution(
                    line_id=cl.line_id,
                    from_material=src.name,
                    to_material=dst.name,
                    to_factor_id=dst.factor_id,
                    delta_kg_co2e=round(delta, 1),
                    pct_of_total=round(100 * delta / p.carbon.total_kg_co2e, 1)
                    if p.carbon.total_kg_co2e
                    else 0.0,
                )
            )

    # The builder's own materials first: a swap they can actually buy. Offered
    # against lines whose factor is in the same category and declared unit.
    cats = _FACTORS.factor_categories()
    own: list[Substitution] = []
    for dst in p.user_factors.values():
        want = ((dst.attribution or "").removeprefix("category: ") or "").lower()
        for cl in p.carbon.lines:
            if not cl.is_counted or not cl.factor or cl.factor.factor_id == dst.factor_id:
                continue
            if cl.factor.declared_unit.strip().lower() != dst.declared_unit:
                continue
            have = f"{cats.get(cl.factor.factor_id, '')} {cl.factor.name}".lower()
            if not want or want not in have:
                continue
            from ecarbon.carbon.calc_trace import explain

            conv = explain(p.takeoff.line(cl.line_id), cl).converted_quantity or cl.quantity
            delta = conv * (dst.gwp_value - cl.factor.gwp_value)
            own.append(Substitution(
                line_id=cl.line_id,
                from_material=cl.factor.name,
                to_material=f"{dst.name} (from your library)",
                to_factor_id=dst.factor_id,
                delta_kg_co2e=round(delta, 1),
                pct_of_total=round(100 * delta / p.carbon.total_kg_co2e, 1) if p.carbon.total_kg_co2e else 0.0,
            ))
    out.sort(key=lambda s: s.delta_kg_co2e)  # biggest saving first
    own.sort(key=lambda s: s.delta_kg_co2e)
    return own + out


@app.get("/projects/{project_id}/compare/{other_id}")
def compare_projects(project_id: str, other_id: str) -> dict:
    """Line-by-line carbon delta from one project to another.

    Meant for a revision against the set it revises -- upload the new issue,
    compare it with the old -- where line ids line up because the same
    assemblies produce them. Both sides use their effective quantities, so an
    estimator's overrides carry into the comparison rather than being undone.
    """
    from ecarbon.takeoff.variants import compute_variant_delta

    base, other = _get(project_id), _get(other_id)
    return compute_variant_delta(base.takeoff, other.takeoff, _FACTORS).to_dict()


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
        takeoff_csv(p.takeoff, p.carbon, p.geography, header=True, chosen=p.material_edits, spec=_spec(project_id)),
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
    from ecarbon.carbon.calc_trace import explain_all

    return HTMLResponse(report_html(
        p.takeoff, p.carbon, get_unspecified(project_id),
        traces=explain_all(p.takeoff, p.carbon, p.material_edits), spec=_spec(project_id),
    ))


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
    _visible(project_id)
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

    key = (project_id, line_id)
    regions = _TRACE.get(key)
    if regions is None:
        regions = trace_line(_design_for(project_id), p.takeoff, line_id)
        _TRACE[key] = regions
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
def get_trace_image(
    project_id: str,
    line_id: str,
    page: int,
    dpi: int = 110,
    highlight: bool = True,
):
    """The source page as a PNG with the measured regions outlined.

    The drawings are licence-restricted: CMHC forbids redistributing them, so
    this renders for the person running the tool and the service must not be
    exposed publicly with a catalogue attached.
    """
    from fastapi.responses import Response

    from ecarbon.trace import render_page, trace_line

    p = _get(project_id)
    design = _design_for(project_id)
    cached = _TRACE.get((project_id, line_id))
    if cached is None:
        cached = trace_line(design, p.takeoff, line_id)
        _TRACE[(project_id, line_id)] = cached
    regions = [r for r in cached if r.page == page]
    if not regions:
        raise HTTPException(404, f"line {line_id!r} does not trace to page {page}")
    # The interface overlays the regions itself as SVG, which stays crisp at
    # any zoom and can be animated. Drawing them into the raster as well would
    # double every outline, so a client that draws its own asks for a clean
    # sheet. Server-side drawing stays for anything fetching the URL directly.
    rects = [rect for r in regions for rect in r.rects] if highlight else []
    dpi = max(40, min(dpi, 400))
    png_key = (project_id, line_id, page, dpi, highlight)
    png = _SHEET_PNG.get(png_key)
    if png is None:
        try:
            png = render_page(design, page, rects, dpi=dpi)
        except IndexError as exc:
            raise HTTPException(404, str(exc)) from None
        # Bounded, because each page is about a megabyte and a long session
        # would otherwise hold every sheet anyone pressed.
        if len(_SHEET_PNG) > 24:
            _SHEET_PNG.clear()
        _SHEET_PNG[png_key] = png
    return Response(content=png, media_type="image/png")


# -- helping it read: user-stated scale, outline and heights (C2) ----------


class PageOut(BaseModel):
    """One page of the drawings, for the "Help it read this" viewer."""

    page: int
    sheet_no: str | None = None
    title: str | None = None
    sheet_type: str
    readable: bool
    width: float = Field(description="page width in PDF points, as rendered")
    height: float = Field(description="page height in PDF points, as rendered")
    # Real mm per PDF point: one the user stated wins over one read off the
    # sheet. None when neither exists, so a click cannot become a length yet.
    scale_mm_per_pt: float | None = None
    scale_stated: bool = False
    # True when the scale is only an estimate from the sheet's own dimensions
    # (a standard ratio, not corroborated). Good enough for a person to click
    # levels against and check the result; not trusted by extraction.
    scale_estimated: bool = False
    image_url: str


@app.get("/projects/{project_id}/pages", response_model=list[PageOut])
def get_pages(project_id: str) -> list[PageOut]:
    """Every page, so the user can pick the one to help with."""
    import pymupdf

    p = _get(project_id)
    design = _design_for_any(project_id, p)
    info = {s.page: s for s in p.takeoff.sheets}
    stated = dict(getattr(p.overrides, "scale_mm_per_pt", {}) or {})
    from ecarbon.geometry.scale import calibrate

    out = []
    doc = pymupdf.open(design.drawings_pdf)
    try:
        for i, page in enumerate(doc):
            s = info.get(i)
            scale = stated.get(i) or getattr(s, "scale", None)
            estimated = False
            kind = getattr(getattr(s, "sheet_type", None), "value", "unknown")
            if scale is None and kind in ("section", "elevation"):
                try:
                    est = calibrate(page)
                    # Whole-building sections are drawn between about 1:25
                    # and 1:200 (1:50, 1:100, 1/4" and 1/8" = 1'-0"); outside
                    # that, the estimate is a detail sheet or a misread.
                    if est.mm_per_pt and est.is_standard and 25 <= (est.ratio or 0) <= 200:
                        scale, estimated = est.mm_per_pt, True
                except Exception:
                    pass
            out.append(
                PageOut(
                    page=i,
                    sheet_no=getattr(s, "sheet_no", None),
                    title=getattr(s, "title", None),
                    sheet_type=getattr(getattr(s, "sheet_type", None), "value", "unknown"),
                    readable=getattr(s, "readable", True),
                    width=round(page.rect.width, 2),
                    height=round(page.rect.height, 2),
                    scale_mm_per_pt=scale,
                    scale_stated=i in stated,
                    scale_estimated=estimated,
                    image_url=f"/projects/{project_id}/pages/{i}.png",
                )
            )
    finally:
        doc.close()
    return out


@app.get("/projects/{project_id}/pages/{page}.png")
def get_page_image(project_id: str, page: int, dpi: int = 110):
    """Any page as a PNG, without highlights.

    The trace image only serves pages a line traces to; this one serves any,
    because the pages that most need help are exactly the ones nothing traced.
    Same licence caveat as the trace image: for the person running the tool.
    """
    from fastapi.responses import Response

    from ecarbon.trace import render_page

    p = _get(project_id)
    design = _design_for_any(project_id, p)
    dpi = max(8, min(dpi, 300))
    # Thumbnails are a few kilobytes and a set has dozens of pages, so they
    # get their own, larger cache rather than evicting the full-size sheets.
    store = _THUMB_PNG if dpi <= 20 else _SHEET_PNG
    key = (project_id, "__page__", page, dpi, False)
    png = store.get(key)
    if png is None:
        try:
            png = render_page(design, page, [], dpi=dpi)
        except IndexError as exc:
            raise HTTPException(404, str(exc)) from None
        if len(store) > (400 if store is _THUMB_PNG else 24):
            store.clear()
        store[key] = png
    return Response(content=png, media_type="image/png")


class Calibrate(BaseModel):
    """One thing the user can see on the drawing and the tool could not read.

    Exactly one of: a known dimension (`page`, `p1`, `p2`, `length`), a traced
    outline (`page`, `corners`), storey heights, or `clear`. Points are in PDF
    points on the rendered page. Lengths take `7160`, `7.16 m` or `23'-6"`.
    """

    page: int | None = None
    p1: tuple[float, float] | None = None
    p2: tuple[float, float] | None = None
    length: str | float | None = None
    corners: list[tuple[float, float]] | None = None
    storey_heights: list[str | float] | None = None
    clear: bool = False


class CalibrateOut(BaseModel):
    carbon: CarbonResult
    gaps: list[Gap]
    lines: int
    stated: dict


def _design_for_any(project_id: str, p: Project):
    design = getattr(p, "design", None)
    return design if design is not None else _design_for(project_id)


@app.post("/projects/{project_id}/calibrate", response_model=CalibrateOut)
def calibrate_project(project_id: str, body: Calibrate) -> CalibrateOut:
    """Rebuild the takeoff with what the user stated, in their workspace only.

    Corrections already made to individual quantities are carried across the
    rebuild, so helping it read one sheet does not undo work on another.
    """
    from ecarbon.takeoff.builder import build_takeoff
    from ecarbon.takeoff.overrides import (
        Overrides,
        parse_length_mm,
        scale_from_points,
    )

    p = _own(project_id)
    design = _design_for_any(project_id, p)
    current = p.overrides if p.overrides is not None else Overrides()
    ov = Overrides(
        scale_mm_per_pt=dict(current.scale_mm_per_pt),
        footprint=current.footprint,
        storey_heights_m=current.storey_heights_m,
        said=dict(current.said),
    )
    try:
        if body.clear:
            ov = Overrides()
        elif body.corners is not None:
            if body.page is None:
                raise ValueError("say which page the outline is on")
            ov.footprint = (body.page, [tuple(c) for c in body.corners])
            ov.said["footprint"] = (
                f"the outline you traced on page {body.page + 1} "
                f"({len(body.corners)} corners)"
            )
        elif body.p1 is not None and body.p2 is not None and body.length is not None:
            if body.page is None:
                raise ValueError("say which page the dimension is on")
            mm = parse_length_mm(body.length)
            ov.scale_mm_per_pt[body.page] = scale_from_points(body.p1, body.p2, mm)
            ov.said["scale"] = f"the scale you set on page {body.page + 1} ({body.length} between two points)"
        elif body.storey_heights:
            hs = [parse_length_mm(h) / 1000.0 for h in body.storey_heights]
            ov.storey_heights_m = hs
            ov.said["heights"] = "storey heights you typed (" + ", ".join(
                str(h) for h in body.storey_heights
            ) + ")"
        else:
            raise ValueError("nothing to apply: give a dimension, an outline, heights, or clear")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

    kept = {ln.id: (ln.user_override, ln.override_note) for ln in p.takeoff.lines if ln.user_override is not None}
    facts = p.takeoff.project.model_copy(deep=True)
    try:
        with _BUILD_LOCK:
            takeoff = build_takeoff(design, facts, trust_stated_gfa=True, overrides=ov)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    for ln in takeoff.lines:
        if ln.id in kept:
            ln.user_override, ln.override_note = kept[ln.id]
    p.takeoff = takeoff
    p.overrides = None if ov.empty else ov
    p.recompute()
    # Traces were computed against the old takeoff.
    for key in [k for k in _TRACE if k[0] == project_id]:
        _TRACE.pop(key, None)
    return CalibrateOut(
        carbon=p.carbon, gaps=p.takeoff.gaps, lines=len(p.takeoff.lines), stated=ov.to_dict()
    )


# -- whose carbon factors (region) -----------------------------------------


class RegionOption(BaseModel):
    geography: str | None
    label: str
    n_factors: int = Field(description="factors the store holds for this country")


class RegionOut(BaseModel):
    geography: str | None
    label: str
    source: str = Field(description="chosen | title block | jurisdiction | default")
    options: list[RegionOption]
    # Set when the project is outside Canada: the factors are validated for
    # Canada only (UX session, 25 Nov), so a figure elsewhere says so.
    note: str | None = None


class SetRegion(BaseModel):
    geography: str | None = None


def _region_out(p: Project) -> RegionOut:
    from collections import Counter

    from ecarbon.carbon.region import _CA_PROVINCES, label_of

    # Canada only, by province: a province's own factors where the store has
    # them (concrete in AB, plywood and OSB in BC), Canada's otherwise.
    geos = Counter((f.geography or "").upper() for f in _FACTORS.list_factors())
    national = geos.get("CA", 0)
    options = [RegionOption(geography=None, label=label_of(None), n_factors=national)]
    for code in sorted(_CA_PROVINCES, key=lambda c: _CA_PROVINCES[c]):
        geo = f"CA-{code}"
        options.append(RegionOption(geography=geo, label=label_of(geo), n_factors=national + geos.get(geo, 0)))
    outside = bool(p.geography) and not p.geography.upper().startswith("CA")
    return RegionOut(
        geography=p.geography, label=label_of(p.geography), source=p.region_source, options=options,
        note=(
            f"{label_of(p.geography)} is outside Canada. The factors and method are validated "
            f"for Canada only; treat this figure as indicative."
            if outside else None
        ),
    )


@app.get("/projects/{project_id}/region", response_model=RegionOut)
def get_region(project_id: str) -> RegionOut:
    """Whose carbon factors this project is priced with, and how that was decided."""
    return _region_out(_get(project_id))


@app.post("/projects/{project_id}/region", response_model=RegionOut)
def set_region(project_id: str, body: SetRegion) -> RegionOut:
    """Price this project with another region's factors, in this workspace only.

    Materials with no factor for that region keep the default one, and their
    lines say so with a wider range.
    """
    from ecarbon.carbon.region import from_text

    geo = body.geography
    if geo is not None:
        geo = geo.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}(-[A-Z]{2,3})?", geo):
            parsed = from_text(body.geography)
            if parsed is None:
                raise HTTPException(422, f"could not read {body.geography!r} as a region")
            geo = parsed
    p = _own(project_id)
    p.geography = geo
    p.region_source = "chosen" if geo else "default"
    p.recompute()
    return _region_out(p)


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

    if project_id in _UNSPECIFIED:
        return _UNSPECIFIED[project_id]

    p = _get(project_id)
    design = getattr(p, "design", None) or _catalogue().get(project_id)
    if design is None:
        _UNSPECIFIED[project_id] = []
        return []
    assemblies, _refused = assemblies_for(design)
    out = [
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
    _UNSPECIFIED[project_id] = out
    return out


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
    file: UploadFile | None = File(None),  # noqa: B008
    # Several PDFs as one set: how builders deliver (floor layout, roof,
    # foundation, details, schedule). Joined by config.folder_design.
    files: list[UploadFile] | None = File(None),  # noqa: B008
    name: str | None = Form(None),  # noqa: B008
    gfa_m2: float | None = Form(None),  # noqa: B008
    gfa_basis: str | None = Form(None),  # noqa: B008
    storeys: int | None = Form(None),  # noqa: B008
    units: int | None = Form(None),  # noqa: B008
    jurisdiction: str | None = Form(None),  # noqa: B008
    background: bool = False,
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

    With `?background=true` it answers at once with a job id, and
    `GET /uploads/{job}` reports each stage as it really finishes -- the pages
    found, sheets classified, footprint measured -- so the twenty seconds the
    drawings take to read show what is being read instead of a spinner.
    """
    from ecarbon.config import Design
    from ecarbon.models import ProjectFacts
    from ecarbon.takeoff.builder import build_takeoff

    parts = [f for f in ([file] if file is not None else []) + list(files or []) if f is not None]
    if not parts:
        raise HTTPException(422, "no plan set: send one PDF as `file`, or several as `files`")
    blobs: list[tuple[str, bytes]] = []
    total = 0
    for part in parts:
        raw = await part.read(MAX_UPLOAD_BYTES + 1)
        total += len(raw)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(
                413, f"plan set larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
            )
        if not raw.startswith(b"%PDF-"):
            raise HTTPException(
                415,
                f"{part.filename or 'a file'} is not a PDF. This pipeline reads vector PDF "
                "drawing sets; a scan or an image export carries no geometry to measure.",
            )
        blobs.append((part.filename or "plan-set.pdf", raw))

    def _safe(n: str) -> str:
        stem = Path(n).stem or "plan-set"
        return re.sub(r"[^A-Za-z0-9._-]+", "-", stem)[:80].strip("-") or "plan-set"

    safe = _safe(name or blobs[0][0]) if len(blobs) > 1 else _safe(blobs[0][0])
    project_id = f"upload-{uuid.uuid4().hex[:8]}-{safe}"

    # Its own empty directory, so nothing in the set can land beside another
    # upload or anything we ship.
    home = _upload_dir() / project_id
    home.mkdir(parents=True, exist_ok=False)
    if len(blobs) == 1:
        pdf = home / f"{safe}.pdf"
        pdf.write_bytes(blobs[0][1])
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
    else:
        from ecarbon.config import folder_design

        used: set[str] = set()
        for fname, raw in blobs:
            base = _safe(fname)
            n, k = base, 2
            while n in used:
                n, k = f"{base}-{k}", k + 1
            used.add(n)
            (home / f"{n}.pdf").write_bytes(raw)
        try:
            design = folder_design(home)
        except Exception as exc:
            raise HTTPException(422, f"could not join these files into one set: {exc}") from exc
        pdf = design.drawings_pdf
    facts = ProjectFacts(
        name=name or safe,
        jurisdiction=jurisdiction,
        gfa_m2=gfa_m2,
        gfa_basis=gfa_basis or "gross",
        storeys=storeys,
        units=units,
    )
    owner = _WORKSPACE.get()

    def run(tell) -> dict[str, object]:
        try:
            import pymupdf

            with pymupdf.open(pdf) as doc:
                tell(
                    "pages",
                    f"{doc.page_count} pages"
                    + (f" across {len(blobs)} files" if len(blobs) > 1 else ""),
                )
            with _BUILD_LOCK:
                takeoff = build_takeoff(
                    design, facts, trust_stated_gfa=gfa_m2 is not None, progress=tell
                )
        except Exception as exc:
            raise HTTPException(
                422,
                f"could not read this plan set: {exc}. Nothing partial is stored.",
            ) from exc
        from ecarbon.carbon.region import detect

        region = detect(design, jurisdiction)
        project = Project(
            id=project_id,
            takeoff=takeoff,
            design=design,
            geography=region.geography,
            region_source=region.source,
        )
        total = project.carbon.total_kg_co2e
        tell("carbon", f"{total:,.0f} kgCO2e across {len(takeoff.lines)} lines")
        _PROJECTS[project_id] = project
        _OWNER[project_id] = owner
        return {
            "id": project_id,
            "n_lines": len(takeoff.lines),
            "n_sheets": len(takeoff.sheets),
            "n_gaps": len(takeoff.gaps),
            "total_kg_co2e": total,
        }

    if not background:
        return run(lambda stage, detail: None)

    job_id = uuid.uuid4().hex
    job: dict[str, object] = {"owner": owner, "stages": [], "result": None, "error": None}
    with _JOBS_LOCK:
        while len(_JOBS) >= _MAX_JOBS:
            _JOBS.pop(next(iter(_JOBS)))
        _JOBS[job_id] = job

    def work() -> None:
        try:
            job["result"] = run(lambda stage, detail: job["stages"].append([stage, detail]))
        except HTTPException as exc:
            job["error"] = exc.detail
        except Exception as exc:  # anything else still ends the job, with its reason
            job["error"] = f"could not read this plan set: {exc}. Nothing partial is stored."

    threading.Thread(target=work, daemon=True).start()
    return {"job": job_id}


# Upload jobs in progress or recently finished. In memory like everything else
# here, and bounded so abandoned uploads cannot grow it.
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 64


@app.get("/uploads/{job_id}")
def upload_status(job_id: str) -> dict[str, object]:
    """The stages an upload has finished so far, then its project or its error."""
    job = _JOBS.get(job_id)
    # Another workspace's job is as absent as one that never existed.
    if job is None or job["owner"] != _WORKSPACE.get():
        raise HTTPException(404, "no such upload")
    return {
        "stages": list(job["stages"]),
        "done": job["result"] is not None or job["error"] is not None,
        "result": job["result"],
        "error": job["error"],
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

    expected = base64.b64encode(
        f"{_AUTH_USER}:{_AUTH_PASSWORD}".encode()
    ).decode()

    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        supplied = header[6:]
    else:
        # A rendered sheet is an <img src>, which cannot carry a header, so
        # the same credential may ride the query string instead. Same origin,
        # same gate, and it never leaves the page that already has it.
        supplied = request.query_params.get("auth", "")
    # Compared in constant time so the comparison itself leaks nothing.
    if not secrets.compare_digest(supplied, expected):
        return Response(
            status_code=401,
            content="Credentials required.",
            headers={"WWW-Authenticate": 'Basic realm="ecarbon"'},
        )
    return await call_next(request)


# -- the takeoff, in three dimensions ---------------------------------------


class MassingWall(BaseModel):
    """One measured partition, in metres relative to the footprint."""

    x: float
    y: float
    w: float
    d: float
    storey: int


class Massing(BaseModel):
    """What the drawings were understood to describe, as geometry.

    Not a render of a building: every figure here is one this pipeline
    measured, so a wrong footprint is a visibly wrong shape and partitions
    that over-detect are walls standing where no walls are. That is the point
    of showing it -- the uncertainty becomes something you can see rather than
    something the gap report asserts.
    """

    width_m: float
    depth_m: float
    storey_heights_m: list[float]
    # The section's TOP OF ROOF datum above the top storey's datum: how high
    # the ridge stands. Measured; the roof's shape between eave and ridge is
    # not, so a viewer drawing one must say it is illustrative. None when the
    # sections carry no roof datum, or one that does not read as a pitch.
    roof_rise_m: float | None = None
    # What stands under the slab, as the bill has it: a grade beam, a
    # foundation wall on its footing, or a thickened slab edge. Depth below
    # the slab and a label; None draws nothing rather than a made-up footing.
    foundation_depth_m: float | None = None
    foundation_label: str | None = None
    walls: list[MassingWall] = Field(default_factory=list)
    carbon_by_class: dict[str, float] = Field(default_factory=dict)
    note: str


def _foundation(lines) -> tuple[float | None, str | None]:
    """(depth below the slab, label) of the perimeter foundation in the bill."""
    import re as _re

    ids = {ln.id: ln for ln in lines}
    if any(i.startswith("ln-grade-beam") for i in ids):
        return 1.2, "Grade beam on the perimeter, below grade"
    wall = ids.get("ln-foundation-wall")
    if wall is not None:
        m = _re.search(r"x ([\d.]+) m over", wall.description or "")
        h = float(m.group(1)) if m else 1.4
        foot = 0.2 if any(i.startswith("ln-strip-footing") for i in ids) else 0.0
        tag = " (assumed)" if wall.confidence.value == "assumed" else ""
        return round(h + foot, 2), f"Foundation wall on a strip footing{tag}, {h + foot:.2f} m deep"
    if "ln-thickened-edge" in ids:
        return 0.3, "Thickened slab edge (assumed)"
    if any(i.startswith("ln-strip-footing") for i in ids):
        return 0.2, "Strip footing"
    return None, None


def _roof_rise(levels, heights: list[float]) -> float | None:
    """Ridge height above the top storey's datum, from the section's roof level."""
    roof = getattr(levels, "roof_level_m", None) if levels else None
    floors = levels.floors if levels else []
    if roof is None or not floors:
        return None
    rise = roof - floors[0].elevation_m - sum(heights)
    return round(rise, 3) if 0.3 <= rise <= 6.0 else None


@app.get("/projects/{project_id}/massing", response_model=Massing | None)
def get_massing(project_id: str) -> Massing | None:
    """Footprint, storey datums and measured partitions, in metres.

    Partition rectangles are stored in PDF page coordinates and the footprint
    keeps no origin, so there is no page-to-building transform to apply. They
    are normalised against their own extent instead, which is sound here for a
    checkable reason: on AB_Fourplex_01 the rect extent is 398 x 1248 pt, a
    ratio of 0.319, against a measured footprint of 7.0 x 22.0 m, a ratio of
    0.318. The partitions span the building, so their bounds are its bounds.

    Returned as None rather than guessed when the footprint or the storey
    heights are missing, which is most of the catalogue outside Alberta.
    """
    p = _get(project_id)
    # A workspace that stated a scale, outline or heights sees its own
    # building; the shared cache holds only the drawings-alone answer.
    stated = getattr(p, "overrides", None)
    stated = stated if stated is not None and not stated.empty else None
    if stated is None and project_id in _MASSING:
        return _MASSING[project_id]

    design = getattr(p, "design", None) or _catalogue().get(project_id)
    if design is None:
        return None

    from ecarbon.geometry.partitions import partitions_for
    from ecarbon.takeoff.builder import gather

    try:
        facts = p.takeoff.project
        expected = (
            facts.gfa_m2 / facts.storeys if facts.gfa_m2 and facts.storeys else None
        )
        inputs, _sheets, _gaps = gather(design, expected, overrides=stated)
    except Exception:
        if stated is None:
            _MASSING[project_id] = None
        return None

    footprint = inputs.footprint
    heights = inputs.heights.storey_heights_m() if inputs.heights else []
    if footprint is None or not heights:
        _MASSING[project_id] = None
        return None

    walls: list[MassingWall] = []
    try:
        measured = partitions_for(design)
    except Exception:
        measured = None

    if measured and measured.runs:
        for storey, run in enumerate(measured.runs):
            if not run.rects:
                continue
            xs = [v for r in run.rects for v in (r[0], r[2])]
            ys = [v for r in run.rects for v in (r[1], r[3])]
            x0, x1 = min(xs), max(xs)
            y0, y1 = min(ys), max(ys)
            span_x = (x1 - x0) or 1.0
            span_y = (y1 - y0) or 1.0
            # The page's long axis is the building's long axis; orientation
            # follows from which span is larger rather than from an assumed
            # sheet rotation.
            flip = (span_x > span_y) != (footprint.width_m > footprint.depth_m)
            for r in run.rects:
                ax = (r[0] - x0) / span_x
                ay = (r[1] - y0) / span_y
                aw = (r[2] - r[0]) / span_x
                ad = (r[3] - r[1]) / span_y
                if flip:
                    ax, ay, aw, ad = ay, ax, ad, aw
                walls.append(
                    MassingWall(
                        x=round(ax * footprint.width_m, 3),
                        y=round(ay * footprint.depth_m, 3),
                        w=round(max(aw * footprint.width_m, 0.05), 3),
                        d=round(max(ad * footprint.depth_m, 0.05), 3),
                        storey=storey,
                    )
                )

    by_class: dict[str, float] = {}
    results = {c.line_id: c for c in p.carbon.lines}
    for line in p.takeoff.lines:
        result = results.get(line.id)
        if result is None or result.kg_co2e is None:
            continue
        key = line.element_class.value
        by_class[key] = round(by_class.get(key, 0.0) + result.kg_co2e, 1)

    result = Massing(
        width_m=round(footprint.width_m, 2),
        depth_m=round(footprint.depth_m, 2),
        storey_heights_m=[round(h, 3) for h in heights],
        roof_rise_m=_roof_rise(inputs.heights, heights),
        foundation_depth_m=_foundation(p.takeoff.lines)[0],
        foundation_label=_foundation(p.takeoff.lines)[1],
        walls=walls,
        carbon_by_class=by_class,
        note=(
            f"{footprint.width_m:.1f} x {footprint.depth_m:.1f} m measured from "
            f"the linework, {len(heights)} storeys from the section datums, and "
            f"{len(walls)} partition walls measured on the plans. Every surface "
            f"here is a quantity in the bill, so a wrong reading is a visibly "
            f"wrong shape rather than a number you would have to check."
        ),
    )
    if stated is None:
        _MASSING[project_id] = result
    return result


# -- accounts ---------------------------------------------------------------


class Credentials(BaseModel):
    username: str
    password: str


class SessionOut(BaseModel):
    token: str
    name: str
    guest: bool


_USERNAME = re.compile(r"^[a-z0-9_-]{3,32}$")


def _hash_password(password: str, salt: bytes) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"{salt.hex()}${digest.hex()}"


def _session(workspace: str) -> SessionOut:
    guest = workspace.startswith("g:")
    return SessionOut(
        token=_sign(workspace),
        name="Guest" if guest else workspace.split(":", 1)[1],
        guest=guest,
    )


@app.post("/auth/signup", response_model=SessionOut, status_code=201)
def signup(body: Credentials) -> SessionOut:
    name = body.username.strip().lower()
    if not _USERNAME.match(name):
        raise HTTPException(
            422, "Use 3 to 32 letters, numbers, dashes or underscores."
        )
    if len(body.password) < 6:
        raise HTTPException(422, "Use a password of at least 6 characters.")
    if name in _USERS:
        raise HTTPException(409, "That name is taken. Sign in instead?")
    _USERS[name] = _hash_password(body.password, secrets.token_bytes(16))
    return _session(f"u:{name}")


@app.post("/auth/login", response_model=SessionOut)
def login(body: Credentials) -> SessionOut:
    name = body.username.strip().lower()
    stored = _USERS.get(name)
    if stored is None:
        # Accounts live in memory; say so rather than "wrong password".
        raise HTTPException(
            401,
            "No account by that name on this server. Accounts clear when the "
            "server restarts, so you may need to create it again.",
        )
    salt_hex, _, _ = stored.partition("$")
    if not hmac.compare_digest(
        _hash_password(body.password, bytes.fromhex(salt_hex)), stored
    ):
        raise HTTPException(401, "That password does not match.")
    return _session(f"u:{name}")


@app.post("/auth/guest", response_model=SessionOut)
def guest() -> SessionOut:
    return _session(f"g:{secrets.token_hex(8)}")


@app.get("/auth/me", response_model=SessionOut | None)
def me() -> SessionOut | None:
    workspace = _WORKSPACE.get()
    return None if workspace == "public" else _session(workspace)


_COVER: dict[str, bytes | None] = {}


@app.get("/projects/{project_id}/cover.jpg")
def get_cover(project_id: str):
    """The rendering on the plan set's cover sheet, if it carries one.

    The showcase view stands the measured model in front of the building the
    drawings describe. Read from the PDF at request time, like every sheet
    render, so no image of a licence-restricted design enters the repository.
    A set without a cover rendering -- most uploads -- is a 404, and the
    interface draws its own backdrop instead of borrowing someone else's.
    """
    import pymupdf
    from fastapi.responses import Response

    if project_id not in _COVER:
        design = _design_for(project_id)
        jpg = None
        try:
            doc = pymupdf.open(design.drawings_pdf)
            try:
                # A photograph-sized raster, not a logo strip or a title-block
                # crest: at least a megapixel and no flatter than 2:1.
                best = None
                for img in doc[0].get_images(full=True):
                    w, h = img[2], img[3]
                    if w * h < 1_000_000 or max(w, h) > 2 * min(w, h):
                        continue
                    if best is None or w * h > best[2] * best[3]:
                        best = img
                if best is not None:
                    pix = pymupdf.Pixmap(doc, best[0])
                    if pix.alpha:
                        pix = pymupdf.Pixmap(pix, 0)
                    if pix.n > 3:
                        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                    while max(pix.width, pix.height) > 1600:
                        pix.shrink(1)
                    jpg = pix.tobytes("jpg", jpg_quality=82)
            finally:
                doc.close()
        except Exception:  # noqa: BLE001 -- a backdrop is never worth a 500
            jpg = None
        _COVER[project_id] = jpg
    jpg = _COVER[project_id]
    if jpg is None:
        raise HTTPException(404, "this plan set has no cover rendering")
    return Response(
        content=jpg,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


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


def _warm_catalogue() -> None:
    """Build the bundled designs in the background once the service is up.

    The first request for a design runs the whole pipeline -- about 23 s on a
    shared core -- and only then is the result cached. Leaving that to the
    first visitor means whoever opens the link does the waiting, which on a
    demo is the one thing worth spending idle CPU to avoid.

    It runs on a thread so the health check passes immediately instead of
    waiting on several builds, and failures are swallowed: a design that
    cannot be pre-built is simply built on request, exactly as before.
    """
    import threading

    def run() -> None:
        for key in _catalogue():
            try:
                _build(key)
            except Exception:
                continue

    threading.Thread(target=run, name="warm-catalogue", daemon=True).start()


@app.on_event("startup")
def _on_startup() -> None:
    """Pre-building is opt-in, and off by default, because it was measured.

    Enabled on a single shared core it made everything worse: the build is
    CPU-bound Python holding the GIL, so the event loop was starved and even
    /health intermittently timed out. Fly restarts machines whose health check
    fails, so an optimisation meant to save a visitor twenty seconds was
    instead putting the service into a restart loop. Turn it on with
    ECARBON_WARM=1 only where there is a core to spare for it.
    """
    if os.environ.get("ECARBON_WARM", "0") == "1":
        _warm_catalogue()
