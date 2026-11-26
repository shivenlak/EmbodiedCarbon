// The plan set, fully interactive (UX session, 26 Nov): select any measured
// wall, leave it out or count it, reclassify it (partition or exterior),
// measure anything at the sheet's scale, and draw a wall the reading missed.
//
// Every change posts the whole plan edit to the server, which rescales the
// partition and exterior wall lines and says so on each line; the totals and
// every calculation update from that answer. Nothing is computed here.

import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CalcContext, CO2e } from "./calc.jsx";

const fmt = (n, p = 2) => (n == null || !Number.isFinite(n) ? "—" : n.toLocaleString(undefined, { maximumFractionDigits: p, minimumFractionDigits: p }));
const CLASS_NAME = { partition: "Partition", exterior: "Exterior wall" };

export default function PlanEditor({ onClose, startPage }) {
  const { api, projectId, afterEdit } = useContext(CalcContext);
  const [plan, setPlan] = useState(null);
  const [pages, setPages] = useState(null);
  const [page, setPage] = useState(startPage ?? null);
  const [tool, setTool] = useState("select"); // select | measure | draw
  const [drawAs, setDrawAs] = useState("partition");
  const [sel, setSel] = useState(null); // wall id or drawn id
  const [pending, setPending] = useState(null); // first click of a measure/draw
  const [hover, setHover] = useState(null);
  const [measures, setMeasures] = useState([]);
  const [scale, setScale] = useState({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [total, setTotal] = useState(null);
  const svgRef = useRef(null);
  const [view, setView] = useState(null);
  const drag = useRef(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  const load = useCallback(async () => {
    const [pl, pgs, carbon] = await Promise.all([
      api.get(`/projects/${projectId}/plan`),
      api.get(`/projects/${projectId}/pages`),
      api.get(`/projects/${projectId}/carbon`),
    ]);
    setPlan(pl);
    setPages(pgs);
    setTotal(carbon.total_kg_co2e);
    return { pl, pgs };
  }, [api, projectId]);

  useEffect(() => {
    load()
      .then(({ pl, pgs }) => {
        setPage((p) => {
          if (p != null) return p;
          if (pl.pages.length) return pl.pages[0].page;
          const plan = pgs.find((x) => x.sheet_type === "floor_plan");
          return plan ? plan.page : 0;
        });
      })
      .catch((e) => setErr(e.message));
    const esc = (e) => {
      if (e.key !== "Escape") return;
      if (pending) setPending(null);
      else closeRef.current();
    };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const pageInfo = pages?.find((p) => p.page === page);
  useEffect(() => {
    if (!pageInfo) return;
    setView({ x: 0, y: 0, w: pageInfo.width, h: pageInfo.height });
    setPending(null);
    if (scale[page] === undefined) {
      api
        .get(`/projects/${projectId}/pages/${page}/scale`)
        .then((s) => setScale((m) => ({ ...m, [page]: s.mm_per_pt })))
        .catch(() => setScale((m) => ({ ...m, [page]: null })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageInfo?.width]);

  const walls = useMemo(() => plan?.pages.find((p) => p.page === page)?.walls || [], [plan, page]);
  const drawn = useMemo(() => (plan?.added || []).filter((a) => a.page === page), [plan, page]);
  const mm = scale[page];
  const lenOf = (a, b) => (mm ? (Math.hypot(b.x - a.x, b.y - a.y) * mm) / 1000 : null);

  // The whole edit, as the server holds it, with one change applied.
  const current = () => ({
    excluded: plan.pages.flatMap((p) => p.walls.filter((w) => w.excluded).map((w) => w.id)),
    classes: Object.fromEntries(plan.pages.flatMap((p) => p.walls.filter((w) => w.as !== "partition").map((w) => [w.id, w.as]))),
    added: plan.added.map((a) => ({ id: a.id, page: a.page, x0: a.x0, y0: a.y0, x1: a.x1, y1: a.y1, as: a.as })),
  });
  async function send(edit) {
    setBusy(true);
    setErr(null);
    try {
      const carbon = await api.post(`/projects/${projectId}/plan`, edit);
      setTotal(carbon.total_kg_co2e);
      setPlan(await api.get(`/projects/${projectId}/plan`));
      await afterEdit(carbon);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }
  const toggleOut = (id) => {
    const e = current();
    e.excluded = e.excluded.includes(id) ? e.excluded.filter((x) => x !== id) : [...e.excluded, id];
    return send(e);
  };
  const reclass = (id, as) => {
    const e = current();
    if (as === "partition") delete e.classes[id];
    else e.classes[id] = as;
    return send(e);
  };
  const addWall = (a, b, as) => {
    const e = current();
    const n = Math.max(0, ...plan.added.map((x) => parseInt(String(x.id).replace(/\D/g, ""), 10) || 0)) + 1;
    e.added.push({ id: `u${n}`, page, x0: a.x, y0: a.y, x1: b.x, y1: b.y, as });
    return send(e).then(() => setSel(`u${n}`));
  };
  const reclassDrawn = (id, as) => {
    const e = current();
    e.added = e.added.map((x) => (x.id === id ? { ...x, as } : x));
    return send(e);
  };
  const removeDrawn = (id) => {
    const e = current();
    e.added = e.added.filter((x) => x.id !== id);
    setSel(null);
    return send(e);
  };

  // Screen to sheet coordinates (PDF points).
  const toSheet = (ev) => {
    const svg = svgRef.current;
    if (!svg) return null;
    const pt = svg.createSVGPoint();
    pt.x = ev.clientX;
    pt.y = ev.clientY;
    const m = svg.getScreenCTM();
    if (!m) return null;
    const q = pt.matrixTransform(m.inverse());
    return { x: q.x, y: q.y };
  };
  // Shift keeps a line horizontal or vertical, as walls usually are.
  const snap = (a, b, ev) => {
    if (!a || !ev.shiftKey) return b;
    return Math.abs(b.x - a.x) > Math.abs(b.y - a.y) ? { x: b.x, y: a.y } : { x: a.x, y: b.y };
  };
  const onSheetClick = (ev) => {
    if (drag.current?.moved) return;
    if (tool === "select") {
      setSel(null);
      return;
    }
    const p = toSheet(ev);
    if (!p) return;
    if (!pending) {
      setPending(p);
      return;
    }
    const b = snap(pending, p, ev);
    if (tool === "measure") setMeasures((m) => [...m, { page, a: pending, b, id: Date.now() }]);
    else addWall(pending, b, drawAs);
    setPending(null);
  };
  const onWheel = (ev) => {
    if (!view) return;
    ev.preventDefault();
    const p = toSheet(ev);
    if (!p) return;
    const k = ev.deltaY > 0 ? 1.18 : 1 / 1.18;
    const w = Math.min(pageInfo.width * 1.2, Math.max(60, view.w * k));
    const h = (view.h * w) / view.w;
    setView({ x: p.x - ((p.x - view.x) * w) / view.w, y: p.y - ((p.y - view.y) * h) / view.h, w, h });
  };
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return undefined;
    const h = (e) => onWheel(e);
    svg.addEventListener("wheel", h, { passive: false });
    return () => svg.removeEventListener("wheel", h);
  });
  const onDown = (ev) => {
    if (ev.button !== 0 && ev.button !== 1) return;
    drag.current = { x: ev.clientX, y: ev.clientY, view, moved: false };
  };
  const onMove = (ev) => {
    if (pending) setHover(snap(pending, toSheet(ev), ev));
    const d = drag.current;
    if (!d || !(ev.buttons & 1 || ev.buttons & 4)) return;
    const dx = ev.clientX - d.x;
    const dy = ev.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 5) return;
    d.moved = true;
    const svg = svgRef.current.getBoundingClientRect();
    const sx = d.view.w / svg.width;
    const sy = d.view.h / svg.height;
    const s = Math.max(sx, sy);
    setView({ ...d.view, x: d.view.x - dx * s, y: d.view.y - dy * s });
  };
  const onUp = () => setTimeout(() => (drag.current = null), 0);

  const selWall = walls.find((w) => w.id === sel);
  const selDrawn = drawn.find((w) => w.id === sel);
  const px = view && svgRef.current ? view.w / (svgRef.current.getBoundingClientRect().width || 1) : 1;
  const sheetPages = (pages || []).filter(
    (p) => p.sheet_type === "floor_plan" || plan?.pages.some((x) => x.page === p.page) || p.page === page,
  );

  return createPortal(
    <div className="pe-backdrop" role="dialog" aria-label="Edit the plan">
      <div className="pe">
        <header className="pe-head">
          <div>
            <div className="sc-eyebrow">The plan set, interactive</div>
            <h2>Edit the plan</h2>
          </div>
          <div className="pe-total">
            {total != null && (
              <>
                <b>{Math.round(total).toLocaleString()}</b> <CO2e /> <span>A1–A3, updates with every change</span>
              </>
            )}
          </div>
          <button type="button" className="calc-x" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>

        <div className="pe-tools" role="toolbar" aria-label="Plan tools">
          {[
            ["select", "Select", "Click a wall to count it, leave it out, or reclassify it"],
            ["measure", "Measure", "Click two points; hold Shift for a straight line"],
            ["draw", "Draw a wall", "Click two points to add a wall the reading missed"],
          ].map(([k, label, hint]) => (
            <button key={k} type="button" className={`pe-tool${tool === k ? " is-on" : ""}`} aria-pressed={tool === k} title={hint} onClick={() => (setTool(k), setPending(null))}>
              {label}
            </button>
          ))}
          {tool === "draw" && (
            <label className="pe-as">
              as
              <select value={drawAs} onChange={(e) => setDrawAs(e.target.value)}>
                <option value="partition">a partition</option>
                <option value="exterior">an exterior wall</option>
              </select>
            </label>
          )}
          <span className="pe-hint">
            {tool === "select" && "Click a wall. Scroll to zoom, drag to move."}
            {tool !== "select" && (pending ? "Click the second point (Shift: straight). Esc cancels." : "Click the first point.")}
            {tool !== "select" && !mm && mm !== undefined && " This sheet has no scale, so lengths cannot be read."}
          </span>
          <select className="pe-page" value={page ?? ""} onChange={(e) => setPage(parseInt(e.target.value, 10))} aria-label="Sheet">
            {sheetPages.map((p) => (
              <option key={p.page} value={p.page}>
                {p.sheet_no || `Page ${p.page + 1}`} {p.title ? `· ${p.title}` : ""}
              </option>
            ))}
          </select>
        </div>

        <div className="pe-main">
          <div className="pe-sheet">
            {view && pageInfo && (
              <svg
                ref={svgRef}
                viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
                preserveAspectRatio="xMidYMid meet"
                className={`pe-svg is-${tool}`}
                onClick={onSheetClick}
                onPointerDown={onDown}
                onPointerMove={onMove}
                onPointerUp={onUp}
              >
                <image href={api.url(`/projects/${projectId}/pages/${page}.png?dpi=110`)} x="0" y="0" width={pageInfo.width} height={pageInfo.height} />
                {walls.map((w) => {
                  const [x0, y0, x1, y1] = w.rect;
                  const pad = 3 * px;
                  return (
                    <rect
                      key={w.id}
                      className={`pe-wall is-${w.as}${w.excluded ? " is-out" : ""}${sel === w.id ? " is-sel" : ""}`}
                      x={x0 - pad}
                      y={y0 - pad}
                      width={x1 - x0 + 2 * pad}
                      height={y1 - y0 + 2 * pad}
                      onClick={(e) => {
                        if (tool !== "select" || drag.current?.moved) return;
                        e.stopPropagation();
                        setSel(w.id);
                      }}
                    >
                      <title>{`${fmt(w.length_m)} m · ${CLASS_NAME[w.as]} · ${w.excluded ? "left out" : "counted"}`}</title>
                    </rect>
                  );
                })}
                {drawn.map((a) => (
                  <g key={a.id} className={`pe-drawn is-${a.as}${sel === a.id ? " is-sel" : ""}`}>
                    <line
                      x1={a.x0}
                      y1={a.y0}
                      x2={a.x1}
                      y2={a.y1}
                      strokeWidth={Math.max(4 * px, 1)}
                      onClick={(e) => {
                        if (tool !== "select") return;
                        e.stopPropagation();
                        setSel(a.id);
                      }}
                    />
                    <text x={(a.x0 + a.x1) / 2} y={(a.y0 + a.y1) / 2 - 6 * px} fontSize={12 * px}>
                      {fmt(a.length_m)} m
                    </text>
                  </g>
                ))}
                {measures
                  .filter((m) => m.page === page)
                  .map((m) => (
                    <g key={m.id} className="pe-measure">
                      <line x1={m.a.x} y1={m.a.y} x2={m.b.x} y2={m.b.y} strokeWidth={Math.max(2 * px, 0.5)} />
                      <text x={(m.a.x + m.b.x) / 2} y={(m.a.y + m.b.y) / 2 - 6 * px} fontSize={12 * px}>
                        {lenOf(m.a, m.b) != null ? `${fmt(lenOf(m.a, m.b))} m` : "no scale"}
                      </text>
                    </g>
                  ))}
                {pending && hover && (
                  <g className={tool === "draw" ? `pe-drawn is-${drawAs} is-ghost` : "pe-measure is-ghost"}>
                    <line x1={pending.x} y1={pending.y} x2={hover.x} y2={hover.y} strokeWidth={Math.max(3 * px, 0.5)} />
                    <text x={(pending.x + hover.x) / 2} y={(pending.y + hover.y) / 2 - 6 * px} fontSize={12 * px}>
                      {lenOf(pending, hover) != null ? `${fmt(lenOf(pending, hover))} m` : ""}
                    </text>
                  </g>
                )}
              </svg>
            )}
            {!pageInfo && !err && <p className="calc-empty pe-loading">Loading the sheets…</p>}
          </div>

          <aside className="pe-side">
            {err && <p className="le-err">{err}</p>}
            {plan && (
              <div className="pe-stats">
                <div>
                  <b>{plan.n_counted}</b> of {plan.n_walls} measured walls counted
                </div>
                <div>
                  Partitions: <b>{fmt(plan.counted_m, 1)}</b> of {fmt(plan.total_m, 1)} m measured
                </div>
                {plan.exterior_added_m > 0 && (
                  <div>
                    Added to the exterior wall: <b>{fmt(plan.exterior_added_m, 1)} m</b> × {fmt(plan.storey_height_m)} m high
                  </div>
                )}
                <div className="calc-detail">A drawn or reclassified wall is one storey high: {plan.storey_height_basis}.</div>
                {!plan.editable && (
                  <div className="calc-detail">
                    The partitions on this set are estimated from the floor area, not measured wall by wall, so only the
                    exterior wall and measuring are editable here.
                  </div>
                )}
              </div>
            )}

            {selWall && (
              <div className="pe-card">
                <div className="sc-eyebrow">Measured wall {selWall.id}</div>
                <div className="pe-len">{fmt(selWall.length_m)} m</div>
                <div className="pe-row">
                  <button type="button" className={`pe-chip${!selWall.excluded ? " is-on" : ""}`} disabled={busy} onClick={() => selWall.excluded && toggleOut(selWall.id)}>
                    Counted
                  </button>
                  <button type="button" className={`pe-chip${selWall.excluded ? " is-on" : ""}`} disabled={busy} onClick={() => !selWall.excluded && toggleOut(selWall.id)}>
                    Left out
                  </button>
                </div>
                <div className="pe-row">
                  {Object.entries(CLASS_NAME).map(([k, v]) => (
                    <button key={k} type="button" className={`pe-chip${selWall.as === k ? " is-on" : ""}`} disabled={busy || selWall.excluded} onClick={() => reclass(selWall.id, k)}>
                      {v}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {selDrawn && (
              <div className="pe-card">
                <div className="sc-eyebrow">Wall you drew, {selDrawn.id}</div>
                <div className="pe-len">{fmt(selDrawn.length_m)} m</div>
                <div className="pe-row">
                  {Object.entries(CLASS_NAME).map(([k, v]) => (
                    <button key={k} type="button" className={`pe-chip${selDrawn.as === k ? " is-on" : ""}`} disabled={busy} onClick={() => reclassDrawn(selDrawn.id, k)}>
                      {v}
                    </button>
                  ))}
                </div>
                <button type="button" className="sc-link" disabled={busy} onClick={() => removeDrawn(selDrawn.id)}>
                  Remove this wall
                </button>
              </div>
            )}

            {measures.filter((m) => m.page === page).length > 0 && (
              <div className="pe-card">
                <div className="sc-eyebrow">Measurements on this sheet</div>
                <ul className="pe-list">
                  {measures
                    .filter((m) => m.page === page)
                    .map((m) => (
                      <li key={m.id}>
                        <span>{lenOf(m.a, m.b) != null ? `${fmt(lenOf(m.a, m.b))} m` : "no scale"}</span>
                        <button type="button" className="sc-link" disabled={busy || !mm} onClick={() => addWall(m.a, m.b, "partition").then(() => setMeasures((x) => x.filter((y) => y.id !== m.id)))}>
                          Add as partition
                        </button>
                        <button type="button" className="sc-link" disabled={busy || !mm} onClick={() => addWall(m.a, m.b, "exterior").then(() => setMeasures((x) => x.filter((y) => y.id !== m.id)))}>
                          as exterior
                        </button>
                        <button type="button" className="sc-link" onClick={() => setMeasures((x) => x.filter((y) => y.id !== m.id))} aria-label="Clear">
                          ×
                        </button>
                      </li>
                    ))}
                </ul>
              </div>
            )}

            <div className="pe-legend">
              <span><i className="is-partition" /> partition, counted</span>
              <span><i className="is-exterior" /> reclassified as exterior</span>
              <span><i className="is-out" /> left out</span>
              <span><i className="is-drawn" /> drawn by you</span>
            </div>
            {plan && (plan.added.length > 0 || plan.n_counted < plan.n_walls || plan.pages.some((p) => p.walls.some((w) => w.as !== "partition"))) && (
              <button type="button" className="le-secondary" disabled={busy} onClick={() => send({ excluded: [], classes: {}, added: [] })}>
                Undo every plan edit
              </button>
            )}
            <p className="calc-detail">
              Each change rescales the measured partition lines by the length counted, and grows the exterior wall by
              length × storey height. Every line it changes says so in its calculation.
            </p>
          </aside>
        </div>
      </div>
    </div>,
    document.body,
  );
}
