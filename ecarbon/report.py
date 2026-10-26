"""Outputs a builder can hand to someone else: a CSV takeoff and a report.

Criterion 5 asks for an exportable bill of quantities and a document a builder
could give a municipality. Both are generated from the same `TakeoffResult`
and `CarbonResult`, so they cannot drift from what the interface shows.

Two rules govern what goes in them.

**Every quantity carries its provenance in the export, not just on screen.**
A spreadsheet row that cannot be traced back to a sheet is the thing this
product exists to replace, so sheet, detail, confidence, basis and the
assumptions all travel as columns.

**The report states its own limits before its total.** A carbon figure is
quoted with its module scope, the share of the building it covers, and the
list of what could not be read. A reader who takes the number out of this
document and into a submission should find it difficult to misrepresent it by
accident.
"""

from __future__ import annotations

import csv
import html
import io
from datetime import date

from ecarbon.models import CarbonResult, TakeoffResult

CSV_COLUMNS = [
    "line_id",
    "element_class",
    "assembly_tag",
    "description",
    "material",
    "quantity",
    "unit",
    "confidence",
    "sheet",
    "detail",
    "page",
    "basis_sources",
    "basis_note",
    "assumptions",
    "user_override",
    "kg_co2e",
    "factor_id",
    "factor_name",
    "factor_source",
    "factor_modules",
    "counted",
    "missing_reason",
]


def takeoff_csv(takeoff: TakeoffResult, carbon: CarbonResult | None = None) -> str:
    """The bill of quantities as CSV, with provenance and carbon per line."""
    by_line = {c.line_id: c for c in (carbon.lines if carbon else [])}
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)

    for line in takeoff.lines:
        c = by_line.get(line.id)
        factor = c.factor if c else None
        writer.writerow(
            [
                line.id,
                line.element_class.value,
                line.assembly_tag or "",
                line.description or "",
                line.material or "",
                f"{line.quantity:.4f}",
                line.unit.value,
                line.confidence.value,
                line.provenance.sheet_no or "",
                line.provenance.detail or "",
                line.provenance.page,
                "; ".join(s.value for s in line.basis.sources),
                line.basis.note or "",
                " | ".join(line.assumptions),
                "" if line.user_override is None else f"{line.user_override:.4f}",
                "" if not c or c.kg_co2e is None else f"{c.kg_co2e:.2f}",
                factor.factor_id if factor else "",
                factor.name if factor else "",
                factor.source if factor else "",
                "+".join(factor.modules) if factor else "",
                "yes" if c and c.kg_co2e is not None else "no",
                (c.missing_reason if c and c.missing_reason else ""),
            ]
        )
    return buf.getvalue()


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def module_label(modules: list[str]) -> str:
    """"A1, A2, A3" is the scope; "A1-A3" is how the standard writes it."""
    if not modules:
        return "scope unknown"
    nums = [int(m[1:]) for m in modules if m[1:].isdigit()]
    contiguous = len(nums) == len(modules) and all(
        n == nums[i - 1] + 1 for i, n in enumerate(nums) if i
    )
    return (
        f"{modules[0]}&ndash;{modules[-1]}" if contiguous and len(modules) > 1
        else ", ".join(modules)
    )


def _rows(takeoff: TakeoffResult, carbon: CarbonResult) -> str:
    by_line = {c.line_id: c for c in carbon.lines}
    out: list[str] = []
    for line in takeoff.lines:
        c = by_line.get(line.id)
        kg = (
            f"{c.kg_co2e:,.0f}"
            if c and c.kg_co2e is not None
            else '<span class="flag">not counted</span>'
        )
        cite = (
            f'<span class="cite">{_esc(line.provenance.sheet_no)}'
            f' &middot; {_esc(line.provenance.detail or "")}</span>'
            if line.provenance.sheet_no
            else '<span class="muted">no sheet recorded</span>'
        )
        notes = list(line.assumptions) + ([c.missing_reason] if c and c.missing_reason else [])
        note_html = (
            "<div class='notes'>"
            + "".join(f"<div>&mdash; {_esc(n)}</div>" for n in notes)
            + "</div>"
            if notes
            else ""
        )
        out.append(
            f"<tr class='c-{line.confidence.value}'>"
            f"<td><div class='el'>{_esc(line.element_class.value.replace('_', ' ').title())}"
            f"{f' [{_esc(line.assembly_tag)}]' if line.assembly_tag else ''}</div>"
            f"<div class='desc'>{_esc(line.description or '')}</div>{cite}{note_html}</td>"
            f"<td class='num'>{line.quantity:,.2f} <span class='muted'>{line.unit.value}</span></td>"
            f"<td><span class='tag'>{line.confidence.value}</span></td>"
            f"<td class='num'>{kg}</td></tr>"
        )
    return "".join(out)


def report_html(takeoff: TakeoffResult, carbon: CarbonResult) -> str:
    """A printable report. Scope and limits come before the total."""
    p = takeoff.project
    gaps = sorted(takeoff.gaps, key=lambda g: {"blocking": 0, "warning": 1}.get(g.severity.value, 2))
    coverage = next(
        (g.message for g in takeoff.gaps if "covers roughly" in g.message), None
    )
    factors = sorted(
        {
            (c.factor.source, c.factor.attribution)
            for c in carbon.lines
            if c.factor and c.factor.source
        }
    )
    readable = sum(1 for s in takeoff.sheets if s.readable)

    gap_html = "".join(
        f"<li class='sev-{g.severity.value}'><b>{_esc(g.severity.value)}</b> "
        f"{_esc(g.message)}</li>"
        for g in gaps
    ) or "<li>Every sheet this takeoff needed was readable.</li>"

    contrib_html = "".join(
        f"<tr><td>{_esc(x.key)}</td><td class='num'>{x.kg_co2e:,.0f}</td>"
        f"<td class='num'>{x.pct_of_total:.1f}%</td></tr>"
        for x in carbon.by_material_category
    )

    factor_html = "".join(
        f"<li>{_esc(src)}{f' &mdash; {_esc(attr)}' if attr else ''}</li>"
        for src, attr in factors
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Embodied carbon takeoff &mdash; {_esc(p.name)}</title>
<style>
  :root {{
    --paper:#fbfaf7; --ink:#141719; --graphite:#5c6469; --hairline:#ddd9d1;
    --rule:#c3beb3; --blueprint:#1d4e89; --flag:#b4531a;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:var(--paper); color:var(--ink); font:14px/1.55 "IBM Plex Sans",
         system-ui,sans-serif; font-variant-numeric:tabular-nums;
         max-width:52rem; margin:0 auto; padding:32px 20px 72px; }}
  h1 {{ font:700 22px/1.2 "Archivo Narrow","Arial Narrow",sans-serif;
        letter-spacing:.04em; text-transform:uppercase; }}
  h2 {{ font:700 13px/1.3 "Archivo Narrow","Arial Narrow",sans-serif;
        letter-spacing:.13em; text-transform:uppercase; color:var(--graphite);
        margin:34px 0 10px; padding-bottom:6px; border-bottom:1px solid var(--ink); }}
  .num {{ font-family:"IBM Plex Mono",ui-monospace,monospace; text-align:right;
          white-space:nowrap; }}
  .muted {{ color:var(--graphite); }}
  header {{ border-bottom:2px solid var(--ink); padding-bottom:14px; }}
  .facts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
            gap:10px 18px; margin-top:14px; }}
  .facts div span {{ display:block; font:600 10px/1.4 "Archivo Narrow",sans-serif;
                     letter-spacing:.13em; text-transform:uppercase; color:var(--graphite); }}
  .total {{ font:500 46px/1 "IBM Plex Mono",monospace; letter-spacing:-.03em; }}
  .scope {{ display:inline-block; margin-top:10px; padding:3px 8px;
            border:1px solid var(--blueprint); color:var(--blueprint);
            font:11px/1.4 "IBM Plex Mono",monospace; }}
  .warn {{ border-left:3px solid var(--flag); background:#fbf0e7;
           padding:11px 14px; margin:16px 0; }}
  table {{ width:100%; border-collapse:collapse; margin-top:4px; }}
  th {{ font:600 10px/1.4 "Archivo Narrow",sans-serif; letter-spacing:.12em;
        text-transform:uppercase; color:var(--graphite); text-align:left;
        padding:8px 8px; border-bottom:1px solid var(--rule); }}
  th.num, td.num {{ text-align:right; }}
  td {{ padding:9px 8px; border-bottom:1px solid var(--hairline); vertical-align:top; }}
  td:first-child {{ border-left:3px solid transparent; padding-left:11px; }}
  tr.c-measured td:first-child {{ border-left-color:var(--blueprint); }}
  tr.c-inferred td:first-child {{ border-left-color:var(--rule); }}
  tr.c-assumed  td:first-child {{ border-left-color:var(--flag); }}
  .el {{ font-weight:500; }}
  .desc {{ color:var(--graphite); font-size:12.5px; }}
  .cite {{ display:inline-block; margin-top:4px; padding:1px 7px;
           border:1px solid var(--blueprint); border-radius:999px;
           font:11px/1.5 "IBM Plex Mono",monospace; color:var(--blueprint); }}
  .tag {{ font:600 10px/1.4 "Archivo Narrow",sans-serif; letter-spacing:.1em;
          text-transform:uppercase; border:1px solid currentColor; padding:1px 5px; }}
  tr.c-measured .tag {{ color:var(--blueprint); }}
  tr.c-inferred .tag {{ color:var(--graphite); }}
  tr.c-assumed  .tag {{ color:var(--flag); }}
  .notes {{ margin-top:6px; font-size:12px; color:var(--graphite); max-width:60ch; }}
  .flag {{ color:var(--flag); font-family:"IBM Plex Mono",monospace; font-size:11.5px; }}
  ul {{ padding-left:18px; }} li {{ margin:6px 0; max-width:72ch; }}
  li.sev-blocking {{ color:var(--flag); }}
  footer {{ margin-top:40px; padding-top:14px; border-top:1px solid var(--rule);
            font-size:12px; color:var(--graphite); }}
  @media print {{ body {{ padding:0; max-width:none; }} h2 {{ page-break-after:avoid; }}
                 tr {{ page-break-inside:avoid; }} }}
</style></head><body>

<header>
  <h1>Embodied carbon takeoff</h1>
  <div class="muted">{_esc(p.name)}{f' &middot; {_esc(p.jurisdiction)}' if p.jurisdiction else ''}
    &middot; from {_esc(takeoff.source_file)}</div>
  <div class="facts">
    <div><span>Floor area</span>{f'{p.gfa_m2:,.1f} m&sup2; ({_esc(p.gfa_basis)})' if p.gfa_m2 else '&mdash;'}</div>
    <div><span>Storeys / units</span>{p.storeys or '&mdash;'} / {p.units or '&mdash;'}</div>
    <div><span>Sheets read</span>{readable} of {len(takeoff.sheets)}</div>
    <div><span>Prepared</span>{takeoff.extracted_at or date.today()}</div>
  </div>
</header>

<h2>What this number is, and is not</h2>
<div class="total">{carbon.total_kg_co2e:,.0f} <span class="muted"
  style="font:600 15px/1 'Archivo Narrow',sans-serif;letter-spacing:.08em">KG CO&#8322;E</span></div>
<div class="scope">Modules {module_label(carbon.modules)} &middot; product stage only</div>
<div style="margin-top:10px">Intensity
  <b class="num">{carbon.intensity_kg_co2e_per_m2:,.1f}</b> kg CO&#8322;e per m&sup2;
  ({_esc(carbon.intensity_basis)} floor area).</div>
{f'<div class="warn">{_esc(coverage)}</div>' if coverage else ''}
<p class="muted" style="margin-top:12px;max-width:72ch">This figure covers the
product stage only &mdash; raw material supply, transport to the factory and
manufacturing. It does not include delivery to site, construction, replacement
over the building&rsquo;s life, or demolition. A published whole-life figure for
the same building will be substantially larger and is not comparable with this
one without restating both to the same modules.</p>

<h2>What could not be read</h2>
<ul>{gap_html}</ul>

<h2>Bill of quantities</h2>
<table><thead><tr><th>Element and source</th><th class="num">Quantity</th>
<th>Basis</th><th class="num">kg CO&#8322;e</th></tr></thead>
<tbody>{_rows(takeoff, carbon)}</tbody></table>

<h2>Where the carbon is</h2>
<table><thead><tr><th>Material</th><th class="num">kg CO&#8322;e</th>
<th class="num">Share</th></tr></thead><tbody>{contrib_html}</tbody></table>

<h2>Factor sources</h2>
<ul>{factor_html or '<li>No factors were applied.</li>'}</ul>

<footer>
  Quantities are measured from the vector drawings and labelled
  <b>measured</b> where two independent sources agreed, <b>inferred</b> where a
  measurement was combined with a stated convention, and <b>assumed</b> where
  the drawings are silent &mdash; every assumption is printed against its line.
  Generated by ecarbon from {_esc(takeoff.source_file)}.
</footer>
</body></html>"""
