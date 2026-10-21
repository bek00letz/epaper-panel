// Where a text or value gets what it shows ("From" in the inspector's Shows
// section): Text, a Sensor, the Time (the add-on's clock) or a Template. Read
// the way the renderer reads it (render/binding.template_for: a template in
// `value` wins), and every choice reachable from every other. No imports from
// util.js: the tests read this file under node.

export const FROM = [["text", "Text"], ["sensor", "Sensor"], ["clock", "Time"], ["template", "Template"]];
// The add-on's own clock's formats (render/binding.TIME_FORMATS); "time" follows the 12/24-hour setting.
export const CLOCK_FORMATS = [["time", "The time"], ["day_full", "Weekday and date"], ["day_date", "Short weekday and date"], ["date", "Date"], ["datetime", "Date and time"]];

export const isTemplate = (v) => typeof v === "string" && /\{[{%]/.test(v);

export function sourceOf(el) {
  if (isTemplate(el.value)) return "template";
  if (el.type === "text" && el.show === "now" && !el.entity) return "clock";
  if (el.value !== undefined && el.value !== null && String(el.value).trim()) return "text";   // what it says wins, as on the panel
  if ("entity" in el || el.type === "number") return "sensor";                // "": a sensor still to choose
  return "text";
}

/* The entities a template reads: states('x.y'), is_state("x.y", …), states.x.y, states['x.y'].
   With `known` (a Set or Map of entity IDs), only those that exist. */
export function templateEntities(tpl, known) {
  const out = new Set(), t = String(tpl || "");
  for (const m of t.matchAll(/['"]([a-z_]+\.[a-z0-9_]+)['"]/g)) out.add(m[1]);
  for (const m of t.matchAll(/\bstates\.([a-z_]+)\.([a-z0-9_]+)/g)) out.add(`${m[1]}.${m[2]}`);
  return [...out].filter((id) => !known || !known.size || known.has(id));
}

/* Switch an element to `to`. Template is written out by the add-on (api/as_template), so it
   comes in as `template`. Returns "pick" when it needs a sensor chosen, else "". */
export function switchSource(el, to, { known, template } = {}) {
  const was = el.value;
  if (to !== "clock" && el.show === "now") delete el.show;
  if (to === "clock") {
    el.type = "text"; el.show = "now";
    el.format = CLOCK_FORMATS.some(([f]) => f === el.format) ? el.format : "time";
    delete el.value; delete el.entity;
  } else if (to === "text") {
    el.value = typeof was === "string" && was.trim() && !isTemplate(was) ? was : "Label";
    delete el.entity;
  } else if (to === "sensor") {
    delete el.value;
    // The one sensor the template reads, over one the element had before; none or several: ask.
    const found = isTemplate(was) ? templateEntities(was, known) : [];
    if (found.length === 1) el.entity = found[0];
    else if (!el.entity) el.entity = "";
    return el.entity ? "" : "pick";
  } else if (to === "template") {
    el.value = isTemplate(was) ? was : template || `{{ '${String(was ?? "").replace(/\\/g, "\\\\").replace(/'/g, "\\'")}' }}`;
  }
  return "";
}
