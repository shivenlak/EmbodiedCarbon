// How every carbon number was calculated, one click away (UX session, 25 Nov).
//
// Practitioners said every number "seems to come out of thin air" and that an
// audit needs the arithmetic. The server's /calc returns, per line, the steps
// from the drawing to the kgCO2e (quantity read, your correction, conversion
// via density or thickness, waste, factor with its source, result); the server
// refuses to return a trace that does not reproduce the figure.
//
// Words, on purpose: carbon is always kg with CO₂e as a subscript; plain mass
// is always "kg (mass)", because mass is itself a step in the calculation.

import { createContext, useContext, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export const CalcContext = createContext({ calc: null, onTrace: null });

const fmt = (n, places) => {
  if (n == null || !Number.isFinite(n)) return "—";
  const a = Math.abs(n);
  const p = places ?? (a >= 100 ? 0 : a >= 1 ? 2 : 4);
  return n.toLocaleString(undefined, { maximumFractionDigits: p, minimumFractionDigits: a >= 100 ? 0 : Math.min(p, 2) });
};

/** The carbon unit: kg with CO₂e as a subscript, so it never reads as mass. */
export function CO2e({ per }) {
  return (
    <span className="u-co2e">
      kg<sub>CO₂e</sub>
      {per ? `/${per}` : ""}
    </span>
  );
}

/** A carbon figure with its unit. With a lineId, it opens its calculation. */
export function Carbon({ value, lineId, places = 0, per, className = "" }) {
  const shown = (
    <>
      <span className="num">{fmt(value, places)}</span>{" "}
      <CO2e per={per} />
    </>
  );
  if (!lineId) return <span className={`carbon-fig ${className}`}>{shown}</span>;
  return (
    <CalcButton lineId={lineId} className={className}>
      {shown}
    </CalcButton>
  );
}

/** Any element that opens a line's calculation. */
export function CalcButton({ lineId, children, className = "" }) {
  const [open, setOpen] = useState(null); // the anchor's rect when open
  const ref = useRef(null);
  const pop = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => {
      const inside = (el) => el && el.contains(e.target);
      if (e.key === "Escape" || (e.type === "pointerdown" && !inside(ref.current) && !inside(pop.current))) setOpen(null);
    };
    const away = () => setOpen(null);
    window.addEventListener("keydown", close);
    window.addEventListener("pointerdown", close);
    window.addEventListener("resize", away);
    return () => {
      window.removeEventListener("keydown", close);
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("resize", away);
    };
  }, [open]);
  return (
    <span className="calc-anchor" ref={ref}>
      <button
        type="button"
        className={`calc-btn ${className}`}
        onClick={(e) => {
          e.stopPropagation();
          const r = e.currentTarget.getBoundingClientRect();
          setOpen((o) => (o ? null : { left: r.left, right: r.right, top: r.top, bottom: r.bottom }));
        }}
        aria-expanded={!!open}
        title="How this was calculated"
      >
        {children}
      </button>
      {open &&
        createPortal(
          <div ref={pop}>
            <CalcPopover lineId={lineId} at={open} onClose={() => setOpen(null)} />
          </div>,
          document.body,
        )}
    </span>
  );
}

export function CalcSteps({ trace }) {
  const { onTrace } = useContext(CalcContext);
  if (!trace) return <p className="calc-empty">Calculation loading…</p>;
  return (
    <>
      <ol className="calc-steps">
        {trace.steps.map((s, i) => {
          const last = i === trace.steps.length - 1 && trace.counted;
          return (
            <li key={i} className={last ? "calc-result" : ""}>
              <div className="calc-row">
                <span className="calc-label">{s.label}</span>
                <span className="calc-val">
                  {s.value == null ? "" : s.unit === "×" ? `× ${fmt(s.value, 2)}` : fmt(s.value)}{" "}
                  {s.unit === "kgCO₂e" ? <CO2e /> : s.unit.startsWith("kgCO₂e per ") ? <><CO2e /> per {s.unit.slice(11)}</> : s.unit === "×" ? "" : s.unit}
                </span>
              </div>
              {s.detail && <div className="calc-detail">{s.detail}</div>}
              {s.source && (
                <div className="calc-source">
                  {i === 0 && onTrace ? (
                    <button type="button" className="sc-link" onClick={() => onTrace(trace.line_id)}>
                      {s.source} · show on the sheet
                    </button>
                  ) : (
                    <>Source: {s.source}</>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
      {trace.counted && (
        <p className="calc-formula">
          <span>Check it:</span> <code>{trace.formula}</code>
        </p>
      )}
    </>
  );
}

// Placed beside its number, kept inside the window: below when there is room,
// above otherwise, never under a panel's scroll edge.
function place(at, width = 420) {
  const W = Math.min(width, window.innerWidth - 32);
  const left = Math.max(16, Math.min(at.left, window.innerWidth - W - 16));
  const below = window.innerHeight - at.bottom;
  const maxH = Math.max(220, Math.min(560, Math.max(below, at.top) - 24));
  return below >= Math.min(360, at.top)
    ? { left, top: at.bottom + 8, width: W, maxHeight: maxH }
    : { left, bottom: window.innerHeight - at.top + 8, width: W, maxHeight: maxH };
}

export function CalcPopover({ lineId, onClose, at }) {
  const { calc } = useContext(CalcContext);
  const trace = calc?.[lineId];
  return (
    <div
      className="calc-pop"
      style={at ? place(at) : undefined}
      role="dialog"
      aria-label="How this was calculated"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="calc-pop-head">
        <b>How this was calculated</b>
        <button type="button" className="calc-x" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>
      <CalcSteps trace={trace} />
    </div>
  );
}

// The complete estimate (A1–A5) under the counted total: what a whole-building
// LCA adds, each item assumed and saying how it was calculated.
export function CompleteLine() {
  const { complete } = useContext(CalcContext);
  const [open, setOpen] = useState(null);
  const ref = useRef(null);
  const pop = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => {
      const inside = (el) => el && el.contains(e.target);
      if (e.key === "Escape" || (e.type === "pointerdown" && !inside(ref.current) && !inside(pop.current))) setOpen(null);
    };
    window.addEventListener("keydown", close);
    window.addEventListener("pointerdown", close);
    return () => {
      window.removeEventListener("keydown", close);
      window.removeEventListener("pointerdown", close);
    };
  }, [open]);
  // ?complete=1 opens it, so the scope table can be reviewed by screenshot.
  const ready = !!complete?.items?.length;
  useEffect(() => {
    if (!ready || !new URLSearchParams(window.location.search).has("complete")) return;
    const b = ref.current?.querySelector("button");
    if (b) {
      const r = b.getBoundingClientRect();
      setOpen({ left: r.left, right: r.right, top: r.top, bottom: r.bottom });
    }
  }, [ready]);
  if (!ready) return null;
  return (
    <span className="complete-line" ref={ref}>
      <button
        type="button"
        className="calc-btn"
        onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          setOpen((o) => (o ? null : { left: r.left, right: r.right, top: r.top, bottom: r.bottom }));
        }}
        aria-expanded={!!open}
      >
        Complete estimate, A1–A5: <b>{fmt(complete.total_kg_co2e, 0)}</b> <CO2e />
      </button>{" "}
      <em>
        range {fmt(complete.low_kg_co2e, 0)}–{fmt(complete.high_kg_co2e, 0)}
      </em>
      {open &&
        createPortal(
          <div ref={pop}>
            <div className="calc-pop" style={place(open, 600)} role="dialog" aria-label="Complete estimate">
              <div className="calc-pop-head">
                <b>Complete estimate, A1–A5</b>
                <button type="button" className="calc-x" onClick={() => setOpen(null)} aria-label="Close">
                  ×
                </button>
              </div>
              <p className="calc-detail" style={{ marginTop: 0 }}>
                The counted total is what the drawings state (A1–A3). A whole-building LCA, such as CMHC's
                reports, also carries what the drawings leave open and what happens between factory and site.
                Each addition below is assumed and says how it was calculated.
              </p>
              <ol className="calc-steps">
                <li>
                  <div className="calc-row">
                    <span className="calc-label">Counted from the drawings (A1–A3)</span>
                    <span className="calc-val">
                      {fmt(complete.counted_kg_co2e, 0)} <CO2e />
                    </span>
                  </div>
                </li>
                {complete.items.map((i) => (
                  <li key={i.key}>
                    <div className="calc-row">
                      <span className="calc-label">+ {i.label}</span>
                      <span className="calc-val">
                        {fmt(i.kg_co2e, 0)} <CO2e />
                      </span>
                    </div>
                    <div className="calc-detail">{i.basis}</div>
                    <div className="calc-source">Source: {i.source}</div>
                  </li>
                ))}
                <li className="calc-result">
                  <div className="calc-row">
                    <span className="calc-label">Complete estimate</span>
                    <span className="calc-val">
                      {fmt(complete.total_kg_co2e, 0)} <CO2e />
                    </span>
                  </div>
                  <div className="calc-detail">
                    range {fmt(complete.low_kg_co2e, 0)}–{fmt(complete.high_kg_co2e, 0)} kgCO₂e
                  </div>
                </li>
              </ol>
              {complete.scope && <ScopeTable scope={complete.scope} />}
            </div>
          </div>,
          document.body,
        )}
    </span>
  );
}

const STATUS_CLASS = {
  counted: "is-counted",
  estimated: "is-estimated",
  "open decision": "is-open",
  added: "is-added",
  "counted elsewhere": "is-inside",
  "not counted": "is-missing",
  "not included": "is-out",
};

// What the estimate includes, element by element, as the NRC guideline's
// Table 9 lists them: the declaration an LCA report makes about its scope.
export function ScopeTable({ scope }) {
  const [openNp, setOpenNp] = useState(false);
  return (
    <div className="scope">
      <h4 className="scope-h">What is included</h4>
      <p className="calc-detail" style={{ marginTop: 0 }}>
        Every building element in {scope.source}, and what this estimate does with it.
      </p>
      <table className="scope-t">
        <tbody>
          {scope.rows.map((r) => (
            <tr key={`${r.code}-${r.element}`} title={r.detail}>
              <td className="scope-code">{r.code}</td>
              <td>
                {r.element}
                <div className="calc-detail">{r.detail}</div>
              </td>
              <td>
                <span className={`scope-st ${STATUS_CLASS[r.status] || ""}`}>{r.status}</span>
              </td>
              <td className="num">
                {r.kg_co2e == null ? "" : fmt(r.kg_co2e, 0)}
                {r.kg_co2e != null && !r.in_total ? "*" : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="calc-detail">
        Figures in <CO2e />. * in the complete estimate, not the counted total.
      </p>
      {scope.not_priced?.length > 0 && (
        <>
          <button type="button" className="sc-link" onClick={() => setOpenNp((o) => !o)} aria-expanded={openNp}>
            {openNp ? "Hide" : "Show"} the {scope.not_priced.length} layers the drawings name but no line prices
          </button>
          {openNp && (
            <ul className="scope-np">
              {scope.not_priced.map((n) => (
                <li key={`${n.assembly}-${n.layer}`}>
                  <b>{n.assembly}</b> {n.layer.toLowerCase()} <em>· {n.reason}</em>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

// One element's build-up, layer by layer (UX session: "if I click the
// exterior wall it should show the composite of the wall and how you
// calculate it"). Each priced layer opens its own calculation.
export function BuildupDrawer({ element, label, onClose }) {
  const { api, projectId, onEdit } = useContext(CalcContext);
  const [b, setB] = useState(null);
  const [err, setErr] = useState(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const { calc } = useContext(CalcContext); // refetch after an edit changes the figures
  useEffect(() => {
    let live = true;
    api
      .get(`/projects/${projectId}/buildup/${element}`)
      .then((r) => live && setB(r))
      .catch((e) => live && setErr(e.message));
    const esc = (e) => e.key === "Escape" && closeRef.current();
    window.addEventListener("keydown", esc);
    return () => {
      live = false;
      window.removeEventListener("keydown", esc);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, element, calc]);
  return createPortal(
    <div className="le-backdrop" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="le bu" role="dialog" aria-label={`Build-up of ${label}`}>
        <header className="le-head">
          <div>
            <div className="sc-eyebrow">What it is made of</div>
            <h2>
              {label}
              {b && (
                <span className="bu-total">
                  {fmt(b.kg_co2e, 0)} <CO2e />
                </span>
              )}
            </h2>
          </div>
          <button type="button" className="calc-x" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>
        {err && <p className="le-err">{err}</p>}
        {!b && !err && <p className="calc-empty">Loading…</p>}
        {b?.assemblies.map((a) => (
          <section className="le-sec" key={a.tag}>
            <h3>
              {a.name || a.tag}
              {a.sheet && <span className="bu-sheet"> · schedule on {a.sheet}</span>}
            </h3>
            <ol className="bu-layers">
              {a.layers.map((l) => (
                <li key={l.n} className={`bu-l is-${l.status.replace(/\s+/g, "-")}`}>
                  <span className="bu-n">{l.n}</span>
                  <div className="bu-body">
                    <div className="bu-mat">{l.material}</div>
                    <div className="calc-detail">
                      {l.status === "priced"
                        ? `${fmt(l.quantity)} ${l.unit === "m3" ? "m³" : l.unit === "m2" ? "m²" : l.unit} · ${l.confidence}`
                        : l.reason}
                    </div>
                  </div>
                  <div className="bu-kg">
                    {l.kg_co2e != null ? (
                      <Carbon value={l.kg_co2e} lineId={l.line_id} />
                    ) : (
                      <span className="bu-st">{l.status}</span>
                    )}
                    {l.line_id && onEdit && (
                      <button type="button" className="sc-link bu-edit" onClick={() => onEdit(l.line_id)}>
                        Edit
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </section>
        ))}
        {b?.other_lines?.length > 0 && (
          <section className="le-sec">
            <h3>Measured or estimated on their own lines</h3>
            <ol className="bu-layers">
              {b.other_lines.map((o) => (
                <li key={o.line_id} className="bu-l">
                  <span className="bu-n">·</span>
                  <div className="bu-body">
                    <div className="bu-mat">{o.material}</div>
                    <div className="calc-detail">
                      {fmt(o.quantity)} {o.unit === "m3" ? "m³" : o.unit === "m2" ? "m²" : o.unit === "kg" ? "kg (mass)" : o.unit} · {o.confidence}
                      {o.kg_co2e == null ? " · the area the layers above are priced over" : ""}
                    </div>
                  </div>
                  <div className="bu-kg">
                    {o.kg_co2e != null && <Carbon value={o.kg_co2e} lineId={o.line_id} />}
                    {o.kg_co2e != null && onEdit && (
                      <button type="button" className="sc-link bu-edit" onClick={() => onEdit(o.line_id)}>
                        Edit
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </section>
        )}
        <p className="calc-detail bu-foot">
          Click any figure for its calculation. Layers the drawings name with no thickness (membranes, barriers) or as
          a placeholder carry no carbon here and say why.
        </p>
      </aside>
    </div>,
    document.body,
  );
}
