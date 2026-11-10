// The measured building in WebGL, for the showcase view.
//
// Every solid here is a quantity the pipeline read: the footprint from the
// linework, the storey datums from the sections, each partition where it was
// counted, the grade beam at the stated section. Nothing is modelled by hand.
// Windows, doors and the roof's pitch are not drawn, because the takeoff has
// counts and areas for them but no positions or profile -- drawing them would
// be decoration presented as measurement.
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

const STRUCTURE = {
  slab_on_grade: "#c9d1dc",
  footing: "#8d99ab",
  exterior_wall: "#e9f0fa",
  floor_assembly: "#dbe4f0",
  roof_assembly: "#dbe4f0",
  interior_partition: "#f4f7fb",
};

// "rgb(12 34 56)" from the shared ramp, into a THREE.Color.
function cssRgb(str) {
  const m = String(str).match(/(\d+)\D+(\d+)\D+(\d+)/);
  if (!m) return new THREE.Color(str);
  return new THREE.Color(+m[1] / 255, +m[2] / 255, +m[3] / 255);
}

export function createScene(canvas, massing, { heatColour, intensity, hotI, coolI, still }) {
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
  const span = Math.max(W, D, H * 2);
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
  grid.position.y = -SLAB_T;
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

  function solid({ cls, storey = null, x, y, z, w, h, d, opacity = 1, label, detail }) {
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
    mesh.position.set(x + w / 2, y + h / 2, z + d / 2);
    mesh.castShadow = opacity >= 0.5;
    mesh.receiveShadow = true;
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo), edgeMat.clone());
    mesh.add(edges);
    const part = { mesh, edges, cls, storey, baseOpacity: opacity, label, detail, y0: y + h / 2, h };
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
  const beamY = -SLAB_T - BEAM_D;
  const beam = { cls: "footing", y: beamY, h: BEAM_D, opacity: 0.9, label: "Footings", detail: "grade beam on the perimeter, below grade" };
  solid({ ...beam, x: 0, z: 0, w: W, d: BEAM_W });
  solid({ ...beam, x: 0, z: D - BEAM_W, w: W, d: BEAM_W });
  solid({ ...beam, x: 0, z: BEAM_W, w: BEAM_W, d: D - 2 * BEAM_W });
  solid({ ...beam, x: W - BEAM_W, z: BEAM_W, w: BEAM_W, d: D - 2 * BEAM_W });

  // The envelope, one shell per storey so the storeys can be pulled apart.
  heights.forEach((h, s) => {
    const y = datums[s];
    const shell = {
      cls: "exterior_wall", storey: s, y, h, opacity: 0.2,
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
      x: 0, y: d - FLOOR_T, z: 0, w: W, h: FLOOR_T, d: D,
      opacity: isRoof ? 0.16 : 0.22,
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
      x: w.x, y: base, z: w.y, w: Math.max(w.w, 0.09), h: Math.max(0.5, top - base), d: Math.max(w.d, 0.09),
      label: "Interior partition",
      detail: `storey ${w.storey + 1}, ${len.toFixed(2)} m long`,
    });
  }

  // ---- state the component drives --------------------------------------

  // `build` holds the build-up until the view says go, so it starts as the
  // photograph steps back rather than on a clock of its own.
  const state = { heat: false, storey: null, explode: 0, focus: null, hover: null, insetRight: 0, build: still };
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
      const visible = state.storey == null || p.storey == null || p.storey === state.storey;
      p.mesh.visible = visible;
      let op = p.baseOpacity;
      if (state.heat && p.cls !== "interior_partition" && p.cls !== "footing" && p.cls !== "slab_on_grade") {
        op = Math.max(op, 0.42);
      }
      if (!lit) op = Math.min(op, 0.07);
      m.opacity = op;
      m.transparent = op < 1;
      m.depthWrite = op >= 1;
      m.emissive = new THREE.Color(hovered ? "#d9a46a" : "#000000");
      m.emissiveIntensity = hovered ? 0.55 : 0;
      p.edges.material.opacity = lit ? (hovered ? 0.95 : 0.38) : 0.04;
      p.edges.material.color.set(hovered ? "#ffd8a8" : state.heat ? "#1b2433" : "#ffffff");
    }
  }

  function layout() {
    // Explode lifts each storey by a share of its own height, so the floor
    // plans open like drawers and every partition can be read from above.
    const lift = (s) => (s == null ? 0 : s * state.explode * 3.2);
    const k = THREE.MathUtils.smoothstep(assemble, 0, 1);
    for (const p of parts) {
      // The build-up: below grade first, then each storey in turn.
      const order = p.storey == null ? 0 : p.storey + 1;
      const local = THREE.MathUtils.clamp(k * (heights.length + 1.4) - order, 0, 1);
      const e = 1 - Math.pow(1 - local, 3);
      p.mesh.scale.y = Math.max(0.001, e);
      p.mesh.position.y = p.y0 - (p.h / 2) * (1 - e) + lift(p.storey);
      p.mesh.material.visible = e > 0.002;
      // The ground floor waits as its plan, drawn flat on the slab, then
      // rises: the drawing becoming the building. Anything above it stays
      // hidden until it starts to rise, rather than floating as an outline.
      p.edges.visible = e > 0.002 || order <= 1;
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
    // centred there rather than behind the glass.
    const shift = Math.min(state.insetRight, w * 0.4) / 2;
    if (shift > 0) camera.setViewOffset(w, h, shift, 0, w, h);
    else camera.clearViewOffset();
    camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();

  let raf = 0;
  function frame(now) {
    if (assemble < 1 && state.build) {
      if (assembleStart == null) assembleStart = now;
      const t = (now - assembleStart) / 1000 - ASSEMBLE_DELAY;
      assemble = Math.max(0, Math.min(1, t / ASSEMBLE_TIME));
    }
    layout();
    controls.update();
    renderer.render(scene, camera);
    raf = requestAnimationFrame(frame);
  }
  restyle();
  layout();
  raf = requestAnimationFrame(frame);

  return {
    set(next) {
      const insetChanged = next.insetRight != null && next.insetRight !== state.insetRight;
      Object.assign(state, next);
      // An exploded building is taller; the aim point rises with it so the
      // top storey does not leave the frame.
      const lift = state.explode * 3.2 * Math.max(0, heights.length - 1) * 0.5;
      const d = lift - liftApplied;
      if (d) {
        controls.target.y += d;
        camera.position.y += d;
        liftApplied = lift;
      }
      if (insetChanged) resize();
      restyle();
    },
    onHover(fn) {
      onHover = fn;
    },
    onPick(fn) {
      onPick = fn;
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
