// One system for everything that floats: popovers anchored to a control,
// sheets for bigger jobs, menus, and the toast. Plus the form controls the
// inspector and the sheets are built from.

import { h, icon, uid } from "./util.js";

const layer = () => document.getElementById("layer");
let open = [];          // stack of {node, close}

function trapKeys(node, close) {
  node.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); return; }
    if (e.key === "Tab") {
      const f = [...node.querySelectorAll("button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex='-1'])")].filter((x) => x.offsetParent !== null);
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
    if (node.classList.contains("menu") && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      e.preventDefault();
      const items = [...node.querySelectorAll(".mi:not([disabled])")];
      const i = items.indexOf(document.activeElement);
      const n = items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length];
      if (n) n.focus();
    }
  });
}

export function closeAll() { [...open].reverse().forEach((o) => o.close()); }
export function isOpen() { return open.length > 0; }

function place(pop, anchor, align, at) {
  const vw = window.innerWidth, vh = window.innerHeight;
  const r = at ? { left: at.x, right: at.x, top: at.y, bottom: at.y, width: 0 } : anchor.getBoundingClientRect();
  const pw = Math.min(pop.offsetWidth, vw - 16);
  let left = align === "right" ? r.right - pw : align === "left" ? r.left : r.left + r.width / 2 - pw / 2;
  left = Math.max(8, Math.min(vw - pw - 8, left));
  let top = r.bottom + 6;
  const ph = pop.offsetHeight;
  if (top + ph > vh - 8 && r.top - ph - 6 > 8) { top = r.top - ph - 6; pop.style.transformOrigin = "bottom center"; }
  pop.style.left = left + "px";
  pop.style.top = top + "px";
  pop.style.maxHeight = Math.max(160, (top > r.top ? vh - top : r.top) - 14) + "px";
}

export function popover(anchor, build, opts = {}) {
  closeAll();
  const returnTo = document.activeElement;
  const pop = h("div", { class: "pop " + (opts.cls || ""), role: opts.role || "dialog", "aria-label": opts.label || null });
  const close = () => {
    pop.remove();
    document.removeEventListener("pointerdown", outside, true);
    window.removeEventListener("resize", close);
    open = open.filter((o) => o.node !== pop);
    if (anchor && anchor.setAttribute) anchor.setAttribute("aria-expanded", "false");
    if (returnTo && returnTo.isConnected) returnTo.focus({ preventScroll: true });
    opts.onClose && opts.onClose();
  };
  const outside = (e) => { if (!pop.contains(e.target) && !(anchor && anchor.contains && anchor.contains(e.target))) close(); };
  build(pop, close);
  layer().append(pop);
  place(pop, anchor, opts.align || "center", opts.at);
  trapKeys(pop, close);
  if (anchor && anchor.setAttribute) anchor.setAttribute("aria-expanded", "true");
  open.push({ node: pop, close });
  setTimeout(() => document.addEventListener("pointerdown", outside, true));
  window.addEventListener("resize", close);
  requestAnimationFrame(() => { const f = pop.querySelector(opts.focus || "input, .mi:not([disabled]), button"); if (f) f.focus({ preventScroll: true }); });
  return close;
}

export function menu(anchor, items, opts = {}) {
  return popover(anchor, (pop, close) => {
    for (const it of items) {
      if (!it) continue;
      if (it === "sep") { pop.append(h("div", { class: "msep", role: "separator" })); continue; }
      if (it.heading) { pop.append(h("div", { class: "mlab", text: it.heading })); continue; }
      pop.append(h("button", { class: "mi" + (it.danger ? " danger" : ""), role: it.checked !== undefined ? "menuitemcheckbox" : "menuitem",
        "aria-checked": it.checked !== undefined ? String(!!it.checked) : null, disabled: !!it.disabled,
        onclick: () => { close(); it.run(); } },
        it.icon ? icon(it.icon, "sm") : h("span", { class: "ic sm" }),
        it.sub ? h("span", { class: "ml two" }, h("span", { text: it.label }), h("small", { text: it.sub })) : h("span", { class: "ml", text: it.label }),
        it.checked ? icon("check", "sm") : null, it.kb ? h("span", { class: "kb", text: it.kb }) : null));
    }
  }, { cls: "menu", role: "menu", label: opts.label, align: opts.align || "left", at: opts.at });
}

export function sheet(title, build, opts = {}) {
  closeAll();
  const returnTo = document.activeElement;
  const scrim = h("div", { class: "scrim" });
  const titleId = "t" + uid();
  const node = h("div", { class: "sheet " + (opts.cls || ""), role: "dialog", "aria-modal": "true", "aria-labelledby": titleId });
  const close = (why) => {
    if (opts.beforeClose && opts.beforeClose(why) === false) return;
    node.classList.add("leaving"); scrim.classList.add("leaving");
    setTimeout(() => { node.remove(); scrim.remove(); }, 180);
    open = open.filter((o) => o.node !== node);
    document.getElementById("app").removeAttribute("inert");
    if (returnTo && returnTo.isConnected) returnTo.focus({ preventScroll: true });
    opts.onClose && opts.onClose(why);
  };
  scrim.addEventListener("click", () => { if (!opts.modal) close("dismiss"); });
  const head = h("div", { class: "sheet-head" },
    opts.back ? h("button", { class: "btn icon", "aria-label": "Back", onclick: opts.back }, icon("back")) : null,
    h("h2", { id: titleId, text: title }),
    opts.modal ? null : h("button", { class: "btn icon", "aria-label": "Close", onclick: () => close("dismiss") }, icon("close")));
  node.append(head);
  build(node, close, head);
  layer().append(scrim, node);
  document.getElementById("app").setAttribute("inert", "");
  trapKeys(node, () => { if (!opts.modal) close("dismiss"); });
  open.push({ node, close });
  requestAnimationFrame(() => { const f = node.querySelector(opts.focus || ".sheet-body input, .sheet-body button, .sheet-foot .btn.primary, button"); if (f) f.focus({ preventScroll: true }); });
  return close;
}

/* ---------- toast ---------- */
let toastT = null;
export function toast(text, action) {
  const t = document.getElementById("toast");
  t.replaceChildren(h("span", { text }));
  if (action) t.append(h("button", { text: action.label, onclick: () => { action.run(); t.classList.remove("on"); } }));
  t.classList.add("on");
  clearTimeout(toastT);
  toastT = setTimeout(() => t.classList.remove("on"), action ? 7000 : 3600);
}

/* ---------- form controls ---------- */
export function field(label, control, opts = {}) {
  const id = control.id || (control.id = "f" + uid());
  const lab = /INPUT|SELECT|TEXTAREA/.test(control.tagName) ? h("label", { for: id, text: label }) : h("span", { class: "lab", text: label, id: id + "-l" });
  if (!/INPUT|SELECT|TEXTAREA/.test(control.tagName)) control.setAttribute("aria-labelledby", id + "-l");
  // A label too long for two lines in its column takes the row, its control under it (editor.css, rows).
  const long = !opts.wide && textWidth(label, `12.5px ${getComputedStyle(document.body).fontFamily}`) > LABEL_TWO_LINES;
  return h("div", { class: "field" + (opts.wide ? " wide" : long ? " long" : "") }, lab, control, opts.note ? h("div", { class: "fnote", text: opts.note }) : null);
}
// What fits in two lines of the inspector's 92 px label column, with room for where words break.
export const LABEL_TWO_LINES = 156;
export function input(value, onChange, attrs = {}) {
  const i = h("input", { class: "inp", value: value ?? "", autocomplete: "off", spellcheck: "false", ...attrs });
  let last = i.value;
  const fire = () => { if (i.value !== last) { last = i.value; onChange(i.value); } };
  i.addEventListener("change", fire);
  i.addEventListener("keydown", (e) => { if (e.key === "Enter" && i.tagName !== "TEXTAREA") { fire(); i.blur(); } if (e.key === "Escape") { i.value = last; i.blur(); } });
  return i;
}
export function textarea(value, onChange, attrs = {}) {
  const t = h("textarea", { class: "inp code", rows: "3", spellcheck: "false", ...attrs });
  t.value = value ?? "";
  t.addEventListener("change", () => onChange(t.value));
  return t;
}
export function number(value, onChange, attrs = {}) {
  return input(value, (v) => onChange(v === "" ? "" : Number(v)), { type: "number", inputmode: "decimal", ...attrs });
}
export function select(options, value, onChange, attrs = {}) {
  const s = h("select", { class: "inp", ...attrs }, ...options.map(([v, l]) => h("option", { value: String(v), text: l })));
  s.value = String(value ?? options[0]?.[0] ?? "");
  s.addEventListener("change", () => onChange(s.value));
  return s;
}
/* A row never squeezes its control or wraps its label past two lines (the user's call, 21 Oct):
   every row (.field, .gr) is a wrapping flex row in editor.css, so a control that doesn't fit
   beside its label goes under it, full width. Each control asks for the width it needs; a
   segmented control's is its choices at equal widths, the widest deciding (`segNeed`), set
   as --need when it's made. Padding 6 each side, gap 2, frame 2. */
export const segNeed = (widths) => widths.length * (Math.max(0, ...widths) + 12) + 2 * (widths.length - 1) + 4;
export const segFits = (widths, room) => segNeed(widths) <= room;
// The way back (0.17's): measured live with a ResizeObserver, moving a .field to .stack. Off
// while the row rule proves itself; turning it on again needs nothing else.
const SEG_LIVE = false;
let measurer = null;
function textWidth(text, font) {
  measurer ||= document.createElement("canvas").getContext("2d");
  measurer.font = font;
  return Math.ceil(measurer.measureText(text).width);
}
const fitting = typeof ResizeObserver === "function" ? new ResizeObserver((entries) => {
  for (const { target: c } of entries) {
    const f = c.parentElement;
    if (!f || !f.classList.contains("field")) continue;
    const lab = f.firstElementChild, b = c.querySelector("button");
    if (!b || lab === c) continue;
    const cs = getComputedStyle(b), font = `600 ${cs.fontSize} ${cs.fontFamily}`;     // the chosen one is bolder
    const widths = [...c.children].map((x) => (x.querySelector(".ic") ? 16 : 0) + (x.textContent ? textWidth(x.textContent, font) + (x.querySelector(".ic") ? 4 : 0) : 0));
    // The label's column as it is beside the control (stacked, the label spans the row).
    if (!f.classList.contains("stack")) c.labCol = lab.getBoundingClientRect().width + (parseFloat(getComputedStyle(f).columnGap) || 8);
    f.classList.toggle("stack", !f.classList.contains("wide") && !segFits(widths, f.clientWidth - (c.labCol ?? 100)));
  }
}) : null;

export function seg(options, value, onPick, label) {
  const c = segControl(options, value, onPick, label);
  if (SEG_LIVE) { fitting?.observe(c); return c; }
  const font = `600 12.5px ${getComputedStyle(document.body).fontFamily}`;       // the chosen one is bolder
  c.style.setProperty("--need", segNeed(options.map(([, l, ic]) => (ic ? 16 : textWidth(String(l), font)))) + "px");
  return c;
}
function segControl(options, value, onPick, label) {
  return h("div", { class: "segc", role: "radiogroup", "aria-label": label },
    ...options.map(([v, l, ic]) => h("button", { role: "radio", "aria-checked": String(String(value) === String(v)), "aria-label": ic ? l : null, title: ic ? l : null,
      onclick: () => onPick(v),
      onkeydown: (e) => {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        e.preventDefault();
        const i = options.findIndex(([x]) => String(x) === String(value));
        const n = options[(i + (e.key === "ArrowRight" ? 1 : -1) + options.length) % options.length];
        onPick(n[0]);
      } }, ic ? icon(ic, "sm") : l)));
}
export function toggle(on, onChange, label) {
  const b = h("button", { class: "switch", role: "switch", "aria-checked": String(!!on), "aria-label": label });
  b.addEventListener("click", () => { const v = b.getAttribute("aria-checked") !== "true"; b.setAttribute("aria-checked", String(v)); onChange(v); });
  return b;
}
export function toggleRow(label, on, onChange, note) {
  return h("div", { class: "trow" }, h("span", { class: "tl" }, label, note ? h("small", { text: note }) : null), toggle(on, onChange, label));
}
export function section(title, ...kids) {
  return h("section", { class: "isec" }, title ? h("h3", { class: "slab", text: title }) : null, ...kids);
}
export function linkButton(label, onClick, attrs = {}) {
  return h("button", { class: "linkbtn", onclick: onClick, ...attrs }, label);
}
