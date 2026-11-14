// The showcase: the measured building, full screen, in front of the building
// the drawings describe. Loaded on demand, so the classic view never pays for
// three.js.
//
// The deck of panels is not navigation bolted onto a picture. Each panel
// drives the scene: the carbon panel turns the heat map on, hovering a
// quantity lights its element in the model, and pressing a surface in the
// model opens the panel that explains it.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createScene, SPLIT_STOREYS } from "./scene.js";
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
  openingsOf,
  gapTopic,
  floorAreaNote,
  decisionKey,
  EMPTY_SCENARIO,
  authedUrl,
  DetailPage,
  AppFooter,
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
  onOverride,
  coverage,
  page = "model",
  onPage,
  onUpload,
  who,
  onSignOut,
  exportHref,
  reportHref,
}) {
  // The pages that open as a sheet over the model, in their order.
  const SHEETS = [
    { id: "quantities", label: "Bill of quantities" },
    { id: "gaps", label: "Review notes" },
    { id: "options", label: "Options" },
  ];
  const sheetOpen = page && page !== "model";
  const canvasRef = useRef(null);
  const sceneRef = useRef(null);
  const deckRef = useRef(null);
  const [panel, setPanel] = useState(0);
  const [focus, setFocus] = useState(null);
  const [hover, setHover] = useState(null);
  const [storey, setStorey] = useState(null);
  // The pitched roof: its ridge is measured, its shape illustrative. Only
  // offered when the sections gave a roof datum.
  const [roofOn, setRoofOn] = useState(true);
  // One slider: the first stretch opens the storeys, the rest takes the
  // building to pieces.
  // The split itself never goes through React: a slider tick is handed
  // straight to the scene, and only crossing into "apart" re-renders.
  const splitRef = useRef(0);
  const [broken, setBroken] = useState(false);
  const [picked, setPicked] = useState(null);
  const [landed, setLanded] = useState([]);
  const [inventory, setInventory] = useState({});
  const sliderRef = useRef(null);
  const slotEls = useRef(new Map());
  const listRef = useRef(null);
  const brokenRef = useRef(false);
  brokenRef.current = broken;
  const [apart, setApart] = useState(false);
  const apartRef = useRef(false);
  const trayUp = broken || apart;
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

  // Keyed by value: a correction re-fetches the takeoff, and a new object
  // here would rebuild the whole scene mid-gesture.
  const openingsKey = JSON.stringify(openingsOf(takeoff));
  const openings = useMemo(() => JSON.parse(openingsKey), [openingsKey]);
  const surfaces = useMemo(
    () => (massing ? surfaceIntensity(massing, openings) : null),
    [massing, openings],
  );

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
        openings,
      });
    } catch (e) {
      setGlError(e?.message || "WebGL is not available in this browser");
      return undefined;
    }
    sceneRef.current = handle;
    handle.onHover(setHover);
    handle.onPick((cls) => {
      if (brokenRef.current) {
        setPicked((c) => (c === cls ? null : cls));
        return;
      }
      setFocus(cls);
      goTo(cls === "interior_partition" || LINE_FOR[cls] ? 1 : 2);
    });
    // The slider follows the building as it comes apart, without a render
    // per frame.
    handle.onSplit((v, settled) => {
      if (sliderRef.current) sliderRef.current.value = String(v);
      // The list stays up until the last block has left it, so a rebuild
      // flies the pieces home from their rows instead of from nowhere.
      const apart = v > SPLIT_STOREYS + 1e-4;
      if (apart !== apartRef.current) {
        apartRef.current = apart;
        setApart(apart);
      }
    });
    handle.onLanded(setLanded);
    setInventory(handle.inventory());
    setSpinning(!STILL);
    return () => {
      handle.dispose();
      sceneRef.current = null;
    };
    // goTo is stable in effect (reads refs only)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [massing, surfaces, openings]);

  useEffect(() => {
    sceneRef.current?.set({
      heat,
      storey,
      focus: broken ? picked ?? focus : focus,
      selected: broken ? picked : null,
      build: !intro,
      roof: roofOn,
    });
  }, [heat, storey, focus, picked, broken, massing, intro, roofOn]);

  // Centre the building in the space the deck leaves, on a wide screen.
  useEffect(() => {
    const measure = () => {
      const wide = window.innerWidth > 820;
      const deck = document.querySelector(".sc-deck-inner");
      const tray = document.querySelector(".bd");
      const inset = !wide
        ? 0
        : broken && tray
          ? -(tray.getBoundingClientRect().width + 32)
          : deckOpen && deck
            ? deck.getBoundingClientRect().width + 32
            : 0;
      sceneRef.current?.set({ insetRight: inset });
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [deckOpen, massing, broken]);

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

  // While a scroll this code started is in flight, the panel is the one it
  // is heading for. Reading every intermediate position instead made a press
  // on "Carbon" land back on "Quantities", and a swipe past Carbon flicker
  // the heat map on and off as the deck passed through it.
  const steering = useRef(null);
  const steerTimer = useRef(0);
  function goTo(i) {
    const el = deckRef.current;
    const n = Math.max(0, Math.min(PANELS.length - 1, i));
    setPanel(n);
    if (!el) return;
    steering.current = n;
    clearTimeout(steerTimer.current);
    // A backstop in case the browser never reports arriving.
    steerTimer.current = setTimeout(() => {
      steering.current = null;
    }, 900);
    el.scrollTo({ left: n * el.clientWidth, behavior: STILL ? "auto" : "smooth" });
  }
  // Native scroll-snap does the swipe; this only reads where it settled.
  function onDeckScroll() {
    const el = deckRef.current;
    if (!el) return;
    const n = Math.round(el.scrollLeft / Math.max(1, el.clientWidth));
    if (steering.current != null) {
      if (n === steering.current && Math.abs(el.scrollLeft - n * el.clientWidth) < 2) {
        steering.current = null;
      }
      return;
    }
    // A swipe: commit only once it is within a few pixels of a panel, so
    // the heat map does not switch while the deck is between two.
    if (Math.abs(el.scrollLeft - n * el.clientWidth) > 8) return;
    if (n !== panel) setPanel(n);
  }
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.closest?.("input, textarea, select")) return;
      // A trace dialog over everything owns the keyboard.
      if (document.querySelector(".scrim")) return;
      if (sheetOpen) {
        if (e.key === "Escape") onPage("model");
        return;
      }
      if (broken && e.key === "Escape") {
        if (picked) setPicked(null);
        else rebuild();
        return;
      }
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
    splitRef.current = 0;
    setBroken(false);
    setPicked(null);
    // A new building starts whole.
    apartRef.current = false;
    setApart(false);
    setLanded([]);
    if (sliderRef.current) sliderRef.current.value = "0";
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

  // ---- the parts list ----------------------------------------------------

  const carbonById = useMemo(() => new Map(carbonLines.map((l) => [l.line_id, l])), [carbonLines]);
  const groups = useMemo(() => {
    const kg = new Map(byClass);
    const classes = new Set([...Object.keys(inventory), ...lines.map((l) => l.element_class)]);
    return [...classes]
      .map((cls) => ({
        cls,
        blocks: inventory[cls] || 0,
        kg: kg.get(cls) || 0,
        lines: lines.filter((l) => l.element_class === cls),
      }))
      .filter((g) => g.blocks || g.kg);
  }, [byClass, inventory, lines]);
  // The order is fixed when the building comes apart: a correction that
  // re-ranks two rows would otherwise send their blocks jumping.
  const [order, setOrder] = useState([]);
  useEffect(() => {
    if (broken && !order.length) {
      setOrder([...groups].sort((a, b) => b.kg - a.kg).map((g) => g.cls));
    } else if (!trayUp && order.length) {
      setOrder([]);
      setPicked(null);
    }
  }, [broken, trayUp, groups, order.length]);
  const rows = order.length
    ? order.map((cls) => groups.find((g) => g.cls === cls)).filter(Boolean)
    : [...groups].sort((a, b) => b.kg - a.kg);
  const groupTotal = rows.reduce((t, g) => t + g.kg, 0);
  const landedSet = useMemo(() => new Set(landed), [landed]);
  const landedKg = rows.reduce((t, g) => t + (landedSet.has(g.cls) || !g.blocks ? g.kg : 0), 0);
  const allIn = rows.length > 0 && rows.every((g) => landedSet.has(g.cls) || !g.blocks);
  const shownLanded = useCountUp(trayUp ? (allIn ? groupTotal : landedKg) : 0, 650);
  const blockCount = rows.reduce((t, g) => t + g.blocks, 0);

  // Where each row's slot is, for the blocks to fly to. Read every frame
  // by the scene, so the blocks ride along when the list scrolls.
  const slots = useCallback(() => {
    const cv = canvasRef.current;
    if (!cv) return null;
    const c = cv.getBoundingClientRect();
    const list = listRef.current?.getBoundingClientRect();
    const out = {};
    for (const [cls, el] of slotEls.current) {
      const r = el.getBoundingClientRect();
      out[cls] = {
        x: r.left - c.left,
        y: r.top - c.top,
        w: r.width,
        h: r.height,
        clipTop: list ? list.top - c.top : null,
        clipBottom: list ? list.bottom - c.top : null,
      };
    }
    return out;
  }, []);
  useEffect(() => {
    sceneRef.current?.set({ order, slots });
  }, [order, slots, massing, surfaces]);

  function breakApart() {
    splitRef.current = 1;
    sceneRef.current?.set({ split: 1, splitTween: true });
    setBroken(true);
  }
  function rebuild() {
    setPicked(null);
    splitRef.current = 0;
    sceneRef.current?.set({ split: 0, splitTween: true });
    setBroken(false);
  }

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
    <div className={`sc${intro ? " is-intro" : ""}${heat ? " is-heat" : ""}${broken ? " is-broken" : ""}`}>
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
          // Invisible during the photograph, and must not answer the
          // pointer either: hovering the photo showed the model's read-outs.
          style={intro ? { pointerEvents: "none" } : undefined}
          role="img"
          aria-label={`The measured building in 3D: ${massing.width_m} by ${massing.depth_m} metres, ${heights.length} storeys, ${massing.walls.length} partition walls. Drag to orbit, scroll to zoom.`}
        />
      ) : (
        <div className="sc-nomodel glass">
          <h2>No model for this plan set</h2>
          <p>
            {glError
              ? `This browser could not start 3D (${glError}). The bill of quantities has every figure.`
              : "A model needs a measured footprint and the storey datums from the sections, and this set did not state both. Drawing a guess would be the one thing this view exists not to do."}
          </p>
          <button className="sc-btn" onClick={() => onPage("quantities")}>
            Open the bill of quantities
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
          {exportHref && (
            <a className="glass sc-btn sc-hide-phone" href={exportHref} download>
              Download CSV
            </a>
          )}
          {reportHref && (
            <a className="glass sc-btn sc-hide-narrow" href={reportHref} target="_blank" rel="noreferrer">
              Export report
            </a>
          )}
          {who && (
            <button
              className="glass sc-btn sc-who"
              onClick={onSignOut}
              title={who.guest ? "Leave this guest workspace" : `Signed in as ${who.name}`}
            >
              <i aria-hidden="true">{(who.name || "?")[0].toUpperCase()}</i>
              <span className="sc-who-name">{who.name}</span>
              <span className="sc-who-out">{who.guest ? "Leave" : "Sign out"}</span>
            </button>
          )}
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
      {hover && !intro && !sheetOpen && (
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
          <em>{broken ? "press to put it back on the building" : "press to see where it came from"}</em>
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
                Windows and doors are counted and measured in the bill, but
                the takeoff does not say where each sits, so their positions
                on the walls are illustrative.
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
                        <span className="sc-tag">{line.provenance?.sheet_no || "—"}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
              <button className="sc-link" onClick={() => onPage("quantities")}>
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
              <button className="sc-link" onClick={() => onPage("gaps")}>
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
              <button className="sc-link" onClick={() => onPage("options")}>
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

      {/* ---- the sheet: a page, expanded over the model ---- */}
      {sheetOpen && takeoff && (
        <div className="sc-sheet-wrap" onClick={(e) => e.target === e.currentTarget && onPage("model")}>
          <section className="sc-sheet glass" role="dialog" aria-modal="true" aria-label={SHEETS.find((x) => x.id === page)?.label}>
            <header className="sc-sheet-head">
              <nav className="sc-seg" aria-label="Pages">
                {SHEETS.map((x) => (
                  <button
                    key={x.id}
                    className={page === x.id ? "is-on" : ""}
                    aria-current={page === x.id ? "page" : undefined}
                    onClick={() => onPage(x.id)}
                  >
                    {x.label}
                    {x.id === "quantities" && <em>{lines.length}</em>}
                    {x.id === "gaps" && <em>{takeoff?.gaps?.length ?? 0}</em>}
                    {x.id === "options" && <em>{(swaps?.length || 0) + (decisions?.length || 0)}</em>}
                  </button>
                ))}
              </nav>
              <button className="sc-btn sc-sheet-close" onClick={() => onPage("model")}>
                <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path d="M15 6l-6 6 6 6" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
                Back to the model
              </button>
            </header>
            <div className="sc-sheet-body page" key={page}>
              <DetailPage
                page={page}
                takeoff={takeoff}
                carbon={carbon}
                swaps={swaps}
                decisions={decisions}
                scenario={scenario}
                onScenario={onScenario}
                onOverride={onOverride}
                onTrace={onTrace}
                coverage={coverage}
              />
              <AppFooter />
            </div>
          </section>
        </div>
      )}

      {/* ---- the parts list: the building, in pieces ---- */}
      {trayUp && massing && !glError && (
        <aside className={`bd${broken ? "" : " is-leaving"}`} aria-label="Every part and its carbon">
          <header className="glass bd-top">
            <div className="sc-eyebrow">Every part · A1–A3</div>
            <div className="bd-total" aria-live="polite">
              <b>{int(shownLanded)}</b>
              <span>
                {allIn ? "kgCO₂e, the whole building" : `of ${int(groupTotal)} kgCO₂e landed`}
              </span>
            </div>
            <div className="bd-progress" aria-hidden="true">
              <s style={{ width: `${groupTotal ? (Math.min(shownLanded, groupTotal) / groupTotal) * 100 : 0}%` }} />
            </div>
            <p>
              {blockCount} blocks in {rows.length} kinds, heaviest first. Press a
              row to put its blocks back on the building and see the working.
            </p>
          </header>
          <ul className="bd-list" ref={listRef}>
            {(() => {
              let run = 0;
              return rows.map((g) => {
                run += g.kg;
                const on = picked === g.cls;
                const isIn = landedSet.has(g.cls) || !g.blocks;
                const share = groupTotal ? (g.kg / groupTotal) * 100 : 0;
                const illustrative = g.cls === "window" || g.cls === "door";
                return (
                  <li
                    key={g.cls}
                    className={`bd-row${on ? " is-on" : ""}${isIn ? " is-in" : ""}`}
                  >
                    <button
                      className="bd-head"
                      onClick={() => setPicked(on ? null : g.cls)}
                      onMouseEnter={() => setFocus(g.cls)}
                      onMouseLeave={() => setFocus(null)}
                      aria-expanded={on}
                    >
                      <span
                        className="bd-slot"
                        style={{ height: slotHeight(g.blocks) }}
                        aria-hidden="true"
                        ref={(el) => {
                          if (el && g.blocks) slotEls.current.set(g.cls, el);
                          else slotEls.current.delete(g.cls);
                        }}
                      >
                        {!g.blocks && <i>not drawn</i>}
                      </span>
                      <span className="glass bd-info">
                        <span className="bd-name">
                          {CLASS_LABEL[g.cls] || titleCase(g.cls)}
                          <em>
                            {g.blocks ? `${g.blocks} ${g.blocks === 1 ? "block" : "blocks"}` : "in the bill"}
                            {illustrative && " · placed for illustration"}
                          </em>
                        </span>
                        <span className="bd-kg">
                          <b>{int(g.kg)}</b>
                          <em>kg</em>
                        </span>
                        <span className="bd-bar" aria-hidden="true">
                          <s style={{ width: `${(g.kg / (rows[0]?.kg || 1)) * 100}%` }} />
                        </span>
                        <span className="bd-run">
                          {dec(share, 1)}% · running total <b>{isIn ? int(run) : "…"}</b>
                        </span>
                      </span>
                    </button>
                    {on && (
                      <ul className="glass bd-lines">
                        {g.lines.map((line) => (
                          <PartLine
                            key={line.id}
                            line={line}
                            carbonLine={carbonById.get(line.id)}
                            onOverride={onOverride}
                            onTrace={onTrace}
                          />
                        ))}
                        {!g.lines.length && <li className="bd-none">No line in the bill for this part.</li>}
                      </ul>
                    )}
                  </li>
                );
              });
            })()}
          </ul>
          <button className="glass sc-btn bd-rebuild" onClick={rebuild}>
            Put it back together
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
          {massing.roof_rise_m > 0 && (
            <div className="sc-seg" role="group" aria-label="Roof">
              <button
                className={roofOn ? "is-on" : ""}
                onClick={() => setRoofOn((r) => !r)}
                aria-pressed={roofOn}
                title={`Ridge ${massing.roof_rise_m.toFixed(2)} m above the top storey, from the section. The gable shape is illustrative.`}
              >
                Roof
              </button>
            </div>
          )}
          <label className="sc-explode" title="Open the storeys, then keep going to take it to pieces">
            <span>Explode</span>
            <input
              ref={sliderRef}
              type="range"
              min="0"
              max="1"
              step="0.005"
              defaultValue={0}
              onChange={(e) => {
                const v = Number(e.target.value);
                splitRef.current = v;
                sceneRef.current?.set({ split: v, splitTween: false });
                const apartNow = v > SPLIT_STOREYS + 0.001;
                if (apartNow !== brokenRef.current) setBroken(apartNow);
              }}
            />
          </label>
          <button
            className={`sc-break${broken ? " is-on" : ""}`}
            onClick={broken ? rebuild : breakApart}
            aria-pressed={broken}
          >
            <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
              {broken ? (
                <path d="M4 20h16M6 20v-7l6-5 6 5v7" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
              ) : (
                <path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM15 15l5 5M20 15l-5 5" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
              )}
            </svg>
            <span>{broken ? "Rebuild" : "Break it apart"}</span>
          </button>
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

// A slot tall enough for its blocks to read as blocks: one row of big ones
// for a slab, a little brick wall for seventy partitions.
function slotHeight(n) {
  if (!n) return 30;
  if (n <= 4) return 44;
  if (n <= 12) return 52;
  return Math.min(150, 12 * Math.ceil(n / 8) + 8);
}

// One line of the bill, worked: what was read, times its factor, is its
// carbon. The quantity can be corrected in place.
function PartLine({ line, carbonLine, onOverride, onTrace }) {
  const [draft, setDraft] = useState(null);
  const edited = line.user_override != null;
  const qty = edited ? line.user_override : line.quantity;
  const unit = UNIT_LABEL[line.unit] || line.unit;
  const f = carbonLine?.factor;
  const converted = carbonLine?.conversion_note && !/directly matches/i.test(carbonLine.conversion_note);
  // When the factor is declared in another unit, the multiplication is shown
  // in that unit, so the arithmetic on screen is arithmetic that holds.
  const inFactorUnit = f && f.gwp_value ? (carbonLine.kg_co2e || 0) / f.gwp_value : null;

  async function commit() {
    const value = parseFloat(draft);
    setDraft(null);
    if (!Number.isFinite(value) || value < 0) return;
    // Typing back the figure we read is an undo.
    if (value === line.quantity) {
      if (edited) await onOverride(line.id, null);
      return;
    }
    if (value === line.user_override) return;
    await onOverride(line.id, value);
  }

  return (
    <li className="bd-line">
      <div className="bd-line-head">
        <span>{line.description}</span>
        <Confidence value={line.confidence} />
      </div>
      <div className="bd-math">
        <label className="bd-qty">
          <span className="sr">Quantity for {line.description}</span>
          <input
            inputMode="decimal"
            value={draft ?? dec(qty, line.unit === "each" ? 0 : 2)}
            onFocus={(e) => {
              setDraft(String(qty));
              requestAnimationFrame(() => e.target.select());
            }}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.currentTarget.blur();
              if (e.key === "Escape") {
                setDraft(null);
                requestAnimationFrame(() => e.target.blur());
              }
            }}
          />
          <em>{unit}</em>
        </label>
        {f ? (
          <>
            {converted && inFactorUnit != null && (
              <span className="bd-conv" title={carbonLine.conversion_note}>
                → {dec(inFactorUnit, inFactorUnit < 10 ? 2 : 1)}
                <em>{UNIT_LABEL[f.declared_unit] || f.declared_unit}</em>
              </span>
            )}
            <span className="bd-op">×</span>
            <span className="bd-factor">
              {dec(f.gwp_value, f.gwp_value < 10 ? 2 : 0)}
              <em>kg/{UNIT_LABEL[f.declared_unit] || f.declared_unit}</em>
            </span>
            <span className="bd-op">=</span>
            <b className="bd-result">{int(carbonLine.kg_co2e)}</b>
          </>
        ) : (
          <span className="bd-nofactor">
            {carbonLine?.missing_reason || "no factor found, so not in the total"}
          </span>
        )}
      </div>
      <div className="bd-line-foot">
        {f && <span className="bd-src">{f.name}</span>}
        {converted && <span className="bd-src">{carbonLine.conversion_note}</span>}
        {edited && (
          <span className="bd-was">
            we read {dec(line.quantity, 2)} ·{" "}
            <button className="sc-link" onClick={() => onOverride(line.id, null)}>
              undo
            </button>
          </span>
        )}
        <button className="sc-tag bd-sheet" onClick={() => onTrace(line.id, line.provenance)} title="Open the sheet this came from">
          {line.provenance?.sheet_no || "sheet"}
        </button>
      </div>
    </li>
  );
}
