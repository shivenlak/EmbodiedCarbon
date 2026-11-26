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
function place(at) {
  const W = Math.min(420, window.innerWidth - 32);
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
  if (!complete || !complete.items?.length) return null;
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
            <div className="calc-pop" style={place(open)} role="dialog" aria-label="Complete estimate">
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
            </div>
          </div>,
          document.body,
        )}
    </span>
  );
}
