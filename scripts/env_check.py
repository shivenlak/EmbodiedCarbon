#!/usr/bin/env python
"""Verify the environment really works: deps import, data is findable, and a
real PDF and IFC parse to the numbers recorded in RESEARCH.md.

Checking that imports succeed is not enough -- the point is to catch a silently
wrong install before it costs a day of debugging.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OK, BAD, WARN = "  ok  ", " FAIL ", " warn "
failures = 0


def check(label: str, fn) -> object | None:
    global failures
    try:
        value, detail = fn()
    except Exception as exc:
        print(f"[{BAD}] {label}: {type(exc).__name__}: {exc}")
        failures += 1
        return None
    tag = OK if value else BAD
    if not value:
        failures += 1
    print(f"[{tag}] {label}: {detail}")
    return value


def main() -> int:
    print(f"python {sys.version.split()[0]}  ({sys.executable})\n")
    # Deliberate runtime guard: this script must also be runnable by the
    # system python 3.9 and tell the user why it cannot help them.
    if sys.version_info < (3, 11):  # noqa: UP036
        print("FAIL: need python >= 3.11 (pymupdf/shapely/duckdb wheels). "
              "Use .venv/bin/python, not /usr/bin/python3.")
        return 1

    def _deps():
        import fastapi
        import ifcopenshell
        import pandas
        import pydantic
        import pymupdf
        import shapely

        v = (
            f"pymupdf={pymupdf.__version__} "
            f"ifcopenshell={ifcopenshell.version} shapely={shapely.__version__} "
            f"pydantic={pydantic.VERSION} fastapi={fastapi.__version__} "
            f"pandas={pandas.__version__}"
        )
        return True, v

    check("dependencies import", _deps)

    def _poppler():
        import shutil

        p = shutil.which("pdftoppm")
        return bool(p), p or "pdftoppm not on PATH (brew install poppler)"

    check("poppler (page rendering / OCR fallback)", _poppler)

    def _contract():
        from ecarbon.models import SCHEMA_VERSION, CarbonResult, TakeoffResult  # noqa: F401

        return True, f"schema {SCHEMA_VERSION}"

    check("data contract imports", _contract)

    def _data():
        from ecarbon.config import data_root, discover

        designs = discover()
        with_pdf = [d for d in designs if d.drawings_pdf]
        with_ifc = [d for d in designs if d.has_ifc]
        detail = (
            f"{len(designs)} designs at {data_root()} "
            f"({len(with_pdf)} with drawings PDF, {len(with_ifc)} with IFC)"
        )
        return len(designs) >= 52, detail

    designs_ok = check("catalogue discovered (expect >= 52)", _data)

    if designs_ok:

        def _pdf():
            from ecarbon.config import get_design
            from ecarbon.intake import inventory

            d = get_design("AB_Fourplex_01")
            sheets, _, producer = inventory(d.drawings_pdf)
            paths = sum(s.n_paths for s in sheets)
            # RESEARCH.md §2: 46 pages, ~738k path ops, ~11.3k text ops
            good = len(sheets) == 46 and paths > 400_000
            return good, f"AB_Fourplex_01: {len(sheets)} pages, {paths:,} path ops ({producer or 'no producer'})"

        check("PDF parse matches RESEARCH.md", _pdf)

        def _ifc():
            import ifcopenshell

            from ecarbon.config import get_design

            d = get_design("AB_Fourplex_01")
            f = ifcopenshell.open(str(d.ifc))
            walls = len(f.by_type("IfcWall"))
            # RESEARCH.md §2: 92 walls (IfcWall + IfcWallStandardCase)
            return walls >= 70, f"AB_Fourplex_01.ifc: {walls} walls, schema {f.schema}"

        check("IFC parse matches RESEARCH.md", _ifc)

    def _refs():
        from ecarbon.config import repo_root

        ref = repo_root() / "reference"
        pdfs = sorted(p.name for p in ref.glob("*.pdf")) if ref.is_dir() else []
        if not pdfs:
            return None, "reference/ empty -- run: python scripts/fetch_references.py"
        return True, f"{len(pdfs)} reference PDFs: {', '.join(pdfs)[:90]}"

    got = _refs()
    print(f"[{OK if got[0] else WARN}] reference material: {got[1]}")

    print()
    if failures:
        print(f"{failures} check(s) failed.")
        return 1
    print("environment ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
