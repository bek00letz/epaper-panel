"use strict";
/* Clickable mockups of the editor directions. Everything here is fake data
   drawn in the browser; the real editor renders through /api/preview. */

const W = 792, H = 272, MARGIN = 40, FOOT = 236, SNAP = 6;
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (_) {} },
};

/* ---------- tiny DOM helper (text always goes in as text) ---------- */
function h(tag, props, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k === "style") Object.assign(n.style, v);
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (k === "data") Object.assign(n.dataset, v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c !== null && c !== undefined && c !== false) n.append(c.nodeType ? c : document.createTextNode(String(c)));
  return n;
}

/* UI glyphs, drawn to match SF Symbols' regular weight. Trusted constants. */
const P = (d, extra = "") => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"${extra}>${d}</svg>`;
const ICON = {
  plus: P('<path d="M12 5v14M5 12h14"/>'),
  undo: P('<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>'),
  redo: P('<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>'),
  gear: P('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'),
  send: P('<path d="M12 19V5M6 11l6-6 6 6"/>'),
  layers: P('<path d="m12 3 9 5-9 5-9-5 9-5z"/><path d="m3 13 9 5 9-5"/>'),
  sidebar: P('<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>'),
  back: P('<path d="m15 18-6-6 6-6"/>'),
  chev: P('<path d="m9 6 6 6-6 6"/>'),
  close: P('<path d="M6 6l12 12M18 6 6 18"/>'),
  search: P('<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>'),
  grip: P('<path d="M8 6h.01M8 12h.01M8 18h.01M16 6h.01M16 12h.01M16 18h.01"/>', ' stroke-width="2.6"'),
  trash: P('<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>'),
  dup: P('<rect x="8" y="8" width="12" height="12" rx="2.5"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>'),
  moon: P('<path d="M20 14.5A8 8 0 1 1 9.5 4 6.5 6.5 0 0 0 20 14.5z"/>'),
  sparkle: P('<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>'),
  info: P('<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>'),
  value: P('<path d="M5 9h14M5 15h14M10 4 8 20M16 4l-2 16"/>'),
  text: P('<path d="M5 6V4h14v2M12 4v16M9 20h6"/>'),
  image: P('<rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>'),
  square: P('<rect x="4" y="4" width="16" height="16" rx="3"/>'),
  line: P('<path d="M4 12h16"/>'),
  wave: P('<path d="M3 15c3 0 3-6 6-6s3 8 6 8 3-6 6-6"/>'),
  gauge: P('<rect x="3" y="8" width="18" height="8" rx="2"/><path d="M7 8v8M11 8v8"/>'),
  chart: P('<path d="M5 20V10M10 20V4M15 20v-8M20 20v-5"/>'),
  cloud: P('<path d="M7 18h10a4 4 0 0 0 .5-8 6 6 0 0 0-11.4 1.5A3.3 3.3 0 0 0 7 18z"/>'),
  calendar: P('<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/>'),
  grid: P('<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>'),
  plane: P('<path d="M10.5 21 12 18l1.5 3M12 3c1 0 1.5 1 1.5 2v4l7 4v2l-7-2v4l2 1.5v1.5L12 19l-3.5 1.5V19l2-1.5v-4l-7 2v-2l7-4V5c0-1 .5-2 1.5-2z"/>'),
  qr: P('<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><path d="M14 14h2v2M18 14h2M14 18h2v2M18 18h2v2"/>'),
  centerh: P('<path d="M12 3v18M7 8h10v8H7z"/>'),
  centerv: P('<path d="M3 12h18M8 7h8v10H8z"/>'),
  widen: P('<path d="M3 4v16M21 4v16M7 12h10M10 9l-3 3 3 3M14 9l3 3-3 3"/>'),
  front: P('<rect x="9" y="9" width="11" height="11" rx="2" fill="currentColor"/><path d="M5 15H4V4h11v1"/>'),
  back2: P('<rect x="4" y="4" width="11" height="11" rx="2" fill="currentColor"/><path d="M19 9h1v11H9v-1"/>'),
  fwd: P('<path d="M12 19V7M7 12l5-5 5 5"/>'),
  bwd: P('<path d="M12 5v12M7 12l5 5 5-5"/>'),
  clip: P('<rect x="7" y="4" width="10" height="4" rx="1.5"/><path d="M9 6H7a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-2"/>'),
};
function icon(name, cls = "") {
  const s = h("span", { class: "ic " + cls, "aria-hidden": "true" });
  s.innerHTML = ICON[name] || "";
  return s;
}

/* Panel art: chunky black glyphs, as the panel draws them. */
const A = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
const ART = {
  sun: A('<circle cx="12" cy="12" r="4.2" fill="currentColor"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8"/>'),
  paw: `<svg viewBox="0 0 24 24" fill="currentColor"><ellipse cx="6" cy="10" rx="2.1" ry="2.7"/><ellipse cx="10" cy="6.2" rx="2.2" ry="2.9"/><ellipse cx="14.6" cy="6.2" rx="2.2" ry="2.9"/><ellipse cx="18.4" cy="10" rx="2.1" ry="2.7"/><path d="M12.2 11.2c-3 0-6.2 4.6-6.2 7.1 0 1.8 1.6 2.4 3 2.1 1.2-.3 2.1-.8 3.2-.8s2 .5 3.2.8c1.4.3 3-.3 3-2.1 0-2.5-3.2-7.1-6.2-7.1z"/></svg>`,
  thermo: A('<path d="M14 14.8V4.5a2 2 0 0 0-4 0v10.3a4 4 0 1 0 4 0z"/><circle cx="12" cy="17.5" r="1.6" fill="currentColor"/>'),
  dryer: A('<rect x="4" y="3" width="16" height="18" rx="2.5"/><circle cx="12" cy="13" r="4.2"/><path d="M7.5 6.5h.01M10.5 6.5h.01"/>'),
  pin: A('<path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3" fill="currentColor"/>'),
  battery: A('<rect x="3" y="7" width="16" height="10" rx="2"/><path d="M21 10.5v3"/><rect x="5.5" y="9.5" width="8" height="5" fill="currentColor" stroke="none"/>'),
  clock: A('<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>'),
  calendar: A('<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>'),
  tv: A('<rect x="3" y="5" width="18" height="12" rx="2.5"/><path d="M8 21h8M12 17v4"/>'),
  door: A('<path d="M6 21V4.5A1.5 1.5 0 0 1 7.5 3h9A1.5 1.5 0 0 1 18 4.5V21M3 21h18"/><path d="M14.5 12h.01"/>'),
  bin: A('<path d="M4 7h16M6.5 7l1 13h9l1-13M9.5 7V4h5v3"/>'),
};
const ART_NAMES = { sun: "Sun", paw: "Paw", thermo: "Thermometer", dryer: "Dryer", pin: "Map pin", battery: "Battery", clock: "Clock", calendar: "Calendar", tv: "TV", door: "Door", bin: "Bin" };

/* ---------- fake Home Assistant ---------- */
const ENT = {
  "sensor.solar_today_production": ["Solar today", "12.4", "kWh"],
  "sensor.epaper_solar_month": ["Solar this month", "318", "kWh"],
  "sensor.solar_pv_power": ["Solar power", "2140", "W"],
  "sensor.home_battery": ["Home battery", "76", "%"],
  "sensor.cat_location": ["Cat's spot", "Sofa", ""],
  "sensor.outdoor_temperature": ["Outside", "8.5", "°C"],
  "sensor.indoor_temperature": ["Inside", "21.2", "°C"],
  "sensor.epaper_watch": ["Next to watch", "Severance", ""],
  "sensor.epaper_watch_count": ["New to watch", "0", ""],
  "timer.dryer_cycle": ["Dryer", "idle", ""],
  "sensor.home_distance": ["Distance from home", "420", "m"],
  "binary_sensor.front_door": ["Front door", "off", ""],
  "calendar.bins": ["Bin collection", "Recycling", ""],
  "sensor.living_room_humidity": ["Living room humidity", "47", "%"],
};
const STATES = { "timer.dryer_cycle": ["active", "idle", "paused"], "binary_sensor.front_door": ["on", "off"] };

const SEED = {
  rotate_seconds: 30,
  rotation: ["solar", "solar_month", "cat", "watch", "cat", "temps", "dryer", "energy"],
  pages: {
    solar: { tier: "rotate", elements: [
      { type: "icon", icon: "sun", x: 32, y: 44, w: 116, h: 116 },
      { type: "number", entity: "sensor.solar_today_production", x: 160, y: 30, w: 310, h: 128 },
      { type: "text", value: "kWh today", size: 30, bold: false, x: 164, y: 170, w: 320, h: 40 },
      { type: "curve", entity: "sensor.solar_pv_power", x: 490, y: 100, w: 270, h: 86 },
    ] },
    solar_month: { tier: "rotate", elements: [
      { type: "icon", icon: "sun", x: 40, y: 52, w: 100, h: 100 },
      { type: "number", entity: "sensor.epaper_solar_month", x: 168, y: 34, w: 280, h: 118 },
      { type: "text", value: "kWh this month", size: 30, bold: false, x: 170, y: 172, w: 340, h: 40 },
      { type: "text", entity: "sensor.home_battery", prefix: "battery ", suffix: " %", size: 30, bold: false, x: 452, y: 172, w: 300, h: 40 },
    ] },
    cat: { tier: "rotate", elements: [
      { type: "icon", icon: "paw", x: 96, y: 24, w: 180, h: 180 },
      { type: "text", entity: "sensor.cat_location", x: 320, y: 60, w: 430, h: 112 },
      { type: "text", entity: "sensor.cat_location", show: "last_changed", prefix: "since ", size: 30, bold: false, x: 324, y: 184, w: 420, h: 40 },
    ] },
    temps: { tier: "rotate", elements: [
      { type: "text", value: "outside", size: 30, bold: false, x: 62, y: 44, w: 200, h: 36 },
      { type: "number", entity: "sensor.outdoor_temperature", suffix: "°", x: 56, y: 86, w: 290, h: 112 },
      { type: "line", x: 392, y: 40, w: 4, h: 160 },
      { type: "text", value: "inside", size: 30, bold: false, x: 436, y: 44, w: 200, h: 36 },
      { type: "number", entity: "sensor.indoor_temperature", suffix: "°", x: 430, y: 86, w: 290, h: 112 },
    ] },
    watch: { tier: "when", cond: { entity: "sensor.epaper_watch_count", op: "gt", value: "0" }, elements: [
      { type: "text", value: "new to watch", size: 26, bold: false, x: 40, y: 28, w: 300, h: 36 },
      { type: "text", entity: "sensor.epaper_watch", x: 40, y: 74, w: 712, h: 150 },
    ] },
    dryer: { tier: "when", cond: { entity: "timer.dryer_cycle", op: "eq", value: "active" }, elements: [
      { type: "icon", icon: "dryer", x: 56, y: 60, w: 110, h: 110 },
      { type: "text", value: "0:42", x: 190, y: 40, w: 320, h: 122 },
      { type: "text", value: "dryer, time left", size: 30, bold: false, x: 194, y: 176, w: 400, h: 40 },
    ] },
    energy: { tier: "rotate", elements: [
      { type: "icon", icon: "battery", x: 40, y: 78, w: 84, h: 84 },
      { type: "number", entity: "sensor.home_battery", suffix: " %", decimals: 0, size: 76, x: 136, y: 66, w: 220, h: 100 },
      { type: "text", value: "home battery", size: 26, bold: false, x: 40, y: 178, w: 320, h: 40 },
      { type: "box", fill: "outline", radius: 14, thickness: 3, x: 18, y: 14, w: 362, h: 216 },
      { type: "curve", entity: "sensor.solar_pv_power", x: 414, y: 74, w: 344, h: 96 },
      { type: "text", value: "solar today", size: 26, bold: false, x: 414, y: 28, w: 350, h: 190, valign: "top" },
      { type: "number", entity: "sensor.solar_today_production", suffix: " kWh", decimals: 1, size: 40, x: 414, y: 178, w: 330, h: 46 },
      { type: "box", fill: "outline", radius: 14, thickness: 3, x: 396, y: 14, w: 380, h: 216 },
    ] },
    clock: { tier: "rotate", elements: [
      { type: "text", value: "14:05", size: 110, x: 40, y: 20, w: 450, h: 140 },
      { type: "text", value: "Monday, 19 October", size: 36, bold: false, x: 44, y: 168, w: 500, h: 46 },
      { type: "icon", icon: "clock", x: 620, y: 40, w: 120, h: 120 },
    ] },
    arrival: { tier: "alert", hold: 10, elements: [
      { type: "icon", icon: "pin", x: 40, y: 56, w: 120, h: 120 },
      { type: "text", value: "Arriving", x: 184, y: 34, w: 560, h: 104 },
      { type: "text", entity: "sensor.home_distance", prefix: "nearly home · ", suffix: " m away", size: 34, bold: false, x: 188, y: 150, w: 560, h: 44 },
    ] },
  },
};
const clone = (o) => JSON.parse(JSON.stringify(o));

const PRESETS = [
  { id: "climate", title: "Room climate", desc: "Temperature and a 24-hour curve", domain: "sensor", make: (e) => [
    { type: "icon", icon: "thermo", x: 32, y: 44, w: 116, h: 116 },
    { type: "number", entity: e, decimals: 1, suffix: "°", x: 160, y: 30, w: 320, h: 128 },
    { type: "text", value: "room climate", size: 30, bold: false, x: 164, y: 170, w: 320, h: 40 },
    { type: "curve", entity: e, x: 490, y: 100, w: 270, h: 86 }] },
  { id: "countdown", title: "Countdown", desc: "Days until a calendar event", domain: "calendar", make: (e) => [
    { type: "icon", icon: "calendar", x: 32, y: 40, w: 110, h: 110 },
    { type: "number", entity: e, value: "4 days", x: 160, y: 24, w: 340, h: 130 },
    { type: "text", value: "until it happens", size: 30, bold: false, x: 164, y: 166, w: 320, h: 42 }] },
  { id: "door", title: "Door or pet", desc: "Open or closed, and since when", domain: "binary_sensor", make: (e) => [
    { type: "icon", icon: "door", x: 32, y: 44, w: 116, h: 116 },
    { type: "text", entity: e, size: 80, x: 164, y: 30, w: 360, h: 128, replace: { on: "Open", off: "Closed" } },
    { type: "text", entity: e, show: "last_changed", prefix: "since ", size: 30, bold: false, x: 164, y: 170, w: 420, h: 40 }] },
  { id: "bins", title: "Bin day", desc: "Which bin, and how many days", domain: "calendar", make: (e) => [
    { type: "icon", icon: "bin", x: 32, y: 40, w: 110, h: 110 },
    { type: "text", value: "2 days", size: 96, x: 160, y: 24, w: 340, h: 130 },
    { type: "text", entity: e, prefix: "", size: 30, bold: false, x: 164, y: 166, w: 400, h: 42 }] },
  { id: "clock", title: "Clock", desc: "Time and date, very large", domain: null, make: () => clone(SEED.pages.clock.elements) },
  { id: "battery", title: "Battery", desc: "Charge level in a card", domain: "sensor", make: (e) => [
    { type: "box", fill: "outline", radius: 14, thickness: 3, x: 18, y: 14, w: 756, h: 216 },
    { type: "icon", icon: "battery", x: 52, y: 70, w: 110, h: 110 },
    { type: "number", entity: e, suffix: " %", decimals: 0, x: 190, y: 44, w: 360, h: 140 }] },
];

/* ---------- value formatting and element names ---------- */
function valueText(el) {
  if (el.value !== undefined && !el.entity) return el.value;
  if (el.value !== undefined && el.type === "number") return el.value;
  const e = ENT[el.entity];
  if (!e) return (el.prefix || "") + "--" + (el.suffix || "");
  let v = e[1];
  if (el.show === "last_changed") v = "14:02";
  else if (el.replace && el.replace[v] !== undefined) v = el.replace[v];
  else if (el.type === "number" && v !== "" && !isNaN(Number(v))) {
    const d = el.decimals ?? (String(e[1]).includes(".") ? 1 : 0);
    v = Number(v).toFixed(d);
  }
  return (el.prefix || "") + v + (el.suffix || "");
}
const TYPE_NAMES = { number: "Value", text: "Text", icon: "Icon", box: "Card", line: "Divider", curve: "Sparkline", bar: "Gauge" };
const TYPE_ICONS = { number: "value", text: "text", icon: "image", box: "square", line: "line", curve: "wave", bar: "gauge" };
function elName(el) {
  const t = TYPE_NAMES[el.type] || el.type;
  let d = "";
  if (el.entity && ENT[el.entity]) d = ENT[el.entity][0];
  else if (el.value) d = "“" + el.value + "”";
  else if (el.icon) d = ART_NAMES[el.icon] || el.icon;
  return { t, d };
}
const pageTitle = (n) => n.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
function condText(c) {
  if (!c || !c.entity) return "Shows always";
  const e = ENT[c.entity];
  const name = e ? e[0] : c.entity;
  const ops = { eq: "is", ne: "isn't", gt: "is above", lt: "is below" };
  return `Only while ${name} ${ops[c.op] || "is"} ${c.value}`;
}
function condHolds(c) {
  if (!c || !c.entity) return true;
  const e = ENT[c.entity]; if (!e) return false;
  const s = e[1];
  if (c.op === "eq") return s === c.value;
  if (c.op === "ne") return s !== c.value;
  if (c.op === "gt") return Number(s) > Number(c.value);
  if (c.op === "lt") return Number(s) < Number(c.value);
  return false;
}
function whyHidden(c) {
  const e = ENT[c.entity];
  if (!e) return "Its sensor isn't in Home Assistant";
  return `${condText(c).replace("Only while", "Shows while")}. It's ${e[1]}${e[2] ? " " + e[2] : ""}.`;
}
function slug(s) { return String(s).trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, ""); }

/* ---------- drawing a page ---------- */
const cq = (px) => `calc(${px} * 100cqw / ${W})`;
function drawEl(el) {
  const d = h("div", { class: "pe pe-" + el.type });
  Object.assign(d.style, { left: (el.x / W * 100) + "%", top: (el.y / H * 100) + "%", width: (el.w / W * 100) + "%", height: (el.h / H * 100) + "%" });
  if (el.type === "number" || el.type === "text") {
    const auto = el.type === "number" ? el.h * 0.86 : el.h * 0.8;
    const size = el.size || auto;
    d.style.fontSize = cq(size);
    d.style.fontWeight = el.bold === false ? "400" : "700";
    d.style.justifyContent = el.align === "center" ? "center" : el.align === "right" ? "flex-end" : "flex-start";
    if (el.valign === "top") d.style.alignItems = "flex-start";
    const span = h("span", { text: valueText(el) });
    if (el.invert) Object.assign(span.style, { background: "var(--ink)", color: "var(--paper)", padding: `${cq(2)} ${cq(10)}`, borderRadius: cq(8) });
    d.append(span);
  } else if (el.type === "icon") {
    d.innerHTML = ART[el.icon] || ART.sun;
  } else if (el.type === "box") {
    const t = el.thickness || 3;
    d.style.borderRadius = cq(el.radius || 0);
    if (el.fill === "black") d.style.background = "var(--ink)";
    else if (el.fill === "white") d.style.background = "var(--paper)";
    else d.style.boxShadow = `inset 0 0 0 ${cq(t)} var(--ink)`;
  } else if (el.type === "line") {
    d.style.background = "var(--ink)";
  } else if (el.type === "curve") {
    d.innerHTML = '<svg viewBox="0 0 100 40" preserveAspectRatio="none"><polyline fill="none" stroke="currentColor" stroke-width="3" vector-effect="non-scaling-stroke" stroke-linejoin="round" points="0,38 10,37 20,33 30,24 40,14 50,8 60,6 70,11 80,20 90,31 100,37"/></svg>';
  }
  return d;
}
function drawPage(page, name, opts = {}) {
  const p = h("div", { class: "panel" + (opts.editable ? " editable" : "") });
  const ink = h("div", { class: "ink" });
  (page.elements || []).forEach((el) => ink.append(drawEl(el)));
  const f = h("div", { class: "footer" }, h("span", { class: "fp on", text: name || "" }), h("span", { class: "clock", text: "14:05" }));
  p.append(ink, f);
  return p;
}
function thumb(page, name) {
  const t = drawPage(page, name);
  t.classList.add("thumb");
  t.setAttribute("aria-hidden", "true");
  return t;
}

/* ---------- shared clipboard: survives page switches, reloads, windows ---------- */
let CLIP = null;
try { CLIP = JSON.parse(store.get("epaper-mock-clip") || "null"); } catch (_) {}
function setClip(c) { CLIP = c; store.set("epaper-mock-clip", JSON.stringify(c)); }

/* ---------- a fake server with a version check, for the two-window lab ---------- */
class Server {
  constructor(spec) { this.spec = clone(spec); this.etag = 1; }
  get() { return { spec: clone(this.spec), etag: this.etag }; }
  put(spec, ifMatch) {
    if (ifMatch !== undefined && ifMatch !== this.etag) return { status: 409, spec: clone(this.spec), etag: this.etag };
    this.spec = clone(spec); this.etag++;
    return { status: 200, etag: this.etag };
  }
}

/* ================================================================
   The mock editor
   ================================================================ */
let ACTIVE = null;

class Mock {
  constructor(host, variant, opt = {}) {
    this.host = host; this.v = variant; this.opt = opt;
    this.server = opt.server || new Server(SEED);
    const got = this.server.get();
    this.s = got.spec; this.base = clone(got.spec); this.etag = got.etag;
    this.cur = opt.page || "solar";
    this.sel = [];
    this.hist = [JSON.stringify(this.s)]; this.hpos = 0;
    this.dirty = false; this.sentAt = "14:05";
    this.pickMode = opt.pickMode || "smallest";
    this.screen = variant === "c" ? "home" : "editor";
    this.layersOpen = store.get("epaper-mock-layers") === "1";
    this.inspTab = "inspector";
    this.inspOpen = false; this.navOpen = false;
    this.lastClick = null; this.stack = null; this.hover = -1; this.hoverRow = -1;
    this.asleep = false;
    this.build();
  }

  /* state */
  page() { return this.s.pages[this.cur]; }
  els() { return this.page().elements; }
  commit(kind) {
    const now = Date.now();
    const json = JSON.stringify(this.s);
    if (kind && this.lastKind === kind && now - this.lastAt < 900 && this.hpos === this.hist.length - 1 && this.hpos > 0) {
      this.hist[this.hpos] = json;
    } else {
      this.hist = this.hist.slice(0, this.hpos + 1);
      this.hist.push(json);
      if (this.hist.length > 60) this.hist.shift();
      this.hpos = this.hist.length - 1;
    }
    this.lastKind = kind; this.lastAt = now;
    this.dirty = true;
    if (this.opt.onChange) this.opt.onChange(this);
  }
  restore(i) {
    if (i < 0 || i >= this.hist.length) return;
    this.hpos = i; this.s = JSON.parse(this.hist[i]);
    if (!this.s.pages[this.cur]) this.cur = Object.keys(this.s.pages)[0];
    this.sel = this.sel.filter((k) => k < this.els().length);
    this.dirty = true; this.render();
  }
  undo() { this.restore(this.hpos - 1); }
  redo() { this.restore(this.hpos + 1); }

  /* ---------- building ---------- */
  build() {
    this.win = h("div", { class: "win v-" + this.v, tabindex: "-1" });
    this.tb = h("div", { class: "tb", role: "toolbar", "aria-label": "Editor" });
    this.bannerEl = h("div");
    this.body = h("div", { class: "body" });
    this.toastEl = h("div", { class: "toast", role: "status" }, h("span"), h("button", { hidden: true }));
    this.live = h("div", { class: "sr", "aria-live": "polite" });
    this.layer = h("div", { class: "layer" });
    this.win.append(this.tb, this.bannerEl, this.body, this.toastEl, this.live, this.layer);
    this.host.replaceChildren(this.win);
    this.win.addEventListener("pointerdown", () => { ACTIVE = this; }, true);
    this.win.addEventListener("focusin", () => { ACTIVE = this; });
    this.render();
  }

  render() {
    this.renderToolbar();
    this.body.replaceChildren();
    this.body.className = "body";
    if (this.v === "c" && this.screen === "home") {
      this.body.classList.add("home");
      this.body.append(this.renderHome());
    } else {
      if (this.v === "c") this.body.classList.add("editor");
      if (this.v === "a") this.body.append(this.renderNav());
      this.body.append(this.renderStage());
      if (this.v === "lab") this.body.append(this.renderLabSide());
      else this.body.append(this.renderInspector());
    }
    this.renderBanner();
  }

  /* ---------- toolbar ---------- */
  renderToolbar() {
    const tb = this.tb; tb.replaceChildren();
    const b = (ic, label, on, extra = {}) => h("button", { class: "btn icon", "aria-label": label, title: label, onclick: on, ...extra }, icon(ic));
    if (this.v === "lab") {
      tb.append(h("span", { class: "title", text: pageTitle(this.cur) }), h("span", { class: "spacer" }),
        b("undo", "Undo", () => this.undo(), { disabled: this.hpos <= 0 }), b("redo", "Redo", () => this.redo(), { disabled: this.hpos >= this.hist.length - 1 }));
      if (this.opt.sendable) tb.append(this.sendButton());
      return;
    }
    if (this.v === "c" && this.screen === "home") {
      tb.append(h("span", { class: "title", text: "E-paper panel" }), h("span", { class: "spacer" }), this.nowPill(),
        b("gear", "Settings", () => this.openSettings()),
        h("button", { class: "btn tinted", onclick: (e) => this.openPresets(e.currentTarget) }, icon("plus"), h("span", { class: "hide-phone", text: "New page" })));
      return;
    }
    if (this.v === "a") tb.append(h("button", { class: "btn icon show-phone", "aria-label": "Pages and layers", onclick: () => { this.navOpen = !this.navOpen; this.render(); } }, icon("sidebar")));
    if (this.v === "c") tb.append(h("button", { class: "btn", onclick: () => { this.screen = "home"; this.sel = []; this.render(); } }, icon("back"), h("span", { text: "Pages" })));
    tb.append(h("span", { class: "title", text: pageTitle(this.cur) }));
    tb.append(b("undo", "Undo", () => this.undo(), { disabled: this.hpos <= 0 }), b("redo", "Redo", () => this.redo(), { disabled: this.hpos >= this.hist.length - 1 }));
    tb.append(h("span", { class: "sep hide-phone" }));
    tb.append(h("button", { class: "btn tinted", "aria-label": "Insert an element or a sensor", onclick: (e) => this.openInsert(e.currentTarget) }, icon("plus"), h("span", { class: "hide-phone", text: "Insert" })));
    tb.append(h("span", { class: "spacer" }));
    if (this.v !== "c") { tb.append(this.nowPill()); tb.append(b("gear", "Settings", () => this.openSettings())); }
    tb.append(this.sendButton());
  }
  sendButton() {
    const label = this.dirty ? "Send to panel. Some changes aren't on the panel yet" : "Send to panel";
    return h("button", { class: "btn primary", "aria-label": label, title: label, onclick: () => this.send() },
      this.dirty ? h("span", { class: "dot", "aria-hidden": "true" }) : null,
      h("span", { class: "hide-phone", text: "Send to panel" }), h("span", { class: "show-phone" }, icon("send")));
  }
  nowPill() {
    const wait = this.dirty;
    const text = this.asleep ? "Asleep" : wait ? "Not sent yet" : "Up to date";
    return h("button", { class: "statuspill", onclick: (e) => this.openNow(e.currentTarget), "aria-label": "Now on the panel: " + text },
      h("span", { class: "led" + (wait ? " wait" : "") }), h("span", { class: "hide-phone", text }));
  }
  renderBanner() {
    this.bannerEl.replaceChildren();
    if (this.v === "lab" && this.opt.server && this.server.etag !== this.etag) {
      this.bannerEl.append(h("div", { class: "banner", role: "status" }, icon("info", "sm"), h("span", { text: "The other window sent changes. They'll merge when you send." })));
    }
  }

  /* ---------- page lists ---------- */
  slots() {
    const rot = this.s.rotation.map((n, i) => ({ n, i, repeat: this.s.rotation.indexOf(n) < i }));
    const out = Object.keys(this.s.pages).filter((n) => !this.s.rotation.includes(n) && this.s.pages[n].tier !== "alert");
    const alerts = Object.keys(this.s.pages).filter((n) => this.s.pages[n].tier === "alert");
    return { rot, out, alerts };
  }
  pageSub(n, repeat) {
    const p = this.s.pages[n];
    if (repeat) return "Shown again";
    if (p.tier === "alert") return `Alert, holds ${p.hold || 10} min`;
    if (p.tier === "when") return (condHolds(p.cond) ? "Showing now · " : "Hidden now · ") + condText(p.cond).replace("Only while ", "while ");
    return "Shows always";
  }
  openPage(n) {
    if (!this.s.pages[n]) return;
    this.cur = n; this.sel = []; this.stack = null; this.lastClick = null;
    if (this.v === "c") this.screen = "editor";
    this.navOpen = false;
    this.render();
    this.say(`Editing ${pageTitle(n)}`);
  }
  moveSlot(from, to) {
    const r = this.s.rotation; const [x] = r.splice(from, 1); r.splice(to > from ? to - 1 : to, 0, x);
    this.commit(); this.render();
    this.toast(`Moved ${pageTitle(x)} in the rotation.`, "Undo", () => this.undo());
  }

  /* Drag to reorder, with an insertion line; a plain click opens. */
  reorderable(list, items, axis, onMove, onClick) {
    items.forEach((it, idx) => {
      it.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        const start = { x: e.clientX, y: e.clientY }; let drag = false, target = idx;
        const rects = items.map((x) => x.getBoundingClientRect());
        const lr = list.getBoundingClientRect();
        let mark = null;
        const thr = e.pointerType === "touch" ? 8 : 4;
        try { it.setPointerCapture(e.pointerId); } catch (_) {}
        const move = (ev) => {
          const dx = ev.clientX - start.x, dy = ev.clientY - start.y;
          if (!drag && Math.hypot(dx, dy) < thr) return;
          if (!drag) { drag = true; it.classList.add("lifted"); mark = h("div", { class: "insert-mark" }); list.append(mark); }
          it.style.transform = axis === "x" ? `translateX(${dx}px) scale(1.04)` : `translateY(${dy}px)`;
          const pos = axis === "x" ? ev.clientX : ev.clientY;
          target = rects.filter((r) => (axis === "x" ? r.left + r.width / 2 : r.top + r.height / 2) < pos).length;
          const r = rects[Math.min(target, rects.length - 1)];
          const before = target < rects.length;
          if (axis === "x") Object.assign(mark.style, { left: ((before ? r.left - 6 : r.right + 4) - lr.left + list.scrollLeft) + "px", top: (r.top - lr.top) + "px", width: "3px", height: (r.height * 0.62) + "px" });
          else Object.assign(mark.style, { top: ((before ? r.top - 2 : r.bottom) - lr.top + list.scrollTop) + "px", left: "8px", right: "8px", height: "3px" });
        };
        const up = () => {
          it.removeEventListener("pointermove", move); it.removeEventListener("pointerup", up); it.removeEventListener("pointercancel", up);
          if (mark) mark.remove();
          it.style.transform = ""; it.classList.remove("lifted");
          if (!drag) { onClick(idx); return; }
          if (target !== idx && target !== idx + 1) onMove(idx, target);
        };
        it.addEventListener("pointermove", move); it.addEventListener("pointerup", up); it.addEventListener("pointercancel", up);
      });
      it.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(idx); }
        if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowLeft") && idx > 0) { e.preventDefault(); onMove(idx, idx - 1); }
        if (e.altKey && (e.key === "ArrowDown" || e.key === "ArrowRight") && idx < items.length - 1) { e.preventDefault(); onMove(idx, idx + 2); }
      });
    });
  }

  renderStrip() {
    const strip = h("div", { class: "strip", role: "listbox", "aria-label": "Rotation. Drag to reorder" });
    const { rot, out, alerts } = this.slots();
    strip.append(h("div", { class: "lead" }, "Every", h("b", { text: this.s.rotate_seconds + " s" })));
    const items = rot.map(({ n, repeat }) => {
      const p = this.s.pages[n];
      const hidden = p.tier === "when" && !condHolds(p.cond);
      return h("button", { class: "tile" + (hidden ? " hidden-now" : "") + (repeat ? " repeat" : ""), role: "option", "aria-current": n === this.cur && !repeat ? "page" : null, "aria-label": `${pageTitle(n)}. ${this.pageSub(n, repeat)}` },
        thumb(p, n), h("span", { class: "tname" }, h("span", { text: pageTitle(n) }), p.tier === "when" ? h("span", { class: "badge when", text: "when" }) : null),
        h("span", { class: "tsub", text: this.pageSub(n, repeat) }));
    });
    items.forEach((t) => strip.append(t));
    this.reorderable(strip, items, "x", (f, t) => this.moveSlot(f, t), (i) => this.openPage(rot[i].n));
    strip.append(h("button", { class: "addtile", "aria-label": "New page", title: "New page", onclick: (e) => this.openPresets(e.currentTarget) }, icon("plus")));
    if (out.length) {
      strip.append(h("span", { class: "groupsep" }), h("span", { class: "grouplab", text: "Not in rotation" }));
      out.forEach((n) => strip.append(h("button", { class: "tile", "aria-current": n === this.cur ? "page" : null, onclick: () => this.openPage(n) }, thumb(this.s.pages[n], n), h("span", { class: "tname", text: pageTitle(n) }), h("span", { class: "tsub", text: "Not in rotation" }))));
    }
    if (alerts.length) {
      strip.append(h("span", { class: "groupsep" }), h("span", { class: "grouplab", text: "Alerts" }));
      alerts.forEach((n) => strip.append(h("button", { class: "tile", "aria-current": n === this.cur ? "page" : null, onclick: () => this.openPage(n) }, thumb(this.s.pages[n], n), h("span", { class: "tname" }, h("span", { text: pageTitle(n) }), h("span", { class: "badge alert", text: "alert" })), h("span", { class: "tsub", text: this.pageSub(n) }))));
    }
    return strip;
  }

  pageRows(compact) {
    const frag = [];
    const { rot, out, alerts } = this.slots();
    const list = h("div", { class: compact ? "navlist" : "list", role: "listbox", "aria-label": "Rotation. Drag to reorder" });
    const row = (n, sub, current, dim) => h("button", { class: "row" + (dim ? " dim" : ""), role: "option", "aria-current": current ? "page" : null, "aria-label": `${pageTitle(n)}. ${sub}` },
      h("span", { class: "rthumb" }, thumb(this.s.pages[n], n)),
      h("span", { class: "rtext" }, h("span", { class: "rmain", text: pageTitle(n) }), h("span", { class: "rsub", text: sub })),
      h("span", { class: "grip" }, icon("grip", "sm")));
    const items = rot.map(({ n, repeat }) => {
      const p = this.s.pages[n];
      return row(n, this.pageSub(n, repeat), n === this.cur && !repeat && this.screen !== "home", (p.tier === "when" && !condHolds(p.cond)) || repeat);
    });
    items.forEach((r) => list.append(r));
    this.reorderable(list, items, "y", (f, t) => this.moveSlot(f, t), (i) => this.openPage(rot[i].n));
    frag.push({ label: `In rotation · every ${this.s.rotate_seconds} s`, list });
    if (out.length) {
      const l2 = h("div", { class: compact ? "navlist" : "list" });
      out.forEach((n) => { const r = row(n, "Not in rotation", n === this.cur && this.screen !== "home", true); r.onclick = () => this.openPage(n); l2.append(r); });
      frag.push({ label: "Not in rotation", list: l2 });
    }
    if (alerts.length) {
      const l3 = h("div", { class: compact ? "navlist" : "list" });
      alerts.forEach((n) => { const r = row(n, this.pageSub(n), n === this.cur && this.screen !== "home"); r.onclick = () => this.openPage(n); l3.append(r); });
      frag.push({ label: "Alerts", list: l3 });
    }
    return frag;
  }

  renderNav() {
    const nav = h("div", { class: "nav" + (this.navOpen ? " open" : "") });
    nav.append(this.nowCard());
    const pages = h("div", { class: "navsec pages" }, h("div", { class: "navhead" }, h("span", { text: "Pages" }), h("button", { class: "btn icon", "aria-label": "New page", title: "New page", onclick: (e) => this.openPresets(e.currentTarget) }, icon("plus", "sm"))));
    const scroll = h("div", { class: "navlist", style: { flex: "1", overflowY: "auto" } });
    this.pageRows(true).forEach(({ label, list }) => { scroll.append(h("div", { class: "sub", text: label }), list); });
    pages.append(scroll);
    const layers = h("div", { class: "navsec layers" }, h("div", { class: "navhead" }, h("span", { text: "Layers" }), h("span", { class: "muted", text: "front at the top", style: { fontWeight: "400", fontSize: "11px" } })));
    layers.append(this.layerList());
    nav.append(pages, layers);
    return nav;
  }
  nowCard() {
    const live = this.liveCount();
    return h("button", { class: "nowcard", onclick: (e) => this.openNow(e.currentTarget) },
      h("span", { class: "l1" }, h("span", { class: "led" + (this.dirty ? " wait" : "") }), h("span", { text: this.asleep ? "Asleep" : this.dirty ? "Not sent yet" : "Up to date" })),
      h("span", { class: "l2", text: `${live} pages rotating · sent ${this.sentAt}` }));
  }
  liveCount() { return [...new Set(this.s.rotation)].filter((n) => { const p = this.s.pages[n]; return p && (p.tier !== "when" || condHolds(p.cond)); }).length; }

  renderHome() {
    const wrap = h("div", { class: "home-inner" });
    const live = this.liveCount();
    wrap.append(h("button", { class: "hero", onclick: (e) => this.openNow(e.currentTarget) },
      h("span", { class: "big" }, h("span", { class: "led" + (this.dirty ? " wait" : "") }), h("span", { text: this.asleep ? "The panel is asleep" : this.dirty ? "Some changes aren't on the panel yet" : "The panel is up to date" })),
      h("span", { class: "muted", text: `${live} pages rotating, ${this.s.rotate_seconds} s each. Last sent at ${this.sentAt}. Quiet hours 23:00 to 07:00.` })));
    this.pageRows(false).forEach(({ label, list }) => wrap.append(h("div", { class: "grp" }, h("div", { class: "glab" }, h("span", { text: label })), list)));
    return wrap;
  }

  /* ---------- stage and canvas ---------- */
  renderStage() {
    const stage = h("div", { class: "stage" });
    const bar = h("div", { class: "canvasbar" });
    const p = this.page();
    bar.append(h("span", { class: "crumb", text: p.tier === "when" ? condText(p.cond) : p.tier === "alert" ? "Alert page" : "Shows always" }), h("span", { class: "spacer", style: { flex: "1" } }));
    if (this.v === "b") bar.append(h("button", { class: "btn", "aria-pressed": this.layersOpen ? "true" : "false", onclick: () => this.toggleLayers() }, icon("layers", "sm"), h("span", { text: "Layers" })));
    stage.append(bar);
    const area = h("div", { class: "canvasarea" });
    const dev = h("div", { class: "device" });
    this.panel = drawPage(p, this.cur, { editable: true });
    this.panel.setAttribute("role", "application");
    this.panel.setAttribute("aria-label", `Canvas for ${pageTitle(this.cur)}. Click to select, click again to select what's underneath.`);
    this.ov = h("div", { class: "ov" });
    this.panel.append(this.ov);
    this.wireCanvas(this.panel);
    dev.append(this.panel); area.append(dev); stage.append(area);
    if (!this.els().length) area.append(this.emptyCanvas());
    if (this.v === "b" && this.layersOpen) {
      area.classList.add("withdock");
      area.append(h("div", { class: "layersdock", role: "region", "aria-label": "Layers" }, h("div", { class: "navhead" }, h("span", { text: "Layers" }), h("span", { class: "muted", text: "front at the top", style: { fontWeight: "400", fontSize: "11px" } })), this.layerList()));
    }
    if (this.v === "b") stage.append(this.renderStrip());
    this.drawOverlays();
    return stage;
  }
  emptyCanvas() {
    return h("div", { style: { position: "absolute", inset: "0", display: "grid", placeItems: "center", pointerEvents: "none" } },
      h("div", { style: { pointerEvents: "auto", textAlign: "center", background: "var(--surface)", padding: "14px 18px", borderRadius: "12px", boxShadow: "var(--shadow-pop)" } },
        h("div", { style: { fontWeight: "600" }, text: "This page is empty" }),
        h("div", { class: "muted", style: { fontSize: "12.5px", margin: "2px 0 10px" }, text: "Insert a sensor value, text or an icon." }),
        h("button", { class: "btn primary", onclick: (e) => this.openInsert(e.currentTarget) }, icon("plus", "sm"), "Insert")));
  }
  toggleLayers() {
    this.layersOpen = !this.layersOpen; store.set("epaper-mock-layers", this.layersOpen ? "1" : "0");
    this.render();
  }

  /* Hit testing: everything under the point, in picking order. */
  hitsAt(p) {
    const out = [];
    this.els().forEach((el, i) => {
      const tol = el.type === "line" ? 6 : 2;
      if (p.x >= el.x - tol && p.x <= el.x + el.w + tol && p.y >= el.y - tol && p.y <= el.y + el.h + tol) out.push(i);
    });
    if (this.pickMode === "smallest") out.sort((a, b) => { const A1 = this.els()[a], B1 = this.els()[b]; return (A1.w * A1.h) - (B1.w * B1.h) || b - a; });
    else out.sort((a, b) => b - a);
    return out;
  }
  toPanel(e) {
    const r = this.panel.getBoundingClientRect();
    return { x: (e.clientX - r.left) * W / r.width, y: (e.clientY - r.top) * H / r.height, scale: W / r.width };
  }

  wireCanvas(panel) {
    panel.addEventListener("contextmenu", (e) => { e.preventDefault(); this.openContext(e); });
    panel.addEventListener("pointermove", (e) => {
      if (this.press) return;
      const hits = this.hitsAt(this.toPanel(e));
      const hv = hits.length ? hits[0] : -1;
      if (hv !== this.hover) { this.hover = hv; this.drawOverlays(); }
    });
    panel.addEventListener("pointerleave", () => { if (!this.press && this.hover !== -1) { this.hover = -1; this.drawOverlays(); } });
    panel.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      const hd = e.target.closest(".hd");
      const p = this.toPanel(e);
      try { panel.setPointerCapture(e.pointerId); } catch (_) {}
      if (hd) { this.press = { mode: "size", corner: hd.dataset.c, sx: e.clientX, sy: e.clientY, scale: p.scale, orig: clone(this.els()[this.sel[0]]), dragging: true, i: this.sel[0] }; return; }
      const hits = this.hitsAt(p);
      this.press = { mode: "move", sx: e.clientX, sy: e.clientY, p, scale: p.scale, hits, shift: e.shiftKey, alt: e.altKey, dragging: false, thr: e.pointerType === "touch" ? 8 : 4 };
      if (this.opt.legacyClick && hits.length) this.beginDrag(hits[0]);
    });
    panel.addEventListener("pointermove", (e) => {
      const pr = this.press; if (!pr) return;
      const dx = (e.clientX - pr.sx) * pr.scale, dy = (e.clientY - pr.sy) * pr.scale;
      if (pr.mode === "size") return this.resizeTo(pr, dx, dy, e.altKey);
      if (!pr.dragging) {
        if (Math.hypot(e.clientX - pr.sx, e.clientY - pr.sy) < pr.thr) return;
        if (!pr.hits.length) return;
        const selUnder = pr.hits.find((i) => this.sel.includes(i));
        this.beginDrag(selUnder !== undefined ? selUnder : pr.hits[0]);
      }
      this.dragTo(pr, dx, dy, e.altKey);
    });
    const up = () => {
      const pr = this.press; if (!pr) return;
      this.press = null;
      this.ov.querySelectorAll(".guide").forEach((g) => g.remove());
      if (pr.dragging) {
        if (this.opt.legacyClick && !pr.moved && Math.random() < 0.7) this.dragTo(pr, 0, 0, true);
        if (pr.moved) { this.commit(); this.say("Moved"); }
        this.render(); return;
      }
      this.clickAt(pr);
    };
    panel.addEventListener("pointerup", up);
    panel.addEventListener("pointercancel", () => { this.press = null; this.render(); });
  }

  beginDrag(i) {
    const pr = this.press;
    if (!this.sel.includes(i)) { this.sel = pr.shift ? [...this.sel, i] : [i]; }
    pr.dragging = true; pr.moved = false;
    pr.orig = this.sel.map((k) => ({ k, x: this.els()[k].x, y: this.els()[k].y }));
    this.stack = null;
    this.drawOverlays();
  }
  dragTo(pr, dx, dy, noSnap) {
    if (this.opt.legacyClick) { dx = Math.round(dx + (Math.random() < 0.5 ? 1 : -1)); dy = Math.round(dy + (Math.random() < 0.5 ? 1 : 0)); }
    if (!dx && !dy && !this.opt.legacyClick) return;
    pr.moved = true;
    const els = this.els();
    const xs = pr.orig.map((o) => o.x + dx), ys = pr.orig.map((o) => o.y + dy);
    let bx = Math.min(...xs), by = Math.min(...ys);
    const bw = Math.max(...pr.orig.map((o) => o.x + dx + els[o.k].w)) - bx, bh = Math.max(...pr.orig.map((o) => o.y + dy + els[o.k].h)) - by;
    let sx = 0, sy = 0; const guides = [];
    if (!noSnap) {
      const tx = [MARGIN, W / 2, W - MARGIN], ty = [24, FOOT / 2, FOOT];
      els.forEach((o, j) => { if (!this.sel.includes(j)) { tx.push(o.x, o.x + o.w / 2, o.x + o.w); ty.push(o.y, o.y + o.h / 2, o.y + o.h); } });
      let best = SNAP + 0.1;
      for (const [v, off] of [[bx, 0], [bx + bw / 2, bw / 2], [bx + bw, bw]]) for (const t of tx) if (Math.abs(v - t) < best) { best = Math.abs(v - t); sx = t - v; guides[0] = t; }
      best = SNAP + 0.1;
      for (const [v] of [[by], [by + bh / 2], [by + bh]]) for (const t of ty) if (Math.abs(v - t) < best) { best = Math.abs(v - t); sy = t - v; guides[1] = t; }
    }
    pr.orig.forEach((o) => {
      const el = els[o.k];
      el.x = Math.round(Math.max(0, Math.min(W - el.w, o.x + dx + sx)));
      el.y = Math.round(Math.max(0, Math.min(H - el.h, o.y + dy + sy)));
    });
    this.repaintInk();
    this.drawOverlays(guides);
    if (this.opt.onNudge) this.opt.onNudge(this);
  }
  resizeTo(pr, dx, dy) {
    const el = this.els()[pr.i], o = pr.orig; pr.moved = true;
    let { x, y, w, h: hh } = o;
    if (pr.corner.includes("e")) w = o.w + dx; if (pr.corner.includes("s")) hh = o.h + dy;
    if (pr.corner.includes("w")) { x = o.x + dx; w = o.w - dx; } if (pr.corner.includes("n")) { y = o.y + dy; hh = o.h - dy; }
    if (w < 16) { if (pr.corner.includes("w")) x -= 16 - w; w = 16; }
    if (hh < 8) { if (pr.corner.includes("n")) y -= 8 - hh; hh = 8; }
    Object.assign(el, { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(hh) });
    this.repaintInk(); this.drawOverlays();
  }
  repaintInk() {
    const ink = this.panel.querySelector(".ink");
    ink.replaceChildren(...this.els().map(drawEl));
  }

  clickAt(pr) {
    const hits = pr.hits;
    if (!hits.length) {
      this.sel = []; this.stack = null; this.lastClick = null;
      this.render(); this.say(`Nothing selected. The inspector shows the page ${pageTitle(this.cur)}.`); return;
    }
    let idx = 0;
    const same = this.lastClick && Math.hypot(pr.sx - this.lastClick.x, pr.sy - this.lastClick.y) < 5 && this.lastClick.sig === hits.join(",");
    if (this.pickMode === "today") idx = 0;
    else if (pr.alt) idx = Math.min(1, hits.length - 1);
    else if (same) idx = (this.lastClick.idx + 1) % hits.length;
    const picked = hits[idx];
    if (pr.shift) {
      this.sel = this.sel.includes(picked) ? this.sel.filter((k) => k !== picked) : [...this.sel, picked];
    } else this.sel = [picked];
    this.lastClick = { x: pr.sx, y: pr.sy, sig: hits.join(","), idx };
    const { t, d } = elName(this.els()[picked]);
    if (hits.length > 1 && this.pickMode !== "today") {
      this.stack = { hits, idx, p: pr.p, until: Date.now() + 1800, fresh: true };
      clearTimeout(this.stackT); this.stackT = setTimeout(() => { this.stack = null; this.drawOverlays(); }, 1800);
    } else this.stack = null;
    this.render();
    const where = hits.length > 1 && this.pickMode !== "today" ? `, ${idx + 1} of ${hits.length} under the pointer` : "";
    this.say(`Selected ${t} ${d}${where}`);
    if (this.opt.onPick) this.opt.onPick(this, { t, d, idx, n: hits.length, mode: this.pickMode });
  }

  drawOverlays(guides) {
    if (!this.ov) return;
    this.ov.replaceChildren();
    const box = (el, cls) => {
      const b = h("div", { class: "ovbox " + cls });
      Object.assign(b.style, { left: (el.x / W * 100) + "%", top: (el.y / H * 100) + "%", width: (el.w / W * 100) + "%", height: (el.h / H * 100) + "%" });
      this.ov.append(b); return b;
    };
    const els = this.els();
    if (this.stack) this.stack.hits.forEach((k) => { if (!this.sel.includes(k) && els[k]) box(els[k], "stk"); });
    const hv = this.hoverRow >= 0 ? this.hoverRow : this.hover;
    if (hv >= 0 && !this.sel.includes(hv) && els[hv] && !this.press) box(els[hv], "hov");
    this.sel.forEach((k) => {
      if (!els[k]) return;
      const picking = this.stack && this.stack.fresh && this.stack.hits[this.stack.idx] === k;
      const b = box(els[k], this.sel.length > 1 ? "sel multi" : picking ? "pick" : "sel");
      if (this.sel.length === 1 && !this.press?.dragging) ["nw", "ne", "sw", "se"].forEach((c) => b.append(h("span", { class: "hd " + c, data: { c } })));
    });
    if (this.stack && this.stack.fresh) {
      const k = this.stack.hits[this.stack.idx]; const el = els[k];
      if (el) {
        const { t, d } = elName(el);
        const chip = h("div", { class: "pickchip", text: `${this.stack.idx + 1} of ${this.stack.hits.length} · ${t}${d ? " " + d : ""}` });
        Object.assign(chip.style, { left: Math.max(12, Math.min(88, this.stack.p.x / W * 100)) + "%", top: Math.max(14, this.stack.p.y / H * 100) + "%" });
        this.ov.append(chip);
      }
    }
    if (guides) {
      if (guides[0] !== undefined) this.ov.append(h("div", { class: "guide v", style: { left: (guides[0] / W * 100) + "%" } }));
      if (guides[1] !== undefined) this.ov.append(h("div", { class: "guide h", style: { top: (guides[1] / H * 100) + "%" } }));
    }
  }

  /* ---------- layers ---------- */
  layerList() {
    const list = h("div", { class: "navlist", role: "listbox", "aria-label": "Layers, front first. Drag to reorder", style: { flex: "1", overflowY: "auto" } });
    const els = this.els();
    if (!els.length) { list.append(h("div", { class: "empty-note", text: "No layers yet." })); return list; }
    const order = els.map((_, i) => i).reverse();
    const rows = order.map((i) => {
      const { t, d } = elName(els[i]);
      const r = h("button", { class: "row", role: "option", "aria-selected": this.sel.includes(i) ? "true" : "false", "aria-label": `${t} ${d}` },
        h("span", { class: "glyph" }, icon(TYPE_ICONS[els[i].type] || "square", "sm")),
        h("span", { class: "rtext" }, h("span", { class: "rmain", text: t }), d ? h("span", { class: "rsub", text: d }) : null),
        h("span", { class: "grip" }, icon("grip", "sm")));
      r.addEventListener("pointerenter", () => { this.hoverRow = i; this.drawOverlays(); });
      r.addEventListener("pointerleave", () => { this.hoverRow = -1; this.drawOverlays(); });
      return r;
    });
    rows.forEach((r) => list.append(r));
    this.reorderable(list, rows, "y", (from, to) => {
      const arr = els; const src = order[from];
      const newOrder = order.slice(); const [m] = newOrder.splice(from, 1); newOrder.splice(to > from ? to - 1 : to, 0, m);
      const items = newOrder.slice().reverse().map((k) => arr[k]);
      const selEls = this.sel.map((k) => arr[k]);
      this.page().elements = items;
      this.sel = selEls.map((e) => items.indexOf(e));
      this.commit(); this.render();
      this.say(`Moved ${elName(arr[src]).t} in the layer order`);
    }, (k) => { this.sel = [order[k]]; this.stack = null; this.render(); });
    return list;
  }

  /* ---------- order, align, clipboard ---------- */
  reorderSel(where) {
    if (this.sel.length !== 1) return;
    const arr = this.els(), i = this.sel[0], el = arr[i];
    arr.splice(i, 1);
    const j = where === "front" ? arr.length : where === "back" ? 0 : where === "fwd" ? Math.min(arr.length, i + 1) : Math.max(0, i - 1);
    arr.splice(j, 0, el); this.sel = [j];
    this.commit(); this.render();
    this.say({ front: "Brought to front", back: "Sent to back", fwd: "Brought forward", bwd: "Sent backward" }[where]);
  }
  copy(cut) {
    if (!this.sel.length) return;
    const items = this.sel.slice().sort((a, b) => a - b).map((k) => clone(this.els()[k]));
    setClip({ from: this.cur, items });
    if (cut) { this.page().elements = this.els().filter((_, k) => !this.sel.includes(k)); this.sel = []; this.commit(); this.render(); }
    this.toast(`${cut ? "Cut" : "Copied"} ${items.length === 1 ? elName(items[0]).t.toLowerCase() : items.length + " elements"}. Paste on any page to put ${items.length === 1 ? "it" : "them"} in the same place.`);
  }
  paste() {
    if (!CLIP || !CLIP.items) { this.toast("Nothing to paste yet. Copy an element first."); return; }
    const els = this.els();
    const clash = CLIP.items.every((c) => els.some((e) => e.x === c.x && e.y === c.y && e.type === c.type));
    const items = CLIP.items.map((c) => { const n = clone(c); if (clash) { n.x = Math.min(W - n.w, n.x + 12); n.y = Math.min(H - n.h, n.y + 12); } return n; });
    els.push(...items);
    this.sel = items.map((_, k) => els.length - items.length + k);
    this.commit(); this.render();
    const where = clash ? "slightly offset, since the originals are here" : CLIP.from && CLIP.from !== this.cur ? `in the same place as on ${pageTitle(CLIP.from)}` : "in the same place";
    this.toast(`Pasted ${items.length === 1 ? "1 element" : items.length + " elements"} ${where}.`, "Undo", () => this.undo());
  }
  duplicate() {
    if (!this.sel.length) return;
    const els = this.els();
    const items = this.sel.slice().sort((a, b) => a - b).map((k) => { const n = clone(els[k]); n.x = Math.min(W - n.w, n.x + 12); n.y = Math.min(H - n.h, n.y + 12); return n; });
    els.push(...items); this.sel = items.map((_, k) => els.length - items.length + k);
    this.commit(); this.render();
  }
  remove() {
    if (!this.sel.length) return;
    const n = this.sel.length;
    this.page().elements = this.els().filter((_, k) => !this.sel.includes(k));
    this.sel = []; this.commit(); this.render();
    this.toast(`Deleted ${n === 1 ? "1 element" : n + " elements"}.`, "Undo", () => this.undo());
  }
  align(kind) {
    const items = this.sel.map((k) => this.els()[k]);
    if (items.length === 1) {
      const el = items[0];
      if (kind === "ch") el.x = Math.round((W - el.w) / 2);
      if (kind === "cv") el.y = Math.round((FOOT - el.h) / 2);
      if (kind === "full") { el.x = MARGIN; el.w = W - MARGIN * 2; }
    } else {
      const minX = Math.min(...items.map((e) => e.x)), maxR = Math.max(...items.map((e) => e.x + e.w));
      const minY = Math.min(...items.map((e) => e.y)), maxB = Math.max(...items.map((e) => e.y + e.h));
      items.forEach((e) => {
        if (kind === "l") e.x = minX; if (kind === "r") e.x = maxR - e.w; if (kind === "ch") e.x = Math.round((minX + maxR - e.w) / 2);
        if (kind === "t") e.y = minY; if (kind === "b") e.y = maxB - e.h; if (kind === "cv") e.y = Math.round((minY + maxB - e.h) / 2);
      });
    }
    this.commit(); this.render();
  }

  /* ---------- inspector ---------- */
  renderInspector() {
    const insp = h("div", { class: "insp" + (this.inspOpen ? " open" : ""), role: "region", "aria-label": "Inspector" });
    const head = h("div", { class: "insp-head", onclick: (e) => { if (getComputedStyle(insp).position === "absolute" && !e.target.closest("input,button")) { this.inspOpen = !this.inspOpen; insp.classList.toggle("open", this.inspOpen); } } }, h("span", { class: "grab", "aria-hidden": "true" }));
    const body = h("div", { class: "insp-body" });
    insp.append(head);
    if (this.v === "c") {
      const seg = h("div", { class: "seg", role: "tablist" },
        ...[["inspector", "Inspector"], ["layers", "Layers"]].map(([k, l]) => h("button", { role: "tab", "aria-selected": this.inspTab === k ? "true" : "false", onclick: () => { this.inspTab = k; this.render(); } , text: l })));
      insp.append(h("div", { class: "insp-tabs" }, seg));
    }
    insp.append(body);
    const els = this.els();
    if (this.v === "c" && this.inspTab === "layers") {
      head.append(h("span", { class: "ttl", text: "Layers" }));
      body.append(this.layerList());
      return insp;
    }
    if (this.sel.length > 1) this.inspMulti(head, body);
    else if (this.sel.length === 1 && els[this.sel[0]]) this.inspElement(head, body, els[this.sel[0]]);
    else this.inspPage(head, body);
    return insp;
  }
  sec(label, ...kids) { return h("div", { class: "isec" }, label ? h("div", { class: "slab" }, ...[].concat(label)) : null, ...kids); }
  field(label, control, id) {
    if (!control.id && /INPUT|SELECT/.test(control.tagName)) control.id = "f" + Math.random().toString(36).slice(2, 8);
    return h("div", { class: "field" }, h("label", { for: id || control.id, text: label }), control);
  }
  inp(value, onChange, attrs = {}) {
    const id = "f" + Math.random().toString(36).slice(2, 8);
    const i = h("input", { class: "inp", id, value: value ?? "", ...attrs });
    i.addEventListener("change", () => onChange(i.value));
    i.addEventListener("keydown", (e) => { if (e.key === "Enter") i.blur(); });
    return i;
  }
  segc(options, cur, onPick, label) {
    return h("div", { class: "segc", role: "group", "aria-label": label }, ...options.map(([v, l, ic]) => h("button", { "aria-pressed": String(cur === v), onclick: () => onPick(v), "aria-label": ic ? l : null, title: ic ? l : null }, ic ? icon(ic, "sm") : l)));
  }

  inspMulti(head, body) {
    head.append(h("span", { class: "ttl" }, h("span", { class: "kind", text: "Selection" }), `${this.sel.length} elements`));
    body.append(this.sec("Align",
      h("div", { class: "btnrow" }, ...[["l", "Left edges"], ["ch", "Centres"], ["r", "Right edges"]].map(([k, l]) => h("button", { class: "btn", onclick: () => this.align(k), text: l }))),
      h("div", { class: "btnrow", style: { marginTop: "6px" } }, ...[["t", "Tops"], ["cv", "Middles"], ["b", "Bottoms"]].map(([k, l]) => h("button", { class: "btn", onclick: () => this.align(k), text: l })))));
    body.append(this.sec(null, h("div", { class: "btnrow" },
      h("button", { class: "btn", onclick: () => this.copy() }, icon("clip", "sm"), "Copy"),
      h("button", { class: "btn", onclick: (e) => this.openCopyTo(e.currentTarget) }, "Copy to page…")),
      h("div", { class: "btnrow", style: { marginTop: "6px" } }, h("button", { class: "btn", onclick: () => this.duplicate() }, icon("dup", "sm"), "Duplicate"), h("button", { class: "btn danger", onclick: () => this.remove() }, icon("trash", "sm"), "Delete"))));
  }

  inspElement(head, body, el) {
    const { t, d } = elName(el);
    head.append(h("span", { class: "ttl" }, h("span", { class: "kind", text: t }), d || t));
    const set = (k, v, kind) => { if (v === "" || v === undefined) delete el[k]; else el[k] = v; this.commit(kind); this.render(); };
    if (el.type === "number" || el.type === "text") {
      const s = this.sec("Shows");
      if (el.entity) {
        const e = ENT[el.entity] || [el.entity, "?", ""];
        s.append(h("button", { class: "entbtn", "aria-label": `Sensor: ${e[0]}. Change`, onclick: (ev) => this.openEntityPicker(ev.currentTarget, (id) => set("entity", id)) },
          h("span", { style: { minWidth: "0" } }, h("span", { class: "e1", text: e[0] }), h("span", { class: "e2", text: el.entity })), h("span", { class: "ev", text: e[1] + (e[2] ? " " + e[2] : "") })));
        const showSel = h("select", { class: "inp", id: "sh" + this.v },
          ...[["state", "Its value"], ["last_changed", "When it last changed"], ["attribute", "One of its details"], ["days_until", "Days until"]].map(([v, l]) => h("option", { value: v, selected: (el.show || "state") === v, text: l })));
        showSel.onchange = () => set("show", showSel.value === "state" ? "" : showSel.value);
        s.append(this.field("Show", showSel, "sh" + this.v));
        s.append(this.field("Before", this.inp(el.prefix, (v) => set("prefix", v), { placeholder: "nothing" })));
        s.append(this.field("After", this.inp(el.suffix, (v) => set("suffix", v), { placeholder: ENT[el.entity]?.[2] ? " " + ENT[el.entity][2] : "nothing" })));
        if (el.type === "number") s.append(this.field("Decimals", this.inp(el.decimals ?? "", (v) => set("decimals", v === "" ? "" : Number(v)), { type: "number", min: "0", max: "3", placeholder: "auto" })));
      } else {
        s.append(this.field("Text", this.inp(el.value, (v) => set("value", v))));
        s.append(h("button", { class: "btn", style: { marginTop: "2px", color: "var(--accent)", paddingLeft: "0" }, onclick: (ev) => this.openEntityPicker(ev.currentTarget, (id) => { delete el.value; el.entity = id; this.commit(); this.render(); }) }, "Show a sensor instead…"));
      }
      body.append(s);
      const auto = Math.round(el.type === "number" ? el.h * 0.86 : el.h * 0.8);
      const size = el.size || auto;
      const mm = (size * 0.72 * 139.1 / W).toFixed(1);
      const good = mm >= 13;
      const ts = this.sec("Text",
        this.field("Size", this.inp(el.size ?? "", (v) => set("size", v === "" ? "" : Number(v)), { type: "number", min: "8", max: "200", placeholder: `fits the box (${auto})` })),
        h("div", { class: "legible" + (good ? "" : " bad"), role: "note" }, h("span", { class: "led" }), h("span", { text: `${mm} mm tall from 3 m: ${good ? "easy to read" : "hard to read"}` })),
        h("div", { class: "field" }, h("span", { class: "lab", text: "Weight" }), this.segc([["regular", "Regular"], ["bold", "Bold"]], el.bold === false ? "regular" : "bold", (v) => set("bold", v === "bold" ? "" : false), "Weight")),
        h("div", { class: "field" }, h("span", { class: "lab", text: "Align" }), this.segc([["left", "Left"], ["center", "Centre"], ["right", "Right"]], el.align || "left", (v) => set("align", v === "left" ? "" : v), "Alignment")));
      body.append(ts);
    } else if (el.type === "icon") {
      const grid = h("div", { class: "chips" }, ...Object.keys(ART).map((k) => h("button", { class: "chipbtn", "aria-pressed": String(el.icon === k), "aria-label": ART_NAMES[k], title: ART_NAMES[k], onclick: () => set("icon", k), style: { width: "36px", height: "36px", padding: "6px", borderRadius: "8px" } }, (() => { const s = h("span", { class: "ic" }); s.innerHTML = ART[k]; return s; })())));
      body.append(this.sec("Icon", grid, h("button", { class: "btn", style: { marginTop: "6px", color: "var(--accent)", paddingLeft: "0" }, onclick: () => this.toast("The full picker searches all 7,000 icons.") }, "All icons…")));
    } else if (el.type === "box") {
      body.append(this.sec("Card", h("div", { class: "field" }, h("span", { class: "lab", text: "Fill" }), this.segc([["outline", "Outline"], ["black", "Black"], ["white", "White"]], el.fill || "outline", (v) => set("fill", v), "Fill")),
        this.field("Corners", this.inp(el.radius ?? 0, (v) => set("radius", Number(v)), { type: "number", min: "0", max: "60" }))));
    } else if (el.type === "curve") {
      const e = ENT[el.entity] || [el.entity, "", ""];
      body.append(this.sec("Shows", h("button", { class: "entbtn", onclick: (ev) => this.openEntityPicker(ev.currentTarget, (id) => set("entity", id)) }, h("span", { style: { minWidth: "0" } }, h("span", { class: "e1", text: e[0] }), h("span", { class: "e2", text: el.entity }))),
        this.field("Hours", this.inp(el.hours ?? 24, (v) => set("hours", Number(v)), { type: "number", min: "1", max: "168" }))));
    } else if (el.type === "line") {
      body.append(this.sec("Divider", this.field("Thickness", this.inp(Math.min(el.w, el.h), (v) => { if (el.h >= el.w) el.w = Number(v); else el.h = Number(v); this.commit(); this.render(); }, { type: "number", min: "1", max: "12" }))));
    }
    const nums = h("div", { class: "quad" }, ...["x", "y", "w", "h"].map((k) => h("label", {}, this.inp(el[k], (v) => set(k, Math.round(Number(v) || 0)), { type: "number", "aria-label": { x: "Left", y: "Top", w: "Width", h: "Height" }[k] }), { x: "X", y: "Y", w: "Width", h: "Height" }[k])));
    const i = this.sel[0], n = this.els().length;
    body.append(this.sec("Arrange", nums,
      h("div", { class: "btnrow", style: { marginTop: "8px" } },
        h("button", { class: "btn icon", "aria-label": "Centre across", title: "Centre across", onclick: () => this.align("ch") }, icon("centerh", "sm")),
        h("button", { class: "btn icon", "aria-label": "Centre up and down", title: "Centre up and down", onclick: () => this.align("cv") }, icon("centerv", "sm")),
        h("button", { class: "btn icon", "aria-label": "Full width", title: "Full width", onclick: () => this.align("full") }, icon("widen", "sm"))),
      h("div", { class: "field", style: { marginTop: "10px" } }, h("span", { class: "lab", text: `Layer ${n - i} of ${n}` }),
        h("div", { class: "btnrow" },
          h("button", { class: "btn icon", "aria-label": "Send to back", title: "Send to back  ⌥⌘[", disabled: i === 0, onclick: () => this.reorderSel("back") }, icon("back2", "sm")),
          h("button", { class: "btn icon", "aria-label": "Send backward", title: "Send backward  ⌘[", disabled: i === 0, onclick: () => this.reorderSel("bwd") }, icon("bwd", "sm")),
          h("button", { class: "btn icon", "aria-label": "Bring forward", title: "Bring forward  ⌘]", disabled: i === n - 1, onclick: () => this.reorderSel("fwd") }, icon("fwd", "sm")),
          h("button", { class: "btn icon", "aria-label": "Bring to front", title: "Bring to front  ⌥⌘]", disabled: i === n - 1, onclick: () => this.reorderSel("front") }, icon("front", "sm")))),
      h("button", { class: "btn", style: { marginTop: "6px", color: "var(--accent)", paddingLeft: "0" }, onclick: (e) => this.openCopyTo(e.currentTarget) }, "Copy to another page…")));
    const more = h("details", { class: "more" }, h("summary", {}, icon("chev", "sm"), "More"),
      this.field("Only if", this.inp(el.show_if, (v) => set("show_if", v), { placeholder: "a Home Assistant template" })),
      h("div", { class: "field" }, h("span", { class: "lab", text: "Style" }), this.segc([["plain", "Plain"], ["invert", "White on black"]], el.invert ? "invert" : "plain", (v) => set("invert", v === "invert" ? true : ""), "Style")));
    body.append(this.sec(null, more));
    body.append(this.sec(null, h("div", { class: "btnrow" }, h("button", { class: "btn", onclick: () => this.duplicate() }, icon("dup", "sm"), "Duplicate"), h("button", { class: "btn danger", onclick: () => this.remove() }, icon("trash", "sm"), "Delete"))));
  }

  inspPage(head, body) {
    const p = this.page();
    const name = h("input", { class: "inp", value: pageTitle(this.cur), "aria-label": "Page name", style: { font: "600 15px var(--font-display)", background: "transparent", paddingLeft: "4px" } });
    const err = h("div", { class: "muted", style: { fontSize: "11.5px", padding: "0 14px", minHeight: "0" } });
    name.addEventListener("keydown", (e) => { if (e.key === "Enter") name.blur(); if (e.key === "Escape") { name.value = pageTitle(this.cur); name.blur(); } });
    name.addEventListener("input", () => { const s2 = slug(name.value); err.textContent = !s2 ? "A page needs a name." : s2 !== this.cur && this.s.pages[s2] ? `There's already a page called ${pageTitle(s2)}.` : ""; });
    name.addEventListener("change", () => this.renamePage(name.value));
    head.append(h("span", { class: "ttl", style: { overflow: "visible" } }, h("span", { class: "kind", text: "Page", style: { paddingLeft: "4px" } }), name));
    body.append(err);
    const tier = p.tier || "rotate";
    const s = this.sec("Shows", this.segc([["rotate", "Always"], ["when", "Only when"], ["alert", "As an alert"]], tier, (v) => this.setTier(v), "When this page shows"));
    if (tier === "when") {
      const c = p.cond || (p.cond = { entity: "", op: "eq", value: "" });
      const e = ENT[c.entity];
      s.append(h("div", { style: { height: "8px" } }), h("button", { class: "entbtn", onclick: (ev) => this.openEntityPicker(ev.currentTarget, (id) => { c.entity = id; c.value = (STATES[id] || [ENT[id][1]])[0]; c.op = "eq"; this.commit(); this.render(); }) },
        h("span", { style: { minWidth: "0" } }, h("span", { class: "e1", text: e ? e[0] : "Choose a sensor" }), h("span", { class: "e2", text: c.entity || "" })), e ? h("span", { class: "ev", text: "now " + e[1] }) : null));
      if (e) {
        const choices = STATES[c.entity];
        if (choices) s.append(h("div", { class: "field" }, h("span", { class: "lab", text: "is" }), h("div", { class: "chips" }, ...choices.map((v) => h("button", { class: "chipbtn", "aria-pressed": String(c.op === "eq" && c.value === v), onclick: () => { c.op = "eq"; c.value = v; this.commit(); this.render(); }, text: v })))));
        else s.append(h("div", { class: "field" }, h("span", { class: "lab", text: "is above" }), this.inp(c.value, (v) => { c.op = "gt"; c.value = v; this.commit(); this.render(); }, { type: "number" })));
        const holds = condHolds(c);
        s.append(h("div", { class: "legible" + (holds ? "" : " bad") }, h("span", { class: "led" }), h("span", { text: holds ? "Showing on the panel now" : `Hidden right now. ${e[0]} is ${e[1]}.` })));
      }
      s.append(h("button", { class: "btn", style: { marginTop: "4px", color: "var(--accent)", paddingLeft: "0" }, onclick: () => this.toast("A template field opens here, for anything the simple form can't say.") }, "Custom condition…"));
    }
    if (tier === "alert") s.append(this.field("Hold for", this.inp(p.hold || 10, (v) => { p.hold = Number(v) || 10; this.commit(); }, { type: "number", min: "1", max: "1440" })), h("div", { class: "muted", style: { fontSize: "12px" }, text: "Takes over the panel when its condition turns true, then gives it back." }));
    body.append(s);
    if (tier !== "alert") {
      const times = this.s.rotation.filter((n) => n === this.cur).length;
      const r = this.sec("Rotation",
        h("div", { class: "muted", style: { fontSize: "12.5px", marginBottom: "8px" }, text: times === 0 ? "Not in the rotation." : times === 1 ? "Once in every round. Drag its tile to move it." : `${times} times in every round.` }),
        h("div", { class: "btnrow" },
          h("button", { class: "btn", onclick: () => { this.s.rotation.push(this.cur); this.commit(); this.render(); }, text: times ? "Show again" : "Add to rotation" }),
          times ? h("button", { class: "btn", onclick: () => { const i = this.s.rotation.lastIndexOf(this.cur); this.s.rotation.splice(i, 1); this.commit(); this.render(); }, text: times > 1 ? "Show once less" : "Take out" }) : null),
        this.field("Each page", (() => { const sl = h("select", { class: "inp", id: "rs" + this.v }, ...[15, 30, 60, 120, 300].map((v) => h("option", { value: v, selected: this.s.rotate_seconds === v, text: v < 60 ? v + " s" : v / 60 + " min" }))); sl.onchange = () => { this.s.rotate_seconds = Number(sl.value); this.commit(); this.render(); }; return sl; })(), "rs" + this.v));
      body.append(r);
    }
    body.append(this.sec("Page",
      h("div", { class: "btnrow" }, h("button", { class: "btn", onclick: (e) => this.openMatch(e.currentTarget) }, "Match layout of…")),
      h("div", { class: "btnrow", style: { marginTop: "6px" } }, h("button", { class: "btn", onclick: () => this.duplicatePage() }, icon("dup", "sm"), "Duplicate"), h("button", { class: "btn danger", onclick: () => this.deletePage() }, icon("trash", "sm"), "Delete"))));
    body.append(h("div", { class: "empty-note", text: "Select something on the canvas to edit it." }));
  }

  setTier(v) {
    const p = this.page(); p.tier = v;
    if (v === "alert") this.s.rotation = this.s.rotation.filter((n) => n !== this.cur);
    else if (!this.s.rotation.includes(this.cur)) this.s.rotation.push(this.cur);
    this.commit(); this.render();
  }
  renamePage(raw) {
    const n = slug(raw);
    if (!n || n === this.cur || this.s.pages[n]) { this.render(); return; }
    const pages = {}; for (const [k, v] of Object.entries(this.s.pages)) pages[k === this.cur ? n : k] = v;
    this.s.pages = pages; this.s.rotation = this.s.rotation.map((x) => x === this.cur ? n : x);
    const old = this.cur; this.cur = n; this.commit(); this.render();
    this.toast(`Renamed ${pageTitle(old)} to ${pageTitle(n)}.`, "Undo", () => this.undo());
  }
  uniqueName(base) { let n = slug(base) || "page", k = 2; const b = n; while (this.s.pages[n]) n = `${b}_${k++}`; return n; }
  duplicatePage() {
    const n = this.uniqueName(this.cur + "_copy");
    this.s.pages[n] = clone(this.page());
    if (this.page().tier !== "alert") this.s.rotation.push(n);
    this.cur = n; this.sel = []; this.commit(); this.render();
    this.toast(`Duplicated as ${pageTitle(n)}. Rename it above.`, "Undo", () => this.undo());
  }
  deletePage() {
    const gone = this.cur;
    delete this.s.pages[gone]; this.s.rotation = this.s.rotation.filter((n) => n !== gone);
    this.cur = Object.keys(this.s.pages)[0]; this.sel = []; this.commit();
    if (this.v === "c") this.screen = "home";
    this.render();
    this.toast(`Deleted ${pageTitle(gone)}.`, "Undo", () => { this.undo(); });
  }

  /* ---------- side panel for the labs ---------- */
  renderLabSide() {
    const side = h("div", { class: "nav side", style: { borderRight: "0", borderLeft: "0.5px solid var(--sep)" } });
    side.append(h("div", { class: "navhead" }, h("span", { text: "Layers" }), h("span", { class: "muted", text: "front at the top", style: { fontWeight: "400", fontSize: "11px" } })), this.layerList());
    if (this.opt.sideExtra) side.append(this.opt.sideExtra(this));
    return side;
  }

  /* ---------- popovers and sheets ---------- */
  place(pop, anchor, align = "center") {
    const wr = this.win.getBoundingClientRect(), ar = anchor.getBoundingClientRect();
    const top = ar.bottom - wr.top + 6;
    pop.style.top = top + "px";
    pop.style.maxHeight = (wr.height - top - 12) + "px";
    requestAnimationFrame(() => {
      const pw = pop.offsetWidth;
      let left = align === "left" ? ar.left - wr.left : align === "right" ? ar.right - wr.left - pw : ar.left - wr.left + ar.width / 2 - pw / 2;
      left = Math.max(8, Math.min(wr.width - pw - 8, left));
      pop.style.left = left + "px";
    });
  }
  closeLayer(keepLayersFlag) {
    this.layer.replaceChildren();
    document.removeEventListener("pointerdown", this.outside, true);
    if (!keepLayersFlag && this.layersOpen && this.v === "b") { /* layers stay open by choice; reopened on render */ }
    if (this.returnFocus && this.returnFocus.isConnected) this.returnFocus.focus({ preventScroll: true });
    this.returnFocus = null;
  }
  popover(anchor, build, opts = {}) {
    this.closeLayer(true);
    this.returnFocus = anchor;
    const pop = h("div", { class: "pop " + (opts.cls || ""), role: opts.role || "dialog", "aria-label": opts.label || "" });
    build(pop);
    this.layer.append(pop);
    let ref = anchor;
    if (opts.at) { ref = h("span", { style: { position: "absolute", left: opts.at.x + "px", top: opts.at.y + "px", width: "1px", height: "1px" } }); this.layer.append(ref); }
    this.place(pop, ref, opts.align);
    setTimeout(() => {
      this.outside = (e) => { if (!pop.contains(e.target) && e.target !== anchor && !anchor.contains(e.target)) { this.closeLayer(); } };
      document.addEventListener("pointerdown", this.outside, true);
      const f = pop.querySelector("input, button"); if (f) f.focus({ preventScroll: true });
    });
    return pop;
  }
  sheet(title, build, opts = {}) {
    this.closeLayer(true);
    this.returnFocus = document.activeElement;
    const scrim = h("div", { class: "scrim", onclick: () => this.closeLayer() });
    const sh = h("div", { class: "sheet " + (opts.wide ? "wide" : ""), role: "dialog", "aria-modal": "true", "aria-label": title });
    const head = h("div", { class: "sheet-head" }, h("h5", { text: title }), h("button", { class: "btn icon", "aria-label": "Close", onclick: () => this.closeLayer() }, icon("close")));
    sh.append(head);
    build(sh);
    this.layer.append(scrim, sh);
    setTimeout(() => { const f = sh.querySelector(".sheet-body input, .sheet-body button, .settings button, .sheet-foot button"); if (f) f.focus({ preventScroll: true }); });
    return sh;
  }

  openInsert(anchor) {
    this.popover(anchor, (pop) => {
      const q = h("input", { placeholder: "Search sensors and elements", "aria-label": "Search sensors and elements" });
      const results = h("div");
      pop.append(h("div", { class: "search" }, icon("search", "sm"), q), results);
      const types = [["number", "Value", "value"], ["text", "Text", "text"], ["icon", "Icon", "image"], ["box", "Card", "square"], ["line", "Divider", "line"], ["curve", "Sparkline", "wave"], ["bar", "Gauge", "gauge"], ["chart", "Bar chart", "chart"], ["weather", "Weather", "cloud"], ["month", "Month", "calendar"], ["grid", "Devices", "grid"], ["flights", "Flights", "plane"], ["qr", "QR code", "qr"]];
      const draw = () => {
        const s = q.value.trim().toLowerCase();
        results.replaceChildren();
        const ents = Object.entries(ENT).filter(([id, e]) => !s || id.includes(s) || e[0].toLowerCase().includes(s)).slice(0, s ? 8 : 4);
        const ts = types.filter(([, l]) => !s || l.toLowerCase().includes(s));
        if (ts.length) results.append(h("div", { class: "poplab", text: "Elements" }), h("div", { class: "typegrid" }, ...ts.map(([k, l, ic]) => h("button", { onclick: () => this.insertType(k) }, icon(ic), l))));
        if (ents.length) results.append(h("div", { class: "poplab", text: s ? "Sensors" : "Recent sensors" }), h("div", { class: "optlist" }, ...ents.map(([id, e]) => h("button", { class: "opt", onclick: () => this.insertEntity(id) }, h("span", { class: "glyph" }, icon("value", "sm")), h("span", { style: { minWidth: "0" } }, h("span", { class: "o1", text: e[0] }), h("span", { class: "o2", text: id })), h("span", { class: "ov2", text: e[1] + (e[2] ? " " + e[2] : "") })))));
        if (!ts.length && !ents.length) results.append(h("div", { class: "empty-note", text: `Nothing called “${q.value}”. Try part of the name, like “temp”.` }));
      };
      q.addEventListener("input", draw);
      q.addEventListener("keydown", (e) => { if (e.key === "Enter") { const b = results.querySelector(".opt, .typegrid button"); if (b) b.click(); } });
      draw();
    }, { label: "Insert", align: "left" });
  }
  insertType(k) {
    const base = { x: 260, y: 70, w: 270, h: 90 };
    const make = { number: { type: "number", entity: "sensor.home_battery", suffix: " %" }, text: { type: "text", value: "Label", size: 30, bold: false, h: 40 }, icon: { type: "icon", icon: "paw", w: 100, h: 100, x: 346 }, box: { type: "box", fill: "outline", radius: 12, thickness: 3, x: 40, y: 20, w: 300, h: 196 }, line: { type: "line", w: 300, h: 4, y: 120 }, curve: { type: "curve", entity: "sensor.solar_pv_power" } };
    const el = Object.assign({}, base, make[k] || { type: "text", value: TYPE_NAMES[k] || "Widget", size: 30, h: 40 });
    if (el.type === "box") this.els().unshift(el); else this.els().push(el);
    this.sel = [el.type === "box" ? 0 : this.els().length - 1];
    this.closeLayer(); this.commit(); this.render();
    if (!make[k]) this.toast("Widgets work as they do today; this mock stands one in with text.");
  }
  insertEntity(id) {
    const e = ENT[id]; const num = !isNaN(Number(e[1]));
    const el = { type: num ? "number" : "text", entity: id, x: 260, y: 60, w: 280, h: 100 };
    if (num && e[2]) el.suffix = " " + e[2];
    this.els().push(el); this.sel = [this.els().length - 1];
    this.closeLayer(); this.commit(); this.render();
    this.say(`Added ${e[0]}`);
  }
  openEntityPicker(anchor, onPick) {
    this.popover(anchor, (pop) => {
      const q = h("input", { placeholder: "Search sensors", "aria-label": "Search sensors" });
      const list = h("div", { class: "optlist" });
      const draw = () => {
        const s = q.value.toLowerCase();
        list.replaceChildren(...Object.entries(ENT).filter(([id, e]) => !s || id.includes(s) || e[0].toLowerCase().includes(s)).map(([id, e]) => h("button", { class: "opt", onclick: () => { this.closeLayer(); onPick(id); } }, h("span", { style: { minWidth: "0" } }, h("span", { class: "o1", text: e[0] }), h("span", { class: "o2", text: id })), h("span", { class: "ov2", text: e[1] + (e[2] ? " " + e[2] : "") }))));
      };
      q.addEventListener("input", draw); draw();
      pop.append(h("div", { class: "search" }, icon("search", "sm"), q), list);
    }, { label: "Choose a sensor", align: "left" });
  }

  openNow(anchor) {
    this.popover(anchor, (pop) => {
      pop.style.width = "320px"; pop.style.padding = "12px 14px";
      const hidden = Object.entries(this.s.pages).filter(([n, p]) => p.tier === "when" && this.s.rotation.includes(n) && !condHolds(p.cond));
      pop.append(
        h("div", { style: { display: "flex", alignItems: "center", gap: "8px", fontWeight: "600", fontSize: "15px" } }, h("span", { class: "led" + (this.dirty ? " wait" : "") }), this.asleep ? "Asleep" : this.dirty ? "Not sent yet" : "Up to date"),
        h("div", { class: "muted", style: { fontSize: "12.5px", margin: "2px 0 10px" }, text: this.dirty ? "Your latest changes are only in this window. Send them when you're ready." : `Sent at ${this.sentAt}. The panel checks for new pages every 5 min.` }),
        h("div", { style: { fontSize: "13px" }, text: `${this.liveCount()} pages rotating, ${this.s.rotate_seconds} s each.` }),
        hidden.length ? h("div", { class: "poplab", style: { padding: "10px 0 2px" }, text: "Hidden right now" }) : null,
        ...hidden.map(([n, p]) => h("div", { style: { fontSize: "12.5px", padding: "3px 0" } }, h("b", { text: pageTitle(n) + ". " }), h("span", { class: "muted", text: whyHidden(p.cond) }))),
        h("div", { class: "poplab", style: { padding: "10px 0 2px" }, text: "Quiet hours" }),
        h("div", { style: { fontSize: "12.5px" }, text: "23:00 to 07:00, with the sleep screen." }),
        h("div", { class: "btnrow", style: { marginTop: "12px" } },
          h("button", { class: "btn", onclick: () => { this.asleep = !this.asleep; this.closeLayer(); this.render(); this.toast(this.asleep ? "The panel is going to sleep." : "The panel is waking up."); } }, icon("moon", "sm"), this.asleep ? "Wake" : "Sleep now"),
          h("button", { class: "btn", onclick: () => { this.closeLayer(); this.toast("Asked the panel to clear ghosting."); } }, icon("sparkle", "sm"), "Clear ghosting")),
        h("button", { class: "btn", style: { marginTop: "6px", width: "100%", background: "var(--fill)" }, onclick: () => this.openSettings() }, "Panel settings…"));
    }, { label: "Now on the panel", align: "right" });
  }

  openSettings(section = "panel") {
    this.sheet("Settings", (sh) => {
      const wrap = h("div", { class: "settings" });
      const nav = h("nav", { "aria-label": "Settings sections" });
      const pane = h("div", { class: "pane" });
      const sw = (on, label) => { const b = h("button", { class: "switch", role: "switch", "aria-checked": String(on), "aria-label": label }); b.onclick = () => b.setAttribute("aria-checked", String(b.getAttribute("aria-checked") !== "true")); return b; };
      const sel = (opts, cur, label) => h("select", { class: "inp", "aria-label": label }, ...opts.map((o) => h("option", { selected: o === cur, text: o })));
      const gr = (label, sub, ctl) => h("div", { class: "gr" }, h("span", {}, label, sub ? h("small", { text: sub }) : null), ctl);
      const sections = {
        panel: ["Panel", () => [
          h("div", { class: "gtitle", text: "Connection" }),
          h("div", { class: "group" }, gr("Connected", "Wi-Fi signal good", h("span", { class: "led" })), gr("Install or update the panel", "Makes the ESPHome file and walks you through it", h("button", { class: "btn tinted", text: "Open…" }))),
          h("div", { class: "gtitle", text: "Display" }),
          h("div", { class: "group" }, gr("Model", null, sel(['CrowPanel 5.79"', 'CrowPanel 4.2"', 'CrowPanel 2.9"', 'CrowPanel 7.5"', 'CrowPanel 10.2"'], 'CrowPanel 5.79"', "Model")), gr("Mounted", null, sel(["Landscape", "Upside down", "Portrait", "Portrait, flipped"], "Landscape", "Mounted")), gr("Check for new pages every", null, sel(["1 min", "2 min", "5 min", "10 min", "30 min"], "5 min", "Check every"))),
          h("div", { class: "gtitle", text: "Ghosting" }),
          h("div", { class: "group" }, gr("Clear ghosting", "A full refresh flashes the screen once to clean it", sel(["On automatic changes", "Every few refreshes"], "On automatic changes", "Clear ghosting")), gr("After", "partial refreshes", h("input", { class: "inp", type: "number", value: "10", style: { width: "70px" }, "aria-label": "After this many refreshes" })), gr("Clear it now", null, h("button", { class: "btn tinted", text: "Clear" }))),
          h("div", { class: "group" }, gr("Sleep", "Shows the sleep screen until someone presses a button", sw(this.asleep, "Sleep")))]],
        quiet: ["Quiet hours", () => [
          h("div", { class: "group", style: { marginTop: "12px" } }, gr("Quiet hours", "No flashing and no downloads while they last", sw(true, "Quiet hours")), gr("From", null, h("input", { class: "inp", type: "time", value: "23:00", "aria-label": "From" })), gr("Until", null, h("input", { class: "inp", type: "time", value: "07:00", "aria-label": "Until" }))),
          h("div", { class: "group" }, gr("Also while nobody's home", "Choose who or which zone", h("button", { class: "btn tinted", text: "Choose…" })), gr("Alerts can wake it", null, sw(true, "Alerts can wake it")), gr("Sleep screen", "Closed eyes and when it wakes. Off keeps a page on screen overnight.", sw(true, "Sleep screen")))]],
        sources: ["Data sources", () => [
          h("p", { class: "muted", style: { fontSize: "12.5px", marginTop: "12px" }, text: "Each source becomes a sensor your pages can show, like any other." }),
          h("div", { class: "group" }, gr("Next to watch", "Jellyfin · new and unwatched", h("button", { class: "btn tinted", text: "Edit" })), gr("Solar this month", "Home Assistant statistic", h("button", { class: "btn tinted", text: "Edit" }))),
          h("button", { class: "btn tinted" }, icon("plus", "sm"), "Add a source")]],
        editor: ["Editor", () => [
          h("div", { class: "group", style: { marginTop: "12px" } }, gr("Appearance", null, sel(["Match the system", "Light", "Dark"], "Match the system", "Appearance")), gr("Check legibility from", "The size note under each text uses this distance", sel(["0.8 m, a desk", "1.5 m, a bedside", "3 m, a sofa", "5 m, across a room", "Don't check"], "3 m, a sofa", "Legibility distance")), gr("Show footer and padlock guides", null, sw(false, "Guides"))),
          h("div", { class: "group" }, gr("Keyboard shortcuts", null, h("button", { class: "btn tinted", text: "Show" })))]],
      };
      const show = (k) => {
        pane.replaceChildren(h("h5", { text: sections[k][0], style: { font: "600 17px var(--font-display)", margin: "8px 0 0" } }), ...sections[k][1]());
        nav.querySelectorAll(".row").forEach((r) => r.setAttribute("aria-current", r.dataset.k === k ? "page" : "false"));
      };
      Object.entries(sections).forEach(([k, [l]]) => nav.append(h("button", { class: "row", data: { k }, onclick: () => show(k) }, h("span", { class: "rmain", text: l }))));
      wrap.append(nav, pane); sh.append(wrap);
      show(section);
    }, { wide: true });
  }

  openPresets() {
    this.sheet("New page", (sh) => {
      const body = h("div", { class: "sheet-body" });
      const grid = h("div", { class: "presetgrid" });
      grid.append(h("button", { onclick: () => this.addPage("untitled", []) }, (() => { const t = thumb({ elements: [] }, ""); return t; })(), h("div", { class: "pt", text: "Blank" }), h("div", { class: "pd", text: "Start from nothing" })));
      PRESETS.forEach((p) => grid.append(h("button", { onclick: () => this.presetStep2(sh, p) }, thumb({ elements: p.make(Object.keys(ENT).find((k) => k.startsWith((p.domain || "sensor") + ".")) || "") }, p.id), h("div", { class: "pt", text: p.title }), h("div", { class: "pd", text: p.desc }))));
      body.append(grid); sh.append(body);
    }, { wide: true });
  }
  presetStep2(sh, p) {
    if (!p.domain) { this.addPage(p.id, p.make("")); return; }
    sh.querySelector("h5").textContent = p.title;
    const body = h("div", { class: "sheet-body" });
    const pv = h("div", { style: { maxWidth: "360px", margin: "0 auto 12px" } });
    const q = h("input", { placeholder: "Search sensors", "aria-label": "Search sensors" });
    const list = h("div", { class: "optlist" });
    let chosen = null;
    const add = h("button", { class: "btn primary", disabled: true, onclick: () => this.addPage(p.id, p.make(chosen)) , text: "Add page" });
    const draw = () => {
      pv.replaceChildren(thumb({ elements: p.make(chosen || "") }, p.id));
      const s = q.value.toLowerCase();
      list.replaceChildren(...Object.entries(ENT).filter(([id, e]) => (id.startsWith(p.domain + ".") || s) && (!s || id.includes(s) || e[0].toLowerCase().includes(s))).map(([id, e]) => h("button", { class: "opt" + (chosen === id ? " active" : ""), "aria-pressed": String(chosen === id), onclick: () => { chosen = id; add.disabled = false; draw(); } }, h("span", { style: { minWidth: "0" } }, h("span", { class: "o1", text: e[0] }), h("span", { class: "o2", text: id })), h("span", { class: "ov2", text: e[1] + (e[2] ? " " + e[2] : "") }))));
    };
    q.addEventListener("input", draw); draw();
    body.append(pv, h("div", { style: { fontWeight: "600", margin: "4px 0" }, text: "Which sensor should it show?" }), h("div", { class: "search", style: { margin: "4px 0" } }, icon("search", "sm"), q), list);
    sh.replaceChildren(sh.firstChild, body, h("div", { class: "sheet-foot" }, h("button", { class: "btn", onclick: () => this.addPage(p.id, p.make("")), text: "Skip for now" }), add));
  }
  addPage(base, elements) {
    const n = this.uniqueName(base);
    this.s.pages[n] = { tier: "rotate", elements };
    this.s.rotation.push(n);
    this.cur = n; this.sel = []; if (this.v === "c") this.screen = "editor";
    this.closeLayer(); this.commit(); this.render();
    this.toast(`Added ${pageTitle(n)}. Rename it in the inspector.`, "Undo", () => this.undo());
  }

  openCopyTo(anchor) {
    const items = this.sel.map((k) => clone(this.els()[k]));
    if (!items.length) return;
    this.popover(anchor, (pop) => {
      const chosen = new Set();
      const go = h("button", { class: "btn primary", style: { width: "100%", marginTop: "6px" }, disabled: true, text: "Copy" });
      const list = h("div", { class: "optlist" }, ...Object.keys(this.s.pages).filter((n) => n !== this.cur).map((n) => {
        const b = h("button", { class: "opt", role: "checkbox", "aria-checked": "false" }, h("span", { class: "rthumb", style: { width: "56px", borderRadius: "4px", overflow: "hidden", flex: "none" } }, thumb(this.s.pages[n], n)), h("span", { class: "o1", text: pageTitle(n) }));
        b.onclick = () => { chosen.has(n) ? chosen.delete(n) : chosen.add(n); b.setAttribute("aria-checked", String(chosen.has(n))); b.classList.toggle("active", chosen.has(n)); go.disabled = !chosen.size; go.textContent = chosen.size ? `Copy to ${chosen.size} page${chosen.size > 1 ? "s" : ""}` : "Copy"; };
        return b;
      }));
      go.onclick = () => { chosen.forEach((n) => this.s.pages[n].elements.push(...clone(items))); this.closeLayer(); this.commit(); this.render(); this.toast(`Copied to ${[...chosen].map(pageTitle).join(", ")}, in the same place.`, "Undo", () => this.undo()); };
      pop.append(h("div", { class: "poplab", text: "Same place and size on…" }), list, go);
    }, { label: "Copy to page" });
  }
  openMatch(anchor) {
    this.popover(anchor, (pop) => {
      pop.style.width = "330px";
      const others = Object.keys(this.s.pages).filter((n) => n !== this.cur);
      const sel = h("select", { class: "inp", "aria-label": "Take the layout from" }, ...others.map((n) => h("option", { value: n, selected: n === "solar" || n === "solar_month" && this.cur === "solar", text: pageTitle(n) })));
      const pairsEl = h("div", { class: "pairs" });
      const apply = h("button", { class: "btn primary", style: { width: "100%" }, text: "Match layout" });
      const pairsFor = (src) => {
        const used = new Set();
        return this.els().map((el) => {
          const j = this.s.pages[src].elements.findIndex((o, k) => !used.has(k) && o.type === el.type);
          if (j >= 0) used.add(j);
          return [el, j >= 0 ? this.s.pages[src].elements[j] : null];
        });
      };
      const draw = () => {
        pairsEl.replaceChildren(...pairsFor(sel.value).map(([mine, theirs]) => h("div", {}, h("span", { text: elName(mine).t + (elName(mine).d ? " " + elName(mine).d : "") }), icon("chev", "sm"), h("span", { class: theirs ? "" : "none", text: theirs ? "takes its place and size" : "no match, stays put" }))));
      };
      sel.onchange = draw; draw();
      apply.onclick = () => {
        pairsFor(sel.value).forEach(([mine, t]) => { if (t) ["x", "y", "w", "h", "size", "bold", "align"].forEach((k) => { if (t[k] !== undefined) mine[k] = t[k]; else delete mine[k]; }); });
        this.closeLayer(); this.commit(); this.render(); this.toast(`Matched the layout of ${pageTitle(sel.value)}. Your sensors and text stay.`, "Undo", () => this.undo());
      };
      pop.append(h("div", { class: "poplab", text: "Take positions, sizes and text styles from" }), h("div", { style: { padding: "4px" } }, sel), h("div", { style: { padding: "0 4px" } }, pairsEl, apply));
    }, { label: "Match layout" });
  }

  openContext(e) {
    const p = this.toPanel(e);
    const hits = this.hitsAt(p);
    if (hits.length && !hits.some((k) => this.sel.includes(k))) { this.sel = [hits[0]]; this.render(); }
    const wr = this.win.getBoundingClientRect();
    const at = { x: e.clientX - wr.left, y: e.clientY - wr.top - 6 };
    const anchor = this.panel;
    const mi = (label, kb, fn, dis) => h("button", { class: "mi", role: "menuitem", disabled: dis, onclick: () => { this.closeLayer(); fn(); } }, h("span", { text: label }), kb ? h("span", { class: "kb", text: kb }) : null);
    const has = this.sel.length > 0;
    this.popover(anchor, (pop) => {
      pop.append(mi("Cut", "⌘X", () => this.copy(true), !has), mi("Copy", "⌘C", () => this.copy(), !has), mi("Paste", "⌘V", () => this.paste(), !CLIP), mi("Duplicate", "⌘D", () => this.duplicate(), !has), mi("Delete", "⌫", () => this.remove(), !has));
      if (hits.length > 1) {
        pop.append(h("div", { class: "msep" }), h("div", { class: "mlab", text: "Select" }));
        hits.forEach((k) => { const { t, d } = elName(this.els()[k]); pop.append(mi(`${t}${d ? " " + d : ""}`, this.sel.includes(k) ? "✓" : "", () => { this.sel = [k]; this.render(); })); });
      }
      pop.append(h("div", { class: "msep" }), mi("Bring to front", "⌥⌘]", () => this.reorderSel("front"), this.sel.length !== 1), mi("Send to back", "⌥⌘[", () => this.reorderSel("back"), this.sel.length !== 1));
    }, { cls: "menu", role: "menu", label: "Element", align: "left", at });
  }

  /* ---------- sending, with the version check ---------- */
  send() {
    if (!this.opt.server) { this.dirty = false; this.sentAt = new Date().toTimeString().slice(0, 5); this.render(); this.toast("Sent. The panel is updating now."); return; }
    const r = this.server.put(this.s, this.etag);
    if (r.status === 200) { this.etag = r.etag; this.base = clone(this.s); this.dirty = false; this.render(); this.toast("Sent. The panel is updating now."); if (this.opt.onSent) this.opt.onSent(); return; }
    // Someone saved in between: merge by page.
    const theirs = r.spec, base = this.base, mine = this.s;
    const names = new Set([...Object.keys(base.pages), ...Object.keys(mine.pages), ...Object.keys(theirs.pages)]);
    const merged = clone(theirs); const clash = [];
    const js = (x) => JSON.stringify(x ?? null);
    names.forEach((n) => {
      const b = js(base.pages[n]), m = js(mine.pages[n]), t = js(theirs.pages[n]);
      if (m === b) return; // only they changed it (or nobody)
      if (t === b || t === m) { if (mine.pages[n]) merged.pages[n] = clone(mine.pages[n]); else delete merged.pages[n]; return; }
      clash.push(n);
    });
    if (js(mine.rotation) !== js(base.rotation)) merged.rotation = clone(mine.rotation);
    if (!clash.length) {
      const r2 = this.server.put(merged, r.etag);
      this.s = merged; this.base = clone(merged); this.etag = r2.etag; this.dirty = false;
      this.hist.push(JSON.stringify(this.s)); this.hpos = this.hist.length - 1;
      this.render(); this.toast("Sent, together with the other window's changes."); if (this.opt.onSent) this.opt.onSent(); return;
    }
    this.resolveConflict(clash, merged, theirs, r.etag);
  }
  resolveConflict(clash, merged, theirs, etag) {
    const choice = {}; clash.forEach((n) => choice[n] = "mine");
    this.sheet(clash.length === 1 ? `${pageTitle(clash[0])} changed in both windows` : `${clash.length} pages changed in both windows`, (sh) => {
      const body = h("div", { class: "sheet-body" }, h("p", { class: "muted", style: { fontSize: "13px" }, text: "The other window sent its changes while you were editing. Everything else merged on its own. Choose which version to keep; the other stays one undo away." }));
      clash.forEach((n) => {
        const mineC = h("button", { class: "cmpcard", "aria-pressed": "true" }, thumb(this.s.pages[n] || { elements: [] }, n), h("div", { class: "ct", text: "Yours" }), h("div", { class: "cs", text: "From this window, just now" }));
        const theirC = h("button", { class: "cmpcard", "aria-pressed": "false" }, thumb(theirs.pages[n] || { elements: [] }, n), h("div", { class: "ct", text: "The other window's" }), h("div", { class: "cs", text: "Sent a moment ago" }));
        mineC.onclick = () => { choice[n] = "mine"; mineC.setAttribute("aria-pressed", "true"); theirC.setAttribute("aria-pressed", "false"); };
        theirC.onclick = () => { choice[n] = "theirs"; mineC.setAttribute("aria-pressed", "false"); theirC.setAttribute("aria-pressed", "true"); };
        body.append(clash.length > 1 ? h("h4", { text: pageTitle(n) }) : null, h("div", { class: "cmpgrid" }, mineC, theirC));
      });
      sh.append(body, h("div", { class: "sheet-foot" }, h("button", { class: "btn primary", text: "Keep and send", onclick: () => {
        const before = JSON.stringify(this.s);
        clash.forEach((n) => { if (choice[n] === "mine") { if (this.s.pages[n]) merged.pages[n] = clone(this.s.pages[n]); else delete merged.pages[n]; } });
        const r2 = this.server.put(merged, etag);
        this.hist.push(before, JSON.stringify(merged)); this.hpos = this.hist.length - 1;
        this.s = merged; this.base = clone(merged); this.etag = r2.etag; this.dirty = false;
        if (!this.s.pages[this.cur]) this.cur = Object.keys(this.s.pages)[0];
        this.sel = []; this.closeLayer(); this.render(); this.toast("Sent. The version you didn't keep is one undo away.", "Undo", () => this.undo()); if (this.opt.onSent) this.opt.onSent();
      } })));
    });
  }

  /* ---------- feedback ---------- */
  toast(text, action, run) {
    const [span, btn] = this.toastEl.children;
    span.textContent = text;
    btn.hidden = !action; if (action) { btn.textContent = action; btn.onclick = () => { run(); this.toastEl.classList.remove("on"); }; }
    this.toastEl.classList.add("on");
    clearTimeout(this.toastT); this.toastT = setTimeout(() => this.toastEl.classList.remove("on"), action ? 6000 : 3200);
  }
  say(t) { this.live.textContent = t; }

  key(e) {
    const tag = e.target.tagName;
    if (e.key === "Escape") { if (this.layer.children.length) { this.closeLayer(); e.preventDefault(); } else if (this.sel.length) { this.sel = []; this.render(); } return; }
    if (/INPUT|SELECT|TEXTAREA/.test(tag)) return;
    if (this.v === "c" && this.screen === "home") return;
    const mod = e.metaKey || e.ctrlKey; const k = e.key.toLowerCase();
    if (mod && k === "z") { e.preventDefault(); e.shiftKey ? this.redo() : this.undo(); return; }
    if (mod && k === "c") { e.preventDefault(); this.copy(); return; }
    if (mod && k === "x") { e.preventDefault(); this.copy(true); return; }
    if (mod && k === "v") { e.preventDefault(); this.paste(); return; }
    if (mod && k === "d") { e.preventDefault(); this.duplicate(); return; }
    if (mod && k === "a") { e.preventDefault(); this.sel = this.els().map((_, i) => i); this.render(); return; }
    if (mod && (e.key === "]" || e.key === "[")) { e.preventDefault(); this.reorderSel(e.key === "]" ? (e.altKey ? "front" : "fwd") : (e.altKey ? "back" : "bwd")); return; }
    if (!this.sel.length) return;
    if (e.key === "Backspace" || e.key === "Delete") { e.preventDefault(); this.remove(); return; }
    const st = e.shiftKey ? 10 : 1;
    const m = { ArrowLeft: [-st, 0], ArrowRight: [st, 0], ArrowUp: [0, -st], ArrowDown: [0, st] }[e.key];
    if (m) { e.preventDefault(); this.sel.forEach((i) => { const el = this.els()[i]; el.x = Math.max(0, Math.min(W - el.w, el.x + m[0])); el.y = Math.max(0, Math.min(H - el.h, el.y + m[1])); }); this.commit("nudge"); this.render(); }
  }
}

document.addEventListener("keydown", (e) => { if (ACTIVE && ACTIVE.win.isConnected && ACTIVE.win.offsetParent !== null) ACTIVE.key(e); });

/* ================================================================
   Page wiring: tabs, mocks, labs
   ================================================================ */
const mocks = {};
function ensureMock(id) {
  if (mocks[id]) return;
  if (id === "a" || id === "b" || id === "c") mocks[id] = new Mock(document.getElementById("host-" + id), id);
  if (id === "fixes") buildLabs();
}
const tabs = [...document.querySelectorAll('[role="tab"]')];
function showTab(id, push) {
  tabs.forEach((t) => t.setAttribute("aria-selected", String(t.getAttribute("aria-controls") === id)));
  document.querySelectorAll('section[role="tabpanel"]').forEach((s) => { s.hidden = s.id !== id; });
  ensureMock(id);
  store.set("epaper-mock-tab", id);
  if (push) history.replaceState(null, "", "#" + id);
}
tabs.forEach((t, i) => {
  t.addEventListener("click", () => showTab(t.getAttribute("aria-controls"), true));
  t.addEventListener("keydown", (e) => {
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!d) return; e.preventDefault();
    const n = tabs[(i + d + tabs.length) % tabs.length]; n.focus(); showTab(n.getAttribute("aria-controls"), true);
  });
});
document.querySelectorAll('a[href^="#"]').forEach((a) => a.addEventListener("click", (e) => { const id = a.getAttribute("href").slice(1); if (document.getElementById(id)?.getAttribute("role") === "tabpanel") { e.preventDefault(); showTab(id, true); window.scrollTo({ top: 0, behavior: "smooth" }); } }));
document.querySelectorAll("[data-size]").forEach((b) => b.addEventListener("click", () => {
  const id = b.dataset.for; const host = document.getElementById("host-" + id);
  host.classList.toggle("phone", b.dataset.size === "phone");
  b.parentElement.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  setTimeout(() => mocks[id] && mocks[id].render(), 420);
}));

function buildLabs() {
  /* A: picking */
  const log = document.getElementById("log-a");
  const labA = new Mock(document.getElementById("host-lab-a"), "lab", { page: "energy", pickMode: "smallest", onPick: (m, r) => {
    const deep = r.n > 1 ? ` That's ${r.idx + 1} of ${r.n} under the pointer; click again without moving for the next.` : "";
    log.textContent = r.mode === "today" ? `Picked ${r.t}${r.d ? " " + r.d : ""}: always the topmost box, whatever you meant.` : `Picked ${r.t}${r.d ? " " + r.d : ""}.${deep}`;
  } });
  mocks.labA = labA;
  document.querySelectorAll("#pickmode button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("#pickmode button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    labA.pickMode = b.dataset.mode; labA.sel = []; labA.lastClick = null; labA.stack = null; labA.render();
    log.textContent = { top: "Topmost first: the first click gets the top box, each click without moving goes one deeper.", smallest: "Smallest first: the first click gets the smallest thing under the pointer, each click without moving goes to the next bigger one.", today: "Today: every click gets the topmost box, and there's no way to click through." }[b.dataset.mode];
  }));

  /* B: click versus drag */
  const counter = (el, m) => {
    const moved = m.els().reduce((s, e, i) => s + (m.origin[i] ? Math.abs(e.x - m.origin[i].x) + Math.abs(e.y - m.origin[i].y) : 0), 0);
    const steps = m.hpos;
    el.replaceChildren(h("span", {}, "Moved ", h("b", { class: moved ? "bad" : "", text: moved + " px" })), h("span", {}, "Undo steps ", h("b", { class: steps ? "bad" : "", text: String(steps) })));
  };
  const mk = (id, legacy) => {
    const host = document.getElementById("host-lab-b" + id), cnt = document.getElementById("cnt-b" + id);
    const m = new Mock(host, "lab", { page: "solar", pickMode: "top", legacyClick: legacy, onChange: () => counter(cnt, m), onNudge: () => counter(cnt, m), onPick: () => counter(cnt, m) });
    m.origin = clone(m.els()); counter(cnt, m); return m;
  };
  mocks.labB1 = mk(1, true); mocks.labB2 = mk(2, false);

  /* C: two windows */
  const server = new Server(SEED);
  const both = [];
  const opts = (n) => ({ server, page: n === 1 ? "solar" : "solar_month", sendable: true, onSent: () => both.forEach((m) => m.renderBanner()), sideExtra: (m) => h("div", { style: { padding: "8px 12px", borderTop: "0.5px solid var(--sep)" } },
    h("div", { class: "navhead", style: { padding: "4px 0" } }, "Page"),
    ...["solar", "solar_month", "temps"].map((p) => h("button", { class: "row", "aria-current": m.cur === p ? "page" : null, onclick: () => m.openPage(p) }, h("span", { class: "rmain", text: pageTitle(p) })))) });
  both.push(mocks.labC1 = new Mock(document.getElementById("host-lab-c1"), "lab", opts(1)));
  both.push(mocks.labC2 = new Mock(document.getElementById("host-lab-c2"), "lab", opts(2)));
}

/* Start on the remembered or linked section. */
const startTab = (location.hash || "").slice(1);
showTab(document.getElementById(startTab)?.getAttribute("role") === "tabpanel" ? startTab : (store.get("epaper-mock-tab") || "findings"), false);
