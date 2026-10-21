// When a page shows: the simple form (sensor, comparison, value) compiles to
// the same Home Assistant template 0.9 wrote, and reads it back. Anything the
// form can't express stays a custom template, untouched.

import { getWidgetSensorId, todoShowIf } from "./legacy.js";

const NO_VALUE = ["unavailable", "unknown"];

export const OPS = [["eq", "is"], ["ne", "isn't"], ["gt", "is above"], ["lt", "is below"], ["ge", "is at least"], ["le", "is at most"]];

export function parseShowIf(expr) {
  const s = String(expr || "").trim();
  if (!s) return { mode: "simple", ent: "", op: "eq", val: "" };
  const inner = s.startsWith("{{") && s.endsWith("}}") ? s.slice(2, -2).trim() : s;
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

export function compileShowIf({ ent, op, val }) {
  ent = String(ent || "").trim().replace(/'/g, "");
  val = String(val ?? "").trim().replace(/'/g, "");
  if (!ent) return "";
  if (op === "eq") return `{{ is_state('${ent}','${val}') }}`;
  // A sensor with no value (unavailable, unknown) never meets "isn't" or a
  // number: float(0) would read it as 0, so "below 20" came true at every restart.
  if (op === "ne") return `{{ has_value('${ent}') and not is_state('${ent}','${val}') }}`;
  const sym = { gt: ">", lt: "<", ge: ">=", le: "<=" }[op] || ">";
  const n = Number(val);
  return `{{ has_value('${ent}') and states('${ent}') | float(0) ${sym} ${isNaN(n) ? 0 : n} }}`;
}

/* Does a simple condition hold with these states? null when it can't tell. */
export function evaluate(parsed, entMap) {
  if (!parsed || parsed.mode !== "simple" || !parsed.ent) return null;
  const e = entMap.get(parsed.ent);
  if (!e) return null;
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
  const op = OPS.find(([k]) => k === p.op)?.[1] || "is";
  const unit = e?.unit ? " " + e.unit : "";
  return { text: `Shows while ${name} ${op} ${p.val}${OPS.slice(2).some(([k]) => k === p.op) ? unit : ""}`,
    why: e ? `${name} is ${e.state}${unit} now.` : `${p.ent} isn't in Home Assistant.` };
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
    const c = todoShowIf(list.entity);
    if (c) page.show_if = c; else delete page.show_if;
    return;
  }
  widgetEl = widgetEl || (page.elements || []).find((x) => ["sports_match", "sports_racing", "flight_tracker"].includes(x.type));
  if (!widgetEl) return;
  const cur = String(page.show_if || "").trim();
  if (cur && !BUILTIN_MARKERS.some((m) => cur.includes(m))) return;
  const sid = getWidgetSensorId(widgetEl);
  if (widgetEl.type === "flight_tracker") page.show_if = `{{ states('${sid}') | int(0) > 0 }}`;
  else if (sid) page.show_if = `{{ is_state('${sid}','active') }}`;
}
export function syncDynamicGridShowIf(page, gridEl) {
  if (!page || page.tier !== "when") return;
  gridEl = gridEl || (page.elements || []).find((x) => x.type === "dynamic_grid");
  if (!gridEl) return;
  const ents = (gridEl.items || []).map((x) => (x.entity || "").trim()).filter(Boolean);
  const st = (gridEl.filter_state || "on").toLowerCase();
  if (!ents.length || st === "*") delete page.show_if;
  else page.show_if = "{{ " + ents.map((e) => `is_state('${e}','${st}')`).join(" or ") + " }}";
}
