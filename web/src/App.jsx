/* ecarbon — reading a drawing set into a carbon figure you can argue with.
 *
 * The ordering of this page is the argument: what we could not read comes
 * before the number, the number is given twice because one of its lines is
 * measured rather than stated, and every quantity carries the sheet it came
 * from as a control you can press.
 *
 * Styling lives in index.css as classes, where the type scale and the colour
 * meanings can be held in one place.
 */

import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

// Same origin in a build, because the service serves this bundle itself.
// Hardcoding the dev address once shipped an interface that called the
// *viewer's* localhost: every request failed for anyone but the developer,
// while curl against the deployment worked perfectly and hid it.
const API = import.meta.env.DEV ? "http://127.0.0.1:8000" : "";

// Mirrors PARTITION_LINE_PREFIX in ecarbon/takeoff/builder.py.
const PARTITION_PREFIX = "ln-interior-partition";

/* ------------------------------------------------------------ plumbing -- */

// Credentials are held for the tab and sent explicitly on every request.
// Relying on the browser's own basic-auth cache is not safe enough: the page
// loads while every fetch comes back 401, which renders as a dead app and
// looks exactly like a broken deployment.
let AUTH = sessionStorage.getItem("ecarbon-auth") || "";

export function setAuth(user, password) {
  AUTH = "Basic " + btoa(`${user}:${password}`);
  try {
    sessionStorage.setItem("ecarbon-auth", AUTH);
  } catch {
    // A private window can refuse storage; the value still works for this tab.
  }
}

export function clearAuth() {
  AUTH = "";
  try {
    sessionStorage.removeItem("ecarbon-auth");
  } catch {
    /* nothing to clear */
  }
}

class Unauthorized extends Error {}

async function getJSON(path) {
  const res = await fetch(`${API}${path}`, {
    headers: AUTH ? { Authorization: AUTH } : {},
  });
  if (res.status === 401) throw new Unauthorized("Credentials required");
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} on ${path}`);
  return res.json();
}

async function postJSON(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(AUTH ? { Authorization: AUTH } : {}),
    },
    body: JSON.stringify(body),
  });
  if (res.status === 401) throw new Unauthorized("Credentials required");
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// A rendered sheet is an <img src>, which cannot carry a header, so the
// credential rides the query string instead. Same origin, same gate.
export function authedUrl(path) {
  if (!AUTH) return `${API}${path}`;
  const joiner = path.includes("?") ? "&" : "?";
  return `${API}${path}${joiner}auth=${encodeURIComponent(AUTH.slice(6))}`;
}

const int = (n) => (n == null ? "—" : Math.round(n).toLocaleString());

// Motion is suppressed wherever a reader has asked for that, so this is
// checked once rather than at every call site.
const STILL =
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** A number that counts up to its value, easing out.
 *
 * The headline is the thing a reader looks at first, and a figure that
 * arrives reads as a figure that was computed. It is 700 ms, once, on load
 * and on project change -- not a flourish repeated on every render, which
 * would make the page feel busy rather than alive.
 */
function useCountUp(value, duration = 700) {
  const [shown, setShown] = useState(value ?? 0);
  const from = useRef(0);

  useEffect(() => {
    if (value == null) return;
    if (STILL) {
      setShown(value);
      return;
    }
    const start = performance.now();
    const origin = from.current;
    const delta = value - origin;
    let raf = 0;
    const tick = (now) => {
      const t = Math.min(1, (now - start) / duration);
      // easeOutCubic: fast enough to feel immediate, settled enough to read.
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(origin + delta * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
      else from.current = value;
    };
    raf = requestAnimationFrame(tick);

    // A headline stuck partway through counting is a wrong number on screen.
    // requestAnimationFrame stops in a background tab and does not advance
    // reliably under headless capture, so the true value is written once the
    // animation should have finished whatever happened to the frames.
    const settle = setTimeout(() => {
      cancelAnimationFrame(raf);
      from.current = value;
      setShown(value);
    }, duration + 120);

    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(settle);
    };
  }, [value, duration]);

  return shown;
}
const dec = (n, p = 1) => (n == null ? "—" : Number(n).toFixed(p));
// A carbon line is counted when it carries a figure. `is_counted` exists on
// the Python model as a property and is never serialised, so testing it here
// silently marked every line uncounted -- which read as "0 of 20 counted" and
// quietly suppressed the without-partitions total.
const isCounted = (line) => line.kg_co2e != null;
const titleCase = (s) =>
  String(s || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());

// Which plan set to open on. `?plan=` wins so a demo or a bug report can
// deep-link an exact design; otherwise prefer a multi-storey set over an ADU,
// because a single-storey plan yields fewer than two floor datums and so has
// no wall height, no wall, floor or partition area, and a thin bill.
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

/* -------------------------------------------------------------- pieces -- */

const CONFIDENCE = {
  measured: "chip-measured",
  inferred: "chip-inferred",
  assumed: "chip-assumed",
};

function Confidence({ value }) {
  return <span className={`chip ${CONFIDENCE[value] || "chip-assumed"}`}>{value}</span>;
}

// The sheet tag is the trace control. It is styled like the stamp it refers
// to so that pressing it feels like reaching for the drawing.
function Citation({ provenance, onTrace, lineId }) {
  const sheet = provenance?.sheet_no;
  if (!sheet) return <span className="cite-none">no sheet recorded</span>;
  return (
    <button
      className="cite"
      onClick={() => onTrace?.(lineId, provenance)}
      title={`Show where this came from on sheet ${sheet}`}
    >
      <span className="cite-sheet">{sheet}</span>
      <span className="cite-detail" title={provenance.detail || ""}>
        {provenance.detail || `page ${provenance.page + 1}`}
      </span>
    </button>
  );
}

// Intensity is only as good as its denominator, and the denominator is the
// one project fact the drawings may not state. Where the measured area and
// the stated area disagree, say which is in use before it is read.
function floorAreaNote(gaps) {
  const list = gaps || [];
  if (list.some((g) => String(g.message).startsWith("Floor area: using")))
    return "measured from the drawings — whole block, confirm this";
  if (list.some((g) => String(g.message).includes("kgCO2e/m2 is not possible")))
    return "check this — the intensity it gives is impossible";
  return null;
}

function TitleBlock({ takeoff, carbon, coverage }) {
  const p = takeoff?.project || {};
  const sheets = takeoff?.sheets || [];
  const readable = sheets.filter((s) => s.readable).length;
  const areaNote = floorAreaNote(takeoff?.gaps);
  const pct = coverage == null ? null : Math.round(coverage * 100);

  const rows = [
    [
      "Project",
      (p.name || "—")
        .replace(/_/g, " ")
        .replace(/\s*Technical Design Package$/i, ""),
    ],
    ["Location", p.jurisdiction || "—"],
    [
      "Floor area",
      <>
        {p.gfa_m2 ? `${dec(p.gfa_m2, 1)} m²` : "—"}
        {p.gfa_basis ? ` · ${p.gfa_basis}` : ""}
        {areaNote && <span className="tb-flag">{areaNote}</span>}
      </>,
    ],
    ["Storeys / units", `${p.storeys || "—"} / ${p.units || "—"}`],
    ["Sheets read", `${readable} of ${sheets.length}`],
    ["Module scope", carbon?.modules?.join(" · ") || "—"],
    [
      "Element coverage",
      <>
        {pct == null ? "—" : `${pct}% of carbon`}
        <span className="meter">
          <i style={{ width: `${pct ?? 0}%` }} />
        </span>
      </>,
    ],
    ["Factor sources", carbon?.factor_sources?.join(", ") || "Kootenay · BEAM · EC3"],
  ];

  return (
    <aside className="card titleblock">
      {rows.map(([label, value]) => (
        <div className="tb-row" key={label}>
          <span className="tb-label">{label}</span>
          <span className="tb-value">{value}</span>
        </div>
      ))}
    </aside>
  );
}

function Hero({ carbon, takeoff, coverage }) {
  const shownTotal = useCountUp(carbon?.total_kg_co2e);
  const counted = (carbon?.lines || []).filter(isCounted).length;
  const measured = (takeoff?.lines || []).filter(
    (l) => l.confidence === "measured",
  ).length;

  // Carbon carried by the interior-partition lines. Their run length is
  // measured off the drawing rather than stated by a schedule, so the total
  // is shown both ways instead of asking the reader to take one on trust.
  const partitions = (carbon?.lines || [])
    .filter((l) => isCounted(l) && String(l.line_id).startsWith(PARTITION_PREFIX))
    .reduce((sum, l) => sum + (l.kg_co2e || 0), 0);

  return (
    <section className="card hero">
      <div className="hero-top">
        <div>
          <div className="figure">
            {carbon?.total_kg_co2e == null ? "—" : int(shownTotal)}
            <span className="figure-unit">kg CO₂e</span>
          </div>
          <div className="chips">
            <span className="chip chip-scope">
              {carbon?.modules?.length
                ? `modules ${carbon.modules.join("–")} · product stage only`
                : "module scope unknown"}
            </span>
            {coverage != null && coverage < 1 && (
              <span className="chip chip-danger">
                partial · {Math.round(coverage * 100)}% of the building
              </span>
            )}
          </div>
        </div>
      </div>

      {partitions > 0 && (
        <div className="alt-total">
          <span className="alt-total-figure">
            {int(carbon.total_kg_co2e - partitions)}
          </span>
          <span className="alt-total-note">
            without the inferred interior partitions, measured from the plan
            linework rather than read from a schedule. Both are given because
            that run is the least certain quantity here.
          </span>
        </div>
      )}

      <div className="kpis">
        <div className="kpi" style={{ "--i": 0 }}>
          <div className="kpi-label">Intensity</div>
          <div className="kpi-value">{dec(carbon?.intensity_kg_co2e_per_m2, 1)}</div>
          <div className="kpi-sub">kg/m² {carbon?.intensity_basis || ""}</div>
        </div>
        <div className="kpi" style={{ "--i": 1 }}>
          <div className="kpi-label">Counted</div>
          <div className="kpi-value">{counted}</div>
          <div className="kpi-sub">of {takeoff?.lines?.length ?? 0} lines</div>
        </div>
        <div className="kpi" style={{ "--i": 2 }}>
          <div className="kpi-label">Measured</div>
          <div className="kpi-value">{measured}</div>
          <div className="kpi-sub">from geometry</div>
        </div>
        <div className="kpi" style={{ "--i": 3 }}>
          <div className="kpi-label">Notices</div>
          <div className="kpi-value">{takeoff?.gaps?.length ?? 0}</div>
          <div className="kpi-sub">things we could not read</div>
        </div>
      </div>
    </section>
  );
}

/* --------------------------------------------------------------- charts -- */

const SERIES = [
  "#1e40af", "#2563eb", "#3b82f6", "#60a5fa",
  "#0891b2", "#0d9488", "#b45309", "#94a3b8",
];

// Hand-drawn rather than pulled from a chart library: eight segments and a
// bar list do not justify the bundle, and this way the palette is the same
// one the confidence chips use.
function Contribution({ carbon, focus, onFocus, filter, onFilter }) {
  const rows = (carbon?.by_material_category || []).slice(0, 8);
  const total = rows.reduce((sum, r) => sum + (r.kg_co2e || 0), 0);
  if (!rows.length) return null;

  const R = 68;
  const C = 2 * Math.PI * R;
  let running = 0;
  const segments = rows.map((row, i) => {
    const frac = total ? (row.kg_co2e || 0) / total : 0;
    const seg = { row, i, dash: frac * C, offset: running };
    running += frac * C;
    return seg;
  });

  // Focus is the material key rather than an index, because the bill, the
  // donut and the bars are three views of the same thing and an index means
  // nothing outside this component.
  const hover = focus == null ? null : rows.findIndex((r) => r.key === focus);
  const active = hover >= 0 ? rows[hover] : null;

  return (
    <div className="charts">
      <div className="donut-wrap">
        <div className={`donut${active ? " has-hover" : ""}`}>
          <svg
            width="190"
            height="190"
            viewBox="0 0 190 190"
            role="img"
            aria-label="Carbon by material category"
          >
            {segments.map(({ row, i, dash, offset }) => (
              <circle
                key={row.key}
                className={`donut-seg${hover === i ? " is-hover" : ""}`}
                cx="95"
                cy="95"
                r={R}
                fill="none"
                stroke={SERIES[i % SERIES.length]}
                strokeWidth="24"
                strokeDasharray={`${dash} ${C - dash}`}
                strokeDashoffset={-offset}
                onMouseEnter={() => onFocus(row.key)}
                onMouseLeave={() => onFocus(null)}
                onClick={() => onFilter(filter === row.key ? null : row.key)}
              />
            ))}
          </svg>
          <div className="donut-centre">
            <b>{active ? `${dec(active.pct_of_total, 1)}%` : int(total)}</b>
            <span>{active ? active.key : "kg CO₂e counted"}</span>
          </div>
        </div>
      </div>

      <div className="bars">
        {rows.map((row, i) => (
          <div
            className={`bar-row${filter === row.key ? " is-filtered" : ""}`}
            key={row.key}
            style={{ "--i": i }}
            onMouseEnter={() => onFocus(row.key)}
            onMouseLeave={() => onFocus(null)}
            onClick={() => onFilter(filter === row.key ? null : row.key)}
            title={
              filter === row.key
                ? "Show every line again"
                : "Show only the lines made of this"
            }
          >
            <span className="bar-name" title={row.key}>{row.key}</span>
            <span className="bar-track">
              <i
                style={{
                  width: `${row.pct_of_total}%`,
                  background: SERIES[i % SERIES.length],
                }}
              />
            </span>
            <span className="bar-value">{dec(row.pct_of_total, 1)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------- notices -- */

function Notices({ gaps }) {
  // Nineteen notices, most of them near-identical, pushed the bill of
  // quantities below two screens of repeated text. Nothing is dropped --
  // honesty is the point of this panel -- but repeats of one kind collapse
  // behind a count so the distinct problems are read first.
  const [expanded, setExpanded] = useState({});
  if (!gaps?.length) return null;

  const rank = { blocking: 0, warning: 1, info: 2 };
  const sorted = [...gaps].sort(
    (a, b) => (rank[a.severity] ?? 3) - (rank[b.severity] ?? 3),
  );

  const groups = [];
  const seen = new Map();
  for (const gap of sorted) {
    const key = `${gap.severity}:${gap.code}`;
    if (gap.severity === "blocking" || !seen.has(key)) {
      const group = { key, severity: gap.severity, code: gap.code, items: [gap] };
      if (gap.severity !== "blocking") seen.set(key, group);
      groups.push(group);
    } else {
      seen.get(key).items.push(gap);
    }
  }

  const SHOWN = 2;
  return (
    <div className="notices">
      {groups.map((group) => {
        const open = expanded[group.key];
        const shown = open ? group.items : group.items.slice(0, SHOWN);
        const hidden = group.items.length - shown.length;
        return (
          <Fragment key={group.key}>
            {shown.map((gap, i) => (
              <div className={`notice notice-${gap.severity || "info"}`} key={i}>
                <div className="notice-head">
                  {gap.severity === "blocking" ? "Read this first" : "Worth knowing"}
                  {" · "}
                  {(gap.code || "").replace(/_/g, " ")}
                </div>
                <div className="notice-body">{gap.message}</div>
              </div>
            ))}
            {hidden > 0 && (
              <button
                className="notice-more"
                onClick={() => setExpanded((e) => ({ ...e, [group.key]: true }))}
              >
                + {hidden} more of the same kind (
                {(group.code || "").replace(/_/g, " ")})
              </button>
            )}
          </Fragment>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ BoQ -- */

// Twenty lines, each two rows tall with its derivation control, put the
// substitutions and the open decisions four thousand pixels down the page.
// Eight is enough to show the shape of a bill -- measured, inferred and
// assumed, with and without a factor -- and the rest is one press away.
const BILL_PREVIEW = 8;

function BillOfQuantities({
  takeoff,
  carbon,
  onOverride,
  onTrace,
  focus,
  onFocus,
  filter,
}) {
  const [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState("");
  const [open, setOpen] = useState({});
  const [showAll, setShowAll] = useState(false);

  const byLine = useMemo(() => {
    const map = {};
    for (const line of carbon?.lines || []) map[line.line_id] = line;
    return map;
  }, [carbon]);

  const commit = async (line) => {
    const value = parseFloat(draft);
    setEditing(null);
    if (!Number.isFinite(value) || value < 0 || value === line.quantity) return;
    await onOverride(line.id, value);
  };

  return (
    <div className="table-scroll">
      <table className="boq">
        <thead>
          <tr>
            <th>Element</th>
            <th className="r">Quantity</th>
            <th>Basis</th>
            <th>Source</th>
            <th className="r">kg CO₂e</th>
          </tr>
        </thead>
        <tbody>
          {(showAll
            ? takeoff?.lines || []
            : (takeoff?.lines || []).slice(0, BILL_PREVIEW)
          ).map((line) => {
            const result = byLine[line.id];
            const edited = line.user_override != null;
            const material = result?.factor?.name || null;
            // Dimmed rather than removed: a filtered bill that silently drops
            // rows would let a reader think the total only covers what is on
            // screen.
            const dimmed = filter != null && material !== filter;
            const lit = focus != null && material === focus;
            return (
              <tr
                key={line.id}
                className={`${dimmed ? "is-dimmed" : ""}${lit ? " is-lit" : ""}`}
                onMouseEnter={() => material && onFocus(material)}
                onMouseLeave={() => onFocus(null)}
              >
                <td>
                  <div className="el-name">
                    {titleCase(line.element_class)}
                    {line.assembly_tag && (
                      <span className="el-tag">{line.assembly_tag}</span>
                    )}
                  </div>
                  {line.description && (
                    <div className="el-desc">{line.description}</div>
                  )}
                  {(line.assumptions?.length || line.basis?.note) && (
                    <>
                      <div
                        className="derivation"
                        onClick={() =>
                          setOpen((o) => ({ ...o, [line.id]: !o[line.id] }))
                        }
                      >
                        {open[line.id] ? "▾" : "▸"} how this was derived
                      </div>
                      {open[line.id] && (
                        <div className="derivation-body">
                          {line.basis?.note && <div>{line.basis.note}</div>}
                          {line.assumptions?.length > 0 && (
                            <ul>
                              {line.assumptions.map((a, i) => (
                                <li key={i}>{a}</li>
                              ))}
                            </ul>
                          )}
                        </div>
                      )}
                    </>
                  )}
                </td>

                <td className="r">
                  {editing === line.id ? (
                    <input
                      className="qty-input"
                      autoFocus
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      onBlur={() => commit(line)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") commit(line);
                        if (e.key === "Escape") setEditing(null);
                      }}
                    />
                  ) : (
                    <span className={`qty${edited ? " qty-edited" : ""}`}>
                      <button
                        className="qty-btn"
                        title={
                          edited
                            ? `Your figure. We read ${dec(line.quantity, 2)} ${line.unit}.`
                            : "Correct this quantity"
                        }
                        onClick={() => {
                          setEditing(line.id);
                          setDraft(String(line.user_override ?? line.quantity));
                        }}
                      >
                        {/* The effective quantity, not the original. Showing
                            line.quantity after an override left the number we
                            read on screen beside a total computed from the
                            number the reader typed. */}
                        {dec(edited ? line.user_override : line.quantity, 2)}
                      </button>
                      <span className="qty-unit">{line.unit}</span>
                      {edited && (
                        <span className="qty-was">
                          we read {dec(line.quantity, 2)}
                        </span>
                      )}
                    </span>
                  )}
                </td>

                <td><Confidence value={line.confidence} /></td>

                <td>
                  <Citation
                    provenance={line.provenance}
                    onTrace={onTrace}
                    lineId={line.id}
                  />
                </td>

                <td className="r">
                  {result && isCounted(result) ? (
                    <span className="carbon">{int(result.kg_co2e)}</span>
                  ) : (
                    <span
                      className="carbon-none"
                      title={result?.missing_reason || "no factor"}
                    >
                      not counted
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {(takeoff?.lines?.length || 0) > BILL_PREVIEW && (
        <button className="bill-more" onClick={() => setShowAll((v) => !v)}>
          {showAll
            ? `Show the first ${BILL_PREVIEW} lines`
            : `Show all ${takeoff.lines.length} lines · ${
                takeoff.lines.length - BILL_PREVIEW
              } more`}
        </button>
      )}
    </div>
  );
}

/* ------------------------------------------------------- open decisions -- */

// Not a substitution: a substitution replaces a material somebody chose,
// while this is a choice nobody has made. Showing them the same way would
// imply a decision exists where none does.
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
            </div>
          </div>
          <div className="decision-says">
            The drawings say “{c.drawing_says}” — the choice is still open, so
            nothing is added to the total until one is made.
          </div>
          <div className="decision-opts">
            {c.options.map((o) => (
              <div className="decision-opt" key={o.factor_id}>
                <span>{o.name}</span>
                <b>{int(o.kg_co2e)}</b>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function Substitutions({ swaps, takeoff }) {
  if (!swaps?.length)
    return <div className="notices muted">No swaps apply to this design.</div>;
  const nameOf = (id) => {
    const line = (takeoff?.lines || []).find((l) => l.id === id);
    return line ? titleCase(line.element_class) : id;
  };
  return (
    <div className="swaps">
      {swaps.slice(0, 8).map((s, i) => (
        <div className="swap" key={`${s.line_id}-${i}`}>
          <div>
            <div className="swap-el">{nameOf(s.line_id)}</div>
            <div className="swap-move">
              {s.from_material} → {s.to_material}
            </div>
          </div>
          <div className="swap-delta">
            {int(s.delta_kg_co2e)}
            <span className="swap-pct">{dec(s.pct_of_total, 1)}% of total</span>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- trace -- */

// How strong a trace is. These are different claims and the interface must
// not flatten them.
const TRACE_KIND = {
  measured_geometry: {
    label: "Measured here",
    cls: "chip-measured",
    blurb: "Each outline is one element whose size is in the quantity.",
  },
  schedule_row: {
    label: "Read from this",
    cls: "chip-inferred",
    blurb: "The quantity was computed from the highlighted text.",
  },
  sheet_only: {
    label: "Sheet only",
    cls: "chip-assumed",
    blurb:
      "The right sheet, but the exact region could not be located. Nothing is highlighted rather than pointing at a guess.",
  },
};

// The sheet is fetched clean and the regions are drawn over it as SVG, so
// the outline stays sharp at any zoom and can be animated. Opening zoomed to
// the measured region is the point: a 36x24 inch sheet scaled to fit a
// dialog shows a grey haze, and the whole claim of this panel is that you can
// see the thing that was measured.
function TracePanel({ trace, onClose }) {
  const [page, setPage] = useState(0);
  const [whole, setWhole] = useState(false);
  const [drawn, setDrawn] = useState(false);

  useEffect(() => {
    setPage(0);
    setWhole(false);
  }, [trace?.lineId]);

  useEffect(() => {
    setDrawn(false);
    const id = setTimeout(() => setDrawn(true), 120);
    return () => clearTimeout(id);
  }, [page, whole, trace?.lineId]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!trace) return null;

  const { lineId, label, regions, loading, error } = trace;
  const region = regions?.[page];
  const kind = TRACE_KIND[region?.kind] || TRACE_KIND.sheet_only;

  // The viewBox is the measured region with a margin, or the whole sheet.
  // Everything else -- image placement, stroke widths -- follows from it, so
  // zooming is one number rather than a transform stack.
  const view = (() => {
    const W = region?.page_width || 0;
    const H = region?.page_height || 0;
    if (!W || !H) return null;
    const rects = region.rects || [];
    if (whole || !rects.length) return { x: 0, y: 0, w: W, h: H, full: true };
    const x0 = Math.min(...rects.map((r) => r[0]));
    const y0 = Math.min(...rects.map((r) => r[1]));
    const x1 = Math.max(...rects.map((r) => r[2]));
    const y1 = Math.max(...rects.map((r) => r[3]));
    // Breathing room so the region is legible in context rather than cropped
    // to its own edges, and a floor so a single thin wall is not magnified
    // into abstraction.
    const pad = Math.max((x1 - x0) * 0.6, (y1 - y0) * 0.6, 90);
    const x = Math.max(0, x0 - pad);
    const y = Math.max(0, y0 - pad);
    return {
      x,
      y,
      w: Math.min(W - x, x1 - x0 + pad * 2),
      h: Math.min(H - y, y1 - y0 + pad * 2),
      full: false,
    };
  })();

  // The outline uses vector-effect: non-scaling-stroke, so this width is in
  // screen pixels and stays constant however far the view zooms. Computing it
  // from the viewBox -- as page units -- drew an 8 px slab over the very wall
  // it was pointing at.
  const stroke = 2.4;

  return (
    <div className="scrim" onClick={onClose}>
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

        {loading && (
          <div className="trace-body">
            <div className="skeleton" style={{ height: 340 }} />
          </div>
        )}
        {error && <div className="trace-body muted">{error}</div>}

        {region && (
          <>
            <div className="trace-meta">
              <span className={`chip ${kind.cls}`}>{kind.label}</span>
              <span className="trace-sheet">
                {region.sheet_no || "—"} · page {region.page + 1}
              </span>
              {region.rects?.length > 0 && (
                <button
                  className="trace-zoom"
                  onClick={() => setWhole((w) => !w)}
                >
                  {whole ? "Zoom to the measurement" : "Show the whole sheet"}
                </button>
              )}
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
              {view ? (
                <svg
                  className="trace-sheetview"
                  viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
                  preserveAspectRatio="xMidYMid meet"
                  role="img"
                  aria-label={`Sheet ${region.sheet_no}${
                    region.rects?.length
                      ? ` with ${region.rects.length} measured region(s) outlined`
                      : ""
                  }`}
                >
                  <image
                    href={authedUrl(
                      `/projects/${trace.projectId}/trace/${lineId}/image.png` +
                        `?page=${region.page}&dpi=120&highlight=0`,
                    )}
                    x="0"
                    y="0"
                    width={region.page_width}
                    height={region.page_height}
                  />
                  {(region.rects || []).map((r, i) => {
                    const w = r[2] - r[0];
                    const h = r[3] - r[1];
                    const perimeter = 2 * (w + h);
                    return (
                      <rect
                        key={i}
                        className="trace-rect"
                        x={r[0]}
                        y={r[1]}
                        width={w}
                        height={h}
                        strokeWidth={stroke}
                        strokeDasharray={perimeter}
                        strokeDashoffset={drawn ? 0 : perimeter}
                        style={{ transitionDelay: `${Math.min(i * 22, 500)}ms` }}
                      />
                    );
                  })}
                </svg>
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

/* ------------------------------------------------------------- sign in -- */

function SignIn({ onDone }) {
  const [user, setUser] = useState("judge");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setFailed(false);
    try {
      const res = await fetch(`${API}/projects`, {
        headers: { Authorization: "Basic " + btoa(`${user}:${password}`) },
      });
      if (!res.ok) throw new Error("rejected");
      setAuth(user, password);
      onDone();
    } catch {
      clearAuth();
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="centre">
      <div className="card panel" style={{ padding: 32 }}>
        <h2>Sign in</h2>
        <p>
          This service reads licence-restricted drawings, so it is not open to
          the web. Use the credentials supplied with the submission.
        </p>
        <form onSubmit={submit} className="form">
          <label>
            <span className="eyebrow">User</span>
            <input value={user} onChange={(e) => setUser(e.target.value)} />
          </label>
          <label>
            <span className="eyebrow">Password</span>
            <input
              type="password"
              value={password}
              autoFocus
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <button
            className="btn btn-primary"
            type="submit"
            disabled={busy || !password}
          >
            {busy ? "Checking…" : "Open"}
          </button>
        </form>
        {failed && (
          <p className="form-fail">
            Those credentials were refused. Check them and try again.
          </p>
        )}
      </div>
    </div>
  );
}




/* ------------------------------------------------------------- massing -- */

// An axonometric, drawn in SVG, rather than a 3D engine.
//
// Three.js would be ~600 kB against a 260 kB bundle to show a box with
// internal walls. An axonometric is also how a building is drawn rather than
// rendered, which is the right register for a tool whose subject is drawings:
// this is a reading of a plan set, not a visualisation of a house.
//
// Nothing here is decorative. The footprint is measured from the linework,
// the storey heights come from the section datums, and every wall is one of
// the partitions counted in the bill. So a wrong reading shows up as a wrong
// shape -- on AB_ADU_02, where partitions over-detect by 92%, you can see
// walls standing where no walls are.

// A sequential ramp, cool to warm. The legend carries the figures beside
// every swatch, so colour is a way in rather than the evidence.
//
// It is driven by carbon per square metre of surface, not by totals. Totals
// made almost the whole drawing red: exterior wall, partitions and slab come
// to 12,305, 11,078 and 10,909 kgCO2e -- within 13% of each other -- and they
// happen to be the three most visible surfaces, so a ramp scaled to the
// largest painted everything at the top of it. Intensity is also the more
// honest thing to show spatially: it says this surface is carbon-dense, not
// that there is a lot of this surface.
// Blue through yellow to red, with no green in it. Green at the midpoint
// reads as "fine", and nothing here is making that judgement -- the ramp
// says denser or lighter, not better or worse.
const HEAT = ["#bfdbfe", "#7dd3fc", "#fde047", "#fbbf24", "#f97316", "#dc2626"];

function heatColour(value, max, min = 0) {
  if (!max || value == null) return "#e2e8f0";
  // Scaled across the observed range rather than from zero, so the coolest
  // surface is visibly cool instead of merely less red than the rest.
  const span = max - min || max;
  const t = Math.max(0, Math.min(1, (value - min) / span));
  const step = (HEAT.length - 1) * t;
  const i = Math.min(HEAT.length - 2, Math.floor(step));
  const f = step - i;
  const lerp = (a, b) => Math.round(a + (b - a) * f);
  const hex = (c) => [1, 3, 5].map((k) => parseInt(c.slice(k, k + 2), 16));
  const [r1, g1, b1] = hex(HEAT[i]);
  const [r2, g2, b2] = hex(HEAT[i + 1]);
  return `rgb(${lerp(r1, r2)} ${lerp(g1, g2)} ${lerp(b1, b2)})`;
}

const CLASS_LABEL = {
  exterior_wall: "Exterior wall",
  interior_partition: "Interior partitions",
  slab_on_grade: "Slab on grade",
  footing: "Footings",
  roof_assembly: "Roof",
  floor_assembly: "Floors",
  door: "Doors",
  window: "Windows",
};

// A general axonometric rather than a fixed isometric, so the view can turn.
// Azimuth spins about the vertical axis; elevation is how far above the
// building the viewer sits. Both are plain angles, which keeps the depth sort
// below honest -- it uses the same rotated coordinate the projection does,
// rather than a constant that only held at 45 degrees.
const ELEVATION = Math.sin(Math.PI / 6);

function rotate(x, y, azimuth) {
  const c = Math.cos(azimuth);
  const sn = Math.sin(azimuth);
  return [x * c - y * sn, x * sn + y * c];
}

function project(x, y, z, s, azimuth = Math.PI / 4) {
  const [rx, ry] = rotate(x, y, azimuth);
  return [rx * s, (ry * ELEVATION - z) * s];
}

// How far into the scene a point sits, for the painter's algorithm. Larger is
// nearer the viewer, so faces sort ascending and the near ones land last.
function depthOf(x, y, z, azimuth) {
  const [, ry] = rotate(x, y, azimuth);
  return ry + z * 0.001;
}

function face(points, fill, stroke, key, opacity = 1) {
  return (
    <polygon
      key={key}
      points={points.map(([a, b]) => `${a.toFixed(2)},${b.toFixed(2)}`).join(" ")}
      fill={fill}
      stroke={stroke}
      strokeWidth="0.6"
      strokeLinejoin="round"
      opacity={opacity}
    />
  );
}

function Massing({ massing }) {
  const [storey, setStorey] = useState(null); // null = every storey
  // Dragging turns the building. Held in a ref as well as state so the
  // pointer handlers do not need to be rebound on every frame of a drag.
  // `?turn=<degrees>` sets the opening angle, so a demo can link to a
  // viewpoint and so the rotation can be reviewed in a screenshot at all.
  const [azimuth, setAzimuth] = useState(() => {
    const turn = new URLSearchParams(window.location.search).get("turn");
    const deg = turn == null ? null : Number(turn);
    return Number.isFinite(deg) ? (deg * Math.PI) / 180 : Math.PI / 4;
  });
  const drag = useRef(null);
  const [mode, setMode] = useState(
    // `?view=carbon` opens on the heat map, so the demo can link to it and so
    // it can be reviewed in a screenshot at all.
    () =>
      new URLSearchParams(window.location.search).get("view") === "carbon"
        ? "carbon"
        : "structure",
  );

  if (!massing) return null;
  const {
    width_m: W,
    depth_m: D,
    storey_heights_m: heights,
    walls,
    note,
    carbon_by_class: carbon = {},
  } = massing;
  if (!W || !D || !heights?.length) return null;

  const s = 15;
  const WALL_H = 0.82;
  const heat = mode === "carbon";

  // Storey datums first: the surface areas below are computed from the
  // building's height, and a const read above its declaration is a temporal
  // dead zone error that blanks the entire page rather than warning.
  let z = 0;
  const datums = [0];
  for (const h of heights) {
    z += h;
    datums.push(z);
  }
  const total = z;

  // Carbon per square metre of the surface we actually draw for each class.
  // Totals answer "how much of this is there"; intensity answers "how heavy
  // is this surface", which is the question a picture of a building can
  // usefully show.
  const wallFace = walls.reduce(
    (sum, w) =>
      sum + 2 * Math.max(w.w, w.d) * (heights[w.storey] ?? 3) * WALL_H,
    0,
  );
  const floorArea = W * D;
  const area = {
    slab_on_grade: floorArea,
    exterior_wall: 2 * (W + D) * total,
    interior_partition: wallFace,
    roof_assembly: floorArea,
    floor_assembly: floorArea * Math.max(1, heights.length - 1),
  };
  const intensity = {};
  for (const [cls, kg] of Object.entries(carbon)) {
    if (area[cls]) intensity[cls] = kg / area[cls];
  }
  const values = Object.values(intensity);
  const hotI = values.length ? Math.max(...values) : 1;
  const coolI = values.length ? Math.min(...values) : 0;

  // In carbon mode a surface takes the colour of its intensity; in structure
  // mode the colour that makes the building readable.
  const tone = (cls, fallback) =>
    heat && intensity[cls] != null
      ? heatColour(intensity[cls], hotI, coolI)
      : heat
        ? "#e2e8f0"
        : fallback;

  const shapes = [];
  const p3 = (X, Y, Z) => project(X, Y, Z, s, azimuth);

  const onPointerDown = (e) => {
    drag.current = { x: e.clientX, from: azimuth };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e) => {
    if (!drag.current) return;
    // A full turn across roughly the width of the view, so a short drag is a
    // small adjustment rather than a spin.
    setAzimuth(drag.current.from + (e.clientX - drag.current.x) * 0.012);
  };
  const endDrag = (e) => {
    drag.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
  };

  // Ground slab.
  shapes.push({
    depth: -1e6,
    el: face(
      [p3(0, 0, 0), p3(W, 0, 0), p3(W, D, 0), p3(0, D, 0)],
      tone("slab_on_grade", "#e2e8f0"),
      "#94a3b8",
      "slab-0",
    ),
  });

  // The two far walls only, so the building is cut away and the partitions
  // inside stay visible. Drawing all four would make a closed box, which is
  // a worse drawing and hides every quantity that matters.
  shapes.push({
    depth: -1e5,
    el: (
      <g key="envelope">
        {face(
          [p3(0, 0, 0), p3(W, 0, 0), p3(W, 0, total), p3(0, 0, total)],
          tone("exterior_wall", "#f1f5f9"),
          "#94a3b8",
          "env-a",
          heat ? 0.62 : 0.5,
        )}
        {face(
          [p3(0, 0, 0), p3(0, D, 0), p3(0, D, total), p3(0, 0, total)],
          tone("exterior_wall", "#e8edf4"),
          "#94a3b8",
          "env-b",
          heat ? 0.62 : 0.5,
        )}
      </g>
    ),
  });

  const shown = walls.filter((w) => storey == null || w.storey === storey);
  for (const [i, w] of shown.entries()) {
    const base = datums[w.storey] ?? 0;
    const h = (heights[w.storey] ?? 3) * WALL_H;
    const { x, y, w: ww, d: dd } = w;
    const top = base + h;
    const body = tone("interior_partition", "#93b4f5");
    const side = tone("interior_partition", "#6f98ea");
    const cap = tone("interior_partition", "#c3d6fb");
    shapes.push({
      depth: depthOf(x + ww / 2, y + dd / 2, base, azimuth),
      el: (
        <g key={`w${i}`}>
          {face(
            [p3(x, y + dd, base), p3(x + ww, y + dd, base), p3(x + ww, y + dd, top), p3(x, y + dd, top)],
            body,
            heat ? "#7f1d1d" : "#1e40af",
            `w${i}a`,
          )}
          {face(
            [p3(x + ww, y, base), p3(x + ww, y + dd, base), p3(x + ww, y + dd, top), p3(x + ww, y, top)],
            side,
            heat ? "#7f1d1d" : "#1e40af",
            `w${i}b`,
          )}
          {face(
            [p3(x, y, top), p3(x + ww, y, top), p3(x + ww, y + dd, top), p3(x, y + dd, top)],
            cap,
            heat ? "#7f1d1d" : "#1e40af",
            `w${i}c`,
          )}
        </g>
      ),
    });
  }

  // Storey slabs and the roof. Drawn last because they sit above everything,
  // which means they are also the easiest surfaces to bury the building
  // under -- so they stay faint. The roof is skipped while every storey is
  // shown, or it simply lids the thing the panel exists to reveal.
  datums.slice(1).forEach((d, i) => {
    const isRoof = i === datums.length - 2;
    if (isRoof && storey == null) return;
    shapes.push({
      depth: 1e6 + d,
      el: face(
        [p3(0, 0, d), p3(W, 0, d), p3(W, D, d), p3(0, D, d)],
        heat
          ? tone(isRoof ? "roof_assembly" : "floor_assembly", null)
          : "rgba(148,163,184,0.30)",
        "#64748b",
        `slab${i + 1}`,
        heat ? 0.3 : 1,
      ),
    });
  });

  shapes.sort((a, b) => a.depth - b.depth);

  const corners = [
    p3(0, 0, 0), p3(W, 0, 0), p3(W, D, 0), p3(0, D, 0),
    p3(0, 0, total), p3(W, 0, total), p3(W, D, total), p3(0, D, total),
  ];
  const xs = corners.map((c) => c[0]);
  const ys = corners.map((c) => c[1]);
  const pad = 16;
  const vb = [
    Math.min(...xs) - pad,
    Math.min(...ys) - pad,
    Math.max(...xs) - Math.min(...xs) + pad * 2,
    Math.max(...ys) - Math.min(...ys) + pad * 2,
  ];

  // Ranked by intensity where we have it, because that is what the drawing
  // is coloured by; classes with no drawn surface follow, greyed.
  const ranked = Object.entries(carbon)
    .map(([cls, kg]) => [cls, kg, intensity[cls] ?? null])
    .sort((a, b) => (b[2] ?? -1) - (a[2] ?? -1));

  return (
    <div className="massing">
      <div className="massing-view">
        <span className="massing-hint">drag to turn</span>
        <svg
          className={`massing-svg${drag.current ? " is-dragging" : ""}`}
          viewBox={vb.join(" ")}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          role="img"
          aria-label={`Axonometric of the measured building: ${W} by ${D} metres, ${heights.length} storeys, ${walls.length} measured partition walls`}
        >
          {shapes.map((sh) => sh.el)}
        </svg>
      </div>

      <div className="massing-side">
        <div className="massing-modes">
          <button
            className={mode === "structure" ? "is-on" : ""}
            onClick={() => setMode("structure")}
          >
            Structure
          </button>
          <button
            className={mode === "carbon" ? "is-on" : ""}
            onClick={() => setMode("carbon")}
          >
            Carbon
          </button>
        </div>

        {heat ? (
          <>
            <p className="massing-note">
              Coloured by carbon per square metre of surface, not by total —
              totals would paint almost all of it red, because the three
              largest are within 13% of each other and happen to be the three
              biggest surfaces.
            </p>
            <div className="heat-key">
              {ranked.map(([cls, kg, dens]) => (
                <div
                  className={`heat-row${dens == null ? " is-undrawn" : ""}`}
                  key={cls}
                >
                  <i
                    style={{
                      background:
                        dens == null
                          ? "#e2e8f0"
                          : heatColour(dens, hotI, coolI),
                    }}
                  />
                  <span>{CLASS_LABEL[cls] || titleCase(cls)}</span>
                  <b>
                    {dens == null ? "—" : dec(dens, 1)}
                    <em>{int(kg)}</em>
                  </b>
                </div>
              ))}
            </div>
            <p className="massing-caveat">
              kgCO₂e per m² of surface, with the element's total beside it.
              Doors and windows carry no surface in this drawing, so they are
              listed without a colour rather than coloured arbitrarily.
            </p>
          </>
        ) : (
          <p className="massing-note">{note}</p>
        )}

        <div className="massing-storeys">
          <button
            className={storey == null ? "is-on" : ""}
            onClick={() => setStorey(null)}
          >
            Every storey
          </button>
          {heights.map((h, i) => (
            <button
              key={i}
              className={storey === i ? "is-on" : ""}
              onClick={() => setStorey(i)}
            >
              Storey {i + 1}
              <span>{walls.filter((w) => w.storey === i).length} walls</span>
            </button>
          ))}
        </div>

        <p className="massing-caveat">
          A massing of what was read, not an architectural model. The near two
          walls are cut away so the partitions inside stay visible. If the
          footprint were misread the box would be the wrong shape, and where
          partitions over-detect you would see walls with no room between them.
        </p>
      </div>
    </div>
  );
}

/* ------------------------------------------------------- sheet coverage -- */

// Sheet types grouped into the families that matter to a reader, in the order
// they matter. A schedule is where the build-ups come from and is worth more
// than its page count suggests; mechanical and electrical sheets are opened,
// classified and then legitimately not used.
const SHEET_FAMILY = [
  ["schedule", "Schedules", ["assembly_schedule", "opening_schedule"], "#1e40af"],
  [
    "plan",
    "Plans",
    ["floor_plan", "foundation_plan", "roof_plan", "framing_plan", "site_plan"],
    "#2563eb",
  ],
  ["section", "Sections & elevations", ["section", "elevation", "detail"], "#0891b2"],
  [
    "other",
    "Cover, legends, services",
    [
      "title", "cover", "legend", "specification", "mechanical", "electrical",
    ],
    "#cbd5e1",
  ],
];

function familyOf(type) {
  for (const [key, , types] of SHEET_FAMILY) if (types.includes(type)) return key;
  return "other";
}

// Every page of the set, in order, coloured by what it turned out to be and
// marked where the bill actually drew on it. The claim "45 of 46 sheets were
// read" is in the title block as a number; this is the same claim in a form
// where a reader can see which ones carried the weight -- and see that the
// unreadable one is a single tick rather than a silent omission.
function SheetStrip({ takeoff }) {
  const [hover, setHover] = useState(null);
  const sheets = takeoff?.sheets || [];
  if (!sheets.length) return null;

  const cited = new Set(
    (takeoff.lines || [])
      .map((l) => l.provenance?.sheet_no)
      .filter(Boolean),
  );
  const active = hover == null ? null : sheets[hover];
  const counts = SHEET_FAMILY.map(([key, label, , colour]) => [
    label,
    colour,
    sheets.filter((x) => x.readable && familyOf(x.sheet_type) === key).length,
  ]);
  const unreadable = sheets.filter((x) => !x.readable).length;

  return (
    <div className="strip-wrap">
      <div className="strip">
        {sheets.map((sheet, i) => {
          const family = familyOf(sheet.sheet_type);
          const colour =
            SHEET_FAMILY.find(([k]) => k === family)?.[3] || "#cbd5e1";
          const isCited = sheet.sheet_no && cited.has(sheet.sheet_no);
          return (
            <button
              key={sheet.page}
              className={`tick${isCited ? " is-cited" : ""}${
                sheet.readable ? "" : " is-unreadable"
              }${hover === i ? " is-hover" : ""}`}
              style={{ "--c": colour }}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
              aria-label={`${sheet.sheet_no || `page ${sheet.page + 1}`}: ${
                sheet.title || sheet.sheet_type
              }`}
            />
          );
        })}
      </div>

      <div className="strip-read">
        {active ? (
          <>
            <b>{active.sheet_no || `page ${active.page + 1}`}</b>
            <span>
              {(active.title || active.sheet_type || "").toString().slice(0, 78)}
              {active.readable ? "" : " · no readable text"}
              {active.sheet_no && cited.has(active.sheet_no)
                ? " · a quantity is read from this sheet"
                : ""}
            </span>
          </>
        ) : (
          <>
            <b>{sheets.length} sheets opened</b>
            <span>
              every page classified · {cited.size} carry a quantity in the bill
              {unreadable > 0 ? ` · ${unreadable} had no readable text` : ""}
            </span>
          </>
        )}
      </div>

      <div className="strip-key">
        {counts.map(([label, colour, n]) =>
          n ? (
            <span className="strip-key-item" key={label}>
              <i style={{ background: colour }} />
              {label} {n}
            </span>
          ) : null,
        )}
        {unreadable > 0 && (
          <span className="strip-key-item">
            <i className="hatch" />
            unreadable {unreadable}
          </span>
        )}
        <span className="strip-key-item">
          <i className="cited" />
          cited by the bill
        </span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- upload -- */

// The catalogue is a development set; a builder's own drawings are the
// product. Until this existed the upload endpoint was reachable only by curl,
// which meant the one thing that proves this is not a canned demo -- running
// a set the service has never opened -- could not be done from the interface.
function Upload({ onDone, onClose }) {
  const [file, setFile] = useState(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [facts, setFacts] = useState({
    name: "",
    gfa_m2: "",
    storeys: "",
    units: "",
    jurisdiction: "",
  });

  const take = (f) => {
    setError(null);
    if (!f) return;
    if (!/\.pdf$/i.test(f.name)) {
      setError(
        "This reads vector PDF drawing sets. A scan or an image export carries no geometry to measure.",
      );
      return;
    }
    setFile(f);
    setFacts((x) => ({ ...x, name: x.name || f.name.replace(/\.pdf$/i, "") }));
  };

  async function submit(e) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    const body = new FormData();
    body.append("file", file);
    for (const [k, v] of Object.entries(facts)) if (v !== "") body.append(k, v);
    try {
      const res = await fetch(`${API}/projects/upload`, {
        method: "POST",
        headers: AUTH ? { Authorization: AUTH } : {},
        body,
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(payload.detail || `upload failed (${res.status})`);
      onDone(payload.id);
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="scrim" onClick={onClose}>
      <div
        className="upload"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Upload a plan set"
      >
        <div className="trace-head">
          <div>
            <div className="eyebrow">Run this on your own drawings</div>
            <div className="trace-title">Upload a plan set</div>
          </div>
          <button className="trace-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <form className="upload-body" onSubmit={submit}>
          <label
            className={`dropzone${over ? " is-over" : ""}${file ? " has-file" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              take(e.dataTransfer.files?.[0]);
            }}
          >
            <input
              type="file"
              accept="application/pdf,.pdf"
              hidden
              onChange={(e) => take(e.target.files?.[0])}
            />
            {file ? (
              <>
                <b>{file.name}</b>
                <span>{(file.size / 1e6).toFixed(1)} MB · click to choose another</span>
              </>
            ) : (
              <>
                <b>Drop a vector PDF here</b>
                <span>or click to choose · any set from the CMHC catalogue works</span>
              </>
            )}
          </label>

          {/* Asked for rather than inferred. Floor area in particular decides
              the intensity per square metre, and guessing it from a plan whose
              extents cover a whole block gave one catalogue design an
              intensity six times its neighbours'. */}
          <div className="upload-facts">
            {[
              ["name", "Name", "text", "As you want it shown"],
              ["gfa_m2", "Floor area m²", "number", "Leave blank to measure it"],
              ["storeys", "Storeys", "number", ""],
              ["units", "Units", "number", ""],
              ["jurisdiction", "Location", "text", "Edmonton, AB"],
            ].map(([key, label, type, hint]) => (
              <label key={key}>
                <span className="eyebrow">{label}</span>
                <input
                  type={type}
                  value={facts[key]}
                  placeholder={hint}
                  onChange={(e) =>
                    setFacts((x) => ({ ...x, [key]: e.target.value }))
                  }
                />
              </label>
            ))}
          </div>

          {error && <p className="form-fail">{error}</p>}

          <div className="upload-actions">
            <button className="btn btn-primary" type="submit" disabled={!file || busy}>
              {busy ? "Reading the drawings…" : "Read this plan set"}
            </button>
            <span className="muted">
              {busy
                ? "A 46-page set takes about 20 seconds."
                : "Nothing is stored beyond this session."}
            </span>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- topbar -- */

function Topbar({ projects, projectId, onPick, exportHref, reportHref, onUpload }) {
  return (
    <header className="topbar">
      <div className="wordmark">
        e<span>carbon</span>
      </div>
      <div className="topbar-spacer" />
      {onUpload && (
        <button className="btn btn-primary" onClick={onUpload}>
          Upload a plan set
        </button>
      )}
      {exportHref && (
        <>
          <a className="btn" href={exportHref}>
            Download takeoff
          </a>
          <a className="btn" href={reportHref} target="_blank" rel="noreferrer">
            Open report
          </a>
        </>
      )}
      {projects?.length > 0 && (
        <div className="selector">
          <label htmlFor="plan">Plan set</label>
          <select
            id="plan"
            value={projectId || ""}
            onChange={(e) => onPick(e.target.value)}
          >
            {projects.map((p) => {
              const id = p.id ?? p.project_id;
              const label = String(p.name || id)
                .replace(/_/g, " ")
                .replace(/ Technical Design Package/i, "");
              return (
                <option key={id} value={id}>
                  {label}
                </option>
              );
            })}
          </select>
        </div>
      )}
    </header>
  );
}

/* ------------------------------------------------------------------ app -- */

export default function App() {
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState(null);
  const [takeoff, setTakeoff] = useState(null);
  const [carbon, setCarbon] = useState(null);
  const [swaps, setSwaps] = useState([]);
  const [decisions, setDecisions] = useState([]);
  const [trace, setTrace] = useState(null);
  // One hover and one filter shared by the donut, the bars and the bill, so
  // the three read as views of the same thing rather than three tables that
  // happen to sit on one page.
  // `?upload=1` opens the upload dialog on load, for the same two reasons as
  // `?trace=`: a dialog that only opens on click cannot be screenshotted in
  // review, and a demo wants to link straight to the moment that matters.
  const [massing, setMassing] = useState(null);
  const [uploading, setUploading] = useState(
    () => new URLSearchParams(window.location.search).get("upload") === "1",
  );
  const [focus, setFocus] = useState(null);
  const [filter, setFilter] = useState(null);
  const [status, setStatus] = useState("connecting");
  const [error, setError] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    getJSON("/projects")
      .then((p) => {
        const list = Array.isArray(p) ? p : p.projects || [];
        setProjects(list);
        setStatus(list.length ? "ready" : "empty");
        if (list.length) setProjectId(pickInitial(list));
      })
      .catch((e) => {
        // A 401 is not an outage: the service is up and declining to answer
        // without credentials, which is a different thing to tell the reader.
        if (e instanceof Unauthorized) {
          setStatus("locked");
          return;
        }
        setError(e.message);
        setStatus("offline");
      });
  }, [reloadToken]);

  const load = useCallback(async (id) => {
    if (!id) return;
    setStatus("loading");
    setError(null);
    try {
      setTakeoff(await getJSON(`/projects/${id}/takeoff`));
      setCarbon(await getJSON(`/projects/${id}/carbon`));
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
      try {
        // Null for most of the catalogue: a design without a footprint or
        // storey datums has no geometry to draw, and drawing a guess would
        // be the one thing this view exists not to do.
        setMassing(await getJSON(`/projects/${id}/massing`));
      } catch {
        setMassing(null);
      }
      setStatus("ready");
    } catch (e) {
      if (e instanceof Unauthorized) {
        setStatus("locked");
        return;
      }
      setError(e.message);
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    if (projectId) load(projectId);
    setFilter(null);
    setFocus(null);
  }, [projectId, load]);


  const override = useCallback(
    async (lineId, quantity) => {
      const next = await postJSON(`/projects/${projectId}/lines/${lineId}`, {
        quantity,
      });
      setCarbon(next);
      setTakeoff(await getJSON(`/projects/${projectId}/takeoff`));
    },
    [projectId],
  );

  const showTrace = useCallback(
    async (lineId, provenance) => {
      if (!projectId || !lineId) return;
      const label =
        provenance?.detail ||
        (provenance?.sheet_no ? `Sheet ${provenance.sheet_no}` : lineId);
      setTrace({ lineId, label, projectId, regions: [], loading: true, error: null });
      try {
        const regions = await getJSON(`/projects/${projectId}/trace/${lineId}`);
        setTrace({ lineId, label, projectId, regions, loading: false, error: null });
      } catch (e) {
        setTrace({
          lineId,
          label,
          projectId,
          regions: [],
          loading: false,
          error: `Could not trace this line: ${e.message}`,
        });
      }
    },
    [projectId],
  );

  // `?trace=<line id>` opens that line's trace on load. It exists so a demo
  // or a bug report can link straight to the moment that matters instead of
  // describing which row to press, and it is how this panel is reviewed --
  // a dialog that only opens on click cannot otherwise be screenshotted.
  //
  // Keyed on the takeoff rather than on `status`: an earlier version watched
  // status alone, so whether it fired depended on whether `takeoff` happened
  // to be set in the same render. It worked for one line and silently did
  // nothing for the next. The ref keeps it to once per project, so closing
  // the panel does not reopen it.
  const autoTraced = useRef(null);
  useEffect(() => {
    if (!takeoff || !projectId) return;
    if (autoTraced.current === projectId) return;
    const wanted = new URLSearchParams(window.location.search).get("trace");
    if (!wanted) return;
    const line =
      takeoff.lines.find((l) => l.id === wanted) ||
      takeoff.lines.find((l) => l.id.includes(wanted));
    if (!line) return;
    autoTraced.current = projectId;
    showTrace(line.id, line.provenance);
  }, [takeoff, projectId, showTrace]);

  // The coverage the takeoff reports about itself, not a recomputation.
  const coverage = useMemo(() => {
    const gap = (takeoff?.gaps || []).find((g) =>
      /covers roughly \d+%/.test(g.message),
    );
    if (!gap) return takeoff ? 1 : null;
    return parseInt(gap.message.match(/covers roughly (\d+)%/)[1], 10) / 100;
  }, [takeoff]);

  if (status === "locked") {
    return (
      <div className="app">
        <Topbar />
        <SignIn
          onDone={() => {
            setStatus("connecting");
            setReloadToken((n) => n + 1);
          }}
        />
      </div>
    );
  }

  if (status === "offline" || status === "error") {
    return (
      <div className="app">
        <Topbar />
        <div className="centre">
          <div className="card panel" style={{ padding: 32 }}>
            <h2>The reader is not running</h2>
            <p>
              {error || "Start the service and this page will connect on its own."}
            </p>
            <button
              className="btn btn-primary"
              onClick={() => setReloadToken((n) => n + 1)}
            >
              Try again
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <Topbar
        projects={projects}
        projectId={projectId}
        onPick={setProjectId}
        onUpload={() => setUploading(true)}
        exportHref={projectId ? authedUrl(`/projects/${projectId}/export.csv`) : null}
        reportHref={projectId ? authedUrl(`/projects/${projectId}/report.html`) : null}
      />

      <main className="page">
        {status === "loading" || !takeoff ? (
          <>
            <div className="card skeleton" style={{ height: 240 }} />
            <div className="card skeleton" style={{ height: 180 }} />
            <div className="card skeleton" style={{ height: 420 }} />
          </>
        ) : (
          <>
            <div className="hero-grid">
              <Hero carbon={carbon} takeoff={takeoff} coverage={coverage} />
              <TitleBlock takeoff={takeoff} carbon={carbon} coverage={coverage} />
            </div>

            {massing && (
              <section className="card">
                <div className="card-head">
                  <h2>What we understood from the drawings</h2>
                  <span className="card-note">
                    measured footprint, section datums and counted partitions
                  </span>
                </div>
                <Massing massing={massing} />
              </section>
            )}

            <section className="card">
              <div className="card-head">
                <h2>Every sheet in the set</h2>
                <span className="card-note">
                  what each page turned out to be, and which ones the number
                  rests on
                </span>
              </div>
              <SheetStrip takeoff={takeoff} />
            </section>

            <section className="card">
              <div className="card-head">
                <h2>What we could not read</h2>
                <span className="card-note">
                  {takeoff.gaps?.length || 0} notices · shown before the number
                </span>
              </div>
              {takeoff.gaps?.length ? (
                <Notices gaps={takeoff.gaps} />
              ) : (
                <div className="notices muted">
                  Every sheet this takeoff needed was readable.
                </div>
              )}
            </section>

            {carbon?.by_material_category?.length ? (
              <section className="card">
                <div className="card-head">
                  <h2>Where the carbon is</h2>
                  <span className="card-note">by material category</span>
                </div>
                <Contribution
                  carbon={carbon}
                  focus={focus}
                  onFocus={setFocus}
                  filter={filter}
                  onFilter={setFilter}
                />
              </section>
            ) : null}

            <section className="card">
              <div className="card-head">
                <h2>Bill of quantities</h2>
                <span className="card-note">
                  {filter ? (
                    <button className="filter-clear" onClick={() => setFilter(null)}>
                      showing {filter} · show everything
                    </button>
                  ) : (
                    "press a sheet tag to see where a number came from"
                  )}
                </span>
              </div>
              <BillOfQuantities
                takeoff={takeoff}
                carbon={carbon}
                onOverride={override}
                onTrace={showTrace}
                focus={focus}
                onFocus={setFocus}
                filter={filter}
              />
            </section>

            <div className="two-col">
              {decisions.length > 0 && (
                <section className="card">
                  <div className="card-head">
                    <h2>Decisions still open</h2>
                    <span className="card-note">not counted · priced as a range</span>
                  </div>
                  <OpenDecisions choices={decisions} />
                </section>
              )}
              <section className="card">
                <div className="card-head">
                  <h2>Material substitutions</h2>
                  <span className="card-note">ranked by what they save</span>
                </div>
                <Substitutions swaps={swaps} takeoff={takeoff} />
              </section>
            </div>
          </>
        )}
      </main>

      <TracePanel trace={trace} onClose={() => setTrace(null)} />

      {uploading && (
        <Upload
          onClose={() => setUploading(false)}
          onDone={async (id) => {
            setUploading(false);
            // Re-list so the new set appears in the selector, then open it.
            try {
              const list = await getJSON("/projects");
              setProjects(Array.isArray(list) ? list : list.projects || []);
            } catch {
              /* the selector will catch up on the next load */
            }
            setProjectId(id);
          }}
        />
      )}
    </div>
  );
}
