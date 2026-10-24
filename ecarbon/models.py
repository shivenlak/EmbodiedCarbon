"""The frozen data contract between extraction (S) and carbon/UI (T).

Nothing downstream of extraction may invent fields. If a new field is needed,
change it here first, regenerate the fixture, and tell the other person --
that is the whole point of this module.

Two rules that the rubric scores directly:
  * Every quantity carries provenance (sheet + detail + bbox) and a confidence
    label (measured / inferred / assumed). See `TakeoffLine`.
  * Carbon results are a SEPARATE document keyed by line id, so recomputing
    carbon never mutates the takeoff. See `CarbonResult`.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0.0"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class Confidence(StrEnum):
    """Stage 2 requires every quantity to be labelled one of exactly these."""

    MEASURED = "measured"  # >=2 independent sources agreed
    INFERRED = "inferred"  # derived from one source + a documented rule
    ASSUMED = "assumed"  # no source; a default was applied


class Toolchain(StrEnum):
    """How a page was exported. Detected per PAGE, not per file -- a single
    drawings PDF concatenates several firms' exports (RESEARCH.md §4b)."""

    REVIT_TAGGED = "revit_tagged"  # /revit_metadata_* keys present
    AIA_LAYERED = "aia_layered"  # AIA-standard OCG layer names present
    FLATTENED = "flattened"  # vector + text, but no layers or metadata
    DISTILLER_OUTLINED = "distiller_outlined"  # text converted to outlines
    VECTORWORKS = "vectorworks"
    RASTER = "raster"  # scanned; not seen in the catalogue but possible
    UNKNOWN = "unknown"


class Discipline(StrEnum):
    ARCHITECTURAL = "A"
    STRUCTURAL = "S"
    MECHANICAL = "M"
    ELECTRICAL = "E"
    GENERAL = "G"
    CIVIL = "C"
    UNKNOWN = "?"


class SheetType(StrEnum):
    """Stage 1 must identify what the set contains."""

    TITLE = "title"
    COVER = "cover"
    SITE_PLAN = "site_plan"
    FLOOR_PLAN = "floor_plan"
    FOUNDATION_PLAN = "foundation_plan"
    ROOF_PLAN = "roof_plan"
    FRAMING_PLAN = "framing_plan"
    ELEVATION = "elevation"
    SECTION = "section"
    DETAIL = "detail"
    ASSEMBLY_SCHEDULE = "assembly_schedule"
    OPENING_SCHEDULE = "opening_schedule"
    SCHEDULE_OTHER = "schedule_other"
    SPECIFICATION = "specification"
    LEGEND = "legend"
    MECHANICAL = "mechanical"
    ELECTRICAL = "electrical"
    UNKNOWN = "unknown"


class ElementClass(StrEnum):
    """Build order follows carbon contribution (Kootenay guide, see docs/)."""

    SLAB_ON_GRADE = "slab_on_grade"
    FOOTING = "footing"
    FOUNDATION_WALL = "foundation_wall"
    EXTERIOR_WALL = "exterior_wall"
    INTERIOR_PARTITION = "interior_partition"
    PARTY_WALL = "party_wall"
    FLOOR_ASSEMBLY = "floor_assembly"
    ROOF_ASSEMBLY = "roof_assembly"
    WINDOW = "window"
    DOOR = "door"
    STAIR = "stair"
    CLADDING = "cladding"
    INSULATION = "insulation"
    OTHER = "other"


class Unit(StrEnum):
    M2 = "m2"
    M3 = "m3"
    M = "m"
    KG = "kg"
    EACH = "each"


class GapSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"  # a carbon-relevant quantity cannot be produced


class GapCode(StrEnum):
    """Stage 1: 'a missing section detail or illegible schedule must produce a
    reported gap, never a silent assumption.' Each code is user-facing."""

    PAGE_TEXT_UNREADABLE = "page_text_unreadable"
    SHEET_TITLE_UNKNOWN = "sheet_title_unknown"
    SCALE_NOT_FOUND = "scale_not_found"
    SCALE_SOURCES_DISAGREE = "scale_sources_disagree"
    SHEET_TYPE_MISSING = "sheet_type_missing"
    ASSEMBLY_SCHEDULE_MISSING = "assembly_schedule_missing"
    OPENING_SCHEDULE_MISSING = "opening_schedule_missing"
    SECTION_DETAIL_MISSING = "section_detail_missing"
    ASSEMBLY_TAG_UNRESOLVED = "assembly_tag_unresolved"
    STOREY_HEIGHT_UNKNOWN = "storey_height_unknown"
    NO_CARBON_FACTOR = "no_carbon_factor"
    MODULE_SCOPE_MISMATCH = "module_scope_mismatch"
    PROJECT_FACT_REQUIRED = "project_fact_required"
    GEOMETRY_AMBIGUOUS = "geometry_ambiguous"


class BasisSource(StrEnum):
    """Which independent signal supported a quantity. Confidence is a function
    of WHICH of these agreed -- see takeoff.confidence."""

    VECTOR_PATH = "vector_path"
    DIM_TEXT_METRIC = "dim_text_metric"
    DIM_TEXT_IMPERIAL = "dim_text_imperial"
    SCHEDULE = "schedule"
    SECTION_NOTE = "section_note"
    LAYER_NAME = "layer_name"
    REVIT_METADATA = "revit_metadata"
    STATED_TOTAL = "stated_total"
    HOT2000 = "hot2000"
    USER = "user"
    DEFAULT_RULE = "default_rule"


# --------------------------------------------------------------------------
# Takeoff document
# --------------------------------------------------------------------------


class ProjectFacts(BaseModel):
    """Stage 1 must prompt for facts that are not on the drawings."""

    name: str
    jurisdiction: str | None = None
    gfa_m2: float | None = None
    gfa_basis: Literal["gross", "conditioned", "unknown"] = "unknown"
    storeys: int | None = None
    units: int | None = None
    known_product_specs: dict[str, str] = Field(default_factory=dict)

    @property
    def intensity_denominator(self) -> float | None:
        return self.gfa_m2 if self.gfa_m2 and self.gfa_m2 > 0 else None


class SheetInfo(BaseModel):
    page: int = Field(ge=0, description="0-based page index in the PDF")
    sheet_no: str | None = None
    title: str | None = None
    discipline: Discipline = Discipline.UNKNOWN
    sheet_type: SheetType = SheetType.UNKNOWN
    toolchain: Toolchain = Toolchain.UNKNOWN
    readable: bool = True
    width_in: float | None = None
    height_in: float | None = None
    scale: float | None = Field(
        default=None, description="Real-world mm per PDF point. None if unknown."
    )
    scale_source: BasisSource | None = None
    classified_by: BasisSource | None = None
    layer_names: list[str] = Field(default_factory=list)
    n_paths: int = 0
    n_text: int = 0
    n_images: int = 0


class Gap(BaseModel):
    code: GapCode
    severity: GapSeverity
    message: str
    page: int | None = None
    sheet_no: str | None = None
    affects: list[str] = Field(default_factory=list, description="TakeoffLine ids")


class Provenance(BaseModel):
    """Criterion 2: 'every line traceable back to the sheet and detail it came
    from'. bbox powers click-to-trace."""

    page: int
    sheet_no: str | None = None
    detail: str | None = None
    bbox: tuple[float, float, float, float] | None = None


class Basis(BaseModel):
    sources: list[BasisSource] = Field(default_factory=list)
    agreement: float | None = Field(
        default=None,
        ge=0.0,
        description="Max relative spread between independent sources, e.g. 0.03 = 3%.",
    )
    note: str = ""


class TakeoffLine(BaseModel):
    id: str
    element_class: ElementClass
    quantity: float = Field(ge=0)
    unit: Unit
    confidence: Confidence
    basis: Basis = Field(default_factory=Basis)
    provenance: Provenance
    assembly_tag: str | None = Field(default=None, description="e.g. W2, F1, R2")
    material: str | None = Field(default=None, description="e.g. CMHC_Wood Framing")
    description: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    user_override: float | None = None
    override_note: str | None = None

    @property
    def effective_quantity(self) -> float:
        """What carbon is computed from. A human correction always wins."""
        return self.user_override if self.user_override is not None else self.quantity

    @property
    def is_overridden(self) -> bool:
        return self.user_override is not None

    @model_validator(mode="after")
    def _assumed_must_be_documented(self) -> TakeoffLine:
        # The scope: "Assumptions must be documented and viewable to the user."
        if self.confidence is Confidence.ASSUMED and not self.assumptions:
            raise ValueError(
                f"line {self.id!r} is 'assumed' but documents no assumption; "
                "the scope requires assumptions to be viewable"
            )
        return self


class TakeoffResult(BaseModel):
    schema_version: str = SCHEMA_VERSION
    project: ProjectFacts
    source_file: str
    sheets: list[SheetInfo] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    lines: list[TakeoffLine] = Field(default_factory=list)
    extracted_at: date | None = None
    duration_s: float | None = None

    @field_validator("lines")
    @classmethod
    def _unique_ids(cls, v: list[TakeoffLine]) -> list[TakeoffLine]:
        seen = set()
        for line in v:
            if line.id in seen:
                raise ValueError(f"duplicate TakeoffLine id {line.id!r}")
            seen.add(line.id)
        return v

    def line(self, line_id: str) -> TakeoffLine:
        for ln in self.lines:
            if ln.id == line_id:
                return ln
        raise KeyError(line_id)

    def by_confidence(self) -> dict[Confidence, int]:
        out = dict.fromkeys(Confidence, 0)
        for ln in self.lines:
            out[ln.confidence] += 1
        return out

    @property
    def readable_sheets(self) -> list[SheetInfo]:
        return [s for s in self.sheets if s.readable]

    @property
    def blocking_gaps(self) -> list[Gap]:
        return [g for g in self.gaps if g.severity is GapSeverity.BLOCKING]


# --------------------------------------------------------------------------
# Carbon document -- separate, keyed by line id
# --------------------------------------------------------------------------


class FactorRef(BaseModel):
    """Criterion 3: source, declared unit, validity, geography and data type
    must all stay visible to the user. This is the visible record."""

    factor_id: str
    name: str
    source: str
    source_id: str | None = None
    declared_unit: str
    gwp_value: float
    gwp_unit: str = "kgCO2e"
    modules: list[str] = Field(description="e.g. ['A1','A2','A3']")
    geography: str
    data_type: Literal["epd", "industry_avg", "generic"]
    valid_from: date | None = None
    valid_to: date | None = None
    uncertainty_pct: float | None = None
    attribution: str | None = None
    density_kg_m3: float | None = None

    @property
    def module_label(self) -> str:
        return "-".join([self.modules[0], self.modules[-1]]) if self.modules else "?"


class CarbonLine(BaseModel):
    line_id: str
    quantity: float
    unit: Unit
    factor: FactorRef | None = None
    kg_co2e: float | None = None
    conversion_note: str | None = None
    missing_reason: str | None = Field(
        default=None,
        description="Set when no factor was found. Such a line is reported and "
        "EXCLUDED from the total -- never silently zeroed.",
    )

    @model_validator(mode="after")
    def _factor_or_reason(self) -> CarbonLine:
        if self.factor is None and not self.missing_reason:
            raise ValueError(
                f"carbon line {self.line_id!r} has no factor and no missing_reason; "
                "the scope forbids silent substitution"
            )
        return self

    @property
    def is_counted(self) -> bool:
        return self.kg_co2e is not None and self.factor is not None


class Contribution(BaseModel):
    key: str
    kg_co2e: float
    pct_of_total: float


class CarbonResult(BaseModel):
    schema_version: str = SCHEMA_VERSION
    takeoff_source: str
    modules: list[str] = Field(
        default=["A1", "A2", "A3"],
        description="The module scope this total represents. Only like-for-like "
        "modules are summed; mixing raises in carbon.totals.",
    )
    total_kg_co2e: float
    intensity_kg_co2e_per_m2: float | None = None
    intensity_basis: Literal["gross", "conditioned", "unknown"] = "unknown"
    lines: list[CarbonLine] = Field(default_factory=list)
    by_assembly: list[Contribution] = Field(default_factory=list)
    by_material_category: list[Contribution] = Field(default_factory=list)
    uncounted_lines: list[str] = Field(
        default_factory=list, description="line ids with no factor -- shown to the user"
    )
    range_low_kg_co2e: float | None = None
    range_high_kg_co2e: float | None = None

    @property
    def coverage_pct(self) -> float:
        if not self.lines:
            return 0.0
        return 100.0 * sum(1 for ln in self.lines if ln.is_counted) / len(self.lines)
