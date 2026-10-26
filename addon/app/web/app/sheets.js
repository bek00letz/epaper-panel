// The bigger jobs, each in a sheet: a new page, settings, what's on the panel
// now, the whole strip, saving a preset, and the rare question of which
// version to keep.

import { h, icon, api, clone, pageTitle, slug, modKey, prefs, withDevice, span, seconds, turning } from "./util.js";
import { sheet, popover, field, input, number, select, seg, toggle, toggleRow, section, linkButton, toast, closeAll } from "./ui.js";
import { DISPLAYS, isWidget } from "./elements.js";
import { describe, parseShowIf, syncDynamicGridShowIf, partOn, showsWords } from "./conditions.js";
import { reflowPageElements } from "./legacy.js";
import { LOOKS as PRESETS, clockPages, dateInstead } from "./presets.js";
import { thumbnail, statusSummary, forgetThumbnails, unsentWords } from "./strip.js";
import { SETTING_NAMES } from "./doc.js";
import { paint } from "./glyphs.js";
import { problemLines, servicesPane } from "./services.js";
import { formNote } from "./data.js";
import { widgets as widgetDescriptors } from "./catalog.js";

const thumbImg = (app, key, page) => {
  const img = h("img", { class: "thumb", alt: "", "data-thumb": key, draggable: "false" });
  requestAnimationFrame(() => thumbnail(app, key, img, page));
  return h("span", { class: "thumbwrap", style: { aspectRatio: `${app.geometry().W} / ${app.geometry().H}` } }, img);
};

/* ---------- a new page ---------- */
// Which sensors a preset can show. Most ask for a kind of entity; the
// Jellyfin ones want a Jellyfin source's own sensor (the server marks them).
const fits = (p, e) => (p.asks === "jellyfin" ? e.feed === "jellyfin" : e.entity_id.startsWith(p.asks + "."));
const candidates = (app, p) => app.ents.filter((e) => fits(p, e));
const guess = (app, p) => (p.asks === "jellyfin" ? (candidates(app, p)[0] || {}).entity_id || "" : "");

// The 0.10 New page sheet: one grid of every look. Not used since 0.15's
// shelves (newpage.js); kept as the way back until they've proven themselves.
export function openPresetsGrid(app) {
  const close = sheet("New page", (node, close) => {
    const body = h("div", { class: "sheet-body" });
    const grid = h("div", { class: "presetgrid" });
    const card = (key, page, title, desc, onPick, extra) => h("div", { class: "pcard" },
      h("button", { class: "pbtn", onclick: onPick, "aria-label": `${title}. ${desc}` }, thumbImg(app, key, page), h("span", { class: "pt", text: title }), h("span", { class: "pd", text: desc })), extra);
    grid.append(card("preset:__blank", { elements: [] }, "Blank", "Start from nothing.", () => { close(); app.addPage("untitled", { tier: "rotate", elements: [] }); }));
    (app.doc.spec.custom_presets || []).forEach((cp, k) => grid.append(card("preset:custom" + k, { elements: cp.elements }, cp.title || cp.name, cp.desc || "One of yours.", () => { close(); app.addPage(cp.id || "page", { tier: cp.tier || "rotate", show_if: cp.show_if || undefined, elements: clone(cp.elements || []) }); },
      h("button", { class: "btn icon pdel", "aria-label": `Delete the preset ${cp.title || cp.name}`, onclick: () => {
        app.doc.spec.custom_presets.splice(k, 1); app.doc.commit(); close();
        toast(`Deleted the preset ${cp.title || cp.name}.`, { label: "Undo", run: () => app.doc.undo() });
      } }, icon("close", "sm")))));
    PRESETS.forEach((p) => grid.append(card("preset:" + p.id, { elements: p.makeElements(guess(app, p)) }, p.title, p.desc, () => {
      // One Jellyfin source is the answer already; don't ask.
      const only = p.asks === "jellyfin" && candidates(app, p).length === 1;
      if (only) { close(); addFromPreset(app, p, guess(app, p)); }
      else if (p.asks) step2(app, node, close, p); else { close(); addFromPreset(app, p, ""); }
    })));
    if ((app.doc.spec.custom_presets || []).length) body.append(h("p", { class: "fnote", text: "Yours first, then the built-in ones." }));
    body.append(grid);
    node.append(body);
  }, { cls: "wide tall" });
  return close;
}

function step2(app, node, close, p) {
  const head = node.querySelector(".sheet-head h2");
  head.textContent = p.title;
  const q = h("input", { type: "search", placeholder: "Search", "aria-label": "Search sensors", autocomplete: "off" });
  const list = h("div", { class: "optlist", role: "listbox", "aria-label": "Sensors" });
  const preview = h("div", { class: "pv" });
  let chosen = "";
  const add = h("button", { class: "btn primary", disabled: true, onclick: () => { close(); addFromPreset(app, p, chosen); } }, "Add page");
  const drawPreview = () => preview.replaceChildren(thumbImg(app, "preset:" + p.id + ":" + chosen, { elements: p.makeElements(chosen) }));
  const draw = () => {
    const s = q.value.toLowerCase();
    const found = app.ents.filter((e) => (s ? (e.entity_id.includes(s) || (e.name || "").toLowerCase().includes(s)) : fits(p, e)));
    list.replaceChildren(...found.slice(0, 80).map((e) => h("button", { class: "opt" + (chosen === e.entity_id ? " active" : ""), role: "option", "aria-selected": String(chosen === e.entity_id),
      onclick: () => { chosen = e.entity_id; add.disabled = false; draw(); drawPreview(); } },
      h("span", { class: "otext" }, h("span", { class: "o1", text: e.name || e.entity_id }), h("span", { class: "o2", text: e.entity_id })), h("span", { class: "ov", text: `${e.state}${e.unit ? " " + e.unit : ""}` }))));
    if (!found.length) list.append(h("p", { class: "empty-note", text: s ? "Nothing matches. Try part of the name."
      : p.asks === "jellyfin" ? "No Jellyfin source yet. Add one in Settings, under Data sources, or skip." : "No sensors of this kind. Search for one, or skip." }));
  };
  q.addEventListener("input", draw);
  const body = h("div", { class: "sheet-body split" },
    h("div", {}, preview, h("p", { class: "fnote", text: p.desc })),
    h("div", {}, h("h3", { class: "slab", text: "Which sensor should it show?" }), h("div", { class: "search" }, icon("search", "sm"), q), list));
  node.querySelector(".sheet-body").replaceWith(body);
  node.append(h("div", { class: "sheet-foot" }, h("button", { class: "btn tinted", onclick: () => { close(); addFromPreset(app, p, ""); } }, "Skip for now"), add));
  draw(); drawPreview(); q.focus();
}

function addFromPreset(app, p, ent) {
  const els = p.makeElements(ent);
  const page = { tier: p.tier || "rotate", elements: els };
  if (p.show_if) page.show_if = p.show_if;
  if (p.showIf) page.show_if = p.showIf(ent);
  if (page.tier === "when") syncDynamicGridShowIf(page);
  // A page per list: named after it ("Chores", "Work"), not "To do 2".
  const named = p.namedByEntity && ent ? slug(app.entMap.get(ent)?.name || ent.split(".")[1]) : "";
  app.addPage(named || p.id, page);
}

export function savePresetSheet(app) {
  const doc = app.doc;
  sheet("Save as a preset", (node, close) => {
    let title = pageTitle(doc.cur), desc = "";
    const t = h("input", { class: "inp", value: title, "aria-label": "Name" });
    const d = h("input", { class: "inp", value: "", placeholder: `Based on ${pageTitle(doc.cur)}`, "aria-label": "Description" });
    const save = () => {
      title = t.value.trim();
      if (!title) { t.focus(); return; }
      doc.spec.custom_presets.unshift({ id: slug(title) || "preset", title, desc: d.value.trim(), tier: doc.page().tier || "rotate", show_if: doc.page().show_if || "", elements: clone(doc.els()) });
      doc.commit(); close();
      toast(`Saved ${title} as a preset. It's first in New page.`);
    };
    [t, d].forEach((x) => x.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); }));
    node.append(h("div", { class: "sheet-body" }, field("Name", t), field("Description", d), h("p", { class: "fnote", text: "Presets are kept with your pages and sent with them." })),
      h("div", { class: "sheet-foot" }, h("button", { class: "btn tinted", onclick: () => close() }, "Cancel"), h("button", { class: "btn primary", onclick: save }, "Save preset")));
  }, { focus: "input" });
}

/* ---------- now on the panel ---------- */
export function openStatus(app, anchor) {
  popover(anchor, async (pop, close) => {
    pop.classList.add("status");
    const s = app.status || {}, doc = app.doc;
    // A screen that sleeps between updates (a TRMNL; a CrowPanel updating every 2 minutes or more): its own rhythm.
    const wakes = app.screen?.owns_interval === "addon", info = app.screen?.info || {}, t = app.screen?.timing;
    const pairs = app.screen?.setup === "pair", wake = "update";
    const { tone, line1 } = statusSummary(app);
    const lines = [];
    if (doc.saving === "error") lines.push(`Your changes couldn't be saved: ${doc.saveError} They're kept in this window, and it keeps trying.`);
    else if (doc.dirty) lines.push("Your changes are saved, but the panel doesn't have them until you send.");
    else if (wakes) lines.push(info.last_seen ? `It last updated at ${hm(info.last_seen)} and updates every ${span(t?.update_minutes || s.panel_interval || 15)}, showing ${turning(t)}.`
      : !pairs ? "It hasn't updated since it started sleeping between updates." : info.paired ? "Paired. It hasn't woken since." : "Not paired yet. Pair it in Settings.");
    else if (s.rendered_at) lines.push(`Pages rendered at ${hm(s.rendered_at)}. The panel is always on and looks for new ones every minute.`);
    if (s.panel_link?.pending_refresh) lines.push(`The panel hasn't picked up the last change yet${s.panel_link.last_error ? `: ${s.panel_link.last_error}` : ""}. It keeps trying.`);
    if (s.panel_link?.problem && !s.panel_link?.node) lines.push(`No panel found: ${s.panel_link.problem}.`);
    if (s.error) lines.push(`The last render failed: ${s.error}`);
    const notes = lines.map((l) => h("p", { class: "fnote", text: l }));
    // What isn't sent comes right under the line that says so.
    pop.append(h("div", { class: "sthead" }, h("span", { class: "led " + tone }), h("span", { text: line1 })), ...notes.slice(0, 1),
      ...(doc.dirty && doc.saving !== "error" ? [unsentList(app, close)] : []), ...notes.slice(1));
    // Outside services whose problem sensor is on (the user's call, 22 Oct); nothing when all answer.
    pop.append(...problemLines(app, close, (id) => openSettings(app, "services", id)));

    const live = s.pages || [];
    pop.append(h("div", { class: "poplab", text: "Rotating" }), h("p", { class: "fnote", text: live.length ? `${live.map(pageTitle).join(", ")}, ${turning(t)}.` : "Nothing at the moment." }));
    const hidden = [...new Set(doc.live.rotation)].filter((n) => doc.live.pages[n]?.tier === "when" && !live.includes(n));
    if (hidden.length) {
      pop.append(h("div", { class: "poplab", text: "Hidden right now" }));
      hidden.forEach((n) => {
        const p = doc.live.pages[n], d = describe(p.show_if, app.entMap);
        // With a widget's part (0.21.1): the whole of it, and which part doesn't hold now.
        const why = partOn(p) && s.parts?.[n] === false ? "Nothing on it to show right now." : p.show_if ? d.why : "";
        pop.append(h("p", { class: "fnote" }, h("b", { text: pageTitle(n) + ". " }), `${partOn(p) ? showsWords(p, app.entMap) : d.text}. ${why}`.trim()));
      });
    }
    if (s.active_alert) pop.append(h("div", { class: "poplab", text: "Alert" }), h("p", { class: "fnote", text: wakes ? `${pageTitle(s.active_alert)} shows at its next ${wake}. It can't be woken sooner.` : `${pageTitle(s.active_alert)} has taken over the panel.` }));
    const qh = doc.live.quiet_hours || {};
    pop.append(h("div", { class: "poplab", text: "Quiet hours" }), h("p", { class: "fnote", text: !qh.enabled ? "Off." : s.quiet_active ? `On now${s.quiet_reason ? ` (${s.quiet_reason})` : ""}, until ${qh.end}.` : `${qh.start} to ${qh.end}${qh.sleep_screen !== false ? ", with the sleep screen" : ""}.` }));

    const actions = h("div", { class: "btnrow wrap" });
    const dev = app.device || {};
    if (dev.sleep !== null && dev.sleep !== undefined) actions.append(h("button", { class: "btn tinted", onclick: async () => { close(); await app.deviceSet({ sleep: !dev.sleep }, dev.sleep ? "The panel is waking up." : "The panel is going to sleep."); } }, icon("moon", "sm"), dev.sleep ? "Wake" : "Sleep now"));
    if (dev.can_clear) actions.append(h("button", { class: "btn tinted", onclick: async () => { close(); await app.deviceSet({ clear_ghosting: true }, "The panel is clearing its ghosting."); } }, icon("sparkle", "sm"), "Clear ghosting"));
    actions.append(h("button", { class: "btn tinted", onclick: () => { close(); openFullStrip(app); } }, icon("eye", "sm"), app.screen?.picks_page === "addon" ? "See what it shows" : "See every page"));
    pop.append(actions);
    if (doc.dirty) pop.append(h("button", { class: "btn tinted danger wide", onclick: () => { close(); doc.revert(); toast("Went back to what's on the panel.", { label: "Undo", run: () => doc.undo() }); } }, icon("revert", "sm"), "Throw away all unsent changes"));
    // Fresh device state for next time; the buttons above use what's known now.
    app.loadDevice();
  }, { label: "Now on the panel", align: "left" });
}

/* What the panel doesn't have yet (doc.changes), a line each: a page and what's waiting for it, in
   the strip's order, then the settings sent with the pages. A line opens its page with its changes
   outlined; Undo puts that one thing back to what the panel has, with an Undo toast, and the list
   stays open for the next, with focus where it was. */
function unsentList(app, close) {
  const doc = app.doc, box = h("div", { class: "ulist", role: "group", "aria-label": "Not sent yet" });
  const draw = (focusAt = -1) => {
    const pend = doc.pending();
    if (!pend.any) { close(); return; }
    const lines = [];
    const names = [...new Set([...doc.spec.rotation, ...Object.keys(doc.spec.pages), ...Object.keys(pend.pages)])];
    for (const n of names) {
      const words = unsentWords(pend, n);
      if (!words) continue;
      const removed = pend.pages[n]?.status === "removed";
      lines.push({ name: pageTitle(n), words, open: removed ? null : () => { close(); app.showChanges(n); }, undoLabel: removed ? "Put back" : "Undo", undo: () => app.revertPage(n) });
    }
    for (const s of pend.settings) {
      // A new model or mounting placed every page for it: that goes back with Throw away, or in Settings.
      const placing = s === "display" || s === "orientation";
      const where = s === "quiet_hours" ? "quiet" : placing ? "panel" : null;
      lines.push({ name: SETTING_NAMES[s] || s, words: placing ? "Changed. Change it back in Settings" : "Changed",
        open: where ? () => { close(); openSettings(app, where); } : null, undoLabel: "Undo", undo: placing ? null : () => app.revertSetting(s) });
    }
    const rows = lines.map(({ name, words, open, undoLabel, undo }, i) => {
      const what = [h("span", { class: "udot", "aria-hidden": "true" }), h("span", { class: "un", text: name }), h("span", { class: "uw", text: words })];
      return h("div", { class: "urow" },
        open ? h("button", { class: "uopen", "aria-label": `${name}: ${words}. Open it`, onclick: open }, ...what) : h("span", { class: "uopen" }, ...what),
        undo ? h("button", { class: "btn tinted small", "aria-label": undoLabel === "Put back" ? `Put ${name} back` : `Undo ${name}: back to what the panel has`, onclick: () => { undo(); draw(i); } }, undoLabel) : null);
    });
    box.replaceChildren(...rows);
    if (focusAt >= 0) box.querySelectorAll(".urow")[Math.min(focusAt, rows.length - 1)]?.querySelector("button:last-child")?.focus({ preventScroll: true });
  };
  draw();
  return box;
}

export function openFullStrip(app) {
  const wakes = app.screen?.picks_page === "addon";            // it holds one picture, not every page
  sheet(wakes ? "What it shows" : "Every page, as the panel has them", (node) => {
    const img = h("img", { class: "fullstrip", alt: wakes ? "The picture the device got at its last wake." : "All the pages the panel is rotating through, stacked." });
    const meta = h("p", { class: "fnote" });
    img.addEventListener("error", () => { meta.textContent = wakes ? "Nothing yet. It gets its first picture at its next wake." : "No pages rendered yet."; });
    const load = () => { img.src = withDevice("api/strip.png?t=" + Date.now()); const p = app.status?.pages || []; meta.textContent = wakes ? "The picture it got at its last wake." : p.length ? `In order: ${p.map(pageTitle).join(", ")}.` : ""; };
    node.append(h("div", { class: "sheet-body" }, h("div", { class: "stripbox" }, img), meta,
      app.doc.dirty ? h("p", { class: "fnote", text: "This is what's been sent. Your unsent changes aren't in it yet." }) : null),
      h("div", { class: "sheet-foot" }, h("button", { class: "btn tinted", onclick: load }, "Reload")));
    load();
  }, { cls: "wide" });
}

/* ---------- adding a screen ---------- */
// Like setting up a phone: new, a copy of another screen's pages, or the same
// pages as another screen. Then on to installing it.
export function openAddScreen(app) {
  const kinds = app.kinds.filter((k) => k.displays.length);
  if (!kinds.length) { toast("This add-on doesn't know any kind of device it can add."); return; }
  const st = { kind: kinds[0], display: kinds[0].displays[0].id, orientation: 0, pages: "new", from: app.screen?.id || app.screens[0]?.id, quiet: true, power: "on",
    minutes: kinds[0].asleep_default || 15 };
  // "Device", not "screen": next to "New page", "screen" read like another page (the user's call).
  sheet("Add new device", (node, close) => {
    const body = h("div", { class: "sheet-body" });
    const name = h("input", { class: "inp", placeholder: "Kitchen", "aria-label": "Name", maxlength: "60", autocomplete: "off" });
    const err = h("p", { class: "fnote bad", role: "status", "aria-live": "polite" });
    const add = h("button", { class: "btn primary", onclick: () => submit() }, "Add device");
    const pairs = () => st.kind.setup === "pair";
    const source = () => app.screens.find((d) => d.id === st.from) || app.screens[0];
    const pick = (opts, value, onChange, label) => select(opts, value, onChange, { "aria-label": label });

    // A card to pick. `extra` goes under its text (Copy from: which screen); `aside` sits at its right edge (Sleeps: how often).
    function choice(mode, title, sub, extra, key = "pages", aside = null) {
      const on = st[key] === mode;
      const b = h("button", { class: "cmp choice" + (aside ? " aside" : ""), role: "radio", "aria-checked": String(on), onclick: (e) => { if (e.target.closest("select")) return; st[key] = mode; draw(); } },
        h("span", { class: "ct", text: title }), h("span", { class: "cs", text: sub }), extra || null, aside);
      return b;
    }
    // How often a screen that sleeps updates: the same times Settings › Device offers (timing.py), less always on.
    const sleepChoices = () => st.kind.update_choices.filter((m) => m !== 1);
    const every = (label) => pick(sleepChoices().map((m) => [m, span(m)]), st.minutes, (v) => {
      st.minutes = Number(v); st.power = "sleep"; draw();
      body.querySelector("select[data-every]")?.focus();
    }, label);
    function draw() {
      const screensOpts = app.screens.map((d) => [d.id, d.name]);
      const fromSel = () => pick(screensOpts, st.from, (v) => { st.from = v; draw(); }, "Which device");
      if (!sleepChoices().includes(st.minutes)) st.minutes = sleepChoices().includes(st.kind.asleep_default) ? st.kind.asleep_default : sleepChoices()[0];
      const everySel = every(pairs() ? "Updates every" : "Sleeps between updates: how often it updates");
      everySel.dataset.every = "";
      const src = source();
      const qh = st.pages === "new" ? (app.screen || src)?.quiet : src?.quiet;
      const disp = st.kind.displays.find((d) => d.id === st.display) || st.kind.displays[0];
      add.textContent = pairs() ? "Add and pair" : "Add device";
      body.replaceChildren(
        group(grow("Name", null, name),
          kinds.length > 1 ? grow("Kind", null, pick(kinds.map((k) => [k.id, k.name]), st.kind.id, (v) => { st.kind = kinds.find((k) => k.id === v); st.display = st.kind.displays[0].id; draw(); }, "Kind")) : null,
          pairs() && st.kind.displays.length < 2
            ? grow("Size", "Another size is picked up when it pairs", h("span", { class: "fnote", text: `${disp.name}, ${disp.w} × ${disp.h}` }))
            : grow("Model", null, pick(st.kind.displays.map((d) => [d.id, `${d.name}, ${d.w} × ${d.h}`]), st.display, (v) => { st.display = v; }, "Model")),
          grow("Mounted", null, pick(ORIENTATIONS, st.orientation, (v) => { st.orientation = Number(v); }, "Mounted"))),
        // Power comes first after the hardware: like the model and how it's mounted, it's about the screen
        // itself (on a cable or a battery), and it's the choice every new screen makes. A TRMNL always sleeps.
        h("h4", { class: "gtitle", text: "Power" }),
        pairs() ? group(grow("Updates every", "It sleeps in between, so it lasts months on its battery. Change it any time.", everySel))
          : h("div", { class: "choices", role: "radiogroup", "aria-label": "Power" },
            choice("on", "Always on", "On a cable. Updates every minute; buttons and alerts answer at once.", null, "power"),
            choice("sleep", "Sleeps between updates", "On a battery. The less often it updates, the longer it lasts. Change it any time.", null, "power", everySel)),
        h("h4", { class: "gtitle", text: "Pages" }),
        h("div", { class: "choices", role: "radiogroup", "aria-label": "Pages" },
          choice("new", "Set up as new", "One starter page to show it's working. Add your own from there."),
          choice("copy", "Copy from another device", "Its pages, fitted to this one, then yours to change.", st.pages === "copy" ? fromSel() : null),
          choice("same", "Same pages as another device", "Edits show on both. Each device keeps its own layout.", st.pages === "same" ? fromSel() : null)),
        qh?.enabled ? group(grow(`Same quiet hours as ${st.pages === "new" ? (app.screen || src).name : src.name}`, `${qh.start} to ${qh.end}. Change them any time.`,
          toggle(st.quiet, (v) => { st.quiet = v; }, "Same quiet hours"))) : "",
        err);
    }
    async function submit() {
      err.textContent = "";
      if (!name.value.trim()) { err.textContent = "Give the device a name."; name.focus(); return; }
      const src = source();
      const qsrc = st.pages === "new" ? (app.screen || src) : src;
      add.disabled = true;
      try {
        const r = (await api("api/devices", { method: "POST", body: { kind: st.kind.id, name: name.value.trim(), display: st.display, orientation: st.orientation,
          pages: st.pages, from: st.from, quiet_hours_from: st.quiet && qsrc?.quiet?.enabled ? qsrc.id : null, update_minutes: !pairs() && st.power === "on" ? 1 : st.minutes } })).body;
        close();
        await app.doc.flush();
        app.screens = r.devices; app.kinds = r.kinds;
        await app.switchScreen(r.device.id);
        app.applyScreens(r, r.device.id);
        if (r.device.setup === "pair") { openPairing(app, r.device.id); return; }
        toast(`Added ${r.device.name}. Install it from here when it's in your hands.`);
        openSettings(app, "install");
      } catch (e) { err.textContent = e.message; add.disabled = false; }
    }
    name.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
    draw();
    node.append(body, h("div", { class: "sheet-foot" }, h("button", { class: "btn tinted", onclick: () => close() }, "Cancel"), add));
  }, { focus: "input" });
}

/* ---------- pairing a screen that asks to join (TRMNL) ---------- */
// Listens for ten minutes. The screen is told this add-on's address, asks to
// join, and gets its own key. Polls while open; nothing to type here.
const hm = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "");
const mmss = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

export function openPairing(app, id, listen = true) {
  let info = null, since = null, left = 0, poll = null, tick = null, problem = "";
  const url = `api/devices/${encodeURIComponent(id)}/pair`;
  const stop = () => { clearInterval(poll); clearInterval(tick); poll = tick = null; };
  sheet("Pair your TRMNL", (node, close) => {
    const body = h("div", { class: "sheet-body" });
    const foot = h("div", { class: "sheet-foot" });
    const state = h("p", { class: "fnote pairstate", role: "status", "aria-live": "polite" });
    node.append(body, foot);
    const scr = () => app.screens.find((d) => d.id === id) || { name: "Your TRMNL" };
    async function call(method) {
      try {
        info = (await api(url, method ? { method } : undefined)).body; problem = "";
        if (since === null) since = info.paired_at || "";
        left = info.pairing_left;
      } catch (e) { problem = e.message; }
      draw();
    }
    const done = () => info && info.paired && (info.paired_at || "") !== since;
    function addrRow(a) {
      // Text, not a field: it wraps at phone width instead of hiding its end.
      const field = h("code", { class: "sel addrtext", text: a.url, "aria-label": "API server address" });
      // Its own full-width row: the address is the one thing to get exactly right.
      return h("div", { class: "addr" }, h("span", { class: "gl" }, a.where === "home" ? "At home" : "Away from home",
        h("small", { text: a.where === "home" ? "On the same network as Home Assistant" : "From anywhere, through Reaching home" })),
        h("div", { class: "inline" }, field, h("button", { class: "btn tinted", onclick: () => copyText(a.url, "the address") }, "Copy")));
    }
    function draw() {
      foot.replaceChildren();
      if (problem && !info) { body.replaceChildren(h("p", { class: "fnote bad", text: `Couldn't start listening: ${problem}` })); foot.append(h("button", { class: "btn primary", onclick: () => call("POST") }, "Try again")); return; }
      if (!info) { body.replaceChildren(h("p", { class: "fnote", text: "Getting ready…" })); return; }
      if (done()) {
        stop();
        app.loadScreens(id).catch(() => {});
        body.replaceChildren(h("div", { class: "pairdone" }, icon("check"), h("h3", { text: `${scr().name} is paired` }),
          h("p", { class: "fnote", text: `It shows your pages from now on, updating every ${span(info.update_minutes || 15)}. On its own screen it calls itself ${info.friendly_id}.` })));
        foot.append(h("button", { class: "btn primary", onclick: () => close() }, "Done"));
        return;
      }
      const away = info.addresses.find((a) => a.where === "away");
      body.replaceChildren(
        h("ol", { class: "steps" },
          h("li", { text: "Open your TRMNL's Wi-Fi setup. A new one starts there: join the network it shows, and a page opens." }),
          h("li", { text: away ? "Under Advanced, enter this as its API server. If it will travel, use the away address." : "Under Advanced, enter this as its API server." }),
          h("li", { text: "Choose your Wi-Fi and connect. It asks to join within a minute." })),
        group(...info.addresses.map(addrRow)),
        away ? null : h("p", { class: "fnote", text: "To use it away from home too, turn on Reaching home in Settings first." }),
        state);
      drawState();
      if (left <= 0) foot.append(h("button", { class: "btn primary", onclick: () => { since = null; info = null; call("POST"); start(); } }, "Listen again"));
      else foot.append(h("button", { class: "btn tinted", onclick: () => close() }, "Pair later"));
    }
    function drawState() {
      if (!info || done()) return;
      state.classList.toggle("bad", left <= 0);
      state.replaceChildren(h("span", { class: "led " + (left > 0 ? "wait listening" : "bad") }),
        left > 0 ? ` Listening for it · ${mmss(left)} left` : " The ten minutes are up and no TRMNL asked to join. Check the address, then listen again.");
    }
    function start() {
      stop();
      poll = setInterval(() => call(), 3000);
      tick = setInterval(() => { if (left > 0) { left -= 1; drawState(); if (left === 0) draw(); } }, 1000);
    }
    call(listen ? "POST" : undefined);
    start();
  }, { cls: "wide", onClose: stop });
}

/* ---------- which version to keep ---------- */
export function resolveClashes(app, clashes) {
  return new Promise((resolve) => {
    const choice = {};
    clashes.forEach((c) => { choice[c.name] = "mine"; });
    const title = clashes.length === 1 && clashes[0].kind === "page" ? `${pageTitle(clashes[0].name)} was changed in two places` : "Changed in two places";
    sheet(title, (node, close) => {
      const body = h("div", { class: "sheet-body" }, h("p", { class: "fnote", text: "Another window changed this too. Everything else merged on its own. Choose which to keep; the other stays one undo away." }));
      clashes.forEach((c) => {
        const pick = (who, card, other) => { choice[c.name] = who; card.setAttribute("aria-checked", "true"); other.setAttribute("aria-checked", "false"); };
        if (c.kind === "page") {
          const mine = h("button", { class: "cmp", role: "radio", "aria-checked": "true" }, thumbImg(app, "clash:mine:" + c.name, c.mine || { elements: [] }), h("span", { class: "ct", text: c.mine ? "Yours" : "Yours: deleted" }), h("span", { class: "cs", text: "From this window" }));
          const theirs = h("button", { class: "cmp", role: "radio", "aria-checked": "false" }, thumbImg(app, "clash:theirs:" + c.name, c.theirs || { elements: [] }), h("span", { class: "ct", text: c.theirs ? "The other one" : "The other: deleted" }), h("span", { class: "cs", text: "From another window" }));
          mine.onclick = () => pick("mine", mine, theirs); theirs.onclick = () => pick("theirs", theirs, mine);
          if (clashes.length > 1) body.append(h("h3", { class: "slab", text: pageTitle(c.name) }));
          body.append(h("div", { class: "cmpgrid", role: "radiogroup", "aria-label": pageTitle(c.name) }, mine, theirs));
        } else {
          const label = c.kind === "rotation" ? "The rotation" : SETTING_NAMES[c.name] || c.name;
          body.append(h("h3", { class: "slab", text: label }), seg([["mine", "Keep yours"], ["theirs", "Use the other one"]], "mine", (v) => { choice[c.name] = v; }, label));
        }
      });
      node.append(body, h("div", { class: "sheet-foot" }, h("button", { class: "btn primary", onclick: () => { close("done"); } }, "Keep these")));
    }, { modal: true, onClose: () => resolve(choice), cls: "wide" });
  });
}

/* ---------- keyboard shortcuts ---------- */
export function openShortcuts() {
  const rows = [["Undo, redo", `${modKey}Z, ⇧${modKey}Z`], ["Copy, cut, paste", `${modKey}C, ${modKey}X, ${modKey}V`], ["Paste and match", `⌥⇧${modKey}V`],
    ["Duplicate", `${modKey}D`], ["Select everything on the page", `${modKey}A`], ["Delete", "⌫"], ["Nudge 1 px, 10 px", "Arrows, ⇧ arrows"],
    ["Bring forward, send backward", `${modKey}], ${modKey}[`], ["To the front, to the back", `⌥${modKey}], ⌥${modKey}[`], ["Next or previous element", "Tab, ⇧Tab on the canvas"],
    ["Next or previous page", `${modKey}↓, ${modKey}↑`], ["Insert", `${modKey}I`], ["Send to panel", `${modKey}S`], ["Move a page in the strip", "⌥← ⌥→"],
    ["Zoom in, out, actual size", `${modKey}+, ${modKey}−, ${modKey}0`], ["Snap off while dragging", "Hold ⌥"], ["Click again without moving", "Selects what's underneath"], ["This list", "?"]];
  sheet("Keyboard shortcuts", (node) => {
    node.append(h("div", { class: "sheet-body" }, h("dl", { class: "keys" }, ...rows.flatMap(([a, b]) => [h("dt", { text: a }), h("dd", {}, h("kbd", { text: b }))]))));
  });
}

/* ---------- settings ---------- */
const SRC_FIELDS = {
  jellyfin: [["name", "Name"], ["base", "Server"], ["key", "API key", "password"], ["user", "User"], ["days", "New within, days", "number"]],
  rest: [["name", "Name"], ["url", "Address"], ["headers", "Headers", "password"], ["pick", "Value at"], ["unit", "Unit"], ["icon", "Icon"]],
  statistics: [["name", "Name"], ["entity", "Statistic"], ["period", "Period"], ["unit", "Unit"], ["icon", "Icon"]],
};
const SRC_KINDS = { jellyfin: "Jellyfin: new and unwatched", rest: "Any JSON address", statistics: "A long-term statistic" };
const SENSOR_ONLY = ["unit", "icon"];          // what only a sensor has: not one that fills a page
// The kinds of page a JSON address can fill in the add-on's own form (shapes.py, from the catalog).
const pageShapes = () => Object.values(widgetDescriptors()).map((w) => w.shape).filter(Boolean);

/* What a source gives: a sensor (its value), or a kind of page's data in the add-on's own form, which
   a widget of that kind can read in place of the add-on's services (its inspector's "Its data"). */
function sourceGives(s, redraw) {
  const becomes = h("p", { class: "fnote" }, "Becomes ", h("code", { text: `sensor.epaper_${s.name || "name"}` }), s.type === "jellyfin" ? " and its _count" : "");
  if (s.type !== "rest") return [becomes];
  const shapes = pageShapes();
  const shape = shapes.find((x) => x.kind === s.fills);
  const gives = field("Gives", select([["", "A sensor with its value"], ...shapes.map((x) => [x.kind, `${x.name} pages, in the add-on's form`])], s.fills || "",
    (v) => { if (v) s.fills = v; else delete s.fills; redraw(); }, { "aria-label": "What it gives" }));
  if (!shape) return [gives, becomes];
  return [gives, h("p", { class: "fnote", text: `A ${shape.name} page reads it when its "Its data" says so, in place of the add-on's services. Test checks that it answers in the add-on's form.` }), formNote(shape)];
}

export function openSettings(app, sectionName = "panel", focus = null) {
  sheet("Settings", (node) => {
    const nav = h("nav", { class: "setnav", "aria-label": "Settings" });
    const pane = h("div", { class: "setpane" });
    const pairs = app.screen?.setup === "pair";
    const sections = {
      panel: ["Device", "panel", () => (pairs ? pairedPane(app, pane, show) : panelPane(app, pane, show))],
      ...(pairs ? {} : { install: ["Install or update", "key", () => installPane(app, pane)] }),
      quiet: ["Quiet hours", "moon", () => quietPane(app, pane)],
      reach: ["Reaching home", "globe", () => reachPane(app, pane)],
      sources: ["Data sources", "plug", () => sourcesPane(app, pane)],
      services: ["Services", "cloud", () => { servicesPane(app, pane, focus); focus = null; }],
      icons: ["Icons", "grid", () => iconsPane(app, pane)],
      time: ["Time and language", "clock", () => timePane(app, pane)],
      editor: ["Editor", "gear", () => editorPane(app, pane)],
    };
    function show(k) {
      nav.querySelectorAll("button").forEach((b) => b.setAttribute("aria-current", b.dataset.k === k ? "page" : "false"));
      const perScreen = ["panel", "install", "quiet"].includes(k) && app.screen;
      pane.replaceChildren(h("h3", { class: "panetitle", text: perScreen ? `${sections[k][0]} · ${app.screen.name}` : sections[k][0] }));
      sections[k][2]();
      prefs.set("settings_section", k);
    }
    Object.entries(sections).forEach(([k, [l, ic]]) => nav.append(h("button", { class: "navrow", data: { k }, onclick: () => show(k) }, icon(ic, "sm"), h("span", { text: l }))));
    node.append(h("div", { class: "settings" }, nav, pane));
    const want = sectionName || prefs.get("settings_section", "panel");
    show(sections[want] ? want : "panel");
  }, { cls: "wide tall" });
}

function copyText(text, what) {
  const done = () => toast(`Copied ${what}.`);
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, () => fallback());
  else fallback();
  function fallback() {
    const t = h("textarea", { style: { position: "fixed", left: "-9999px" } }); t.value = text; document.body.append(t); t.select();
    let ok = false; try { ok = document.execCommand("copy"); } catch (_) {}
    t.remove();
    if (ok) done(); else toast("Your browser didn't allow copying. Select the text and copy it yourself.");
  }
}

function group(...rows) { return h("div", { class: "group" }, ...rows); }
function grow(label, sub, ctl) { return h("div", { class: "gr" }, h("span", { class: "gl" }, label, sub ? h("small", { text: sub }) : null), ctl); }

/* A new size or mounting: the pages come back placed for it (that size's own
   layout, or an automatic fit), as one undoable change that's sent like any other. */
/* Which way up it's mounted: Settings › Device and the screen bar. Turning it a quarter
   offers to rearrange the page on screen. */
export async function setMounted(app, v) {
  const doc = app.doc, spec = doc.spec;
  const was = [90, 270].includes(Number(spec.orientation)), now = [90, 270].includes(Number(v));
  if (!(await placeFor(app, spec.display, v))) return;
  if (was !== now) toast(`The canvas is ${now ? "portrait" : "landscape"} now.`, { label: "Rearrange this page", run: () => {
    // Which of its texts show the time is the add-on's answer (the canvas's own render says: shows_time).
    const times = (app.canvas.metrics || []).filter((m) => m.shows_time).map((m) => m.i);
    reflowPageElements(doc.page(), now, app.geometry().d, times); doc.commit();
  } });
}
export async function placeFor(app, display, orientation) {
  const doc = app.doc, spec = doc.spec;
  try {
    const r = (await api("api/arrange", { method: "POST", body: { spec, display, orientation: Number(orientation) } })).body;
    spec.pages = r.pages; spec.display = display; spec.orientation = Number(orientation);
    doc.commit();
    return true;
  } catch (e) { toast(`Couldn't change it: ${e.message}`); return false; }
}

const signal = (dbm) => (dbm >= -60 ? "strong" : dbm >= -70 ? "good" : dbm >= -80 ? "weak" : "very weak");
const awakeText = (s, per) => (s == null ? null : `awake ${s.toLocaleString([], { maximumFractionDigits: 1 })} s ${per}`);
function pairedPane(app, pane, show) {
  const doc = app.doc, spec = doc.spec, scr = app.screen || {}, info = scr.info || {};
  const name = input(scr.name || "", async (v) => {
    try { app.applyScreens((await api(`api/devices/${encodeURIComponent(scr.id)}`, { method: "PATCH", body: { name: v } })).body); }
    catch (e) { toast(e.message); name.value = scr.name; }
  }, { "aria-label": "Name", maxlength: "60" });
  const seen = !info.paired ? "Not paired yet" : !info.last_seen ? "Paired. Waiting for its first wake."
    : [`Last seen at ${hm(info.last_seen)}`, info.battery != null ? `battery ${info.battery}%` : null,
      info.rssi != null ? `Wi-Fi ${signal(info.rssi)}` : null, awakeText(info.awake_s, "a wake")].filter(Boolean).join(" · ");
  pane.append(group(grow("Name", null, name),
    grow("Connection", info.log?.length ? `It said: ${info.log[info.log.length - 1]}` : null, h("span", { class: "fnote", text: seen })),
    grow(info.paired ? "Pair again" : "Pair it", info.paired ? "After it was reset, or to give it a new key" : "Listens for ten minutes",
      h("button", { class: "btn tinted", onclick: () => openPairing(app, scr.id) }, info.paired ? "Pair again" : "Pair"))));
  const disp = DISPLAYS[spec.display] || {};
  pane.append(h("h4", { class: "gtitle", text: "Display" }), group(
    grow("Size", "As it reports it", h("span", { class: "fnote", text: disp.w ? `${disp.name}, ${disp.w} × ${disp.h}` : "" })),
    grow("Mounted", "Which way up it stands", select(ORIENTATIONS, spec.orientation || 0, (v) => setMounted(app, v)))));
  pane.append(h("h4", { class: "gtitle", text: "Power" }), timersBox(app, scr, () => show("panel")));
  sharedGroup(app, pane, scr, show);
  removeGroup(app, pane, scr);
}

function sharedGroup(app, pane, scr, show) {
  if (!scr.shares_with?.length) return;
  const doc = app.doc, others = scr.shares_with.map((x) => x.name).join(", ");
  pane.append(h("h4", { class: "gtitle", text: "Pages" }), group(grow(`Same pages as ${others}`, "Edits show on both. Each device keeps its own layout.",
    h("button", { class: "btn tinted", onclick: async () => {
      await doc.flush();
      try {
        const r = (await api(`api/devices/${encodeURIComponent(scr.id)}/unlink`, { method: "POST" })).body;
        app.applyScreens(r); await doc.load(); app.refresh();
        toast(`${scr.name} has its own pages now, as they were.`);
        show("panel");
      } catch (e) { toast(`Couldn't do that: ${e.message}`); }
    } }, "Stop sharing"))));
}

// Adding one sits with removing one: where people look for their screens in Settings.
function removeGroup(app, pane, scr) {
  const only = app.screens.length < 2;
  pane.append(group(grow("Add another device", "New, a copy of these pages, or the same ones",
    h("button", { class: "btn tinted", onclick: () => openAddScreen(app) }, "Add…")), grow("Remove this device", only ? "It's the only one. Add another first." : "Its key stops working. Undo puts it back.",
    h("button", { class: "btn tinted danger", disabled: only, onclick: () => removeScreen(app, scr) }, "Remove"))));
}

/* Removing a screen, from Settings or the screen menu: no question first, an undo after. */
export async function removeScreen(app, scr) {
  const doc = app.doc, gone = scr;
  try {
    await doc.flush();
    const r = (await api(`api/devices/${encodeURIComponent(gone.id)}`, { method: "DELETE" })).body;
    closeAll();
    app.screens = r.devices;
    await app.switchScreen(r.devices[0].id);
    app.applyScreens(r, r.devices[0].id);
    toast(`Removed ${gone.name}.`, { label: "Undo", run: async () => {
      try {
        const back = (await api(`api/devices/${encodeURIComponent(gone.id)}/restore`, { method: "POST" })).body;
        app.screens = back.devices; await app.switchScreen(gone.id); app.applyScreens(back, gone.id);
      } catch (e) { toast(`Couldn't put it back: ${e.message}`); }
    } });
  } catch (e) { toast(`Couldn't remove it: ${e.message}`); }
}

async function panelPane(app, pane, show) {
  const doc = app.doc, spec = doc.spec, scr = app.screen || {};
  const kind = app.kinds.find((k) => k.id === scr.kind) || { displays: Object.values(DISPLAYS) };
  const conn = h("span", { class: "fnote", text: "Checking…" });
  const name = input(scr.name || "", async (v) => {
    try {
      const r = (await api(`api/devices/${encodeURIComponent(scr.id)}`, { method: "PATCH", body: { name: v } })).body;
      app.applyScreens(r);
    } catch (e) { toast(e.message); name.value = scr.name; }
  }, { "aria-label": "Name", maxlength: "60" });
  // A new name shows here at once, and in Home Assistant once the panel is installed from a file that has it.
  pane.append(group(grow("Name", "Home Assistant takes it at the next install.", name), grow("Connection", null, conn),
    grow("Install or update", "Makes its ESPHome file and walks you through it", h("button", { class: "btn tinted", onclick: () => show("install") }, "Open"))));
  const sleeps = !!scr.sleeps;
  const reflowNote = h("p", { class: "fnote" });
  pane.append(h("h4", { class: "gtitle", text: "Display" }), group(
    grow("Model", null, select(kind.displays.map((d) => [d.id, `${d.name}, ${d.w} × ${d.h}`]), spec.display, (v) => placeFor(app, v, spec.orientation || 0))),
    grow("Mounted", "Which way up it hangs", select(ORIENTATIONS, spec.orientation || 0, (v) => setMounted(app, v)))), reflowNote);
  pane.append(h("h4", { class: "gtitle", text: "Power" }), timersBox(app, scr, () => show("panel")));

  sharedGroup(app, pane, scr, show);
  const ghost = h("div");
  pane.append(h("h4", { class: "gtitle", text: "Ghosting and sleep" }), ghost);
  const drawDevice = (dev) => {
    ghost.replaceChildren();
    if (sleeps) { ghost.append(h("p", { class: "fnote", text: "These live on the panel, and it sleeps between updates. To change them, ask it to stay awake above, or make it always on." })); return; }
    if (!dev || !dev.available) { ghost.append(h("p", { class: "fnote", text: dev?.problem ? `These live on the panel, and it isn't reachable: ${dev.problem}.` : "These live on the panel, and it isn't reachable right now." })); return; }
    const rows = [];
    if (dev.ghost_mode !== null) rows.push(grow("Clear ghosting", "A full refresh flashes once and cleans the screen", select((dev.ghost_modes.length ? dev.ghost_modes : ["On automatic changes", "Every Nth refresh"]).map((o) => [o, o === "Every Nth refresh" ? "Every few refreshes" : o]), dev.ghost_mode, (v) => app.deviceSet({ ghost_mode: v }, "Saved on the panel."))));
    if (dev.ghost_after !== null) rows.push(grow("After", "partial refreshes", number(dev.ghost_after, (v) => app.deviceSet({ ghost_after: v }, "Saved on the panel."), { min: "2", max: "60", style: { width: "5em" } })));
    if (dev.can_clear) rows.push(grow("Clear it now", null, h("button", { class: "btn tinted", onclick: () => app.deviceSet({ clear_ghosting: true }, "The panel is clearing its ghosting.") }, "Clear")));
    if (dev.sleep !== null) rows.push(grow("Asleep", "Shows the sleep screen until someone presses a button", toggle(dev.sleep, (v) => app.deviceSet({ sleep: v }, v ? "The panel is going to sleep." : "The panel is waking up."), "Asleep")));
    if (!rows.length) ghost.append(h("p", { class: "fnote", text: "This panel's firmware is older and doesn't have these settings. Reinstall it from Install or update." }));
    else ghost.append(group(...rows));
  };
  drawDevice(app.device);
  app.loadDevice().then(drawDevice);
  removeGroup(app, pane, scr);
  if (sleeps) {
    const info = scr.info || {};
    conn.textContent = info.last_seen ? [`Last updated at ${hm(info.last_seen)}`, awakeText(info.awake_s, "an update")].filter(Boolean).join(" · ") : "It hasn't updated since it started sleeping between updates.";
    return;
  }
  try {
    const r = (await api("api/panel-setup")).body;
    const p = r.panel || {};
    conn.textContent = p.connected ? `Connected${p.network ? ` to ${p.network}` : ""}${p.rssi ? `, Wi-Fi ${p.rssi} dBm` : ""}` : p.node ? "Found, but offline. It picks up changes when it's back." : "No panel yet";
  } catch (e) { conn.textContent = "Couldn't check"; }
}

/* Update every and Rotate every (timing.py): how a screen is powered, and how its pages turn. They apply at once. */
/* The one way the editor changes a screen's timers: Settings › Device and the screen bar both use it. */
export async function changeTimers(app, scr, body, said) {
  try {
    const r = (await api(`api/devices/${encodeURIComponent(scr.id)}`, { method: "PATCH", body })).body;
    app.applyScreens(r);
    app.refresh();                                     // the inspector, the strip and the bar say how pages turn
    app.canvas?.preview(true);                         // asleep, it draws the date where a time is: the canvas shows its own render
    // A clock needs nothing here: a device that sleeps draws the date in its place (render/clocktime.py).
    // The 0.15 draft's offerTheDate, which changed the design for every device, is kept off as the way back.
    toast(r.note || said);
  } catch (e) { toast(`Couldn't change it: ${e.message}`); }
}

/* Not used: the way back. It offered to turn clock pages into the date when a
   device started sleeping, but that changed the design for every device
   showing it (the user's call, 21 Oct: per device and automatic instead, in
   the renderer). Kept off until the renderer's way has proven itself. */
// eslint-disable-next-line no-unused-vars
function offerTheDate(app, scr) {
  const doc = app.doc, pages = clockPages(doc.spec.pages);
  if (!pages.length) return false;
  const which = pages.length === 1 ? pageTitle(pages[0]) : `${pages.length} pages`;
  toast(`${scr.name || "This device"} sleeps between updates now, so a clock would stop at the time of its last update. ${which} can show the date instead.`, {
    label: "Show the date", run: () => {
      pages.forEach((n) => { doc.spec.pages[n].elements = dateInstead(doc.spec.pages[n].elements || []); });
      doc.commit();
      toast(pages.length === 1 ? `${which} shows the date now.` : `Those pages show the date now.`, { label: "Undo", run: () => doc.undo() });
    } });
  return true;
}
export const updateLabel = (m) => (m === 1 ? "1 minute · always on" : span(m));
export const updateSaid = (m) => (m === 1 ? "It's always on." : `It updates every ${span(m)} from its next update.`);
export const rotateOptions = (t) => (t.always_on
  ? [...new Set([...t.rotate_seconds_choices, t.rotate_seconds])].sort((a, b) => a - b).map((x) => [x, seconds(x)])
  : t.rotate_update_choices.map((n) => [n, n === 1 ? "Every update" : span(n * t.update_minutes)]));
export const rotateChange = (t, v) => (t.always_on
  ? [{ rotate_seconds: Number(v) }, `Each page shows for ${seconds(Number(v))}.`]
  : [{ rotate_updates: Number(v) }, `It moves to the next page every ${span(Number(v) * t.update_minutes)}.`]);
export const ORIENTATIONS = [[0, "Landscape"], [180, "Landscape, upside down"], [90, "Portrait"], [270, "Portrait, flipped"]];

function timersBox(app, scr, redraw) {
  const info = scr.info || {}, t = scr.timing || {}, box = h("div");
  const url = `api/devices/${encodeURIComponent(scr.id)}`, pairs = scr.setup === "pair";
  const change = async (body, said) => { await changeTimers(app, scr, body, said); redraw(); };
  const update = select(t.update_choices.map((m) => [m, updateLabel(m)]), t.update_minutes,
    (v) => change({ update_minutes: Number(v) }, updateSaid(Number(v))), { "aria-label": "Update every" });
  const rotate = select(rotateOptions(t), t.always_on ? t.rotate_seconds : t.rotate_updates, (v) => change(...rotateChange(t, v)), { "aria-label": "Rotate every" });
  const rows = [
    grow("Update every", t.always_on ? "Always on: for a panel on a cable" : t.can_stay_on ? "It sleeps in between. Longer lasts longer on a battery" : "Longer lasts longer on its battery", update),
    grow("Rotate every", t.always_on ? "How long each page shows" : "Each update refreshes the page on screen; this moves to the next", rotate)];
  if (!t.always_on && !pairs) {
    const stay = info.stay_awake || {};
    const awakeSub = stay.until ? `Awake until ${hm(stay.until)}, for an update over Wi-Fi.`
      : stay.asked ? "It stays awake ten minutes from its next update. Press a button on it to start now."
      : "Ten minutes, for an update over Wi-Fi. Starts at its next update.";
    rows.push(grow("Stay awake", awakeSub, h("button", { class: "btn tinted", onclick: async () => {
      try {
        await api(`${url}/stay-awake`, { method: stay.asked || stay.until ? "DELETE" : "POST" });
        await app.loadScreens(scr.id);
        redraw();
      } catch (e) { toast(`Couldn't ask it: ${e.message}`); }
    } }, stay.asked || stay.until ? "Cancel" : "Stay awake")));
  }
  box.append(group(...rows), h("p", { class: "fnote", text: t.always_on
    ? "Buttons and alerts answer at once, and Home Assistant can wake it. On a battery, choose 2 minutes or more and it sleeps in between."
    : pairs ? "It sleeps between updates, so nothing can wake it early: new pages and alerts show at its next update. Its button shows the next page."
    : "It sleeps between updates, so new pages and alerts show at its next update. A button press updates it right away." }));
  if (!t.always_on && !pairs && !info.firmware_sleeps) box.append(h("p", { class: "note warn" }, icon("info", "sm"),
    h("span", { text: "This panel's firmware can't sleep yet, so it stays connected and checks on its own timer. Install it again from Install or update and it starts sleeping." })));
  return box;
}

/* Where the panel stands with Home Assistant, and what to do next. Home Assistant sets the panel's
   encryption itself when it adds it, so nothing here asks for a key. */
function connectionNote(p) {
  const devices = () => h("a", { class: "linkbtn inline", href: "/config/integrations/dashboard", target: "_top" }, "Open Devices & services");
  const note = (kind, text, extra) => h("div", { class: "note " + kind, role: "status" },
    h("span", { class: kind === "waiting" ? "led listening" : "led" }), h("span", { text }), extra || null);
  if (p.connected) return note("good", `Connected in Home Assistant${p.ip ? ` at ${p.ip}` : ""}.`);
  if (p.waiting === "add") return note("warn", "Home Assistant found the panel. Add it in Settings › Devices & services; it sets up the panel's encryption itself.", devices());
  if (p.waiting === "confirm") return note("warn", "Home Assistant asks you to confirm the panel's new firmware. In Settings › Devices & services, choose Reconfigure on it and confirm.", devices());
  if (p.node) return note("warn", "Found, but offline. It picks up changes when it reconnects.");
  if (p.installed) return h("div", {},
    note("waiting", "Waiting for Home Assistant to find the panel…"),
    h("p", { class: "fnote", text: `If nothing shows up in a few minutes, add it yourself: Settings › Devices & services › Add integration › ESPHome, ${p.home_ip ? `and enter ${p.home_ip}` : "and enter the panel's address"}. Home Assistant has 15 minutes after the panel starts; if it says it can't connect, unplug the panel for a moment and try again.` }));
  return note("warn", "No panel yet. Send to ESPHome and Install it there; Home Assistant then finds it.");
}

async function installPane(app, pane) {
  const box = h("div", {}, h("p", { class: "fnote", text: "Loading…" }));
  pane.append(box);
  let r;
  try { r = (await api("api/panel-setup")).body; } catch (e) { box.replaceChildren(h("p", { class: "fnote bad", text: `Couldn't load the panel's setup: ${e.message}` })); return; }
  const c = r.config || {};       // its address is Home Assistant's own, never this browser's (it may be a tunnel's)
  const yaml = h("textarea", { class: "inp code tall", readonly: true, "aria-label": "The panel's ESPHome file", spellcheck: "false" });
  const secrets = h("textarea", { class: "inp code", readonly: true, "aria-label": "secrets.yaml lines", spellcheck: "false" });
  const secretsWrap = h("div");
  const status = h("div");
  // What ESPHome would refuse (no way online, a Wi-Fi password it can't take), said before Install.
  const problems = h("div", { role: "status", "aria-live": "polite" });
  const copyFile = h("button", { class: "btn tinted", onclick: () => copy(yaml.value, "the file") }, "Copy");
  // Send to ESPHome: the file goes into Home Assistant's ESPHome folder and ESPHome opens, to Install there.
  const esphomeBox = h("div");
  let saving = Promise.resolve(), sending = false;
  const sendToEsphome = async () => {
    if (sending) return; sending = true; drawEsphome();
    const dash = r.esphome?.dashboard;
    // Opened now, while it's still the click: a tab opened after waiting is blocked as a pop-up.
    const tab = dash ? window.open("about:blank", "_blank") : null;
    try {
      await saving;                       // a field changed just before the click is saved first
      const x = (await api("api/panel-setup/esphome", { method: "POST" })).body;
      r.esphome = x.esphome;
      if (tab) { tab.location.href = new URL(dash, location.origin).href; toast(`Sent to ${x.esphome.file}. In ESPHome, choose Install on the panel.`); }
      else toast(`Sent to ${x.esphome.file}. Open ESPHome in Home Assistant and choose Install on the panel.`);
    } catch (e) { tab?.close(); toast(e.message); }
    sending = false; drawEsphome();
  };
  function drawEsphome() {
    const e = r.esphome || {}, blocked = (r.problems || []).length > 0;
    if (e.state === "no_folder") {
      esphomeBox.replaceChildren(group(grow("ESPHome", "Home Assistant has no ESPHome folder yet. Install the ESPHome add-on from the add-on store, then come back and Send to ESPHome.", null)));
      return;
    }
    const sub = blocked ? "Fix the above first."
      : e.state === "same" ? `Up to date in ${e.file}.`
      : e.state === "differs" ? `ESPHome has an older copy in ${e.file}. Send this one, then Install there.`
      : `Not in ESPHome yet. It goes to ${e.file}.`;
    esphomeBox.replaceChildren(group(grow("ESPHome", sub,
      h("button", { class: "btn primary", disabled: blocked || sending, onclick: sendToEsphome }, sending ? "Sending…" : "Send to ESPHome"))));
  }
  const downloadFile = h("button", { class: "btn tinted", onclick: () => {
    const a = h("a", { href: URL.createObjectURL(new Blob([yaml.value], { type: "text/yaml" })), download: (dev.value.trim() || "crowpanel-epaper") + ".yaml" });
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  } }, "Download");
  const save = async (extra = {}, msg) => {
    try {
      const body = { ha_host: host.value.trim(), frame_port: parseInt(port.value, 10) || 8099,
        device_name: dev.value.trim() || "crowpanel-epaper", wifi_ssid: ssid.value.trim(), wifi_password: pw.value, use_secrets: useSecrets,
        wifi_networks: nets.filter((n) => n.ssid.trim()), hotspot: hotspotOn, ...extra };
      const p = api("api/panel-setup", { method: "POST", body });
      saving = p.catch(() => {});
      r = (await p).body;
      apply();
      if (msg) toast(msg);
    } catch (e) { toast(`Couldn't save the setup: ${e.message}`); }
  };
  const host = input(c.ha_host, () => save(), { placeholder: "homeassistant.local" });
  const port = number(c.frame_port || r.frame_port || 8099, () => save(), { min: "1", max: "65535", style: { width: "7em" } });
  const dev = input(c.device_name || "crowpanel-epaper", () => save());
  const ssid = input(c.wifi_ssid, () => save(), { placeholder: "From your secrets" });
  // Other places the screen goes (work, a holiday home): it joins whichever it finds.
  const nets = (c.wifi_networks || []).map((n) => ({ ...n }));
  const netsBox = h("div");
  const drawNets = () => netsBox.replaceChildren(...nets.map((n, i) => group(
    grow("Also at", null, input(n.ssid, (v) => { n.ssid = v.trim(); save(); }, { placeholder: "Network name", "aria-label": `Network ${i + 2} name` })),
    grow("Password", null, h("div", { class: "inline" }, input(n.password, (v) => { n.password = v; save(); }, { type: "password", "aria-label": `Network ${i + 2} password` }),
      h("button", { class: "btn tinted danger", "aria-label": `Remove the network ${n.ssid || i + 2}`, onclick: () => { nets.splice(i, 1); drawNets(); save(); } }, "Remove"))))),
    h("div", { class: "btnrow" }, h("button", { class: "btn tinted", disabled: nets.length >= 8, onclick: () => { nets.push({ ssid: "", password: "" }); drawNets(); netsBox.querySelector(`[aria-label="Network ${nets.length + 1} name"]`)?.focus(); } }, icon("plus", "sm"), "Add a network")));
  const pw = input(c.wifi_password, () => save(), { type: "password", placeholder: "From your secrets" });
  let useSecrets = !!c.use_secrets;
  // Its own Wi-Fi, for choosing a network from a phone where it knows none.
  let hotspotOn = c.hotspot !== false;
  const hotspotBox = h("div");
  let hotspotPw = null;
  const drawHotspot = () => {
    const cc = r.config || c;
    hotspotBox.replaceChildren(group(
      grow("Its own Wi-Fi when it's lost", `Where it finds none of these networks, it opens “${cc.hotspot_name || "setup"}” so you can choose one from your phone. Its screen says so.`,
        toggle(hotspotOn, (v) => { hotspotOn = v; save(); }, "Its own Wi-Fi when it's lost")),
      hotspotOn ? grow("Password", "For joining it from your phone. A change takes effect when you install the panel again.", h("div", { class: "inline" },
        hotspotPw = input(cc.hotspot_password || "", (v) => {
          if (!v) { toast("Its own Wi-Fi needs a password: 8 to 63 characters."); hotspotPw.value = cc.hotspot_password || ""; return; }
          save({ hotspot_password: v });
        }, { class: "inp code", maxlength: "64", "aria-label": "The panel's own Wi-Fi password" }),
        h("button", { class: "btn tinted", onclick: () => copyText(hotspotPw.value, "the password") }, "Copy"))) : null),
      hotspotOn ? h("p", { class: "fnote", text: "A network you choose there replaces the ones above until you install the panel again, so add places it goes often above." }) : null);
  };
  const copy = copyText;
  function apply() {
    const cc = r.config || {};
    drawHotspot();
    yaml.value = r.yaml || ""; secrets.value = r.secrets_yaml || "";
    const issues = r.problems || [];
    problems.replaceChildren(...issues.map((t) => h("p", { class: "note warn" }, icon("info", "sm"), h("span", { text: t }))),
      issues.length ? h("p", { class: "fnote", text: "ESPHome wouldn't install this file. Fix the above and it's ready; Home Assistant's ESPHome folder keeps the last good one until then." }) : "");
    copyFile.disabled = downloadFile.disabled = issues.length > 0;
    drawEsphome();
    secretsWrap.hidden = !(cc.use_secrets || !cc.wifi_ssid);
    const p = r.panel || {};
    status.replaceChildren(...[
      connectionNote(p),
      r.frame_protection && r.frame_protection !== "on" ? h("p", { class: "note warn" }, icon("info", "sm"), h("span", { text: "Pages on your network aren't protected yet. Installing the file below switches it on; nothing goes blank in between." })) : null,
      app.status?.ha_entities?.problem ? h("p", { class: "note warn" }, icon("info", "sm"), h("span", { text: app.status.ha_entities.problem })) : null,
      app.doc.live.display !== app.doc.spec.display ? h("p", { class: "note warn" }, icon("info", "sm"), h("span", { text: "You changed the model but haven't sent it yet. This file is for the model the device has now; send first, then install." })) : null].filter(Boolean));
  }
  box.replaceChildren(status,
    group(grow("Home Assistant's address", "Where the panel fetches pages from", host), grow("Port", null, port), grow("Device name", null, dev)),
    group(grow("Wi-Fi network", null, ssid), grow("Wi-Fi password", null, pw), grow("Use secrets.yaml", "Keep the Wi-Fi details out of the file", toggle(useSecrets, (v) => { useSecrets = v; save(); }, "Use secrets.yaml"))),
    h("h4", { class: "gtitle", text: "Other networks" }), h("p", { class: "fnote", text: "Where else the device goes, like work. It joins whichever it finds." }), netsBox, hotspotBox,
    h("h4", { class: "gtitle", text: "The panel's file" }), problems, esphomeBox, yaml,
    h("p", { class: "fnote", text: "Passwords and the panel's update key are hidden here. Send to ESPHome writes the whole file." }),
    h("div", { class: "btnrow" }, copyFile, downloadFile),
    secretsWrap,
    h("h4", { class: "gtitle", text: "Installing" }),
    h("ol", { class: "steps" },
      r.esphome?.state === "no_folder" ? h("li", { text: "Install the ESPHome add-on from Home Assistant's add-on store." }) : null,
      h("li", { text: "Send to ESPHome. ESPHome opens in a new tab, with this panel among its devices." }),
      h("li", { text: "Choose Install on it. Use USB-C the first time; after that it updates over Wi-Fi." }),
      h("li", { text: "Home Assistant finds the panel and asks to add it, in Settings › Devices & services. Add it within 15 minutes of the panel starting; Home Assistant sets up its encryption itself." })));
  // Until Home Assistant has the panel, look again every few seconds while this is open.
  const watch = () => setTimeout(async () => {
    if (!box.isConnected) return;
    if (!(r.panel || {}).connected) {
      try {
        const x = (await api("api/panel-setup")).body;
        // Redrawn only when something changed, so nothing on the sheet moves while it waits.
        if (JSON.stringify(x.panel) !== JSON.stringify(r.panel)) { r.panel = x.panel; apply(); }
      } catch (_) {}
    }
    if (!(r.panel || {}).connected) watch();
  }, 5000);
  watch();
  drawNets();
  secretsWrap.append(h("h4", { class: "gtitle", text: "Lines for secrets.yaml" }), secrets, h("div", { class: "btnrow" }, h("button", { class: "btn tinted", onclick: () => copy(secrets.value, "the lines") }, "Copy")));
  apply();
}

function quietPane(app, pane) {
  const doc = app.doc;
  const qh = doc.spec.quiet_hours;
  const set = (k, v) => { qh[k] = v; doc.commit(); draw(); };
  const body = h("div");
  const wakes = app.screen?.owns_interval === "addon";
  pane.append(h("p", { class: "fnote", text: wakes
    ? `This device's own. While quiet hours last it shows the sleep screen and sleeps until they end. ${app.screen?.setup === "pair" ? "A press of its button shows a page" : "A press of a button shows your pages"} for two minutes. Sent with your pages.`
    : "This device's own. While quiet hours last, it doesn't flash or download, so a dark room stays dark. Its buttons still work. Sent with your pages." }), body);
  function draw() {
    body.replaceChildren(
      group(grow("Quiet hours", null, toggle(qh.enabled, (v) => set("enabled", v), "Quiet hours"))),
      group(grow("From", null, input(qh.start, (v) => set("start", v), { type: "time" })), grow("Until", "Overnight works, like 23:00 to 07:00", input(qh.end, (v) => set("end", v), { type: "time" }))),
      group(grow("Also while nobody's home", qh.presence_entity ? (app.entMap.get(qh.presence_entity)?.name || qh.presence_entity) : "A person, group or zone", (() => {
        const b = h("button", { class: "btn tinted", onclick: () => app.openEntityPicker(b, (id) => set("presence_entity", id), { domains: ["person", "zone", "group"], current: qh.presence_entity, allowNone: true }) }, qh.presence_entity ? "Change" : "Choose"); return b; })()),
        grow(wakes ? "Alerts show through them" : "Alerts can wake it", wakes ? "At its next wake" : null, toggle(qh.allow_alerts !== false, (v) => set("allow_alerts", v), wakes ? "Alerts show through them" : "Alerts can wake it")),
        grow("Sleep screen", "Closed eyes, and when it wakes. Off keeps a page on screen overnight.", toggle(qh.sleep_screen !== false, (v) => set("sleep_screen", v), "Sleep screen"))),
      h("p", { class: "fnote" }, "Home Assistant gets ", h("code", { text: "sensor.epaper_quiet_hours" + (app.screen?.entity_suffix || "") }), " for your own automations."));
    body.querySelectorAll(".group:not(:first-child)").forEach((g) => g.classList.toggle("off", !qh.enabled));
  }
  draw();
}

/* ---------- reaching home ---------- */
// How screens away from home reach the add-on: not at all, through Home
// Assistant's own address (the companion integration), or a tunnel of yours.
async function reachPane(app, pane) {
  const box = h("div", {}, h("p", { class: "fnote", text: "Checking…" }));
  pane.append(h("p", { class: "fnote", text: "Take a device to work or on holiday and it keeps showing your pages. Away from home, every device needs its own key, and wrong keys slow down." }), box);
  let r = null, busy = false, restarting = false;
  const call = async (path, method, body, done) => {
    if (busy) return; busy = true;
    try { r = (await api(path, { method, body })).body; if (done) toast(done); }
    catch (e) { toast(e.message); }
    busy = false; draw();
  };
  // While Home Assistant restarts, the editor can't reach the add-on either (it comes through
  // Home Assistant), so keep asking quietly until Home Assistant runs the new copy.
  const restart = async () => {
    if (busy) return; busy = true;
    try {
      const x = (await api("api/reach/restart", { method: "POST" })).body;
      if (!x.restarting) { toast(`Home Assistant didn't restart: ${x.problem}`); return; }
      restarting = true; draw();
      const until = Date.now() + 4 * 60000;
      const tick = async () => {
        if (!box.isConnected) return;
        try { r = (await api("api/reach")).body; } catch (_) {}
        const c = r.companion || {};
        const settled = !c.restart_needed && c.state !== "unknown";
        if (settled || Date.now() > until) {
          restarting = false; draw();
          if (c.state === "running") toast("Home Assistant is back, and the integration is running.");
          else if (!settled) toast("Home Assistant hasn't come back yet. Check again in a minute.");
          return;
        }
        setTimeout(tick, 5000);
      };
      setTimeout(tick, 5000);
    } catch (e) { toast(e.message); }
    finally { busy = false; }
  };
  // What's picked here (`chosen`) can be ahead of what screens use (`mode`): "own" with no address yet.
  const picked = () => r.chosen || r.mode;
  const mode = (m, title, sub) => h("button", { class: "cmp choice", role: "radio", "aria-checked": String(picked() === m),
    onclick: async () => {
      if (picked() === m) return;
      await call("api/reach", "PUT", { mode: m, address: r.address }, m === "home" ? "Devices reach the add-on at home only." : null);
      if (m === "own" && !r.address) box.querySelector("input[data-own]")?.focus();
    } },
    h("span", { class: "ct", text: title }), h("span", { class: "cs", text: sub }));
  const NOW = { home: "on your home network only", ha: "through Home Assistant's address" };
  function draw() {
    if (!r) return;
    const parts = [h("div", { class: "choices", role: "radiogroup", "aria-label": "Reaching home" },
      mode("home", "At home only", "Devices fetch from the add-on on your home network."),
      mode("ha", "Through Home Assistant's address", "Wherever you reach Home Assistant from outside: Home Assistant Cloud, Cloudflare, your own domain."),
      mode("own", "Through your own address", "A tunnel or proxy of yours, pointed at this add-on."))];
    if (picked() === "ha") {
      const c = r.companion || {};
      parts.push(r.ha_address
        ? (c.state === "running" && !c.restart_needed
          ? h("p", { class: "note good" }, icon("check", "sm"), h("span", { text: `Devices use ${r.ha_address}/api/epaper.` }))
          : h("p", { class: "note info" }, icon("info", "sm"), h("span", { text: `Devices will use ${r.ha_address}/api/epaper once the integration runs.` })))
        : h("p", { class: "note warn" }, icon("info", "sm"), h("span", { text: "Home Assistant has no address outside your home yet. Set one in Home Assistant under Settings, System, Network, or turn on Home Assistant Cloud." })));
      const restartRow = (title, sub) => restarting
        ? grow("Restarting Home Assistant", "This updates when it's back, in about a minute.", h("span", { class: "fnote", text: "Waiting…" }))
        : grow(title, sub, h("button", { class: "btn primary", onclick: restart }, "Restart"));
      parts.push(group(
        !c.installed ? grow("A small integration", "Home Assistant needs it to pass devices on to the add-on. Nothing to fill in.", h("button", { class: "btn primary", onclick: () => call("api/reach/companion", "POST", undefined, "Installed. Restart Home Assistant to load it.") }, "Install"))
        : c.restart_needed || restarting ? restartRow("Restart Home Assistant", "It loads the integration when it starts. Takes about a minute.")
        : c.state === "running" ? grow("The integration", `Running, version ${c.version}.`, h("span", { class: "fnote", text: "Ready" }))
        : c.state === "set_up" ? grow("The integration", `Home Assistant didn't set it up: ${c.problem || "no answer"}.`, h("button", { class: "btn tinted", onclick: () => call("api/reach", "GET") }, "Try again"))
        : c.state === "stopped" && c.disabled ? grow("The integration is turned off", "Turn on e-Paper Panel in Home Assistant under Settings, Devices & services.", h("button", { class: "btn tinted", onclick: () => call("api/reach", "GET") }, "Check again"))
        : c.state === "stopped" ? restartRow("The integration didn't start", "Restart Home Assistant to try again. If it still doesn't, Home Assistant's log says why.")
        : grow("The integration", "Home Assistant didn't answer. It may be restarting.", h("button", { class: "btn tinted", onclick: () => call("api/reach", "GET") }, "Check again"))));
    }
    if (picked() === "own") {
      const addr = input(r.address, (v) => call("api/reach", "PUT", { mode: "own", address: v }, "Saved. Devices away from home use it."), { placeholder: "https://panel.example.com", "aria-label": "Your address", inputmode: "url", autocomplete: "off", data: { own: "" } });
      if (r.mode !== "own") parts.push(h("p", { class: "note info" }, icon("info", "sm"), h("span", { text: `Until you save an https address here, devices keep reaching the add-on ${NOW[r.mode] || NOW.home}.` })));
      parts.push(group(grow("Your address", "Where your tunnel answers. It must be https.", addr),
        r.service_address ? grow("Point it at", "In the Cloudflared app, add a host with this as its service.", h("div", { class: "inline" }, h("input", { class: "inp code", readonly: true, value: r.service_address, "aria-label": "Point your tunnel at" }), h("button", { class: "btn tinted", onclick: () => copyText(r.service_address, "the address") }, "Copy"))) : null));
    }
    if (r.mode !== "home") {
      if (r.token_short) parts.push(h("p", { class: "note warn" }, icon("warn", "sm"), h("span", { text: "The frame token in the add-on's options is short, so someone on the internet could guess it. Make it at least 16 characters, or clear it and the add-on makes a long one." })));
      parts.push(h("p", { class: "fnote", text: "Install each CrowPanel again once (Install or update) so it uses this address. Until then it keeps working at home." }));
    }
    box.replaceChildren(...parts);
  }
  try { r = (await api("api/reach")).body; draw(); }
  catch (e) { box.replaceChildren(h("p", { class: "fnote bad", text: `Couldn't check: ${e.message}` })); }
}

async function sourcesPane(app, pane) {
  let srcs = [];
  try { srcs = (await api("api/sources")).body || []; } catch (e) { pane.append(h("p", { class: "fnote bad", text: `Couldn't load your sources: ${e.message}` })); return; }
  const list = h("div");
  const msg = h("span", { class: "fnote", role: "status", "aria-live": "polite" });
  const add = select([["", "Add a source…"], ...Object.entries(SRC_KINDS)], "", (v) => {
    if (!v) return;
    const base = { type: v, name: "" }; if (v === "jellyfin") base.days = 30; if (v === "statistics") base.period = "month";
    srcs.push(base); add.value = ""; draw();
  }, { "aria-label": "Add a source" });
  const save = async () => {
    try { const r = (await api("api/sources", { method: "PUT", body: srcs })).body; srcs = r.sources || srcs; draw(); msg.textContent = "Saved."; setTimeout(() => (msg.textContent = ""), 2500); }
    catch (e) { msg.textContent = `Couldn't save: ${e.message}`; }
  };
  function draw() {
    list.replaceChildren();
    if (!srcs.length) list.append(h("p", { class: "fnote", text: "No sources yet. A source fetches something from outside Home Assistant, like what's new in Jellyfin, and turns it into a sensor your pages can show." }));
    srcs.forEach((s, i) => {
      const out = h("p", { class: "fnote", role: "status", "aria-live": "polite" });
      list.append(h("div", { class: "srccard" },
        h("div", { class: "srchead" }, h("b", { text: SRC_KINDS[s.type] || s.type }), h("span", { class: "spacer" }),
          h("button", { class: "btn tinted", onclick: async () => {
            out.textContent = "Testing…";
            try {
              const r = (await api("api/sources/test", { method: "POST", body: s })).body;
              out.textContent = r.fills ? `It works. ${r.fills}.` : r.error ? `It didn't work: ${r.error}`
                : r.published.length ? r.published.map((p) => `${p.entity_id} = ${p.state}`).join("  ·  ") : "Nothing came back. Check the settings above.";
            }
            catch (e) { out.textContent = `It didn't work: ${e.message}`; }
          } }, "Test"),
          h("button", { class: "btn tinted danger", onclick: () => { srcs.splice(i, 1); draw(); } }, "Remove")),
        ...sourceGives(s, draw),
        ...(SRC_FIELDS[s.type] || []).filter(([k]) => !(s.fills && SENSOR_ONLY.includes(k))).map(([k, l, t]) => field(k === "pick" && s.fills ? "Data at" : l, input(s[k], (v) => { s[k] = t === "number" ? Number(v) || 0 : v; if (k === "name") { s.name = slug(v).replace(/-/g, "_"); draw(); } }, { type: t === "password" ? "password" : t === "number" ? "number" : "text" }))),
        out));
    });
  }
  pane.append(list, h("div", { class: "btnrow" }, add, h("span", { class: "spacer" }), msg, h("button", { class: "btn primary", onclick: save }, "Save sources")));
  draw();
}

/* ---------- icons ---------- */
// Your own SVGs (local:, in epaper/icons) and Iconify sets, each downloaded only when someone asks
// (iconsets.py). Nothing here needs Custom Icons (the user's design, 22 Oct).
const ICON_BATCH = 600 * 1024;              // what one request carries, under the editor's 1 MB
const MAX_ICON_FILE = 512 * 1024;           // iconsets.MAX_SVG
const many = (n, one, more) => `${n.toLocaleString()} ${n === 1 ? one : more}`;
const listed = (names) => (names.length < 3 ? names.join(" and ") : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`);

async function iconsPane(app, pane) {
  const box = h("div");
  const said = h("p", { class: "fnote", role: "status", "aria-live": "polite" });
  pane.append(box);
  let st = null, timer = 0, busyBefore = new Set(), checking = false;
  const here = () => box.isConnected;
  const refreshIcons = (prefixes) => { prefixes.forEach((p) => app.glyphs.forget(p)); app.glyphs.load().then(() => app.refresh()); };

  async function load() {
    try { st = (await api("api/iconsets")).body; }
    catch (e) {
      box.replaceChildren(h("p", { class: "fnote bad", text: `Couldn't read your icon sets: ${e.message}` }),
        h("div", { class: "btnrow" }, h("button", { class: "btn tinted", onclick: load }, "Try again")));
      return;
    }
    settled();
  }
  // After every answer: what finished since the last one is drawn again everywhere, and the pane
  // asks again while anything is still downloading.
  function settled() {
    const busy = new Set(st.sets.filter((s) => s.state === "downloading").map((s) => s.prefix));
    const done = [...busyBefore].filter((p) => !busy.has(p));
    const checked = checking && !st.check?.running;
    if (done.length || checked) refreshIcons(checked ? st.sets.map((s) => s.prefix) : done);
    if (checked) {
      const c = st.check;
      said.textContent = c.failed.length ? `Couldn't check ${listed(c.failed)}. ${st.sets.find((s) => s.error)?.error || ""}`.trim()
        : c.updated.length ? `Updated ${listed(c.updated)}.` : "Your sets are up to date.";
    }
    busyBefore = busy; checking = !!st.check?.running;
    draw();
    clearTimeout(timer);
    if ((busy.size || checking) && here()) timer = setTimeout(() => here() && load(), 1000);
  }

  async function upload(files) {
    const svgs = files.filter((f) => /\.svg$/i.test(f.name) || f.type === "image/svg+xml");
    const out = { added: [], replaced: [], refused: files.filter((f) => !svgs.includes(f)).map((f) => ({ file: f.name, why: "isn't an SVG file" })) };
    if (!svgs.length) { said.textContent = "Choose SVG files. Other kinds of pictures can't be icons."; return; }
    said.textContent = "";
    let batch = [], size = 0;
    const send = async () => {
      if (!batch.length) return;
      const r = (await api("api/icons/own", { method: "POST", body: { files: batch } })).body;
      ["added", "replaced", "refused"].forEach((k) => out[k].push(...r[k]));
      st = r; batch = []; size = 0;
    };
    try {
      for (const f of svgs) {
        if (f.size > MAX_ICON_FILE) { out.refused.push({ file: f.name, why: "is larger than 512 kB, more than any icon needs" }); continue; }
        const item = { name: f.name, svg: await f.text() };
        const n = JSON.stringify(item).length;
        if (batch.length && (size + n > ICON_BATCH || batch.length >= 40)) await send();
        batch.push(item); size += n;
      }
      await send();
    } catch (e) { said.textContent = `Couldn't add them: ${e.message}`; draw(); return; }
    const names = [...out.added, ...out.replaced];
    const lines = [];
    if (names.length === 1) lines.push(`Added ${names[0]}. Use it as local:${names[0]}.`);
    else if (names.length) lines.push(`Added ${many(names.length, "icon", "icons")}${out.replaced.length ? `, ${out.replaced.length} of them replacing ones you had` : ""}.`);
    out.refused.forEach((r) => lines.push(`${r.file} ${r.why}.`));
    said.textContent = lines.join(" ");
    if (names.length) refreshIcons(["local"]);
    draw();
  }

  async function addSet(prefix, name) {
    // The row is there at once; "Downloading…" fades in only if it takes a while (editor.css).
    if (!st.sets.some((s) => s.prefix === prefix)) { st.sets.push({ prefix, name: name || prefix, state: "downloading" }); draw(); }
    try { st = (await api("api/iconsets", { method: "POST", body: { prefix } })).body; }
    catch (e) { toast(e.message); st.sets = st.sets.filter((s) => s.prefix !== prefix || s.state !== "downloading"); draw(); return; }
    busyBefore.add(prefix);       // ready already counts as finished: drawn again everywhere
    settled();
  }
  async function removeSet(s) {
    try { st = (await api(`api/iconsets/${encodeURIComponent(s.prefix)}`, { method: "DELETE" })).body; }
    catch (e) { toast(`Couldn't remove it: ${e.message}`); return; }
    refreshIcons([s.prefix]);
    settled();
    toast(`Removed ${s.name}.`, { label: "Undo", run: () => addSet(s.prefix, s.name) });
  }

  function draw() {
    const own = st.own, total = own.count + own.legacy;
    const fileIn = h("input", { type: "file", accept: ".svg,image/svg+xml", multiple: true, hidden: true,
      onchange: () => { upload([...fileIn.files]); fileIn.value = ""; } });
    const ownGroup = group(grow("Your own icons", total ? `${many(total, "icon", "icons")}, used as local:name` : "None yet",
      h("button", { class: "btn tinted", onclick: () => fileIn.click() }, "Add icons…")), fileIn);
    // The note's words are the same for everyone; Custom Icons' folder is named only to those who have icons in it.
    const where = h("p", { class: "fnote" }, "Add SVG files with the button, or drop them here. They're kept in ", h("code", { text: own.folder }),
      " in Home Assistant's configuration folder, where you can also put them yourself.",
      own.legacy ? [" Icons in ", h("code", { text: own.legacy_folder }), ", the Custom Icons integration's folder, are used too."] : null);
    // Dropping SVG files anywhere on the group or its note adds them too.
    const ownZone = h("div", { class: "dropzone" }, ownGroup, where);
    ownZone.addEventListener("dragover", (e) => { if ([...(e.dataTransfer?.types || [])].includes("Files")) { e.preventDefault(); ownGroup.classList.add("dropping"); } });
    ownZone.addEventListener("dragleave", (e) => { if (!ownZone.contains(e.relatedTarget)) ownGroup.classList.remove("dropping"); });
    ownZone.addEventListener("drop", (e) => { e.preventDefault(); ownGroup.classList.remove("dropping"); upload([...(e.dataTransfer?.files || [])]); });

    const rows = st.sets.map((s) => {
      const sub = s.state === "downloading" ? h("small", { class: "waiting", text: "Downloading…" })
        : s.state === "failed" ? h("small", { class: "bad", text: s.error })
        : s.state === "missing" ? h("small", { text: "Not downloaded yet" })
        : h("small", { text: [`${s.prefix}:`, many(s.count, "icon", "icons"), s.license, s.source === "custom_icons" ? "from Custom Icons' download" : ""].filter(Boolean).join(" · ") });
      const retry = s.state === "failed" || s.state === "missing";
      return h("div", { class: "gr" }, h("span", { class: "gl" }, s.name, sub),
        h("span", { class: "rowbtns" },
          retry ? h("button", { class: "btn tinted", onclick: () => addSet(s.prefix) }, s.state === "missing" ? "Download" : "Try again") : null,
          h("button", { class: "btn tinted danger", "aria-label": `Remove ${s.name}`, disabled: s.state === "downloading" ? "" : null, onclick: () => removeSet(s) }, "Remove")));
    });
    const sets = rows.length ? group(...rows)
      : h("p", { class: "fnote", text: "No sets yet. Iconify has over 150 single-color sets, like Phosphor, Tabler and Font Awesome. Each is downloaded when you add it." });
    const check = h("button", { class: "btn tinted", disabled: !st.sets.length || checking ? "" : null,
      onclick: async () => {
        try { st = (await api("api/iconsets/check", { method: "POST" })).body; } catch (e) { said.textContent = `Couldn't check: ${e.message}`; return; }
        checking = true; said.textContent = ""; settled();
      } }, checking ? "Checking…" : "Check for updates");
    box.replaceChildren(ownZone,
      h("h4", { class: "gtitle", text: "Iconify sets" }), sets,
      h("div", { class: "btnrow" }, h("button", { class: "btn primary", onclick: () => addSetPane(app, pane, st, addSet, () => { pane.replaceChildren(pane.firstChild, box); draw(); }) }, "Add a set…"),
        h("span", { class: "spacer" }), check),
      said);
  }
  await load();
}

/* Add a set: Iconify's single-color sets, searchable, inside the Icons pane (Back returns). The
   list is fetched the first time it's opened, then kept by the add-on. */
async function addSetPane(app, pane, st, addSet, back) {
  const title = pane.firstChild;
  const q = h("input", { type: "search", "aria-label": "Search Iconify's sets", placeholder: "Search sets: phosphor, weather, brands…", autocomplete: "off", spellcheck: "false" });
  const list = h("div");
  const head = h("div", { class: "subhead" }, h("button", { class: "btn icon", "aria-label": "Back to Icons", onclick: back }, icon("back")), h("h4", { text: "Add a set" }));
  pane.replaceChildren(title, head, h("div", { class: "search" }, icon("search", "sm"), q), list);
  // Fades in only when it's slow (editor.css), so a kept list never flashes it.
  list.replaceChildren(h("p", { class: "fnote waiting", text: "Getting Iconify's list of sets…" }));
  let sets;
  const fetchList = async (refresh) => {
    try { sets = (await api(`api/iconsets/available${refresh ? "?refresh=1" : ""}`)).body.sets; }
    catch (e) {
      list.replaceChildren(h("p", { class: "fnote bad", text: e.message }),
        h("div", { class: "btnrow" }, h("button", { class: "btn tinted", onclick: () => fetchList(true) }, "Try again")));
      return;
    }
    draw();
  };
  const chosen = new Set(st.sets.map((s) => s.prefix));
  // Previews: each set's sample icons, asked for when its row comes into view, a few rows at a
  // time; drawn into squares that are there from the start, so nothing moves.
  const seen = new Map(), asked = new Set();
  let wantTimer = 0;
  const viewer = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting && !asked.has(e.target.dataset.prefix)) { asked.add(e.target.dataset.prefix); viewer.unobserve(e.target); }
    clearTimeout(wantTimer);
    wantTimer = setTimeout(askSamples, 120);
  }, { root: pane, rootMargin: "200px 0px" });
  async function askSamples() {
    const want = [...asked].filter((p) => !seen.has(p)).slice(0, 24);
    if (!want.length || !list.isConnected) return;
    want.forEach((p) => seen.set(p, null));
    let got = {};
    try { got = (await api("api/iconsets/samples", { method: "POST", body: { prefixes: want } })).body.samples || {}; } catch (_) { /* the squares stay empty */ }
    for (const [p, recs] of Object.entries(got)) { seen.set(p, recs); fill(p); }
    if ([...asked].some((p) => !seen.has(p))) askSamples();
  }
  function fill(prefix) {
    const recs = seen.get(prefix);
    const strip = list.querySelector(`.samples[data-prefix="${CSS.escape(prefix)}"]`);
    if (!recs || !strip) return;
    [...strip.children].forEach((svg, i) => { if (recs[i]) paint(svg, recs[i]); });
  }
  const strip = (s) => {
    const n = Math.max(1, (s.samples || []).length);
    const el = h("span", { class: "samples", "aria-hidden": "true", data: { prefix: s.prefix } },
      ...Array.from({ length: n }, () => { const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"); svg.setAttribute("viewBox", "0 0 24 24"); return svg; }));
    if (seen.get(s.prefix)) requestAnimationFrame(() => fill(s.prefix));
    else if (!asked.has(s.prefix)) viewer.observe(el);
    return el;
  };
  function draw() {
    const words = q.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const shown = sets.filter((s) => words.every((w) => `${s.name} ${s.prefix} ${s.category} ${s.author}`.toLowerCase().includes(w)));
    list.replaceChildren(shown.length ? group(...shown.slice(0, 250).map((s) => h("div", { class: "gr" },
      h("span", { class: "gl" }, s.name, h("small", { text: [`${s.prefix}:`, many(s.total, "icon", "icons"), s.license, s.category].filter(Boolean).join(" · ") }), strip(s)),
      chosen.has(s.prefix) ? h("span", { class: "added" }, icon("check", "sm"), "Added")
        : h("button", { class: "btn tinted", "aria-label": `Add ${s.name}`, onclick: () => { chosen.add(s.prefix); back(); addSet(s.prefix, s.name); } }, "Add"))))
      : h("p", { class: "empty-note", text: `No set matches “${q.value.trim()}”. Try a simpler word.` }));
  }
  q.addEventListener("input", () => sets && draw());
  q.focus({ preventScroll: true });
  await fetchList(false);
}

/* ---------- time and language ---------- */
// One setting for every device's times (render/clock.py): clocks, sunrise, "Today 14:00", kick-off.
// The screen's language goes here too when it comes.
async function timePane(app, pane) {
  const box = h("div", {}, h("p", { class: "fnote", text: "Checking…" }));
  pane.append(box);
  let r;
  try { r = (await api("api/settings/time")).body || {}; } catch (e) { box.replaceChildren(h("p", { class: "fnote bad", text: `Couldn't read it: ${e.message}` })); return; }
  const word = (f) => (f === "12h" ? "12-hour" : "24-hour");
  const draw = () => box.replaceChildren(group(grow("Time", "On every device: clocks, sunrise and sunset, due times, kick-offs",
    select([["auto", `As in Home Assistant (${word(r.resolved)} here)`], ["12h", "12-hour, like 2:30 PM"], ["24h", "24-hour, like 14:30"]], r.format || "auto", async (v) => {
      try {
        r = (await api("api/settings/time", { method: "PUT", body: { format: v } })).body || r;
        draw(); forgetThumbnails(); app.canvas?.preview(true); app.renderStrip();
        toast(`Times read ${word(r.resolved)} now, on every device from its next update.`);
      } catch (e) { toast(`Couldn't change it: ${e.message}`); }
    }, { "aria-label": "Time" }))));
  draw();
}

function editorPane(app, pane) {
  const buttons = select([["third", "Over the last third"], ["half", "Across the bottom half"]], app.tileButtons(),
    (v) => { app.prefs.set("tile_buttons_" + app.stripSize(), v); app.applyStripPos(); }, { "aria-label": "Where Duplicate and Delete sit" });
  pane.append(group(
    grow("Appearance", null, select([["system", "Match the system"], ["light", "Light"], ["dark", "Dark"]], app.prefs.get("theme", "system"), (v) => { app.prefs.set("theme", v); app.applyTheme(); })),
    grow("Page strip", "Down the side becomes a row again in narrow windows", select([["top", "Above the canvas"], ["bottom", "Below the canvas"], ["side", "Down the side"]], app.prefs.get("strip_pos", "top"), (v) => { app.prefs.set("strip_pos", v); app.applyStripPos(); })),
    grow("Page strip size", "How large its pages are", select([["small", "Small"], ["standard", "Standard"], ["large", "Large"]], app.stripSize(), (v) => { app.prefs.set("page_strip_size", v); app.applyStripPos(); buttons.value = app.tileButtons(); })),
    grow("Duplicate and Delete", "On each page in the strip, for this size", buttons),
    grow("Check legibility from", "The size note under text uses this distance", select([["0.8", "0.8 m, a desk"], ["1.5", "1.5 m, a bedside"], ["3.0", "3 m, a sofa"], ["5.0", "5 m, across a room"], ["0", "Don't check"]], app.prefs.get("view_dist", "3.0"), (v) => { app.prefs.set("view_dist", v); app.canvas.preview(true); })),
    grow("Guides", "Where the footer is, and a faint outline around every element", toggle(app.prefs.get("guides") === "1", (v) => { app.prefs.set("guides", v ? "1" : "0"); app.refresh(); }, "Guides"))),
    group(grow("Keyboard shortcuts", null, h("button", { class: "btn tinted", onclick: () => openShortcuts() }, "Show"))));
}
