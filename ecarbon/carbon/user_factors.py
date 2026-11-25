"""A project's own materials, on top of the shared factor store (UX, 25 Nov).

Practitioners asked to choose any material for any line, to type their own
factor with its source, and to upload the builder's list of materials they can
actually buy. All three land here:

- `ProjectFactors` wraps the shared store with the project's own factors and
  answers a line whose material was changed ("<material> => factor:<id>")
  with exactly the factor chosen;
- `user_factor` turns a typed or uploaded material into a `FactorRef`, labelled
  as the builder's own (data type "epd", geography "user", source "Builder
  library: <file>" or "Entered by you");
- `read_material_list` reads a CSV or XLSX in the template, row by row, with an
  error per bad row rather than failing the file.

The shared store is never written to, so one builder's materials are never
another visitor's.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date

from ecarbon.carbon.store import FactorProvider
from ecarbon.models import FactorRef

EDIT_MARK = " => factor:"

TEMPLATE_COLUMNS = [
    "name",
    "category",
    "declared_unit",
    "gwp_kgco2e_per_unit",
    "density_kg_m3",
    "source",
    "epd_id",
    "valid_to",
]
TEMPLATE_EXAMPLE = [
    "Mineral wool batt, R-22 (supplier X)",
    "insulation",
    "m3",
    "38.5",
    "40",
    "Supplier X product EPD",
    "EPD-XXX-0001",
    "2029-12-31",
]
UNITS = {"m3", "m2", "kg", "m", "each", "100m2"}
_HEADER_ALIASES = {
    "name": ("name", "material", "product"),
    "category": ("category", "type", "group"),
    "declared_unit": ("declared_unit", "unit", "declared unit", "functional unit"),
    "gwp": ("gwp_kgco2e_per_unit", "gwp", "gwp_value", "kgco2e", "a1-a3", "a1a3", "gwp (kgco2e/unit)"),
    "density": ("density_kg_m3", "density", "density (kg/m3)"),
    "source": ("source", "epd source", "reference"),
    "epd_id": ("epd_id", "epd", "epd number", "epd no"),
    "valid_to": ("valid_to", "valid until", "expiry", "expires"),
}


def template_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(TEMPLATE_COLUMNS)
    w.writerow(TEMPLATE_EXAMPLE)
    return buf.getvalue()


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "material"


def user_factor(
    name: str,
    declared_unit: str,
    gwp_value: float,
    *,
    source: str,
    density_kg_m3: float | None = None,
    epd_id: str | None = None,
    valid_to: date | None = None,
    category: str | None = None,
) -> FactorRef:
    unit = declared_unit.strip().lower().replace(" ", "").replace("³", "3").replace("²", "2")
    if unit not in UNITS:
        raise ValueError(f"declared unit {declared_unit!r} is not one of {sorted(UNITS)}")
    if not (gwp_value == gwp_value) or gwp_value < 0:
        raise ValueError("the carbon factor must be a number, zero or more")
    if density_kg_m3 is not None and density_kg_m3 <= 0:
        raise ValueError("density must be more than zero")
    return FactorRef(
        factor_id=f"user:{_slug(name)}",
        name=name.strip(),
        source=source,
        source_id=epd_id or None,
        declared_unit=unit,
        gwp_value=float(gwp_value),
        modules=["A1", "A2", "A3"],
        geography="user",
        data_type="epd",
        valid_to=valid_to,
        uncertainty_pct=None,
        attribution=f"category: {category}" if category else None,
        density_kg_m3=density_kg_m3,
    )


def _float(v: str | None) -> float | None:
    if v is None or str(v).strip() == "":
        return None
    return float(str(v).replace(",", "").strip())


def _date(v) -> date | None:
    if v is None or str(v).strip() == "":
        return None
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v).strip()[:10])


def _rows_from(content: bytes, filename: str) -> list[dict]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        ws = load_workbook(io.BytesIO(content), read_only=True, data_only=True).active
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        head = [str(h or "").strip() for h in rows[0]] if rows else []
        return [dict(zip(head, r, strict=False)) for r in rows[1:] if any(c not in (None, "") for c in r)]
    text = content.decode("utf-8-sig", errors="replace")
    return [r for r in csv.DictReader(io.StringIO(text)) if any((v or "").strip() for v in r.values())]


def read_material_list(content: bytes, filename: str) -> tuple[list[FactorRef], list[str]]:
    """(factors, one error per bad row) from a CSV/XLSX in the template."""
    raw = _rows_from(content, filename)
    if not raw:
        return [], ["the file has no rows under its header"]
    keys = {k.lower().strip(): k for k in raw[0] if k}

    def col(field: str) -> str | None:
        for alias in _HEADER_ALIASES[field]:
            if alias in keys:
                return keys[alias]
        return None

    need = [f for f in ("name", "declared_unit", "gwp") if col(f) is None]
    if need:
        return [], [f"missing column(s): {', '.join(need)}; download the template for the expected headers"]
    out: list[FactorRef] = []
    errors: list[str] = []
    for i, r in enumerate(raw, start=2):
        def get(field, r=r):
            c = col(field)
            return r.get(c) if c else None

        try:
            name = str(get("name") or "").strip()
            if not name:
                raise ValueError("no material name")
            gwp = _float(get("gwp"))
            if gwp is None:
                raise ValueError("no carbon factor")
            out.append(user_factor(
                name, str(get("declared_unit") or ""), gwp,
                source=f"Builder library: {filename}" + (f"; {get('source')}" if get("source") else ""),
                density_kg_m3=_float(get("density")),
                epd_id=str(get("epd_id")).strip() if get("epd_id") else None,
                valid_to=_date(get("valid_to")),
                category=str(get("category")).strip() if get("category") else None,
            ))
        except Exception as e:  # one bad row must not lose the rest
            errors.append(f"row {i}: {e}")
    return out, errors


class ProjectFactors(FactorProvider):
    """The shared store plus one project's own factors."""

    def __init__(self, base: FactorProvider, own: dict[str, FactorRef] | None = None):
        self.base = base
        self.own = own or {}

    def get_factor(self, factor_id: str) -> FactorRef | None:
        return self.own.get(factor_id) or self.base.get_factor(factor_id)

    def find_by_material(self, material_name: str, geography: str | None = None) -> FactorRef | None:
        if EDIT_MARK in material_name:
            return self.get_factor(material_name.split(EDIT_MARK, 1)[1].strip())
        return (
            self.base.find_by_material(material_name, geography)
            if geography
            else self.base.find_by_material(material_name)
        )

    def list_factors(self) -> list[FactorRef]:
        return [*self.own.values(), *self.base.list_factors()]

    def factor_categories(self) -> dict[str, str]:
        return self.base.factor_categories()

    def list_substitutions(self) -> list[dict]:
        return self.base.list_substitutions()
