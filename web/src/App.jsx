/* ecarbon — the estimator's view of a plan set.
 *
 * Laid out as a drawing sheet: the bill of quantities occupies the field, and
 * the facts you check a drawing against sit in a fixed title block at the
 * edge. Every quantity carries the sheet it was read from, which is the one
 * thing this product exists to do, so the citation is the most distinctive
 * element on the page rather than a tooltip.
 *
 * Styling lives in index.css as classes. The previous version of this file
 * held 520 inline style objects and a single className, which made a
 * consistent type scale impossible to hold.
 */

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";

const API = "http://127.0.0.1:8000";

const CONFIDENCE_NOTE = {
  measured: "Read from the drawing geometry and confirmed by a second source.",
  inferred: "Derived from a measured value plus a convention named on the line.",
  assumed: "Not in the drawings. The assumption is stated and can be overridden.",
};

/* ------------------------------------------------------------- helpers --- */

const int = (n) =>
  n === null || n === undefined ? "—" : Math.round(n).toLocaleString("en-CA");

const dec = (n, p = 2) =>
  n === null || n === undefined ? "—" : Number(n).toFixed(p);

const titleCase = (s) =>
  (s || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

/* Catalogue keys carry a packaging suffix that tells a reader nothing. */
const prettyName = (s) =>
  (s || "")
    .replace(/[_ ]*Technical[_ ]Design[_ ]Package/i, "")
    .replace(/[_ ]*Drawings?$/i, "")
    .replace(/_/g, " ")
    .trim();

/* A line is counted when the engine produced a figure for it. `is_counted` is
 * a property on the Python model and so never reaches the JSON; the presence
 * of kg_co2e is the same fact and is in the payload. */
const isCounted = (c) => c != null && c.kg_co2e != null;

/* "A1, A2, A3" is the scope; "A1–A3" is how the standard writes it. */
const moduleLabel = (mods) => {
  if (!mods?.length) return null;
  const nums = mods.map((m) => parseInt(m.slice(1), 10));
  const contiguous = nums.every((n, i) => i === 0 || n === nums[i - 1] + 1);
  return contiguous && mods.length > 1
    ? `${mods[0]}\u2013${mods[mods.length - 1]}`
    : mods.join(", ");
};

async function getJSON(path) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} on ${path}`);
  return res.json();
}

/* --------------------------------------------------------------- pieces -- */

// Which plan set to open on. `?plan=` wins so a demo or a bug report can
// deep-link an exact design; otherwise prefer a multi-storey set over an ADU,
// because a single-storey plan yields fewer than two floor datums and so has
// no wall height, no wall, floor or partition area, and a thin bill. Opening
// on the catalogue's first key alphabetically meant always landing on
// AB_ADU_01, the weakest design we have.
function pickInitial(list) {
  const wanted = new URLSearchParams(window.location.search).get("plan");
  const idOf = (p) => p.id ?? p.project_id;
  if (wanted) {
    const exact = list.find((p) => idOf(p) === wanted);
    if (exact) return idOf(exact);
    const loose = list.find((p) =>
      String(idOf(p)).toLowerCase().includes(wanted.toLowerCase()),
    );
    if (loose) return idOf(loose);
  }
  const multi = list.find((p) => !/_ADU_/i.test(String(idOf(p))));
  return idOf(multi ?? list[0]);
}

function ScaleBar() {
  return (
    <div className="scalebar" aria-hidden="true">
      <i /><i /><i /><i /><i /><i />
    </div>
  );
}

// Mirrors PARTITION_LINE_PREFIX in ecarbon/takeoff/builder.py.
const PARTITION_PREFIX = "ln-interior-partition";

function Citation({ provenance, onTrace, lineId }) {
  const sheet = provenance?.sheet_no;
  if (!sheet) {
    return (
      <span className="cite cite-none">
        <span className="cite-sheet">—</span>
        <span className="cite-detail">no sheet recorded</span>
      </span>
    );
  }
  const detail = provenance.detail || `page ${provenance.page + 1}`;
  return (
    <button
      className="cite"
      onClick={() => onTrace?.(lineId, provenance)}
      title={`Show where this came from on sheet ${sheet}`}
    >
      <span className="cite-sheet">{sheet}</span>
      <span className="cite-detail">{detail}</span>
    </button>
  );
}

// Intensity is only as good as its denominator, and the denominator is the
// one project fact the drawings may not state. Where the measured area and
// the stated area disagree, the title block says which one is in use so the
// reader can confirm it rather than discovering it in a gap further down.
function floorAreaNote(gaps) {
  const measured = (gaps || []).find((g) =>
    String(g.message).startsWith("Floor area: using"),
  );
  if (measured) return "measured from the drawings — whole block, confirm this";
  const impossible = (gaps || []).find((g) =>
    String(g.message).includes("kgCO2e/m2 is not possible"),
  );
  if (impossible) return "check this — the intensity it gives is impossible";
  return null;
}

function TitleBlockRow({ label, children }) {
  return (
    <div className="tb-row">
      <span className="tb-label">{label}</span>
      <div className="tb-value">{children}</div>
    </div>
  );
}

export function TitleBlock({ takeoff, carbon, coverage }) {
  const p = takeoff?.project || {};
  const sheets = takeoff?.sheets || [];
  const readable = sheets.filter((s) => s.readable).length;
  const scoped = carbon?.modules?.join(" · ") || "—";
  const areaNote = floorAreaNote(takeoff?.gaps);

  return (
    <aside className="titleblock">
      <TitleBlockRow label="Project">{prettyName(p.name) || "—"}</TitleBlockRow>
      {p.jurisdiction && (
        <TitleBlockRow label="Location">{p.jurisdiction}</TitleBlockRow>
      )}
      <TitleBlockRow label="Plan set">{takeoff?.source_file || "—"}</TitleBlockRow>
      <TitleBlockRow label="Floor area">
        {p.gfa_m2 ? `${dec(p.gfa_m2, 1)} m²` : "—"}
        {p.gfa_basis ? ` · ${p.gfa_basis}` : ""}
        {areaNote && <span className="tb-flag">{areaNote}</span>}
      </TitleBlockRow>
      <TitleBlockRow label="Storeys / units">
        {p.storeys || "—"} / {p.units || "—"}
      </TitleBlockRow>
      <TitleBlockRow label="Sheets read">
        {readable} of {sheets.length}
      </TitleBlockRow>
      <TitleBlockRow label="Module scope">{scoped}</TitleBlockRow>
      <TitleBlockRow label="Element coverage">
        {coverage === null ? "—" : `${Math.round(coverage * 100)}% of carbon`}
        <div className="contrib-bar" style={{ marginTop: 7 }}>
          <div
            className="contrib-fill"
            style={{
              width: `${Math.min((coverage || 0) * 100, 100)}%`,
              background: (coverage || 0) < 0.6 ? "var(--flag)" : "var(--blueprint)",
            }}
          />
        </div>
      </TitleBlockRow>
      <TitleBlockRow label="Extracted">
        {takeoff?.extracted_at || "—"}
      </TitleBlockRow>
      <TitleBlockRow label="Factor sources">
        {carbon?.factor_sources?.length
          ? carbon.factor_sources.join(", ")
          : "Kootenay guide · BEAM · EC3 snapshot"}
      </TitleBlockRow>
    </aside>
  );
}

export function Hero({ carbon, takeoff }) {
  const intensity = carbon?.intensity_kg_co2e_per_m2;
  const counted = (carbon?.lines || []).filter(isCounted).length;
  const measured = (takeoff?.lines || []).filter(
    (l) => l.confidence === "measured",
  ).length;

  // Carbon carried by the interior-partition lines. Their run length is
  // measured off the drawing rather than stated by a schedule, so the total
  // is shown both ways instead of asking the reader to take the one on trust.
  const inferredPartitions = (carbon?.lines || [])
    .filter((l) => isCounted(l) && String(l.line_id).startsWith(PARTITION_PREFIX))
    .reduce((sum, l) => sum + (l.kg_co2e || 0), 0);

  return (
    <section className="hero">
      <div className="hero-total">
        <span className="hero-figure">{int(carbon?.total_kg_co2e)}</span>
        <span className="hero-unit">kg CO₂e</span>
      </div>

      {inferredPartitions > 0 && (
        <div className="hero-range">
          <span className="hero-range-measured">
            {int(carbon.total_kg_co2e - inferredPartitions)} kg CO₂e
          </span>
          <span className="hero-range-note">
            without the inferred interior partitions, which are measured from
            the plan linework rather than read from a schedule. Both figures
            are given because that run is the least certain quantity here.
          </span>
        </div>
      )}

      <div className="hero-scope">
        <span>▣</span>
        <span>
          {carbon?.modules?.length
            ? `Modules ${moduleLabel(carbon.modules)} · product stage only`
            : "Module scope unknown"}
        </span>
      </div>

      <div className="hero-sub">
        <div className="hero-sub-item">
          <span className="eyebrow">Intensity</span>
          <div className="num" style={{ fontSize: 19 }}>
            {dec(intensity, 1)}
            <span className="muted" style={{ fontSize: 12 }}>
              {" "}
              kg/m² {carbon?.intensity_basis || ""}
            </span>
          </div>
        </div>
        <div className="hero-sub-item">
          <span className="eyebrow">Quantities counted</span>
          <div className="num" style={{ fontSize: 19 }}>
            {counted}
            <span className="muted" style={{ fontSize: 12 }}>
              {" "}
              of {takeoff?.lines?.length ?? 0}
            </span>
          </div>
        </div>
        <div className="hero-sub-item">
          <span className="eyebrow">Measured</span>
          <div className="num" style={{ fontSize: 19 }}>
            {measured}
            <span className="muted" style={{ fontSize: 12 }}>
              {" "}
              {measured === 1 ? "line" : "lines"}
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}

export function Notices({ gaps }) {
  // Fourteen notices, eleven of them "R1 layer N states no thickness", pushed
  // the bill of quantities below two screens of near-identical text. The
  // honesty is the point of this panel, so nothing is dropped -- but repeats
  // of one kind collapse behind a count so the distinct problems are the ones
  // you read first.
  const [expanded, setExpanded] = useState({});
  if (!gaps?.length) return null;

  const rank = { blocking: 0, warning: 1, info: 2 };
  const sorted = [...gaps].sort(
    (a, b) => (rank[a.severity] ?? 3) - (rank[b.severity] ?? 3),
  );

  const groups = [];
  const seen = new Map();
  for (const g of sorted) {
    const key = `${g.severity}:${g.code}`;
    if (g.severity === "blocking" || !seen.has(key)) {
      const group = { key, severity: g.severity, code: g.code, items: [g] };
      if (g.severity !== "blocking") seen.set(key, group);
      groups.push(group);
    } else {
      seen.get(key).items.push(g);
    }
  }

  const SHOWN = 2;
  return (
    <div>
      {groups.map((group) => {
        const open = expanded[group.key];
        const shown = open ? group.items : group.items.slice(0, SHOWN);
        const hidden = group.items.length - shown.length;
        return (
          <Fragment key={group.key}>
            {shown.map((g, i) => (
              <div
                key={i}
                className={`notice${g.severity === "blocking" ? "" : " notice-blueprint"}`}
              >
                <div className="notice-head">
                  {g.severity === "blocking" ? "Read this first" : "Worth knowing"} ·{" "}
                  {(g.code || "").replace(/_/g, " ")}
                </div>
                <div>{g.message}</div>
              </div>
            ))}
            {hidden > 0 && (
              <button
                className="notice-more"
                onClick={() =>
                  setExpanded((e) => ({ ...e, [group.key]: true }))
                }
              >
                + {hidden} more of the same kind
                {" ("}
                {(group.code || "").replace(/_/g, " ")}
                {") — shown in full in the exported report"}
              </button>
            )}
          </Fragment>
        );
      })}
    </div>
  );
}

function QuantityCell({ line, editing, draft, onDraft, onCommit, onEdit }) {
  if (editing) {
    return (
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onCommit();
        }}
        style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}
      >
        <input
          className="qty-input"
          type="number"
          step="any"
          autoFocus
          value={draft}
          onChange={(e) => onDraft(e.target.value)}
          aria-label={`Quantity for ${line.element_class}`}
        />
        <button className="btn btn-primary" type="submit">
          Save
        </button>
      </form>
    );
  }
  return (
    <button
      onClick={onEdit}
      className="qty"
      style={{
        background: "none",
        border: "none",
        borderBottom: "1px dashed var(--rule)",
        cursor: "pointer",
        padding: 0,
      }}
      title="Change this quantity and recalculate"
    >
      {dec(line.quantity)}
      <span className="qty-unit">{line.unit}</span>
    </button>
  );
}

export function BillOfQuantities({ takeoff, carbon, onOverride, onTrace }) {
  const [open, setOpen] = useState({});
  const [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState("");

  const carbonFor = useMemo(() => {
    const m = {};
    for (const l of carbon?.lines || []) m[l.line_id] = l;
    return m;
  }, [carbon]);

  const lines = takeoff?.lines || [];
  if (!lines.length) {
    return (
      <p className="muted" style={{ paddingTop: 18, maxWidth: "62ch" }}>
        No quantities were produced for this plan set. The notices above say
        which sheets could not be read.
      </p>
    );
  }

  const commit = (line) => {
    const v = parseFloat(draft);
    setEditing(null);
    if (!Number.isNaN(v) && v !== line.quantity) onOverride(line.id, v);
  };

  return (
    <table className="boq">
      <thead>
        <tr>
          <th style={{ paddingLeft: 13 }}>Element</th>
          <th className="right">Quantity</th>
          <th>Basis</th>
          <th className="right hide-sm">kg CO₂e</th>
        </tr>
      </thead>
      <tbody>
        {lines.map((line) => {
          const c = carbonFor[line.id];
          const isOpen = open[line.id];
          const notes = [
            ...(line.assumptions || []),
            ...(line.basis?.note ? [line.basis.note] : []),
          ];
          return (
            <Fragment key={line.id}>
              <tr className={`c-${line.confidence}`}>
                <td className="lead">
                  <div className="el-name">
                    {titleCase(line.element_class)}
                    {line.assembly_tag ? (
                      <span className="muted num" style={{ fontSize: 12 }}>
                        {" "}
                        [{line.assembly_tag}]
                      </span>
                    ) : null}
                  </div>
                  {line.description && (
                    <div className="el-desc">{line.description}</div>
                  )}
                  <Citation
                    provenance={line.provenance}
                    onTrace={onTrace}
                    lineId={line.id}
                  />
                </td>

                <td className="right">
                  <QuantityCell
                    line={line}
                    editing={editing === line.id}
                    draft={draft}
                    onDraft={setDraft}
                    onCommit={() => commit(line)}
                    onEdit={() => {
                      setEditing(line.id);
                      setDraft(String(line.quantity));
                    }}
                  />
                  {line.user_override !== null &&
                    line.user_override !== undefined && (
                      <div
                        className="num"
                        style={{ fontSize: 11, color: "var(--blueprint)" }}
                      >
                        edited
                      </div>
                    )}
                </td>

                <td>
                  <span className={`tag tag-${line.confidence}`}>
                    {line.confidence}
                  </span>
                  {notes.length > 0 && (
                    <div>
                      <button
                        onClick={() =>
                          setOpen((o) => ({ ...o, [line.id]: !o[line.id] }))
                        }
                        style={{
                          background: "none",
                          border: "none",
                          padding: "4px 0 0",
                          color: "var(--graphite)",
                          cursor: "pointer",
                          font: "inherit",
                          fontSize: 11.5,
                          textDecoration: "underline",
                        }}
                        aria-expanded={!!isOpen}
                      >
                        {isOpen ? "Hide" : "Show"} how this was derived
                      </button>
                    </div>
                  )}
                </td>

                <td className="right num hide-sm">
                  {isCounted(c) ? (
                    int(c.kg_co2e)
                  ) : (
                    <span className="uncounted">not counted</span>
                  )}
                </td>
              </tr>

              {isOpen && (
                <tr className="disclose">
                  <td colSpan={4}>
                    <div className="eyebrow" style={{ marginBottom: 8 }}>
                      {line.confidence} — {CONFIDENCE_NOTE[line.confidence]}
                    </div>
                    {notes.map((n, i) => (
                      <div className="disclose-item" key={i}>
                        <span>{n}</span>
                      </div>
                    ))}
                    {c?.missing_reason && (
                      <div
                        className="disclose-item"
                        style={{ color: "var(--flag)" }}
                      >
                        <span>{c.missing_reason}</span>
                      </div>
                    )}
                    {line.basis?.sources?.length ? (
                      <div
                        className="disclose-item num"
                        style={{ fontSize: 11.5 }}
                      >
                        <span>
                          Sources: {line.basis.sources.join(", ")}
                          {line.basis.agreement
                            ? ` · agreement ${(line.basis.agreement * 100).toFixed(0)}%`
                            : ""}
                        </span>
                      </div>
                    ) : null}
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}

export function Contribution({ carbon }) {
  const rows = carbon?.by_material_category || [];
  if (!rows.length) return null;
  const max = Math.max(...rows.map((r) => r.pct_of_total || 0), 1);
  return (
    <div>
      {rows.map((r) => (
        <div className="contrib-row" key={r.key}>
          <div>
            <div style={{ fontSize: 13 }}>{r.key}</div>
            <div className="contrib-bar">
              <div
                className="contrib-fill"
                style={{ width: `${((r.pct_of_total || 0) / max) * 100}%` }}
              />
            </div>
          </div>
          <div className="right num" style={{ textAlign: "right" }}>
            {int(r.kg_co2e)}
          </div>
          <div className="num muted" style={{ textAlign: "right" }}>
            {dec(r.pct_of_total, 1)}%
          </div>
        </div>
      ))}
    </div>
  );
}

export function Substitutions({ swaps, takeoff }) {
  if (!swaps?.length) {
    return (
      <p className="muted" style={{ paddingTop: 18, maxWidth: "62ch" }}>
        No substitutions apply yet. One appears when a counted quantity uses a
        material the factor store holds a like-for-like alternative for.
      </p>
    );
  }

  /* Two lines can offer the same swap, so each row names the element it would
   * change -- otherwise the list reads as a duplicate. */
  const elementOf = (lineId) => {
    const l = (takeoff?.lines || []).find((x) => x.id === lineId);
    return l ? titleCase(l.element_class) : lineId;
  };

  const ranked = [...swaps].sort(
    (a, b) => (a.delta_kg_co2e ?? 0) - (b.delta_kg_co2e ?? 0),
  );

  return (
    <div>
      {ranked.map((s) => {
        const d = s.delta_kg_co2e ?? 0;
        return (
          <div className="swap" key={`${s.line_id}-${s.to_material}`}>
            <div>
              <div style={{ fontWeight: 500 }}>
                {elementOf(s.line_id)}
                <span className="muted" style={{ fontWeight: 400 }}>
                  {" "}
                  — switch the mix
                </span>
              </div>
              <div className="el-desc">
                {s.from_material} → {s.to_material}
              </div>
            </div>
            <div>
              <div className={`swap-delta${d > 0 ? " swap-delta-worse" : ""}`}>
                {d > 0 ? "+" : "−"}
                {int(Math.abs(d))}
              </div>
              <div className="muted" style={{ fontSize: 11, textAlign: "right" }}>
                kg CO₂e · {dec(Math.abs(s.pct_of_total), 1)}% of total
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ app -- */


// How strong a trace is. These are different claims and the UI must not
// flatten them: measured_geometry means the outlined rectangles ARE the
// measurement, schedule_row means they are the text the figure was read from,
// and sheet_only means the region could not be found and nothing is outlined.
const TRACE_KIND = {
  measured_geometry: {
    label: "Measured here",
    blurb: "Each outline is one element whose size is in the quantity.",
  },
  schedule_row: {
    label: "Read from this",
    blurb: "The quantity was computed from the highlighted text.",
  },
  sheet_only: {
    label: "Sheet only",
    blurb:
      "This is the right sheet, but the exact region could not be located. Nothing is highlighted rather than pointing at a guess.",
  },
};

function TracePanel({ trace, onClose }) {
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), [trace?.lineId]);
  if (!trace) return null;

  const { lineId, label, regions, loading, error } = trace;
  const region = regions?.[page];
  const kind = TRACE_KIND[region?.kind] || TRACE_KIND.sheet_only;

  return (
    <div className="trace-scrim" onClick={onClose}>
      <div
        className="trace"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={`Where ${label} came from`}
      >
        <div className="trace-head">
          <div>
            <div className="eyebrow">Where this number came from</div>
            <div className="trace-title">{label || lineId}</div>
          </div>
          <button className="trace-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {loading && <div className="trace-body muted">Rendering the sheet…</div>}
        {error && <div className="trace-body notice-warn">{error}</div>}

        {region && (
          <>
            <div className="trace-meta">
              <span className={`trace-kind trace-kind-${region.kind}`}>
                {kind.label}
              </span>
              <span className="trace-sheet">
                {region.sheet_no || "—"} · page {region.page + 1}
              </span>
              {regions.length > 1 && (
                <span className="trace-pager">
                  {regions.map((r, i) => (
                    <button
                      key={r.page}
                      className={i === page ? "is-on" : ""}
                      onClick={() => setPage(i)}
                    >
                      {r.sheet_no || `p${r.page + 1}`}
                    </button>
                  ))}
                </span>
              )}
            </div>
            <p className="trace-note">{region.note || kind.blurb}</p>
            <div className="trace-body">
              {region.rects?.length ? (
                <img
                  className="trace-img"
                  src={`${API}${region.image_url}`}
                  alt={`Sheet ${region.sheet_no} with the measured region outlined`}
                />
              ) : (
                <div className="muted">
                  Nothing is highlighted on this sheet, by design.
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// Layers the drawings decline to specify. Not a substitution: a substitution
// replaces a material somebody chose, while this is a choice nobody has made,
// and showing them the same way would imply a decision exists where none does.
function OpenDecisions({ choices }) {
  if (!choices?.length) return null;
  return (
    <div className="decisions">
      {choices.map((c) => (
        <div className="decision" key={`${c.assembly_tag}-${c.category}`}>
          <div className="decision-head">
            <div>
              <span className="decision-cat">{c.category}</span>
              <span className="decision-tag">
                {c.assembly_tag} · {c.area_m2} m²
              </span>
            </div>
            <div className="decision-range">
              {int(c.low_kg_co2e)}–{int(c.high_kg_co2e)}
              <span className="muted"> kg CO₂e</span>
            </div>
          </div>
          <div className="decision-says">
            The drawings say “{c.drawing_says}” — the choice is still open, so
            nothing is added to the total until one is made.
          </div>
          <div className="decision-opts">
            {c.options.map((o) => (
              <div className="decision-opt" key={o.factor_id}>
                <span className="decision-opt-name">{o.name}</span>
                <span className="decision-opt-val">{int(o.kg_co2e)}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function App() {
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState(null);
  const [takeoff, setTakeoff] = useState(null);
  const [carbon, setCarbon] = useState(null);
  const [swaps, setSwaps] = useState([]);
  const [decisions, setDecisions] = useState([]);
  const [trace, setTrace] = useState(null);
  const [status, setStatus] = useState("connecting");
  const [error, setError] = useState(null);

  const showTrace = useCallback(
    async (lineId, provenance) => {
      if (!projectId || !lineId) return;
      const label =
        provenance?.detail ||
        (provenance?.sheet_no ? `Sheet ${provenance.sheet_no}` : lineId);
      setTrace({ lineId, label, regions: [], loading: true, error: null });
      try {
        const regions = await getJSON(`/projects/${projectId}/trace/${lineId}`);
        setTrace({ lineId, label, regions, loading: false, error: null });
      } catch (e) {
        setTrace({
          lineId,
          label,
          regions: [],
          loading: false,
          error: `Could not trace this line: ${e.message}`,
        });
      }
    },
    [projectId],
  );

  useEffect(() => {
    getJSON("/projects")
      .then((p) => {
        const list = Array.isArray(p) ? p : p.projects || [];
        setProjects(list);
        setStatus(list.length ? "ready" : "empty");
        if (list.length) setProjectId(pickInitial(list));
      })
      .catch((e) => {
        setError(e.message);
        setStatus("offline");
      });
  }, []);

  const load = useCallback(async (id) => {
    if (!id) return;
    setStatus("loading");
    setError(null);
    try {
      const t = await getJSON(`/projects/${id}/takeoff`);
      setTakeoff(t);
      const c = await getJSON(`/projects/${id}/carbon`);
      setCarbon(c);
      try {
        setSwaps(await getJSON(`/projects/${id}/substitutions`));
      } catch {
        setSwaps([]);
      }
      try {
        setDecisions(await getJSON(`/projects/${id}/unspecified`));
      } catch {
        setDecisions([]);
      }
      setStatus("ready");
    } catch (e) {
      setError(e.message);
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    if (projectId) load(projectId);
  }, [projectId, load]);

  const override = async (lineId, quantity) => {
    try {
      const res = await fetch(`${API}/projects/${projectId}/lines/${lineId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ quantity }),
      });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      setCarbon(await res.json());
      setTakeoff((t) =>
        t
          ? {
              ...t,
              lines: t.lines.map((l) =>
                l.id === lineId
                  ? { ...l, quantity, user_override: quantity }
                  : l,
              ),
            }
          : t,
      );
    } catch (e) {
      setError(`Could not save that quantity: ${e.message}`);
    }
  };

  const coverage = useMemo(() => {
    const g = (takeoff?.gaps || []).find((x) => /covers roughly (\d+)%/.test(x.message));
    if (!g) return takeoff ? 1 : null;
    return parseInt(g.message.match(/covers roughly (\d+)%/)[1], 10) / 100;
  }, [takeoff]);

  if (status === "offline") {
    return (
      <div className="field">
        <div className="masthead">
          <div className="wordmark">
            e<span>carbon</span>
          </div>
        </div>
        <div className="state">
          <div className="state-title">The reader is not running</div>
          <p className="muted">
            Start the service and this page will connect on its own.
          </p>
          <pre
            className="num"
            style={{
              marginTop: 16,
              padding: 12,
              background: "var(--paper-sunk)",
              border: "1px solid var(--hairline)",
              fontSize: 12.5,
              overflowX: "auto",
            }}
          >
            uvicorn ecarbon.api.main:app --reload
          </pre>
          <button
            className="btn btn-primary"
            style={{ marginTop: 18 }}
            onClick={() => window.location.reload()}
          >
            Try again
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="shell">
      <main className="field">
        <header className="masthead">
          <div className="wordmark">
            e<span>carbon</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            {projectId && status === "ready" && (
              <>
                {/* Plain links, not fetches: the browser already knows how to
                    save a file and open a printable page. */}
                <a
                  className="btn"
                  href={`${API}/projects/${encodeURIComponent(projectId)}/export.csv`}
                  style={{ textDecoration: "none" }}
                >
                  Download takeoff
                </a>
                <a
                  className="btn"
                  href={`${API}/projects/${encodeURIComponent(projectId)}/report.html`}
                  target="_blank"
                  rel="noreferrer"
                  style={{ textDecoration: "none" }}
                >
                  Open report
                </a>
              </>
            )}
            <span className="eyebrow">Plan set</span>
            <select
              className="picker"
              value={projectId || ""}
              onChange={(e) => setProjectId(e.target.value)}
              aria-label="Choose a plan set"
            >
              {projects.map((p) => {
                const id = p.id ?? p.project_id;
                return (
                  <option key={id} value={id}>
                    {prettyName(p.name || id)}
                  </option>
                );
              })}
            </select>
          </div>
        </header>

        {status === "loading" && (
          <div className="state">
            <div className="state-title">Reading the plan set</div>
            <p className="muted">
              Finding the sheets, calibrating scale, measuring the footprint.
            </p>
            <ScaleBar />
          </div>
        )}

        {status === "empty" && (
          <div className="state">
            <div className="state-title">No plan sets yet</div>
            <p className="muted">
              Point the service at a catalogue directory and the sets will be
              listed here.
            </p>
          </div>
        )}

        {error && status !== "loading" && (
          <div className="notice">
            <div className="notice-head">Something went wrong</div>
            <div>{error}</div>
          </div>
        )}

        {status === "ready" && takeoff && (
          <>
            <Hero carbon={carbon} takeoff={takeoff} />

            <section className="section">
              <div className="section-head">
                <h2 className="sheet-title">What we could not read</h2>
                <span className="eyebrow">
                  {takeoff.gaps?.length || 0} notices
                </span>
              </div>
              {takeoff.gaps?.length ? (
                <Notices gaps={takeoff.gaps} />
              ) : (
                <p className="muted" style={{ paddingTop: 18 }}>
                  Every sheet this takeoff needed was readable.
                </p>
              )}
            </section>

            <section className="section">
              <div className="section-head">
                <h2 className="sheet-title">Bill of quantities</h2>
                <span className="eyebrow">
                  Click a sheet tag to see where a number came from
                </span>
              </div>
              <BillOfQuantities
                takeoff={takeoff}
                carbon={carbon}
                onOverride={override}
                onTrace={showTrace}
              />
            </section>

            {carbon?.by_material_category?.length ? (
              <section className="section">
                <div className="section-head">
                  <h2 className="sheet-title">Where the carbon is</h2>
                  <span className="eyebrow">By material</span>
                </div>
                <Contribution carbon={carbon} />
              </section>
            ) : null}

            {decisions.length ? (
              <section className="section">
                <div className="section-head">
                  <h2 className="sheet-title">Decisions still open</h2>
                  <span className="eyebrow">
                    Not counted in the total · priced as a range
                  </span>
                </div>
                <OpenDecisions choices={decisions} />
              </section>
            ) : null}

            <section className="section">
              <div className="section-head">
                <h2 className="sheet-title">Material substitutions</h2>
                <span className="eyebrow">Ranked by what they save</span>
              </div>
              <Substitutions swaps={swaps} takeoff={takeoff} />
            </section>
            <TracePanel trace={trace} onClose={() => setTrace(null)} />
          </>
        )}
      </main>

      <TitleBlock takeoff={takeoff} carbon={carbon} coverage={coverage} />
    </div>
  );
}
