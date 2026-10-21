// Element types, their starting values, their names, and the geometry of each
// panel model. Panel pixels throughout: the numbers come from theme.py.

// Each panel model and its canvases, landscape and portrait: size, footer band
// and side margin. They come from the add-on (theme.canvas_geometry, sent with
// api/devices), so the guides sit where the renderer draws.
export const DISPLAYS = {};
export function setDisplays(ds) {
  if (!ds || typeof ds !== "object" || !Object.keys(ds).length) return;
  for (const k of Object.keys(DISPLAYS)) delete DISPLAYS[k];
  Object.assign(DISPLAYS, ds);
}

export function geometry(spec) {
  const d = DISPLAYS[spec.display] || Object.values(DISPLAYS)[0];
  const portrait = [90, 270].includes(Number(spec.orientation || 0));
  const c = portrait ? d.portrait : d.landscape;
  return { d, W: c.w, H: c.h, portrait, footer: c.band, safeH: c.h - c.band, margin: c.margin, mmPerPx: d.mm_w / d.w };
}

export const TYPES = {
  number: { name: "Value", icon: "value" },
  text: { name: "Text", icon: "text" },
  icon: { name: "Icon", icon: "image" },
  box: { name: "Card", icon: "square" },
  line: { name: "Divider", icon: "line" },
  bar: { name: "Gauge", icon: "gauge" },
  curve: { name: "Sparkline", icon: "wave" },
  bar_chart: { name: "Bar chart", icon: "chart" },
  qr: { name: "QR code", icon: "qr" },
  weather_forecast: { name: "Weather", icon: "cloud" },
  dynamic_grid: { name: "Devices", icon: "grid" },
  calendar_month: { name: "Month", icon: "calendar" },
  calendar_agenda: { name: "Agenda", icon: "list" },
  todo_list: { name: "To-do list", icon: "todo" },
  flight_tracker: { name: "Flights", icon: "plane" },
  sports_racing: { name: "Racing", icon: "flag" },
  sports_match: { name: "Match", icon: "ball" },
  sun_times: { name: "Sunrise and sunset", icon: "sun" },
  energy_total: { name: "Energy total", icon: "chart" },
  grid_now: { name: "Grid now", icon: "plug" },
  energy_cost: { name: "Energy cost", icon: "value" },
  now_playing: { name: "Now playing", icon: "play" },
  tv_week: { name: "On TV this week", icon: "calendar" },
  group: { name: "Group", icon: "layers" },
};
export const GROUP_STYLES = [["outline", "Outline"], ["pill", "Pill"], ["invert", "Inverted"]];
export const GROUP_PAD = 10;

/* A group's box: around its members, `pad` out (the renderer draws it the same way). */
export function groupBox(group, els) {
  const ids = new Set(group.members || []);
  const ms = els.filter((e) => e.type !== "group" && ids.has(e.id));
  if (!ms.length) return null;
  const pad = Number.isFinite(Number(group.pad)) ? Math.max(0, Math.min(60, Number(group.pad))) : GROUP_PAD;
  const x0 = Math.min(...ms.map((e) => e.x)) - pad, y0 = Math.min(...ms.map((e) => e.y)) - pad;
  const x1 = Math.max(...ms.map((e) => e.x + e.w)) + pad, y1 = Math.max(...ms.map((e) => e.y + e.h)) + pad;
  return { x: Math.max(0, Math.round(x0)), y: Math.max(0, Math.round(y0)), w: Math.round(x1 - Math.max(0, x0)), h: Math.round(y1 - Math.max(0, y0)) };
}
export const INSERT_GROUPS = [
  ["Basics", ["text", "number", "icon", "box", "line"]],
  ["Charts", ["bar", "curve", "bar_chart"]],
  ["Widgets", ["weather_forecast", "sun_times", "energy_total", "grid_now", "energy_cost", "now_playing", "tv_week", "calendar_month", "calendar_agenda", "todo_list", "dynamic_grid", "flight_tracker", "sports_racing", "sports_match", "qr"]],
];
export const WIDGETS = ["dynamic_grid", "calendar_month", "calendar_agenda", "todo_list", "weather_forecast", "flight_tracker", "sports_racing", "sports_match", "sun_times", "energy_total", "grid_now", "energy_cost", "now_playing", "tv_week"];
export const BREAKABLE = ["weather_forecast", "flight_tracker", "calendar_agenda", "sports_match", "sports_racing"];
export const isWidget = (el) => WIDGETS.includes(el.type);
export const hasText = (el) => el.type === "text" || el.type === "number";

/* A new element of a type, placed sensibly on this panel (from the 0.9 palette). */
export function makeElement(t, g) {
  const m = g.margin, maxW = g.W - m * 2;
  const base = { type: t, x: m, y: 60, w: Math.min(t === "line" ? 240 : 260, maxW), h: t === "line" ? 4 : 90 };
  if (t === "number") Object.assign(base, { entity: "", show: "state", decimals: 1, align: "left" });
  if (t === "text") Object.assign(base, { value: "Label", size: 30, bold: false, align: "left", h: 44 });
  if (t === "icon") Object.assign(base, { icon: "mdi:home", w: 110, h: 110 });
  if (t === "box") Object.assign(base, { x: m, y: 36, w: Math.min(240, maxW), h: 120, fill: "outline", radius: 12, thickness: 3 });
  if (t === "line") Object.assign(base, { h: 8, thickness: 4 });
  if (t === "bar") Object.assign(base, { y: 70, w: Math.min(280, maxW), h: 58, entity: "", title: "Battery", min_val: 0, max_val: 100, suffix: "%", bar_style: "solid", show_label: true, decimals: 0 });
  if (t === "curve") Object.assign(base, { entity: "", hours: 24 });
  if (t === "bar_chart") Object.assign(base, { y: 36, w: Math.min(320, maxW), h: 140, entity: "", hours: 24, bars: 12, title: "Last 24 hours", show_labels: true, show_border: false });
  if (t === "qr") Object.assign(base, { y: 26, w: 148, h: 172, value: "https://www.home-assistant.io", title: "Scan me", show_border: false });
  if (t === "dynamic_grid") Object.assign(base, { y: 16, w: maxW, h: g.safeH - 24, header_icon: "mdi:lightning-bolt", header_title: "On now", filter_state: "on", layout_mode: "grid", show_labels: "both", icon_size: "auto", secondary_mode: "runtime", items: [{ entity: "", name: "Spot 1", icon: "mdi:radiator" }, { entity: "", name: "Spot 2", icon: "mdi:radiator" }] });
  if (t === "calendar_month") Object.assign(base, { x: 20, y: 14, w: Math.min(360, maxW), h: Math.min(230, g.safeH - 20), show_header: true, show_weekdays: true, first_weekday: 0, highlight_today: true, show_border: true, entity: "" });
  if (t === "calendar_agenda") Object.assign(base, { x: m, y: 14, w: Math.min(380, maxW), h: Math.min(230, g.safeH - 20), title: "Coming up", max_events: 4, show_border: true, entity: "" });
  if (t === "todo_list") Object.assign(base, { y: 14, w: maxW, h: g.safeH - 20, entity: "" });
  if (t === "weather_forecast") Object.assign(base, { y: 14, w: maxW, h: g.safeH - 20, entity: "weather.forecast_home", show_border: true });
  if (t === "flight_tracker") Object.assign(base, { y: 14, w: maxW, h: g.safeH - 20, radius: 35, style: "card", show_border: true });
  if (t === "sports_racing") Object.assign(base, { y: 14, w: maxW, h: g.safeH - 20, series: "f1", entity: "", show_border: true });
  if (t === "sports_match") Object.assign(base, { y: 14, w: maxW, h: g.safeH - 20, league: "soccer/eng.1", team: "", entity: "", show_border: true });
  // The widgets that size everything from their own box (render/hero.py): the content area.
  if (t === "sun_times") Object.assign(base, { y: 14, w: maxW, h: g.safeH - 20, style: "next" });
  if (t === "energy_total") Object.assign(base, { y: 14, w: maxW, h: g.safeH - 20, source: "solar", entity: "", period: "month" });
  if (t === "grid_now") Object.assign(base, { y: 14, w: maxW, h: g.safeH - 20, entity: "", invert: false });
  if (t === "energy_cost") Object.assign(base, { y: 14, w: maxW, h: g.safeH - 20 });
  if (t === "now_playing") Object.assign(base, { y: 14, w: maxW, h: g.safeH - 20, entity: "" });
  if (t === "tv_week") Object.assign(base, { y: 14, w: maxW, h: g.safeH - 20, entity: "", days: 7 });
  base.x = Math.max(0, Math.min(g.W - base.w, base.x));
  base.y = Math.max(0, Math.min(g.H - base.h, base.y));
  return base;
}

/* A value or text for an entity, the way the 0.9 drop did it. */
export function makeEntityElement(ent, g, at) {
  const numeric = ent && ent.state !== "" && !isNaN(Number(ent.state));
  const isCal = ent.entity_id.startsWith("calendar.");
  const w = Math.min(280, g.W - g.margin * 2), hh = 90;
  const el = { type: numeric ? "number" : "text", entity: ent.entity_id, show: isCal ? "days_until" : "state", align: "left",
    x: at ? Math.max(0, Math.min(g.W - w, Math.round(at.x - w / 2))) : Math.round((g.W - w) / 2),
    y: at ? Math.max(0, Math.min(g.H - hh, Math.round(at.y - hh / 2))) : Math.round((g.safeH - hh) / 2), w, h: hh };
  if (numeric) { el.decimals = String(ent.state).includes(".") ? 1 : 0; if (ent.unit) el.suffix = " " + ent.unit; }
  if (isCal) el.suffix = " days";
  return el;
}

/* What the layer list and the inspector call an element. */
export function elName(el, entMap) {
  const t = TYPES[el.type]?.name || el.type;
  let d = "";
  const ent = el.entity && entMap ? entMap.get(el.entity) : null;
  if (el.type === "group") d = `${(GROUP_STYLES.find(([v]) => v === el.style) || [, ""])[1]} around ${(el.members || []).length}`;
  else if (el.type === "dynamic_grid") d = el.header_title || "";
  else if (ent) d = ent.name || el.entity;
  else if (el.entity) d = el.entity;
  else if (el.value && !/\{[{%]/.test(el.value)) d = "“" + String(el.value).slice(0, 40) + "”";
  else if (el.value) d = "Template";
  else if (el.icon) d = String(el.icon).replace(/^mdi:/, "").replace(/-/g, " ");
  else if (el.title) d = el.title;
  return { t, d };
}

/* Pair two element lists by type, in order: what Paste and match uses. */
export function pairByType(targets, sources) {
  const used = new Set();
  return targets.map((el) => {
    const j = sources.findIndex((o, k) => !used.has(k) && o.type === el.type);
    if (j >= 0) used.add(j);
    return [el, j >= 0 ? sources[j] : null];
  });
}
export const LAYOUT_KEYS = ["x", "y", "w", "h", "size", "bold", "font", "align", "invert", "pill", "radius", "font_scale"];

/* Keep a divider's stroke dead centre in its box (from 0.9). */
export function normalizeLineParity(el, targetCenter = null, axis = "x") {
  if (!el || el.type !== "line") return;
  const thick = Math.max(1, Number(el.thickness || el.stroke || 2));
  const isVert = el.h >= el.w;
  if (isVert && axis === "x") {
    const cx = targetCenter !== null ? targetCenter : (el.x + el.w / 2);
    let baseW = Math.max(thick + 6, el.w || 8);
    if ((baseW % 2) !== (thick % 2)) baseW += 1;
    el.w = baseW; el.x = Math.round(cx - el.w / 2);
  } else if (!isVert && axis === "y") {
    const cy = targetCenter !== null ? targetCenter : (el.y + el.h / 2);
    let baseH = Math.max(thick + 6, el.h || 8);
    if ((baseH % 2) !== (thick % 2)) baseH += 1;
    el.h = baseH; el.y = Math.round(cy - el.h / 2);
  }
}
