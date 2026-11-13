// The measured building in WebGL, for the showcase view.
//
// Every solid here is a quantity the pipeline read: the footprint from the
// linework, the storey datums from the sections, each partition where it was
// counted, the grade beam at the stated section. Nothing is modelled by hand.
//
// The one exception is said out loud wherever it shows: windows and doors.
// The takeoff counts them and measures their area, but does not record where
// each sits, so they are spread along the walls for illustration and every
// read-out of one says its position is illustrative. The roof's pitch is not
// drawn at all; there is no profile to draw.
//
// "Break it apart" takes the building to pieces: it spreads like an exploded
// drawing, then every block glides to a slot in the parts list beside the
// model, so the list is made of the building rather than describing it.
//
// Kept free of React so the render loop and React's renders never contend:
// the component hands it state through the returned handle.

import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

const SLAB_T = 0.13; // AB_Fourplex_01's stated slab; a visual thickness elsewhere
const FLOOR_T = 0.3;
const EXT_T = 0.235;
const BEAM_W = 0.2;
const BEAM_D = 1.2;
// Faces that would otherwise share a plane -- a wall's foot on the slab, a
// floor's edge on the wall -- are held this far apart. Coplanar faces
// z-fight: they flicker between their two colours as the camera moves, which
// the heat map made obvious.
const GAP = 0.012;

const STRUCTURE = {
  slab_on_grade: "#c9d1dc",
  footing: "#8d99ab",
  exterior_wall: "#e9f0fa",
  floor_assembly: "#dbe4f0",
  roof_assembly: "#dbe4f0",
  interior_partition: "#f4f7fb",
  // Glass and a quiet leaf: part of the same pale building, not stickers on it.
  window: "#cfe3ff",
  door: "#d9e2ee",
};

// The share of the slider that opens the storeys; the rest takes the
// building to pieces.
export const SPLIT_STOREYS = 0.3;
// Of the break-apart: the building first spreads evenly about its centre, an
// architect's exploded drawing, with nothing turned or thrown...
const SPREAD = 0.3;
const SPREAD_BY = 0.42;
// ...then each kind of part glides to its row in turn, the windows of one
// overlapping the next so the motion never stops and starts.
const FLY_WINDOW = 0.5;
const FLY_STAGGER = 0.42;
const TILT = new THREE.Quaternion().setFromEuler(new THREE.Euler(-0.42, 0.55, 0, "YXZ"));

// Deterministic, so the same building always comes apart the same way.
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const easeInOut = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
const easeSine = (x) => -(Math.cos(Math.PI * x) - 1) / 2;

// "rgb(12 34 56)" from the shared ramp, into a THREE.Color.
function cssRgb(str) {
  const m = String(str).match(/(\d+)\D+(\d+)\D+(\d+)/);
  if (!m) return new THREE.Color(str);
  return new THREE.Color(+m[1] / 255, +m[2] / 255, +m[3] / 255);
}

export function createScene(canvas, massing, { heatColour, intensity, hotI, coolI, still, openings }) {
  const W = massing.width_m;
  const D = massing.depth_m;
  const heights = massing.storey_heights_m;
  const datums = [0];
  for (const h of heights) datums.push(datums[datums.length - 1] + h);
  const H = datums[datums.length - 1];

  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: true,
    powerPreference: "high-performance",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x0b1422, 60, 140);

  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 500);
  // Framed by the larger of plan and height; height weighs more, because a
  // three-storey block framed by its plan alone runs into the headline.
  // A square plan's diagonal is much longer than either side, and an
  // uploaded rowhouse framed by its side alone ran off the screen.
  const span = Math.max(W, D, Math.hypot(W, D) * 0.95, H * 2.7);
  const HOME = [span * 1.25, span * 0.85, span * 1.4];
  camera.position.set(...HOME);

  const controls = new OrbitControls(camera, canvas);
  controls.target.set(0, H * 0.42, 0);
  controls.enableDamping = true;
  controls.dampingFactor = 0.07;
  // The full sphere: over the roof, round every side, and under the slab to
  // see the grade beam. The ground is see-through for exactly that reason.
  controls.minPolarAngle = 0.02;
  controls.maxPolarAngle = Math.PI - 0.02;
  controls.minDistance = span * 0.35;
  controls.maxDistance = span * 3.2;
  controls.autoRotate = !still;
  controls.autoRotateSpeed = 0.55;
  controls.addEventListener("start", () => {
    controls.autoRotate = false;
  });

  // Winter light, from the rendering on the cover: low warm sun, cold sky.
  scene.add(new THREE.HemisphereLight(0xdbe8ff, 0x1c2638, 1.15));
  const sun = new THREE.DirectionalLight(0xffe4c4, 2.1);
  sun.position.set(-span * 0.9, span * 1.3, span * 0.6);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  const sc = sun.shadow.camera;
  sc.left = -span;
  sc.right = span;
  sc.top = span;
  sc.bottom = -span;
  sc.near = 1;
  sc.far = span * 5;
  sun.shadow.bias = -0.0004;
  scene.add(sun);
  const rim = new THREE.DirectionalLight(0x9cc1ff, 0.6);
  rim.position.set(span, span * 0.4, -span);
  scene.add(rim);

  // Ground: a shadow catcher and a one-metre grid, both transparent, so the
  // photograph shows through and the footings show from underneath.
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(span * 6, span * 6),
    new THREE.ShadowMaterial({ opacity: 0.32 }),
  );
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -SLAB_T - 0.001;
  ground.receiveShadow = true;
  scene.add(ground);
  const grid = new THREE.GridHelper(span * 3, Math.round(span * 3), 0x9fb6d6, 0x9fb6d6);
  grid.material.transparent = true;
  grid.material.opacity = 0.09;
  grid.material.depthWrite = false;
  grid.position.y = -SLAB_T - 0.004;
  scene.add(grid);

  const root = new THREE.Group();
  root.position.set(-W / 2, 0, -D / 2);
  scene.add(root);

  // Every pickable solid is registered with its class and storey, so hover,
  // highlight, storey filter and explode all work from one list.
  const parts = [];
  const edgeMat = new THREE.LineBasicMaterial({
    color: 0xffffff,
    transparent: true,
    opacity: 0.38,
  });

  // What stays behind when the blocks leave: the building as a drawing.
  const ghostMat = new THREE.LineBasicMaterial({ color: 0xcfe0f5, transparent: true, opacity: 0, depthWrite: false });
  const random = rng(Math.round(W * 1000 + D * 37 + H * 11));
  const centre = new THREE.Vector3(W / 2, H * 0.4, D / 2);
  const classCount = {};

  function solid({ cls, storey = null, x, y, z, w, h, d, opacity = 1, label, detail, order = 0, edge = 0.38 }) {
    const geo = new THREE.BoxGeometry(w, h, d);
    const mat = new THREE.MeshStandardMaterial({
      color: STRUCTURE[cls] || "#e2e8f0",
      roughness: 0.82,
      metalness: 0.02,
      transparent: opacity < 1,
      opacity,
      depthWrite: opacity >= 1,
    });
    const mesh = new THREE.Mesh(geo, mat);
    // Translucent layers draw in a fixed order (floors, then the envelope)
    // rather than re-sorting by distance every frame, which made them swap
    // places -- and colours -- as the building turned.
    mesh.renderOrder = order;
    mesh.position.set(x + w / 2, y + h / 2, z + d / 2);
    mesh.castShadow = opacity >= 0.5;
    mesh.receiveShadow = true;
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo), edgeMat.clone());
    mesh.add(edges);
    const ghost = new THREE.LineSegments(edges.geometry, ghostMat);
    ghost.position.copy(mesh.position);
    ghost.visible = false;
    root.add(ghost);
    const part = { mesh, edges, ghost, cls, storey, baseOpacity: opacity, edgeOp: edge, label, detail, y0: y + h / 2, h };
    // ---- what the break-apart needs: where it lives, and how it lies once
    // it is a tile in the list.
    part.home = mesh.position.clone();
    part.index = classCount[cls] = (classCount[cls] ?? -1) + 1;
    part.jitter = random();
    // Lay the block flat to the screen: longest side across, next side up,
    // thinnest side towards the viewer.
    const dims = [w, h, d];
    const ix = [0, 1, 2].sort((a, b) => dims[b] - dims[a]);
    part.long = dims[ix[0]];
    part.next = Math.max(dims[ix[1]], 0.02);
    const cols = [null, null, null];
    cols[ix[0]] = new THREE.Vector3(1, 0, 0);
    cols[ix[1]] = new THREE.Vector3(0, 1, 0);
    cols[ix[2]] = new THREE.Vector3(0, 0, 1);
    const m = new THREE.Matrix4().makeBasis(cols[0], cols[1], cols[2]);
    if (m.determinant() < 0) {
      cols[ix[2]].negate();
      m.makeBasis(cols[0], cols[1], cols[2]);
    }
    part.flat = new THREE.Quaternion().setFromRotationMatrix(m);
    part.fly = 0;
    part.back = 0;
    part.op = opacity;
    mesh.userData.part = part;
    parts.push(part);
    root.add(mesh);
    return part;
  }

  // Slab, measured.
  solid({
    cls: "slab_on_grade", x: 0, y: -SLAB_T, z: 0, w: W, h: SLAB_T, d: D,
    label: "Slab on grade", detail: `${W.toFixed(1)} × ${D.toFixed(1)} m footprint`,
  });

  // Grade beam round the perimeter, below grade.
  const beamY = -SLAB_T - BEAM_D - GAP;
  const beam = { cls: "footing", y: beamY, h: BEAM_D, opacity: 0.9, label: "Footings", detail: "grade beam on the perimeter, below grade" };
  const g = GAP;
  solid({ ...beam, x: g, z: g, w: W - 2 * g, d: BEAM_W });
  solid({ ...beam, x: g, z: D - BEAM_W - g, w: W - 2 * g, d: BEAM_W });
  solid({ ...beam, x: g, z: BEAM_W + 2 * g, w: BEAM_W, d: D - 2 * BEAM_W - 4 * g });
  solid({ ...beam, x: W - BEAM_W - g, z: BEAM_W + 2 * g, w: BEAM_W, d: D - 2 * BEAM_W - 4 * g });

  // The envelope, one shell per storey so the storeys can be pulled apart.
  heights.forEach((h, s) => {
    const y = datums[s] + GAP;
    const shell = {
      cls: "exterior_wall", storey: s, y, h: h - 2 * GAP, opacity: 0.2, order: 2,
      label: "Exterior wall", detail: `storey ${s + 1}, ${h.toFixed(1)} m datum to datum`,
    };
    solid({ ...shell, x: 0, z: 0, w: W, d: EXT_T });
    solid({ ...shell, x: 0, z: D - EXT_T, w: W, d: EXT_T });
    solid({ ...shell, x: 0, z: EXT_T, w: EXT_T, d: D - 2 * EXT_T });
    solid({ ...shell, x: W - EXT_T, z: EXT_T, w: EXT_T, d: D - 2 * EXT_T });
  });

  // Floors between storeys, and the roof assembly on top.
  datums.slice(1).forEach((d, i) => {
    const isRoof = i === datums.length - 2;
    solid({
      cls: isRoof ? "roof_assembly" : "floor_assembly",
      storey: i,
      x: EXT_T + GAP, y: d - FLOOR_T + GAP, z: EXT_T + GAP,
      w: W - 2 * (EXT_T + GAP), h: FLOOR_T - 2 * GAP, d: D - 2 * (EXT_T + GAP),
      opacity: isRoof ? 0.16 : 0.22,
      order: 1,
      label: isRoof ? "Roof" : "Floor assembly",
      detail: isRoof ? "flat here: the profile is not in the takeoff" : `between storeys ${i + 1} and ${i + 2}`,
    });
  });

  // Partitions, each where it was counted.
  for (const w of massing.walls) {
    const base = datums[w.storey] ?? 0;
    const top = (datums[w.storey + 1] ?? base + 3) - FLOOR_T;
    const len = Math.max(w.w, w.d);
    solid({
      cls: "interior_partition", storey: w.storey,
      x: w.x, y: base + GAP, z: w.y, w: Math.max(w.w, 0.09),
      h: Math.max(0.5, top - base - 2 * GAP), d: Math.max(w.d, 0.09),
      label: "Interior partition",
      detail: `storey ${w.storey + 1}, ${len.toFixed(2)} m long`,
    });
  }

  // ---- windows and doors: counted, not located ----------------------------
  // The bill has how many and how much area, not where. They are spread
  // evenly so the building reads as a building, and each says so.
  const winN = Math.min(160, Math.max(0, Math.round(openings?.windows?.count || 0)));
  const winArea = openings?.windows?.area || 0;
  const doorN = Math.min(160, Math.max(0, Math.round(openings?.doors?.count || 0)));
  const perimeter = 2 * (W + D);
  // A point `t` metres round the outside, anticlockwise from the origin.
  function round(t) {
    t = ((t % perimeter) + perimeter) % perimeter;
    if (t < W) return { along: "x", x: t, z: 0 };
    if (t < W + D) return { along: "z", x: W, z: t - W };
    if (t < 2 * W + D) return { along: "x", x: 2 * W + D - t, z: D };
    return { along: "z", x: 0, z: perimeter - t };
  }
  const extDoorSlots = [];
  if (winN > 0 && heights.length) {
    const a = winArea > 0 ? winArea / winN : 1.2;
    const wh = Math.min(1.8, Math.max(0.6, Math.sqrt(a) * 1.1));
    const ww = Math.max(0.35, a / wh);
    let placed = 0;
    heights.forEach((sh, s) => {
      const n = Math.round(((s + 1) * winN) / heights.length) - placed;
      placed += n;
      const step = perimeter / Math.max(1, n);
      const sill = datums[s] + Math.min(0.9, Math.max(0.3, sh - wh - 0.35));
      for (let k = 0; k < n; k++) {
        const t = (k + 0.5) * step;
        const at = round(t);
        // Clear of the corners.
        const pos = at.along === "x" ? at.x : at.z;
        const run = at.along === "x" ? W : D;
        const c = Math.min(Math.max(pos, ww / 2 + 0.4), run - ww / 2 - 0.4);
        // Set into the wall, not stuck on it: a pane inside the wall's own
        // thickness, so the envelope stays one clean glass box.
        const T = EXT_T - 0.05;
        solid({
          cls: "window", storey: s,
          x: at.along === "x" ? c - ww / 2 : at.x === 0 ? 0.025 : W - EXT_T + 0.025,
          y: sill,
          z: at.along === "z" ? c - ww / 2 : at.z === 0 ? 0.025 : D - EXT_T + 0.025,
          w: at.along === "x" ? ww : T, h: wh, d: at.along === "z" ? ww : T,
          opacity: 0.4, order: 3, edge: 0.22,
          label: "Window · position illustrative",
          detail: `one of ${winN}; the bill measures ${winArea.toFixed(1)} m² in all, but not where each sits`,
        });
        if (s === 0) extDoorSlots.push(t + step / 2);
      }
    });
  }
  if (doorN > 0) {
    // Most of a plan set's doors are interior: they go in the partitions
    // long enough to take one; any left over go on the ground-floor walls,
    // between the windows.
    const hosts = massing.walls.filter((w) => Math.max(w.w, w.d) >= 1.1);
    const inPartitions = Math.min(doorN, hosts.length);
    const DW = 0.86;
    for (let k = 0; k < inPartitions; k++) {
      const w = hosts[Math.floor(((k + 0.5) * hosts.length) / inPartitions)];
      const base = datums[w.storey] ?? 0;
      const top = (datums[w.storey + 1] ?? base + 3) - FLOOR_T;
      const dh = Math.min(2.03, top - base - 0.12);
      const alongX = w.w >= w.d;
      // A hair proud of the wall each side, so it never z-fights the face.
      const thick = Math.max(alongX ? w.d : w.w, 0.09) + 0.012;
      solid({
        cls: "door", storey: w.storey,
        x: alongX ? w.x + w.w / 2 - DW / 2 : w.x - 0.006,
        y: base + GAP * 2,
        z: alongX ? w.y - 0.006 : w.y + w.d / 2 - DW / 2,
        w: alongX ? DW : thick, h: dh, d: alongX ? thick : DW,
        edge: 0.16,
        label: "Door · position illustrative",
        detail: `one of ${doorN} in the bill; it counts them, it does not place them`,
      });
    }
    const left = doorN - inPartitions;
    const slots = extDoorSlots.length ? extDoorSlots : [W / 2, W + D / 2, 2 * W + D * 1.5];
    for (let k = 0; k < left; k++) {
      const at = round(slots[k % slots.length] + Math.floor(k / slots.length) * 1.1);
      const T = EXT_T - 0.05;
      solid({
        cls: "door", storey: 0,
        x: at.along === "x" ? at.x - DW / 2 : at.x === 0 ? 0.025 : W - EXT_T + 0.025,
        y: GAP * 2,
        z: at.along === "z" ? at.z - DW / 2 : at.z === 0 ? 0.025 : D - EXT_T + 0.025,
        w: at.along === "x" ? DW : T, h: Math.min(2.03, (heights[0] || 3) - FLOOR_T - 0.1), d: at.along === "z" ? DW : T,
        opacity: 0.55, order: 3, edge: 0.16,
        label: "Door · position illustrative",
        detail: `one of ${doorN} in the bill; it counts them, it does not place them`,
      });
    }
  }

  // ---- state the component drives --------------------------------------

  // `build` holds the build-up until the view says go, so it starts as the
  // photograph steps back rather than on a clock of its own.
  const state = {
    heat: false, storey: null, focus: null, hover: null, insetRight: 0, build: still,
    // 0 → SPLIT_STOREYS opens the storeys; on to 1 takes it to pieces.
    split: 0, splitTween: false,
    // The class pressed in the parts list: its blocks fly back home.
    selected: null,
    // The parts list, in its order, and where each row's slot is on screen.
    order: [], slots: null,
  };
  let splitShown = 0;
  let tween = null; // { from, to, start, dur } for a button-driven split
  let lastNow = null;
  let onSplit = () => {};
  let onLanded = () => {};
  let landedKey = "";
  let assemble = still ? 1 : 0; // 0 → 1, the opening build-up
  // Driven by the clock, not by frames: a slow machine (a projector laptop,
  // software WebGL) renders fewer frames, and a frame-counted build-up would
  // stall half-built on exactly the screen where it matters.
  let assembleStart = null;
  const ASSEMBLE_DELAY = still ? 0 : 0.35;
  const ASSEMBLE_TIME = 2.4;
  let liftApplied = 0;

  function colourFor(cls) {
    if (state.heat && intensity[cls] != null) return cssRgb(heatColour(intensity[cls], hotI, coolI));
    if (state.heat) return new THREE.Color("#5b6b82");
    return new THREE.Color(STRUCTURE[cls] || "#e2e8f0");
  }

  function restyle() {
    for (const p of parts) {
      const m = p.mesh.material;
      m.color.copy(colourFor(p.cls));
      const lit = state.focus == null || state.focus === p.cls;
      const hovered = state.hover === p;
      let op = p.baseOpacity;
      if (state.heat && p.cls !== "interior_partition" && p.cls !== "footing" && p.cls !== "slab_on_grade") {
        op = Math.max(op, 0.42);
      }
      if (!lit) op = Math.min(op, 0.07);
      // The frame loop owns the final opacity: a block in the parts list is
      // drawn solid whatever it was in the building.
      p.op = op;
      p.lit = lit;
      m.emissive.set(hovered ? "#d9a46a" : "#000000");
      m.emissiveIntensity = hovered ? 0.55 : 0;
      p.edges.material.opacity = lit ? (hovered ? 0.95 : p.edgeOp) : 0.04;
      p.edges.material.color.set(hovered ? "#ffd8a8" : state.heat ? "#1b2433" : "#ffffff");
    }
  }

  const clamp01 = (x) => Math.min(1, Math.max(0, x));
  const vHome = new THREE.Vector3();
  const vBurst = new THREE.Vector3();
  const vT = new THREE.Vector3();
  const vCtrl = new THREE.Vector3();
  const vRay = new THREE.Vector3();
  const vFwd = new THREE.Vector3();
  const qNow = new THREE.Quaternion();
  const qT = new THREE.Quaternion();
  const qId = new THREE.Quaternion();

  // Where each class's blocks lie in its slot this frame, in root space.
  function slotTargets() {
    const rects = state.slots ? state.slots() : null;
    if (!rects) return null;
    const cw = canvas.clientWidth;
    const ch = canvas.clientHeight;
    if (!cw || !ch) return null;
    camera.updateMatrixWorld();
    camera.getWorldDirection(vFwd);
    const depth = Math.max(camera.near * 4, camera.position.distanceTo(controls.target) * 0.5);
    const wpp = (2 * depth * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2)) / ch;
    const out = {};
    for (const [cls, r] of Object.entries(rects)) {
      const n = classCount[cls] + 1;
      if (!n || !r) continue;
      const cols = Math.max(1, Math.min(n, Math.round(Math.sqrt((n * r.w) / Math.max(1, r.h)))));
      const rows = Math.ceil(n / cols);
      out[cls] = { r, cols, cellW: r.w / cols, cellH: r.h / rows, depth, wpp };
    }
    return out;
  }
  function target(p, t, into) {
    const c = p.index % t.cols;
    const row = Math.floor(p.index / t.cols);
    const px = t.r.x + (c + 0.5) * t.cellW;
    const py = t.r.y + (row + 0.5) * t.cellH;
    const cw = canvas.clientWidth;
    const ch = canvas.clientHeight;
    vRay.set((px / cw) * 2 - 1, -(py / ch) * 2 + 1, 0.5).unproject(camera).sub(camera.position).normalize();
    into.copy(camera.position).addScaledVector(vRay, t.depth / Math.max(0.2, vRay.dot(vFwd))).sub(root.position);
    const s = Math.min((t.cellW * 0.7 * t.wpp) / p.long, (t.cellH * 0.66 * t.wpp) / p.next);
    // A row scrolled out of the list takes its blocks with it.
    const hidden = t.r.clipTop != null && (py < t.r.clipTop || py > t.r.clipBottom);
    return { s, hidden };
  }

  function layout(dt) {
    const liftK = clamp01(splitShown / SPLIT_STOREYS);
    const bd = clamp01((splitShown - SPLIT_STOREYS) / (1 - SPLIT_STOREYS));
    // Explode lifts each storey by a share of its own height, so the floor
    // plans open like drawers and every partition can be read from above.
    const lift = (s) => (s == null ? 0 : s * liftK * 3.2);
    const k = THREE.MathUtils.smoothstep(assemble, 0, 1);
    const spread = easeSine(clamp01(bd / SPREAD));
    const flyU = clamp01((bd - SPREAD) / (1 - SPREAD));
    const targets = bd > 0 ? slotTargets() : null;
    const camQ = camera.quaternion;
    const nRows = Math.max(1, state.order.length - 1);
    const minFly = {};
    ghostMat.opacity = 0.16 * easeSine(flyU);
    for (const p of parts) {
      // The build-up: below grade first, then each storey in turn.
      const order = p.storey == null ? 0 : p.storey + 1;
      const local = clamp01(k * (heights.length + 1.4) - order);
      const e = 1 - Math.pow(1 - local, 3);
      vHome.set(p.home.x, p.y0 - (p.h / 2) * (1 - e) + lift(p.storey), p.home.z);
      let scale = 1;
      let hidden = false;
      qNow.identity();
      p.fly = 0;
      if (bd > 0) {
        // The building spreads about its centre, every block keeping its
        // place relative to the rest...
        vBurst.copy(vHome).sub(centre).multiplyScalar(1 + SPREAD_BY * spread).add(centre);
        // ...then each kind glides to its row, in list order, so the
        // running total climbs as each one lands.
        const rank = state.order.indexOf(p.cls);
        const delay = (rank < 0 ? 1 : rank / nRows) * FLY_STAGGER + p.jitter * 0.08;
        const t = targets?.[p.cls];
        p.fly = t ? easeInOut(clamp01((flyU - delay) / FLY_WINDOW)) : 0;
        if (p.fly > 0) {
          const got = target(p, t, vT);
          // An arc rather than a straight line: up and over.
          vCtrl.copy(vBurst).lerp(vT, 0.5);
          vCtrl.y += span * 0.05;
          const f = p.fly;
          vBurst.multiplyScalar((1 - f) * (1 - f)).addScaledVector(vCtrl, 2 * f * (1 - f)).addScaledVector(vT, f * f);
          qT.copy(camQ).multiply(TILT).multiply(p.flat);
          qNow.slerp(qT, f);
          scale = 1 + (got.s - 1) * f;
          hidden = got.hidden && f > 0.5;
        }
        minFly[p.cls] = Math.min(minFly[p.cls] ?? 1, p.fly);
      } else {
        vBurst.copy(vHome);
      }
      // A class pressed in the list goes home, and glows there.
      const want = state.selected === p.cls && bd > 0 ? 1 : 0;
      p.back += (want - p.back) * Math.min(1, dt * 4.5);
      if (Math.abs(want - p.back) < 0.001) p.back = want;
      const b = easeInOut(p.back);
      if (b > 0) {
        vBurst.lerp(vHome, b);
        qNow.slerp(qId, b);
        scale += (1 - scale) * b;
      }
      p.ghost.visible = bd > 0;
      if (bd > 0) {
        p.ghost.position.copy(vHome);
        p.ghost.scale.y = Math.max(0.001, e);
      }
      p.mesh.position.copy(vBurst);
      p.mesh.quaternion.copy(qNow);
      p.mesh.scale.set(scale, scale * Math.max(0.001, e), scale);
      p.mesh.material.visible = e > 0.002;
      // The ground floor waits as its plan, drawn flat on the slab, then
      // rises: the drawing becoming the building. Anything above it stays
      // hidden until it starts to rise, rather than floating as an outline.
      p.edges.visible = e > 0.002 || order <= 1;
      const storeyOk = state.storey == null || p.storey == null || p.storey === state.storey;
      p.mesh.visible = (storeyOk || bd > 0) && !hidden;
      p.mesh.castShadow = bd < 0.02 && p.baseOpacity >= 0.5;
      // In pieces, every block is drawn solid enough to read as a block.
      const inList = p.fly * (1 - b);
      // Glass in the building, glass while it spreads; a little more body
      // once it is a tile, so a thin wall still reads in its slot.
      let op = p.op;
      op += ((p.lit ? 0.85 : 0.3) - op) * inList;
      if (b > 0 && state.selected === p.cls) op = Math.max(op, p.baseOpacity, 0.5 * b);
      const m = p.mesh.material;
      m.opacity = op;
      m.transparent = op < 0.999;
      m.depthWrite = op >= 0.999;
      if (state.hover !== p) {
        const glow = state.selected === p.cls ? b : 0;
        if (glow > 0) m.emissive.setHex(0xd9a46a);
        m.emissiveIntensity = 0.4 * glow;
      }
    }
    if (bd > 0) {
      const landed = Object.keys(minFly).filter((c) => minFly[c] >= 0.999).sort();
      const key = landed.join(",");
      if (key !== landedKey) {
        landedKey = key;
        onLanded(landed);
      }
    } else if (landedKey) {
      landedKey = "";
      onLanded([]);
    }
  }

  // ---- picking -----------------------------------------------------------

  const ray = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  let onHover = () => {};
  let onPick = () => {};
  let downAt = null;

  function pick(ev) {
    const r = canvas.getBoundingClientRect();
    ndc.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hits = ray.intersectObjects(parts.filter((p) => p.mesh.visible).map((p) => p.mesh), false);
    // Prefer a solid wall over the translucent shell in front of it, so the
    // envelope never blocks the partitions it was made see-through to show.
    const hit =
      hits.find((h) => h.object.userData.part.baseOpacity >= 1) || hits[0];
    return hit ? hit.object.userData.part : null;
  }
  function onMove(ev) {
    const p = pick(ev);
    if (p !== state.hover) {
      state.hover = p;
      restyle();
    }
    onHover(p ? { cls: p.cls, label: p.label, detail: p.detail, x: ev.clientX, y: ev.clientY } : null);
  }
  function onLeave() {
    state.hover = null;
    restyle();
    onHover(null);
  }
  function onDown(ev) {
    downAt = [ev.clientX, ev.clientY];
  }
  function onUp(ev) {
    // A click, not the end of an orbit drag.
    if (!downAt || Math.hypot(ev.clientX - downAt[0], ev.clientY - downAt[1]) > 5) return;
    const p = pick(ev);
    if (p) onPick(p.cls);
  }
  canvas.addEventListener("pointermove", onMove);
  canvas.addEventListener("pointerleave", onLeave);
  canvas.addEventListener("pointerdown", onDown);
  canvas.addEventListener("pointerup", onUp);

  // ---- loop --------------------------------------------------------------

  function resize() {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    // Keep the whole building in frame on a tall phone screen.
    camera.fov = camera.aspect < 0.8 ? 50 : 32;
    // With the deck open the free area is left of it, so the building is
    // centred there rather than behind the glass; with the parts list open
    // (a negative inset), right of it.
    shiftTo = Math.max(-w * 0.4, Math.min(state.insetRight, w * 0.4)) / 2;
    if (!shiftReady || still) shiftNow = shiftTo;
    shiftReady = true;
    applyShift();
  }
  // The frame slides between centres rather than jumping when the deck or
  // the parts list opens.
  let shiftNow = 0;
  let shiftTo = 0;
  let shiftReady = false;
  function applyShift() {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (!w || !h) return;
    if (Math.abs(shiftNow) > 0.25) camera.setViewOffset(w, h, shiftNow, 0, w, h);
    else camera.clearViewOffset();
    camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();

  let raf = 0;
  function frame(now) {
    const dt = lastNow == null ? 0 : Math.min(0.1, (now - lastNow) / 1000);
    lastNow = now;
    if (assemble < 1 && state.build) {
      if (assembleStart == null) assembleStart = now;
      const t = (now - assembleStart) / 1000 - ASSEMBLE_DELAY;
      assemble = Math.max(0, Math.min(1, t / ASSEMBLE_TIME));
    }
    // The split eases to its target: a slow ease-in-out when a button sent
    // it, a damped glide behind the thumb when the slider is dragged. Never
    // a step, so a jerky drag still draws as a smooth one.
    const before = splitShown;
    if (still) {
      splitShown = state.split;
      tween = null;
    } else if (tween) {
      if (tween.start == null) tween.start = now;
      const t = clamp01((now - tween.start) / 1000 / tween.dur);
      splitShown = tween.from + (tween.to - tween.from) * easeSine(t);
      if (t >= 1) {
        splitShown = tween.to;
        tween = null;
      }
    } else if (splitShown !== state.split) {
      splitShown += (state.split - splitShown) * (1 - Math.exp(-dt * 6));
      if (Math.abs(state.split - splitShown) < 5e-4) splitShown = state.split;
    }
    if (splitShown !== before) onSplit(splitShown, splitShown === state.split && !tween);
    if (Math.abs(shiftTo - shiftNow) > 0.25) {
      shiftNow += (shiftTo - shiftNow) * (1 - Math.exp(-dt * 5));
      applyShift();
    } else if (shiftNow !== shiftTo) {
      shiftNow = shiftTo;
      applyShift();
    }
    // An exploded building is taller; the aim point rises with it so the
    // top storey does not leave the frame.
    const lift = clamp01(splitShown / SPLIT_STOREYS) * 3.2 * Math.max(0, heights.length - 1) * 0.5;
    const dl = lift - liftApplied;
    if (dl) {
      controls.target.y += dl;
      camera.position.y += dl;
      liftApplied = lift;
    }
    layout(dt);
    controls.update();
    renderer.render(scene, camera);
    raf = requestAnimationFrame(frame);
  }
  restyle();
  layout(0);
  raf = requestAnimationFrame(frame);

  return {
    set(next) {
      const insetChanged = next.insetRight != null && next.insetRight !== state.insetRight;
      // Only what changes the look restyles; a slider tick should cost a
      // number, not a pass over every material.
      const styleChanged = ["heat", "focus", "storey"].some((k) => k in next && next[k] !== state[k]);
      if ("split" in next && next.split !== state.split) {
        tween = next.splitTween
          ? { from: splitShown, to: next.split, start: null, dur: Math.max(0.8, (next.split > splitShown ? 6 : 4.5) * Math.abs(next.split - splitShown)) }
          : null;
      }
      Object.assign(state, next);
      if (insetChanged) resize();
      if (styleChanged) restyle();
    },
    onHover(fn) {
      onHover = fn;
    },
    onPick(fn) {
      onPick = fn;
    },
    // (shown, settled): the split as drawn, for a slider to follow.
    onSplit(fn) {
      onSplit = fn;
    },
    // The classes whose every block has landed in its row.
    onLanded(fn) {
      onLanded = fn;
    },
    // How many blocks each class came apart into.
    inventory() {
      const out = {};
      for (const [cls, i] of Object.entries(classCount)) out[cls] = i + 1;
      return out;
    },
    reset() {
      camera.position.set(HOME[0], HOME[1] + liftApplied, HOME[2]);
      controls.target.set(0, H * 0.42 + liftApplied, 0);
      controls.autoRotate = !still;
    },
    view(name) {
      const t = controls.target;
      const views = {
        top: [0.001, span * 2.2, 0.001],
        front: [0, H * 0.5, span * 2.1],
        side: [span * 2.1, H * 0.5, 0],
        under: [span * 0.9, -span * 1.1, span * 0.9],
      };
      const v = views[name];
      if (!v) return;
      controls.autoRotate = false;
      camera.position.set(t.x + v[0], v[1], t.z + v[2]);
    },
    spin(on) {
      controls.autoRotate = on;
    },
    dispose() {
      cancelAnimationFrame(raf);
      ro.disconnect();
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerleave", onLeave);
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointerup", onUp);
      controls.dispose();
      scene.traverse((o) => {
        o.geometry?.dispose?.();
        if (o.material) [].concat(o.material).forEach((m) => m.dispose());
      });
      renderer.dispose();
    },
  };
}
