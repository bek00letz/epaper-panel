// The New page sheet: one shelf per group that slides sideways, your own
// presets first, a search, and "+ Blank page" pinned in the footer. Picking a
// preset opens its next step in place: its look (style, league or series),
// what it shows, and anything it needs set up first. The shelves stay behind
// it, scrolled where they were, so Back returns to the same spot.

import { h, icon, api, clone, slug, prefs } from "./util.js";
import { sheet, toast } from "./ui.js";
import { syncDynamicGridShowIf } from "./conditions.js";
import { reflowPageElements } from "./legacy.js";
import { PRESETS as ALL_PRESETS, GROUPS, forDevice, sleepsBetweenUpdates, staleNote, presetChangesEvery, lookOf, pageFor, examplePage, pageName, search, rankSensors, fitToCanvas } from "./presets.js";
import { thumbnail } from "./strip.js";
import { slider } from "./slider.js";
import { setupStep } from "./setup.js";

const UNITS = { Style: ["style", "styles"], League: ["league", "leagues"], Series: ["series", "series"] };
const count = (p) => (p.sub ? p.sub : p.looks.length > 1 && UNITS[p.choose || "Style"] ? `${p.looks.length} ${UNITS[p.choose || "Style"][1]}` : "");
// Something to pick or set up before the page exists; otherwise a click adds it.
const hasStep = (p) => p.looks.length > 1 || !!p.asks || !!p.needs;

/* A thumbnail, sized for the device: wide screens fill the card, tall ones
   keep to a shelf's height. `example` draws it with the add-on's example
   values, never the person's own. */
function thumb(app, key, page, { example = false, fit = true, cls = "" } = {}) {
  const g = app.geometry();
  const img = h("img", { class: "thumb", alt: "", "data-thumb": key, draggable: "false" });
  // Built-in presets are drawn for the 5.79" and fitted to this device; your own are as you saved them.
  const fitted = fit ? { ...page, elements: fitToCanvas(page.elements || [], g, reflowPageElements) } : page;
  requestAnimationFrame(() => thumbnail(app, key, img, fitted, { example }));
  return h("span", { class: "thumbwrap " + cls, style: { aspectRatio: `${g.W} / ${g.H}` } }, img);
}

export function openPresets(app) {
  const g = app.geometry();
  // What this device can show well: a Date, not a Clock, on one that sleeps between updates.
  const PRESETS = ALL_PRESETS.map((p) => forDevice(p, sleepsBetweenUpdates(app.screen)));
  const tall = g.W / g.H < 1;
  let query = "", step = null;

  sheet("New page", (node, close, head) => {
    node.classList.add("npsheet");
    node.classList.toggle("tallcards", tall);
    node.style.setProperty("--aspect", String(g.W / g.H));
    const title = head.querySelector("h2");
    const back = h("button", { class: "btn icon", "aria-label": "Back to all presets", hidden: true, onclick: () => leave() }, icon("back"));
    head.prepend(back);
    const q = h("input", { type: "search", placeholder: "Search presets", "aria-label": "Search presets", autocomplete: "off", spellcheck: "false" });
    const search = h("label", { class: "search sheetsearch" }, icon("search", "sm"), q);
    title.after(search);

    const shelves = h("div", { class: "shelves" });
    const results = h("div", { class: "results", hidden: true });
    const stepBox = h("div", { class: "step", hidden: true });
    const body = h("div", { class: "sheet-body shelfbody" }, shelves, results, stepBox);
    const blank = h("button", { class: "btn tinted blankbtn", onclick: () => { close(); app.addPage("untitled", { tier: "rotate", elements: [] }); } }, icon("plus", "sm"), "Blank page");
    const foot = h("div", { class: "sheet-foot" }, blank, h("span", { class: "spacer" }));
    node.append(body, foot);

    const yours = () => app.doc.spec.custom_presets || [];
    function card(p) {
      // Noted, never hidden: on a device that sleeps, what changes faster than it updates says how old it can be.
      const stale = staleNote(presetChangesEvery(p), app.screen, { short: true });
      const look = lookOf(p, 0), sub = stale || count(p) || (p.was ? `Was “${p.was}”` : "");
      return h("button", { class: "pbtn", "aria-label": `${p.title}${count(p) ? `, ${count(p)}` : ""}. ${p.desc}${stale ? " " + staleNote(presetChangesEvery(p), app.screen) : ""}`, onclick: () => pick(p) },
        thumb(app, `preset:${look.id}:example`, examplePage(p, look), { example: true }),
        h("span", { class: "pt", text: p.title }), h("span", { class: "sub", text: sub || " ", "aria-hidden": "true" }));
    }
    function ownCard(cp, k) {
      const name = cp.title || cp.name;
      return h("div", { class: "pcard" },
        h("button", { class: "pbtn", "aria-label": `${name}. ${cp.desc || "One of yours."}`, onclick: () => {
          close(); app.addPage(cp.id || "page", { tier: cp.tier || "rotate", show_if: cp.show_if || undefined, elements: clone(cp.elements || []) });
        } }, thumb(app, "preset:custom" + k, { elements: cp.elements || [] }, { fit: false }), h("span", { class: "pt", text: name }), h("span", { class: "sub", text: cp.desc || " " })),
        h("button", { class: "btn icon pdel", "aria-label": `Delete the preset ${name}`, onclick: () => {
          app.doc.spec.custom_presets.splice(k, 1); app.doc.commit(); close();
          toast(`Deleted the preset ${name}.`, { label: "Undo", run: () => app.doc.undo() });
        } }, icon("close", "sm")));
    }

    function shelf(id, name, cards) {
      // Each card sits in a list item, so it stays a button to VoiceOver.
      const row = h("div", { class: "row", role: "list", "aria-label": name }, ...cards.map((c) => (c.classList.contains("pcard") ? (c.setAttribute("role", "listitem"), c) : h("div", { role: "listitem" }, c))));
      const wrap = slider(row, { name });
      // Arrow keys move along the shelf; Tab moves on to the next one.
      row.addEventListener("keydown", (e) => {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        const items = [...row.children].map((c) => c.querySelector(".pbtn") || c);
        const i = items.findIndex((b) => b === document.activeElement);
        const next = items[i + (e.key === "ArrowRight" ? 1 : -1)];
        if (i < 0 || !next) return;
        e.preventDefault();
        next.focus({ preventScroll: true });
        next.scrollIntoView({ inline: "nearest", block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      });
      const hid = "shelf-" + id;
      return h("section", { class: "shelf", "aria-label": `${name}, ${cards.length} ${cards.length === 1 ? "preset" : "presets"}` },
        h("div", { class: "shelf-head" }, h("h3", { id: hid, text: name }), h("span", { class: "count", "aria-hidden": "true", text: `(${cards.length})` })),
        wrap);
    }

    function drawShelves() {
      const mine = yours();
      // replaceChildren() takes nodes only: a null would show as the word "null".
      shelves.replaceChildren(...[
        mine.length ? shelf("yours", "Yours", mine.map(ownCard)) : null,
        ...GROUPS.map(([id, name]) => {
          const list = PRESETS.filter((p) => p.group === id);
          return list.length ? shelf(id, name, list.map(card)) : null;
        })].filter(Boolean));
    }
    function drawResults() {
      const s = query.trim().toLowerCase();
      const hits = search(s, PRESETS);
      const mine = yours().map((cp, k) => [cp, k]).filter(([cp]) => `${cp.title || cp.name} ${cp.desc || ""}`.toLowerCase().includes(s));
      const n = hits.length + mine.length;
      results.replaceChildren(n
        ? h("div", {}, h("p", { class: "results-head", role: "status", text: `${n} ${n === 1 ? "preset" : "presets"}` }),
          h("div", { class: "presetgrid fade" }, ...mine.map(([cp, k]) => ownCard(cp, k)), ...hits.map(card)))
        : h("div", { class: "empty", role: "status" }, h("b", { text: "No presets match" }), h("span", { text: "Try another word, or start from a blank page." })));
    }
    q.addEventListener("input", () => {
      query = q.value;
      const searching = !!query.trim();
      shelves.hidden = searching; results.hidden = !searching;
      if (searching) drawResults();
    });

    function pick(p) {
      if (!hasStep(p)) { close(); add(p, lookOf(p, 0), ""); return; }
      step = setupStep(app, p, {
        thumb, add: (look, ent, extra) => { close(); add(p, look, ent, extra); },
        foot, initialLook: prefs.get("look_" + p.id, 0),
        rememberLook: (i) => prefs.set("look_" + p.id, i),
      });
      stepBox.replaceChildren(step.node);
      shelves.hidden = results.hidden = true; stepBox.hidden = false;
      back.hidden = false; search.hidden = true; blank.hidden = true; node.classList.add("stepping");
      title.textContent = p.title;
      body.scrollTop = 0;
      step.focus();
    }
    function leave() {
      if (!step) return;
      step.dispose(); step = null;
      stepBox.hidden = true; stepBox.replaceChildren();
      shelves.hidden = !!query.trim(); results.hidden = !query.trim();
      back.hidden = true; search.hidden = false; blank.hidden = false; node.classList.remove("stepping");
      title.textContent = "New page";
      (shelves.hidden ? results : shelves).classList.add("fade");
      setTimeout(() => q.focus({ preventScroll: true }));
    }
    // Esc in a preset's step goes back to the shelves; on the shelves it closes.
    node.addEventListener("keydown", (e) => { if (e.key === "Escape" && step) { e.preventDefault(); e.stopImmediatePropagation(); leave(); } }, true);

    drawShelves();
  }, { cls: "wide tall", focus: "input[type=search]" });

  function add(p, look, ent, extra) {
    const page = pageFor(p, look, ent, extra);
    page.elements = fitToCanvas(page.elements, g, reflowPageElements);
    if (page.tier === "when") syncDynamicGridShowIf(page);
    const entName = ent ? app.entMap.get(ent)?.name : "";
    app.addPage(slug(pageName(p, look, ent, entName, extra)) || p.id, page);
  }
}

