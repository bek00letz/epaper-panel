// Small shared helpers. Text always goes into the page as text (the editor
// shares an origin with Home Assistant): build nodes with h(), never with
// innerHTML from data. Only the icon constants below use innerHTML.

export function h(tag, props, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k === "style") Object.assign(n.style, v);
    else if (k === "data") Object.assign(n.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else if (k === "value") n.value = v;
    else n.setAttribute(k, v === true ? "" : v);
  }
  append(n, kids);
  return n;
}
function append(n, kids) {
  for (const c of kids) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) append(n, c);
    else n.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
}

// Glyphs drawn to SF Symbols' regular weight and 24 pt grid. Trusted constants.
const P = (d, extra = "") => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"${extra}>${d}</svg>`;
export const ICONS = {
  plus: P('<path d="M12 5v14M5 12h14"/>'),
  minus: P('<path d="M5 12h14"/>'),
  undo: P('<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>'),
  redo: P('<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>'),
  gear: P('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'),
  send: P('<path d="M12 19V5M6 11l6-6 6 6"/>'),
  layers: P('<path d="m12 3 9 5-9 5-9-5 9-5z"/><path d="m3 13 9 5 9-5"/>'),
  guides: P('<rect x="3" y="4" width="18" height="16" rx="2.5" stroke-dasharray="2.5 2.5"/><path d="M3 16h18"/>'),
  back: P('<path d="m15 18-6-6 6-6"/>'),
  chev: P('<path d="m9 6 6 6-6 6"/>'),
  down: P('<path d="m6 9 6 6 6-6"/>'),
  close: P('<path d="M6 6l12 12M18 6 6 18"/>'),
  search: P('<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>'),
  grip: P('<path d="M8 6h.01M8 12h.01M8 18h.01M16 6h.01M16 12h.01M16 18h.01"/>', ' stroke-width="2.6"'),
  trash: P('<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>'),
  dup: P('<rect x="8" y="8" width="12" height="12" rx="2.5"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/><path d="M14 11v6M11 14h6"/>'),
  moon: P('<path d="M20 14.5A8 8 0 1 1 9.5 4 6.5 6.5 0 0 0 20 14.5z"/>'),
  more: P('<circle cx="6" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="18" cy="12" r="1.3" fill="currentColor"/>'),
  clock: P('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
  sun: P('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
  sparkle: P('<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>'),
  info: P('<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>'),
  warn: P('<path d="M12 4 2.5 20h19L12 4z"/><path d="M12 10v4M12 17h.01"/>'),
  check: P('<path d="m5 12 5 5 9-10"/>'),
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
  list: P('<path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>', ' stroke-width="2"'),
  bell: P('<path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15z"/><path d="M10 21h4"/>'),
  todo: P('<rect x="3" y="4" width="5" height="5" rx="1.2"/><rect x="3" y="15" width="5" height="5" rx="1.2"/><path d="M12 6.5h9M12 17.5h9"/>'),
  grid: P('<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>'),
  play: P('<circle cx="12" cy="12" r="9"/><path d="M10 8.6v6.8l5.6-3.4z"/>'),
  plane: P('<path d="M10.5 21 12 18l1.5 3M12 3c1 0 1.5 1 1.5 2v4l7 4v2l-7-2v4l2 1.5v1.5L12 19l-3.5 1.5V19l2-1.5v-4l-7 2v-2l7-4V5c0-1 .5-2 1.5-2z"/>'),
  flag: P('<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>'),
  ball: P('<circle cx="12" cy="12" r="9"/><path d="m12 7 4 3-1.5 4.5h-5L8 10z"/>'),
  qr: P('<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><path d="M14 14h2v2M18 14h2M14 18h2v2M18 18h2v2"/>'),
  centerh: P('<path d="M12 3v18M7 8h10v8H7z"/>'),
  centerv: P('<path d="M3 12h18M8 7h8v10H8z"/>'),
  widen: P('<path d="M3 4v16M21 4v16M7 12h10M10 9l-3 3 3 3M14 9l3 3-3 3"/>'),
  alignl: P('<path d="M4 3v18M8 7h10v4H8zM8 14h6v4H8z"/>'),
  alignr: P('<path d="M20 3v18M6 7h10v4H6zM10 14h6v4h-6z"/>'),
  alignt: P('<path d="M3 4h18M7 8v10h4V8zM14 8v6h4V8z"/>'),
  alignb: P('<path d="M3 20h18M7 6v10h4V6zM14 10v6h4v-6z"/>'),
  disth: P('<path d="M4 4v16M20 4v16M10 8h4v8h-4z"/>'),
  distv: P('<path d="M4 4h16M4 20h16M8 10h8v4H8z"/>'),
  front: P('<rect x="9" y="9" width="11" height="11" rx="2" fill="currentColor"/><path d="M5 15H4V4h11v1"/>'),
  back2: P('<rect x="4" y="4" width="11" height="11" rx="2" fill="currentColor"/><path d="M19 9h1v11H9v-1"/>'),
  fwd: P('<path d="M12 19V7M7 12l5-5 5 5"/>'),
  bwd: P('<path d="M12 5v12M7 12l5 5 5-5"/>'),
  scissors: P('<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><path d="M8 7.5 20 18M8 16.5 20 6"/>'),
  copy: P('<rect x="8" y="8" width="12" height="12" rx="2.5"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>'),
  paste: P('<rect x="7" y="4" width="10" height="4" rx="1.5"/><path d="M9 6H7a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-2"/>'),
  revert: P('<path d="M4 4v6h6"/><path d="M4.5 15a8 8 0 1 0 1.9-8.3L4 10"/>'),
  eye: P('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'),
  keyboard: P('<rect x="2" y="6" width="20" height="12" rx="2.5"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>'),
  panel: P('<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M5 15h14"/>'),
  plug: P('<path d="M9 2v5M15 2v5M6 7h12v4a6 6 0 0 1-12 0V7zM12 17v5"/>'),
  key: P('<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M16 7l3 3"/>'),
  globe: P('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>'),
};
export function icon(name, cls = "") {
  const s = document.createElement("span");
  s.className = "ic" + (cls ? " " + cls : "");
  s.setAttribute("aria-hidden", "true");
  s.innerHTML = ICONS[name] || "";
  return s;
}

// Remembered per browser. A private window simply uses the defaults.
export const prefs = {
  get(k, d = null) { try { const v = localStorage.getItem("epaper_" + k); return v === null ? d : v; } catch (_) { return d; } },
  set(k, v) { try { localStorage.setItem("epaper_" + k, v); } catch (_) {} },
};

// JSON API. Errors carry the status and, for a 409, the body.
/* Which screen the editor is working on. Every add-on request says so; the
   ones that aren't about a screen ignore it. */
let currentDevice = "";
export function setDevice(id) { currentDevice = String(id || ""); }
export function getDevice() { return currentDevice; }
export function withDevice(path) {
  if (!currentDevice || !path.startsWith("api/")) return path;
  return path + (path.includes("?") ? "&" : "?") + "device=" + encodeURIComponent(currentDevice);
}

export async function api(path, opts = {}) {
  path = withDevice(path);
  const init = { method: opts.method || "GET", headers: { ...(opts.headers || {}) } };
  if (opts.body !== undefined) { init.body = JSON.stringify(opts.body); init.headers["Content-Type"] = "application/json"; }
  let r;
  try { r = await fetch(path, init); } catch (_) {
    throw Object.assign(new Error("The add-on isn't answering. Check that it's running."), { status: 0 });
  }
  if (opts.raw) { if (!r.ok) throw Object.assign(new Error(await r.text() || r.statusText), { status: r.status }); return r; }
  const text = await r.text().catch(() => "");
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch (_) {}
  if (!r.ok) {
    // The add-on says why in plain text ("There's already a screen called Kitchen."); its
    // framework's own "400: Bad Request" says nothing, so that gets our words instead.
    const said = !body && text.trim() && text.length <= 300 && !/^\d{3}: /.test(text.trim()) ? text.trim() : "";
    const msg = (body && body.error) || said || (r.status === 400 ? "The add-on couldn't read that." : `The add-on answered ${r.status}.`);
    throw Object.assign(new Error(msg), { status: r.status, body });
  }
  return { body, etag: (r.headers.get("ETag") || "").replace(/^W\//, "").replace(/"/g, "") };
}

export const clone = (o) => JSON.parse(JSON.stringify(o));
/* Equal as data: an object by its keys and values, whatever order its keys were written in (the
   add-on and the editor write a page's in different orders, and that alone isn't a change);
   an array keeps its order. */
const sorted = (_, v) => (v && typeof v === "object" && !Array.isArray(v) ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, v[k]])) : v);
export const same = (a, b) => JSON.stringify(a ?? null, sorted) === JSON.stringify(b ?? null, sorted);
export const slug = (s) => String(s || "").trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 64);
export const pageTitle = (n) => String(n || "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
export const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
export const modKey = isMac ? "⌘" : "Ctrl+";
export const nowHM = (t) => { const d = t ? new Date(t * 1000) : new Date(); return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); };
// A screen's timers in words (timing.py): minutes as people say them, and how its pages turn.
export const span = (m) => (m === 1 ? "1 minute" : m < 60 ? `${m} minutes` : m === 60 ? "1 hour" : `${+(m / 60).toFixed(1)} hours`);
export const seconds = (s) => (s < 60 ? `${s} seconds` : span(s / 60));
export function turning(t) {
  if (!t) return "";
  if (t.always_on) return `each page for ${seconds(t.rotate_seconds)}`;
  return `the next page every ${span(t.update_minutes * t.rotate_updates)}`;
}
export function uid() { return Math.random().toString(36).slice(2, 9); }
