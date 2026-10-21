// What a countdown counts to, picked in place: a date of yours, or your bins
// and their days. The same editors serve New page's step and the inspector,
// on the element's own fields (render/countdown.py reads them; nothing here
// works out "days until", so the canvas and the panel always agree).

import { h, icon } from "./util.js";
import { select, toggle } from "./ui.js";

const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
const row = (label, sub, ctl) => h("label", { class: "gr" }, h("span", { class: "gl" }, label, sub ? h("small", { text: sub }) : null), ctl);

/* `live`: answer every keystroke (New page's preview); otherwise on change, so
   the inspector, which redraws on each saved change, doesn't lose the field. */
function inp(value, onChange, attrs, live) {
  const x = h("input", { class: "inp", value: value ?? "", autocomplete: "off", spellcheck: "false", ...attrs });
  x.addEventListener(live ? "input" : "change", () => onChange(x.value));
  return x;
}

/* When the page starts showing (render/countdown.py `show_before`, in days): right away, or not
   until it's near, so a countdown set six months ahead can wait. */
export const SHOW_BEFORE = [[0, "Right away"], [1, "1 day before"], [3, "3 days before"], [7, "1 week before"], [14, "2 weeks before"],
  [30, "1 month before"], [90, "3 months before"], [180, "6 months before"]];
const startsShowing = (el, changed, sub) => row("Starts showing", sub, select(SHOW_BEFORE, el.show_before || 0,
  (v) => { el.show_before = Number(v) || 0; changed(); }, { "aria-label": "Starts showing" }));

/* A date: a name, the day, a time if you like, and whether it comes round every year. */
export function dateEditor(el, changed, { live = false } = {}) {
  const [d0, t0] = String(el.at || "").split("T");
  let day = d0 || "", time = (t0 || "").slice(0, 5);
  const save = () => { el.at = day ? day + (time ? `T${time}` : "") : ""; changed(); };
  return h("div", { class: "group" },
    row("What it's for", null, inp(el.name, (v) => { el.name = v; changed(); }, { placeholder: "Holiday", maxlength: "40", "aria-label": "What it's for" }, live)),
    row("Date", null, inp(day, (v) => { day = v; save(); }, { type: "date", "aria-label": "Date" }, live)),
    row("Time", "Leave it empty for the whole day", inp(time, (v) => { time = v; save(); }, { type: "time", "aria-label": "Time" }, live)),
    row("Every year", "Birthdays and anniversaries come round again; otherwise it's marked Passed after the day",
      toggle(!!el.yearly, (v) => { el.yearly = v; changed(); }, "Every year")),
    startsShowing(el, changed, "Until then the panel leaves the page out"));
}

export const EVERY = [[1, "Every week"], [2, "Every 2 weeks"], [3, "Every 3 weeks"], [4, "Every 4 weeks"]];
export const CLOSE_TO = [["noon", "Tomorrow, then Today until noon"], ["midnight", "Tomorrow, then Today until midnight"], ["days", "Numbers only: 1 day, 0 days"]];

/* Bins: each with its name, its next collection and how often it comes.
   Alternating bins are two bins every 2 weeks, a week apart. */
export function binsEditor(el, changed, { live = false } = {}) {
  if (!Array.isArray(el.bins) || !el.bins.length) el.bins = [{ name: "", from: "", every: 1 }];
  const box = h("div", { class: "binlist" });
  const draw = () => {
    box.replaceChildren(...el.bins.map((b, k) => h("div", { class: "group bin" },
      row("Bin", null, h("div", { class: "inline" }, inp(b.name, (v) => { b.name = v; changed(); }, { placeholder: k ? "General waste" : "Recycling", maxlength: "30", "aria-label": `Bin ${k + 1} name` }, live),
        el.bins.length > 1 ? h("button", { class: "btn icon", "aria-label": `Remove ${b.name || `bin ${k + 1}`}`, onclick: (e) => { e.preventDefault(); el.bins.splice(k, 1); draw(); changed(); } }, icon("close", "sm")) : null)),
      row("Next collection", null, inp(b.from, (v) => { b.from = v; changed(); }, { type: "date", min: today(), "aria-label": `${b.name || `Bin ${k + 1}`}: next collection` }, live)),
      row("How often", null, select(EVERY, b.every || 1, (v) => { b.every = Number(v); changed(); }, { "aria-label": `${b.name || `Bin ${k + 1}`}: how often` })))),
    h("div", { class: "btnrow" }, h("button", { class: "btn tinted", disabled: el.bins.length >= 6, onclick: () => {
      const last = el.bins[el.bins.length - 1];
      el.bins.push({ name: "", from: "", every: last?.every || 1 });
      draw(); changed();
      box.querySelector(`[aria-label="Bin ${el.bins.length} name"]`)?.focus();
    } }, icon("plus", "sm"), "Add a bin")),
    h("div", { class: "group" }, row("Close to the day", null, select(CLOSE_TO, el.today_until || "noon", (v) => { el.today_until = v; changed(); }, { "aria-label": "Close to the day" })),
      startsShowing(el, changed, "Before each collection; until then the panel leaves the page out")));
  };
  draw();
  return box;
}

/* Whether it has what it needs to count. */
export const ready = (el) => (el.to === "bins" ? (el.bins || []).some((b) => b.from) : !!String(el.at || "").slice(0, 10));
