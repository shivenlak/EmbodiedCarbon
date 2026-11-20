// "Help it read this": the guided fallback for what the drawings did not give up.
//
// When the pipeline cannot find a scale, an outline or the storey heights,
// the person looking at the drawing can usually see them in seconds. This
// puts the sheet in front of them and asks for exactly one thing at a time:
// click both ends of a dimension and type it, click the building's corners,
// or type the heights. The server rebuilds the takeoff with what they said
// (POST /projects/{id}/calibrate), in their workspace only, and every line
// built from it carries a "you said" chip rather than passing for measured.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const MODES = [
  { id: "scale", label: "Set the scale" },
  { id: "outline", label: "Trace the outline" },
  { id: "heights", label: "Storey heights" },
];

const PT_TO_MM = 25.4 / 72;

// Which review notes this can answer.
export const HELP_CODES = new Set([
  "scale_not_found",
  "geometry_ambiguous",
  "storey_height_unknown",
  "sheet_type_missing",
]);
export const canHelp = (gaps) =>
  (gaps || []).some((g) => g.severity !== "info" && HELP_CODES.has(g.code));

// The mode a note asks for.
export function modeFor(gaps) {
  const codes = new Set((gaps || []).filter((g) => g.severity !== "info").map((g) => g.code));
  if (codes.has("scale_not_found") || codes.has("sheet_type_missing")) return "scale";
  if (codes.has("geometry_ambiguous")) return "outline";
  if (codes.has("storey_height_unknown")) return "heights";
  return "scale";
}

export default function HelpRead({ projectId, takeoff, massing, initialMode = "scale", api, onApplied, onClose }) {
  const [pages, setPages] = useState(null);
  const [pageAt, setPageAt] = useState(0);
  const [mode, setMode] = useState(initialMode);
  const [points, setPoints] = useState([]); // scale: up to two clicks
  const [corners, setCorners] = useState([]); // outline
  const [levels, setLevels] = useState([]); // heights: y of each floor line clicked
  const [length, setLength] = useState("");
  const [heights, setHeights] = useState(() => {
    const hs = massing?.storey_heights_m;
    const n = hs?.length || takeoff?.project?.storeys || 2;
    return Array.from({ length: n }, (_, i) => (hs?.[i] ? String(hs[i]) : ""));
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);
  const [stated, setStated] = useState(null);
  const [view, setView] = useState(null);
  const svgRef = useRef(null);
  const drag = useRef(null);

  // The sheet each mode wants: a plan for the scale and the outline, a
  // section (or failing that an elevation) for the levels. When nothing was
  // recognised, the first page with drawing on it, and the pager is right there.
  const pickFor = (list, m) => {
    const want = m === "heights" ? ["section", "elevation"] : ["floor_plan", "foundation_plan"];
    // For the levels, a sheet whose scale is known first: clicks on it
    // become heights straight away.
    if (m === "heights") {
      for (const t of want) {
        const i = list.findIndex((p) => p.sheet_type === t && p.scale_mm_per_pt);
        if (i >= 0) return i;
      }
    }
    for (const t of want) {
      const i = list.findIndex((p) => p.sheet_type === t);
      if (i >= 0) return i;
    }
    return Math.min(1, list.length - 1);
  };

  const loadPages = useCallback(
    () => api.get(`/projects/${projectId}/pages`).then((list) => {
      setPages(list);
      return list;
    }),
    [api, projectId],
  );

  useEffect(() => {
    let live = true;
    loadPages()
      .then((list) => live && setPageAt(pickFor(list, initialMode)))
      .catch((e) => live && setError(`Could not load the sheets: ${e.message}`));
    return () => {
      live = false;
    };
  }, [loadPages]); // eslint-disable-line react-hooks/exhaustive-deps

  const page = pages?.[pageAt];
  useEffect(() => {
    if (!page) return;
    setView({ x: 0, y: 0, w: page.width, h: page.height });
    setPoints([]);
    setCorners([]);
    setLevels([]);
  }, [page?.page]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // ---- the viewer: click to mark, drag to pan, wheel or buttons to zoom ----

  const toPage = (e) => {
    const svg = svgRef.current;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    return [Math.round(p.x * 10) / 10, Math.round(p.y * 10) / 10];
  };

  const zoom = useCallback(
    (factor, at) => {
      setView((v) => {
        if (!v || !page) return v;
        const w = Math.min(page.width, Math.max(page.width / 40, v.w * factor));
        const h = (w / v.w) * v.h;
        const [cx, cy] = at || [v.x + v.w / 2, v.y + v.h / 2];
        const x = cx - ((cx - v.x) * w) / v.w;
        const y = cy - ((cy - v.y) * h) / v.h;
        return { x, y, w, h };
      });
    },
    [page],
  );

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return undefined;
    const onWheel = (e) => {
      e.preventDefault();
      zoom(e.deltaY > 0 ? 1.18 : 1 / 1.18, toPage(e));
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, [zoom, view !== null]); // eslint-disable-line react-hooks/exhaustive-deps

  const onDown = (e) => {
    svgRef.current.setPointerCapture?.(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, view, moved: false };
  };
  const onMove = (e) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 5) return;
    d.moved = true;
    const rect = svgRef.current.getBoundingClientRect();
    const k = Math.max(d.view.w / rect.width, d.view.h / rect.height);
    setView({ ...d.view, x: d.view.x - dx * k, y: d.view.y - dy * k });
  };
  const onUp = (e) => {
    const d = drag.current;
    drag.current = null;
    if (!d || d.moved) return;
    const p = toPage(e);
    setError(null);
    setDone(null);
    if (mode === "scale") setPoints((ps) => (ps.length >= 2 ? [p] : [...ps, p]));
    else if (mode === "heights") setLevels((ls) => (ls.length >= 9 ? ls : [...ls, p[1]]));
    else setCorners((cs) => [...cs, p]);
  };

  // Markers keep a constant size on screen whatever the zoom.
  const unit = useMemo(() => {
    const el = svgRef.current;
    if (!el || !view) return 1;
    const r = el.getBoundingClientRect();
    return Math.max(view.w / (r.width || 1), view.h / (r.height || 1));
  }, [view]);

  // ---- saving ----

  const send = async (body, what) => {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const r = await api.post(`/projects/${projectId}/calibrate`, body);
      setStated(r.stated);
      loadPages().catch(() => {});
      setDone(
        `${what} The total is now ${Math.round(r.carbon.total_kg_co2e || 0).toLocaleString()} kgCO₂e from ${r.lines} lines. Lines built from it show a “you said” chip.`,
      );
      await onApplied?.();
      return true;
    } catch (e) {
      setError(e.message.replace(/^\d+\s*/, ""));
      return false;
    } finally {
      setBusy(false);
    }
  };

  // Floor lines clicked on a section, lowest on the sheet first, become one
  // height per storey through the sheet's scale.
  const sheetScale = page?.scale_mm_per_pt || null;
  useEffect(() => {
    if (mode !== "heights" || levels.length < 2 || !sheetScale) return;
    const ys = [...levels].sort((a, b) => b - a);
    const hs = ys.slice(1).map((y, i) => ((ys[i] - y) * sheetScale) / 1000);
    setHeights(hs.map((h) => h.toFixed(2)));
  }, [levels, sheetScale, mode]);

  const ptsLen = points.length === 2 ? Math.hypot(points[1][0] - points[0][0], points[1][1] - points[0][1]) : 0;

  const saveScale = async () => {
    if (await send({ page: page.page, p1: points[0], p2: points[1], length: length.trim() }, "Scale set.")) {
      setMode("outline");
    }
  };
  const saveOutline = () => send({ page: page.page, corners }, "Outline saved.");
  const saveHeights = () =>
    send({ storey_heights: heights.map((h) => h.trim()).filter(Boolean) }, "Heights saved.");
  const clearAll = () => send({ clear: true }, "Cleared what you stated; the drawings alone again.");

  const scaleOnPage = stated?.scale_mm_per_pt?.[String(page?.page)];

  return (
    <div className="scrim" onClick={onClose}>
      <div className="trace help" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Help it read this">
        <div className="trace-head">
          <div>
            <div className="eyebrow">Help it read this</div>
            <div className="trace-title">Show it what the drawing says, and it will measure the rest</div>
          </div>
          <button className="trace-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div className="help-bar">
          <div className="help-modes" role="tablist" aria-label="What to give it">
            {MODES.map((m) => (
              <button
                key={m.id}
                role="tab"
                aria-selected={mode === m.id}
                className={mode === m.id ? "is-on" : ""}
                onClick={() => {
                  setMode(m.id);
                  setError(null);
                  const cur = pages?.[pageAt]?.sheet_type;
                  const fits =
                    m.id === "heights" ? ["section", "elevation"].includes(cur) : !["section", "elevation"].includes(cur);
                  if (pages && !fits) setPageAt(pickFor(pages, m.id));
                }}
              >
                {m.label}
              </button>
            ))}
          </div>
          {pages && (
            <div className="help-pager">
              <button onClick={() => setPageAt((i) => Math.max(0, i - 1))} disabled={pageAt === 0} aria-label="Previous page">
                ‹
              </button>
              <select value={pageAt} onChange={(e) => setPageAt(Number(e.target.value))} aria-label="Page">
                {pages.map((p, i) => (
                  <option key={p.page} value={i}>
                    {`Page ${p.page + 1}${p.sheet_no ? ` · ${p.sheet_no}` : ""}${
                      p.sheet_type && p.sheet_type !== "unknown" ? ` · ${p.sheet_type.replace(/_/g, " ")}` : ""
                    }`}
                  </option>
                ))}
              </select>
              <button
                onClick={() => setPageAt((i) => Math.min(pages.length - 1, i + 1))}
                disabled={pageAt === pages.length - 1}
                aria-label="Next page"
              >
                ›
              </button>
            </div>
          )}
        </div>

        {pages && pages.length > 1 && (
          <div className="help-strip" role="listbox" aria-label="Pages">
            {pages.map((p, i) => (
              <button
                key={p.page}
                role="option"
                aria-selected={i === pageAt}
                className={i === pageAt ? "is-on" : ""}
                onClick={() => setPageAt(i)}
                title={`Page ${p.page + 1}${p.sheet_no ? ` · ${p.sheet_no}` : ""}`}
                ref={i === pageAt ? (el) => el?.scrollIntoView?.({ block: "nearest", inline: "nearest" }) : undefined}
              >
                <img src={api.url(p.image_url + "?dpi=10")} alt="" loading="lazy" />
                <span>{p.sheet_no || p.page + 1}</span>
              </button>
            ))}
          </div>
        )}

        <p className="help-ask">
          {mode === "scale" &&
            (points.length < 2
              ? "Find a dimension you can read on a plan, and click both ends of it. Scroll or use + to zoom; drag to move."
              : "Now type the length written on that dimension.")}
          {mode === "outline" &&
            (scaleOnPage || corners.length
              ? "Click each outside corner of the building, in order. Press Done when you are back at the start."
              : "Click each outside corner of the building, in order. If it says the page has no scale, set the scale first.")}
          {mode === "heights" &&
            (!sheetScale
              ? "Open a section or elevation, where the floors are drawn as level lines. This sheet has no scale yet: set one first (one dimension), or type the heights below."
              : levels.length === 0
                ? `On a section, click the main floor line, then each floor above it, then the top of the wall. Each gap becomes a storey height.${
                    page?.scale_estimated
                      ? ` (Scale read from this sheet as about 1:${Math.round(sheetScale / PT_TO_MM)}; check the heights look right.)`
                      : ""
                  }`
                : levels.length === 1
                  ? "Now click the next floor line up."
                  : "Keep clicking floor lines, or check the heights below and save. You can edit any of them.")}
        </p>

        <div className="help-stage">
            {!page || !view ? (
              <div className="skeleton help-skel" />
            ) : (
              <svg
                ref={svgRef}
                className="help-sheet"
                viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
                preserveAspectRatio="xMidYMid meet"
                onPointerDown={onDown}
                onPointerMove={onMove}
                onPointerUp={onUp}
                role="img"
                aria-label={`Page ${page.page + 1}; click to mark points`}
              >
                <image href={api.url(page.image_url + "?dpi=110")} x="0" y="0" width={page.width} height={page.height} />
                {mode === "scale" && points.length === 2 && (
                  <line
                    className="help-dim"
                    x1={points[0][0]}
                    y1={points[0][1]}
                    x2={points[1][0]}
                    y2={points[1][1]}
                    vectorEffect="non-scaling-stroke"
                  />
                )}
                {mode === "outline" && corners.length > 1 && (
                  <polygon
                    className="help-outline"
                    points={corners.map((c) => c.join(",")).join(" ")}
                    vectorEffect="non-scaling-stroke"
                  />
                )}
                {(mode === "scale" ? points : mode === "outline" ? corners : []).map((p, i) => (
                  <circle key={i} className="help-dot" cx={p[0]} cy={p[1]} r={6 * unit} vectorEffect="non-scaling-stroke" />
                ))}
                {mode === "heights" &&
                  [...levels]
                    .sort((a, b) => b - a)
                    .map((y, i) => (
                      <g key={i}>
                        <line className="help-level" x1={view.x} x2={view.x + view.w} y1={y} y2={y} vectorEffect="non-scaling-stroke" />
                        <text className="help-level-tag" x={view.x + 12 * unit} y={y - 6 * unit} fontSize={13 * unit}>
                          {i === 0 ? "floor 1" : `level ${i + 1}`}
                        </text>
                      </g>
                    ))}
              </svg>
            )}
            <div className="help-zoom">
              <button onClick={() => zoom(1 / 1.5)} aria-label="Zoom in">
                +
              </button>
              <button onClick={() => zoom(1.5)} aria-label="Zoom out">
                −
              </button>
              <button
                onClick={() => page && setView({ x: 0, y: 0, w: page.width, h: page.height })}
                aria-label="Whole sheet"
              >
                ⤢
              </button>
            </div>
        </div>
        {mode === "heights" && (
          <div className="help-heights">
            {heights.map((h, i) => (
              <label key={i}>
                <span>Storey {i + 1}</span>
                <input
                  value={h}
                  inputMode="decimal"
                  placeholder="3.0"
                  onChange={(e) => setHeights((hs) => hs.map((x, j) => (j === i ? e.target.value : x)))}
                />
              </label>
            ))}
            <div className="help-heights-n">
              <button onClick={() => setHeights((hs) => [...hs, ""])} disabled={heights.length >= 8}>
                Add a storey
              </button>
              <button onClick={() => setHeights((hs) => hs.slice(0, -1))} disabled={heights.length <= 1}>
                Remove one
              </button>
              {levels.length > 0 && (
                <button onClick={() => setLevels((ls) => ls.slice(0, -1))}>Undo last line</button>
              )}
              {!sheetScale && (
                <button onClick={() => setMode("scale")}>Set this sheet&apos;s scale</button>
              )}
            </div>
          </div>
        )}

        <div className="help-foot">
          {mode === "scale" && (
            <>
              <label className="help-len">
                <span>Length between the two points</span>
                <input
                  value={length}
                  onChange={(e) => setLength(e.target.value)}
                  placeholder={"7160, 7.16 m or 23'-6\""}
                  disabled={points.length < 2}
                  onKeyDown={(e) => e.key === "Enter" && length.trim() && points.length === 2 && saveScale()}
                />
              </label>
              {points.length === 2 && length.trim() && ptsLen > 0 && (
                <span className="help-hint">{ratioHint(length, ptsLen)}</span>
              )}
              <button className="btn-primary" onClick={saveScale} disabled={busy || points.length < 2 || !length.trim()}>
                {busy ? "Setting…" : "Set scale"}
              </button>
            </>
          )}
          {mode === "outline" && (
            <>
              <span className="help-hint">{corners.length} corners</span>
              <button onClick={() => setCorners((cs) => cs.slice(0, -1))} disabled={!corners.length}>
                Undo last corner
              </button>
              <button className="btn-primary" onClick={saveOutline} disabled={busy || corners.length < 3}>
                {busy ? "Measuring…" : "Done"}
              </button>
            </>
          )}
          {mode === "heights" && (
            <button className="btn-primary" onClick={saveHeights} disabled={busy || !heights.some((h) => h.trim())}>
              {busy ? "Saving…" : "Save heights"}
            </button>
          )}
          {stated && (stated.footprint || stated.storey_heights_m || Object.keys(stated.scale_mm_per_pt || {}).length > 0) && (
            <button className="help-clear" onClick={clearAll} disabled={busy}>
              Clear what I stated
            </button>
          )}
        </div>

        {(error || done) && (
          <p className={`help-msg ${error ? "is-err" : "is-ok"}`} role={error ? "alert" : "status"}>
            {error || done}
          </p>
        )}
      </div>
    </div>
  );
}

// What scale that length implies, as a sanity check before saving: a typo
// that makes the drawing 1:7 or 1:4000 is visible at once.
function ratioHint(length, pts) {
  const t = length.trim();
  let mm = null;
  const metric = t.match(/^(\d+(?:[.,]\d+)?)\s*(mm|cm|m)?$/i);
  if (metric) {
    const v = parseFloat(metric[1].replace(",", "."));
    const u = (metric[2] || "").toLowerCase();
    mm = u === "m" || (!u && v < 100) ? v * 1000 : u === "cm" ? v * 10 : v;
  } else {
    const imp = t.match(/^(\d+)\s*['’]\s*-?\s*(\d+(?:\.\d+)?)?\s*(?:(\d+)\/(\d+))?\s*["”]?$/);
    if (imp) {
      const inches = Number(imp[2] || 0) + (imp[3] ? Number(imp[3]) / Number(imp[4]) : 0);
      mm = Number(imp[1]) * 304.8 + inches * 25.4;
    }
  }
  if (!mm) return "";
  const ratio = mm / pts / PT_TO_MM;
  return `about 1:${ratio < 20 ? ratio.toFixed(1) : Math.round(ratio)} on the printed sheet`;
}
