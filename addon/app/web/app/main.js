// The editor: canvas in the middle, the page strip under it, the inspector on
// the right. This file wires them together and holds the actions every part
// can ask for (insert, copy, paste, send…).

import { h, icon, api, prefs, clone, pageTitle, slug, modKey, isMac, setDevice } from "./util.js";
import { menu, toast, closeAll, isOpen } from "./ui.js";
import { Doc } from "./doc.js";
import { Canvas } from "./canvas.js";
import { renderStrip, statusSummary } from "./strip.js";
import { renderInspector } from "./inspector.js";
import { openEntityPicker, openAttributePicker, openIconPicker, openInsert } from "./pickers.js";
import { openPresets } from "./newpage.js";
import { savePresetSheet, openStatus, openSettings, resolveClashes, openShortcuts, openAddScreen, removeScreen } from "./sheets.js";
import { setCatalog } from "./catalog.js";
import { geometry, setDisplays, applyCatalog, makeElement, makeEntityElement, elName, TYPES, pairByType, LAYOUT_KEYS, normalizeLineParity } from "./elements.js";
import { syncDynamicGridShowIf, syncWidgetShowIf } from "./conditions.js";
import { CATEGORY_TERMS } from "./legacy.js";
import { unitsRows } from "./units.js";
import { renderScreenBar } from "./screenbar.js";

const ZOOM_STEPS = [0.75, 1, 1.25, 1.5, 2];
const ZOOM_MIN = 0.5, ZOOM_MAX = 3;                  // a pinch can go a little past the steps

const CLIP_KEY = "clipboard";

class App {
  constructor() {
    this.doc = new Doc();
    this.prefs = prefs;
    this.ents = []; this.entMap = new Map();
    this.status = null; this.device = null;
    this.screens = []; this.kinds = []; this.screen = null;
    this.el = {
      app: document.getElementById("app"), tb: document.getElementById("toolbar"), bar: document.getElementById("canvasbar"),
      area: document.getElementById("canvasarea"), strip: document.getElementById("strip"), insp: document.getElementById("inspector"),
      live: document.getElementById("live"), screenbar: document.getElementById("screenbar"),
    };
    this.canvas = new Canvas(this);
    this.el.area.append(this.canvas.device);
    this.unitsRows = (el, set) => unitsRows(this, el, set);
    this.doc.resolveClashes = (c) => resolveClashes(this, c);
    this.doc.on("change", () => { this.refresh(); this.canvas.preview(); });
    this.doc.on("select", () => { this.canvas.draw(); this.renderInspector(); this.renderLayers(); this.renderToolbar(); });
    this.doc.on("page", () => { if (this.doc.cur) prefs.set("page", this.doc.cur); this.canvas.stack = null; this.canvas.lastClick = null; this.canvas.layout(); this.refresh(); this.canvas.preview(true); });
    this.doc.on("saving", () => { this.renderToolbar(); this.renderStrip(); });
    this.doc.on("merged", (n) => toast(n ? "Merged with changes from another window." : "Merged with changes from another window. Nothing clashed."));
    this.doc.on("load", () => { this.canvas.layout(); this.refresh(); this.canvas.preview(true); });
    this.applyTheme();
    this.el.app.dataset.strip = prefs.get("strip_pos", "top");
    matchMedia("(min-width: 901px)").addEventListener("change", () => this.renderStrip());
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => this.applyTheme());
    this.wireKeys();
    this.wirePinch();
    addEventListener("beforeunload", (e) => { if (this.doc.saving !== "saved") { this.doc.flush(); e.preventDefault(); e.returnValue = ""; } });
    document.addEventListener("visibilitychange", () => { if (document.hidden) this.doc.flush(); else this.poll(); });
  }

  async boot() {
    this.loadMdi();
    this.renderToolbar();
    try {
      await this.loadScreens(prefs.get("device"));
      const note = await this.doc.load();
      const last = prefs.get("page");
      if (last && this.doc.spec.pages[last] && last !== this.doc.cur) { this.doc.cur = last; this.doc.emit("page"); }
      if (note) toast(note);
    } catch (e) {
      this.fatal(e.message);
      return;
    }
    await this.loadEntities();
    this.poll();
    setInterval(() => this.poll(), 15000);
    setInterval(() => this.loadEntities(), 60000);
    this.loadDevice();
    if (!Object.keys(this.doc.spec.pages).length) this.firstRun();
  }

  geometry() { return geometry(this.doc.spec); }
  /* Where the page strip sits: above the canvas (default), below it, or down
     the side. Down the side turns back into a row on narrow windows. */
  applyStripPos() {
    const pos = prefs.get("strip_pos", "top");
    this.el.app.dataset.strip = ["top", "bottom", "side"].includes(pos) ? pos : "top";
    const size = prefs.get("strip_size", "standard");
    this.el.app.dataset.stripsize = ["small", "standard", "large"].includes(size) ? size : "standard";
    this.renderStrip();
  }
  stripVertical() { return this.el.app.dataset.strip === "side" && matchMedia("(min-width: 901px)").matches; }
  say(text) { this.el.live.textContent = ""; requestAnimationFrame(() => { this.el.live.textContent = text; }); }
  toast(t, a) { toast(t, a); }
  notice(t) { toast(t); }
  fatal(msg) {
    this.el.area.replaceChildren(h("div", { class: "fatal" }, icon("warn"), h("h2", { text: "The editor couldn't load your pages" }), h("p", { text: msg }),
      h("button", { class: "btn primary", onclick: () => location.reload() }, "Try again")));
  }

  /* ---------- screens ---------- */
  /* The screens the add-on drives; the editor works on one at a time. */
  async loadScreens(want) {
    const r = (await api("api/devices")).body;
    // The canvas's sizes come only from here; without them there's nothing safe to draw.
    if (!r || !r.displays || !Object.keys(r.displays).length || !(r.devices || []).length)
      throw new Error("The add-on didn't say which devices it has. Restart the add-on, then reload this page.");
    // What the add-on knows (leagues, series, widgets, state words), once: read, never copied (catalog.js).
    if (!this.catalogLoaded) {
      try { setCatalog((await api("api/catalog")).body); applyCatalog(); this.catalogLoaded = true; }
      catch (e) { this.notice(`Couldn't load the add-on's widgets: ${e.message} Reload the page to try again.`); }
    }
    this.applyScreens(r, want);
  }
  applyScreens(r, want) {
    this.screens = r.devices || []; this.kinds = r.kinds || []; setDisplays(r.displays);
    const id = want || this.screen?.id;
    this.screen = this.screens.find((d) => d.id === id) || this.screens[0] || null;
    setDevice(this.screen?.id);
    if (this.screen) prefs.set("device", this.screen.id);
    this.renderToolbar(); this.renderBar(); renderScreenBar(this);
  }
  async switchScreen(id) {
    if (!id || id === this.screen?.id) return;
    await this.doc.flush();
    const to = this.screens.find((d) => d.id === id);
    if (!to) return;
    this.screen = to; setDevice(id); prefs.set("device", id);
    this.status = null; this.device = null; this.didScroll = false;
    try {
      const note = await this.doc.load();
      if (note) toast(note);
    } catch (e) { toast(`Couldn't open ${to.name}: ${e.message}`); return; }
    this.say(`Editing ${to.name}.`);
    this.poll(); this.loadDevice();
  }
  screenLine(d) {
    const parts = [d.display_name];
    if ([90, 270].includes(d.orientation)) parts.push("portrait");
    if (d.shares_with.length) parts.push(`same pages as ${d.shares_with.map((x) => x.name).join(", ")}`);
    if (d.setup === "pair" && !d.info?.paired) parts.push("not paired yet");
    if (d.sleeps && d.setup !== "pair") parts.push("sleeps between updates");
    return parts.join(" · ");
  }
  openScreens(anchor) {
    const items = this.screens.map((d) => ({ label: d.name, sub: this.screenLine(d), checked: d.id === this.screen?.id, run: () => this.switchScreen(d.id) }));
    // The screens; then this one's own (Rename, Remove); then adding another.
    const only = this.screens.length < 2;
    menu(anchor, [...items, "sep",
      { label: "Rename…", run: () => this.startRename() },
      { label: "Remove", danger: true, disabled: only, run: () => removeScreen(this, this.screen) },
      "sep",
      { label: "Add new device…", icon: "plus", run: () => openAddScreen(this) }], { label: "Devices" });
  }
  /* The name in the toolbar turns into a field where it stands (names are edited in
     place). Enter or clicking away keeps it; Esc puts it back. Settings › Device has it too. */
  startRename() {
    if (!this.screen) return;
    this.renaming = true;
    this.renderToolbar();
  }
  renameField(scr) {
    if (this.renameInput?.isConnected && this.renameInput.dataset.id === scr.id) return this.renameInput;
    const i = h("input", { class: "inp screenname", value: scr.name, maxlength: "60", autocomplete: "off", spellcheck: "false", "aria-label": `Rename ${scr.name}`, data: { id: scr.id } });
    let done = false;
    const back = () => { this.renameInput = null; this.renaming = false; this.renderToolbar(); this.el.tb.querySelector(".screenbtn")?.focus({ preventScroll: true }); };
    const finish = async (keep) => {
      if (done) return;
      done = true;
      const v = i.value.replace(/\s+/g, " ").trim();
      if (!keep || !v || v === scr.name) { back(); return; }
      i.disabled = true;
      try {
        this.applyScreens((await api(`api/devices/${encodeURIComponent(scr.id)}`, { method: "PATCH", body: { name: v } })).body);
        this.say(`Renamed to ${v}.`);
        back();
      } catch (e) {
        // Taken, say: keep what was typed so it can be fixed.
        toast(e.message); done = false; i.disabled = false; i.focus(); i.select();
      }
    };
    i.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); finish(true); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(false); }
    });
    i.addEventListener("blur", () => { if (!i.disabled) finish(true); });
    requestAnimationFrame(() => { i.focus({ preventScroll: true }); i.select(); });
    this.renameInput = i;
    return i;
  }

  /* ---------- data ---------- */
  async loadEntities() {
    try {
      this.ents = (await api("api/entities")).body || [];
      this.entMap = new Map(this.ents.map((e) => [e.entity_id, e]));
      this.refresh();
    } catch (_) { /* keep what we had */ }
  }
  async poll() {
    try { this.status = (await api("api/status")).body; } catch (_) { this.status = this.status || {}; }
    this.renderStrip();
  }
  async loadDevice() {
    try { this.device = (await api("api/panel-device")).body; } catch (_) { this.device = null; }
    this.renderStrip();
    return this.device;
  }
  async deviceSet(body, okMsg) {
    try {
      const r = (await api("api/panel-device", { method: "POST", body })).body;
      if (r.ok) toast(okMsg); else toast(`The panel didn't get it: ${r.error}.`);
    } catch (e) { toast(`The panel didn't get it: ${e.message}`); }
    setTimeout(() => this.loadDevice(), 1500);
  }
  recentEntities() {
    let recent = [];
    try { recent = JSON.parse(prefs.get("recent_entities", "[]")); } catch (_) {}
    const used = new Set(recent);
    for (const p of Object.values(this.doc.spec.pages)) for (const el of p.elements) if (el.entity) used.add(el.entity);
    return [...used].map((id) => this.entMap.get(id)).filter(Boolean);
  }
  remember(id) {
    let recent = [];
    try { recent = JSON.parse(prefs.get("recent_entities", "[]")); } catch (_) {}
    prefs.set("recent_entities", JSON.stringify([id, ...recent.filter((x) => x !== id)].slice(0, 8)));
  }

  /* Material Design icons, the same font the panel draws with. */
  async loadMdi() {
    this.mdi = null; this.mdiWaiters = [];
    try { this.mdi = (await api("api/mdi/all")).body || {}; } catch (_) { this.mdi = {}; }
    this.mdiWaiters.forEach((f) => f()); this.mdiWaiters = [];
    this.refresh();
  }
  mdiReady() { return !!this.mdi; }
  whenMdi(f) { if (this.mdi) return; this.mdiWaiters.push(f); }
  mdiGlyph(name) {
    if (!this.mdi || !name) return "";
    const cp = this.mdi[String(name).replace(/^mdi:/, "").trim().toLowerCase()];
    return cp !== undefined ? String.fromCodePoint(cp) : "";
  }
  searchIcons(q) {
    if (!this.mdi) return [];
    q = String(q || "").trim().toLowerCase().replace(/^mdi:/, "");
    const keys = Object.keys(this.mdi), out = [], seen = new Set();
    const push = (k) => { if (!seen.has(k) && this.mdi[k] !== undefined) { seen.add(k); out.push([k, String.fromCodePoint(this.mdi[k])]); } };
    if (!q) {
      ["paw", "cat", "dog", "radiator", "bed", "lightning-bolt", "power", "lightbulb", "home", "door", "thermometer", "fan", "solar-power", "battery-charging",
        "clock-outline", "fire", "water", "television", "wifi", "shield-check", "account", "bell", "calendar", "weather-partly-cloudy"].forEach(push);
      for (const k of keys) { if (out.length >= 96) break; push(k); }
      return out;
    }
    const terms = CATEGORY_TERMS[q] || q.split(/\s+/);
    terms.forEach(push);
    for (const t of terms) for (const k of keys) { if (out.length >= 250) break; if (k.startsWith(t) || k.includes("-" + t)) push(k); }
    for (const t of terms) for (const k of keys) { if (out.length >= 250) break; if (k.includes(t)) push(k); }
    return out;
  }

  /* ---------- drawing ---------- */
  /* The canvas's size comes from the add-on with the screens (elements.js
     DISPLAYS), so nothing that measures it draws before they've arrived. */
  ready() { return !!this.screen; }
  refresh() {
    if (!this.ready()) { this.renderToolbar(); return; }
    this.renderToolbar(); this.renderBar(); this.renderStrip(); this.renderInspector(); this.renderLayers(); renderScreenBar(this); this.canvas.draw();
    document.title = this.doc.cur ? `${pageTitle(this.doc.cur)} · e-Paper Panel` : "e-Paper Panel";
  }

  renderToolbar() {
    const doc = this.doc, tb = this.el.tb;
    const ib = (ic, label, kb, run, attrs = {}) => h("button", { class: "btn icon", "aria-label": label, title: kb ? `${label}  ${kb}` : label, onclick: run, ...attrs }, icon(ic));
    const save = doc.saving === "error" ? h("span", { class: "savestate bad", role: "status", title: doc.saveError }, icon("warn", "sm"), h("span", { class: "hide-narrow", text: "Not saved yet, retrying" }))
      : h("span", { class: "savestate", role: "status", "aria-live": "polite" }, h("span", { class: "hide-narrow", text: doc.saving === "saved" ? (doc.dirty ? "Saved, not sent" : "") : "Saving…" }));
    const sendLabel = doc.dirty ? "Send to panel. Some changes aren't on it yet" : "Send to panel";
    const sel = doc.sel.length;
    const scr = this.screen;
    const items = [
      scr && this.renaming ? this.renameField(scr) : null,
      // A double-click on the name renames it; the first click has opened the menu, which closes.
      scr && !this.renaming ? h("button", { class: "screenbtn", "aria-haspopup": "menu", "aria-label": `Editing ${scr.name}. Switch device, rename it or add one`, title: this.screenLine(scr),
        onclick: (e) => { if (e.detail === 2) { closeAll(); this.startRename(); } else if (e.detail < 2) this.openScreens(e.currentTarget); } },
        icon("panel", "sm"), h("span", { class: "sn", text: scr.name }), icon("down", "sm")) : null,
      ib("undo", "Undo", `${modKey}Z`, () => doc.undo(), { disabled: !doc.canUndo }),
      ib("redo", "Redo", `⇧${modKey}Z`, () => doc.redo(), { disabled: !doc.canRedo }),
      h("span", { class: "tbsep", role: "separator" }),
      h("button", { class: "btn tinted", "aria-label": "Insert a sensor, text or another element", title: `Insert  ${modKey}I`, disabled: !doc.page(), onclick: (e) => openInsert(this, e.currentTarget) }, icon("plus"), h("span", { class: "hide-narrow", text: "Insert" })),
      sel ? h("span", { class: "tbsel hide-narrow" },
        h("button", { class: "btn icon", "aria-label": "Copy", title: `Copy  ${modKey}C`, onclick: () => this.copy() }, icon("copy")),
        h("button", { class: "btn icon", "aria-label": "Duplicate", title: `Duplicate  ${modKey}D`, onclick: () => this.duplicate() }, icon("dup")),
        h("button", { class: "btn icon", "aria-label": "Delete", title: "Delete  ⌫", onclick: () => this.remove() }, icon("trash"))) : null,
      this.clip() ? h("button", { class: "btn icon hide-narrow", "aria-label": "Paste", title: `Paste  ${modKey}V`, disabled: !doc.page(), onclick: (e) => menu(e.currentTarget, [
        { label: "Paste", kb: `${modKey}V`, icon: "paste", run: () => this.paste() },
        { label: "Paste and match", kb: `⌥⇧${modKey}V`, icon: "paste", run: () => this.pasteMatch() }], { label: "Paste" }) }, icon("paste")) : null,
      h("span", { class: "spacer" }),
      save,
      ib("gear", "Settings", null, () => openSettings(this)),
      h("button", { class: "btn primary send", "aria-label": sendLabel, title: `${sendLabel}  ${modKey}S`, disabled: this.sending, onclick: () => this.send() },
        doc.dirty ? h("span", { class: "dot", "aria-hidden": "true" }) : null, icon("send", "sm show-narrow"), h("span", { class: "hide-narrow", text: this.sending ? "Sending…" : "Send to panel" }))].filter(Boolean);
    // While a name is being typed, the toolbar redraws around the field, so it keeps its focus and text.
    const field = this.renaming && this.renameInput?.isConnected && items[0] === this.renameInput ? this.renameInput : null;
    if (field) { [...tb.children].forEach((c) => { if (c !== field) c.remove(); }); tb.append(...items.slice(1)); }
    else tb.replaceChildren(...items);
  }

  /* ---------- zoom ---------- */
  /* Fit, or a size of the panel's own pixels (1 = actual size). Steps for the menu and
     ⌘+ ⌘−; a pinch goes anywhere between the ends. Remembered. */
  zoom() {
    if (matchMedia("(max-width: 760px)").matches) return "fit";       // a phone has no zoom control
    const z = prefs.get("zoom", "fit");
    if (z === "actual") return 1;                       // before 0.15: Fit or Actual size
    const n = Number(z);
    return z !== "fit" && n > 0 ? Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, n)) : "fit";
  }
  shownScale() {
    const z = this.zoom();
    if (z !== "fit") return z;
    // Fit's size from the area, as editor.css works it out (the frame may still be moving).
    const a = this.el.area, cs = getComputedStyle(a), g = this.geometry();
    const w = a.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    const hgt = a.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    return Math.max(0.01, (Math.min(w, (hgt - 32) * (g.W / g.H) + 24) - 24) / g.W);
  }
  // Keeps the point at (x, y) on screen where it was: the pointer for a pinch, else the middle of the view.
  setZoom(z, at) {
    const area = this.el.area, before = this.canvas.device.getBoundingClientRect(), view = area.getBoundingClientRect();
    const x = at?.x ?? view.left + view.width / 2, y = at?.y ?? view.top + view.height / 2;
    const fx = (x - before.left) / before.width, fy = (y - before.top) / before.height;
    prefs.set("zoom", z === "fit" ? "fit" : String(Math.round(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z)) * 1000) / 1000));
    this.applyZoom();
    if (z !== "fit") {
      const after = this.canvas.device.getBoundingClientRect();
      area.scrollLeft += after.left + fx * after.width - x;
      area.scrollTop += after.top + fy * after.height - y;
    }
    this.renderBar();
  }
  applyZoom() {
    const z = this.zoom(), area = this.el.area;
    area.classList.toggle("zoomed", z !== "fit");
    area.style.setProperty("--zoom", z === "fit" ? "1" : String(z));
  }
  zoomStep(dir) {
    const cur = this.shownScale();
    const next = dir > 0 ? ZOOM_STEPS.find((s) => s > cur + 0.001) : [...ZOOM_STEPS].reverse().find((s) => s < cur - 0.001);
    if (next) this.setZoom(next);
  }
  // A trackpad pinch: ctrl + wheel in Chrome and Firefox, gesture events in Safari.
  wirePinch() {
    const area = this.el.area;
    let start = 1, settle = null;
    const done = () => { clearTimeout(settle); settle = setTimeout(() => this.say(`Zoom ${Math.round(this.shownScale() * 100)}%.`), 300); };
    const narrow = () => matchMedia("(max-width: 760px)").matches;
    area.addEventListener("wheel", (e) => {
      if (!e.ctrlKey || narrow()) return;
      e.preventDefault();
      this.setZoom(this.shownScale() * Math.exp(-e.deltaY * 0.01), { x: e.clientX, y: e.clientY });
      done();
    }, { passive: false });
    area.addEventListener("gesturestart", (e) => { if (narrow()) return; e.preventDefault(); start = this.shownScale(); });
    area.addEventListener("gesturechange", (e) => { if (narrow()) return; e.preventDefault(); this.setZoom(start * e.scale, { x: e.clientX, y: e.clientY }); done(); });
    area.addEventListener("gestureend", (e) => { if (!narrow()) e.preventDefault(); });
  }
  zoomControl() {
    const z = this.zoom(), label = z === "fit" ? "Fit" : `${Math.round(z * 100)}%`;
    const cur = this.shownScale();
    return h("div", { class: "zoomc hide-narrow", role: "group", "aria-label": "Zoom" },
      h("button", { class: "btn icon small", "aria-label": "Zoom out", title: `Zoom out  ${modKey}−`, disabled: cur <= ZOOM_STEPS[0] + 0.001, onclick: () => this.zoomStep(-1) }, icon("minus", "sm")),
      h("button", { class: "btn small zoomv", "aria-haspopup": "menu", "aria-label": `Zoom: ${label}. Choose a size`, onclick: (e) => menu(e.currentTarget, [
        { label: "Fit", sub: "As big as the window allows", checked: z === "fit", run: () => this.setZoom("fit") },
        "sep",
        ...ZOOM_STEPS.map((s) => ({ label: `${s * 100}%`, kb: s === 1 ? `${modKey}0` : null, checked: z === s, run: () => this.setZoom(s) }))], { label: "Zoom", align: "right" }) },
        h("span", { text: label }), icon("down", "sm")),
      h("button", { class: "btn icon small", "aria-label": "Zoom in", title: `Zoom in  ${modKey}+`, disabled: cur >= ZOOM_STEPS[ZOOM_STEPS.length - 1] - 0.001, onclick: () => this.zoomStep(1) }, icon("plus", "sm")));
  }

  renderBar() {
    const doc = this.doc, bar = this.el.bar, p = doc.page();
    this.applyZoom();
    bar.replaceChildren(
      h("div", { class: "crumb" }, h("b", { text: p ? pageTitle(doc.cur) : "No page" }),
        p ? h("span", { class: "muted", text: p.tier === "alert" ? "Alert page" : p.tier === "when" ? "Shows only sometimes" : "Shows always" }) : null),
      this.shareLine() || "",
      h("span", { class: "spacer" }),
      h("button", { class: "btn small", "aria-pressed": String(prefs.get("guides") === "1"), title: "Show where the footer is, and every element's box", onclick: () => { prefs.set("guides", prefs.get("guides") === "1" ? "0" : "1"); this.refresh(); } }, icon("guides", "sm"), h("span", { class: "hide-narrow", text: "Guides" })),
      h("button", { class: "btn small", "aria-pressed": String(prefs.get("layers") === "1"), "aria-controls": "layers", title: "Layers, front first", onclick: () => this.showLayers() }, icon("layers", "sm"), h("span", { text: "Layers" })),
      this.zoomControl());
  }

  /* Pages shared with other screens: say so quietly, and what an edit here reaches. */
  shareLine() {
    const s = this.screen;
    if (!s || !s.shares_with.length) return null;
    const others = s.shares_with.map((x) => x.name).join(", ");
    const text = s.made_here ? `Shared with ${others}. Edits show on both.` : `Arranging for ${s.name}. What things show is shared with ${others}.`;
    return h("span", { class: "share hide-narrow", text, title: text });
  }

  renderStrip() {
    if (!this.ready()) return;
    const old = this.el.strip.querySelector(".tiles");
    const scroll = old ? [old.scrollLeft, old.scrollTop] : [0, 0];
    const focusedTile = document.activeElement?.closest?.(".tile");
    const fi = focusedTile ? [...this.el.strip.querySelectorAll(".tile")].indexOf(focusedTile) : -1;
    this.el.strip.replaceChildren(renderStrip(this));
    const n = this.el.strip.querySelector(".tiles");
    // In a row, status and New page together are exactly one page preview tall.
    const front = this.el.strip.querySelector(".stripfront"), first = this.el.strip.querySelector(".tile");
    if (front) front.style.height = !this.stripVertical() && first ? first.offsetHeight + "px" : "";
    if (n) { n.scrollLeft = scroll[0]; n.scrollTop = scroll[1]; n.closest(".slider")?.sync(); }   // edges as they were, no fade-in
    if (fi >= 0) { const t = this.el.strip.querySelectorAll(".tile")[fi]; if (t) t.focus({ preventScroll: true }); }
    if (n && !this.didScroll) { const c = n.querySelector('[aria-current="page"]'); if (c) { c.scrollIntoView({ inline: "nearest", block: "nearest" }); this.didScroll = true; } }
  }

  renderInspector() {
    const insp = this.el.insp;
    // Don't rebuild under someone's typing; the field commits on change.
    const active = document.activeElement;
    const typing = active && insp.contains(active) && /INPUT|TEXTAREA/.test(active.tagName) && active.type !== "range";
    if (typing && this.inspKey === this.inspectorKey()) return;
    const scroll = insp.querySelector(".insp-body")?.scrollTop || 0;
    const focusId = active && insp.contains(active) ? active.getAttribute("aria-label") || active.id : null;
    const [head, body] = renderInspector(this);
    const grab = h("button", { class: "grab", "aria-label": insp.classList.contains("open") ? "Collapse the inspector" : "Expand the inspector", onclick: () => { insp.classList.toggle("open"); this.renderInspector(); } });
    insp.replaceChildren(grab, head, body);
    if (this.inspKey === this.inspectorKey()) body.scrollTop = scroll;
    this.inspKey = this.inspectorKey();
    if (focusId) { const f = [...insp.querySelectorAll("[aria-label], [id]")].find((x) => x.getAttribute("aria-label") === focusId || x.id === focusId); if (f && f.focus) f.focus({ preventScroll: true }); }
  }
  inspectorKey() { return `${this.doc.cur}|${this.doc.sel.join(",")}`; }
  inspectorSoon() { cancelAnimationFrame(this.inspRaf); this.inspRaf = requestAnimationFrame(() => this.renderInspector()); }
  onMetrics(m) {
    // The page's own note follows a countdown's state; redrawn only when that changes, so typing isn't lost.
    const cd = JSON.stringify((m || []).find((x) => x.countdown)?.countdown || null);
    const redrawPage = !this.doc.sel.length && cd !== this._countdown;
    this._countdown = cd;
    if (this.doc.sel.length === 1 || redrawPage) this.renderInspector();
  }
  liveFields(el) {
    const q = this.el.insp.querySelectorAll(".quad input");
    if (q.length === 4) ["x", "y", "w", "h"].forEach((k, i) => { q[i].value = el[k]; });
  }

  /* ---------- layers ---------- */
  showLayers(force) {
    const on = force === true ? true : prefs.get("layers") !== "1";
    prefs.set("layers", on ? "1" : "0");
    this.renderBar(); this.renderLayers();
    if (on) requestAnimationFrame(() => document.querySelector("#layers .lrow")?.focus());
  }
  renderLayers() {
    const host = document.getElementById("layers");
    const on = prefs.get("layers") === "1" && !!this.doc.page();
    host.hidden = !on;
    document.getElementById("stage").classList.toggle("with-layers", on);
    if (!on) return;
    const doc = this.doc, els = doc.els();
    const list = h("div", { class: "llist", role: "listbox", "aria-label": "Layers, front first", "aria-multiselectable": "true" });
    const order = els.map((_, i) => i).reverse();
    const rows = order.map((i) => {
      const { t, d } = elName(els[i], this.entMap);
      const r = h("button", { class: "lrow", role: "option", "aria-selected": String(doc.sel.includes(i)), "aria-label": `${t} ${d}` },
        h("span", { class: "glyph" }, icon(TYPES[els[i].type]?.icon || "square", "sm")),
        h("span", { class: "rtext" }, h("span", { class: "r1", text: t }), d ? h("span", { class: "r2", text: d }) : null),
        h("span", { class: "grip", "aria-hidden": "true" }, icon("grip", "sm")));
      r.addEventListener("pointerenter", () => { this.canvas.rowHover = i; this.canvas.draw(); });
      r.addEventListener("pointerleave", () => { this.canvas.rowHover = -1; this.canvas.draw(); });
      return r;
    });
    rows.forEach((r) => list.append(r));
    // Drag a row to reorder; click selects (shift adds); Alt+↑↓ moves.
    rows.forEach((r, k) => {
      r.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        const sy = e.clientY; let drag = false, target = k, mark = null;
        const rects = rows.map((x) => x.getBoundingClientRect());
        try { r.setPointerCapture(e.pointerId); } catch (_) {}
        const move = (ev) => {
          if (!drag && Math.abs(ev.clientY - sy) < 4) return;
          if (!drag) { drag = true; r.classList.add("lifted"); mark = h("div", { class: "insert-mark h" }); list.append(mark); }
          r.style.transform = `translateY(${ev.clientY - sy}px)`;
          target = rects.filter((x) => x.top + x.height / 2 < ev.clientY).length;
          const lr = list.getBoundingClientRect(), rr = rects[Math.min(target, rects.length - 1)];
          mark.style.top = ((target < rects.length ? rr.top - 2 : rr.bottom) - lr.top + list.scrollTop) + "px";
        };
        const up = (ev) => {
          r.removeEventListener("pointermove", move); r.removeEventListener("pointerup", up);
          if (mark) mark.remove(); r.style.transform = ""; r.classList.remove("lifted");
          if (!drag) { const i = order[k]; doc.select(ev.shiftKey ? (doc.sel.includes(i) ? doc.sel.filter((x) => x !== i) : [...doc.sel, i]) : [i]); return; }
          if (target !== k && target !== k + 1) this.moveLayer(order, k, target);
        };
        r.addEventListener("pointermove", move); r.addEventListener("pointerup", up);
      });
      r.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); doc.select([order[k]]); }
        else if (e.altKey && e.key === "ArrowUp" && k > 0) { e.preventDefault(); this.moveLayer(order, k, k - 1, true); }
        else if (e.altKey && e.key === "ArrowDown" && k < rows.length - 1) { e.preventDefault(); this.moveLayer(order, k, k + 2, true); }
        else if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); const n = rows[k + (e.key === "ArrowDown" ? 1 : -1)]; if (n) n.focus(); }
      });
    });
    host.replaceChildren(h("div", { class: "lhead" }, h("h2", { text: "Layers" }), h("span", { class: "muted", text: "Front at the top" }),
      h("button", { class: "btn icon", "aria-label": "Close layers", onclick: () => this.showLayers(false) }, icon("close", "sm"))),
      els.length ? list : h("p", { class: "empty-note", text: "Nothing on this page yet." }));
  }
  moveLayer(order, from, to, keepFocus) {
    const doc = this.doc, els = doc.els();
    const newOrder = order.slice(); const [m] = newOrder.splice(from, 1); newOrder.splice(to > from ? to - 1 : to, 0, m);
    const items = newOrder.slice().reverse().map((k) => els[k]);
    const selEls = doc.sel.map((k) => els[k]);
    const moved = els[order[from]];
    doc.page().elements = items;
    doc.sel = selEls.map((e) => items.indexOf(e)).filter((i) => i >= 0);
    doc.commit();
    const { t } = elName(moved, this.entMap);
    this.say(`${t} is now layer ${items.length - items.indexOf(moved)} of ${items.length}.`);
    if (keepFocus) requestAnimationFrame(() => document.querySelectorAll("#layers .lrow")[to > from ? to - 1 : to]?.focus());
  }

  /* ---------- actions ---------- */
  insertType(t) {
    const doc = this.doc, el = makeElement(t, this.geometry());
    if (t === "box") { doc.els().unshift(el); doc.sel = [0]; }                 // cards go behind what they frame
    else { doc.els().push(el); doc.sel = [doc.els().length - 1]; }
    if (doc.page().tier === "when" && t === "dynamic_grid") syncDynamicGridShowIf(doc.page(), el);
    doc.commit();
    this.say(`Added ${TYPES[t].name}`);
    this.openInspectorOnPhone();
  }
  insertEntity(id) {
    const doc = this.doc, ent = this.entMap.get(id) || { entity_id: id, state: "" };
    doc.els().push(makeEntityElement(ent, this.geometry()));
    doc.sel = [doc.els().length - 1];
    this.remember(id);
    doc.commit();
    this.say(`Added ${ent.name || id}`);
    this.openInspectorOnPhone();
  }
  openInspectorOnPhone() { if (matchMedia("(max-width: 760px)").matches) this.el.insp.classList.add("open"); }

  uniqueName(base) { let n = slug(base) || "page", k = 2; const b = n; while (this.doc.spec.pages[n]) n = `${b}_${k++}`; return n; }
  addPage(base, page) {
    const doc = this.doc, n = this.uniqueName(base);
    doc.spec.pages[n] = page;
    if (page.tier !== "alert") doc.spec.rotation.push(n);
    doc.cur = n; doc.sel = [];
    doc.commit(); doc.emit("page");
    toast(`Added ${pageTitle(n)}. Rename it in the inspector.`, { label: "Undo", run: () => doc.undo() });
    requestAnimationFrame(() => { const t = this.el.strip.querySelector('[aria-current="page"]'); if (t) t.scrollIntoView({ inline: "nearest", block: "nearest" }); });
  }
  renamePage(old, raw) {
    const doc = this.doc, n = slug(raw);
    if (!n || n === old || doc.spec.pages[n]) { this.renderInspector(); return; }
    const pages = {};
    for (const [k, v] of Object.entries(doc.spec.pages)) pages[k === old ? n : k] = v;
    doc.spec.pages = pages;
    doc.spec.rotation = doc.spec.rotation.map((x) => (x === old ? n : x));
    doc.cur = n;
    doc.commit();
    toast(`Renamed ${pageTitle(old)} to ${pageTitle(n)}.`, { label: "Undo", run: () => doc.undo() });
  }
  duplicatePage(name = this.doc.cur) {
    const doc = this.doc, n = this.uniqueName(name + "_copy");
    doc.spec.pages[n] = clone(doc.spec.pages[name]);
    if ((doc.spec.pages[n].tier || "rotate") !== "alert") doc.spec.rotation.push(n);
    doc.cur = n; doc.sel = [];
    doc.commit(); doc.emit("page");
    toast(`Duplicated as ${pageTitle(n)}. Rename it in the inspector.`, { label: "Undo", run: () => doc.undo() });
  }
  deletePage(name = this.doc.cur) {
    const doc = this.doc;
    delete doc.spec.pages[name];
    doc.spec.rotation = doc.spec.rotation.filter((n) => n !== name);
    if (doc.cur === name) { doc.cur = doc.firstPage(); doc.sel = []; }
    doc.commit(); doc.emit("page");
    toast(`Deleted ${pageTitle(name)}.`, { label: "Undo", run: () => doc.undo() });
    if (!Object.keys(doc.spec.pages).length) this.firstRun();
  }
  setTier(v) {
    const doc = this.doc, p = doc.page();
    p.tier = v;
    if (v === "alert") doc.spec.rotation = doc.spec.rotation.filter((n) => n !== doc.cur);
    else if (!doc.spec.rotation.includes(doc.cur)) doc.spec.rotation.push(doc.cur);
    if (v === "when") { syncDynamicGridShowIf(p); syncWidgetShowIf(p); }
    this.rawCondition = this.rawUntil = false;
    doc.commit();
  }
  savePreset() { savePresetSheet(this); }

  order(where) {
    const doc = this.doc;
    if (doc.sel.length !== 1) return;
    const arr = doc.els(), i = doc.sel[0], el = arr[i];
    arr.splice(i, 1);
    const j = where === "front" ? arr.length : where === "back" ? 0 : where === "fwd" ? Math.min(arr.length, i + 1) : Math.max(0, i - 1);
    arr.splice(j, 0, el);
    doc.sel = [j];
    doc.commit();
    this.say(`${{ front: "In front of everything", back: "Behind everything", fwd: "One layer forward", bwd: "One layer back" }[where]}: layer ${arr.length - j} of ${arr.length}.`);
  }
  align(kind) {
    const doc = this.doc, items = doc.selected();
    if (items.length < 2) return;
    if (kind === "dh" || kind === "dv") {
      // Space around, across the panel: the same gap between the elements and
      // at both ends (the whole width, or from the top to the footer). If
      // they're too wide for any gap, their centres are spaced evenly.
      const g = this.geometry();
      const k = kind === "dh" ? "x" : "y", size = kind === "dh" ? "w" : "h";
      const s = items.slice().sort((a, b) => (a[k] + a[size] / 2) - (b[k] + b[size] / 2));
      const start = 0, end = kind === "dh" ? g.W : g.safeH;
      const gap = (end - start - s.reduce((t, e) => t + e[size], 0)) / (s.length + 1);
      if (gap >= 0) {
        let at = start + gap;
        s.forEach((it) => { it[k] = Math.round(at); at += it[size] + gap; });
      } else {
        const step = (end - start) / s.length;
        s.forEach((it, i) => { it[k] = Math.round(start + step * (i + 0.5) - it[size] / 2); });
      }
    } else {
      const minX = Math.min(...items.map((e) => e.x)), maxR = Math.max(...items.map((e) => e.x + e.w));
      const minY = Math.min(...items.map((e) => e.y)), maxB = Math.max(...items.map((e) => e.y + e.h));
      items.forEach((e) => {
        if (kind === "l") e.x = minX;
        if (kind === "r") e.x = maxR - e.w;
        if (kind === "t") e.y = minY;
        if (kind === "b") e.y = maxB - e.h;
        if (kind === "cx") { const ref = items.filter((x) => !(x.type === "line" && x.h >= x.w)); const a = Math.min(...(ref.length ? ref : items).map((x) => x.x)), b = Math.max(...(ref.length ? ref : items).map((x) => x.x + x.w)); const mid = Math.round((a + b) / 2); if (e.type === "line" && e.h >= e.w) normalizeLineParity(e, mid, "x"); else { if (e.type === "icon" && e.w % 2) e.w += 1; e.x = Math.round(mid - e.w / 2); } }
        if (kind === "cy") { const ref = items.filter((x) => !(x.type === "line" && x.w > x.h)); const a = Math.min(...(ref.length ? ref : items).map((x) => x.y)), b = Math.max(...(ref.length ? ref : items).map((x) => x.y + x.h)); const mid = Math.round((a + b) / 2); if (e.type === "line" && e.w > e.h) normalizeLineParity(e, mid, "y"); else { if (e.type === "icon" && e.h % 2) e.h += 1; e.y = Math.round(mid - e.h / 2); } }
      });
    }
    doc.commit();
  }
  duplicate() {
    const doc = this.doc;
    if (!doc.sel.length) return;
    const g = this.geometry(), els = doc.els();
    const copies = doc.sel.slice().sort((a, b) => a - b).map((k) => { const c = clone(els[k]); delete c.id; delete c._auto; c.x = Math.min(g.W - c.w, c.x + 12); c.y = Math.min(g.H - c.h, c.y + 12); return c; });
    els.push(...copies);
    doc.sel = copies.map((_, k) => els.length - copies.length + k);
    doc.commit();
  }
  remove() {
    const doc = this.doc, n = doc.sel.length;
    if (!n) return;
    doc.page().elements = doc.els().filter((_, k) => !doc.sel.includes(k));
    doc.sel = [];
    doc.commit();
    toast(`Deleted ${n === 1 ? "1 element" : n + " elements"}.`, { label: "Undo", run: () => doc.undo() });
  }

  /* Copy and paste keep position and size, across pages, reloads and windows
     (the clipboard lives in this browser). */
  clip() { try { return JSON.parse(prefs.get(CLIP_KEY, "null")); } catch (_) { return null; } }
  copy(cut) {
    const doc = this.doc;
    if (!doc.sel.length) return;
    const items = doc.sel.slice().sort((a, b) => a - b).map((k) => clone(doc.els()[k]));
    prefs.set(CLIP_KEY, JSON.stringify({ from: doc.cur, items }));
    try { if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(JSON.stringify({ epaper: items })).catch(() => {}); } catch (_) {}
    if (cut) { doc.page().elements = doc.els().filter((_, k) => !doc.sel.includes(k)); doc.sel = []; doc.commit(); }
    else this.renderToolbar();
    const what = items.length === 1 ? elName(items[0], this.entMap).t.toLowerCase() : `${items.length} elements`;
    toast(`${cut ? "Cut" : "Copied"} ${what}. Paste on any page to put ${items.length === 1 ? "it" : "them"} in the same place.`);
  }
  paste() {
    const doc = this.doc, c = this.clip();
    if (!c?.items?.length) { toast("Nothing to paste. Copy something first."); return; }
    if (!doc.page()) return;
    const g = this.geometry(), els = doc.els();
    const onTop = c.items.every((it) => els.some((e) => e.type === it.type && e.x === it.x && e.y === it.y && e.w === it.w && e.h === it.h));
    const items = c.items.map((it) => { const n = clone(it); delete n.id; delete n._auto; if (onTop) { n.x = Math.min(g.W - n.w, n.x + 12); n.y = Math.min(g.H - n.h, n.y + 12); } return n; });
    els.push(...items);
    doc.sel = items.map((_, k) => els.length - items.length + k);
    doc.commit();
    const where = onTop ? "a little offset, since the originals are right there" : c.from && c.from !== doc.cur && doc.spec.pages[c.from] ? `in the same place as on ${pageTitle(c.from)}` : "in the same place";
    toast(`Pasted ${items.length === 1 ? "1 element" : items.length + " elements"} ${where}.`, { label: "Undo", run: () => doc.undo() });
  }
  /* Paste and match: what you copied lends its place, size and text style to
     what's here, paired by kind in order. Your sensors and words stay. */
  pasteMatch() {
    const doc = this.doc, c = this.clip();
    if (!c?.items?.length) { toast("Nothing to match. Copy the elements whose layout you want, then come back."); return; }
    const targets = doc.sel.length ? doc.sel.slice().sort((a, b) => a - b).map((k) => doc.els()[k]) : doc.els();
    const pairs = pairByType(targets, c.items);
    let n = 0;
    for (const [mine, src] of pairs) {
      if (!src) continue;
      for (const k of LAYOUT_KEYS) { if (src[k] !== undefined) mine[k] = clone(src[k]); else if (!["x", "y", "w", "h"].includes(k)) delete mine[k]; }
      n++;
    }
    if (!n) { toast("Nothing here matches what you copied. Paste and match pairs elements of the same kind."); return; }
    doc.commit();
    const left = pairs.length - n;
    toast(`Matched ${n} element${n === 1 ? "" : "s"}${c.from && doc.spec.pages[c.from] ? ` to ${pageTitle(c.from)}` : ""}${left ? `; ${left} had no partner and stayed put` : ""}.`, { label: "Undo", run: () => doc.undo() });
  }

  async send() {
    if (this.sending) return;
    this.sending = true; this.renderToolbar(); this.renderStrip();
    try {
      await this.doc.send();
      let pushed = null;
      try { pushed = (await api("api/push", { method: "POST" })).body; } catch (_) {}
      if (pushed && pushed.pushed) toast("Sent. The panel is updating now.");
      else toast(`Sent. The panel will update as soon as it can be reached${pushed?.error ? ` (${pushed.error})` : ""}.`);
    } catch (e) {
      toast(`Couldn't send: ${e.message}`);
    } finally {
      this.sending = false;
      this.renderToolbar();
      this.poll();
      this.loadScreens().catch(() => {});             // its size may have changed with what was sent
    }
  }

  /* ---------- menus ---------- */
  openCanvasMenu(e, hits) {
    const doc = this.doc, has = doc.sel.length > 0, clip = this.clip();
    const items = [
      { label: "Cut", kb: `${modKey}X`, icon: "scissors", disabled: !has, run: () => this.copy(true) },
      { label: "Copy", kb: `${modKey}C`, icon: "copy", disabled: !has, run: () => this.copy() },
      { label: "Paste", kb: `${modKey}V`, icon: "paste", disabled: !clip, run: () => this.paste() },
      { label: "Paste and match", kb: `⌥⇧${modKey}V`, icon: "paste", disabled: !clip, run: () => this.pasteMatch() },
      { label: "Duplicate", kb: `${modKey}D`, icon: "dup", disabled: !has, run: () => this.duplicate() },
      { label: "Delete", kb: "⌫", icon: "trash", disabled: !has, run: () => this.remove() },
    ];
    if (hits.length > 1) {
      items.push("sep", { heading: "Under the pointer" });
      hits.forEach((k) => { const { t, d } = elName(doc.els()[k], this.entMap); items.push({ label: `${t}${d ? " · " + d : ""}`, icon: TYPES[doc.els()[k].type]?.icon, checked: doc.sel.includes(k), run: () => doc.select([k]) }); });
    }
    items.push("sep", { label: "Bring to front", kb: `⌥${modKey}]`, icon: "front", disabled: doc.sel.length !== 1, run: () => this.order("front") },
      { label: "Send to back", kb: `⌥${modKey}[`, icon: "back2", disabled: doc.sel.length !== 1, run: () => this.order("back") });
    menu(null, items, { at: { x: e.clientX, y: e.clientY }, label: "Element" });
  }
  openPageMenu(e, n, anchor) {
    const doc = this.doc, p = doc.spec.pages[n], times = doc.spec.rotation.filter((x) => x === n).length;
    menu(anchor || null, [
      { label: "Open", run: () => doc.openPage(n) },
      { label: "Duplicate", icon: "dup", run: () => this.duplicatePage(n) },
      p.tier !== "alert" ? { label: times ? "Show again" : "Add to rotation", run: () => { doc.spec.rotation.push(n); doc.commit(); } } : null,
      p.tier !== "alert" && times ? { label: times > 1 ? "Show once less" : "Take out of rotation", run: () => { doc.spec.rotation.splice(doc.spec.rotation.lastIndexOf(n), 1); doc.commit(); } } : null,
      "sep",
      { label: "Delete", icon: "trash", danger: true, run: () => this.deletePage(n) },
    ], { ...(anchor ? { align: "right" } : { at: { x: e.clientX, y: e.clientY } }), label: pageTitle(n) });
  }
  openStatus(anchor) { openStatus(this, anchor); }
  openPresets() { openPresets(this); }
  openEntityPicker(anchor, onPick, opts) { openEntityPicker(this, anchor, onPick, opts); }
  openAttributePicker(anchor, entity, onPick) { openAttributePicker(this, anchor, entity, onPick); }
  openIconPicker(cur, onPick) { openIconPicker(this, cur, onPick); }

  firstRun() {
    if (Object.keys(this.doc.spec.pages).length) return;
    this.el.area.querySelector(".firstrun")?.remove();
    this.el.area.append(h("div", { class: "firstrun" }, h("h2", { text: "No pages yet" }),
      h("p", { text: "A page is one screen on the panel. Start from a preset and pick your sensor, or start blank." }),
      h("div", { class: "btnrow center" },
        h("button", { class: "btn primary", onclick: (e) => { e.currentTarget.closest(".firstrun").remove(); this.openPresets(); } }, "Choose a preset"),
        h("button", { class: "btn tinted", onclick: (e) => { e.currentTarget.closest(".firstrun").remove(); this.addPage("untitled", { tier: "rotate", elements: [] }); } }, "Blank page"))));
  }

  /* ---------- appearance ---------- */
  applyTheme() {
    const t = prefs.get("theme", "system");
    const dark = t === "dark" || (t === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }

  /* ---------- keyboard ---------- */
  wireKeys() {
    addEventListener("keydown", (e) => {
      const doc = this.doc;
      if (isOpen()) return;                                    // sheets and popovers handle their own keys
      const t = e.target, typing = /INPUT|TEXTAREA|SELECT/.test(t.tagName) || t.isContentEditable;
      const mod = isMac ? e.metaKey : e.ctrlKey, k = e.key.toLowerCase();
      if (mod && k === "s") { e.preventDefault(); this.send(); return; }
      if (typing) return;
      if (mod && (e.key === "=" || e.key === "+")) { e.preventDefault(); this.zoomStep(1); return; }
      if (mod && (e.key === "-" || e.key === "_")) { e.preventDefault(); this.zoomStep(-1); return; }
      if (mod && e.key === "0") { e.preventDefault(); this.setZoom(1); return; }
      if (mod && k === "z") { e.preventDefault(); e.shiftKey ? doc.redo() : doc.undo(); return; }
      if (mod && k === "y") { e.preventDefault(); doc.redo(); return; }
      if (!doc.page()) return;
      if (mod && k === "c") { e.preventDefault(); this.copy(); return; }
      if (mod && k === "x") { e.preventDefault(); this.copy(true); return; }
      if (mod && k === "v") { e.preventDefault(); if (e.shiftKey && e.altKey) this.pasteMatch(); else this.paste(); return; }
      if (mod && k === "d") { e.preventDefault(); this.duplicate(); return; }
      if (mod && k === "a") { e.preventDefault(); doc.select(doc.els().map((_, i) => i)); return; }
      if (mod && k === "i") { e.preventDefault(); openInsert(this, this.el.tb.querySelector(".btn.tinted")); return; }
      if (mod && (e.key === "]" || e.key === "[")) { e.preventDefault(); this.order(e.key === "]" ? (e.altKey ? "front" : "fwd") : (e.altKey ? "back" : "bwd")); return; }
      if (mod && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        e.preventDefault();
        const names = [...new Set([...doc.spec.rotation, ...Object.keys(doc.spec.pages)])];
        const i = names.indexOf(doc.cur), n = names[(i + (e.key === "ArrowDown" ? 1 : -1) + names.length) % names.length];
        doc.openPage(n); this.say(`${pageTitle(n)}`);
        return;
      }
      if (e.key === "?" ) { e.preventDefault(); openShortcuts(); return; }
      if (e.key === "Escape") { if (doc.sel.length) { doc.select([]); this.canvas.stack = null; } return; }
      if (t === this.canvas.panel && e.key === "Tab" && !mod) {
        const n = doc.els().length; if (!n) return;
        const cur = doc.sel.length === 1 ? doc.sel[0] : (e.shiftKey ? n : -1);
        const next = cur + (e.shiftKey ? -1 : 1);
        if (next < 0 || next >= n) { doc.select([]); return; }      // let focus leave the canvas
        e.preventDefault();
        doc.select([next]);
        const { t: tn, d } = elName(doc.els()[next], this.entMap);
        this.say(`${tn}${d ? ", " + d : ""}, ${next + 1} of ${n}`);
        return;
      }
      if (!doc.sel.length) return;
      if (e.key === "Backspace" || e.key === "Delete") { e.preventDefault(); this.remove(); return; }
      const st = e.shiftKey ? 10 : 1;
      const m = { ArrowLeft: [-st, 0], ArrowRight: [st, 0], ArrowUp: [0, -st], ArrowDown: [0, st] }[e.key];
      if (m && !mod) {
        e.preventDefault();
        const g = this.geometry();
        doc.selected().forEach((el) => { el.x = Math.max(0, Math.min(g.W - el.w, el.x + m[0])); el.y = Math.max(0, Math.min(g.H - el.h, el.y + m[1])); });
        doc.commit("nudge");
      }
    });
  }
}

const app = new App();
window.__editor = app;            // for debugging from the console
app.boot();
