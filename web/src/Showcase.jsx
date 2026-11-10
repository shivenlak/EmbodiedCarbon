// The showcase: the measured building, full screen, in front of the building
// the drawings describe. Loaded on demand, so the classic view never pays for
// three.js.
//
// The deck of panels is not navigation bolted onto a picture. Each panel
// drives the scene: the carbon panel turns the heat map on, hovering a
// quantity lights its element in the model, and pressing a surface in the
// model opens the panel that explains it.

import { useEffect, useMemo, useRef, useState } from "react";
import { createScene } from "./scene.js";
import {
  int,
  dec,
  titleCase,
  isCounted,
  useCountUp,
  Confidence,
  UNIT_LABEL,
  CLASS_LABEL,
  PARTITION_PREFIX,
  HEAT,
  heatColour,
  surfaceIntensity,
  gapTopic,
  floorAreaNote,
  decisionKey,
  EMPTY_SCENARIO,
  authedUrl,
} from "./App.jsx";
import "./showcase.css";

const STILL =
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

const PANELS = [
  { id: "read", label: "The building" },
  { id: "quantities", label: "Quantities" },
  { id: "carbon", label: "Carbon" },
  { id: "notes", label: "Open questions" },
  { id: "spec", label: "Try a spec" },
];

// The element each class is billed under, for "press a surface, see its line".
const LINE_FOR = {
  slab_on_grade: "ln-slab-on-grade",
  footing: "ln-grade-beam",
  exterior_wall: "ln-exterior-wall",
  window: "ln-windows",
  door: "ln-doors",
};

const MODEL_ORDER = [
  "slab_on_grade",
  "footing",
  "exterior_wall",
  "window",
  "door",
  "interior_partition",
];

export default function Showcase({
  projects,
  projectId,
  onProject,
  takeoff,
  carbon,
  massing,
  swaps,
  decisions,
  scenario,
  onScenario,
  onTrace,
  onClassic,
  onUpload,
}) {
  const canvasRef = useRef(null);
  const sceneRef = useRef(null);
  const deckRef = useRef(null);
  const [panel, setPanel] = useState(0);
  const [focus, setFocus] = useState(null);
  const [hover, setHover] = useState(null);
  const [storey, setStorey] = useState(null);
  const [explode, setExplode] = useState(0);
  const [heatPinned, setHeatPinned] = useState(false);
  const [deckOpen, setDeckOpen] = useState(true);
  const [cover, setCover] = useState("loading"); // loading | ok | none
  const [intro, setIntro] = useState(!STILL);
  const [spinning, setSpinning] = useState(!STILL);
  const [glError, setGlError] = useState(null);

  const heat = heatPinned || PANELS[panel].id === "carbon" || PANELS[panel].id === "spec";
  const lines = takeoff?.lines || [];
  const carbonLines = carbon?.lines || [];
  const kgOf = useMemo(
    () => new Map(carbonLines.map((l) => [l.line_id, l.kg_co2e])),
    [carbonLines],
  );
  const p = takeoff?.project || {};
  const heights = massing?.storey_heights_m || [];

  const surfaces = useMemo(() => (massing ? surfaceIntensity(massing) : null), [massing]);

  // ---- the scene ---------------------------------------------------------

  useEffect(() => {
    if (!massing || !canvasRef.current || !surfaces) return undefined;
    let handle;
    try {
      handle = createScene(canvasRef.current, massing, {
        heatColour,
        intensity: surfaces.intensity,
        hotI: surfaces.hotI,
        coolI: surfaces.coolI,
        still: STILL,
      });
    } catch (e) {
      setGlError(e?.message || "WebGL is not available in this browser");
      return undefined;
    }
    sceneRef.current = handle;
    handle.onHover(setHover);
    handle.onPick((cls) => {
      setFocus(cls);
      goTo(cls === "interior_partition" || LINE_FOR[cls] ? 1 : 2);
    });
    setSpinning(!STILL);
    return () => {
      handle.dispose();
      sceneRef.current = null;
    };
    // goTo is stable in effect (reads refs only)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [massing, surfaces]);

  useEffect(() => {
    sceneRef.current?.set({ heat, storey, explode, focus, build: !intro });
  }, [heat, storey, explode, focus, massing, intro]);

  // Centre the building in the space the deck leaves, on a wide screen.
  useEffect(() => {
    const measure = () => {
      const wide = window.innerWidth > 820;
      const deck = document.querySelector(".sc-deck-inner");
      const inset = wide && deckOpen && deck ? deck.getBoundingClientRect().width + 32 : 0;
      sceneRef.current?.set({ insetRight: inset });
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [deckOpen, massing]);

  // ---- backdrop: the rendering from the plan set's cover ------------------

  const coverUrl = projectId ? authedUrl(`/projects/${projectId}/cover.jpg`) : null;
  useEffect(() => {
    if (!coverUrl) return undefined;
    setCover("loading");
    setIntro(!STILL);
    const img = new Image();
    img.onload = () => setCover("ok");
    img.onerror = () => {
      setCover("none");
      setIntro(false);
    };
    img.src = coverUrl;
    // The photograph is shown clear for a beat, then steps back behind the
    // model -- "here is the house; here is what we read from its drawings".
    const t = setTimeout(() => setIntro(false), STILL ? 0 : 2200);
    return () => clearTimeout(t);
  }, [coverUrl]);

  // ---- the deck ----------------------------------------------------------

  function goTo(i) {
    const el = deckRef.current;
    const n = Math.max(0, Math.min(PANELS.length - 1, i));
    setPanel(n);
    if (el) el.scrollTo({ left: n * el.clientWidth, behavior: STILL ? "auto" : "smooth" });
  }
  // Native scroll-snap does the swipe; this only reads where it landed.
  function onDeckScroll() {
    const el = deckRef.current;
    if (!el) return;
    const n = Math.round(el.scrollLeft / Math.max(1, el.clientWidth));
    if (n !== panel) setPanel(n);
  }
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.closest?.("input, textarea, select")) return;
      if (e.key === "ArrowRight") goTo(panel + 1);
      if (e.key === "ArrowLeft") goTo(panel - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  useEffect(() => {
    setPanel(0);
    setFocus(null);
    setStorey(null);
    setExplode(0);
    deckRef.current?.scrollTo({ left: 0 });
  }, [projectId]);

  // ---- figures -----------------------------------------------------------

  const total = carbon?.total_kg_co2e;
  const shownTotal = useCountUp(total, 1400);
  const partitions = carbonLines
    .filter((l) => isCounted(l) && String(l.line_id).startsWith(PARTITION_PREFIX))
    .reduce((sum, l) => sum + (l.kg_co2e || 0), 0);

  const byClass = useMemo(() => {
    const m = new Map();
    for (const line of lines) {
      const kg = kgOf.get(line.id);
      if (kg) m.set(line.element_class, (m.get(line.element_class) || 0) + kg);
    }
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [lines, kgOf]);
  const topKg = byClass[0]?.[1] || 1;

  const scenarioTotal = useMemo(() => {
    let t = total || 0;
    for (const s of swaps || []) if (scenario.swaps[s.line_id] === s.to_material) t += s.delta_kg_co2e || 0;
    for (const c of decisions || []) {
      const o = c.options.find((x) => x.factor_id === scenario.picks[decisionKey(c)]);
      if (o) t += o.kg_co2e || 0;
    }
    return t;
  }, [total, swaps, decisions, scenario]);
  const scenarioActive =
    Object.keys(scenario.swaps).length > 0 || Object.keys(scenario.picks).length > 0;
  const shownSpec = useCountUp(scenarioTotal, 600);

  const counts = useMemo(() => {
    const c = { measured: 0, inferred: 0, assumed: 0 };
    for (const l of lines) if (c[l.confidence] != null) c[l.confidence] += 1;
    return c;
  }, [lines]);

  const modelLines = MODEL_ORDER.map((cls) =>
    cls === "interior_partition"
      ? lines.find((l) => l.id.startsWith(PARTITION_PREFIX))
      : lines.find((l) => l.id === LINE_FOR[cls]),
  ).filter(Boolean);

  const sheets = takeoff?.sheets || [];
  const readable = sheets.filter((s) => s.readable).length;
  const areaNote = floorAreaNote(takeoff?.gaps);

  // The distinct notes: one per topic, so five topics read as five things.
  const noteTopics = useMemo(() => {
    const seen = new Map();
    const rank = { blocking: 0, warning: 1, info: 2 };
    for (const g of [...(takeoff?.gaps || [])].sort(
      (a, b) => (rank[a.severity] ?? 3) - (rank[b.severity] ?? 3),
    )) {
      const key = `${g.severity}:${g.code}`;
      if (!seen.has(key)) seen.set(key, { ...g, n: 1 });
      else seen.get(key).n += 1;
    }
    return [...seen.values()];
  }, [takeoff]);

  const firstSentence = (t) => {
    const s = String(t || "");
    const i = s.search(/[.;:](\s|$)/);
    return i > 40 && i < 220 ? s.slice(0, i + 1) : s.length > 200 ? `${s.slice(0, 200)}…` : s;
  };

  const toggleSwap = (s) =>
    onScenario((sc) => {
      const next = { ...sc.swaps };
      if (next[s.line_id] === s.to_material) delete next[s.line_id];
      else next[s.line_id] = s.to_material;
      return { ...sc, swaps: next };
    });
  const pick = (c, o) =>
    onScenario((sc) => {
      const picks = { ...sc.picks };
      if (picks[decisionKey(c)] === o.factor_id) delete picks[decisionKey(c)];
      else picks[decisionKey(c)] = o.factor_id;
      return { ...sc, picks };
    });
  const nameOf = (id) => {
    const l = lines.find((x) => x.id === id);
    return l ? `${titleCase(l.element_class)}${l.assembly_tag ? ` ${l.assembly_tag}` : ""}` : id;
  };

  const shortName = (p0) => (p0?.name || "").replace(/ Technical Design Package$/i, "");

  // ---- render ------------------------------------------------------------

  return (
    <div className={`sc${intro ? " is-intro" : ""}${heat ? " is-heat" : ""}`}>
      <div
        className={`sc-backdrop${cover === "ok" ? " has-cover" : ""}`}
        style={cover === "ok" ? { backgroundImage: `url(${coverUrl})` } : undefined}
        aria-hidden="true"
      />
      <div className="sc-veil" aria-hidden="true" />

      {!takeoff ? (
        <div className="sc-wait" role="status">
          <span className="sc-wait-ring" aria-hidden="true" />
          Reading the plan set…
        </div>
      ) : massing && !glError ? (
        <canvas
          ref={canvasRef}
          className="sc-canvas"
          role="img"
          aria-label={`The measured building in 3D: ${massing.width_m} by ${massing.depth_m} metres, ${heights.length} storeys, ${massing.walls.length} partition walls. Drag to orbit, scroll to zoom.`}
        />
      ) : (
        <div className="sc-nomodel glass">
          <h2>No model for this plan set</h2>
          <p>
            {glError
              ? `This browser could not start 3D (${glError}). The classic view has every figure.`
              : "A model needs a measured footprint and the storey datums from the sections, and this set did not state both. Drawing a guess would be the one thing this view exists not to do."}
          </p>
          <button className="sc-btn" onClick={() => onClassic("model")}>
            Open the classic view
          </button>
        </div>
      )}

      {cover === "ok" && intro && (
        <div className="sc-intro-caption">
          <span>{shortName(projects.find((x) => x.id === projectId))}</span>
          <em>as drawn, from the cover of its plan set</em>
        </div>
      )}

      {/* ---- top bar ---- */}
      <header className="sc-top">
        <div className="glass sc-brand">
          <span className="sc-logo" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="18" height="18">
              <path d="M4 7h16M4 12h16M4 17h10" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" fill="none" />
            </svg>
          </span>
          <b>ecarbon</b>
          <label className="sc-select">
            <span className="sr">Plan set</span>
            <select value={projectId || ""} onChange={(e) => onProject(e.target.value)}>
              {projects.map((x) => (
                <option key={x.id} value={x.id}>
                  {shortName(x)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="sc-top-actions">
          <button className="glass sc-btn" onClick={() => onClassic("model")}>
            Classic view
          </button>
          <button className="sc-btn sc-btn-primary" onClick={onUpload}>
            Upload a plan set
          </button>
        </div>
      </header>

      {/* ---- the figure ---- */}
      {total != null && (
      <section className="sc-hero" aria-live="polite">
        <div className="sc-eyebrow">Embodied carbon · A1–A3, product stage</div>
        <div className="sc-figure">
          {total == null ? "—" : int(shownTotal)}
          <span>kgCO₂e</span>
        </div>
        <div className="sc-sub">
          <span>
            <b>{dec(carbon?.intensity_kg_co2e_per_m2, 1)}</b> kg/m² over{" "}
            {p.gfa_m2 ? dec(p.gfa_m2, 0) : "—"} m²
          </span>
          {partitions > 0 && (
            <span>
              <b>{int(total - partitions)}</b> without the inferred partitions
            </span>
          )}
        </div>
        {scenarioActive && (
          <button className="sc-spec-chip" onClick={() => goTo(4)}>
            Your spec <b>{int(shownSpec)}</b>
            <em>
              {scenarioTotal <= total ? "−" : "+"}
              {int(Math.abs(scenarioTotal - total))}
            </em>
          </button>
        )}
      </section>
      )}

      {/* ---- hover read-out ---- */}
      {hover && (
        <div
          className="sc-tip glass"
          style={{ left: hover.x + 16, top: hover.y + 16 }}
          role="status"
        >
          <b>{hover.label}</b>
          <span>{hover.detail}</span>
          {surfaces?.intensity[hover.cls] != null && (
            <span className="sc-tip-heat">
              <i style={{ background: heatColour(surfaces.intensity[hover.cls], surfaces.hotI, surfaces.coolI) }} />
              {dec(surfaces.intensity[hover.cls], 1)} kgCO₂e/m² of surface
            </span>
          )}
          <em>press to see where it came from</em>
        </div>
      )}

      {/* ---- the deck ---- */}
      {takeoff && (
      <aside className={`sc-deck${deckOpen ? "" : " is-closed"}`} aria-label="Details">
        <div className="glass sc-deck-inner">
          <nav className="sc-tabs" aria-label="Panels">
            {PANELS.map((x, i) => (
              <button
                key={x.id}
                className={i === panel ? "is-on" : ""}
                aria-current={i === panel ? "true" : undefined}
                onClick={() => goTo(i)}
              >
                {x.label}
              </button>
            ))}
          </nav>

          <div className="sc-track" ref={deckRef} onScroll={onDeckScroll}>
            {/* 1. what was read */}
            <section className="sc-panel" aria-label="The building">
              <h2>Read from a {sheets.length}-sheet PDF</h2>
              <p className="sc-lede">
                Every solid in the model is a quantity the takeoff measured or
                read. Nothing was modelled by hand, so a misread drawing would
                show up as a wrong shape.
              </p>
              <dl className="sc-facts">
                <div><dt>Footprint</dt><dd>{dec(massing?.width_m, 1)} × {dec(massing?.depth_m, 1)} m</dd></div>
                <div><dt>Storeys</dt><dd>{heights.length || p.storeys || "—"}</dd></div>
                <div><dt>Units</dt><dd>{p.units ?? "—"}</dd></div>
                <div><dt>Partitions</dt><dd>{massing?.walls?.length ?? "—"} walls</dd></div>
                <div><dt>Sheets read</dt><dd>{readable} of {sheets.length}</dd></div>
                <div><dt>Bill</dt><dd>{lines.length} lines</dd></div>
              </dl>
              <div className="sc-basis">
                <span><Confidence value="measured" /> {counts.measured} off the linework</span>
                <span><Confidence value="inferred" /> {counts.inferred} from what a sheet states</span>
                <span><Confidence value="assumed" /> {counts.assumed} where a standard stood in</span>
              </div>
              {areaNote && <p className="sc-flag">Floor area {areaNote}.</p>}
              <p className="sc-hint">
                Drag to orbit on any axis, scroll to zoom, right-drag to pan.
                Windows and doors are counted in the bill but not drawn: the
                takeoff has their sizes, not their positions.
              </p>
            </section>

            {/* 2. quantities */}
            <section className="sc-panel" aria-label="Quantities">
              <h2>Press a quantity for its sheet</h2>
              <ul className="sc-qty">
                {modelLines.map((line) => {
                  const isPart = line.id.startsWith(PARTITION_PREFIX);
                  const walls = massing?.walls?.length;
                  const qty = isPart && walls ? walls : line.user_override ?? line.quantity;
                  const unit = isPart && walls ? "walls" : UNIT_LABEL[line.unit] || line.unit;
                  const cls = line.element_class;
                  return (
                    <li key={line.id}>
                      <button
                        className={focus === cls ? "is-on" : ""}
                        onMouseEnter={() => setFocus(cls)}
                        onMouseLeave={() => setFocus(null)}
                        onFocus={() => setFocus(cls)}
                        onBlur={() => setFocus(null)}
                        onClick={() => onTrace(line.id, line.provenance)}
                      >
                        <span className="sc-qty-name">
                          {CLASS_LABEL[cls] || titleCase(cls)}
                          <Confidence value={line.confidence} />
                        </span>
                        <span className="sc-qty-num">
                          {dec(qty, line.unit === "each" || unit === "walls" ? 0 : 1)}
                          <em>{unit}</em>
                        </span>
                        <span className="sc-sheet">{line.provenance?.sheet_no || "—"}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
              <button className="sc-link" onClick={() => onClassic("quantities")}>
                All {lines.length} lines, with factors and derivations →
              </button>
            </section>

            {/* 3. carbon */}
            <section className="sc-panel" aria-label="Carbon">
              <h2>Where the carbon is</h2>
              <p className="sc-lede">
                The model is coloured by carbon per square metre of surface.
                Hover a row to find it.
              </p>
              <ul className="sc-bars">
                {byClass.map(([cls, kg]) => {
                  const dens = surfaces?.intensity[cls];
                  return (
                    <li
                      key={cls}
                      className={focus === cls ? "is-on" : ""}
                      onMouseEnter={() => setFocus(cls)}
                      onMouseLeave={() => setFocus(null)}
                    >
                      <span className="sc-bar-name">
                        <i
                          style={{
                            background:
                              dens != null && surfaces
                                ? heatColour(dens, surfaces.hotI, surfaces.coolI)
                                : "transparent",
                          }}
                          className={dens == null ? "is-none" : ""}
                        />
                        {CLASS_LABEL[cls] || titleCase(cls)}
                      </span>
                      <span className="sc-bar-track">
                        <s style={{ width: `${(kg / topKg) * 100}%` }} />
                      </span>
                      <b>{int(kg)}</b>
                      <em>{dens != null ? `${dec(dens, 1)}/m²` : "not drawn"}</em>
                    </li>
                  );
                })}
              </ul>
              <div className="sc-ramp" aria-hidden="true">
                <span>lighter per m²</span>
                <i style={{ background: `linear-gradient(90deg, ${HEAT.join(",")})` }} />
                <span>heavier</span>
              </div>
            </section>

            {/* 4. notes */}
            <section className="sc-panel" aria-label="Open questions">
              <h2>{takeoff?.gaps?.length ?? 0} things the drawings leave open</h2>
              <p className="sc-lede">
                Flagged instead of assumed. A low total that does not say it is
                partial looks exactly like a good one.
              </p>
              <ul className="sc-notes">
                {noteTopics.slice(0, 5).map((g, i) => (
                  <li key={i} className={`sev-${g.severity}`}>
                    <span className="sc-note-head">
                      {g.severity === "blocking" ? "Read this first" : "Worth knowing"} ·{" "}
                      {gapTopic(g.code)}
                      {g.n > 1 && <em> ×{g.n}</em>}
                    </span>
                    <span>{firstSentence(g.message)}</span>
                  </li>
                ))}
              </ul>
              <button className="sc-link" onClick={() => onClassic("gaps")}>
                Every note, and every sheet →
              </button>
            </section>

            {/* 5. scenario */}
            <section className="sc-panel" aria-label="Try a specification">
              <h2>Try a spec before it is locked</h2>
              <div className="sc-spec">
                <div>
                  <span>Counted</span>
                  <b>{int(total)}</b>
                </div>
                <div className="sc-spec-you">
                  <span>Your spec</span>
                  <b>{int(shownSpec)}</b>
                </div>
                {scenarioActive && (
                  <button className="sc-reset" onClick={() => onScenario(EMPTY_SCENARIO)}>
                    Reset
                  </button>
                )}
              </div>
              {(decisions || []).map((c) => (
                <div className="sc-decision" key={decisionKey(c)}>
                  <span className="sc-decision-head">
                    {c.category} <em>drawn as a placeholder, not counted</em>
                  </span>
                  <div className="sc-chips">
                    {c.options.map((o) => {
                      const on = scenario.picks[decisionKey(c)] === o.factor_id;
                      return (
                        <button
                          key={o.factor_id}
                          className={on ? "is-on" : ""}
                          aria-pressed={on}
                          onClick={() => pick(c, o)}
                        >
                          {o.name} <b>+{int(o.kg_co2e)}</b>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
              <ul className="sc-swaps">
                {(swaps || []).slice(0, 5).map((s) => {
                  const on = scenario.swaps[s.line_id] === s.to_material;
                  return (
                    <li key={`${s.line_id}|${s.to_material}`}>
                      <button className={on ? "is-on" : ""} aria-pressed={on} onClick={() => toggleSwap(s)}>
                        <span>
                          <b>{nameOf(s.line_id)}</b>
                          {s.to_material}
                        </span>
                        <em>{int(s.delta_kg_co2e)}</em>
                      </button>
                    </li>
                  );
                })}
              </ul>
              <button className="sc-link" onClick={() => onClassic("options")}>
                All {swaps?.length || 0} swaps, ranked, with their caveats →
              </button>
            </section>
          </div>

          <div className="sc-deck-foot">
            <button className="sc-arrow" onClick={() => goTo(panel - 1)} disabled={panel === 0} aria-label="Previous panel">
              <svg viewBox="0 0 24 24" width="16" height="16"><path d="M15 6l-6 6 6 6" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </button>
            <div className="sc-dots" aria-hidden="true">
              {PANELS.map((x, i) => (
                <i key={x.id} className={i === panel ? "is-on" : ""} />
              ))}
            </div>
            <button className="sc-arrow" onClick={() => goTo(panel + 1)} disabled={panel === PANELS.length - 1} aria-label="Next panel">
              <svg viewBox="0 0 24 24" width="16" height="16"><path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </button>
          </div>
        </div>
        <button className="glass sc-deck-toggle" onClick={() => setDeckOpen((o) => !o)} aria-expanded={deckOpen}>
          {deckOpen ? "Hide panels" : "Show panels"}
        </button>
      </aside>
      )}

      {/* ---- the dock: what the model shows ---- */}
      {massing && !glError && (
        <nav className="sc-dock glass" aria-label="Model controls">
          <div className="sc-seg" role="group" aria-label="Colour the model by">
            <button className={!heat ? "is-on" : ""} onClick={() => { setHeatPinned(false); if (PANELS[panel].id === "carbon" || PANELS[panel].id === "spec") goTo(0); }}>
              Structure
            </button>
            <button className={heat ? "is-on" : ""} onClick={() => setHeatPinned(true)}>
              Heat map
            </button>
          </div>
          <div className="sc-seg" role="group" aria-label="Storeys shown">
            <button className={storey == null ? "is-on" : ""} onClick={() => setStorey(null)}>All</button>
            {heights.map((_, i) => (
              <button key={i} className={storey === i ? "is-on" : ""} onClick={() => setStorey(i)}>
                L{i + 1}
              </button>
            ))}
          </div>
          <label className="sc-explode">
            <span>Explode</span>
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={explode}
              onChange={(e) => setExplode(Number(e.target.value))}
            />
          </label>
          <div className="sc-seg" role="group" aria-label="Camera">
            {["top", "front", "side", "under"].map((v) => (
              <button key={v} onClick={() => { sceneRef.current?.view(v); setSpinning(false); }}>
                {v[0].toUpperCase() + v.slice(1)}
              </button>
            ))}
            <button
              className={spinning ? "is-on" : ""}
              onClick={() => {
                const next = !spinning;
                setSpinning(next);
                if (next) sceneRef.current?.reset();
                else sceneRef.current?.spin(false);
              }}
              aria-pressed={spinning}
            >
              Spin
            </button>
          </div>
        </nav>
      )}
    </div>
  );
}
