// The inspector: shows what's selected, or the page when nothing is.
// Most-used first (what it shows, how it looks), then arrangement, then
// "More" for the rare things. Every setting 0.9 had is here.

import { h, icon, api, clone, pageTitle, slug, modKey } from "./util.js";
import { field, input, number, select, seg, textarea, toggle, toggleRow, section, linkButton, toast } from "./ui.js";
import { TYPES, BREAKABLE, isWidget, hasText, elName, normalizeLineParity } from "./elements.js";
import { OPS, parseShowIf, compileShowIf, evaluate, describe, syncWidgetShowIf, syncDynamicGridShowIf } from "./conditions.js";
import { explodeWidget, getWidgetSensorId, suggestIconForEntity } from "./legacy.js";

const SHOWS = [["state", "Its value"], ["unit", "Its unit, following the value"], ["attribute", "One of its details"], ["last_changed", "When it last changed"], ["last_updated", "When it last updated"],
  ["days_until", "Days until it"], ["date_formatted", "Its date"], ["calendar_title", "The event's name"]];
const FORMATS = [["relative", "2 hours ago"], ["date", "3 Mar"], ["day_date", "Thu, 24 Oct"], ["day_full", "Thursday, 24 Oct"], ["time", "14:05"], ["time_12", "2:05 PM"], ["datetime", "Date and time"]];
const FONTS = [["lato", "Lato"], ["dejavu", "DejaVu Sans"], ["mono", "Roboto Mono"]];
const KNOWN_STATES = { binary_sensor: ["on", "off"], switch: ["on", "off"], light: ["on", "off"], input_boolean: ["on", "off"], fan: ["on", "off"],
  timer: ["active", "idle", "paused"], person: ["home", "not_home"], device_tracker: ["home", "not_home"], lock: ["locked", "unlocked"],
  cover: ["open", "closed"], media_player: ["playing", "paused", "idle", "off"], alarm_control_panel: ["armed_away", "armed_home", "disarmed", "triggered"] };

export function renderInspector(app) {
  const doc = app.doc;
  const head = h("div", { class: "insp-head" });
  const body = h("div", { class: "insp-body" });
  const els = doc.els();
  if (!doc.page()) {
    head.append(h("div", { class: "ttl" }, h("span", { class: "kind", text: "Pages" }), "No pages yet"));
    body.append(h("p", { class: "empty-note", text: "Start with a preset or a blank page, from the + at the end of the page strip." }));
  } else if (doc.sel.length > 1) multi(app, head, body);
  else if (doc.sel.length === 1 && els[doc.sel[0]]) element(app, head, body, els[doc.sel[0]], doc.sel[0]);
  else page(app, head, body);
  return [head, body];
}

/* ---------- shared bits ---------- */
function setter(app, el, after) {
  return (k, v, kind) => {
    if (v === "" || v === undefined || v === null) delete el[k]; else el[k] = v;
    if (after) after(k, v);
    app.doc.commit(kind);
  };
}
function entityButton(app, entityId, onPick, opts = {}) {
  const e = entityId ? app.entMap.get(entityId) : null;
  const b = h("button", { class: "entbtn", "aria-label": `${opts.label || "Sensor"}: ${e ? e.name : entityId || "none"}. Change` },
    h("span", { class: "eb-text" }, h("span", { class: "e1", text: e ? (e.name || entityId) : entityId || opts.placeholder || "Choose a sensor" }),
      entityId ? h("span", { class: "e2", text: entityId }) : null),
    e ? h("span", { class: "ev", text: `${e.state}${e.unit ? " " + e.unit : ""}` }) : null,
    icon("chev", "sm"));
  b.addEventListener("click", () => app.openEntityPicker(b, onPick, { domains: opts.domains, current: entityId, allowNone: opts.allowNone }));
  return b;
}
function iconButton(app, value, onPick, label = "Icon") {
  const glyph = app.mdiGlyph(value);
  const b = h("button", { class: "iconbtn", "aria-label": `${label}: ${value || "none"}. Change` },
    h("span", { class: "glyph mdi", text: glyph || "?" }), h("span", { class: "e1", text: value ? String(value).replace(/^mdi:/, "") : "Choose an icon" }), icon("chev", "sm"));
  b.addEventListener("click", () => app.openIconPicker(value, onPick));
  return b;
}
function legibility(app, i, el) {
  const m = app.canvas.metrics.find((x) => x.i === i);
  if (!m) return null;
  const out = [];
  if (m.not_a_number !== undefined) out.push(h("div", { class: "note bad", role: "note" }, icon("warn", "sm"), h("span", { text: `“${m.not_a_number}” isn't a number, so the panel shows --. Treat it as text instead.` }),
    linkButton("Treat as text", () => { el.type = "text"; app.doc.commit(); }, { class: "linkbtn inline" })));
  if (m.collection) out.push(h("div", { class: "note bad", role: "note" }, icon("warn", "sm"), h("span", { text: "That's a list, not one value. Pick a different detail, or show its value." })));
  const dist = Number(app.prefs.get("view_dist", "3.0"));
  if (dist > 0) {
    const good = /comfortable|effortless/.test(m.verdict);
    const verdict = m.verdict.replace(/ at [\d.]+m$/, "");
    out.push(h("div", { class: "note " + (good ? "good" : "warn"), role: "note" }, h("span", { class: "led" }),
      h("span", { text: `${m.size} px, ${m.mm} mm tall: ${verdict} from ${dist} m` })));
  }
  if (m.overflow) out.push(h("div", { class: "note warn", role: "note" }, icon("warn", "sm"), h("span", { text: el.wrap ? "Too long for its box, even wrapped." : "Wider than its box, so it's cut off." }),
    !el.wrap && el.type === "text" ? linkButton("Wrap it", () => { el.wrap = true; app.doc.commit(); }, { class: "linkbtn inline" }) : null,
    el.size ? linkButton("Fit the box", () => { delete el.size; app.doc.commit(); }, { class: "linkbtn inline" }) : null));
  return out;
}
function styleRows(app, el, set) {
  const style = el.invert ? "invert" : el.pill ? "pill" : "plain";
  const rows = [h("div", { class: "field" }, h("span", { class: "lab", text: "Style" }), seg([["plain", "Plain"], ["invert", "Inverted"], ["pill", "Outlined"]], style, (v) => {
    delete el.invert; delete el.pill;
    if (v === "invert") el.invert = true; if (v === "pill") el.pill = true;
    app.doc.commit();
  }, "Style"))];
  if (el.invert || el.pill) rows.push(field("Corners", number(el.radius ?? 10, (v) => set("radius", v), { min: "0", max: "60", placeholder: "10" })));
  return rows;
}

/* ---------- element ---------- */
function element(app, head, body, el, i) {
  const { t, d } = elName(el, app.entMap);
  head.append(h("div", { class: "ttl" }, h("span", { class: "kind" }, icon(TYPES[el.type]?.icon || "square", "xs"), t), h("span", { class: "tname", text: d || t })));
  const set = setter(app, el);
  const doc = app.doc, g = app.geometry();

  if (hasText(el)) {
    body.append(shows(app, el, set));
    body.append(section("Text",
      field("Size", number(el.size, (v) => set("size", v), { min: "8", max: "360", placeholder: "Fits the box" })),
      legibility(app, i, el),
      toggleRow("Wrap onto more lines", !!el.wrap, (v) => set("wrap", v ? true : "")),
      field("Font", select(FONTS, el.font || "lato", (v) => set("font", v === "lato" ? "" : v))),
      h("div", { class: "field" }, h("span", { class: "lab", text: "Weight" }), seg([["bold", "Bold"], ["regular", "Regular"]], el.bold === false ? "regular" : "bold", (v) => set("bold", v === "regular" ? false : ""), "Weight")),
      h("div", { class: "field" }, h("span", { class: "lab", text: "Align" }), seg([["left", "Left", "alignl"], ["center", "Centre", "centerh"], ["right", "Right", "alignr"]], el.align || "left", (v) => set("align", v === "left" ? "" : v), "Alignment")),
      styleRows(app, el, set)));
  } else if (el.type === "icon") {
    body.append(section("Icon",
      iconButton(app, el.icon, (ic) => set("icon", ic)),
      field("Size", number(el.size, (v) => set("size", v), { min: "8", max: "360", placeholder: "Fits the box" })),
      legibility(app, i, el), styleRows(app, el, set)));
  } else {
    body.append(...typeSections(app, el, set, i));
  }

  if (isWidget(el)) {
    const scale = Number(el.font_scale || 1);
    const pct = h("output", { class: "rangeval", text: Math.round(scale * 100) + "%" });
    const r = h("input", { type: "range", class: "range", min: "0.7", max: "1.6", step: "0.05", value: String(scale), list: "fscale-ticks", "aria-label": "Text size" });
    r.addEventListener("input", () => { pct.textContent = Math.round(r.value * 100) + "%"; });
    r.addEventListener("change", () => set("font_scale", Number(r.value) === 1 ? "" : Number(r.value)));
    body.append(section("Text size", h("div", { class: "rangerow" }, h("span", { class: "rmin", "aria-hidden": "true", text: "A" }), r, h("span", { class: "rmax", "aria-hidden": "true", text: "A" }), pct),
      BREAKABLE.includes(el.type) ? h("div", { class: "btnrow" }, h("button", { class: "btn tinted", onclick: () => {
        const parts = explodeWidget(el);
        if (!parts.length) return;
        doc.els().splice(i, 1, ...parts);
        doc.sel = parts.map((_, k) => i + k);
        doc.commit();
        toast(`Broken into ${parts.length} elements you can move one by one.`, { label: "Undo", run: () => doc.undo() });
      } }, "Break apart")) : null,
      BREAKABLE.includes(el.type) ? h("p", { class: "fnote", text: "Turns the widget into plain text, values and icons you can move and restyle one by one." }) : null));
  }

  // Arrange
  const n = doc.els().length;
  const quad = h("div", { class: "quad" }, ...[["x", "X"], ["y", "Y"], ["w", "Width"], ["h", "Height"]].map(([k, l]) =>
    h("label", { class: "qcell" }, number(el[k], (v) => { el[k] = Math.round(Number(v) || 0); if (k === "w" || k === "h") el[k] = Math.max(1, el[k]); app.doc.commit(); }, { "aria-label": l }), h("span", { text: l }))));
  const centreX = () => { if (el.type === "line" && el.h >= el.w) normalizeLineParity(el, g.W / 2, "x"); else { if (el.type === "icon" && el.w % 2) el.w += 1; el.x = Math.round(g.W / 2 - el.w / 2); } doc.commit(); };
  const centreY = () => { if (el.type === "line" && el.w > el.h) normalizeLineParity(el, g.safeH / 2, "y"); else { if (el.type === "icon" && el.h % 2) el.h += 1; el.y = Math.round(g.safeH / 2 - el.h / 2); } doc.commit(); };
  body.append(section("Arrange", quad,
    h("div", { class: "btnrow icons" },
      h("button", { class: "btn icon tinted", "aria-label": "Centre across", title: "Centre across", onclick: centreX }, icon("centerh")),
      h("button", { class: "btn icon tinted", "aria-label": "Centre up and down, above the footer", title: "Centre up and down", onclick: centreY }, icon("centerv")),
      h("button", { class: "btn icon tinted", "aria-label": "Full width, inside the margins", title: "Full width", onclick: () => { el.x = g.margin; el.w = g.W - g.margin * 2; doc.commit(); } }, icon("widen")),
      h("span", { class: "spacer" }),
      h("span", { class: "layerpos", text: `Layer ${n - i} of ${n}`, title: "1 is the front" })),
    h("div", { class: "btnrow icons" },
      h("button", { class: "btn icon tinted", "aria-label": "Send to back", title: `Send to back  ⌥${modKey}[`, disabled: i === 0, onclick: () => app.order("back") }, icon("back2")),
      h("button", { class: "btn icon tinted", "aria-label": "Send backward", title: `Send backward  ${modKey}[`, disabled: i === 0, onclick: () => app.order("bwd") }, icon("bwd")),
      h("button", { class: "btn icon tinted", "aria-label": "Bring forward", title: `Bring forward  ${modKey}]`, disabled: i === n - 1, onclick: () => app.order("fwd") }, icon("fwd")),
      h("button", { class: "btn icon tinted", "aria-label": "Bring to front", title: `Bring to front  ⌥${modKey}]`, disabled: i === n - 1, onclick: () => app.order("front") }, icon("front")),
      h("span", { class: "spacer" }),
      linkButton("Layers", () => app.showLayers(true)))));

  const more = h("details", { class: "more" }, h("summary", {}, icon("chev", "sm"), "More"),
    field("Only show if", textarea(el.show_if, (v) => set("show_if", v.trim())), { wide: true, note: "A Home Assistant template. The element is drawn only while it's true." }));
  if (app.prefs.get("more_open") === "1") more.open = true;
  more.addEventListener("toggle", () => app.prefs.set("more_open", more.open ? "1" : "0"));
  body.append(section(null, more));
  body.append(section(null, h("div", { class: "btnrow" },
    h("button", { class: "btn tinted", onclick: () => app.duplicate() }, icon("dup", "sm"), "Duplicate"),
    h("button", { class: "btn tinted danger", onclick: () => app.remove() }, icon("trash", "sm"), "Delete"))));
}

/* What a text or value shows. */
function shows(app, el, set) {
  const tpl = typeof el.value === "string" && /\{[{%]/.test(el.value);
  const source = el.entity && !el.value ? "sensor" : tpl ? "template" : el.value !== undefined && !el.entity ? "text" : el.entity ? "sensor" : el.type === "number" ? "sensor" : "text";
  const s = section("Shows", h("div", { class: "field" }, h("span", { class: "lab", text: "From" }), seg([["text", "Text"], ["sensor", "Sensor"], ["template", "Template"]], source, (v) => {
    if (v === "text") { el.value = el.value && !/\{[{%]/.test(el.value) ? el.value : "Label"; delete el.entity; }
    if (v === "sensor") { delete el.value; }
    if (v === "template") { el.value = el.value && /\{[{%]/.test(el.value) ? el.value : `{{ states('${el.entity || "sensor.example"}') }}`; }
    app.doc.commit();
  }, "Shows")));
  if (source === "text") {
    s.append(field("Text", input(el.value, (v) => set("value", v), { placeholder: "What it says" })));
  } else if (source === "template") {
    s.append(field("Template", textarea(el.value, (v) => set("value", v)), { wide: true, note: "Anything Home Assistant can render." }));
  } else {
    s.append(entityButton(app, el.entity, (id) => {
      el.entity = id;
      const e = app.entMap.get(id);
      if (el.type === "number" && e && e.unit && !el.suffix) el.suffix = " " + e.unit;
      app.doc.commit();
    }));
    const show = el.show || "state";
    s.append(field("Show", select(SHOWS, show, (v) => {
      if (v === "unit") { showUnit(app, el); return; }
      set("show", v === "state" ? "" : v);
    })));
    if (show === "attribute") {
      const b = h("button", { class: "entbtn", "aria-label": `Detail: ${el.attribute || "none"}. Change` },
        h("span", { class: "eb-text" }, h("span", { class: "e1", text: el.attribute || "Choose a detail" })), icon("chev", "sm"));
      b.addEventListener("click", () => app.openAttributePicker(b, el.entity, (a) => {
        // Its unit is better shown as the unit that follows the value.
        if (a === "unit_of_measurement" || a === "unit") { showUnit(app, el, true); return; }
        set("attribute", a);
      }));
      s.append(field("Detail", b));
    }
    if (["last_changed", "last_updated", "date_formatted"].includes(show)) {
      s.append(field("Looks like", select(FORMATS, el.format || (show === "date_formatted" ? "date" : "relative"), (v) => set("format", v))));
    }
    s.append(h("div", { class: "pair" },
      field("Before", input(el.prefix, (v) => set("prefix", v), { placeholder: "nothing" })),
      field("After", input(el.suffix, (v) => set("suffix", v), { placeholder: "nothing" }))));
    s.append(h("div", { class: "field" }, h("span", { class: "lab", text: "As" }), seg([["number", "A number"], ["text", "Text"]], el.type, (v) => {
      el.type = v; if (v === "number" && el.decimals === undefined) el.decimals = 1; app.doc.commit();
    }, "Treat the value as")));
    if (el.type === "number") {
      s.append(h("div", { class: "pair" },
        field("Decimals", number(el.decimals, (v) => set("decimals", v), { min: "0", max: "6", placeholder: "1" })),
        field("If missing", input(el.fallback, (v) => set("fallback", v), { placeholder: "--" }))));
      const u = unitsRows(app, el, set); if (u) s.append(u);
    } else if (show === "unit") {
      const u = unitsRows(app, el, set); if (u) s.append(u);
    }
    s.append(replacements(app, el));
  }
  return s;
}

/* Show the sensor's unit as the word it uses right now (950 W, then kW). */
function showUnit(app, el, fromDetail) {
  const u = app.entMap.get(el.entity)?.unit || el.units?.base || String(el.suffix || "").trim();
  el.show = "unit"; el.type = "text"; delete el.attribute; delete el.decimals;
  if (u && !el.units) el.units = { base: u, mode: "scale", decimals: 2 };
  app.doc.commit();
  if (fromDetail) toast("Showing its unit, which steps up with the value. Set that under Units.");
}

/* Dynamic units: filled in by the units step (see units.js). */
function unitsRows(app, el, set) { return app.unitsRows ? app.unitsRows(el, set) : null; }

function replacements(app, el) {
  const reps = Object.entries(el.replace || {});
  const wrap = h("details", { class: "more" }, h("summary", {}, icon("chev", "sm"), reps.length ? `Says it differently (${reps.length})` : "Say it differently"));
  if (reps.length) wrap.open = true;
  const rows = h("div", { class: "reps" });
  const commit = () => {
    const out = {};
    rows.querySelectorAll(".rep").forEach((r) => { const [k, v] = r.querySelectorAll("input"); if (k.value.trim()) out[k.value.trim()] = v.value; });
    if (Object.keys(out).length) el.replace = out; else delete el.replace;
    app.doc.commit();
  };
  const row = (k, v) => h("div", { class: "rep" },
    h("input", { class: "inp", value: k, placeholder: "When it says", "aria-label": "When it says", onchange: commit }),
    icon("chev", "sm"),
    h("input", { class: "inp", value: v, placeholder: "Show", "aria-label": "Show instead", onchange: commit }));
  reps.forEach(([k, v]) => rows.append(row(k, v)));
  rows.append(row("", ""));
  wrap.append(h("p", { class: "fnote", text: "For example, when it says on, show Running." }), rows);
  return wrap;
}

/* ---------- per-type settings for everything that isn't text ---------- */
const F = {
  entity: (key, label, domains) => ({ kind: "entity", key, label, domains }),
  text: (key, label, ph) => ({ kind: "text", key, label, ph }),
  num: (key, label, ph, min, max, step) => ({ kind: "num", key, label, ph, min, max, step }),
  sel: (key, label, options, def) => ({ kind: "sel", key, label, options, def }),
  on: (key, label, def) => ({ kind: "toggle", key, label, def }),
};
const BORDER_ON = F.on("show_border", "Border", true);
const TYPE_FIELDS = {
  box: [F.sel("fill", "Fill", [["outline", "Outline"], ["black", "Black"], ["screen", "Half tone"], ["white", "White"]], "outline"), F.num("radius", "Corners", "12", 0, 120), F.num("thickness", "Border", "3", 1, 20)],
  bar: [F.entity("entity", "Sensor"), F.text("title", "Title", "Battery"), F.sel("bar_style", "Style", [["solid", "Solid"], ["segmented", "Segments"], ["vertical", "Upright"]], "solid"),
    { kind: "num", key: "segments", label: "Segments", ph: "10", min: 2, max: 40, when: (el) => el.bar_style === "segmented" },
    F.num("min_val", "From", "0"), F.num("max_val", "To", "100"), F.text("suffix", "Unit", "%"), F.num("decimals", "Decimals", "0", 0, 4), F.on("show_label", "Show the value", true)],
  curve: [F.entity("entity", "Sensor"), F.num("hours", "Hours", "24", 1, 720)],
  bar_chart: [F.entity("entity", "Sensor"), F.text("title", "Title", "Last 24 hours"), F.num("hours", "Hours", "24", 1, 720), F.num("bars", "Bars", "12", 2, 48), F.on("show_labels", "Lowest and highest", true), F.on("show_border", "Border", false)],
  calendar_month: [F.entity("entity", "Calendar", ["calendar"]), F.sel("first_weekday", "Week starts", [["0", "Monday"], ["6", "Sunday"]], "0"), F.on("show_header", "Month name", true), F.on("show_weekdays", "Weekday names", true), F.on("highlight_today", "Mark today", true), BORDER_ON],
  calendar_agenda: [F.entity("entity", "Calendar", ["calendar"]), F.text("title", "Title", "Coming up"), F.sel("max_events", "Events", [["2", "2, extra large"], ["3", "3, large"], ["4", "4"], ["5", "5"], ["6", "6"]], "4"), F.on("show_sub", "Times and places", true), BORDER_ON],
  weather_forecast: [F.entity("entity", "Weather", ["weather"]), F.sel("layout_mode", "Layout", [["auto", "Fit the box"], ["split", "Now and forecast side by side"], ["stacked", "Now above the forecast"], ["hero_only", "Now only, very large"], ["forecast_only", "Forecast only"]], "auto"),
    F.sel("forecast_days", "Days", [["3", "3"], ["4", "4"], ["5", "5"]], "4"), F.on("show_details", "Humidity and wind", true), BORDER_ON],
  sports_racing: [F.sel("series", "Series", [["f1", "Formula 1"], ["fe", "Formula E"], ["nascar", "NASCAR"], ["indycar", "IndyCar"]], "f1"), F.entity("entity", "Sensor, if you have one"),
    F.sel("max_drivers", "Leaderboard", [["6", "Top 6, extra large"], ["8", "Top 8, large"], ["10", "Top 10"]], "10"),
    { kind: "window", label: "Only show around sessions" }, F.sel("window_mode", "Around", [["session", "Each session"], ["weekend", "The whole weekend"]], "session"),
    F.num("pre_buffer_hours", "Hours before", "2", 0, 24, 0.5), F.num("post_buffer_hours", "Hours after", "2", 0, 24, 0.5),
    F.on("show_teams", "Team names", true), F.text("timezone", "Time zone", "Home Assistant's"), BORDER_ON, { kind: "sensorid" }],
  sports_match: [F.sel("league", "League", [["soccer/eng.1", "Premier League"], ["soccer/uefa.champions", "Champions League"], ["soccer/esp.1", "La Liga"], ["soccer/ger.1", "Bundesliga"], ["soccer/ita.1", "Serie A"], ["basketball/nba", "NBA"], ["football/nfl", "NFL"], ["baseball/mlb", "MLB"], ["hockey/nhl", "NHL"]], "soccer/eng.1"),
    F.text("team", "Team", "Any team"), F.entity("entity", "Team Tracker sensor"), { kind: "window", label: "Only show on match days" },
    F.num("pre_buffer_hours", "Hours before", "2", 0, 24, 0.5), F.num("post_buffer_hours", "Hours after", "2", 0, 24, 0.5),
    F.text("timezone", "Time zone", "Home Assistant's"), F.on("show_stats", "Team stats", true), F.on("show_scorers", "Scorers", true), BORDER_ON, { kind: "sensorid" }],
  flight_tracker: [F.sel("style", "Style", [["card", "Details"], ["split", "Radar and details"], ["radar", "Radar"]], "card"), { kind: "place" },
    F.num("radius", "Radius, km", "35", 5, 250), { kind: "window", label: "Only show while a plane is near" }, F.on("show_sub_metrics", "Second units", true), BORDER_ON, { kind: "sensorid" }],
};

function typeSections(app, el, set, i) {
  if (el.type === "line") return [lineSection(app, el)];
  if (el.type === "qr") return [qrSection(app, el, set)];
  if (el.type === "dynamic_grid") return gridSections(app, el, set);
  const fields = TYPE_FIELDS[el.type] || [];
  const s = section(TYPES[el.type]?.name || "Settings");
  for (const f of fields) {
    if (f.when && !f.when(el)) continue;
    if (f.kind === "entity") s.append(field(f.label, entityButton(app, el[f.key], (id) => set(f.key, id), { domains: f.domains, allowNone: true })));
    else if (f.kind === "text") s.append(field(f.label, input(el[f.key], (v) => set(f.key, v), { placeholder: f.ph || "" })));
    else if (f.kind === "num") s.append(field(f.label, number(el[f.key], (v) => set(f.key, v), { placeholder: f.ph || "", min: f.min, max: f.max, step: f.step })));
    else if (f.kind === "sel") s.append(field(f.label, select(f.options, el[f.key] ?? f.def, (v) => {
      const num = /^(first_weekday|max_events|forecast_days|max_drivers)$/.test(f.key);
      set(f.key, num ? Number(v) : v);
      if ((f.key === "league" || f.key === "series") && app.doc.page().tier === "when") { syncWidgetShowIf(app.doc.page(), el); app.doc.commit(); }
    })));
    else if (f.kind === "toggle") s.append(toggleRow(f.label, f.def ? el[f.key] !== false : !!el[f.key], (v) => set(f.key, f.def ? (v ? "" : false) : (v ? true : ""))));
    else if (f.kind === "window") s.append(toggleRow(f.label, app.doc.page().tier === "when", (v) => {
      const p = app.doc.page();
      el.auto_window = v;
      if (v) { p.tier = "when"; syncWidgetShowIf(p, el); if (!app.doc.spec.rotation.includes(app.doc.cur)) app.doc.spec.rotation.push(app.doc.cur); }
      else { p.tier = "rotate"; delete p.show_if; }
      app.doc.commit();
    }, "Sets when the whole page shows"));
    else if (f.kind === "sensorid") s.append(h("details", { class: "more" }, h("summary", {}, icon("chev", "sm"), "Its sensor"),
      h("p", { class: "fnote" }, "The add-on publishes this widget's state as ", h("code", { class: "sel", text: getWidgetSensorId(el) }), ", for your own automations.")));
    else if (f.kind === "place") s.append(...placeRows(app, el, set));
  }
  return [s];
}

function lineSection(app, el) {
  const vert = el.h >= el.w;
  const g = app.geometry();
  return section("Divider",
    h("div", { class: "field" }, h("span", { class: "lab", text: "Direction" }), seg([["h", "Across"], ["v", "Up and down"]], vert ? "v" : "h", (v) => {
      const cx = el.x + el.w / 2, cy = el.y + el.h / 2, len = Math.max(16, vert ? el.h : el.w);
      const thick = Math.max(1, Number(el.thickness || el.stroke || 2)), pad = Math.max(thick % 2 ? 9 : 8, thick + 6);
      if (v === "v") { el.w = pad; el.h = Math.min(g.safeH - 8, len); } else { el.w = Math.min(g.W - 8, len); el.h = pad; }
      el.x = Math.max(0, Math.min(g.W - el.w, Math.round(cx - el.w / 2)));
      el.y = Math.max(0, Math.min(g.H - el.h, Math.round(cy - el.h / 2)));
      app.doc.commit();
    }, "Direction")),
    field("Length", number(vert ? el.h : el.w, (v) => { const n = Math.max(4, Math.min(960, Number(v) || 60)); if (vert) el.h = Math.max(el.w + 1, n); else el.w = Math.max(el.h + 1, n); app.doc.commit(); }, { min: "4", max: "960" })),
    field("Thickness", number(el.thickness ?? el.stroke ?? 2, (v) => { el.thickness = Math.max(1, Number(v) || 2); normalizeLineParity(el, null, vert ? "x" : "y"); app.doc.commit(); }, { min: "1", max: "20" })));
}

function qrSection(app, el, set) {
  const wifi = el.qr_mode === "wifi" || !!(el.wifi_ssid && String(el.wifi_ssid).length);
  const s = section("QR code", h("div", { class: "field" }, h("span", { class: "lab", text: "Opens" }), seg([["text", "A link or text"], ["wifi", "Wi-Fi"]], wifi ? "wifi" : "text", (v) => {
    el.qr_mode = v;
    if (v === "wifi") { el.wifi_ssid = el.wifi_ssid || "Guest"; el.wifi_auth = el.wifi_auth || "WPA"; }
    else { delete el.wifi_ssid; delete el.wifi_password; delete el.wifi_auth; }
    app.doc.commit();
  }, "What the code opens")));
  if (wifi) {
    s.append(field("Network", input(el.wifi_ssid, (v) => set("wifi_ssid", v))),
      field("Password", input(el.wifi_password, (v) => set("wifi_password", v), { type: "text" })),
      field("Security", select([["WPA", "WPA2 or WPA3"], ["WEP", "WEP"], ["nopass", "None"]], el.wifi_auth || "WPA", (v) => set("wifi_auth", v))));
  } else {
    s.append(field("Link or text", input(el.value, (v) => set("value", v), { placeholder: "https://…" })),
      field("Or a sensor", entityButton(app, el.entity, (id) => set("entity", id), { allowNone: true, placeholder: "None" })));
  }
  s.append(field("Caption", input(el.title, (v) => set("title", v), { placeholder: "Scan me" })),
    toggleRow("Border", !!el.show_border, (v) => set("show_border", v ? true : "")));
  return s;
}

function placeRows(app, el, set) {
  const msg = h("div", { class: "fnote", role: "status", "aria-live": "polite" });
  const code = h("input", { class: "inp", maxlength: "3", placeholder: "LHR", "aria-label": "Airport code", autocapitalize: "characters", spellcheck: "false", style: { textTransform: "uppercase", width: "6em" } });
  const go = async () => {
    const c = code.value.trim().toUpperCase();
    if (!/^[A-Z]{3}$/.test(c)) { msg.textContent = "Type a three-letter airport code, like LHR."; msg.classList.add("bad"); return; }
    try {
      const a = (await api("api/airport?code=" + encodeURIComponent(c))).body;
      el.lat = a.lat; el.lon = a.lon; el.location_name = a.code;
      app.doc.commit();
      toast(`Centred on ${a.name}${a.city ? ", " + a.city : ""}.`);
    } catch (e) { msg.textContent = e.message; msg.classList.add("bad"); }
  };
  code.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } });
  const places = app.doc.spec.location_presets || [];
  const chips = h("div", { class: "chips" },
    h("button", { class: "chipbtn", "aria-pressed": String(el.lat === undefined), onclick: () => { delete el.lat; delete el.lon; delete el.location_name; app.doc.commit(); } }, "Home"),
    ...places.map((p, k) => h("span", { class: "chipgroup" },
      h("button", { class: "chipbtn", "aria-pressed": String(el.lat === p.lat && el.lon === p.lon), title: `${p.lat}, ${p.lon}`, onclick: () => { el.lat = p.lat; el.lon = p.lon; el.location_name = p.label; app.doc.commit(); } }, p.label),
      h("button", { class: "chipx", "aria-label": `Forget ${p.label}`, title: `Forget ${p.label}`, onclick: () => { places.splice(k, 1); app.doc.commit(); toast(`Forgot ${p.label}.`, { label: "Undo", run: () => app.doc.undo() }); } }, icon("close", "xs")))),
    places.length < 4 && el.lat !== undefined ? h("button", { class: "chipbtn add", onclick: () => {
      const label = (el.location_name || "").trim().slice(0, 12) || `${Number(el.lat).toFixed(2)},${Number(el.lon).toFixed(2)}`;
      places.push({ label, lat: Number(el.lat), lon: Number(el.lon) }); app.doc.spec.location_presets = places; app.doc.commit();
      toast(`Saved ${label} as a place.`);
    } }, icon("plus", "xs"), "Save this place") : null);
  return [
    field("Airport", h("div", { class: "inline" }, code, h("button", { class: "btn tinted", onclick: go, text: "Go" }))), msg,
    field("Places", chips),
    field("Called", input(el.location_name, (v) => set("location_name", v), { placeholder: "Home" })),
    h("div", { class: "pair" },
      field("Latitude", number(el.lat, (v) => set("lat", v), { step: "any", placeholder: "Home" })),
      field("Longitude", number(el.lon, (v) => set("lon", v), { step: "any", placeholder: "Home" }))),
  ];
}

function gridSections(app, el, set) {
  if (!Array.isArray(el.items)) el.items = [];
  const p = app.doc.page();
  const resync = () => { syncDynamicGridShowIf(p, el); };
  const top = section("Devices",
    field("Title", input(el.header_title, (v) => set("header_title", v), { placeholder: "On now" })),
    field("Title icon", iconButton(app, el.header_icon, (ic) => set("header_icon", ic), "Title icon")),
    field("Counts as on", select([["on", "On"], ["off", "Off"], ["*", "Any state"]], el.filter_state || "on", (v) => { el.filter_state = v; resync(); app.doc.commit(); })),
    field("Layout", select([["grid", "Grid"], ["columns", "One row"]], el.layout_mode || (el.layout_4 === "columns" ? "columns" : "grid"), (v) => set("layout_mode", v))),
    field("Shows", select([["both", "Icon, name and detail"], ["name_only", "Icon and name"], ["icons_only", "Icons only, large"]], el.show_labels || "both", (v) => set("show_labels", v))),
    field("Icon size", select([["auto", "Fit"], ["medium", "Medium"], ["large", "Large"], ["huge", "Huge"]], el.icon_size || "auto", (v) => set("icon_size", v))),
    field("Detail", select([["runtime", "How long it's been on"], ["state", "Its state"], ["none", "Nothing"]], el.secondary_mode || "runtime", (v) => set("secondary_mode", v))),
    toggleRow("Hide the page when nothing's on", p.tier === "when", (v) => {
      if (v) { p.tier = "when"; resync(); if (!app.doc.spec.rotation.includes(app.doc.cur)) app.doc.spec.rotation.push(app.doc.cur); }
      else { p.tier = "rotate"; delete p.show_if; }
      app.doc.commit();
    }, "Sets when the whole page shows"));
  const spots = section(`Spots (${el.items.length})`);
  el.items.forEach((it, k) => {
    const card = h("div", { class: "spot" },
      h("div", { class: "spothead" }, h("span", { text: it.name || `Spot ${k + 1}` }),
        h("button", { class: "btn icon", "aria-label": `Remove ${it.name || "spot " + (k + 1)}`, onclick: () => { el.items.splice(k, 1); resync(); app.doc.commit(); } }, icon("trash", "sm"))),
      entityButton(app, it.entity, (id) => {
        it.entity = id;
        const e = app.entMap.get(id), friendly = e?.name || "";
        if ((!it.name || /^Spot \d+$/i.test(it.name)) && friendly) it.name = friendly;
        if (!it.icon || it.icon === "mdi:radiator" || it.icon === "mdi:power") it.icon = suggestIconForEntity(id, friendly);
        resync(); app.doc.commit();
      }),
      field("Name", input(it.name, (v) => { it.name = v; app.doc.commit(); }, { placeholder: "Its name in Home Assistant" })),
      toggleRow("Icon only", !!it.hide_name, (v) => { it.hide_name = v; app.doc.commit(); }),
      field("When on", iconButton(app, it.icon, (ic) => { it.icon = ic; app.doc.commit(); }, "Icon when on")),
      field("When off", iconButton(app, it.icon_off, (ic) => { it.icon_off = ic; app.doc.commit(); }, "Icon when off")));
    spots.append(card);
  });
  spots.append(h("button", { class: "btn tinted", onclick: () => { el.items.push({ entity: "", name: `Spot ${el.items.length + 1}`, icon: "mdi:radiator" }); resync(); app.doc.commit(); } }, icon("plus", "sm"), "Add a spot"));
  return [top, spots];
}

/* ---------- several selected ---------- */
function multi(app, head, body) {
  const doc = app.doc;
  head.append(h("div", { class: "ttl" }, h("span", { class: "kind", text: "Selection" }), h("span", { class: "tname", text: `${doc.sel.length} elements` })));
  const btn = (ic, label, run) => h("button", { class: "btn icon tinted", "aria-label": label, title: label, onclick: run }, icon(ic));
  body.append(section("Align",
    h("div", { class: "btnrow icons" }, btn("alignl", "Align left edges", () => app.align("l")), btn("centerh", "Align centres", () => app.align("cx")), btn("alignr", "Align right edges", () => app.align("r")),
      h("span", { class: "spacer" }), btn("alignt", "Align tops", () => app.align("t")), btn("centerv", "Align middles", () => app.align("cy")), btn("alignb", "Align bottoms", () => app.align("b"))),
    h("div", { class: "btnrow icons" }, btn("disth", "Space evenly across", () => app.align("dh")), btn("distv", "Space evenly up and down", () => app.align("dv")),
      h("span", { class: "fnote", text: doc.sel.length < 3 ? "Spacing needs three or more." : "" })),
    h("p", { class: "fnote", text: "Drag any of them to move them together, or use the arrow keys." })));
  body.append(section(null, h("div", { class: "btnrow" },
    h("button", { class: "btn tinted", onclick: () => app.copy() }, icon("copy", "sm"), "Copy"),
    h("button", { class: "btn tinted", onclick: () => app.duplicate() }, icon("dup", "sm"), "Duplicate"),
    h("button", { class: "btn tinted danger", onclick: () => app.remove() }, icon("trash", "sm"), "Delete"))));
}

/* ---------- the page ---------- */
function page(app, head, body) {
  const doc = app.doc, p = doc.page(), cur = doc.cur;
  const name = h("input", { class: "inp title", value: cur, "aria-label": "Page name", spellcheck: "false", autocomplete: "off" });
  const err = h("div", { class: "fnote", role: "status", "aria-live": "polite" });
  name.addEventListener("input", () => {
    const n = slug(name.value);
    err.classList.remove("bad");
    if (!n) { err.textContent = "A page needs a name."; err.classList.add("bad"); }
    else if (n !== cur && doc.spec.pages[n]) { err.textContent = `There's already a page called ${n}.`; err.classList.add("bad"); }
    else err.textContent = n !== name.value.trim() ? `Saved as ${n}` : "";
  });
  name.addEventListener("keydown", (e) => { if (e.key === "Enter") name.blur(); if (e.key === "Escape") { name.value = cur; err.textContent = ""; name.blur(); } });
  name.addEventListener("change", () => app.renamePage(cur, name.value));
  head.append(h("div", { class: "ttl" }, h("span", { class: "kind", text: "Page" }), name), err);

  const tier = p.tier || "rotate";
  const when = section("Shows", seg([["rotate", "Always"], ["when", "Only when"], ["alert", "As an alert"]], tier, (v) => app.setTier(v), "When this page shows"));
  if (tier !== "rotate") when.append(conditionRows(app, p));
  if (tier === "alert") {
    when.append(field("Holds for", number(p.hold_minutes ?? 10, (v) => { p.hold_minutes = Math.max(1, Math.min(1440, Number(v) || 10)); doc.commit(); }, { min: "1", max: "1440" }), { note: "Minutes. It takes over the panel when its condition turns true, then gives it back." }));
  }
  body.append(when);

  if (tier !== "alert") {
    const times = doc.spec.rotation.filter((n) => n === cur).length;
    body.append(section("Rotation",
      h("p", { class: "fnote", text: times === 0 ? "Not in the rotation, so the panel never shows it." : times === 1 ? "Once in every round. Drag its tile in the strip to move it." : `${times} times in every round, so it shows more often.` }),
      h("div", { class: "btnrow" },
        h("button", { class: "btn tinted", onclick: () => { doc.spec.rotation.push(cur); doc.commit(); } }, times ? "Show again" : "Add to rotation"),
        times ? h("button", { class: "btn tinted", onclick: () => { doc.spec.rotation.splice(doc.spec.rotation.lastIndexOf(cur), 1); doc.commit(); } }, times > 1 ? "Show once less" : "Take out") : null),
      field("Each page shows for", select([[15, "15 seconds"], [30, "30 seconds"], [45, "45 seconds"], [60, "1 minute"], [120, "2 minutes"], [300, "5 minutes"]], doc.spec.rotate_seconds || 30, (v) => { doc.spec.rotate_seconds = Number(v); doc.commit(); }), { note: "For every page in the rotation." })));
  }
  body.append(section(null, h("div", { class: "btnrow" },
    h("button", { class: "btn tinted", onclick: () => app.duplicatePage() }, icon("dup", "sm"), "Duplicate"),
    h("button", { class: "btn tinted", onclick: () => app.savePreset() }, "Save as preset"),
    h("button", { class: "btn tinted danger", onclick: () => app.deletePage() }, icon("trash", "sm"), "Delete"))));
  body.append(h("p", { class: "empty-note", text: doc.els().length ? "Select something on the canvas to change it." : "This page is empty. Insert a sensor, text or an icon." }));
}

function conditionRows(app, p) {
  const doc = app.doc;
  const parsed = parseShowIf(p.show_if);
  const wrap = h("div", { class: "cond" });
  if (parsed.mode === "raw" || app.rawCondition) {
    wrap.append(field("Condition", textarea(p.show_if, (v) => { if (v.trim()) p.show_if = v.trim(); else delete p.show_if; doc.commit(); }), { wide: true, note: "A Home Assistant template that's true while the page should show." }));
    const back = parseShowIf(p.show_if);
    if (back.mode === "simple") wrap.append(linkButton("Use the simple form", () => { app.rawCondition = false; app.refresh(); }));
    return wrap;
  }
  const upd = (patch) => { const next = { ...parsed, ...patch }; const c = compileShowIf(next); if (c) p.show_if = c; else delete p.show_if; doc.commit(); };
  wrap.append(entityButton(app, parsed.ent, (id) => {
    const dom = id.split(".")[0], st = app.entMap.get(id)?.state;
    upd({ ent: id, op: "eq", val: (KNOWN_STATES[dom] || [])[0] || st || "" });
  }, { label: "While" }));
  if (parsed.ent) {
    const dom = parsed.ent.split(".")[0], known = KNOWN_STATES[dom];
    const opSel = select(OPS, parsed.op, (v) => upd({ op: v }), { "aria-label": "Comparison" });
    const valIn = input(parsed.val, (v) => upd({ val: v }), { "aria-label": "Value", placeholder: "Value" });
    wrap.append(h("div", { class: "inline cmp" }, opSel, valIn));
    if (known && (parsed.op === "eq" || parsed.op === "ne")) wrap.append(h("div", { class: "chips" }, ...known.map((s) => h("button", { class: "chipbtn", "aria-pressed": String(parsed.val === s), onclick: () => upd({ val: s }) }, s.replace(/_/g, " ")))));
    const holds = evaluate(parsed, app.entMap);
    if (holds !== null) {
      const d = describe(p.show_if, app.entMap);
      wrap.append(h("div", { class: "note " + (holds ? "good" : "warn"), role: "note" }, h("span", { class: "led" }), h("span", { text: holds ? "True now, so it's showing." : `False now: ${d.why}` })));
    }
  }
  wrap.append(linkButton("Use a custom condition", () => { app.rawCondition = true; app.refresh(); }));
  return wrap;
}
