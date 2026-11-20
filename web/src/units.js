// Metric or imperial, everywhere a quantity is shown.
//
// The pipeline works in SI and the server stores SI; only what is displayed
// changes. A US builder reading m² and m³ has to convert in their head, which
// is exactly the friction a tool meant to be picked up without training
// should not add. kg CO2e stays kg CO2e: it is the reporting unit in the US
// too (EC3, LEED, Buy Clean).

import { createContext, useContext } from "react";

// SI unit -> [multiplier into the imperial unit, its label].
const TO_IMPERIAL = {
  m: [3.28084, "ft"],
  m2: [10.7639, "ft²"],
  m3: [1.30795, "yd³"],
  mm: [1 / 25.4, "in"],
};
const METRIC_LABEL = { m3: "m³", m2: "m²", m: "m", each: "each", kg: "kg", mm: "mm" };

export const UnitsContext = createContext({ system: "metric", setSystem: () => {} });

const STORE_KEY = "ec-units";

// The viewer's own choice, if they made one; null otherwise.
export function savedSystem() {
  try {
    const v = localStorage.getItem(STORE_KEY);
    return v === "metric" || v === "imperial" ? v : null;
  } catch {
    return null;
  }
}
export function saveSystem(system) {
  try {
    localStorage.setItem(STORE_KEY, system);
  } catch {
    /* private window: the choice lasts this visit */
  }
}

// What a project defaults to when the viewer has not chosen: feet for a
// project priced as US, metres otherwise.
export function defaultSystem(region) {
  return region?.geography?.toUpperCase().startsWith("US") ? "imperial" : "metric";
}

export function makeUnits(system = "metric", setSystem = () => {}) {
  const imperial = system === "imperial";
  const k = (unit) => (imperial && TO_IMPERIAL[unit] ? TO_IMPERIAL[unit][0] : 1);
  const label = (unit) =>
    imperial && TO_IMPERIAL[unit] ? TO_IMPERIAL[unit][1] : METRIC_LABEL[unit] ?? unit;
  return {
    system,
    setSystem,
    imperial,
    // A stored SI value as shown, and a shown value back to SI.
    v: (value, unit) => (value == null ? value : value * k(unit)),
    back: (value, unit) => (value == null ? value : value / k(unit)),
    label,
    // kg per m² as kg per ft², and its label.
    perArea: (kgPerM2) => (kgPerM2 == null ? kgPerM2 : kgPerM2 / k("m2")),
    areaLabel: label("m2"),
    // A factor in kg per declared unit (m³, m²) as kg per shown unit.
    perUnit: (kgPer, unit) => (kgPer == null ? kgPer : kgPer / k(unit)),
    // Numbers with units inside a server sentence ("130 mm over 154.0 m2").
    text: (t) => (imperial ? toImperialText(t) : t),
  };
}

export function useUnits() {
  const { system, setSystem } = useContext(UnitsContext);
  return makeUnits(system, setSystem);
}

const fmt = (n, places) =>
  n.toLocaleString("en-US", { minimumFractionDigits: places, maximumFractionDigits: places });

// "154.0 m2 footprint" -> "1,658 ft² footprint", "130 mm" -> "5.1 in". Only a
// number followed by a unit is touched, so "kgCO2e/m2" and sheet names are not.
function toImperialText(t) {
  return String(t ?? "").replace(
    /(\d[\d,]*(?:\.\d+)?)\s?(mm|m2|m²|m3|m³|m)(?![\w²³])/g,
    (whole, num, unit) => {
      const value = parseFloat(num.replace(/,/g, ""));
      if (!Number.isFinite(value)) return whole;
      const u = unit === "m²" ? "m2" : unit === "m³" ? "m3" : unit;
      const [mult, lab] = TO_IMPERIAL[u];
      const x = value * mult;
      const places = u === "m2" ? 0 : x < 10 ? 2 : 1;
      return `${fmt(x, places)} ${lab}`;
    },
  );
}
