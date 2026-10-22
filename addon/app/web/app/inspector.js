// The inspector: shows what's selected, or the page when nothing is.
// Most-used first (what it shows, how it looks), then arrangement, then
// "More" for the rare things. Every setting 0.9 had is here.

import { h, icon, api, clone, pageTitle, slug, modKey, turning } from "./util.js";
import { field, input, number, select, seg, textarea, toggle, toggleRow, section, linkButton, toast } from "./ui.js";
import { TYPES, breakable, isWidget, hasText, elName, normalizeLineParity, GROUP_STYLES, GROUP_PAD } from "./elements.js";
import { OPS, CHANGED_MINUTES, parseShowIf, compileShowIf, valueChoices, evaluate, describe, changedLine, syncWidgetShowIf, syncDynamicGridShowIf, GRID_RULES, gridRule, gridByNumber, gridWrote } from "./conditions.js";
import { explodeWidget, getWidgetSensorId, suggestIconForEntity } from "./legacy.js";
import { dateEditor, binsEditor } from "./countdown.js";
import { zonesEditor } from "./zones.js";
import { staleNote, changesEvery, pageChangesEvery, sleepsBetweenUpdates, batterySensors, ruleTicks, isLowSensor } from "./presets.js";
import { busyNote, leftOutNote } from "./busyday.js";
import { notifyRows } from "./notify.js";
import { widget, leagueOptions, seriesOptions, sportWord, stateWords } from "./catalog.js";
import { FROM, CLOCK_FORMATS, sourceOf, switchSource, isTemplate } from "./shows.js";
import { isFollowing, startFollowing, stopFollowing, setEntity, addState, removeState, setStateIcon, setStateLook, suggestions, wordFor,
  LOOKS, styleOf, setStyle, iconOf, lookOf, framed } from "./follows.js";

const SHOWS = [["state", "Its value"], ["unit", "Its unit, following the value"], ["attribute", "One of its details"], ["last_changed", "When it last changed"], ["last_updated", "When it last updated"],
  ["days_until", "Days until it"], ["date_formatted", "Its date"], ["calendar_title", "The event's name"]];
const FORMATS = [["relative", "2 hours ago"], ["date", "3 Mar"], ["day_date", "Thu, 24 Oct"], ["day_full", "Thursday, 24 Oct"], ["time", "14:05"], ["time_12", "2:05 PM"], ["datetime", "Date and time"]];
const FONTS = [["lato", "Lato"], ["dejavu", "DejaVu Sans"], ["mono", "Roboto Mono"]];

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
  const b = h("button", { class: "entbtn" + (opts.cls ? " " + opts.cls : ""), "aria-label": `${opts.label || "Sensor"}: ${e ? e.name : entityId || "none"}. Change` },
    h("span", { class: "eb-text" }, h("span", { class: "e1", text: e ? (e.name || entityId) : entityId || opts.placeholder || "Choose a sensor" }),
      entityId ? h("span", { class: "e2", text: entityId }) : null),
    e ? h("span", { class: "ev", text: `${e.state}${e.unit ? " " + e.unit : ""}` }) : null,
    icon("chev", "sm"));
  b.addEventListener("click", () => app.openEntityPicker(b, onPick, { domains: opts.domains, current: entityId, allowNone: opts.allowNone }));
  return b;
}
/* An icon to choose. With `look` (follows.js LOOKS), its tile shows it and the picker offers it too. */
function iconButton(app, value, onPick, label = "Icon", look) {
  const drawn = app.glyphs.has(value), said = look ? LOOKS.find(([v]) => v === look.value)?.[1] : "";
  const b = h("button", { class: "iconbtn", "aria-label": `${label}: ${value || "none"}${said && look.value !== "plain" ? `, ${said.toLowerCase()}` : ""}. Change` },
    h("span", { class: "glyph mdi" + (look ? " look-" + look.value : "") }, drawn ? app.iconNode(value) : "?"), h("span", { class: "e1", text: value ? String(value).replace(/^mdi:/, "") : "Choose an icon" }), icon("chev", "sm"));
  b.addEventListener("click", () => app.openIconPicker(value, onPick, look));
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
  if (dist > 0 && m.verdict) {                     // only what the renderer measured: a world clock reports none
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
  // An icon that changes with a sensor has a look per state, its own Style being "Anything else"'s,
  // chosen in the icon picker: one control for it, never two.
  const rows = isFollowing(el) ? [] : [h("div", { class: "field" }, h("span", { class: "lab", text: "Style" }), seg(LOOKS, styleOf(el), (v) => {
    setStyle(el, v);
    app.doc.commit();
  }, "Style"))];
  if (framed(el)) rows.push(field("Corners", number(el.radius ?? 10, (v) => set("radius", v), { min: "0", max: "60", placeholder: "10" })));
  return rows;
}

/* ---------- element ---------- */
function element(app, head, body, el, i) {
  const { t, d } = elName(el, app.entMap);
  if (el.type === "group") {
    head.append(h("div", { class: "ttl" }, h("span", { class: "kind" }, icon("layers", "xs"), t), h("span", { class: "tname", text: d })));
    const members = app.doc.els().filter((e) => (el.members || []).includes(e.id));
    body.append(together(app, members, el), section(null, h("div", { class: "btnrow" },
      h("button", { class: "btn tinted", onclick: () => app.doc.select(app.canvas.withMembers([i])) }, "Select its elements"))));
    return;
  }
  head.append(h("div", { class: "ttl" }, h("span", { class: "kind" }, icon(TYPES[el.type]?.icon || "square", "xs"), t), h("span", { class: "tname", text: d || t })));
  const set = setter(app, el);
  const doc = app.doc, g = app.geometry();
  if (el._auto) body.append(h("p", { class: "note info" }, icon("info", "sm"), h("span", { text: `Placed automatically for ${app.screen?.name || "this device"}. Move or resize it and this device keeps its own place for it.` })));
  const stale = staleNote(changesEvery(el, app.entMap), app.screen);
  if (stale) body.append(h("p", { class: "note info" }, icon("info", "sm"), h("span", { text: stale })));
  if (widget(el.type)?.sub_items) body.append(leftOutNote(app, doc.cur));   // its page's items left out to fit
  // A device that sleeps draws the date where the time would be; the renderer says which elements
  // it changed (render/clocktime.py, the one place that knows what shows the time).
  const asleep = app.canvas.metrics.find((x) => x.i === i);
  if (asleep?.date_for_time) body.append(h("p", { class: "note info" }, icon("info", "sm"),
    h("span", { text: `${app.screen?.name || "This device"} sleeps between updates, so it shows the date here.` })));
  if (asleep?.hours_apart) body.append(h("p", { class: "note info" }, icon("info", "sm"),
    h("span", { text: `${app.screen?.name || "This device"} sleeps between updates, so each city shows how many hours it's ahead or behind.` })));

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
    body.append(section("Icon", ...iconRows(app, el, set),
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
      legibility(app, i, el),                       // for a widget whose renderer reports its size (a to-do list)
      breakable(el) ? h("div", { class: "btnrow" }, h("button", { class: "btn tinted", onclick: () => {
        const parts = explodeWidget(el);
        if (!parts.length) return;
        doc.els().splice(i, 1, ...parts);
        doc.sel = parts.map((_, k) => i + k);
        doc.commit();
        toast(`Broken into ${parts.length} elements you can move one by one.`, { label: "Undo", run: () => doc.undo() });
      } }, "Break apart")) : null,
      breakable(el) ? h("p", { class: "fnote", text: "Turns the widget into plain text, values and icons you can move and restyle one by one." }) : null));
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

/* An icon, or one that changes with a sensor (follows.js): the switch first, so it never moves
   under the pointer; on, the sensor, a row per state and its own icon as "Anything else", then
   the states the sensor has that aren't added yet, each with Home Assistant's icon for it. */
function iconRows(app, el, set) {
  const doc = app.doc, on = isFollowing(el);
  const sw = toggleRow("Changes with a sensor", on, (v) => {
    if (!v) { stopFollowing(el); doc.commit(); return; }
    startFollowing(el);
    doc.commit();
    // It needs a sensor before it can do anything: ask for it straight away (the commit redrew the inspector).
    if (!el.entity) app.el.insp.querySelector(".follows .entbtn")?.click();
  });
  if (!on) return [sw, iconButton(app, el.icon, (ic) => set("icon", ic))];
  const ent = app.entMap.get(el.entity);
  const sensor = entityButton(app, el.entity, (id) => {
    const was = ent?.name || el.entity, cleared = setEntity(el, id);
    doc.commit();
    if (cleared) toast(`Took off ${cleared === 1 ? "the state" : `the ${cleared} states`} of ${was}.`, { label: "Undo", run: () => doc.undo() });
  }, { label: "Sensor" });
  const asked = el.entity ? askStates(el.entity) : null;
  const kind = el.entity ? stateWords(el.entity, ent?.device_class) : null;
  const word = (st) => wordFor(st, asked?.got, kind);
  const row = (label, sub, btn, end) => h("div", { class: "frow" },
    h("span", { class: "fl", title: sub ? `${label} (${sub})` : label }, h("span", { class: "fw", text: label }), sub ? h("small", { text: sub }) : null), btn, end);
  const rows = Object.entries(el.state_icons).map(([st, v]) => {
    const w = word(st), sub = w.trim().toLowerCase() === st.trim().toLowerCase() ? "" : st;
    const look = { value: lookOf(el, st), set: (l) => { setStateLook(el, st, l); doc.commit(); } };
    return row(w, sub, iconButton(app, iconOf(v), (pick) => { setStateIcon(el, st, pick); doc.commit(); }, `Icon for ${w}`, look),
      h("button", { class: "btn icon", "aria-label": `Remove ${w}`, title: `Remove ${w}`, onclick: () => {
        removeState(el, st); doc.commit();
        toast(`Removed ${w}.`, { label: "Undo", run: () => doc.undo() });
      } }, icon("close", "sm")));
  });
  const own = { value: styleOf(el), set: (l) => { setStyle(el, l); doc.commit(); } };
  const other = row("Anything else", "", iconButton(app, el.icon, (ic) => set("icon", ic), "Icon for anything else", own), h("span", { class: "fend", "aria-hidden": "true" }));
  const out = [sw, h("div", { class: "follows" }, sensor, ...rows, other)];
  if (!el.entity) { out.push(h("p", { class: "fnote", text: "Choose a sensor, then an icon for each of its states." })); return out; }
  out.push(field("Add", addStates(app, el, asked, word)));
  return out;
}

/* A condition's values as chips: the catalog's for its kind at once, then the states Home Assistant
   says it has (api/entity_states), added at the end when it answers (conditions.valueChoices). */
function valueChips(app, parsed, changed, upd) {
  const box = h("div", { class: "chips", role: "group", "aria-label": "Values it has" });
  const asked = askStates(parsed.ent);
  const fill = () => {
    const got = valueChoices(parsed.ent, app.entMap.get(parsed.ent)?.device_class, asked.got);
    box.replaceChildren(...got.map(({ state: s, word }) => h("button", { class: "chipbtn", "aria-pressed": String(parsed.val === s),
      title: word.trim().toLowerCase() === s.toLowerCase() ? word : `${word} (${s})`,
      onclick: () => upd({ val: parsed.val === s && changed ? "" : s }) }, word)));
    box.hidden = !got.length;
  };
  fill();
  if (asked.got === undefined) asked.done.then(() => { if (box.isConnected) fill(); });
  return box;
}

/* The states not added yet, as chips with their icons; "Other state" for one never seen. Held back
   (its space kept) while Home Assistant answers, so nothing flashes on a quick answer. */
function addStates(app, el, asked, word) {
  const doc = app.doc;
  const box = h("div", { class: "chips follows-add", role: "group", "aria-live": "polite" });
  const typed = () => {
    const inp = h("input", { class: "inp", placeholder: "As Home Assistant says it", "aria-label": "A state it has", autocomplete: "off", spellcheck: "false" });
    const done = (keep) => {
      const st = inp.value.trim(), offered = (asked?.got || []).find((o) => o.state.toLowerCase() === st.toLowerCase());
      inp.blur();
      if (keep && st && !addState(el, offered?.state || st, offered?.icon)) { toast(`${word(st)} is already there.`); fill(); return; }
      if (keep && st) doc.commit(); else fill();
    };
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); done(true); } if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); done(false); } });
    inp.addEventListener("blur", () => { if (inp.isConnected && !inp.value.trim()) fill(); });
    return inp;
  };
  const fill = () => {
    const got = asked?.got;
    if (got === undefined) return;
    const chips = suggestions(el, got).map((o) => h("button", { class: "chipbtn add", "aria-label": `Add ${o.word}`, onclick: () => { addState(el, o.state, o.icon); doc.commit(); } },
      h("span", { class: "glyph mdi", "aria-hidden": "true" }, app.iconNode(o.icon)), o.word));
    const more = h("button", { class: "chipbtn add", onclick: () => { const inp = typed(); more.replaceWith(inp); inp.focus(); } }, icon("plus", "xs"), "Other state");
    const said = got === null ? `${asked.error || "Home Assistant didn't say what states it has."} Type one it has instead.`
      : !got.length && !Object.keys(el.state_icons).length ? "Home Assistant doesn't list states for it. Type one it has." : "";
    box.replaceChildren(...chips, more, said ? h("p", { class: "fnote", text: said }) : "");
    box.classList.remove("waiting");
  };
  fill();
  if (asked && asked.got === undefined) {
    setTimeout(() => { if (asked.got === undefined && box.isConnected) { box.classList.add("waiting"); box.replaceChildren(h("span", { class: "fnote", text: "Looking up its states…" })); } }, 600);
    asked.done.then(() => { if (box.isConnected) fill(); });
  }
  return box;
}

// What a sensor's states are (api/entity_states), kept a minute so redrawing the inspector doesn't blink.
const statesAsked = new Map();
function askStates(ent) {
  const had = statesAsked.get(ent);
  if (had && (had.got === undefined || Date.now() - had.at < 60000)) return had;
  const entry = { at: Date.now(), got: had?.got, error: "", done: null };
  entry.done = api("api/entity_states?entity=" + encodeURIComponent(ent))
    .then((r) => { entry.got = r.body?.states || []; return entry; }, (e) => { entry.got = entry.got ?? null; entry.error = e.message; return entry; });
  statesAsked.set(ent, entry);
  return entry;
}

/* What a text or value shows. */
function shows(app, el, set) {
  const source = sourceOf(el);
  const s = section("Shows", h("div", { class: "field" }, h("span", { class: "lab", text: "From" }), seg(FROM, source, async (v) => {
    if (v === source) return;
    // A template starts from what it shows now, written out by the add-on (binding.as_template).
    let template = "";
    if (v === "template" && !isTemplate(el.value)) {
      try { template = (await api("api/as_template", { method: "POST", body: { element: el } })).body?.template || ""; } catch (_) { /* its own words, below */ }
    }
    const pick = switchSource(el, v, { known: app.entMap, template });
    app.doc.commit();
    // No sensor it reads (or more than one): ask for it straight away (the commit redrew the inspector).
    if (pick) app.el.insp.querySelector(".shows-sensor")?.click();
  }, "Shows")));
  if (source === "clock") {
    s.append(field("Looks like", select(CLOCK_FORMATS, el.format || "time", (v) => set("format", v))),
      h("p", { class: "fnote", text: "12- or 24-hour as in Settings › Time and language. A device that sleeps shows the date instead of the time." }));
  } else if (source === "text") {
    s.append(field("Text", input(el.value, (v) => set("value", v), { placeholder: "What it says" })));
  } else if (source === "template") {
    s.append(field("Template", textarea(el.value, (v) => set("value", v)), { wide: true, note: "Anything Home Assistant can render." }));
  } else {
    s.append(entityButton(app, el.entity, (id) => {
      if (!id) return;
      // The unit follows the sensor when it was the old sensor's own (or none); words you typed stay.
      const was = String(app.entMap.get(el.entity)?.unit || "").trim(), mine = String(el.suffix || "").trim();
      el.entity = id;
      const e = app.entMap.get(id);
      if (el.type === "number" && (!mine || mine === was)) { if (e?.unit) el.suffix = e.unit === "%" ? "%" : " " + e.unit; else if (mine) delete el.suffix; }
      app.doc.commit();
    }, { cls: "shows-sensor" }));
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
// The basic elements' settings. A widget's come from its descriptor in the add-on's catalog
// (widgets.py, fieldsFor below), never a copy here.
const TYPE_FIELDS = {
  box: [F.sel("fill", "Fill", [["outline", "Outline"], ["black", "Black"], ["screen", "Half tone"], ["white", "White"]], "outline"), F.num("radius", "Corners", "12", 0, 120), F.num("thickness", "Border", "3", 1, 20)],
  bar: [F.entity("entity", "Sensor"), F.text("title", "Title", "Battery"), F.sel("bar_style", "Style", [["solid", "Solid"], ["segmented", "Segments"], ["vertical", "Upright"]], "solid"),
    { kind: "num", key: "segments", label: "Segments", ph: "10", min: 2, max: 40, when: (el) => el.bar_style === "segmented" },
    F.num("min_val", "From", "0"), F.num("max_val", "To", "100"), F.text("suffix", "Unit", "%"), F.num("decimals", "Decimals", "0", 0, 4), F.on("show_label", "Show the value", true)],
  curve: [F.entity("entity", "Sensor"), F.num("hours", "Hours", "24", 1, 168)],
  bar_chart: [F.entity("entity", "Sensor"), F.text("title", "Title", "Last 24 hours"), F.num("hours", "Hours", "24", 1, 168), F.num("bars", "Bars", "12", 2, 48), F.on("show_labels", "Lowest and highest", true), F.on("show_border", "Border", false)],
};

/* A widget's fields as its descriptor gives them (plain data), made ready for the form: a league
   or series list from the catalog, a condition ({key, is}) as a test, a label with the sport's word
   ("{event}") or by what the element shows, and what an entity field accepts, with the add-on's
   own reason when it won't. */
export function fieldsFor(type) {
  const w = widget(type);
  if (!w) return TYPE_FIELDS[type] || [];
  return (w.fields || []).map((f) => {
    const out = { ...f };
    if (f.options === "leagues") out.options = leagueOptions();
    if (f.options === "series") out.options = seriesOptions();
    if (f.when && typeof f.when === "object") { const { key, is } = f.when; out.when = (el) => (Array.isArray(is) ? is.includes(el[key]) : el[key] === is); }
    if (typeof f.label === "string" && f.label.includes("{event}")) out.label = (el) => f.label.replace("{event}", sportWord(el.league));
    else if (f.label && typeof f.label === "object") out.label = (el) => (f.label.show || {})[el.show] ?? f.label.else ?? "";
    if (f.accepts) out.check = (e) => {
      const a = f.accepts, unit = String(e.unit || "").trim().toLowerCase();
      if ((a.domains || []).some((d) => e.entity_id.startsWith(d + "."))) return "";
      if ((a.unit_ends || []).some((x) => unit.endsWith(x.toLowerCase()))) return "";
      return a.reason || "This sensor won't do here.";
    };
    return out;
  });
}

function typeSections(app, el, set, i) {
  if (el.type === "line") return [lineSection(app, el)];
  if (el.type === "qr") return [qrSection(app, el, set)];
  const fields = fieldsFor(el.type);
  // A descriptor whose field is the whole grid editor (the Devices widget): its own sections.
  if (fields.some((f) => f.kind === "grid")) return gridSections(app, el, set);
  const s = section(TYPES[el.type]?.name || "Settings");
  for (const f of fields) {
    if (f.when && !f.when(el)) continue;
    if (f.kind === "entity") s.append(field(f.label, entityButton(app, el[f.key], (id) => {
      // A field that takes only some sensors says plainly why it won't take this one, and keeps what it had.
      const why = id && f.check ? f.check(app.entMap.get(id) || { entity_id: id }) : "";
      if (why) { s.querySelector(".note.refused")?.remove(); s.append(h("p", { class: "note warn refused", role: "status" }, icon("info", "sm"), h("span", { text: why }))); return; }
      // A to-do list's page shows by its list: follow it, in the same undo step.
      if (el.type === "todo_list" && app.doc.page().tier === "when") { el[f.key] = id; syncWidgetShowIf(app.doc.page(), el); }
      set(f.key, id);
    }, { domains: f.domains, allowNone: true })));
    else if (f.kind === "text") s.append(field(f.label, input(el[f.key], (v) => set(f.key, v), { placeholder: f.ph || "" })));
    else if (f.kind === "num") s.append(field(f.label, number(el[f.key], (v) => set(f.key, v), { placeholder: f.ph || "", min: f.min, max: f.max, step: f.step })));
    else if (f.kind === "sel") { s.append(field(f.label, select(f.options, el[f.key] ?? f.def, (v) => {
      // What a to-do list shows is what its page shows by: follow it, in the same undo step.
      if (el.type === "todo_list" && app.doc.page().tier === "when") { el[f.key] = v; syncWidgetShowIf(app.doc.page(), el); }
      const num = /^(first_weekday|max_events|forecast_days|max_drivers)$/.test(f.key);
      set(f.key, num ? Number(v) : v);
      if ((f.key === "league" || f.key === "series") && app.doc.page().tier === "when") { syncWidgetShowIf(app.doc.page(), el); app.doc.commit(); }
    })));
      if (f.key === "league") s.append(busyNote(app, app.doc.spec));   // could a busy day pass what the device holds (busyday.js)
    }
    else if (f.kind === "toggle") s.append(toggleRow(f.label, f.def ? el[f.key] !== false : !!el[f.key], (v) => set(f.key, f.def ? (v ? "" : false) : (v ? true : ""))));
    else if (f.kind === "window") s.append(toggleRow(typeof f.label === "function" ? f.label(el) : f.label, app.doc.page().tier === "when", (v) => {
      const p = app.doc.page();
      el.auto_window = v;
      if (v) { p.tier = "when"; syncWidgetShowIf(p, el); if (!app.doc.spec.rotation.includes(app.doc.cur)) app.doc.spec.rotation.push(app.doc.cur); }
      else { p.tier = "rotate"; delete p.show_if; }
      app.doc.commit();
    }, "Sets when the whole page shows"));
    else if (f.kind === "sensorid") {
      // Its words are the descriptor's (widgets.py), "{sensor}" where the sensor goes.
      const [before, after = ""] = (f.note || "The add-on publishes this widget's state as {sensor}, for your own automations.").split("{sensor}");
      s.append(h("details", { class: "more" }, h("summary", {}, icon("chev", "sm"), "Its sensor"),
        h("p", { class: "fnote" }, before, h("code", { class: "sel", text: getWidgetSensorId(el) || f.none || "" }), after)));
    }
    else if (f.kind === "note") s.append(h("p", { class: "fnote" }, f.text || ""));   // the descriptor's words, as text
    else if (f.kind === "place") s.append(...placeRows(app, el, set));
    else if (f.kind === "countdown") s.append((el.to === "bins" ? binsEditor : dateEditor)(el, () => app.doc.commit()));
    // A world clock's cities: adding, removing or reordering one redraws the canvas at once (each commit does).
    else if (f.kind === "zones") s.append(field(f.label || "Cities", zonesEditor(el, () => app.doc.commit(), { most: f.most || 4 }), { wide: true }));
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
  // A number rule (a battery below 40 %): each shows while past the page's number, or its own.
  const byNumber = gridByNumber(el), cmp = el.filter_rule === "below" ? "Below" : "At least";
  const top = section("Devices",
    field("Title", input(el.header_title, (v) => set("header_title", v), { placeholder: "On now" })),
    field("Title icon", iconButton(app, el.header_icon, (ic) => set("header_icon", ic), "Title icon")),
    field("Shows each", select(GRID_RULES, gridRule(el), (v) => {
      if (v === "below" || v === "at_least") {
        el.filter_rule = v;
        if (el.filter_value === undefined || el.filter_value === "") el.filter_value = v === "below" ? 20 : 90;
      } else { delete el.filter_rule; el.filter_state = v; }
      resync(); app.doc.commit();
    }, { "aria-label": "Shows each" })),
    byNumber ? field(cmp, number(el.filter_value, (v) => { el.filter_value = v; resync(); app.doc.commit(); }, { step: "any", "aria-label": `${cmp} this number`, style: { width: "6em" } })) : null,
    field("Layout", select([["grid", "Grid"], ["columns", "One row"], ["list", "List"]], el.layout_mode || (el.layout_4 === "columns" ? "columns" : "grid"), (v) => set("layout_mode", v))),
    field("Shows", select([["both", "Icon, name and detail"], ["name_only", "Icon and name"], ["icons_only", "Icons only, large"]], el.show_labels || "both", (v) => set("show_labels", v))),
    field("Icon size", select([["auto", "Fit"], ["medium", "Medium"], ["large", "Large"], ["huge", "Huge"]], el.icon_size || "auto", (v) => set("icon_size", v))),
    // By a number, the detail is its level (render/layout); a state can say how long, or itself.
    byNumber ? null : field("Detail", select([["runtime", "How long it's been on"], ["state", "Its state"], ["none", "Nothing"]], el.secondary_mode || "runtime", (v) => set("secondary_mode", v))),
    toggleRow(byNumber ? "Hide the page when nothing shows" : "Hide the page when nothing's on", p.tier === "when", (v) => {
      if (v) { p.tier = "when"; resync(); if (!app.doc.spec.rotation.includes(app.doc.cur)) app.doc.spec.rotation.push(app.doc.cur); }
      else { p.tier = "rotate"; delete p.show_if; }
      app.doc.commit();
    }, "Sets when the whole page shows"));
  if (el.batteries) return [top, batteriesSection(app, el, cmp, resync)];
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
      ...(byNumber ? [
        field(`Its own ${cmp.toLowerCase()}`, number(it.threshold ?? "", (v) => { if (v === "") delete it.threshold; else it.threshold = v; resync(); app.doc.commit(); },
          { step: "any", placeholder: String(el.filter_value ?? ""), "aria-label": `${it.name || "This one"}: its own number, or empty for the page's`, style: { width: "6em" } })),
        field("Icon", iconButton(app, it.icon, (ic) => { it.icon = ic; app.doc.commit(); }, "Icon")),
        h("p", { class: "fnote", text: "With no icon, a battery shows its level, as in Home Assistant." }),
      ] : [
        field("When on", iconButton(app, it.icon, (ic) => { it.icon = ic; app.doc.commit(); }, "Icon when on")),
        field("When off", iconButton(app, it.icon_off, (ic) => { it.icon_off = ic; app.doc.commit(); }, "Icon when off")),
      ]));
    spots.append(card);
  });
  spots.append(h("button", { class: "btn tinted", onclick: () => { el.items.push({ entity: "", name: `Spot ${el.items.length + 1}`, icon: "mdi:radiator" }); resync(); app.doc.commit(); } }, icon("plus", "sm"), "Add a spot"));
  return [top, spots];
}

/* Batteries by rule (review 2 #5): every battery Home Assistant has, ticked as the rule picks it (its
   kind, minus the unticked, plus the other kind's ticked). A tick changes `except` or `also`, never a
   list of today's batteries, so one added later shows on its own. Each ticked one can have its own
   number (`items` are each battery's own settings). Kinds are the add-on's (GET /api/batteries). */
let batteryKinds = null;
function batteriesSection(app, el, cmp, resync) {
  const all = batterySensors(app.ents);
  const box = section(`Batteries (${all.length})`);
  const kindOf = (e) => (batteryKinds?.[e.entity_id] || "swap");
  const own = (id) => (el.items || []).find((it) => it.entity === id);
  function toggle(e) {
    const id = e.entity_id, mine = kindOf(e) === el.batteries;
    const listKey = mine ? "except" : "also", list = new Set(el[listKey] || []);
    list.has(id) ? list.delete(id) : list.add(id);
    el[listKey] = [...list];
    resync(); app.doc.commit();
  }
  function draw() {
    const ticks = ruleTicks(all, el, kindOf);
    box.replaceChildren(h("h3", { class: "slab", text: `Batteries (${all.length})` }),
      h("p", { class: "fnote", text: el.batteries === "charge"
        ? "Every battery you charge, and any you tick. One you add to Home Assistant later shows too."
        : "Every battery you swap, and any you tick. One you add to Home Assistant later shows too." }),
      ...all.map((e) => {
        const on = ticks.has(e.entity_id), it = own(e.entity_id);
        return h("div", { class: "spot" },
          h("button", { class: "opt", role: "checkbox", "aria-checked": String(on), onclick: () => { toggle(e); draw(); } },
            h("span", { class: "ock", "aria-hidden": "true" }, on ? icon("check", "sm") : null),
            h("span", { class: "otext" }, h("span", { class: "o1", text: e.name || e.entity_id }), h("span", { class: "o2", text: e.entity_id }))),
          on && !isLowSensor(e) ? field(`Its own ${cmp.toLowerCase()}`, number(it?.threshold ?? "", (v) => {
            const items = (el.items || []).filter((x) => x.entity !== e.entity_id);
            if (v !== "") items.push({ ...(it || { entity: e.entity_id, name: "", icon: "" }), threshold: v });
            el.items = items; resync(); app.doc.commit();
          }, { step: "any", placeholder: String(el.filter_value ?? ""), "aria-label": `${e.name || e.entity_id}: its own number, or empty for the page's`, style: { width: "6em" } })) : null);
      }));
    if (!all.length) box.append(h("p", { class: "empty-note", text: "No batteries in Home Assistant yet. Any you add later shows here on its own." }));
  }
  draw();
  if (!batteryKinds) api("api/batteries").then((r) => { batteryKinds = r.body?.kinds || {}; draw(); }, () => {});
  return box;
}

/* ---------- several selected ---------- */
/* ---------- several together ---------- */
// A style around several elements: an outline, a pill, or the whole area
// inverted. It's a group that follows its members, on every screen size.
function together(app, members, grp) {
  const doc = app.doc;
  const choose = (v) => {
    const els = doc.els();
    if (v === "none") {
      if (!grp) return;
      doc.page().elements = els.filter((e) => e !== grp);
      doc.sel = members.map((e) => doc.els().indexOf(e)).filter((i) => i >= 0);
      doc.commit();
      app.toast("Ungrouped.", { label: "Undo", run: () => doc.undo() });
      return;
    }
    if (grp) { grp.style = v; doc.commit(); return; }
    const g = { type: "group", members: members.map((e) => e.id), style: v, pad: GROUP_PAD };
    const first = Math.min(...members.map((e) => els.indexOf(e)));
    els.splice(first, 0, g);                                   // behind its members
    doc.sel = [g, ...members].map((e) => els.indexOf(e));
    doc.commit();
    app.say(`${GROUP_STYLES.find(([k]) => k === v)[1]} around ${members.length} elements.`);
  };
  const rows = [seg([["none", "None"], ...GROUP_STYLES], grp?.style || "none", choose, "Style around them")];
  if (grp) {
    rows.push(field("Space inside", number(grp.pad ?? GROUP_PAD, (v) => { grp.pad = Math.max(0, Math.min(60, Number(v) || 0)); doc.commit("pad"); }, { min: "0", max: "60", style: { width: "5em" } })));
    rows.push(h("p", { class: "fnote", text: "It follows them when they move, and on every device." }));
  } else rows.push(h("p", { class: "fnote", text: "An outline, a pill or an inverted area around all of them." }));
  return section("Together", ...rows);
}

function multi(app, head, body) {
  const doc = app.doc;
  head.append(h("div", { class: "ttl" }, h("span", { class: "kind", text: "Selection" }), h("span", { class: "tname", text: `${doc.sel.length} elements` })));
  const picked = doc.sel.map((k) => doc.els()[k]).filter(Boolean);
  const members = picked.filter((e) => e.type !== "group");
  const ids = new Set(members.map((e) => e.id));
  const groups = picked.filter((e) => e.type === "group");
  // The group these exactly are, if there is one.
  const grp = groups.find((g) => (g.members || []).length === ids.size && g.members.every((m) => ids.has(m)))
    || doc.els().find((g) => g.type === "group" && (g.members || []).length === ids.size && g.members.every((m) => ids.has(m)));
  if (members.length >= 2) body.append(together(app, members, grp));
  const btn = (ic, label, run) => h("button", { class: "btn icon tinted", "aria-label": label, title: label, onclick: run }, icon(ic));
  body.append(section("Align",
    h("div", { class: "btnrow icons" }, btn("alignl", "Align left edges", () => app.align("l")), btn("centerh", "Align centres", () => app.align("cx")), btn("alignr", "Align right edges", () => app.align("r")),
      h("span", { class: "spacer" }), btn("alignt", "Align tops", () => app.align("t")), btn("centerv", "Align middles", () => app.align("cy")), btn("alignb", "Align bottoms", () => app.align("b"))),
    h("div", { class: "btnrow icons" }, btn("disth", "Space evenly across the panel", () => app.align("dh")), btn("distv", "Space evenly from top to footer", () => app.align("dv")),
      h("span", { class: "fnote", text: "Equal space between them and at the edges" })),
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
  // A countdown's page: passed (reuse it with another date, or delete it), or not showing yet.
  const cd = app.canvas.metrics.find((m) => m.countdown)?.countdown;
  if (cd?.state === "passed") body.append(h("div", { class: "note passed", role: "note" }, icon("info", "sm"),
    h("span", { text: `Passed on ${cd.on}, so the panel leaves it out. Give it another date to use it again.` }),
    h("button", { class: "btn tinted danger", onclick: () => app.deletePage() }, icon("trash", "sm"), "Delete")));
  else if (cd?.state === "waiting") body.append(h("p", { class: "note info" }, icon("info", "sm"), h("span", { text: `It starts showing on ${cd.from}.` })));
  // What changes faster than a sleeping device updates is noted, never hidden (presets.staleNote).
  const stale = staleNote(pageChangesEvery(p.elements, app.entMap), app.screen);
  if (stale) body.append(h("p", { class: "note info" }, icon("info", "sm"), h("span", { text: stale })));
  body.append(leftOutNote(app, cur));         // what the panel left out of it to fit, while it does

  const tier = p.tier || "rotate";
  const when = section("Shows", seg([["rotate", "Always"], ["when", "Only when"], ["alert", "As an alert"]], tier, (v) => app.setTier(v), "When this page shows"));
  if (tier !== "rotate") when.append(conditionRows(app, p));
  if (tier === "alert") when.append(...endRows(app, p));
  if (tier !== "rotate" || p.notify) when.append(notifyRows(app, p, cur));   // its phone notifications (notify.js)
  body.append(when);

  if (tier !== "alert") {
    const times = doc.spec.rotation.filter((n) => n === cur).length;
    body.append(section("Rotation",
      h("p", { class: "fnote", text: times === 0 ? "Not in the rotation, so the panel never shows it." : times === 1 ? "Once in every round. Drag its tile in the strip to move it." : `${times} times in every round, so it shows more often.` }),
      h("div", { class: "btnrow" },
        h("button", { class: "btn tinted", onclick: () => { doc.spec.rotation.push(cur); doc.commit(); } }, times ? "Show again" : "Add to rotation"),
        times ? h("button", { class: "btn tinted", onclick: () => { doc.spec.rotation.splice(doc.spec.rotation.lastIndexOf(cur), 1); doc.commit(); } }, times > 1 ? "Show once less" : "Take out") : null),
      // Rotate every is the screen's own (Settings › Device), next to Update every.
      h("p", { class: "fnote", text: `${app.screen?.name || "This device"} shows ${turning(app.screen?.timing) || "your pages in turn"}. Change it under the canvas.` })));
  }
  body.append(section(null, h("div", { class: "btnrow" },
    h("button", { class: "btn tinted", onclick: () => app.duplicatePage() }, icon("dup", "sm"), "Duplicate"),
    h("button", { class: "btn tinted", onclick: () => app.savePreset() }, "Save as preset"),
    h("button", { class: "btn tinted danger", onclick: () => app.deletePage() }, icon("trash", "sm"), "Delete"))));
  body.append(h("p", { class: "empty-note", text: doc.els().length ? "Select something on the canvas to change it." : "This page is empty. Insert a sensor, text or an icon." }));
}

// A "changed" condition: how long a page stays after each change (an alert
// holds for its own Holds for instead), and the status line, which only the
// add-on can give: it reads the sensor's history, so a Home Assistant restart
// isn't a change (api/changed, sources/changes.py). Answers are kept a while,
// so redrawing the inspector doesn't make the line blink.
const changedAsked = new Map();
function askChanged(ent, minutes) {
  const key = ent + "|" + minutes, had = changedAsked.get(key);
  if (had && Date.now() - had.at < 15000) return had;
  const entry = { at: Date.now(), got: had?.got, offset: had?.offset ?? 0, done: null };
  entry.done = api("api/changed?entity=" + encodeURIComponent(ent) + "&minutes=" + minutes)
    .then((r) => { entry.got = r.body; entry.offset = r.body.now * 1000 - Date.now(); return entry; }, () => { entry.got = entry.got ?? null; return entry; });
  changedAsked.set(key, entry);
  return entry;
}
function changedRows(app, p, parsed, upd) {
  const rows = [], alert = p.tier === "alert" ? (p.ends === "until" ? "until" : "time") : "";
  const minutes = alert ? (p.hold_minutes || HOLD[alert]) : (parsed.minutes || CHANGED_MINUTES);
  if (!alert) {
    rows.push(field("Shows for", number(minutes, (v) => upd({ minutes: Math.max(1, Math.min(1440, Math.round(Number(v)) || CHANGED_MINUTES)) }), { min: "1", max: "1440", step: "1" }),
      { note: "Minutes after each change. Then it leaves the rotation by itself." }));
    // A device that sleeps longer than the page stays may never wake while it's there.
    const every = app.screen?.timing?.update_minutes;
    if (sleepsBetweenUpdates(app.screen) && every > minutes)
      rows.push(h("p", { class: "note info" }, icon("info", "sm"), h("span", { text: `${app.screen?.name || "This device"} updates every ${every} minutes, so it can miss a change that shows for ${minutes}.` })));
  }
  // Held back (its space kept) until there's an answer, so it doesn't flash "checking"; kept current while it's in sight.
  const line = h("div", { class: "note pending", role: "note", "aria-live": "polite" }, h("span", { class: "led" }), h("span", { text: "Checking when it last changed…" }));
  const extra = h("p", { class: "note info", hidden: true }, icon("info", "sm"), h("span"));
  const fill = (entry) => {
    if (entry.got === undefined) return;
    const got = entry.got && { ...entry.got, now: (Date.now() + entry.offset) / 1000 };
    const said = changedLine(parsed, got, { minutes, alert });
    const was = line.classList.contains("pending") || line.classList.contains("waiting");
    line.className = "note " + (said ? (said.holds ? "good" : "warn") : "bad") + (was ? " fresh" : "");
    line.lastChild.textContent = said ? said.text : "Home Assistant didn't say when it last changed. It tries again in a moment.";
    extra.hidden = !said?.note;
    extra.lastChild.textContent = said?.note || "";
  };
  const ask = () => { const e = askChanged(parsed.ent, minutes); fill(e); e.done.then(fill); };
  ask();
  setTimeout(() => line.classList.replace("pending", "waiting"), 600);
  const tick = setInterval(() => (line.isConnected ? ask() : clearInterval(tick)), 30000);
  rows.push(line, extra);
  return rows;
}

// How an alert ends: after a time (hold_minutes), or when its Until comes
// true, with hold_minutes as the most it holds (conditions.py, frames.check_alerts).
const HOLD = { time: 10, until: 120 };
function endRows(app, p) {
  const doc = app.doc, ends = p.ends === "until" ? "until" : "time";
  const pick = (v) => {
    if (v === ends) return;
    // Each way of ending has its own sensible default; a time you chose stays.
    if (p.hold_minutes == null || p.hold_minutes === HOLD[ends]) p.hold_minutes = HOLD[v];
    if (v === "until") p.ends = "until"; else delete p.ends;
    app.rawUntil = false;
    doc.commit();
  };
  const minutes = (label, note) => field(label, number(p.hold_minutes ?? HOLD[ends], (v) => { p.hold_minutes = Math.max(1, Math.min(1440, Math.round(Number(v)) || HOLD[ends])); doc.commit(); }, { min: "1", max: "1440", step: "1" }), { note });
  const rows = [field("Ends", select([["time", "After a time"], ["until", "When something happens"]], ends, pick))];
  const onChange = parseShowIf(p.show_if).op === "changed";
  if (ends === "time") rows.push(minutes("Holds for", onChange ? "Minutes. It takes over the panel each time it changes, then gives it back." : "Minutes. It takes over the panel when its condition turns true, then gives it back."));
  else rows.push(conditionRows(app, p, UNTIL), minutes("At most", "Minutes. It gives the panel back sooner if this happens or its start stops being true, and comes back if this is undone."));
  return rows;
}

// The condition a page shows by (show_if), or the Until an alert ends by.
const SHOW = { key: "show_if", raw: "rawCondition", label: "While", rawNote: "A Home Assistant template that's true while the page should show.", now: [ "True now, so it's showing.", "False now" ] };
const UNTIL = { key: "until_if", raw: "rawUntil", label: "Until", rawNote: "A Home Assistant template that's true once the alert should end.", now: [ "True now, so the alert would end.", "False now" ] };

function conditionRows(app, p, c = SHOW) {
  const doc = app.doc;
  const parsed = parseShowIf(p[c.key]);
  const wrap = h("div", { class: "cond" });
  // A condition its Dynamic status grid wrote (and keeps in step): said in words, not as its template.
  const grid = c === SHOW && !app[c.raw] && (p.elements || []).find((x) => x.type === "dynamic_grid");
  if (grid && gridWrote(p[c.key], grid)) {
    const rule = gridRule(grid), what = rule === "below" ? "is below its number" : rule === "at_least" ? "has reached its number" : `is ${rule}`;
    wrap.append(h("p", { class: "note info" }, icon("info", "sm"), h("span", { text: `While one on its list ${what}. It follows the list as you change it.` })),
      linkButton("Write my own condition", () => { app[c.raw] = true; app.refresh(); }));
    return wrap;
  }
  // An Until can't be "changed" in the simple form (see opSel); one written by hand stays as written.
  if (parsed.mode === "raw" || app[c.raw] || (c !== SHOW && parsed.op === "changed")) {
    wrap.append(field(c === SHOW ? "Condition" : "Until", textarea(p[c.key], (v) => { if (v.trim()) p[c.key] = v.trim(); else delete p[c.key]; doc.commit(); }), { wide: true, note: c.rawNote }));
    const back = parseShowIf(p[c.key]);
    if (back.mode === "simple" && (c === SHOW || back.op !== "changed")) wrap.append(linkButton("Use the simple form", () => { app[c.raw] = false; app.refresh(); }));
    return wrap;
  }
  const upd = (patch) => { const next = { ...parsed, ...patch }; const v = compileShowIf(next); if (v) p[c.key] = v; else delete p[c.key]; doc.commit(); };
  const pickBtn = entityButton(app, parsed.ent, (id) => {
    const e = app.entMap.get(id);
    upd({ ent: id, op: "eq", val: valueChoices(id, e?.device_class)[0]?.state || e?.state || "" });
  }, { label: c.label });
  // "Shows" heads the page's own condition; an Until needs its word in sight.
  wrap.append(c === SHOW ? pickBtn : field(c.label, pickBtn));
  if (parsed.ent) {
    const changed = parsed.op === "changed";
    // "Changed" answers when something happens; an Until has nothing to count its minutes from.
    const opSel = select(c === SHOW ? OPS : OPS.filter(([k]) => k !== "changed"), parsed.op, (v) => upd({ op: v }), { "aria-label": c.label + " comparison" });
    const valIn = changed
      ? input(parsed.val, (v) => upd({ val: v }), { "aria-label": "Changed to", placeholder: "Any value" })
      : input(parsed.val, (v) => upd({ val: v }), { "aria-label": c.label + " value", placeholder: "Value" });
    wrap.append(h("div", { class: "inline cmprow" }, opSel, changed ? h("span", { class: "cmpword", text: "to" }) : null, valIn));
    if (parsed.op === "eq" || parsed.op === "ne" || changed) wrap.append(valueChips(app, parsed, changed, upd));
    const holds = changed ? null : evaluate(parsed, app.entMap);
    if (changed) wrap.append(...changedRows(app, p, parsed, upd));
    else if (holds !== null) {
      const d = describe(p[c.key], app.entMap);
      wrap.append(h("div", { class: "note " + (holds ? "good" : "warn"), role: "note" }, h("span", { class: "led" }), h("span", { text: holds ? c.now[0] : `${c.now[1]}: ${d.why}` })));
    }
  }
  wrap.append(linkButton("Use a custom condition", () => { app[c.raw] = true; app.refresh(); }));
  return wrap;
}
