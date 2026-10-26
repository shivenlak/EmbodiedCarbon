"""STEP 6 -- Drawing intake: page inventory and per-page toolchain detection.

Why per PAGE and not per file: a single catalogue drawings PDF concatenates
several firms' exports. AB_Fourplex_01 pages 1-18 carry Revit metadata (the
architect's sheets); pages 19-46 carry none (structural/mech/elec, exported
from AutoCAD and appended). Any per-file assumption about drawing convention
is wrong. See RESEARCH.md §4b.

What we harvest per page, cheapest-first:
  * content-stream op census (paths / text / images) -- decides readability
  * MediaBox -> sheet size in inches
  * /revit_metadata_* page keys -> sheet number + title, free and exact (§4a)
  * optional content group (layer) names -> AIA discipline codes (§4c)
  * /VP viewport matrices -> candidate world-to-page transforms (§4d)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pymupdf

from ecarbon.models import BasisSource, Discipline, SheetInfo, SheetType, Toolchain

# Sheet types that are drawn to scale. A schedule, specification or legend has
# no scale, and asking for one yields nonsense: the size column of an openings
# schedule reads as a dimension chain and implies 1:418.
SCALED_SHEET_TYPES = frozenset(
    {
        SheetType.FLOOR_PLAN,
        SheetType.FOUNDATION_PLAN,
        SheetType.ROOF_PLAN,
        SheetType.FRAMING_PLAN,
        SheetType.SITE_PLAN,
        SheetType.ELEVATION,
        SheetType.SECTION,
        SheetType.DETAIL,
    }
)

# A page with fewer than this many text-show operators has no usable text.
# Calibration: the 8 Acrobat-Distiller NOR sets average <1 per page (text was
# converted to vector outlines); every other set averages 150-2500.
MIN_TEXT_OPS_READABLE = 20

# Below this many path operators a page is not a real drawing.
MIN_PATHS_VECTOR = 200

# AIA CAD Layer Guidelines: discipline letter + separator + 4-letter major
# group, e.g. A-WALL, S-FNDN, G-ANNO-TEXT. Catalogue layer names are often
# xref-prefixed ("X-border_$0$G-ANNO-SCHD", "14-24-082 - XFP-4PX-#1-01|A-FLOR")
# so we search anywhere in the string rather than anchoring.
AIA_LAYER_RE = re.compile(r"(?:^|[^A-Z])([ASMEPGCFLQTX])[-_]([A-Z]{4})(?:$|[^A-Z])")

_OP = {
    "path": re.compile(rb"(?<![A-Za-z0-9])(?:re|m|l|c|v|y|h)(?![A-Za-z0-9])"),
    "text": re.compile(rb"(?<![A-Za-z0-9])(?:Tj|TJ)(?![A-Za-z0-9])"),
    "image": re.compile(rb"(?<![A-Za-z0-9])(?:Do|BI)(?![A-Za-z0-9])"),
}

_REVIT_KEYS = (
    "revit_metadata_view_sheet_number",
    "revit_metadata_view_name",
    "revit_metadata_view_type",
)


def _decode_pdf_string(raw: str | None) -> str | None:
    """Revit writes these as UTF-16BE with a BOM, which arrives from PyMuPDF
    as a parenthesised literal. Strip, de-BOM, drop NULs."""
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    b = s.encode("latin-1", errors="replace")
    b = b.replace(b"\\376\\377", b"\xfe\xff")
    if b.startswith(b"\xfe\xff"):
        try:
            s = b[2:].decode("utf-16-be", errors="replace")
        except Exception:
            s = b.decode("latin-1", errors="replace")
    elif b.startswith(b"\xff\xfe"):
        try:
            s = b[2:].decode("utf-16-le", errors="replace")
        except Exception:
            s = b.decode("latin-1", errors="replace")
    else:
        s = b.decode("latin-1", errors="replace")
    s = s.replace("\x00", "").replace("﻿", "")
    return re.sub(r"\s+", " ", s).strip() or None


@dataclass
class PageProbe:
    """Raw per-page observations, before any interpretation."""

    page: int
    width_in: float
    height_in: float
    n_paths: int = 0
    n_text: int = 0
    n_images: int = 0
    revit_sheet_no: str | None = None
    revit_view_name: str | None = None
    revit_view_type: str | None = None
    layer_names: list[str] = field(default_factory=list)
    n_vp: int = 0
    text_sample: str = ""

    @property
    def aia_layers(self) -> list[str]:
        return [n for n in self.layer_names if AIA_LAYER_RE.search(n.upper())]

    @property
    def meaningful_layers(self) -> list[str]:
        """'Watermark' is on every CMHC sheet and carries no information."""
        return [n for n in self.layer_names if n.strip().lower() not in {"watermark", "0"}]

    @property
    def readable(self) -> bool:
        return self.n_text >= MIN_TEXT_OPS_READABLE

    @property
    def is_vector(self) -> bool:
        return self.n_paths >= MIN_PATHS_VECTOR


class DrawingSet:
    """A drawings PDF, opened once and probed lazily."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.doc = pymupdf.open(self.path)
        self._ocg_names: dict[int, str] | None = None
        self._repair = None
        self._producer = (self.doc.metadata or {}).get("producer") or ""
        self._creator = (self.doc.metadata or {}).get("creator") or ""

    def close(self) -> None:
        self.doc.close()

    def __enter__(self) -> DrawingSet:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __len__(self) -> int:
        return self.doc.page_count

    @property
    def repair(self):
        """Font-shift map for this document, solved once (see textrepair)."""
        if self._repair is None:
            from ecarbon.intake.textrepair import FontRepair

            self._repair = FontRepair().learn(self.doc)
        return self._repair

    @property
    def producer_tag(self) -> str:
        return f"{self._producer} {self._creator}".strip()

    # -- optional content groups -------------------------------------------

    def ocg_names(self) -> dict[int, str]:
        """xref -> layer name, for the whole document."""
        if self._ocg_names is None:
            out: dict[int, str] = {}
            try:
                for xref, info in (self.doc.get_ocgs() or {}).items():
                    name = info.get("name") if isinstance(info, dict) else None
                    if name:
                        out[int(xref)] = str(name)
            except Exception:
                pass
            self._ocg_names = out
        return self._ocg_names

    def _page_layer_names(self, page: pymupdf.Page) -> list[str]:
        """Layer names referenced by this page, via /Resources/Properties.

        AutoCAD-exported pages name their OCGs in the page resource dict, so
        this gives per-page layers rather than document-wide ones.
        """
        names: list[str] = []
        all_names = self.ocg_names()
        try:
            n_props = self.doc.xref_get_key(page.xref, "Resources/Properties")
            if n_props and n_props[0] == "dict":
                for key in re.findall(r"/([^\s/<>\[\]()]+)", n_props[1]):
                    item = self.doc.xref_get_key(page.xref, f"Resources/Properties/{key}")
                    if not item:
                        continue
                    m = re.search(r"(\d+)\s+\d+\s+R", str(item[1]))
                    if m and int(m.group(1)) in all_names:
                        names.append(all_names[int(m.group(1))])
        except Exception:
            pass
        if not names:
            # Fall back to document-level OCGs so we at least know the set has
            # layers; flagged by the caller as not page-specific.
            names = list(all_names.values())
        seen: set[str] = set()
        return [n for n in names if not (n in seen or seen.add(n))]

    # -- probing -----------------------------------------------------------

    def probe_page(self, index: int) -> PageProbe:
        page = self.doc[index]
        rect = page.rect
        probe = PageProbe(
            page=index,
            width_in=round(rect.width / 72.0, 2),
            height_in=round(rect.height / 72.0, 2),
        )

        # Op census from the raw content stream. Deliberately NOT
        # page.get_drawings(): the NOR sets carry up to 4.7M path operators
        # and building Python objects for each takes minutes per file.
        try:
            content = page.read_contents()
        except Exception:
            content = b""
        for key, rx in _OP.items():
            n = len(rx.findall(content))
            if key == "path":
                probe.n_paths = n
            elif key == "text":
                probe.n_text = n
            else:
                probe.n_images = n
        probe.n_vp = len(re.findall(rb"/VP\s*\[", content))

        # Revit sheet metadata -- free, exact Stage 1 classification (§4a).
        for key in _REVIT_KEYS:
            try:
                got = self.doc.xref_get_key(page.xref, key)
            except Exception:
                got = None
            if got and got[0] != "null":
                val = _decode_pdf_string(str(got[1]))
                if key.endswith("sheet_number"):
                    probe.revit_sheet_no = val
                elif key.endswith("view_name"):
                    probe.revit_view_name = val
                else:
                    probe.revit_view_type = val

        probe.layer_names = self._page_layer_names(page)

        if probe.readable:
            try:
                probe.text_sample = page.get_text("text")[:4000]
            except Exception:
                probe.text_sample = ""

        return probe

    def probe(self) -> list[PageProbe]:
        return [self.probe_page(i) for i in range(len(self))]


def classify_toolchain(probe: PageProbe, producer_tag: str = "") -> Toolchain:
    """Decide how this page was exported.

    Order matters. Readability is checked before provenance signals because a
    textless page constrains everything downstream regardless of its origin.
    """
    if not probe.readable and probe.n_paths > 1000:
        # Vector geometry, no text: glyphs were converted to outlines. Found
        # across all 8 NOR sets, but ALSO page-by-page inside otherwise
        # readable ON / BC / SKMB sets -- which is exactly why this is decided
        # per page. See RESEARCH.md §3.
        return Toolchain.DISTILLER_OUTLINED

    if not probe.is_vector and not probe.readable and probe.n_images > 0:
        # Page 0 of every catalogue set: an image-based cover sheet.
        return Toolchain.RASTER

    if probe.revit_sheet_no or probe.revit_view_name:
        return Toolchain.REVIT_TAGGED

    if probe.aia_layers:
        return Toolchain.AIA_LAYERED

    if "vectorworks" in producer_tag.lower():
        return Toolchain.VECTORWORKS

    # A schedule or specification sheet is mostly type and carries very few
    # path operators, so readable text alone is enough to call it a drawing.
    if probe.is_vector or probe.readable:
        return Toolchain.FLATTENED

    return Toolchain.UNKNOWN


def _discipline_from_sheet_no(sheet_no: str | None) -> Discipline:
    if not sheet_no:
        return Discipline.UNKNOWN
    head = sheet_no.strip().upper()[:1]
    try:
        return Discipline(head)
    except ValueError:
        return Discipline.UNKNOWN


def _split_revit_view_name(name: str | None) -> tuple[str | None, str | None]:
    """'A101 - MAIN FLOOR PLAN - ACCESSIBLE READY' -> ('A101', 'MAIN FLOOR...')."""
    if not name:
        return None, None
    m = re.match(r"\s*([A-Z]{1,3}\d{2,4}[a-z]?)\s*[-–]\s*(.+)$", name.strip())
    if m:
        return m.group(1), m.group(2).strip()
    return None, name.strip()


def inventory(
    path: str | Path, with_scale: bool = False
) -> tuple[list[SheetInfo], list[PageProbe], str]:
    """Build the Stage 1 sheet inventory for one drawings PDF.

    Returns (sheets, raw probes, producer tag).

    `with_scale` additionally calibrates each readable sheet (Step 8). It is off
    by default because calibration re-reads every text span and roughly doubles
    the time, and the intake inventory is also used where scale is irrelevant.

    The result is cached per (file, with_scale), because one takeoff asks for it
    eight times -- the builder, the foundation specs, the levels, the assemblies
    twice and the openings twice -- and each call otherwise re-parses the whole
    PDF. Callers get a deep copy of the sheet list, since `SheetInfo` is mutable
    and `set_toolchain` writes to it; handing out the cached objects would let
    one caller's edit reach every other.
    """
    sheets, probes, producer = _inventory_cached(str(path), with_scale)
    return [s.model_copy(deep=True) for s in sheets], probes, producer


@lru_cache(maxsize=8)
def _inventory_cached(
    path: str, with_scale: bool
) -> tuple[list[SheetInfo], list[PageProbe], str]:
    from ecarbon.intake.classify import classify_page

    sheets: list[SheetInfo] = []
    with DrawingSet(path) as ds:
        producer = ds.producer_tag
        probes = ds.probe()

        for p in probes:
            tc = classify_toolchain(p, producer)
            no_from_name, title_from_name = _split_revit_view_name(p.revit_view_name)
            revit_no = p.revit_sheet_no
            # Revit's sheet_number key is sometimes truncated ('A2' for 'A200');
            # prefer the number parsed out of the fuller view name when longer.
            if no_from_name and (not revit_no or len(no_from_name) > len(revit_no)):
                revit_no = no_from_name

            sheet_no, title, stype, disc, src = classify_page(
                ds.doc[p.page],
                revit_sheet_no=revit_no,
                revit_title=title_from_name,
                repair=ds.repair,
            )

            scale_mm_per_pt: float | None = None
            scale_src = None
            if with_scale and p.readable and stype in SCALED_SHEET_TYPES:
                from ecarbon.geometry.scale import ScaleSource, calibrate

                est = calibrate(ds.doc[p.page])
                # Only publish a scale we can defend; an untrustworthy estimate
                # left as None makes downstream quantities impossible rather
                # than quietly wrong, which is the behaviour we want.
                if est.trustworthy:
                    scale_mm_per_pt = est.mm_per_pt
                    scale_src = {
                        ScaleSource.DIMENSION_CHAIN: BasisSource.VECTOR_PATH,
                        ScaleSource.SCALE_TEXT: BasisSource.SECTION_NOTE,
                        ScaleSource.VIEWPORT_MATRIX: BasisSource.VECTOR_PATH,
                    }.get(est.source)

            sheets.append(
                SheetInfo(
                    page=p.page,
                    sheet_no=sheet_no,
                    title=title,
                    discipline=disc,
                    sheet_type=stype,
                    toolchain=tc,
                    readable=p.readable,
                    width_in=p.width_in,
                    height_in=p.height_in,
                    scale=scale_mm_per_pt,
                    scale_source=scale_src,
                    classified_by=src,
                    layer_names=p.meaningful_layers[:40],
                    n_paths=p.n_paths,
                    n_text=p.n_text,
                    n_images=p.n_images,
                )
            )
    return sheets, probes, producer


def set_toolchain(sheets: list[SheetInfo]) -> Toolchain:
    """The dominant toolchain across a set, for benchmark grouping."""
    if not sheets:
        return Toolchain.UNKNOWN
    counts: dict[Toolchain, int] = {}
    for s in sheets:
        counts[s.toolchain] = counts.get(s.toolchain, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]
