// A preset's next step in the New page sheet: its look (a style as a
// picture, a league or series as a chip), what it shows, and whatever it
// needs set up first, in place (the rule: a preset sets up what it needs).
// The footer's Skip for now and Add page belong to the step and leave with it.
//
// What a preset needs (`needs`) is a setup in SETUPS: it draws its own part
// of the step and says when it's ready, what the page shows, and what to
// save before the page is added (a data source goes into the one store
// Settings › Data sources shows, so a second page reuses it).

import { h, icon, api } from "./util.js";
import { select, linkButton, seg } from "./ui.js";
import { dateEditor, binsEditor, ready as countsReady } from "./countdown.js";
import { zonesEditor } from "./zones.js";
import { holdingsEditor } from "./holdings.js";
import { busyNote } from "./busyday.js";
import { connectPart, computerName, heardWords } from "./reporters.js";
import { sleepsBetweenUpdates, lookOf, asksOf, needsOf, pageFor, examplePage, rankSensors, groupName, sensorOf, freeSourceName, energyRoles, staleNote, presetChangesEvery,
  batterySensors, preselectBatteries, batteriesPast, BATTERY_DEFAULT, batteryRule, chargedByYou, isLowSensor, flightIdent } from "./presets.js";

const WHAT = { calendar: "Which calendar should it show?", todo: "Which list should it show?", weather: "Which weather should it show?",
  binary_sensor: "Which sensor should it show?", sensor: "Which sensor should it show?", jellyfin: "Whose Jellyfin should it show?" };
const NONE = { calendar: "No calendars in Home Assistant yet. Search for one, or skip.", todo: "No to-do lists in Home Assistant yet. Add one under Settings, Devices & services, or skip.",
  weather: "No weather in Home Assistant yet. Search for one, or skip." };

// The Energy dashboard, asked once per editor session (presets.energyRoles).
let energy = null;
export async function energySensors() {
  if (!energy) energy = api("api/energy").then((r) => energyRoles(r.body || {}), () => ({ known: false }));
  return energy;
}

/* Arrow keys move the choice in a radio group, as with real radio buttons. */
function radioKeys(group, onPick) {
  group.addEventListener("keydown", (e) => {
    const dir = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (!dir) return;
    const items = [...group.querySelectorAll('[role="radio"]')];
    const i = items.indexOf(document.activeElement);
    if (i < 0) return;
    e.preventDefault();
    const n = (i + dir + items.length) % items.length;
    onPick(n);
    group.querySelectorAll('[role="radio"]')[n]?.focus();          // drawn again by the pick
  });
}

/* A searchable list of entities, sensible ones first (rankSensors), the
   pick ticked. rank() re-sorts once the Energy dashboard is known and says
   which one it would pick. */
function sensorPicker(app, p, onPick, label) {
  let ent = "", ranked = rankSensors(p, app.ents);
  const q = h("input", { type: "search", placeholder: "Search", "aria-label": "Search", autocomplete: "off", spellcheck: "false" });
  const list = h("div", { class: "optlist", role: "listbox", "aria-label": label || WHAT[p.asks] || "Which one" });
  const pick = (id) => { ent = id; draw(); onPick(id); };
  function draw() {
    const s = q.value.trim().toLowerCase();
    const rows = s ? app.ents.filter((e) => e.entity_id.includes(s) || (e.name || "").toLowerCase().includes(s)).map((e) => ({ e, tag: (ranked.find((r) => r.e === e) || {}).tag || "" })) : ranked;
    list.replaceChildren(...rows.slice(0, 80).map(({ e, tag }) => h("button", { class: "opt", role: "option", "aria-selected": String(ent === e.entity_id), onclick: () => pick(e.entity_id) },
      h("span", { class: "ock", "aria-hidden": "true" }, ent === e.entity_id ? icon("check", "sm") : null),
      h("span", { class: "otext" }, h("span", { class: "o1", text: e.name || e.entity_id }), h("span", { class: "o2", text: e.entity_id })),
      tag ? h("span", { class: "otag", text: tag }) : null,
      h("span", { class: "ov", text: `${e.state ?? ""}${e.unit ? " " + e.unit : ""}` }))));
    if (!rows.length) list.append(h("p", { class: "empty-note", text: s ? "Nothing matches. Try part of the name." : NONE[p.asks] || "No sensors of this kind. Search for one, or skip." }));
  }
  q.addEventListener("input", draw);
  draw();
  return {
    node: h("div", { class: "picker" }, h("div", { class: "search" }, icon("search", "sm"), q), list),
    pick,
    rank: (en) => { ranked = rankSensors(p, app.ents, en); draw(); return ranked[0]?.tag ? ranked[0].e.entity_id : ""; },
  };
}

export function setupStep(app, p, { thumb, add, foot, initialLook = 0, rememberLook }) {
  let li = Math.min(Number(initialLook) || 0, p.looks.length - 1), ent = "", need = null, asksEntity = false;
  const look = () => lookOf(p, li);
  const changed = () => { ready(); drawPreview(); };
  const node = h("div", { class: "stepin fade" });
  const preview = h("div", { class: "pv" });
  const caption = h("p", { class: "fnote pvcap", "aria-live": "polite" });
  const notes = [h("p", { class: "fnote", text: `In ${groupName(p.group)}` })];
  if (p.was) notes.push(h("p", { class: "fnote", text: `Was called “${p.was}”.` }));
  const stale = staleNote(presetChangesEvery(p), app.screen);
  if (stale) notes.push(h("p", { class: "note info" }, icon("info", "sm"), h("span", { text: stale })));
  node.append(h("div", { class: "lead" }, h("div", {}, preview, caption), h("div", { class: "leadtext" }, h("p", { class: "desc", text: p.desc }), ...notes)));

  const addBtn = h("button", { class: "btn primary", onclick: async () => {
    if (!need) { add(look(), ent); return; }
    addBtn.disabled = true;
    const done = await need.commit();             // saves what it set up; says why if it couldn't
    if (done) add(look(), done.ent || "", done.extra); else ready();
  } }, "Add page");
  const skip = h("button", { class: "btn tinted", onclick: () => add(look(), "") }, "Skip for now");
  foot.append(skip, addBtn);

  function ready() { addBtn.disabled = need ? !need.ready() : asksEntity && !ent; skip.hidden = !asksEntity; }
  function drawPreview() {
    const shown = need ? need.shows() : { ent, mine: !!ent, caption: ent ? `With ${app.entMap.get(ent)?.name || ent}.` : "" };
    const page = shown.mine ? pageFor(p, look(), shown.ent || "", shown.extra, (id) => app.entMap.get(id) || "") : examplePage(p, look());
    const key = `preset:${look().id}:` + (shown.mine ? JSON.stringify([shown.ent || "", shown.extra || null]) : "example");
    preview.replaceChildren(thumb(app, key, page, { example: !shown.mine, cls: "big" }));
    caption.textContent = shown.mine ? shown.caption : "Example values. Your page shows yours.";
  }

  /* Its look: styles as pictures, leagues and series as chips. */
  if (p.looks.length > 1) {
    const chips = p.choose === "League" || p.choose === "Series";
    const group = h("div", { class: chips ? "chips" : "styles", role: "radiogroup", "aria-label": p.choose || "Style" });
    // A look that changes on its own says how, under the choice.
    const note = h("p", { class: "fnote", "aria-live": "polite" });
    // …and one that draws differently on a device that sleeps says how, there.
    const asleep = () => (sleepsBetweenUpdates(app.screen) ? look().onSleeping || "" : "");
    const drawNote = () => { const t = [look().note, asleep()].filter(Boolean).join(" "); note.textContent = t; note.hidden = !t; };
    // Scores: whether a busy day, with this league added, could pass what the device holds (busyday.js).
    let busy = h("span", { hidden: true });
    const drawBusy = () => {
      if (p.choose !== "League") return;
      const spec = app.doc.spec, adding = "\u0000adding";
      const fresh = busyNote(app, { pages: { ...spec.pages, [adding]: { elements: look().make() } }, rotation: [...spec.rotation, adding] });
      busy.replaceWith(fresh); busy = fresh;
    };
    const choose = (i) => {
      const before = [asksOf(p, look()), needsOf(p, look())].join();
      li = i; rememberLook && rememberLook(i); drawLooks(); drawNote(); drawBusy();
      if ([asksOf(p, look()), needsOf(p, look())].join() !== before) drawWhat();   // a countdown's date, bins or calendar
      changed();
    };
    const drawLooks = () => group.replaceChildren(...p.looks.map((l, i) => chips
      ? h("button", { class: "chipbtn", role: "radio", "aria-checked": String(i === li), tabindex: i === li ? "0" : "-1", onclick: () => choose(i), text: l.name })
      : h("button", { class: "pbtn", role: "radio", "aria-checked": String(i === li), tabindex: i === li ? "0" : "-1", "aria-label": l.name, onclick: () => choose(i) },
        thumb(app, `preset:${l.id}:example`, examplePage(p, l), { example: true }), h("span", { class: "pt", text: l.name }))));
    radioKeys(group, choose);
    drawLooks(); drawNote();
    node.append(h("div", { class: "stepsec" }, h("h3", { class: "slab", text: p.choose || "Style" }), group, note, busy));
    drawBusy();
  }

  /* What it shows, or what it sets up: the look's own, or else the preset's. */
  const what = h("div", { class: "stepwhat" });
  node.append(what);
  function drawWhat() {
    need?.dispose?.();
    ent = "";
    const needs = needsOf(p, look()), asks = asksOf(p, look());
    need = needs && SETUPS[needs] ? SETUPS[needs]({ app, p, look: look(), changed }) : null;
    asksEntity = !!asks && !need;
    what.replaceChildren();
    if (need) { what.append(need.node); return; }
    if (!asksEntity) return;
    // The right kind of entity first, sensibly picked.
    const q = { ...p, asks };
    const picker = sensorPicker(app, q, (id) => { ent = id; changed(); });
    what.append(h("div", { class: "stepsec" }, h("h3", { class: "slab", text: WHAT[asks] || "Which one should it show?" }), picker.node));
    // The Energy dashboard's own sensor is the answer already: picked, and said so.
    if (q.prefer?.energy) energySensors().then((en) => { const first = picker.rank(en); if (!ent && first) picker.pick(first); });
  }
  drawWhat();

  ready(); drawPreview();
  return {
    node,
    focus: () => setTimeout(() => (node.querySelector('[role="radio"][aria-checked="true"], .stepsec input') || addBtn).focus({ preventScroll: true })),
    dispose: () => { skip.remove(); addBtn.remove(); need?.dispose?.(); },
  };
}

/* ---------- what presets set up in place ---------- */
export const SETUPS = { wifi: wifiSetup, jellyfin: jellyfinSetup, energy: energySetup, players: playersSetup, date: countSetup("date"), bins: countSetup("bins"), parts: partsSetup, zones: zonesSetup,
  holdings: holdingsSetup, flight: flightSetup, found: foundSetup, mail: mailSetup, github: githubSetup, reporter: reporterSetup, batteries: batteriesSetup };

/* AI usage: a computer that reports it, connected here (reporters.js, the same part Settings › AI usage
   shows). One already connected is enough: the page reads every one. It can be added before any is,
   and then the page itself says how. */
function reporterSetup({ changed }) {
  let view = null, part = null;
  const node = h("div", { class: "stepsec" });
  const slow = setTimeout(() => { if (!view) node.replaceChildren(h("p", { class: "fnote", text: "Looking for your computers…" })); }, 300);
  const heard = () => (view?.reporters || []).filter((r) => r.heard_at);
  async function load() {
    try { view = (await api("api/reporters")).body || { reporters: [] }; } catch (_) { view = { reporters: [], providers: [] }; }
    clearTimeout(slow); draw(); changed();
  }
  function draw() {
    const reps = view.reporters || [];
    if (!reps.length) {
      part = part || connectPart({ onJoined: () => setTimeout(load, 1500) });
      node.replaceChildren(part.node, h("p", { class: "fnote", text: "You can add the page now: until a computer reports, it says how to connect one." }));
      return;
    }
    node.replaceChildren(h("h3", { class: "slab", text: "From your computers" }),
      h("div", { class: "group" }, ...reps.map((r) => h("div", { class: "gr" },
        h("span", { class: "gl" }, computerName(r), h("small", { text: heardWords(r.heard_at) + "." }))))),
      h("p", { class: "fnote", text: "Connect another, or rename one, in Settings › AI usage." }));
  }
  load();
  return {
    node,
    ready: () => true,
    shows: () => (heard().length ? { mine: true, caption: "With your usage." } : { mine: false }),
    commit: async () => ({}),
    dispose: () => { clearTimeout(slow); part?.dispose(); },
  };
}

/* Guest Wi-Fi: the network goes into the code, so it's asked for. */
function wifiSetup({ changed }) {
  const wifi = { ssid: "", password: "", auth: "WPA" };
  const inp = (key, label, attrs) => {
    const x = h("input", { class: "inp", value: wifi[key], autocomplete: "off", spellcheck: "false", "aria-label": label, ...attrs });
    x.addEventListener("input", () => { wifi[key] = x.value; changed(); });
    return x;
  };
  const pw = inp("password", "Password", { type: "text" });
  const sec = select([["WPA", "WPA, WPA2 or WPA3"], ["WEP", "WEP"], ["nopass", "None, it's open"]], wifi.auth, (v) => { wifi.auth = v; pw.disabled = v === "nopass"; changed(); }, { "aria-label": "Security" });
  const node = h("div", { class: "stepsec" }, h("h3", { class: "slab", text: "Your guest network" }),
    h("div", { class: "group" },
      h("label", { class: "gr" }, h("span", { class: "gl", text: "Network name" }), inp("ssid", "Network name", { placeholder: "As your phone lists it", maxlength: "32" })),
      h("label", { class: "gr" }, h("span", { class: "gl" }, "Password", h("small", { text: "In the code, so guests don't type it" })), pw),
      h("div", { class: "gr" }, h("span", { class: "gl", text: "Security" }), sec)),
    h("p", { class: "fnote", text: "The page shows the network's name; the password stays in the code." }));
  const extra = () => ({ ...wifi, password: wifi.auth === "nopass" ? "" : wifi.password });
  return {
    node,
    ready: () => !!wifi.ssid.trim(),
    shows: () => ({ mine: !!wifi.ssid.trim(), extra: extra(), caption: "As your guests will see it." }),
    commit: async () => ({ extra: extra() }),
  };
}

/* New to watch: a Jellyfin source of its own, or one you already have.
   Connecting asks Jellyfin who's there, so "whose unwatched" is a pick, not
   something to type. With JellyHA installed, its server address is filled in;
   the key is typed, since JellyHA doesn't share it. */
function jellyfinSetup({ app, changed }) {
  let all = null, mine = [], picked = null, connecting = false;
  const form = { base: "", key: "", fromJellyHA: false };
  let check = null, user = "", problem = "";
  const node = h("div", { class: "stepsec" });
  const say = h("p", { class: "fnote", role: "status", "aria-live": "polite" });
  const loading = setTimeout(() => { if (!all) node.replaceChildren(h("p", { class: "fnote", text: "Looking for your Jellyfin…" })); }, 300);

  (async () => {
    try { all = (await api("api/sources")).body || []; } catch (e) { all = []; problem = `Couldn't read your data sources: ${e.message}`; }
    mine = all.filter((s) => s.type === "jellyfin");
    if (mine.length === 1) picked = mine[0];
    if (!mine.length) await suggest();
    clearTimeout(loading);
    draw(); changed();
  })();

  async function suggest() {
    try {
      const r = (await api("api/sources/jellyfin/suggest")).body || {};
      if (r.address && !form.base) { form.base = r.address; form.fromJellyHA = true; }
    } catch (_) { /* typed by hand, then */ }
  }
  async function connect() {
    if (connecting || !form.base.trim() || !form.key.trim()) return;
    connecting = true; problem = ""; check = null; user = ""; draw();
    try {
      const r = (await api("api/sources/jellyfin/check", { method: "POST", body: { base: form.base.trim(), key: form.key.trim() } })).body || {};
      if (r.ok) { check = r; if ((r.users || []).length === 1) user = r.users[0].name; }
      else problem = r.error || "Jellyfin didn't answer. Check the address and the key.";
    } catch (e) { problem = e.message; }
    connecting = false; draw(); changed();
  }

  function draw() {
    if (!all) return;
    const parts = [];
    if (mine.length && picked !== "new") {
      parts.push(h("h3", { class: "slab", text: "Which Jellyfin should it show?" }),
        h("div", { class: "optlist", role: "listbox", "aria-label": "Your Jellyfin" }, ...mine.map((s) => {
          const e = app.entMap.get(sensorOf(s));
          return h("button", { class: "opt", role: "option", "aria-selected": String(picked === s), onclick: () => { picked = s; draw(); changed(); } },
            h("span", { class: "ock", "aria-hidden": "true" }, picked === s ? icon("check", "sm") : null),
            h("span", { class: "otext" }, h("span", { class: "o1", text: s.user ? `${s.user}'s unwatched` : "Unwatched" }), h("span", { class: "o2 plain", text: s.base || sensorOf(s) })),
            h("span", { class: "ov", text: e ? `${e.state ?? ""}` : "" }));
        })),
        h("div", {}, linkButton("Connect another Jellyfin server", async () => { picked = "new"; if (!form.base) await suggest(); draw(); changed(); node.querySelector("input")?.focus(); })));
    } else {
      const base = h("input", { class: "inp", value: form.base, placeholder: "http://jellyfin.local:8096", inputmode: "url", autocomplete: "off", spellcheck: "false", "aria-label": "Server address" });
      const key = h("input", { class: "inp", value: form.key, type: "password", placeholder: "32 letters and numbers", autocomplete: "off", spellcheck: "false", "aria-label": "API key" });
      base.addEventListener("input", () => { form.base = base.value; form.fromJellyHA = false; check = null; changed(); });
      key.addEventListener("input", () => { form.key = key.value; check = null; changed(); });
      [base, key].forEach((x) => x.addEventListener("keydown", (e) => { if (e.key === "Enter") connect(); }));
      const go = h("button", { class: "btn tinted", disabled: connecting, onclick: connect }, connecting ? "Connecting…" : check ? "Connect again" : "Connect");
      parts.push(h("h3", { class: "slab", text: "Connect Jellyfin" }),
        h("p", { class: "fnote", text: "This page reads your Jellyfin library itself. Connect it once: every Jellyfin page uses the same connection, and it's under Settings › Data sources if you want to change it." }),
        h("div", { class: "group" },
          h("label", { class: "gr" }, h("span", { class: "gl" }, "Server address", form.fromJellyHA ? h("small", { text: "From JellyHA" }) : null), base),
          h("label", { class: "gr" }, h("span", { class: "gl" }, "API key", h("small", { text: "In Jellyfin: Dashboard › API Keys, then +" })), key)),
        h("div", { class: "btnrow" }, go, mine.length ? linkButton("Use one you have", () => { picked = mine.length === 1 ? mine[0] : null; draw(); changed(); }) : null));
      if (check) {
        parts.push(h("p", { class: "note good" }, icon("check", "sm"), h("span", { text: `Connected${check.titles != null ? ` · ${check.titles} new or unwatched` : ""}.` })));
        const users = check.users || [];
        if (users.length > 1) {
          const chips = h("div", { class: "chips", role: "radiogroup", "aria-label": "Whose unwatched" }, ...users.map((u) => h("button", { class: "chipbtn", role: "radio",
            "aria-checked": String(user === u.name), onclick: () => { user = u.name; draw(); changed(); }, text: u.name })));
          parts.push(h("h3", { class: "slab", text: "Whose unwatched?" }), chips);
        }
      }
    }
    say.textContent = problem;
    say.classList.toggle("bad", !!problem);
    node.replaceChildren(...parts, say);
  }

  const connected = () => picked === "new" || !mine.length;
  return {
    node,
    ready: () => (connected() ? !!check && (!!user || !(check.users || []).length) : !!picked && picked !== "new"),
    shows: () => (!connected() && picked && picked !== "new"
      ? { mine: true, ent: sensorOf(picked), caption: `With ${picked.user ? `${picked.user}'s` : "your"} Jellyfin.` }
      : { mine: false }),
    commit: async () => {
      if (!connected()) return { ent: sensorOf(picked) };
      const src = { type: "jellyfin", name: freeSourceName(all), base: form.base.trim(), key: form.key.trim(), user, days: 30 };
      try {
        const r = (await api("api/sources", { method: "PUT", body: [...all, src] })).body || {};
        all = r.sources || [...all, src];
        return { ent: sensorOf(src) };
      } catch (e) { problem = `Couldn't save the connection: ${e.message}`; draw(); return null; }
    },
    dispose: () => clearTimeout(loading),
  };
}

/* The Energy dashboard's widgets read it themselves, so nothing is picked
   when it has what they need. When it hasn't, Solar this month and Grid now
   take a sensor instead, here; Energy cost needs the dashboard's prices,
   which only Home Assistant sets, so it says where. */
const ENERGY = {
  solar: { has: (en) => en.solar_energy.length, list: (en) => en.solar_energy, what: "solar",
    pick: { asks: "sensor", prefer: { device_class: ["energy"], units: ["kWh", "Wh", "MWh"] } }, label: "A sensor that counts what your panels make",
    missing: "Your Energy dashboard has no solar yet. Add your panels there (in Home Assistant: Settings › Dashboards › Energy), or pick a sensor that counts what they make." },
  grid: { has: (en) => en.grid.length, list: (en) => en.grid_power.length ? en.grid_power : en.grid, what: "the grid",
    pick: { asks: "sensor", prefer: { device_class: ["power"], units: ["W", "kW"] } }, label: "Your grid power sensor",
    missing: "Your Energy dashboard has no grid yet. Add it there (in Home Assistant: Settings › Dashboards › Energy), or pick the sensor that measures your grid power." },
  cost: { has: (en) => en.has_cost, list: () => [], what: "prices",
    missing: "Energy cost needs prices: add them to the grid in your Energy dashboard (in Home Assistant: Settings › Dashboards › Energy). Until then the page says so." },
};
function energySetup({ app, p, changed }) {
  const role = ENERGY[p.energy];
  let en = null, ent = "", invert = false;
  const node = h("div", { class: "stepsec" });
  const loading = setTimeout(() => { if (!en) node.replaceChildren(h("p", { class: "fnote", text: "Checking your Energy dashboard…" })); }, 300);
  energySensors().then((x) => { clearTimeout(loading); en = x; draw(); changed(); });
  const has = () => !!(en && en.known && role.has(en));
  const name = (id) => app.entMap.get(id)?.name || id;

  function draw() {
    if (has()) {
      const ids = role.list(en);
      // replaceChildren() takes nodes only: a null would show as the word "null".
      node.replaceChildren(...[h("p", { class: "note good" }, icon("check", "sm"), h("span", { text: ids.length
        ? `From your Energy dashboard: ${ids.map(name).join(", ")}.` : "From your Energy dashboard." })),
        p.energy === "grid" && !en.grid_power.length ? h("p", { class: "fnote", text: "Your dashboard has no grid power sensor, so the page shows today's balance instead." }) : null].filter(Boolean));
      return;
    }
    const why = en.known ? role.missing : "Home Assistant didn't say how your Energy dashboard is set up." + (role.pick ? " Pick a sensor instead, or try again later." : " The page shows what it finds.");
    const parts = [h("p", { class: "note info" }, icon("info", "sm"), h("span", { text: why }))];
    if (role.pick) {
      const picker = sensorPicker(app, role.pick, (id) => { ent = id; changed(); }, role.label);
      parts.push(h("h3", { class: "slab", text: role.label }), picker.node);
      if (p.energy === "grid") parts.push(h("div", { class: "group" }, h("div", { class: "gr" }, h("span", { class: "gl", text: "Above zero when" }),
        select([["false", "Buying"], ["true", "Selling"]], String(invert), (v) => { invert = v === "true"; changed(); }, { "aria-label": "Above zero when" }))));
    }
    node.replaceChildren(...parts);
  }
  return {
    node,
    ready: () => !!en && (has() || !role.pick || !!ent),
    shows: () => (has() ? { mine: true, caption: "From your Energy dashboard." }
      : ent ? { mine: true, extra: { entity: ent, invert }, caption: `With ${name(ent)}.` } : { mine: false }),
    commit: async () => ({ extra: has() || !ent ? undefined : { entity: ent, invert } }),
    dispose: () => clearTimeout(loading),
  };
}

/* Now playing follows every media player, or the ones you tick. */
function playersSetup({ app, changed }) {
  const players = app.ents.filter((e) => e.entity_id.startsWith("media_player."));
  const chosen = new Set();
  const list = h("div", { class: "optlist", role: "group", "aria-label": "Which players" });
  const entity = () => [...chosen].join(", ");
  function draw() {
    list.replaceChildren(...players.map((e) => h("button", { class: "opt", role: "checkbox", "aria-checked": String(chosen.has(e.entity_id)),
      onclick: () => { chosen.has(e.entity_id) ? chosen.delete(e.entity_id) : chosen.add(e.entity_id); draw(); changed(); } },
      h("span", { class: "ock", "aria-hidden": "true" }, chosen.has(e.entity_id) ? icon("check", "sm") : null),
      h("span", { class: "otext" }, h("span", { class: "o1", text: e.name || e.entity_id }), h("span", { class: "o2", text: e.entity_id })),
      h("span", { class: "ov", text: e.state ?? "" }))));
    if (!players.length) list.append(h("p", { class: "empty-note", text: "No media players in Home Assistant yet. The page shows any you add later." }));
    hint.textContent = chosen.size ? `Shows ${chosen.size === 1 ? "this one" : "these"} while ${chosen.size === 1 ? "it plays" : "one plays"}.` : "Shows whichever is playing. Tick some to follow only those.";
  }
  const hint = h("p", { class: "fnote", "aria-live": "polite" });
  draw();
  return {
    node: h("div", { class: "stepsec" }, h("h3", { class: "slab", text: "Which players?" }), hint, list),
    ready: () => true,
    shows: () => (chosen.size ? { mine: true, extra: { entity: entity() }, caption: "With your players." } : { mine: false }),
    commit: async () => ({ extra: { entity: entity() } }),
  };
}

/* Countdown: a date of yours, or your bins and their days, in place: no
   calendar needed (the user's call, 21 Oct). The page counts from what's
   picked here (render/countdown.py). */
function countSetup(to) {
  return ({ changed }) => {
    const el = { to, ...(to === "bins" ? { bins: [], today_until: "noon" } : { name: "", at: "", yearly: false }) };
    const extra = () => ({ show_before: el.show_before || 0, ...(to === "bins" ? { bins: el.bins.filter((b) => b.from).map((b) => ({ ...b, name: b.name.trim() })), today_until: el.today_until, ...(el.numbers ? { numbers: true } : {}) }
      : { name: el.name.trim(), at: el.at, yearly: !!el.yearly }) });
    const editor = to === "bins" ? binsEditor(el, changed, { live: true }) : dateEditor(el, changed, { live: true });
    return {
      node: h("div", { class: "stepsec" }, h("h3", { class: "slab", text: to === "bins" ? "Your bins" : "The date" }), editor,
        h("p", { class: "fnote", text: to === "bins" ? "Each bin comes on its next collection day and then every week, or every 2, 3 or 4. Alternating bins are two bins every 2 weeks, a week apart."
          : "It counts the days, and the hours on the day if you give a time." })),
      ready: () => countsReady(el),
      shows: () => (countsReady(el) ? { mine: true, extra: extra(), caption: "With your dates." } : { mine: false }),
      commit: async () => ({ extra: extra() }),
    };
  };
}

/* A preset that shows several sensors (Battery and solar) asks for each, one
   at a time in place, with the Energy dashboard's own picked first and said
   so. Each part is optional: an empty one can be filled in the inspector.
   A shared page's sensors are asked the same way (sharesheet.js): a part
   says its kind (`asks`, a sensor by default), where it's used (`where`), and
   whether the page can't do without it (`needed`: a condition's). With
   `p.partsOptional`, nothing has to be picked; `partsNote` says what then. */
function partsSetup({ app, p, changed }) {
  const picks = {}, tags = {};
  let open = null, roles = {};
  const node = h("div", { class: "stepsec" }, h("h3", { class: "slab", text: "What it shows" }));
  const list = h("div", { class: "group parts" });
  node.append(list, h("p", { class: "fnote", text: p.partsNote || "Leave one out and its gauge stays empty until you pick it in the inspector." }));
  const name = (id) => app.entMap.get(id)?.name || id;
  const askOf = (part) => ({ asks: part.asks || "sensor", prefer: part.prefer });
  const needed = p.parts.filter((part) => part.needed);
  function draw() {
    list.replaceChildren(...p.parts.map((part) => {
      const q = askOf(part);
      const state = picks[part.key] ? `${name(picks[part.key])}${tags[part.key] ? " · " + tags[part.key] : ""}` : part.needed ? "Needed" : "Not chosen";
      const row = h("div", { class: "gr part" },
        h("span", { class: "gl" }, part.label, h("small", { text: part.where ? `${part.where} · ${state}` : state })),
        h("button", { class: "btn tinted", "aria-expanded": String(open === part.key), onclick: () => { open = open === part.key ? null : part.key; draw(); } },
          open === part.key ? "Done" : picks[part.key] ? "Change" : "Choose"));
      if (open !== part.key) return row;
      const picker = sensorPicker(app, q, (id) => { picks[part.key] = id; tags[part.key] = ""; open = null; draw(); changed(); }, part.label);
      picker.rank(roles);
      return h("div", {}, row, picker.node);
    }));
  }
  energySensors().then((en) => {
    roles = en || {};
    for (const part of p.parts) {
      const first = rankSensors(askOf(part), app.ents, roles)[0];
      if (!picks[part.key] && first?.tag) { picks[part.key] = first.e.entity_id; tags[part.key] = first.tag; }
    }
    draw(); changed();
  });
  draw();
  return {
    node,
    ready: () => (needed.length ? needed.every((part) => picks[part.key]) : !!p.partsOptional || Object.values(picks).some(Boolean)),
    shows: () => (Object.values(picks).some(Boolean) ? { mine: true, extra: { ...picks }, caption: "With your sensors." } : { mine: false }),
    commit: async () => ({ extra: { ...picks } }),
  };
}

/* A world clock's cities, picked in place: up to four, each found by its city and named as you like. */
function zonesSetup({ changed }) {
  const el = { zones: [{ tz: "", label: "" }] };
  const extra = () => ({ zones: el.zones.map((z) => ({ tz: z.tz || "", label: String(z.label || "").trim() })) });
  return {
    node: h("div", { class: "stepsec" }, h("h3", { class: "slab", text: "Cities" }), zonesEditor(el, changed, { live: true }),
      h("p", { class: "fnote", text: "Here is Home Assistant's own time zone. The cities share the page alike: one fills it, four make a grid." })),
    ready: () => el.zones.length > 0,
    shows: () => ({ mine: true, extra: extra(), caption: "With your cities." }),
    commit: async () => ({ extra: extra() }),
  };
}

/* Stocks and coins: what it shows, found by name or symbol on any exchange. */
function holdingsSetup({ changed }) {
  const el = { holdings: [] };
  const extra = () => ({ holdings: el.holdings.map((x) => ({ ...x })) });
  return {
    node: h("div", { class: "stepsec" }, h("h3", { class: "slab", text: "What you hold" }), holdingsEditor(el, changed, { live: true }),
      h("p", { class: "fnote", text: "Each shows in its own currency. You can add more, rename them and change their order later." })),
    ready: () => el.holdings.length > 0,
    shows: () => ({ mine: el.holdings.length > 0, extra: extra(), caption: "With today's prices." }),
    commit: async () => ({ extra: extra() }),
  };
}

/* Follow a flight: its number or callsign, as the booking or the airline says it. */
function flightSetup({ changed }) {
  let typed = "";
  const say = h("p", { class: "fnote", "aria-live": "polite" });
  const inp = h("input", { class: "inp", autocomplete: "off", spellcheck: "false", autocapitalize: "characters", maxlength: "10",
    placeholder: "W43186 or BAW17R", "aria-label": "Flight number or callsign" });
  inp.addEventListener("input", () => {
    typed = inp.value;
    say.textContent = typed.trim() && !flightIdent(typed) ? "A flight number is the airline's code and a number, like W4 3186 or BA 117." : "";
    changed();
  });
  return {
    node: h("div", { class: "stepsec" }, h("h3", { class: "slab", text: "Which flight" }),
      h("div", { class: "group" }, h("label", { class: "gr" }, h("span", { class: "gl" }, "Flight", h("small", { text: "Its number or its callsign" })), inp)),
      say, h("p", { class: "fnote", text: "While it flies, the page shows where it is. Before and after, it says so." })),
    ready: () => !!flightIdent(typed),
    shows: () => ({ mine: false, extra: { flight: flightIdent(typed) } }),
    commit: async () => ({ extra: { flight: flightIdent(typed) } }),
  };
}

// Which batteries you charge, by device (GET /api/batteries), asked once per editor session.
let batteriesAsked = null;
function batteryDevices() {
  if (!batteriesAsked) batteriesAsked = api("api/batteries").then((r) => r.body?.batteries || {}, () => { batteriesAsked = null; return {}; });
  return batteriesAsked;
}

/* Batteries: which way (low, to charge; or charged, to unplug), the page's number, and which
   batteries, ticked to start with by what they are (presets.preselectBatteries). Each can have
   its own number later, in the inspector. */
function batteriesSetup({ app, changed }) {
  const all = batterySensors(app.ents);
  let rule = "below", value = BATTERY_DEFAULT.below, tier = "when", touched = false;
  // Ticked once the add-on says which you charge, by their devices; by name if it can't say.
  let byDevice = null, chosen = new Set();
  const looking = setTimeout(() => { if (!byDevice) { hint.textContent = "Looking at your batteries…"; } }, 300);
  batteryDevices().then((got) => {
    clearTimeout(looking); byDevice = got;
    if (!touched) chosen = new Set(preselectBatteries(app.ents, rule, byDevice));
    drawList(); say(); changed();
  });
  const levelText = (e) => {
    if (["unavailable", "unknown"].includes(e.state)) return "No answer";
    if (isLowSensor(e)) return e.state === "on" ? "Low" : "OK";
    const v = parseFloat(e.state); return Number.isFinite(v) ? `${Math.round(v)}%` : "No level";
  };
  const nameOf = (e) => String(e.name || e.entity_id).replace(/\s+battery(\s+level)?$/i, "") || e.name;
  const node = h("div", { class: "stepsec" });
  const hint = h("p", { class: "fnote", role: "status", "aria-live": "polite" });
  const list = h("div", { class: "optlist batlist", role: "group", "aria-label": "Which batteries" });
  const num = h("input", { class: "inp", type: "number", inputmode: "numeric", min: "1", max: "100", step: "1", value: String(value), style: { width: "5em" } });
  num.addEventListener("input", () => { value = num.value === "" ? "" : Number(num.value); say(); changed(); });

  function say() {
    if (!byDevice && !touched) return;                                     // until the ticks are in
    const n = batteriesPast(app.ents, chosen, rule, value);
    hint.textContent = !chosen.size ? "Tick the batteries it watches."
      : `${n === 0 ? "None would show" : n === 1 ? "1 would show" : `${n} would show`} now, of the ${chosen.size} ticked. One you add to Home Assistant later shows too.`;
  }
  function drawList() {
    list.replaceChildren(...all.map((e) => h("button", { class: "opt", role: "checkbox", "aria-checked": String(chosen.has(e.entity_id)),
      onclick: () => { touched = true; chosen.has(e.entity_id) ? chosen.delete(e.entity_id) : chosen.add(e.entity_id); drawList(); say(); changed(); } },
      h("span", { class: "ock", "aria-hidden": "true" }, chosen.has(e.entity_id) ? icon("check", "sm") : null),
      h("span", { class: "otext" }, h("span", { class: "o1", text: nameOf(e) }), h("span", { class: "o2", text: e.entity_id })),
      h("span", { class: "ov", text: levelText(e) }))));
    if (!all.length) list.append(h("p", { class: "empty-note", text: "No batteries in Home Assistant yet: none of its sensors is a battery level in % or a battery-low sensor. Any you add later shows here on its own." }));
  }
  function draw() {
    const cmp = rule === "below" ? "Below" : "At least";
    num.setAttribute("aria-label", `${cmp}, in percent`);
    // replaceChildren() takes nodes only: a null would show as the word "null".
    node.replaceChildren(...[
      h("h3", { class: "slab", text: "Which ones show" }),
      h("div", { class: "group" },
        h("div", { class: "gr" }, h("span", { class: "gl", text: "Shows" }), seg([["below", "Low, to charge"], ["at_least", "Charged, to unplug"]], rule, (v) => {
          if (v === rule) return;
          rule = v; value = BATTERY_DEFAULT[v]; num.value = String(value);
          if (!touched && byDevice) chosen = new Set(preselectBatteries(app.ents, rule, byDevice));   // what fits this way, until you've picked
          draw(); changed();
        }, "Which batteries show")),
        h("label", { class: "gr" }, h("span", { class: "gl" }, cmp, h("small", { text: "Each can have its own in the inspector" })), h("span", { class: "inline" }, num, h("span", { class: "unit", text: "%" })))),
      h("h3", { class: "slab", text: `Batteries (${all.length})` }),
      all.length ? h("div", { class: "btnrow" },
        linkButton("Tick all", () => { touched = true; chosen = new Set(all.map((e) => e.entity_id)); drawList(); say(); changed(); }),
        linkButton("Untick all", () => { touched = true; chosen = new Set(); drawList(); say(); changed(); })) : null,
      list, hint,
      h("div", { class: "group" }, h("div", { class: "gr" }, h("span", { class: "gl" }, "On the device", h("small", { text: tier === "alert" ? "Comes up over the other pages when one is past it" : "Joins the rotation while one is past it" })),
        seg([["when", "With the pages"], ["alert", "As an alert"]], tier, (v) => { tier = v; draw(); changed(); }, "On the device")))].filter(Boolean));
    drawList(); say();
  }
  draw();
  // A rule, not today's list (review 2 #5): every battery of this way's kind, minus the unticked, plus
  // any of the other kind ticked; one added later shows too.
  const ids = new Set((app.ents || []).map((e) => e.entity_id));
  const kindOf = (e) => (chargedByYou(e, ids, byDevice || {}) ? "charge" : "swap");
  const extra = () => ({ rule, value: value === "" ? BATTERY_DEFAULT[rule] : value, ...batteryRule(all, chosen, rule, kindOf), tier });
  return {
    node,
    ready: () => chosen.size > 0,
    shows: () => (chosen.size ? { mine: true, extra: extra(), caption: "With your batteries." } : { mine: false }),
    commit: async () => ({ extra: extra() }),
  };
}

/* ---------- pages built on Home Assistant's own data ---------- */

/* What the add-on finds by itself, asked once per editor session per kind (GET /api/found): the
   same rules a page with nothing picked follows (sources/commute.py, departures.py, mail.py). */
const finding = {};
function found(what) {
  if (!finding[what]) finding[what] = api("api/found?what=" + what).then((r) => ({ ok: true, list: r.body?.found || [] }),
    (e) => { delete finding[what]; return { ok: false, list: [], error: e.message }; });
  return finding[what];
}

/* Where to set each up in Home Assistant, when it has none yet: plain steps, nothing to copy. */
const FOUND = {
  commute: { title: "Routes", all: "Shows every travel time in Home Assistant, and any you add there later.", some: "Shows the routes ticked.",
    none: "No travel times in Home Assistant yet. Add Waze Travel Time there (Settings › Devices & services › Add integration › Waze Travel Time): it needs no account or key, just where from and where to. Add a route for each trip; this page shows them all.",
    unit: (st) => (st == null || st === "" || isNaN(Number(st)) ? "" : `${Math.round(Number(st))} min`) },
  departures: { title: "Stops", all: "Shows every stop Home Assistant gives departures for.", some: "Shows the stops ticked.",
    none: "Nothing in Home Assistant gives departures yet. Add your transit there first (Settings › Devices & services › Add integration): GTFS works for most cities, or your operator's own integration. Then this page finds it by itself.",
    unit: () => "" },
};

/* Commute and Departures: what the add-on finds is ticked; none unticked keeps following what Home
   Assistant has (a route added next month shows too). Unticking one stores the ticked ones. */
function foundSetup({ app, p, changed }) {
  const words = FOUND[p.found];
  let got = null, chosen = null;
  const node = h("div", { class: "stepsec" });
  const looking = setTimeout(() => { if (!got) node.replaceChildren(h("p", { class: "fnote", text: "Looking in Home Assistant…" })); }, 300);
  found(p.found).then((r) => { clearTimeout(looking); got = r; chosen = new Set(r.list.map((e) => e.entity)); draw(); changed(); });
  const all = () => !got || chosen.size === got.list.length;
  const entities = () => (all() ? [] : got.list.map((e) => e.entity).filter((id) => chosen.has(id)));
  function draw() {
    if (!got.ok) { node.replaceChildren(h("p", { class: "note warn" }, icon("info", "sm"), h("span", { text: `${got.error}. Add the page anyway: it shows what it finds once Home Assistant answers.` }))); return; }
    if (!got.list.length) { node.replaceChildren(h("h3", { class: "slab", text: words.title }), h("p", { class: "note info" }, icon("info", "sm"), h("span", { text: words.none }))); return; }
    const list = h("div", { class: "optlist", role: "group", "aria-label": words.title }, ...got.list.map((e) => h("button", { class: "opt", role: "checkbox", "aria-checked": String(chosen.has(e.entity)),
      onclick: () => { chosen.has(e.entity) ? chosen.delete(e.entity) : chosen.add(e.entity); draw(); changed(); } },
      h("span", { class: "ock", "aria-hidden": "true" }, chosen.has(e.entity) ? icon("check", "sm") : null),
      h("span", { class: "otext" }, h("span", { class: "o1", text: e.name || e.entity }), h("span", { class: "o2", text: e.entity })),
      h("span", { class: "ov", text: words.unit(e.state) }))));
    node.replaceChildren(h("h3", { class: "slab", text: words.title }), list,
      h("p", { class: "fnote", role: "status", "aria-live": "polite", text: chosen.size ? (all() ? words.all : words.some) : "Tick at least one." }));
  }
  return {
    node,
    ready: () => !!got && (!got.list.length || chosen.size > 0),
    shows: () => (got?.list.length && chosen.size ? { mine: true, extra: { entities: entities() }, caption: "With yours." } : { mine: false }),
    commit: async () => ({ extra: { entities: got?.list.length ? entities() : [] } }),
    dispose: () => clearTimeout(looking),
  };
}

/* Mail: the add-on never holds an email password. Home Assistant's IMAP integration logs in; this
   says so, and what to set up there, then picks the mailbox when there are several. */
const MAIL_HOW = "Home Assistant's IMAP integration reads your mailbox, and the add-on reads what it says: the unread count, and who each new message is from and its subject. Your password stays in Home Assistant.";
const MAIL_SETUP = "To set it up in Home Assistant: Settings › Devices & services › Add integration › IMAP, with your mail server and an app password from your mail provider. Then come back: this page finds it.";
function mailSetup({ app, changed }) {
  let got = null, picked = "";
  const node = h("div", { class: "stepsec" });
  const looking = setTimeout(() => { if (!got) node.replaceChildren(h("p", { class: "fnote", text: "Looking for your mail in Home Assistant…" })); }, 300);
  found("mail").then((r) => { clearTimeout(looking); got = r; picked = r.list[0]?.entity || ""; draw(); changed(); });
  function draw() {
    const parts = [h("h3", { class: "slab", text: "Your mail" }), h("p", { class: "fnote", text: MAIL_HOW })];
    if (!got.ok) parts.push(h("p", { class: "note warn" }, icon("info", "sm"), h("span", { text: `${got.error}. Add the page anyway: it shows your mail once Home Assistant answers.` })));
    else if (!got.list.length) parts.push(h("p", { class: "note info" }, icon("info", "sm"), h("span", { text: MAIL_SETUP })));
    else {
      if (got.list.length > 1) parts.push(h("div", { class: "optlist", role: "radiogroup", "aria-label": "Which mailbox" }, ...got.list.map((e) => h("button", { class: "opt", role: "radio", "aria-checked": String(picked === e.entity),
        onclick: () => { picked = e.entity; draw(); changed(); } },
        h("span", { class: "ock", "aria-hidden": "true" }, picked === e.entity ? icon("check", "sm") : null),
        h("span", { class: "otext" }, h("span", { class: "o1", text: e.name || e.entity }), h("span", { class: "o2", text: e.entity })),
        h("span", { class: "ov", text: e.state ?? "" })))));
      else parts.push(h("p", { class: "note good" }, icon("check", "sm"), h("span", { text: `Found ${got.list[0].name || got.list[0].entity}.` })));
      parts.push(h("p", { class: "fnote", text: "Messages show from the next one that arrives; the unread count is right from the start." }));
    }
    node.replaceChildren(...parts);
  }
  return {
    node,
    ready: () => !!got,
    shows: () => ({ mine: false }),
    commit: async () => ({ extra: { entity: got?.list.length > 1 ? picked : "" } }),
    dispose: () => clearTimeout(looking),
  };
}

/* A GitHub user, checked with GitHub when typed (a person asked, so it's asked now). */
function githubSetup({ changed }) {
  let user = "", checked = null, checking = false, timer = 0;
  const say = h("p", { class: "fnote", role: "status", "aria-live": "polite" });
  const inp = h("input", { class: "inp", placeholder: "A GitHub username", autocomplete: "off", spellcheck: "false", autocapitalize: "off", "aria-label": "GitHub username", maxlength: "39" });
  async function check() {
    const asked = user.trim().replace(/^@/, "");
    if (!asked) { checked = null; draw(); changed(); return; }
    checking = true; draw();
    try { checked = { user: asked, ...((await api("api/github/check?user=" + encodeURIComponent(asked))).body || {}) }; }
    catch (e) { checked = { user: asked, ok: false, error: e.message }; }
    checking = false;
    if (asked === user.trim().replace(/^@/, "")) { draw(); changed(); }
  }
  inp.addEventListener("input", () => { user = inp.value; checked = null; clearTimeout(timer); timer = setTimeout(check, 600); draw(); changed(); });
  inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { clearTimeout(timer); check(); } });
  function draw() {
    const ok = checked?.ok;
    say.textContent = checking ? "Asking GitHub…" : !checked ? "Public contributions only: no account or token. GitHub is asked at most four times a day."
      : ok ? (checked.total != null ? `${checked.total.toLocaleString()} contributions in the past year.` : "Found. GitHub gave levels, not counts, so the totals are left out.")
      : checked.error;
    say.classList.toggle("bad", !!checked && !ok && !checking);
  }
  draw();
  const node = h("div", { class: "stepsec" }, h("h3", { class: "slab", text: "Whose contributions" }),
    h("div", { class: "group" }, h("label", { class: "gr" }, h("span", { class: "gl", text: "GitHub user" }), inp)), say);
  return {
    node,
    ready: () => !!checked?.ok,
    shows: () => (checked?.ok ? { mine: true, extra: { user: checked.user }, caption: `${checked.user} on GitHub.` } : { mine: false }),
    commit: async () => ({ extra: { user: checked?.user || "" } }),
    dispose: () => clearTimeout(timer),
  };
}
