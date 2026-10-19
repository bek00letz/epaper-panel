// The bigger jobs, each in a sheet: a new page, settings, what's on the panel
// now, the whole strip, saving a preset, and the rare question of which
// version to keep.

import { h, icon, api, clone, pageTitle, slug, nowHM, modKey, prefs } from "./util.js";
import { sheet, popover, field, input, number, select, seg, toggle, toggleRow, section, linkButton, toast, closeAll } from "./ui.js";
import { DISPLAYS, isWidget } from "./elements.js";
import { describe, parseShowIf, syncDynamicGridShowIf } from "./conditions.js";
import { PRESETS, PRESET_ICONS, reflowPageElements } from "./legacy.js";
import { thumbnail, statusSummary } from "./strip.js";

const thumbImg = (app, key, page) => {
  const img = h("img", { class: "thumb", alt: "", "data-thumb": key, draggable: "false" });
  requestAnimationFrame(() => thumbnail(app, key, img, page));
  return h("span", { class: "thumbwrap", style: { aspectRatio: `${app.geometry().W} / ${app.geometry().H}` } }, img);
};

/* ---------- a new page ---------- */
export function openPresets(app) {
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
    PRESETS.forEach((p) => grid.append(card("preset:" + p.id, { elements: p.makeElements("") }, p.title, p.desc, () => {
      if (p.asks) step2(app, node, close, p); else { close(); addFromPreset(app, p, ""); }
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
    const found = app.ents.filter((e) => (s ? (e.entity_id.includes(s) || (e.name || "").toLowerCase().includes(s)) : e.entity_id.startsWith(p.asks + ".")));
    list.replaceChildren(...found.slice(0, 80).map((e) => h("button", { class: "opt" + (chosen === e.entity_id ? " active" : ""), role: "option", "aria-selected": String(chosen === e.entity_id),
      onclick: () => { chosen = e.entity_id; add.disabled = false; draw(); drawPreview(); } },
      h("span", { class: "otext" }, h("span", { class: "o1", text: e.name || e.entity_id }), h("span", { class: "o2", text: e.entity_id })), h("span", { class: "ov", text: `${e.state}${e.unit ? " " + e.unit : ""}` }))));
    if (!found.length) list.append(h("p", { class: "empty-note", text: s ? "Nothing matches. Try part of the name." : "No sensors of this kind. Search for one, or skip." }));
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
  if (page.tier === "when") syncDynamicGridShowIf(page);
  app.addPage(p.id, page);
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
    const { tone, line1 } = statusSummary(app);
    const lines = [];
    if (doc.saving === "error") lines.push(`Your changes couldn't be saved: ${doc.saveError} They're kept in this window, and it keeps trying.`);
    else if (doc.dirty) lines.push("Your changes are saved, but the panel doesn't have them until you send.");
    else if (s.rendered_at) lines.push(`Pages rendered at ${nowHM(s.rendered_at)}. The panel looks for new ones every ${s.panel_interval || 5} min.`);
    if (s.panel_link?.pending_refresh) lines.push(`The panel hasn't picked up the last change yet${s.panel_link.last_error ? `: ${s.panel_link.last_error}` : ""}. It keeps trying.`);
    if (s.panel_link?.problem && !s.panel_link?.node) lines.push(`No panel found: ${s.panel_link.problem}.`);
    if (s.error) lines.push(`The last render failed: ${s.error}`);
    pop.append(h("div", { class: "sthead" }, h("span", { class: "led " + tone }), h("span", { text: line1 })), ...lines.map((l) => h("p", { class: "fnote", text: l })));

    const live = s.pages || [];
    pop.append(h("div", { class: "poplab", text: "Rotating" }), h("p", { class: "fnote", text: live.length ? `${live.map(pageTitle).join(", ")}, ${doc.live.rotate_seconds || 30} s each.` : "Nothing at the moment." }));
    const hidden = [...new Set(doc.live.rotation)].filter((n) => doc.live.pages[n]?.tier === "when" && !live.includes(n));
    if (hidden.length) {
      pop.append(h("div", { class: "poplab", text: "Hidden right now" }));
      hidden.forEach((n) => { const d = describe(doc.live.pages[n].show_if, app.entMap); pop.append(h("p", { class: "fnote" }, h("b", { text: pageTitle(n) + ". " }), `${d.text}. ${d.why}`)); });
    }
    if (s.active_alert) pop.append(h("div", { class: "poplab", text: "Alert" }), h("p", { class: "fnote", text: `${pageTitle(s.active_alert)} has taken over the panel.` }));
    const qh = doc.live.quiet_hours || {};
    pop.append(h("div", { class: "poplab", text: "Quiet hours" }), h("p", { class: "fnote", text: !qh.enabled ? "Off." : s.quiet_active ? `On now${s.quiet_reason ? ` (${s.quiet_reason})` : ""}, until ${qh.end}.` : `${qh.start} to ${qh.end}${qh.sleep_screen !== false ? ", with the sleep screen" : ""}.` }));

    const actions = h("div", { class: "btnrow wrap" });
    const dev = app.device || {};
    if (dev.sleep !== null && dev.sleep !== undefined) actions.append(h("button", { class: "btn tinted", onclick: async () => { close(); await app.deviceSet({ sleep: !dev.sleep }, dev.sleep ? "The panel is waking up." : "The panel is going to sleep."); } }, icon("moon", "sm"), dev.sleep ? "Wake" : "Sleep now"));
    if (dev.can_clear) actions.append(h("button", { class: "btn tinted", onclick: async () => { close(); await app.deviceSet({ clear_ghosting: true }, "The panel is clearing its ghosting."); } }, icon("sparkle", "sm"), "Clear ghosting"));
    actions.append(h("button", { class: "btn tinted", onclick: () => { close(); openFullStrip(app); } }, icon("eye", "sm"), "See every page"));
    pop.append(actions);
    if (doc.dirty) pop.append(h("button", { class: "btn tinted danger wide", onclick: () => { close(); doc.revert(); toast("Went back to what's on the panel.", { label: "Undo", run: () => doc.undo() }); } }, icon("revert", "sm"), "Throw away unsent changes"));
    // Fresh device state for next time; the buttons above use what's known now.
    app.loadDevice();
  }, { label: "Now on the panel", align: "left" });
}

export function openFullStrip(app) {
  sheet("Every page, as the panel has them", (node) => {
    const img = h("img", { class: "fullstrip", alt: "All the pages the panel is rotating through, stacked." });
    const meta = h("p", { class: "fnote" });
    const load = () => { img.src = "api/strip.png?t=" + Date.now(); const p = app.status?.pages || []; meta.textContent = p.length ? `In order: ${p.map(pageTitle).join(", ")}.` : ""; };
    node.append(h("div", { class: "sheet-body" }, h("div", { class: "stripbox" }, img), meta,
      app.doc.dirty ? h("p", { class: "fnote", text: "This is what's been sent. Your unsent changes aren't in it yet." }) : null),
      h("div", { class: "sheet-foot" }, h("button", { class: "btn tinted", onclick: load }, "Reload")));
    load();
  }, { cls: "wide" });
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
          const label = c.kind === "rotation" ? "The rotation" : { quiet_hours: "Quiet hours", rotate_seconds: "How long each page shows", custom_presets: "Your presets", location_presets: "Saved places", display: "Panel model", orientation: "Mounting" }[c.name] || c.name;
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
    ["Snap off while dragging", "Hold ⌥"], ["Click again without moving", "Selects what's underneath"], ["This list", "?"]];
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

export function openSettings(app, sectionName = "panel") {
  sheet("Settings", (node) => {
    const nav = h("nav", { class: "setnav", "aria-label": "Settings" });
    const pane = h("div", { class: "setpane" });
    const sections = {
      panel: ["Panel", "panel", () => panelPane(app, pane, show)],
      install: ["Install or update", "key", () => installPane(app, pane)],
      quiet: ["Quiet hours", "moon", () => quietPane(app, pane)],
      sources: ["Data sources", "plug", () => sourcesPane(app, pane)],
      editor: ["Editor", "gear", () => editorPane(app, pane)],
    };
    function show(k) {
      nav.querySelectorAll("button").forEach((b) => b.setAttribute("aria-current", b.dataset.k === k ? "page" : "false"));
      pane.replaceChildren(h("h3", { class: "panetitle", text: sections[k][0] }));
      sections[k][2]();
      prefs.set("settings_section", k);
    }
    Object.entries(sections).forEach(([k, [l, ic]]) => nav.append(h("button", { class: "navrow", data: { k }, onclick: () => show(k) }, icon(ic, "sm"), h("span", { text: l }))));
    node.append(h("div", { class: "settings" }, nav, pane));
    show(sectionName || prefs.get("settings_section", "panel"));
  }, { cls: "wide tall" });
}

function group(...rows) { return h("div", { class: "group" }, ...rows); }
function grow(label, sub, ctl) { return h("div", { class: "gr" }, h("span", { class: "gl" }, label, sub ? h("small", { text: sub }) : null), ctl); }

async function panelPane(app, pane, show) {
  const doc = app.doc, spec = doc.spec;
  const conn = h("span", { class: "fnote", text: "Checking…" });
  pane.append(group(grow("Connection", null, conn), grow("Install or update the panel", "Makes its ESPHome file and walks you through it", h("button", { class: "btn tinted", onclick: () => show("install") }, "Open"))));
  const reflowNote = h("p", { class: "fnote" });
  pane.append(h("h4", { class: "gtitle", text: "Display" }), group(
    grow("Model", null, select(Object.values(DISPLAYS).map((d) => [d.id, `${d.name}, ${d.w} × ${d.h}`]), spec.display, async (v) => {
      spec.display = v; doc.commit();
      try { await api("api/panel-setup", { method: "POST", body: { display: v } }); } catch (e) { toast(`The panel's install file wasn't updated: ${e.message}`); }
    })),
    grow("Mounted", "Which way up the panel hangs", select([[0, "Landscape"], [180, "Landscape, upside down"], [90, "Portrait"], [270, "Portrait, flipped"]], spec.orientation || 0, (v) => {
      const was = [90, 270].includes(Number(spec.orientation)); spec.orientation = Number(v); const now = [90, 270].includes(spec.orientation);
      doc.commit();
      if (was !== now) toast(`The canvas is ${now ? "portrait" : "landscape"} now.`, { label: "Rearrange this page", run: () => { reflowPageElements(doc.page(), now, app.geometry().d); doc.commit(); } });
    })),
    grow("Check for new pages every", "The panel's own timer. Changes at once.", (() => {
      const s = select([1, 2, 3, 5, 10, 15, 30, 60].map((m) => [m, m === 1 ? "minute" : `${m} minutes`]), app.status?.panel_interval || 5, async (v) => {
        try {
          const r = (await api("api/panel-refresh", { method: "POST", body: { interval: Number(v) } })).body;
          toast(r.ha_updated ? `The panel now checks every ${v} min.` : `Saved, but the panel didn't get it: ${r.error || "it isn't reachable right now"}.`);
        } catch (e) { toast(`Couldn't change it: ${e.message}`); }
      }); return s; })())), reflowNote);

  const ghost = h("div");
  pane.append(h("h4", { class: "gtitle", text: "Ghosting and sleep" }), ghost);
  const drawDevice = (dev) => {
    ghost.replaceChildren();
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
  try {
    const r = (await api("api/panel-setup")).body;
    const p = r.panel || {};
    conn.textContent = p.connected ? `Connected${p.rssi ? `, Wi-Fi ${p.rssi} dBm` : ""}` : p.node ? "Found, but offline. It picks up changes when it's back." : "No panel yet";
  } catch (e) { conn.textContent = "Couldn't check"; }
}

async function installPane(app, pane) {
  const box = h("div", {}, h("p", { class: "fnote", text: "Loading…" }));
  pane.append(box);
  let r;
  try { r = (await api("api/panel-setup")).body; } catch (e) { box.replaceChildren(h("p", { class: "fnote bad", text: `Couldn't load the panel's setup: ${e.message}` })); return; }
  const c = r.config || {};
  if ((!c.ha_host || c.ha_host === "homeassistant.local") && location.hostname && !["localhost", "127.0.0.1"].includes(location.hostname)) c.ha_host = location.hostname;
  const yaml = h("textarea", { class: "inp code tall", readonly: true, "aria-label": "The panel's ESPHome file", spellcheck: "false" });
  const secrets = h("textarea", { class: "inp code", readonly: true, "aria-label": "secrets.yaml lines", spellcheck: "false" });
  const secretsWrap = h("div");
  const status = h("div");
  const save = async (extra = {}, msg) => {
    try {
      const body = { display: app.doc.spec.display, ha_host: host.value.trim() || location.hostname || "homeassistant.local", frame_port: parseInt(port.value, 10) || 8099,
        device_name: dev.value.trim() || "crowpanel-epaper", wifi_ssid: ssid.value.trim(), wifi_password: pw.value, api_encryption_key: key.value.trim(), use_secrets: useSecrets, ...extra };
      r = (await api("api/panel-setup", { method: "POST", body })).body;
      apply();
      if (msg) toast(msg); else if (r.esphome_synced) toast("Saved, and written to Home Assistant's ESPHome folder.");
    } catch (e) { toast(`Couldn't save the setup: ${e.message}`); }
  };
  const host = input(c.ha_host, () => save(), { placeholder: "homeassistant.local" });
  const port = number(c.frame_port || r.frame_port || 8099, () => save(), { min: "1", max: "65535", style: { width: "7em" } });
  const dev = input(c.device_name || "crowpanel-epaper", () => save());
  const ssid = input(c.wifi_ssid, () => save(), { placeholder: "From your secrets" });
  const pw = input(c.wifi_password, () => save(), { type: "password", placeholder: "From your secrets" });
  const key = h("input", { class: "inp code", readonly: true, value: c.api_encryption_key || "", "aria-label": "Encryption key" });
  let useSecrets = !!c.use_secrets;
  const copy = (text, what) => {
    const done = () => toast(`Copied ${what}.`);
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, () => fallback());
    else fallback();
    function fallback() {
      const t = h("textarea", { style: { position: "fixed", left: "-9999px" } }); t.value = text; document.body.append(t); t.select();
      let ok = false; try { ok = document.execCommand("copy"); } catch (_) {}
      t.remove();
      if (ok) done(); else toast("Your browser didn't allow copying. Select the text and copy it yourself.");
    }
  };
  function apply() {
    const cc = r.config || {};
    yaml.value = r.yaml || ""; secrets.value = r.secrets_yaml || ""; key.value = cc.api_encryption_key || key.value;
    secretsWrap.hidden = !(cc.use_secrets || !cc.wifi_ssid);
    const p = r.panel || {};
    status.replaceChildren(...[
      h("p", { class: "note " + (p.connected ? "good" : "warn") }, h("span", { class: "led" }), h("span", { text: p.connected ? `Connected in Home Assistant${p.ip ? ` at ${p.ip}` : ""}.` : p.node ? "Found, but offline. It picks up changes when it reconnects." : "No panel yet. Install the file below with ESPHome, then add the device in Home Assistant." })),
      r.frame_protection && r.frame_protection !== "on" ? h("p", { class: "note warn" }, icon("info", "sm"), h("span", { text: "Pages on your network aren't protected yet. Installing the file below switches it on; nothing goes blank in between." })) : null,
      app.status?.ha_entities?.problem ? h("p", { class: "note warn" }, icon("info", "sm"), h("span", { text: app.status.ha_entities.problem })) : null].filter(Boolean));
  }
  box.replaceChildren(status,
    group(grow("Home Assistant's address", "Where the panel fetches pages from", host), grow("Port", null, port), grow("Device name", null, dev)),
    group(grow("Wi-Fi network", null, ssid), grow("Wi-Fi password", null, pw), grow("Use secrets.yaml", "Keep the Wi-Fi details out of the file", toggle(useSecrets, (v) => { useSecrets = v; save(); }, "Use secrets.yaml"))),
    group(grow("Encryption key", "Also protects updates over Wi-Fi", h("div", { class: "inline" }, key, h("button", { class: "btn tinted", onclick: () => copy(key.value, "the key") }, "Copy"))),
      grow("New key", "The panel then needs reinstalling and re-adding in Home Assistant", h("button", { class: "btn tinted danger", onclick: () => save({ regenerate_keys: true }, "New key made. Reinstall the panel and add it again in Home Assistant.") }, "Make a new key"))),
    h("h4", { class: "gtitle", text: "The panel's file" }), yaml,
    h("div", { class: "btnrow" }, h("button", { class: "btn primary", onclick: () => copy(yaml.value, "the file") }, "Copy"),
      h("button", { class: "btn tinted", onclick: () => {
        const a = h("a", { href: URL.createObjectURL(new Blob([yaml.value], { type: "text/yaml" })), download: (dev.value.trim() || "crowpanel-epaper") + ".yaml" });
        a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      } }, "Download")),
    secretsWrap,
    h("h4", { class: "gtitle", text: "Installing" }),
    h("ol", { class: "steps" },
      h("li", { text: "In Home Assistant, open ESPHome, choose New device, name it, pick ESP32-S3, then Skip." }),
      h("li", { text: "Edit the new device, replace everything with the file above, and Install. Use USB-C the first time; after that it updates over Wi-Fi." }),
      h("li", { text: "When Home Assistant finds the panel under Settings, Devices, choose Configure and paste the encryption key." })));
  secretsWrap.append(h("h4", { class: "gtitle", text: "Lines for secrets.yaml" }), secrets, h("div", { class: "btnrow" }, h("button", { class: "btn tinted", onclick: () => copy(secrets.value, "the lines") }, "Copy")));
  apply();
}

function quietPane(app, pane) {
  const doc = app.doc;
  const qh = doc.spec.quiet_hours;
  const set = (k, v) => { qh[k] = v; doc.commit(); draw(); };
  const body = h("div");
  pane.append(h("p", { class: "fnote", text: "While quiet hours last, the panel doesn't flash or download, so a dark room stays dark. Its buttons still work. Sent with your pages." }), body);
  function draw() {
    body.replaceChildren(
      group(grow("Quiet hours", null, toggle(qh.enabled, (v) => set("enabled", v), "Quiet hours"))),
      group(grow("From", null, input(qh.start, (v) => set("start", v), { type: "time" })), grow("Until", "Overnight works, like 23:00 to 07:00", input(qh.end, (v) => set("end", v), { type: "time" }))),
      group(grow("Also while nobody's home", qh.presence_entity ? (app.entMap.get(qh.presence_entity)?.name || qh.presence_entity) : "A person, group or zone", (() => {
        const b = h("button", { class: "btn tinted", onclick: () => app.openEntityPicker(b, (id) => set("presence_entity", id), { domains: ["person", "zone", "group"], current: qh.presence_entity, allowNone: true }) }, qh.presence_entity ? "Change" : "Choose"); return b; })()),
        grow("Alerts can wake it", null, toggle(qh.allow_alerts !== false, (v) => set("allow_alerts", v), "Alerts can wake it")),
        grow("Sleep screen", "Closed eyes, and when it wakes. Off keeps a page on screen overnight.", toggle(qh.sleep_screen !== false, (v) => set("sleep_screen", v), "Sleep screen"))),
      h("p", { class: "fnote" }, "Home Assistant gets ", h("code", { text: "sensor.epaper_quiet_hours" }), " for your own automations."));
    body.querySelectorAll(".group:not(:first-child)").forEach((g) => g.classList.toggle("off", !qh.enabled));
  }
  draw();
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
            try { const r = (await api("api/sources/test", { method: "POST", body: s })).body; out.textContent = r.published.length ? r.published.map((p) => `${p.entity_id} = ${p.state}`).join("  ·  ") : "Nothing came back. Check the settings above."; }
            catch (e) { out.textContent = `It didn't work: ${e.message}`; }
          } }, "Test"),
          h("button", { class: "btn tinted danger", onclick: () => { srcs.splice(i, 1); draw(); } }, "Remove")),
        h("p", { class: "fnote" }, "Becomes ", h("code", { text: `sensor.epaper_${s.name || "name"}` }), s.type === "jellyfin" ? " and its _count" : ""),
        ...(SRC_FIELDS[s.type] || []).map(([k, l, t]) => field(l, input(s[k], (v) => { s[k] = t === "number" ? Number(v) || 0 : v; if (k === "name") { s.name = slug(v).replace(/-/g, "_"); draw(); } }, { type: t === "password" ? "password" : t === "number" ? "number" : "text" }))),
        out));
    });
  }
  pane.append(list, h("div", { class: "btnrow" }, add, h("span", { class: "spacer" }), msg, h("button", { class: "btn primary", onclick: save }, "Save sources")));
  draw();
}

function editorPane(app, pane) {
  pane.append(group(
    grow("Appearance", null, select([["system", "Match the system"], ["light", "Light"], ["dark", "Dark"]], app.prefs.get("theme", "system"), (v) => { app.prefs.set("theme", v); app.applyTheme(); })),
    grow("Check legibility from", "The size note under text uses this distance", select([["0.8", "0.8 m, a desk"], ["1.5", "1.5 m, a bedside"], ["3.0", "3 m, a sofa"], ["5.0", "5 m, across a room"], ["0", "Don't check"]], app.prefs.get("view_dist", "3.0"), (v) => { app.prefs.set("view_dist", v); app.canvas.preview(true); })),
    grow("Footer and padlock guides", "And a faint outline around every element", toggle(app.prefs.get("guides") === "1", (v) => { app.prefs.set("guides", v ? "1" : "0"); app.refresh(); }, "Guides"))),
    group(grow("Keyboard shortcuts", null, h("button", { class: "btn tinted", onclick: () => openShortcuts() }, "Show")),
      grow("The previous editor", "Still here while this one proves itself", h("a", { class: "btn tinted", href: "?classic=1" }, "Open"))));
}
