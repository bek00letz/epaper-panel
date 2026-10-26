// Sharing pages as a file, both ways (the user's calls, 26 Oct). Share page… (the inspector, a
// tile's menu) and Share all pages… (the device menu) open a sheet that says what goes in the file
// and what stays home, then saves it: nothing is uploaded. Open a file… (New page's footer, or a
// file dropped on the editor) shows the file as a preset's next step in New page: its pictures,
// then the importer's own sensors, Wi-Fi and Jellyfin, asked the way presets ask (setup.js
// SETUPS), then Add page. The add-on writes and checks the file (share.py); share.js fills it in.

import { h, icon, api, pageTitle } from "./util.js";
import { sheet, toast } from "./ui.js";
import { TYPES } from "./elements.js";
import { widget } from "./catalog.js";
import { SETUPS } from "./setup.js";
import { fill, exampleAnswers } from "./share.js";
import { thumbnail } from "./strip.js";

const SHOW_LATE_MS = 300;          // a wait shorter than this shows nothing
const MOST_WORDS = 24;
const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;
const list = (xs) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

/* What a slot is, in the editor's words: the element it's on ("Value", a widget's own field, "Devices")
   or the page's condition. */
function slotWhat(slot) {
  const whats = [];
  for (const u of slot.uses || []) {
    const field = (widget(u.type)?.fields || []).find((f) => f.key === u.key);
    const w = u.type === "page" ? "Shows when" : field?.label && u.key !== "entity" ? field.label : TYPES[u.type]?.name || "";
    if (w && !whats.includes(w)) whats.push(w);
  }
  return list(whats.slice(0, 3)) || "A sensor";
}
const slotPages = (slot) => [...new Set((slot.uses || []).map((u) => u.page).filter(Boolean))];

/* ---------- share: the sheet ---------- */

/* Share `names` (pages of this device, in their order) as one file named after `title`. */
export function openShare(app, names, title) {
  const spec = app.doc.spec, g = app.geometry();
  const several = names.length > 1;
  sheet(several ? "Share all pages" : "Share page", (node, close) => {
    const body = h("div", { class: "sheet-body sharebody" });
    const save = h("button", { class: "btn primary", disabled: true }, icon("share", "sm"), "Save file");
    node.append(body, h("div", { class: "sheet-foot" }, h("span", { class: "spacer" }), h("button", { class: "btn tinted", onclick: () => close() }, "Cancel"), save));

    // The pages as they look here, with your own values: what you're sending.
    const pics = h("div", { class: "sharepics" + (several ? " several" : "") }, ...names.map((n) => {
      const img = h("img", { class: "thumb", alt: "", draggable: "false" });
      requestAnimationFrame(() => thumbnail(app, n, img, spec.pages[n]));
      return h("figure", {}, h("span", { class: "thumbwrap", style: { aspectRatio: `${g.W} / ${g.H}` } }, img),
        several ? h("figcaption", { text: pageTitle(n) }) : null);
    }));
    const said = h("div", { "aria-live": "polite" });
    body.append(pics, said);
    const late = setTimeout(() => said.replaceChildren(h("p", { class: "fnote", text: "Getting it ready…" })), SHOW_LATE_MS);

    let got = null;
    async function prepare() {
      save.disabled = true;
      try {
        const pages = Object.fromEntries(names.map((n) => [n, spec.pages[n]]));
        got = (await api("api/share/export", { method: "POST", body: { pages, rotation: spec.rotation, canvas: `${g.W}x${g.H}`, title } })).body;
      } catch (e) {
        clearTimeout(late);
        said.replaceChildren(h("p", { class: "note bad", role: "alert" }, icon("warn", "sm"), h("span", { text: e.message })),
          h("div", { class: "btnrow" }, h("button", { class: "btn tinted", onclick: prepare }, "Try again")));
        return;
      }
      clearTimeout(late);
      said.replaceChildren(...summary(got));
      said.classList.add("fade");
      save.disabled = false;
      save.focus({ preventScroll: true });
    }
    save.addEventListener("click", () => {
      if (!got) return;
      download(got.name, JSON.stringify(got.file, null, 1));
      close();
      toast(`Saved ${got.name}. Send it however you like: whoever opens it picks their own sensors.`);
    });
    prepare();
  }, { focus: ".sheet-foot .btn.tinted" });
}

/* What's in the file, in plain words: what the other home is asked for, what stays here, and the
   words that go as you wrote them. */
function summary({ file, words }) {
  const slots = file.slots || [];
  const asked = [];
  const sensors = slots.filter((s) => s.kind === "entity");
  if (sensors.length) asked.push(`their own ${sensors.length === 1 ? "sensor" : `${sensors.length} sensors`} (${list(sensors.map(slotWhat).slice(0, 4))}${sensors.length > 4 ? "…" : ""})`);
  if (slots.some((s) => s.kind === "jellyfin")) asked.push("their Jellyfin");
  if (slots.some((s) => s.kind === "wifi")) asked.push("their Wi-Fi network");
  const out = [
    h("h3", { class: "slab", text: "Whoever opens it" }),
    h("p", { class: "fnote", text: asked.length ? `Is asked for ${list(asked)}, the way New page asks.` : "Gets it as it is: it uses nothing of your home's." }),
    h("h3", { class: "slab", text: "Stays here" }),
    h("p", { class: "fnote", text: "Your sensors' names and IDs, your Wi-Fi network and password, places, data sources and keys, and this device's settings." }),
  ];
  if (words.length) {
    const shown = words.slice(0, MOST_WORDS);
    out.push(h("h3", { class: "slab", text: "Goes as you wrote it" }),
      h("ul", { class: "wordchips", "aria-label": "Words in the file" }, ...shown.map((w) => h("li", { text: w })),
        words.length > shown.length ? h("li", { class: "more", text: `${words.length - shown.length} more` }) : null));
  }
  return out;
}

function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const a = h("a", { href: url, download: name, hidden: true });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

/* ---------- open: a file, checked by the add-on ---------- */

const TOO_LARGE = "This file is too large to be a shared page.";

/* A file the person picked or dropped: the add-on's reading of it, or null after saying why not. */
export async function readShared(file) {
  if (!file) return null;
  if (file.size > 1024 * 1024) { toast(TOO_LARGE); return null; }
  let text;
  try { text = await file.text(); } catch (_) { toast("That file couldn't be read. Try saving it again, then open it."); return null; }
  try {
    return (await api("api/share/open", { method: "POST", body: { text } })).body;
  } catch (e) {
    toast(e.status === 413 ? TOO_LARGE : e.message);
    return null;
  }
}

/* A button that opens the file picker for shared pages. */
export function openFileButton(onOpened, attrs = {}) {
  const input = h("input", { type: "file", accept: ".json,application/json", hidden: true, tabindex: "-1" });
  input.addEventListener("change", async () => {
    const f = input.files?.[0];
    input.value = "";                                 // the same file can be opened again
    const opened = await readShared(f);
    if (opened) onOpened(opened);
  });
  return h("span", { class: "filebtn" }, input,
    h("button", { class: "btn tinted", onclick: () => input.click(), ...attrs }, icon("file", "sm"), "Open a file…"));
}

/* ---------- open: its step in New page ---------- */

/* A shared file as a preset's next step: its pictures, then what it needs of yours, the way presets
   ask (SETUPS), then Add page. `add(pages, rotation)` gets the filled pages, placed for this device. */
export function importStep(app, opened, { thumb, foot, add }) {
  const slots = opened.slots || [], pages = opened.pages, several = pages.length > 1;
  const node = h("div", { class: "stepin fade" });
  const changed = () => { ready(); drawPreview(); };
  const pics = h("div", { class: "pv" + (several ? " sharepics several" : "") });
  const caption = h("p", { class: "fnote pvcap", "aria-live": "polite" });

  // What it needs, set up in place: your Jellyfin, your Wi-Fi, your sensors.
  const setups = [];
  const jelly = slots.filter((s) => s.kind === "jellyfin");
  if (jelly.length) setups.push({ slots: jelly, setup: SETUPS.jellyfin({ app, p: {}, changed }), answer: (done) => done.ent || "" });
  for (const s of slots.filter((x) => x.kind === "wifi")) setups.push({ slots: [s], setup: SETUPS.wifi({ app, changed }), answer: (done) => done.extra });
  const sensors = slots.filter((s) => s.kind === "entity");
  if (sensors.length) {
    // Two of the same ("Value", "Value") are numbered in the file's order, and each says what kind it was.
    const whats = sensors.map(slotWhat);
    const nth = (k) => (whats.filter((w) => w === whats[k]).length > 1 ? ` ${whats.slice(0, k + 1).filter((w) => w === whats[k]).length}` : "");
    const kindOf = (s) => [s.device_class.replace(/_/g, " "), s.unit].filter(Boolean).join(", ");
    const parts = sensors.map((s, k) => ({ key: String(s.id), label: whats[k] + nth(k), asks: s.domain, needed: s.needed,
      where: [several ? slotPages(s).map(pageTitle).join(", ") : "", kindOf(s)].filter(Boolean).join(" · ").replace(/^./, (c) => c.toUpperCase()),
      prefer: { device_class: s.device_class ? [s.device_class] : [], units: s.unit ? [s.unit] : [] } }));
    const needed = sensors.filter((s) => s.needed).length;
    const partsNote = !needed ? "Leave one out and pick it later in the inspector."
      : needed === sensors.length ? `A condition or a text on the page needs ${needed === 1 ? "it" : "them"}.`
      : "Needed ones are in a condition or a text. Leave the others out and pick them later in the inspector.";
    setups.push({ slots: sensors, setup: SETUPS.parts({ app, p: { parts, partsOptional: true, partsNote }, changed }), answer: (done, s) => done.extra?.[s.id] || "" });
  }

  const n = pages.length;
  const leadNotes = [h("p", { class: "fnote", text: `Shared from e-Paper Panel${opened.made_with && opened.made_with !== "dev" ? " " + opened.made_with : ""}.` })];
  const g = app.geometry();
  if (opened.canvas !== `${g.W}x${g.H}`) leadNotes.push(h("p", { class: "fnote", text: "Made for another size of device, and placed for this one." }));
  // What it asks of you, in a sentence: "It shows your own sensors and Wi-Fi: pick them below."
  const wifi = slots.filter((s) => s.kind === "wifi");
  const yours = [sensors.length ? (sensors.length === 1 ? "sensor" : "sensors") : "", jelly.length ? "Jellyfin" : "", wifi.length ? "Wi-Fi" : ""].filter(Boolean);
  const asks = sensors.length + (jelly.length ? 1 : 0) + wifi.length;
  const desc = !slots.length ? (several ? "They use nothing of the sender's home, so they come as they are." : "It uses nothing of the sender's home, so it comes as it is.")
    : `${several ? "They show" : "It shows"} your own ${list(yours)}: pick ${asks === 1 ? "it" : "them"} below.`;
  node.append(h("div", { class: "lead" }, h("div", {}, pics, caption), h("div", { class: "leadtext" }, h("p", { class: "desc", text: desc }), ...leadNotes)));
  for (const { setup } of setups) node.append(setup.node);

  const addBtn = h("button", { class: "btn primary", onclick: async () => {
    addBtn.disabled = true;
    const answers = {};
    for (const { slots: ss, setup, answer } of setups) {
      const done = await setup.commit();           // saves what it set up (a Jellyfin); says why if it couldn't
      if (!done) { ready(); return; }
      for (const s of ss) answers[s.id] = answer(done, s);
    }
    add(fill(pages, answers), opened);
  } }, several ? `Add ${n} pages` : "Add page");
  foot.append(addBtn);

  function ready() { addBtn.disabled = !setups.every(({ setup }) => setup.ready()); }
  function drawPreview() {
    // Example values until something of yours is picked, as a preset's step shows them.
    const answers = {};
    let mine = false;
    for (const { slots: ss, setup } of setups) {
      const shown = setup.shows();
      if (!shown.mine) continue;
      mine = true;
      for (const s of ss) answers[s.id] = s.kind === "entity" ? shown.extra?.[s.id] || "" : s.kind === "wifi" ? shown.extra : shown.ent || "";
    }
    const filled = fill(pages, mine ? answers : exampleAnswers(slots));
    const key = "share:" + (mine ? JSON.stringify(answers) : "example") + ":";
    pics.replaceChildren(...filled.map((p, k) => {
      const t = thumb(app, key + k + p.name, p, { example: !mine, from: opened.canvas, cls: several ? "" : "big" });
      return several ? h("figure", {}, t, h("figcaption", { text: pageTitle(p.name) })) : t;
    }));
    caption.textContent = mine ? "With yours." : slots.length ? "Example values. Your page shows yours." : "";
  }
  ready(); drawPreview();
  return {
    node,
    title: several ? `${n} pages` : pageTitle(pages[0].name),
    focus: () => setTimeout(() => (node.querySelector(".stepsec input, .stepsec button") || addBtn).focus({ preventScroll: true })),
    dispose: () => { addBtn.remove(); for (const { setup } of setups) setup.dispose?.(); },
  };
}
