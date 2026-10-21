// A preset's next step in the New page sheet: its look (a style as a
// picture, a league or series as a chip), what it shows, and whatever it
// needs set up first, in place (the rule: a preset sets up what it needs).
// The footer's Skip for now and Add page belong to the step and leave with it.

import { h, icon, api } from "./util.js";
import { select } from "./ui.js";
import { lookOf, pageFor, examplePage, rankSensors, groupName } from "./presets.js";

const WHAT = { calendar: "Which calendar should it show?", todo: "Which list should it show?", weather: "Which weather should it show?",
  binary_sensor: "Which sensor should it show?", sensor: "Which sensor should it show?", jellyfin: "Whose Jellyfin should it show?" };
const NONE = { calendar: "No calendars in Home Assistant yet. Search for one, or skip.", todo: "No to-do lists in Home Assistant yet. Add one under Settings, Devices & services, or skip.",
  weather: "No weather in Home Assistant yet. Search for one, or skip." };

// The Energy dashboard's sensors, asked once per editor session.
let energy = null;
export async function energySensors() {
  if (!energy) energy = api("api/energy").then((r) => r.body || {}, () => ({}));
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

export function setupStep(app, p, { thumb, add, foot, initialLook = 0, rememberLook }) {
  let li = Math.min(Number(initialLook) || 0, p.looks.length - 1), ent = "";
  const wifi = { ssid: "", password: "", auth: "WPA" };
  const look = () => lookOf(p, li);
  const asksEntity = p.asks && p.needs !== "wifi";

  const node = h("div", { class: "stepin fade" });
  const preview = h("div", { class: "pv" });
  const caption = h("p", { class: "fnote pvcap", "aria-live": "polite" });
  const notes = [h("p", { class: "fnote", text: `In ${groupName(p.group)}` })];
  if (p.was) notes.push(h("p", { class: "fnote", text: `Was called “${p.was}”.` }));
  node.append(h("div", { class: "lead" }, h("div", {}, preview, caption), h("div", { class: "leadtext" }, h("p", { class: "desc", text: p.desc }), ...notes)));

  const addBtn = h("button", { class: "btn primary", onclick: () => add(look(), ent, p.needs === "wifi" ? { ...wifi } : undefined) }, "Add page");
  const skip = asksEntity ? h("button", { class: "btn tinted", onclick: () => add(look(), "") }, "Skip for now") : null;
  foot.append(...[skip, addBtn].filter(Boolean));

  function ready() {
    addBtn.disabled = (asksEntity && !ent) || (p.needs === "wifi" && !wifi.ssid.trim());
  }
  function drawPreview() {
    const mine = p.needs === "wifi" ? !!wifi.ssid.trim() : !!ent;
    const page = mine ? pageFor(p, look(), ent, p.needs === "wifi" ? wifi : undefined) : examplePage(p, look());
    const key = `preset:${look().id}:` + (mine ? (p.needs === "wifi" ? JSON.stringify(wifi) : ent) : "example");
    preview.replaceChildren(thumb(app, key, page, { example: !mine, cls: "big" }));
    const e = ent && app.entMap.get(ent);
    caption.textContent = !mine ? "Example values. Your page shows yours." : p.needs === "wifi" ? "As your guests will see it." : `With ${e?.name || ent}.`;
  }

  /* Its look: styles as pictures, leagues and series as chips. */
  if (p.looks.length > 1) {
    const chips = p.choose === "League" || p.choose === "Series";
    const group = h("div", { class: chips ? "chips" : "styles", role: "radiogroup", "aria-label": p.choose || "Style" });
    const choose = (i) => { li = i; rememberLook && rememberLook(i); drawLooks(); drawPreview(); };
    const drawLooks = () => group.replaceChildren(...p.looks.map((l, i) => chips
      ? h("button", { class: "chipbtn", role: "radio", "aria-checked": String(i === li), tabindex: i === li ? "0" : "-1", onclick: () => choose(i), text: l.name })
      : h("button", { class: "pbtn", role: "radio", "aria-checked": String(i === li), tabindex: i === li ? "0" : "-1", "aria-label": l.name, onclick: () => choose(i) },
        thumb(app, `preset:${l.id}:example`, examplePage(p, l), { example: true }), h("span", { class: "pt", text: l.name }))));
    radioKeys(group, choose);
    drawLooks();
    node.append(h("div", { class: "stepsec" }, h("h3", { class: "slab", text: p.choose || "Style" }), group));
  }

  /* What it shows: the right kind of entity first, sensibly picked. */
  if (asksEntity) {
    const q = h("input", { type: "search", placeholder: "Search", "aria-label": "Search", autocomplete: "off", spellcheck: "false" });
    const list = h("div", { class: "optlist", role: "listbox", "aria-label": WHAT[p.asks] || "Which one" });
    let ranked = rankSensors(p, app.ents);
    const draw = () => {
      const s = q.value.trim().toLowerCase();
      const rows = s ? app.ents.filter((e) => e.entity_id.includes(s) || (e.name || "").toLowerCase().includes(s)).map((e) => ({ e, tag: (ranked.find((r) => r.e === e) || {}).tag || "" })) : ranked;
      list.replaceChildren(...rows.slice(0, 80).map(({ e, tag }) => h("button", { class: "opt", role: "option", "aria-selected": String(ent === e.entity_id),
        onclick: () => { ent = e.entity_id; ready(); draw(); drawPreview(); } },
        h("span", { class: "ock", "aria-hidden": "true" }, ent === e.entity_id ? icon("check", "sm") : null),
        h("span", { class: "otext" }, h("span", { class: "o1", text: e.name || e.entity_id }), h("span", { class: "o2", text: e.entity_id })),
        tag ? h("span", { class: "otag", text: tag }) : null,
        h("span", { class: "ov", text: `${e.state ?? ""}${e.unit ? " " + e.unit : ""}` }))));
      if (!rows.length) list.append(h("p", { class: "empty-note", text: s ? "Nothing matches. Try part of the name."
        : p.asks === "jellyfin" ? "No Jellyfin source yet. Add one in Settings, under Data sources, or skip." : NONE[p.asks] || "No sensors of this kind. Search for one, or skip." }));
    };
    q.addEventListener("input", draw);
    node.append(h("div", { class: "stepsec" }, h("h3", { class: "slab", text: WHAT[p.asks] || "Which one should it show?" }), h("div", { class: "search" }, icon("search", "sm"), q), list));
    draw();
    // The Energy dashboard's own sensor is the answer already: picked, and said so.
    if (p.prefer?.energy) energySensors().then((en) => {
      if (!node.isConnected) return;
      ranked = rankSensors(p, app.ents, en);
      if (!ent && ranked[0]?.tag) { ent = ranked[0].e.entity_id; drawPreview(); }
      ready(); draw();
    });
    // One Jellyfin source is the answer already.
    if (p.asks === "jellyfin" && ranked.length === 1) ent = ranked[0].e.entity_id;
  }

  /* Guest Wi-Fi: the network goes into the code, so it's asked for. */
  if (p.needs === "wifi") {
    const inp = (key, label, attrs) => {
      const x = h("input", { class: "inp", value: wifi[key], autocomplete: "off", spellcheck: "false", "aria-label": label, ...attrs });
      x.addEventListener("input", () => { wifi[key] = x.value; ready(); drawPreview(); });
      return x;
    };
    const sec = select([["WPA", "WPA, WPA2 or WPA3"], ["WEP", "WEP"], ["nopass", "None, it's open"]], wifi.auth, (v) => { wifi.auth = v; pw.disabled = v === "nopass"; drawPreview(); }, { "aria-label": "Security" });
    const pw = inp("password", "Password", { type: "text" });
    node.append(h("div", { class: "stepsec" }, h("h3", { class: "slab", text: "Your guest network" }),
      h("div", { class: "group" },
        h("label", { class: "gr" }, h("span", { class: "gl", text: "Network name" }), inp("ssid", "Network name", { placeholder: "As your phone lists it", maxlength: "32" })),
        h("label", { class: "gr" }, h("span", { class: "gl" }, "Password", h("small", { text: "In the code, so guests don't type it" })), pw),
        h("div", { class: "gr" }, h("span", { class: "gl", text: "Security" }), sec)),
      h("p", { class: "fnote", text: "The page shows the network's name; the password stays in the code." })));
  }

  ready(); drawPreview();
  return {
    node,
    focus: () => setTimeout(() => (node.querySelector('[role="radio"][aria-checked="true"], .stepsec input') || addBtn).focus({ preventScroll: true })),
    dispose: () => { skip?.remove(); addBtn.remove(); },
  };
}
