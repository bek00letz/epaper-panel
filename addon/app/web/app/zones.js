// A world clock's cities (the world_clock widget's `zones`), picked in place:
// up to four, each a time zone found by its city, its name yours to change,
// in the order you drag them to (or Alt with ↑ and ↓). The same editor serves
// New page's step and the inspector. The time zones are the add-on's
// (GET /api/timezones); how the cities are laid out is the renderer's.

import { h, icon, api } from "./util.js";

let asked = null;
export function timezones() {
  if (!asked) asked = api("api/timezones").then((r) => r.body || { home: "", zones: [] }, () => { asked = null; return { home: "", zones: [] }; });
  return asked;
}
const cityOf = (tz) => String(tz || "").split("/").pop().replace(/_/g, " ");

/* The cities a search finds, best first: a city that starts with it (Tokyo for "tok"), then one with
   a word that does (Ho Chi Minh for "chi"), then any city, region or zone that holds it (Vostok). */
export function findCities(zones, query, most = 60) {
  const s = String(query || "").trim().toLowerCase();
  if (!s) return zones.slice(0, most);
  const rank = (z) => {
    const c = String(z.city || "").toLowerCase();
    if (c.startsWith(s)) return 0;
    if (c.split(/[\s-]+/).some((w) => w.startsWith(s))) return 1;
    return `${c} ${z.region} ${z.tz}`.toLowerCase().includes(s) ? 2 : -1;
  };
  return zones.map((z, i) => [rank(z), i, z]).filter(([r]) => r >= 0).sort((a, b) => a[0] - b[0] || a[1] - b[1]).map(([, , z]) => z).slice(0, most);
}

/* `el.zones`: [{ tz, label }]; tz "" is Home Assistant's own zone, label "" its city. */
export function zonesEditor(el, changed, { most = 4, live = false } = {}) {
  if (!Array.isArray(el.zones) || !el.zones.length) el.zones = [{ tz: "", label: "" }];
  let tz = { home: "", zones: [] }, picking = null;            // picking: a row's index, or "new"
  const box = h("div", { class: "cities" });  // not "zones": that is the canvas's guides
  const save = () => changed();
  const nameOf = (z) => (z.tz ? (tz.zones.find((x) => x.tz === z.tz)?.city || cityOf(z.tz)) : `Here${tz.home ? `, ${cityOf(tz.home)}` : ""}`);

  function move(from, to) {
    if (to < 0 || to >= el.zones.length || to === from) return;
    const [z] = el.zones.splice(from, 1); el.zones.splice(to, 0, z);
    draw(); save();
    box.querySelectorAll(".zgrip")[to]?.focus();
  }

  function picker(onPick) {
    const q = h("input", { type: "search", placeholder: "Search for a city", "aria-label": "Search for a city", autocomplete: "off", spellcheck: "false" });
    const list = h("div", { class: "optlist", role: "listbox", "aria-label": "Cities" });
    const drawList = () => {
      const s = q.value.trim().toLowerCase();
      const found = findCities(tz.zones, s);
      list.replaceChildren(...[
        !s ? h("button", { class: "opt", role: "option", onclick: () => onPick("") }, h("span", { class: "otext" },
          h("span", { class: "o1", text: "Here" }), h("span", { class: "o2 plain", text: `Home Assistant's own${tz.home ? `: ${cityOf(tz.home)}` : ""}` }))) : null,
        ...found.map((z) => h("button", { class: "opt", role: "option", onclick: () => onPick(z.tz) },
          h("span", { class: "otext" }, h("span", { class: "o1", text: z.city }), h("span", { class: "o2 plain", text: z.region })),
          h("span", { class: "ov", text: z.offset ? `UTC ${z.offset}` : "" }))),
      ].filter(Boolean));
      if (!found.length && s) list.append(h("p", { class: "empty-note", text: "No city by that name. Try the nearest big city in the same time zone." }));
    };
    q.addEventListener("input", drawList);
    q.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); const was = picking; picking = null; draw(); refocus(was); } });
    drawList();
    setTimeout(() => q.focus());
    return h("div", { class: "picker zpick", "data-own-esc": "" }, h("div", { class: "search" }, icon("search", "sm"), q), list);
  }

  function row(z, k) {
    const label = h("input", { class: "inp", value: z.label || "", placeholder: nameOf(z), maxlength: "24", autocomplete: "off", spellcheck: "false", "aria-label": `Name for ${nameOf(z)}` });
    label.addEventListener(live ? "input" : "change", () => { z.label = label.value.trim(); save(); });
    const grip = h("button", { class: "btn icon zgrip", "aria-label": `Move ${nameOf(z)}. Drag, or Alt with an arrow key`, title: "Drag to reorder" }, icon("grip", "sm"));
    grip.addEventListener("keydown", (e) => {
      if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) { e.preventDefault(); move(k, k + (e.key === "ArrowUp" ? -1 : 1)); }
    });
    dragToReorder(grip, k);
    const r = h("div", { class: "gr zrow", role: "listitem" }, grip,
      h("button", { class: "btn tinted zcity", "aria-label": `${nameOf(z)}. Change the city`, onclick: () => { picking = picking === k ? null : k; draw(); if (picking == null) refocus(k); } }, nameOf(z)),
      label,
      el.zones.length > 1 ? h("button", { class: "btn icon", "aria-label": `Remove ${nameOf(z)}`, onclick: () => { el.zones.splice(k, 1); picking = null; draw(); save(); } }, icon("close", "sm")) : null);
    return picking === k ? h("div", {}, r, picker((v) => { z.tz = v; picking = null; draw(); save(); refocus(k); })) : r;
  }

  /* Drag a row by its grip: the rows swap as it passes the middle of the next one. */
  function dragToReorder(grip, k) {
    grip.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      const rows = [...box.querySelectorAll(".zrow")], start = e.clientY;
      let at = k;
      try { grip.setPointerCapture(e.pointerId); } catch (_) {}
      rows[k].classList.add("lifted");
      const onMove = (ev) => {
        rows[k].style.transform = `translateY(${ev.clientY - start}px)`;
        const mids = rows.map((r) => { const b = r.getBoundingClientRect(); return b.top + b.height / 2; });
        at = Math.max(0, Math.min(rows.length - 1, mids.filter((m, i) => i !== k && m < ev.clientY).length));
      };
      const up = () => {
        grip.removeEventListener("pointermove", onMove); grip.removeEventListener("pointerup", up); grip.removeEventListener("pointercancel", up);
        rows[k].style.transform = ""; rows[k].classList.remove("lifted");
        move(k, at);
      };
      grip.addEventListener("pointermove", onMove); grip.addEventListener("pointerup", up); grip.addEventListener("pointercancel", up);
    });
  }

  function draw() {
    // replaceChildren() takes nodes only: a null would show as the word "null".
    box.replaceChildren(...[
      h("div", { class: "group zlist", role: "list", "aria-label": "Cities" }, ...el.zones.map(row)),
      picking === "new" ? picker((v) => { el.zones.push({ tz: v, label: "" }); picking = null; draw(); save(); refocus(el.zones.length - 1); }) : null,
      el.zones.length < most && picking !== "new"
        ? h("div", { class: "btnrow" }, h("button", { class: "btn tinted", onclick: () => { picking = "new"; draw(); } }, icon("plus", "sm"), "Add a city"))
        : el.zones.length >= most ? h("p", { class: "fnote", text: `Up to ${most} cities.` }) : null].filter(Boolean));
  }
  /* Back to where the search was opened from: a row's city, or Add a city. */
  const refocus = (was) => (was === "new" ? box.querySelector(".btnrow .btn") : box.querySelectorAll(".zcity")[was])?.focus();
  draw();
  timezones().then((got) => { tz = got; draw(); });
  return box;
}
