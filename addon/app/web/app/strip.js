// The page strip under the canvas. It is the rotation: tiles in the order the
// panel shows them, a page twice if it's in twice, dragged to reorder. Pages
// left out of the rotation and alert pages follow, set apart. At its head,
// the panel's status, which opens "Now on the panel".

import { h, icon, api, pageTitle, span, seconds } from "./util.js";
import { describe, parseShowIf, evaluate } from "./conditions.js";

/* Thumbnails come from the same renderer as everything else, one at a time,
   cached by what the page contains. */
const thumbCache = new Map();
let queue = [], running = false;
// `example`: drawn with the add-on's example values (api/example), never Home Assistant's (New page's presets).
export function thumbnail(app, name, img, override, { example = false } = {}) {
  const page = override || app.doc.spec.pages[name];
  if (!page) return;
  const key = JSON.stringify([page, app.doc.spec.orientation, app.doc.spec.display, name, example]);
  const hit = thumbCache.get(key);
  if (hit) { img.src = hit; img.classList.add("ready"); return; }
  queue = queue.filter((q) => q.img.isConnected && q.img !== img);
  queue.push({ key, page, name, img, example });
  pump(app);
}
async function pump(app) {
  if (running) return;
  running = true;
  while (queue.length) {
    const job = queue.shift();
    if (!job.img.isConnected) continue;
    try {
      // An example is drawn by api/example: built-in example values, never Home Assistant's or the person's.
      const r = await api(job.example ? "api/example" : "api/preview", { method: "POST", raw: true, body: { page: job.page, label: job.name.replace(/^preset:(__blank)?/, "").split(":")[0], orientation: Number(app.doc.spec.orientation || 0), distance: 0, display: app.doc.spec.display } });
      const url = URL.createObjectURL(await r.blob());
      thumbCache.set(job.key, url);
      if (thumbCache.size > 80) { const [k, u] = thumbCache.entries().next().value; URL.revokeObjectURL(u); thumbCache.delete(k); }
      document.querySelectorAll(`img[data-thumb="${CSS.escape(job.name)}"]`).forEach((im) => { im.src = url; im.classList.add("ready"); });
    } catch (_) { /* the tile keeps its blank paper */ }
  }
  running = false;
}

export function statusSummary(app) {
  const s = app.status || {}, doc = app.doc;
  const liveCount = (s.pages || []).length;
  let tone = "ok", line1 = "Up to date";
  if (doc.saving === "error") { tone = "bad"; line1 = "Changes not saved"; }
  else if (app.sending) { tone = "wait"; line1 = "Sending…"; }
  else if (doc.dirty) { tone = "wait"; line1 = "Not sent yet"; }
  else if (s.error) { tone = "bad"; line1 = "Page didn't render"; }
  else if (s.panel_link?.pending_refresh) { tone = "wait"; line1 = "Panel not updated yet"; }
  if (s.active_alert) line1 = doc.dirty ? line1 : "Alert showing";
  if (app.device?.sleep && !doc.dirty) line1 = "Asleep";
  const t = app.screen?.timing;
  const pace = !t ? "" : t.always_on ? ` · ${seconds(t.rotate_seconds).replace(" seconds", " s")}` : ` · every ${span(t.update_minutes * t.rotate_updates).replace(/ minutes?/, " min")}`;
  const line2 = !s.pages ? "Checking the panel…" : liveCount ? `${liveCount} rotating${pace}` : "No pages rotating";
  return { tone, line1, line2 };
}

export function renderStrip(app) {
  const doc = app.doc, spec = doc.spec;
  const strip = h("div", { class: "strip" });
  const { tone, line1, line2 } = statusSummary(app);
  const head = h("button", { class: "stathead", "aria-label": `Now on the panel: ${line1}. ${line2}`, "aria-haspopup": "dialog" },
    h("span", { class: "l1" }, h("span", { class: "led " + tone }), h("span", { text: line1 })), h("span", { class: "l2", text: line2 }));
  head.addEventListener("click", () => app.openStatus(head));
  // Status and New page share the front of the strip, so neither scrolls away.
  strip.append(h("div", { class: "stripfront" }, head,
    h("button", { class: "newpage", title: "A new page, from a preset or blank", onclick: () => app.openPresets() }, icon("plus", "sm"), h("span", { text: "New page" }))));

  const vertical = app.stripVertical();
  const list = h("div", { class: "tiles", role: "listbox", "aria-label": `Rotation. Drag to reorder; Alt with an arrow key moves the focused page`, "aria-orientation": vertical ? "vertical" : "horizontal" });
  const seen = new Set();
  const slots = spec.rotation.map((n, i) => {
    const again = seen.has(n); seen.add(n);
    return tile(app, n, { again, slot: i });
  }).filter(Boolean);
  slots.forEach((t) => list.append(t));
  reorderable(list, slots, (from, to) => {
    const r = spec.rotation; const [x] = r.splice(from, 1); r.splice(to > from ? to - 1 : to, 0, x);
    doc.commit();
    app.say(`Moved ${pageTitle(x)} to place ${Math.min(to > from ? to : to + 1, r.length)} of ${r.length}.`);
    requestAnimationFrame(() => { const t = app.el.strip.querySelectorAll(".tiles .tile")[to > from ? to - 1 : to]; if (t) t.focus(); });
  }, (i) => doc.openPage(spec.rotation[i]));

  const out = Object.keys(spec.pages).filter((n) => !spec.rotation.includes(n) && spec.pages[n].tier !== "alert");
  const alerts = Object.keys(spec.pages).filter((n) => spec.pages[n].tier === "alert");
  if (out.length) {
    list.append(h("span", { class: "groupsep", role: "presentation" }), h("span", { class: "grouplab", text: "Not in rotation" }));
    out.forEach((n) => { const t = tile(app, n, { out: true }); t.addEventListener("click", () => doc.openPage(n)); list.append(t); });
  }
  if (alerts.length) {
    list.append(h("span", { class: "groupsep", role: "presentation" }), h("span", { class: "grouplab", text: "Alerts" }));
    alerts.forEach((n) => { const t = tile(app, n, {}); t.addEventListener("click", () => doc.openPage(n)); list.append(t); });
  }
  strip.append(list);
  return strip;
}

function tile(app, n, { again, out }) {
  const doc = app.doc, p = doc.spec.pages[n];
  if (!p) return null;
  const live = (app.status?.pages || []).includes(n);
  let sub = "Shows always", badge = null, dim = !!again || !!out;
  if (p.tier === "when") {
    const parsed = parseShowIf(p.show_if);
    const holds = evaluate(parsed, app.entMap);
    const showing = holds === null ? live : holds;
    sub = showing ? "Showing now" : "Hidden now";
    badge = h("span", { class: "badge when", text: "when" });
    if (!showing) dim = true;
  }
  if (p.tier === "alert") { sub = p.ends === "until" ? "Alert · until something happens" : `Alert · holds ${p.hold_minutes || 10} min`; badge = h("span", { class: "badge alert", text: "alert" }); }
  if (again) sub = "Again";
  if (out) sub = "Not in rotation";
  const img = h("img", { class: "thumb", alt: "", "data-thumb": n, draggable: "false" });
  const t = h("button", { class: "tile" + (dim ? " dim" : ""), role: "option", "aria-selected": String(n === doc.cur && !again), "aria-current": n === doc.cur && !again ? "page" : null,
    "aria-label": `${pageTitle(n)}. ${sub}${p.tier === "when" ? ". " + describe(p.show_if, app.entMap).text : ""}` },
    h("span", { class: "thumbwrap", style: { aspectRatio: `${app.geometry().W} / ${app.geometry().H}` } }, img),
    h("span", { class: "tname" }, h("span", { class: "tn", text: pageTitle(n) }), badge), h("span", { class: "tsub", text: sub }));
  t.addEventListener("contextmenu", (e) => { e.preventDefault(); app.openPageMenu(e, n); });
  requestAnimationFrame(() => thumbnail(app, n, img));
  return t;
}

/* Drag to reorder with an insertion mark; a plain click opens. Alt+arrows move.
   Works across or down, whichever way the strip runs. */
function reorderable(list, items, onMove, onOpen) {
  const down = () => getComputedStyle(list).flexDirection === "column";
  items.forEach((it, idx) => {
    it.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      const start = { x: e.clientX, y: e.clientY }, thr = e.pointerType === "touch" ? 10 : 4;
      const v = down();
      let drag = false, target = idx, mark = null;
      const rects = items.map((x) => x.getBoundingClientRect());
      try { it.setPointerCapture(e.pointerId); } catch (_) {}
      const move = (ev) => {
        const dx = ev.clientX - start.x, dy = ev.clientY - start.y;
        if (!drag && Math.hypot(dx, dy) < thr) return;
        if (!drag) { drag = true; it.classList.add("lifted"); mark = h("div", { class: "insert-mark" + (v ? " h" : ""), "aria-hidden": "true" }); list.append(mark); }
        it.style.transform = v ? `translateY(${dy}px)` : `translateX(${dx}px)`;
        const pos = v ? ev.clientY : ev.clientX;
        target = rects.filter((r) => (v ? r.top + r.height / 2 : r.left + r.width / 2) < pos).length;
        const lr = list.getBoundingClientRect();
        const r = rects[Math.min(target, rects.length - 1)];
        const before = target < rects.length;
        if (v) Object.assign(mark.style, { top: ((before ? r.top - 5 : r.bottom + 3) - lr.top + list.scrollTop) + "px" });
        else Object.assign(mark.style, { left: ((before ? r.left - 6 : r.right + 4) - lr.left + list.scrollLeft) + "px", top: (r.top - lr.top) + "px", height: (r.height * 0.6) + "px" });
        // Scroll the strip when dragging near its ends.
        if (v) { if (ev.clientY > lr.bottom - 30) list.scrollTop += 12; else if (ev.clientY < lr.top + 30) list.scrollTop -= 12; }
        else if (ev.clientX > lr.right - 30) list.scrollLeft += 12; else if (ev.clientX < lr.left + 30) list.scrollLeft -= 12;
      };
      const up = () => {
        it.removeEventListener("pointermove", move); it.removeEventListener("pointerup", up); it.removeEventListener("pointercancel", up);
        if (mark) mark.remove();
        it.style.transform = ""; it.classList.remove("lifted");
        if (!drag) { onOpen(idx); return; }
        if (target !== idx && target !== idx + 1) onMove(idx, target);
      };
      it.addEventListener("pointermove", move); it.addEventListener("pointerup", up); it.addEventListener("pointercancel", up);
    });
    it.addEventListener("keydown", (e) => {
      const v = down();
      const back = v ? "ArrowUp" : "ArrowLeft", fwd = v ? "ArrowDown" : "ArrowRight";
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(idx); }
      else if (e.altKey && e.key === back && idx > 0) { e.preventDefault(); onMove(idx, idx - 1); }
      else if (e.altKey && e.key === fwd && idx < items.length - 1) { e.preventDefault(); onMove(idx, idx + 2); }
      else if (!e.altKey && (e.key === fwd || e.key === back)) {
        e.preventDefault();
        const all = [...list.querySelectorAll(".tile")];
        const n = all[all.indexOf(it) + (e.key === fwd ? 1 : -1)];
        if (n) n.focus();
      }
    });
  });
}
