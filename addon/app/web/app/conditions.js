// When a page shows: the simple form (sensor, comparison, value) compiles to
// the same Home Assistant template 0.9 wrote, and reads it back. Anything the
// form can't express stays a custom template, untouched.

import { getWidgetSensorId, todoShowIf } from "./legacy.js";
import { widget, stateWords } from "./catalog.js";

const NO_VALUE = ["unavailable", "unknown"];

export const OPS = [["eq", "is"], ["ne", "isn't"], ["gt", "is above"], ["lt", "is below"], ["ge", "is at least"], ["le", "is at most"], ["changed", "changed"]];
// How long a page stays after a change, to start with (conditions.CHANGED_DEFAULT).
export const CHANGED_MINUTES = 30;

export function parseShowIf(expr) {
  const s = String(expr || "").trim();
  if (!s) return { mode: "simple", ent: "", op: "eq", val: "" };
  const inner = s.startsWith("{{") && s.endsWith("}}") ? s.slice(2, -2).trim() : s;
  const c = parseChanged(inner);
  if (c) return c;
  // The no-value guard compileShowIf adds, on the same sensor; conditions saved
  // before it read the same.
  const g = inner.match(/^has_value\(\s*'([^']+)'\s*\)\s+and\s+(.*)$/);
  const p = parseSimple(g ? g[2] : inner);
  return p && (!g || p.ent === g[1]) ? p : { mode: "raw", raw: s };
}

function parseSimple(inner) {
  let m = inner.match(/^is_state\(\s*'([^']+)'\s*,\s*'([^']*)'\s*\)$/);
  if (m) return { mode: "simple", ent: m[1], op: "eq", val: m[2] };
  m = inner.match(/^not\s+is_state\(\s*'([^']+)'\s*,\s*'([^']*)'\s*\)$/);
  if (m) return { mode: "simple", ent: m[1], op: "ne", val: m[2] };
  m = inner.match(/^states\(\s*'([^']+)'\s*\)\s*\|\s*(?:int|float)\([^)]*\)\s*(>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)$/);
  if (m) return { mode: "simple", ent: m[1], op: { ">": "gt", "<": "lt", ">=": "ge", "<=": "le" }[m[2]], val: m[3] };
  return null;
}

// "Changed": the add-on answers it from the sensor's history, so a restart or a
// sensor coming back from unavailable with the same value isn't a change
// (conditions.changed, sources/changes.py). Written as the nearest Home Assistant
// template; "to" a value is optional.
function parseChanged(inner) {
  const m = inner.match(/^(?:has_value\(\s*'([^']+)'\s*\)|is_state\(\s*'([^']+)'\s*,\s*'([^']*)'\s*\))\s+and\s+now\(\)\s*-\s*states\['([^']+)'\]\.last_changed\s*<\s*timedelta\(\s*minutes\s*=\s*(\d+)\s*\)$/);
  if (!m || (m[1] || m[2]) !== m[4]) return null;
  return { mode: "simple", ent: m[4], op: "changed", val: m[2] ? m[3] : "", minutes: Number(m[5]) };
}

export function compileShowIf({ ent, op, val, minutes }) {
  ent = String(ent || "").trim().replace(/'/g, "");
  val = String(val ?? "").trim().replace(/'/g, "");
  if (!ent) return "";
  if (op === "changed") {
    const n = Math.max(1, Math.min(1440, Math.round(Number(minutes)) || CHANGED_MINUTES));
    const which = val ? `is_state('${ent}','${val}')` : `has_value('${ent}')`;
    return `{{ ${which} and now() - states['${ent}'].last_changed < timedelta(minutes=${n}) }}`;
  }
  if (op === "eq") return `{{ is_state('${ent}','${val}') }}`;
  // A sensor with no value (unavailable, unknown) never meets "isn't" or a
  // number: float(0) would read it as 0, so "below 20" came true at every restart.
  if (op === "ne") return `{{ has_value('${ent}') and not is_state('${ent}','${val}') }}`;
  const sym = { gt: ">", lt: "<", ge: ">=", le: "<=" }[op] || ">";
  const n = Number(val);
  return `{{ has_value('${ent}') and states('${ent}') | float(0) ${sym} ${isNaN(n) ? 0 : n} }}`;
}

/* The values a condition on this entity offers as chips: [{ state, word }]. Home Assistant's own
   for its kind (the catalog, so they show at once), then the states the add-on says it has
   (`offered`, from GET /api/entity_states: its options and what it was), one per state whatever
   its case. The kind's come first in both, so the answer only adds chips at the end. A no-value
   state is never one. */
export function valueChoices(entityId, deviceClass, offered) {
  const kind = stateWords(entityId, deviceClass) || {};
  const out = [], keys = new Set();
  const add = (state, word) => {
    const k = String(state ?? "").trim().toLowerCase();
    if (!k || NO_VALUE.includes(k) || keys.has(k)) return;
    keys.add(k);
    out.push({ state: String(state).trim(), word: word || kind[state]?.word || String(state).trim() });
  };
  for (const [st, w] of Object.entries(kind)) add(st, w?.word);
  for (const o of Array.isArray(offered) ? offered : []) if (o) add(o.state, o.word);
  return out;
}

/* Does a simple condition hold with these states? null when it can't tell. */
export function evaluate(parsed, entMap) {
  if (!parsed || parsed.mode !== "simple" || !parsed.ent) return null;
  const e = entMap.get(parsed.ent);
  if (!e || parsed.op === "changed") return null;     // the add-on knows (changedLine)
  const s = String(e.state), v = parsed.val;
  if (parsed.op === "eq") return s === v;
  if (NO_VALUE.includes(s)) return false;
  if (parsed.op === "ne") return s !== v;
  const a = Number(s), b = Number(v);
  if (isNaN(a)) return false;
  return { gt: a > b, lt: a < b, ge: a >= b, le: a <= b }[parsed.op] ?? null;
}

/* In words: "Shows while Dryer is active." and why it's hidden now. */
export function describe(showIf, entMap) {
  const p = parseShowIf(showIf);
  if (p.mode === "raw") return { text: "Shows while its custom condition is true", why: "Its condition is false right now." };
  if (!p.ent) return { text: "Choose when it shows", why: "" };
  const e = entMap.get(p.ent);
  const name = e?.name || p.ent;
  if (p.op === "changed") return { text: `Shows for ${minutesInWords(p.minutes)} after ${name} changes${p.val ? " to " + p.val : ""}`, why: "It hasn't changed in that time." };
  const op = OPS.find(([k]) => k === p.op)?.[1] || "is";
  const unit = e?.unit ? " " + e.unit : "";
  return { text: `Shows while ${name} ${op} ${p.val}${OPS.slice(2).some(([k]) => k === p.op) ? unit : ""}`,
    why: e ? `${name} is ${e.state}${unit} now.` : `${p.ent} isn't in Home Assistant.` };
}

const minutesInWords = (m) => (m === 1 ? "1 minute" : m < 60 || m % 60 ? `${m} minutes` : m === 60 ? "1 hour" : `${m / 60} hours`);
const ago = (s) => (s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)} min ago` : `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min ago`.replace(" 0 min", ""));

/* The status line under a "changed" condition, from the add-on's answer (GET
   api/changed: {state, at, to, history, now}, epoch seconds on its clock).
   `minutes` is the window: the page's own, or an alert's hold. `alert` is
   "time", "until" or "" (a page). {holds, text, note}; null for no answer. */
export function changedLine(parsed, got, { minutes, alert = "" } = {}) {
  if (!got || parsed?.op !== "changed") return null;
  const n = minutes || parsed.minutes || CHANGED_MINUTES;
  const since = got.at == null ? null : Math.max(0, got.now - got.at);
  const noValue = NO_VALUE.includes(String(got.state)) || got.state == null;
  const fits = since != null && since < n * 60 && !noValue && (!parsed.val || String(got.state) === parsed.val);
  const note = got.history === false ? "Home Assistant keeps no history for this sensor, so its restarts count as changes too." : "";
  if (fits) {
    const left = Math.max(1, Math.ceil((n * 60 - since) / 60));
    const more = left === 1 ? "1 more minute" : `${left} more minutes`;
    const then = alert === "until" ? "it's showing until something happens" : `it shows for ${more}`;
    return { holds: true, text: `Changed to ${got.to ?? got.state} ${ago(since)}, so ${then}.`, note };
  }
  const to = parsed.val ? ` to ${parsed.val}` : "";
  if (alert) return { holds: false, text: `Waiting for a change${to}.`, note };
  if (since != null && since < n * 60 && got.to) return { holds: false, text: `Hidden now: it changed to ${got.to} ${ago(since)}.`, note };
  return { holds: false, text: `Hidden now: no change${to} in the last ${minutesInWords(n)}.`, note };
}

/* Widgets that bring their own "when" (from 0.9, unchanged in effect). */
const BUILTIN_MARKERS = ["sensor.epaper_sports_", "sensor.sports_", "sensor.epaper_racing_", "sensor.f1_status", "sensor.formula_e_status", "sensor.epaper_flights_overhead", "sensor.overhead_aircraft_count"];
export function syncWidgetShowIf(page, widgetEl) {
  if (!page || page.tier !== "when") return;
  const list = widgetEl?.type === "todo_list" ? widgetEl : !widgetEl && (page.elements || []).find((x) => x.type === "todo_list");
  if (list) {
    // Ours to rewrite only while it's still a to-do list's own condition.
    const cur = parseShowIf(page.show_if);
    if (page.show_if && !(cur.mode === "simple" && /^(todo\.|sensor\.epaper_todo_)/.test(cur.ent))) return;
    const c = todoShowIf(list.entity, list.show);
    if (c) page.show_if = c; else delete page.show_if;
    return;
  }
  // A widget that shows only around its events says so in its descriptor ("window": the add-on's).
  widgetEl = widgetEl || (page.elements || []).find((x) => x.type !== "todo_list" && widget(x.type)?.window);
  if (!widgetEl) return;
  const cur = String(page.show_if || "").trim();
  if (cur && !BUILTIN_MARKERS.some((m) => cur.includes(m))) return;
  const sid = getWidgetSensorId(widgetEl);
  if (widgetEl.type === "flight_tracker") page.show_if = `{{ states('${sid}') | int(0) > 0 }}`;
  else if (sid) page.show_if = `{{ is_state('${sid}','active') }}`;
}
/* What a Dynamic status grid shows by (render/layout._draw_dynamic_grid): a state, or a number,
   "below" a value or "at_least" one; an item may have its own `threshold`. */
export const GRID_RULES = [["on", "On"], ["off", "Off"], ["*", "Any state"], ["below", "Below a number"], ["at_least", "At least a number"]];
export const gridByNumber = (el) => el?.filter_rule === "below" || el?.filter_rule === "at_least";
export const gridRule = (el) => (gridByNumber(el) ? el.filter_rule : String(el?.filter_state || "on").toLowerCase());

/* The page's condition a grid writes: any item in its state, or past its number. A number is
   guarded as compileShowIf guards one, so a sensor with no value never counts as 0. "" when the
   grid shows something whatever happens (any state), or has nothing to watch. */
export function gridShowIf(gridEl) {
  const items = (gridEl?.items || []).filter((x) => String(x.entity || "").trim());
  if (!items.length) return "";
  if (gridByNumber(gridEl)) {
    const sym = gridEl.filter_rule === "below" ? "<" : ">=";
    const parts = items.map((x) => {
      const e = String(x.entity).trim().replace(/'/g, ""), own = x.threshold;
      const t = Number(own !== undefined && own !== null && own !== "" ? own : gridEl.filter_value);
      return isNaN(t) ? "" : `(has_value('${e}') and states('${e}') | float(0) ${sym} ${t})`;
    }).filter(Boolean);
    return parts.length ? "{{ " + parts.join(" or ") + " }}" : "";
  }
  const st = String(gridEl.filter_state || "on").toLowerCase();
  if (st === "*") return "";
  return "{{ " + items.map((x) => `is_state('${String(x.entity).trim()}','${st}')`).join(" or ") + " }}";
}
// A condition this grid wrote, and nobody changed: only the parts a grid writes, joined by "or", at
// least one on its sensors (a sensor just taken off the grid is still in the condition it wrote).
const GRID_PART = /^(?:is_state\('([^']+)','[^']*'\)|\(has_value\('([^']+)'\) and states\('\2'\) \| float\(0\) (?:<|>=) -?\d+(?:\.\d+)?\))$/;
export function gridWrote(expr, gridEl) {
  const s = String(expr || "").trim();
  if (!s.startsWith("{{") || !s.endsWith("}}")) return false;
  const mine = new Set((gridEl?.items || []).map((x) => String(x.entity || "").trim()).filter(Boolean));
  const parts = s.slice(2, -2).trim().split(/\s+or\s+(?=is_state|\(has_value)/).map((part) => part.trim().match(GRID_PART));
  return parts.every(Boolean) && parts.some((m) => mine.has(m[1] || m[2]));
}

/* The page shows while its grid shows something: "Only when" always follows the grid; an alert
   follows it while its condition is the grid's own (or empty), so one you wrote yourself stays. */
export function syncDynamicGridShowIf(page, gridEl) {
  if (!page || (page.tier !== "when" && page.tier !== "alert")) return;
  gridEl = gridEl || (page.elements || []).find((x) => x.type === "dynamic_grid");
  if (!gridEl) return;
  if (page.tier === "alert" && page.show_if && !gridWrote(page.show_if, gridEl)) return;
  const s = gridShowIf(gridEl);
  if (s) page.show_if = s;
  else if (page.tier === "when") delete page.show_if;
}
