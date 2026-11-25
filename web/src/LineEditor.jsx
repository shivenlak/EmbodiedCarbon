// Edit one line: its material, its thickness, its quantity (UX session, 25 Nov).
//
// "Builders need to edit every nitty-gritty thing and see the carbon update,
// with where the numbers come from." Every change is posted to the line,
// recalculated on the server, and the calculation re-shown below the fields,
// so what you changed and what it did sit together. Materials come from the
// builder's own list first, then Canadian factors, then the rest; a material
// can be typed in with its source, or a whole list uploaded.

import { useContext, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { CalcContext, CalcSteps } from "./calc.jsx";
import { useUnits } from "./units.js";

const UNITS = ["m3", "m2", "kg", "m", "each"];

function MaterialForm({ onAdded, onCancel }) {
  const { api, projectId } = useContext(CalcContext);
  const [f, setF] = useState({ name: "", declared_unit: "m3", gwp_value: "", density_kg_m3: "", source: "", epd_id: "", valid_to: "" });
  const [err, setErr] = useState(null);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  async function save(e) {
    e.preventDefault();
    setErr(null);
    try {
      const r = await api.post(`/projects/${projectId}/materials`, {
        ...f,
        gwp_value: parseFloat(f.gwp_value),
        density_kg_m3: f.density_kg_m3 ? parseFloat(f.density_kg_m3) : null,
        epd_id: f.epd_id || null,
        valid_to: f.valid_to || null,
      });
      onAdded(r.factor_id);
    } catch (e2) {
      setErr(e2.message);
    }
  }
  return (
    <form className="le-newmat" onSubmit={save}>
      <label>
        Material name
        <input required value={f.name} onChange={set("name")} placeholder="e.g. Mineral wool batt, R-22" />
      </label>
      <div className="le-row">
        <label>
          Carbon factor (A1–A3)
          <input required inputMode="decimal" value={f.gwp_value} onChange={set("gwp_value")} placeholder="38.5" />
        </label>
        <label>
          per
          <select value={f.declared_unit} onChange={set("declared_unit")}>
            {UNITS.map((u) => (
              <option key={u} value={u}>
                {u === "kg" ? "kg (mass)" : u.replace("3", "³").replace("2", "²")}
              </option>
            ))}
          </select>
        </label>
        <label>
          Density, kg/m³
          <input inputMode="decimal" value={f.density_kg_m3} onChange={set("density_kg_m3")} placeholder="optional" />
        </label>
      </div>
      <p className="le-hint">The factor is kgCO₂e per unit chosen. A factor per kg (mass) needs a density to price a volume.</p>
      <div className="le-row">
        <label>
          Source (EPD or database)
          <input required value={f.source} onChange={set("source")} placeholder="Supplier product EPD" />
        </label>
        <label>
          EPD number
          <input value={f.epd_id} onChange={set("epd_id")} placeholder="optional" />
        </label>
        <label>
          Valid to
          <input type="date" value={f.valid_to} onChange={set("valid_to")} />
        </label>
      </div>
      {err && <p className="le-err">{err}</p>}
      <div className="le-actions">
        <button type="button" className="sc-link" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="le-primary">
          Add material
        </button>
      </div>
    </form>
  );
}

export function LibraryUpload({ onDone }) {
  const { api, projectId } = useContext(CalcContext);
  const [msg, setMsg] = useState(null);
  async function upload(file) {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    setMsg({ busy: true, text: `Reading ${file.name}…` });
    try {
      const res = await fetch(api.url(`/projects/${projectId}/materials/upload`), { method: "POST", body: fd });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || res.statusText);
      setMsg({
        text: `${body.added.length} material${body.added.length === 1 ? "" : "s"} added from ${file.name}`,
        errors: body.errors,
      });
      onDone?.();
    } catch (e) {
      setMsg({ text: `Could not read that list: ${e.message}`, errors: [] });
    }
  }
  return (
    <div className="le-library">
      <label className="le-file">
        <input type="file" accept=".csv,.xlsx" onChange={(e) => upload(e.target.files?.[0])} />
        <span>Upload your materials list (CSV or Excel)</span>
      </label>
      <a className="sc-link" href={api.url("/materials/template.csv")} download>
        Download the template
      </a>
      {msg && (
        <div className="le-libmsg">
          {msg.text}
          {msg.errors?.length > 0 && (
            <ul>
              {msg.errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export default function LineEditor({ line, carbonLine, onClose }) {
  const { api, projectId, afterEdit, calc } = useContext(CalcContext);
  const U = useUnits();
  const [materials, setMaterials] = useState([]);
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const drawnMm = useMemo(() => {
    if (line.unit !== "m3") return null;
    const m = [...(line.description || "").matchAll(/(\d+(?:\.\d+)?)\s*mm\b/g)];
    return m.length ? parseFloat(m[m.length - 1][1]) : null;
  }, [line]);
  const [thick, setThick] = useState("");
  const [qty, setQty] = useState("");

  const loadMaterials = () =>
    api.get(`/projects/${projectId}/materials`).then(setMaterials).catch(() => setMaterials([]));
  useEffect(() => {
    loadMaterials();
    const esc = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function send(body) {
    setErr(null);
    setBusy(true);
    try {
      const next = await api.post(`/projects/${projectId}/lines/${line.id}`, body);
      await afterEdit(next);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  const current = carbonLine?.factor?.factor_id;
  const chosen = calc?.[line.id]?.material_chosen;
  const q = query.trim().toLowerCase();
  const shown = materials.filter((m) => !q || m.name.toLowerCase().includes(q) || (m.source || "").toLowerCase().includes(q));
  const groups = ["yours", "Canada", "other"].map((o) => [o, shown.filter((m) => m.origin === o)]).filter(([, l]) => l.length);
  const label = { yours: "Your materials", Canada: "Canadian factors", other: "Other regions (not validated for Canada)" };

  return createPortal(
    <div className="le-backdrop" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="le" role="dialog" aria-label={`Edit ${line.description}`}>
        <header className="le-head">
          <div>
            <div className="sc-eyebrow">Edit this line</div>
            <h2>{U.text(line.description)}</h2>
          </div>
          <button type="button" className="calc-x" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>

        <section className="le-sec">
          <h3>Material</h3>
          <p className="le-now">
            Priced as <b>{carbonLine?.factor?.name || "no factor"}</b>
            {chosen && <em> · you chose this</em>}
          </p>
          <input
            className="le-search"
            placeholder="Search materials by name or source"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="le-list" role="listbox" aria-label="Materials">
            {groups.map(([o, list]) => (
              <div key={o}>
                <div className="le-group">{label[o]}</div>
                {list.map((m) => (
                  <button
                    key={m.factor_id}
                    role="option"
                    aria-selected={m.factor_id === current}
                    className={`le-mat${m.factor_id === current ? " is-on" : ""}`}
                    disabled={busy}
                    onClick={() => send({ factor_id: m.factor_id })}
                  >
                    <span>{m.name}</span>
                    <em>
                      {m.gwp_value} kgCO₂e per {m.declared_unit === "kg" ? "kg (mass)" : U.label(m.declared_unit)} · {m.source}
                    </em>
                  </button>
                ))}
              </div>
            ))}
          </div>
          {adding ? (
            <MaterialForm
              onCancel={() => setAdding(false)}
              onAdded={async (fid) => {
                setAdding(false);
                await loadMaterials();
                await send({ factor_id: fid });
              }}
            />
          ) : (
            <div className="le-actions le-left">
              <button type="button" className="le-secondary" onClick={() => setAdding(true)}>
                + Add your own material
              </button>
              <LibraryUpload onDone={loadMaterials} />
            </div>
          )}
          {chosen && (
            <button type="button" className="sc-link" onClick={() => send({ factor_id: null })}>
              Use the material the drawings name
            </button>
          )}
        </section>

        <section className="le-sec">
          <h3>Size</h3>
          <div className="le-row">
            {drawnMm != null && (
              <label>
                Thickness, mm <em>(drawn {drawnMm})</em>
                <input
                  inputMode="decimal"
                  value={thick}
                  placeholder={String(drawnMm)}
                  onChange={(e) => setThick(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && parseFloat(thick) > 0 && send({ thickness_mm: parseFloat(thick) })}
                />
              </label>
            )}
            <label>
              Quantity, {U.label(line.unit)} <em>(read {+U.v(line.quantity, line.unit).toFixed(3)})</em>
              <input
                inputMode="decimal"
                value={qty}
                placeholder={String(+U.v(line.user_override ?? line.quantity, line.unit).toFixed(3))}
                onChange={(e) => setQty(e.target.value)}
                onKeyDown={(e) =>
                  e.key === "Enter" && parseFloat(qty) >= 0 && send({ quantity: U.back(parseFloat(qty), line.unit), note: "stated in the editor" })
                }
              />
            </label>
          </div>
          <div className="le-actions le-left">
            {drawnMm != null && (
              <button type="button" className="le-secondary" disabled={busy || !(parseFloat(thick) > 0)} onClick={() => send({ thickness_mm: parseFloat(thick) })}>
                Apply thickness
              </button>
            )}
            <button
              type="button"
              className="le-secondary"
              disabled={busy || !(parseFloat(qty) >= 0)}
              onClick={() => send({ quantity: U.back(parseFloat(qty), line.unit), note: "stated in the editor" })}
            >
              Apply quantity
            </button>
            {line.user_override != null && (
              <button type="button" className="sc-link" onClick={() => send({ quantity: null })}>
                Back to the quantity read
              </button>
            )}
          </div>
        </section>

        {err && <p className="le-err">{err}</p>}

        <section className="le-sec">
          <h3>How it is calculated now</h3>
          <CalcSteps trace={calc?.[line.id]} />
        </section>
      </aside>
    </div>,
    document.body,
  );
}
