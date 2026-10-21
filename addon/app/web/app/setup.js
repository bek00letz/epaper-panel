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
import { select, linkButton } from "./ui.js";
import { lookOf, pageFor, examplePage, rankSensors, groupName, sensorOf, freeSourceName, energyRoles } from "./presets.js";

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
  let li = Math.min(Number(initialLook) || 0, p.looks.length - 1), ent = "";
  const look = () => lookOf(p, li);
  const changed = () => { ready(); drawPreview(); };
  const node = h("div", { class: "stepin fade" });
  const preview = h("div", { class: "pv" });
  const caption = h("p", { class: "fnote pvcap", "aria-live": "polite" });
  const notes = [h("p", { class: "fnote", text: `In ${groupName(p.group)}` })];
  if (p.was) notes.push(h("p", { class: "fnote", text: `Was called “${p.was}”.` }));
  node.append(h("div", { class: "lead" }, h("div", {}, preview, caption), h("div", { class: "leadtext" }, h("p", { class: "desc", text: p.desc }), ...notes)));
  const need = p.needs && SETUPS[p.needs] ? SETUPS[p.needs]({ app, p, changed }) : null;
  const asksEntity = p.asks && !need;           // a setup decides what its page shows

  const addBtn = h("button", { class: "btn primary", onclick: async () => {
    if (!need) { add(look(), ent); return; }
    addBtn.disabled = true;
    const done = await need.commit();             // saves what it set up; says why if it couldn't
    if (done) add(look(), done.ent || "", done.extra); else ready();
  } }, "Add page");
  const skip = asksEntity ? h("button", { class: "btn tinted", onclick: () => add(look(), "") }, "Skip for now") : null;
  foot.append(...[skip, addBtn].filter(Boolean));

  function ready() { addBtn.disabled = need ? !need.ready() : asksEntity && !ent; }
  function drawPreview() {
    const shown = need ? need.shows() : { ent, mine: !!ent, caption: ent ? `With ${app.entMap.get(ent)?.name || ent}.` : "" };
    const page = shown.mine ? pageFor(p, look(), shown.ent || "", shown.extra) : examplePage(p, look());
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
    const drawNote = () => { note.textContent = look().note || ""; note.hidden = !look().note; };
    const choose = (i) => { li = i; rememberLook && rememberLook(i); drawLooks(); drawNote(); drawPreview(); };
    const drawLooks = () => group.replaceChildren(...p.looks.map((l, i) => chips
      ? h("button", { class: "chipbtn", role: "radio", "aria-checked": String(i === li), tabindex: i === li ? "0" : "-1", onclick: () => choose(i), text: l.name })
      : h("button", { class: "pbtn", role: "radio", "aria-checked": String(i === li), tabindex: i === li ? "0" : "-1", "aria-label": l.name, onclick: () => choose(i) },
        thumb(app, `preset:${l.id}:example`, examplePage(p, l), { example: true }), h("span", { class: "pt", text: l.name }))));
    radioKeys(group, choose);
    drawLooks(); drawNote();
    node.append(h("div", { class: "stepsec" }, h("h3", { class: "slab", text: p.choose || "Style" }), group, note));
  }

  /* What it shows: the right kind of entity first, sensibly picked. */
  if (asksEntity) {
    const picker = sensorPicker(app, p, (id) => { ent = id; changed(); });
    node.append(h("div", { class: "stepsec" }, h("h3", { class: "slab", text: WHAT[p.asks] || "Which one should it show?" }), picker.node));
    // The Energy dashboard's own sensor is the answer already: picked, and said so.
    if (p.prefer?.energy) energySensors().then((en) => { const first = picker.rank(en); if (!ent && first) picker.pick(first); });
  }

  if (need) node.append(need.node);

  ready(); drawPreview();
  return {
    node,
    focus: () => setTimeout(() => (node.querySelector('[role="radio"][aria-checked="true"], .stepsec input') || addBtn).focus({ preventScroll: true })),
    dispose: () => { skip?.remove(); addBtn.remove(); need?.dispose?.(); },
  };
}

/* ---------- what presets set up in place ---------- */
const SETUPS = { wifi: wifiSetup, jellyfin: jellyfinSetup, energy: energySetup };

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
      node.replaceChildren(h("p", { class: "note good" }, icon("check", "sm"), h("span", { text: ids.length
        ? `From your Energy dashboard: ${ids.map(name).join(", ")}.` : "From your Energy dashboard." })),
        p.energy === "grid" && !en.grid_power.length ? h("p", { class: "fnote", text: "Your dashboard has no grid power sensor, so the page shows today's balance instead." }) : null);
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
