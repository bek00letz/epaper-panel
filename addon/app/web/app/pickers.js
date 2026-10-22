// Choosing things: a sensor, one of its details, an icon, or something to
// insert. All searchable, all usable from the keyboard.

import { h, icon, api } from "./util.js";
import { popover, sheet, seg } from "./ui.js";
import { LOOKS } from "./follows.js";
import { TYPES, INSERT_GROUPS } from "./elements.js";
import { fullName, prefixOf, shortName } from "./glyphs.js";
import { openSettings } from "./sheets.js";

const DOMAIN_NAMES = { sensor: "Sensors", binary_sensor: "On or off", calendar: "Calendars", weather: "Weather", climate: "Climate", person: "People",
  switch: "Switches", light: "Lights", timer: "Timers", lock: "Locks", input_number: "Numbers", input_text: "Texts", input_boolean: "Toggles" };

function listNav(input, list) {
  input.addEventListener("keydown", (e) => {
    const opts = [...list.querySelectorAll(".opt")];
    if (!opts.length) return;
    const i = opts.findIndex((o) => o.classList.contains("active"));
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const n = opts[(i + (e.key === "ArrowDown" ? 1 : -1) + opts.length) % opts.length];
      opts.forEach((o) => o.classList.toggle("active", o === n));
      n.scrollIntoView({ block: "nearest" });
      input.setAttribute("aria-activedescendant", n.id);
    }
    if (e.key === "Enter") { e.preventDefault(); (opts[i] || opts[0]).click(); }
  });
}

function entityRow(e, onPick, current) {
  const row = h("button", { class: "opt" + (e.entity_id === current ? " current" : ""), role: "option", id: "o-" + e.entity_id.replace(/\W/g, "_"), onclick: () => onPick(e.entity_id) },
    h("span", { class: "otext" }, h("span", { class: "o1" }, e.name || e.entity_id, e.is_epaper ? h("span", { class: "badge", text: "add-on" }) : null), h("span", { class: "o2", text: e.entity_id })),
    h("span", { class: "ov", text: `${e.state}${e.unit ? " " + e.unit : ""}` }));
  return row;
}

function filterEntities(ents, q, scope) {
  const s = q.trim().toLowerCase();
  return ents.filter((e) => {
    const own = e.is_epaper || e.entity_id.startsWith("sensor.epaper_");
    if (scope === "own" && !own) return false;
    if (scope && scope !== "own" && !e.entity_id.startsWith(scope + ".")) return false;
    if (!s) return true;
    return s.split(/\s+/).every((w) => e.entity_id.toLowerCase().includes(w) || (e.name || "").toLowerCase().includes(w));
  });
}

export function openEntityPicker(app, anchor, onPick, opts = {}) {
  popover(anchor, (pop, close) => {
    pop.classList.add("picker");
    const q = h("input", { type: "search", placeholder: "Search by name or id", "aria-label": "Search sensors", role: "combobox", "aria-controls": "entlist", "aria-expanded": "true", autocomplete: "off", spellcheck: "false" });
    const list = h("div", { class: "optlist", id: "entlist", role: "listbox", "aria-label": "Sensors" });
    let scope = opts.domains?.length === 1 ? opts.domains[0] : "";
    const scopes = h("div", { class: "chips scopes" });
    const draw = () => {
      scopes.replaceChildren(...[["", "All"], ["own", "The add-on's own"], ...(opts.domains || []).map((d) => [d, DOMAIN_NAMES[d] || d])].map(([v, l]) =>
        h("button", { class: "chipbtn", "aria-pressed": String(scope === v), onclick: () => { scope = v; draw(); q.focus(); } }, l)));
      const found = filterEntities(app.ents, q.value, scope);
      list.replaceChildren(...found.slice(0, 120).map((e) => entityRow(e, (id) => { close(); onPick(id); }, opts.current)));
      if (!found.length) list.append(h("p", { class: "empty-note", text: app.ents.length ? `Nothing matches “${q.value}”. Try part of the name, or All.` : "Home Assistant's sensors haven't loaded. Check the add-on can reach Home Assistant." }));
      if (opts.allowNone && opts.current) list.prepend(h("button", { class: "opt", role: "option", id: "o-none", onclick: () => { close(); onPick(""); } }, h("span", { class: "otext" }, h("span", { class: "o1", text: "None" }))));
    };
    q.addEventListener("input", draw);
    listNav(q, list);
    pop.append(h("div", { class: "search" }, icon("search", "sm"), q), scopes, list);
    draw();
  }, { label: "Choose a sensor", align: "left", focus: "input" });
}

export function openAttributePicker(app, anchor, entity, onPick) {
  if (!entity) { app.toast("Choose a sensor first, then one of its details."); return; }
  popover(anchor, async (pop, close) => {
    pop.classList.add("picker");
    const list = h("div", { class: "optlist", role: "listbox", "aria-label": "Details" }, h("p", { class: "empty-note", text: "Reading its details…" }));
    const q = h("input", { type: "search", placeholder: "Search details", "aria-label": "Search details", autocomplete: "off" });
    pop.append(h("div", { class: "search" }, icon("search", "sm"), q), list);
    let attrs = [];
    try { attrs = (await api("api/attributes?entity=" + encodeURIComponent(entity))).body || []; } catch (e) { list.replaceChildren(h("p", { class: "empty-note", text: `Couldn't read its details: ${e.message}` })); return; }
    const draw = () => {
      const s = q.value.toLowerCase();
      const found = attrs.filter((a) => !s || a.name.toLowerCase().includes(s) || String(a.sample).toLowerCase().includes(s));
      list.replaceChildren(...found.map((a) => h("button", { class: "opt", role: "option", id: "a-" + a.name.replace(/\W/g, "_"), onclick: () => { close(); onPick(a.name); } },
        h("span", { class: "otext" }, h("span", { class: "o1", text: a.name.replace(/_/g, " ") }), h("span", { class: "o2", text: a.kind === "list" ? "A list" : a.kind === "object" ? "Several values" : a.sample })))));
      if (!found.length) list.append(h("p", { class: "empty-note", text: attrs.length ? "No detail matches." : "This sensor has no details besides its value." }));
    };
    q.addEventListener("input", draw); listNav(q, list); draw();
  }, { label: "Choose a detail", align: "left", focus: "input" });
}

/* Icons: every icon the panel can draw (glyphs.js), Material Design and any custom sets. Search
   looks in all of them; with more than one set, chips narrow it to one (the user's call, 21 Oct),
   and the Pets/Heating/... shortcuts are Material Design's. */
/* `look` ({ value, set }): an icon that changes with a sensor chooses each state's look here too
   (follows.js LOOKS), applied at once; the grid shows the icons in it. */
export function openIconPicker(app, current, onPick, look) {
  sheet("Choose an icon", (node, close) => {
    const total = () => (app.glyphs.sets || []).reduce((n, s) => n + s.count, 0);
    const many = (n) => (n >= 1000 ? `${Math.floor(n / 1000).toLocaleString()},000` : String(n));
    const q = h("input", { type: "search", "aria-label": "Search icons", autocomplete: "off", spellcheck: "false" });
    const meta = h("p", { class: "fnote", role: "status", "aria-live": "polite" });
    const grid = h("div", { class: "icongrid", role: "listbox", "aria-label": "Icons" });
    const cats = [["", "Popular"], ["cat", "Pets"], ["radiator", "Heating"], ["bed", "Furniture"], ["power", "Power"], ["light", "Lights"], ["home", "Home"], ["weather", "Weather"], ["thermometer", "Climate"]];
    const was = prefixOf(current);
    let cat = "", only = was && was !== "mdi" ? was : "";
    const setRow = h("div", { class: "chips", role: "group", "aria-label": "Icon sets" });
    const catRow = h("div", { class: "chips" });
    const draw = () => {
      const sets = app.glyphs.sets || [];
      if (only && !sets.some((s) => s.prefix === only)) only = "";
      q.placeholder = `Search ${many(total() || 7000)} icons: cat, radiator, sun…`;
      setRow.hidden = sets.length < 2;
      setRow.replaceChildren(...[["", "All"], ...sets.map((s) => [s.prefix, s.name])].map(([v, l]) =>
        h("button", { class: "chipbtn", "aria-pressed": String(only === v), onclick: () => { only = v; draw(); } }, l)));
      catRow.hidden = only !== "" && only !== "mdi";
      catRow.replaceChildren(...cats.map(([v, l]) => h("button", { class: "chipbtn", "aria-pressed": String(cat === v && !q.value), onclick: () => { cat = v; q.value = ""; draw(); } }, l)));
      const items = app.searchIcons(q.value || (catRow.hidden ? "" : cat), only);
      const shown = (n) => (prefixOf(n) === "mdi" ? shortName(n) : n);
      meta.textContent = !app.glyphs.ready() ? "Loading icons…" : q.value ? `${items.length === 250 ? "250+" : items.length} icons` : "";
      grid.replaceChildren(...items.map((n) => h("button", { class: "iconcell" + (n === fullName(current) ? " current" : ""), role: "option",
        "aria-label": `${shortName(n).replace(/[-_/]/g, " ")}${prefixOf(n) === "mdi" ? "" : `, ${app.glyphs.setName(prefixOf(n))}`}`, title: n,
        onclick: () => { close(); onPick(n); } }, h("span", { class: "mdi" }, app.iconNode(n)), h("span", { class: "in", text: shown(n) }))));
      if (app.glyphs.ready() && !items.length) grid.append(h("p", { class: "empty-note", text: `No icon called “${q.value}”. Try a simpler word.` }));
    };
    q.addEventListener("input", draw);
    app.glyphs.whenReady(draw);
    const lookRow = look ? h("div", { class: "field" }, h("span", { class: "lab", text: "Look" })) : null;
    const drawLook = () => {
      lookRow.replaceChildren(lookRow.firstChild, seg(LOOKS, look.value, (v) => { look.value = v; look.set(v); drawLook(); lookRow.querySelector('[aria-checked="true"]')?.focus(); }, "Look"));
      grid.dataset.look = look.value;
    };
    if (look) drawLook();
    // More sets, and your own icons, are added in Settings › Icons.
    const more = h("button", { class: "linkbtn", onclick: () => { close(); openSettings(app, "icons"); } }, "More icons…");
    node.append(h("div", { class: "sheet-body" }, lookRow, h("div", { class: "search" }, icon("search", "sm"), q), setRow, catRow, h("div", { class: "pickmeta" }, meta, more), grid));
    draw();
  }, { cls: "wide tall", focus: "input" });
}

/* Insert: element types and sensors in one search. Sensors can also be
   dragged straight onto the canvas. */
export function openInsert(app, anchor) {
  popover(anchor, (pop, close) => {
    pop.classList.add("picker", "insert");
    const q = h("input", { type: "search", placeholder: "Search sensors and elements", "aria-label": "Search sensors and elements", autocomplete: "off", spellcheck: "false" });
    const body = h("div", { class: "insbody" });
    const draw = () => {
      const s = q.value.trim().toLowerCase();
      body.replaceChildren();
      for (const [group, types] of INSERT_GROUPS) {
        const found = types.filter((t) => !s || TYPES[t].name.toLowerCase().includes(s) || t.includes(s));
        if (!found.length) continue;
        body.append(h("div", { class: "poplab", text: group }), h("div", { class: "typegrid" }, ...found.map((t) =>
          h("button", { class: "typecell", onclick: () => { close(); app.insertType(t); } }, icon(TYPES[t].icon), h("span", { text: TYPES[t].name })))));
      }
      const ents = s ? filterEntities(app.ents, s, "").slice(0, 30) : app.recentEntities().slice(0, 6);
      if (ents.length) {
        const list = h("div", { class: "optlist", role: "listbox", "aria-label": "Sensors" });
        ents.forEach((e) => {
          const row = entityRow(e, (id) => { close(); app.insertEntity(id); });
          row.draggable = true;
          row.addEventListener("dragstart", (ev) => { ev.dataTransfer.setData("application/x-epaper-entity", e.entity_id); ev.dataTransfer.effectAllowed = "copy"; setTimeout(close, 0); });
          list.append(row);
        });
        body.append(h("div", { class: "poplab", text: s ? "Sensors" : "Recently used sensors" }), list);
      }
      if (!body.children.length) body.append(h("p", { class: "empty-note", text: `Nothing called “${q.value}”. Try part of the name, like temp.` }));
    };
    q.addEventListener("input", draw);
    q.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); const b = body.querySelector(".opt, .typecell"); if (b) b.click(); } });
    listNav(q, body);
    pop.append(h("div", { class: "search" }, icon("search", "sm"), q), body,
      h("p", { class: "fnote pad", text: "Pick one to add it to the middle of the page, or drag a sensor to where you want it." }),
      h("button", { class: "opt newpage", onclick: () => { close(); app.openPresets(); } }, icon("plus", "sm"), h("span", { class: "otext" }, h("span", { class: "o1", text: "A whole new page…" }), h("span", { class: "o2 plain", text: "From a preset, or blank" }))));
    draw();
  }, { label: "Insert", align: "left", focus: "input" });
}
