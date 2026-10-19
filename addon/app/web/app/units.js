// Dynamic units in the inspector. The renderer does the real work
// (render/units.py); this mirrors its tables only to show an example.

import { h, clone } from "./util.js";
import { field, number, select, seg, linkButton, toast } from "./ui.js";

const FAMILIES = [
  [["mW", 1e-3], ["W", 1], ["kW", 1e3], ["MW", 1e6], ["GW", 1e9]],
  [["Wh", 1], ["kWh", 1e3], ["MWh", 1e6], ["GWh", 1e9]],
  [["mg", 1e-3], ["g", 1], ["kg", 1e3], ["t", 1e6]],
  [["mm", 1e-3], ["cm", 1e-2], ["m", 1], ["km", 1e3]],
  [["mA", 1e-3], ["A", 1], ["kA", 1e3]],
  [["mV", 1e-3], ["V", 1], ["kV", 1e3]],
  [["VA", 1], ["kVA", 1e3], ["MVA", 1e6]],
  [["var", 1], ["kvar", 1e3]],
  [["B", 1], ["kB", 1e3], ["MB", 1e6], ["GB", 1e9], ["TB", 1e12]],
  [["bit/s", 1], ["kbit/s", 1e3], ["Mbit/s", 1e6], ["Gbit/s", 1e9]],
  [["Hz", 1], ["kHz", 1e3], ["MHz", 1e6], ["GHz", 1e9]],
  [["mL", 1e-3], ["L", 1], ["m³", 1e3]],
  [["ms", 1e-3], ["s", 1], ["min", 60], ["h", 3600], ["d", 86400]],
];
const CONVERT = { "m/s": ["km/h", "mph"], "km/h": ["m/s", "mph"], "mph": ["km/h"], "°C": ["°F"], "°F": ["°C"], "km": ["mi"], "mi": ["km"], "kg": ["lb"], "lb": ["kg"], "hPa": ["inHg"], "L": ["gal"] };

function familyOf(u) { for (const f of FAMILIES) { const i = f.findIndex(([x]) => x === u); if (i >= 0) return [f, i]; } return [null, -1]; }
function scaleExample(base) {
  const [f, i] = familyOf(base);
  if (!f || i === f.length - 1) return null;
  const next = f[i + 1], ratio = next[1] / f[i][1];
  const below = Math.round(ratio * 0.95), above = ratio * 1.234;
  return `${below.toLocaleString()} ${base} stays ${base}; ${Math.round(above).toLocaleString()} ${base} shows as ${(above / ratio).toFixed(2)} ${next[0]}.`;
}

export function unitsRows(app, el, set) {
  const ent = el.entity ? app.entMap.get(el.entity) : null;
  const sensorUnit = (ent && ent.unit) || "";
  const base = el.units?.base || sensorUnit || String(el.suffix || "").trim();
  const canScale = !!familyOf(base)[0], targets = CONVERT[base] || [];
  if (!el.units && !canScale && !targets.length) return null;
  const mode = el.units ? (el.units.mode || "scale") : "off";
  const wrap = h("div", { class: "unitsbox" });
  const options = [["off", "As is"]];
  if (canScale) options.push(["scale", "Step up"]);
  if (targets.length) options.push(["convert", "Convert"]);
  wrap.append(h("div", { class: "field" }, h("span", { class: "lab", text: "Units" }), seg(options, mode, (v) => {
    if (v === "off") { delete el.units; if (el.type === "number" && base && !el.suffix) el.suffix = " " + base; }
    else {
      el.units = { base, mode: v, ...(v === "scale" ? { decimals: el.units?.decimals ?? 2 } : { to: el.units?.to || targets[0] }) };
      if (String(el.suffix || "").trim() === base) delete el.suffix;
    }
    app.doc.commit();
  }, "Units")));
  if (mode === "scale") {
    const ex = scaleExample(base);
    if (ex) wrap.append(h("p", { class: "fnote", text: ex }));
    wrap.append(field("Decimals then", number(el.units.decimals ?? 2, (v) => { el.units.decimals = v === "" ? 2 : Number(v); app.doc.commit(); }, { min: "0", max: "4" })));
  }
  if (mode === "convert") {
    wrap.append(field("Show in", select(targets.map((t) => [t, t]), el.units.to || targets[0], (v) => { el.units.to = v; app.doc.commit(); })));
  }
  if (mode !== "off" && el.type === "number") {
    wrap.append(linkButton("Add a label that follows the unit", () => {
      const g = app.geometry();
      const label = { type: "text", entity: el.entity, show: "unit", units: clone(el.units), size: 30, bold: false, align: el.align || "left",
        x: el.x, y: Math.min(g.H - 44, el.y + el.h + 4), w: el.w, h: 40 };
      if (base === "W") label.replace = { W: "Watts" };
      app.doc.els().push(label);
      app.doc.sel = [app.doc.els().length - 1];
      app.doc.commit();
      toast("Added a label that says the unit. Change its words under Say it differently.");
    }));
  }
  return wrap;
}
