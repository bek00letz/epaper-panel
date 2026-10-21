// The page strip under the canvas. It is the rotation: tiles in the order the
// panel shows them, a page twice if it's in twice, dragged to reorder. Pages
// left out of the rotation and alert pages follow, set apart. At its head,
// the panel's status, which opens "Now on the panel".

import { h, icon, api, pageTitle, span, seconds } from "./util.js";
import { describe, parseShowIf, evaluate } from "./conditions.js";
import { slider } from "./slider.js";

/* Thumbnails come from the same renderer as everything else, one at a time,
   cached by what the page contains. */
const thumbCache = new Map();
// What the render said about each picture (its metrics): a countdown's state, for the tile to show.
const thumbMeta = new Map();
/* Drawn again from scratch, after a change that isn't in the page (the 12/24-hour setting). */
export function forgetThumbnails() { for (const u of thumbCache.values()) URL.revokeObjectURL(u); thumbCache.clear(); thumbMeta.clear(); }
const tell = (img, metrics) => img.dispatchEvent(new CustomEvent("thumbmeta", { detail: metrics || [] }));
let queue = [], running = false;
// `example`: drawn with the add-on's example values (api/example), never Home Assistant's (New page's presets).
export function thumbnail(app, name, img, override, { example = false } = {}) {
  const page = override || app.doc.spec.pages[name];
  if (!page) return;
  const key = JSON.stringify([page, app.doc.spec.orientation, app.doc.spec.display, name, example]);
  const hit = thumbCache.get(key);
  if (hit) { img.src = hit; img.classList.add("ready"); tell(img, thumbMeta.get(key)); return; }
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
      let metrics = [];
      try { metrics = JSON.parse(r.headers.get("X-Metrics") || "[]"); } catch (_) {}
      const url = URL.createObjectURL(await r.blob());
      thumbCache.set(job.key, url); thumbMeta.set(job.key, metrics);
      if (thumbCache.size > 80) { const [k, u] = thumbCache.entries().next().value; URL.revokeObjectURL(u); thumbCache.delete(k); thumbMeta.delete(k); }
      document.querySelectorAll(`img[data-thumb="${CSS.escape(job.name)}"]`).forEach((im) => { im.src = url; im.classList.add("ready"); tell(im, metrics); });
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

/* What's waiting to be sent for a page (doc.changes), in words: "2 changes",
   "Added", "Renamed from Clock · moved". Null when the panel has it as it is,
   and for a page renamed away (its new name says it). */
const changeCount = (p) => p.elements ? p.elements.added.length + p.elements.removed.length + p.elements.changed.length + (p.order ? 1 : 0) + (p.settings ? 1 : 0) : 0;
const plural = (k) => `${k} change${k === 1 ? "" : "s"}`;
export function unsentWords(pend, n) {
  const p = pend.pages[n], placed = pend.placed[n];
  if (p?.status === "removed") return p.to ? null : "Removed";
  const parts = [], k = p ? changeCount(p) : 0;
  if (p?.status === "added") parts.push("Added");
  if (p?.status === "renamed") parts.push(`Renamed from ${pageTitle(p.from)}`);
  if (k || p?.status === "changed") parts.push(k ? plural(k) : "Changed");
  if (placed) parts.push(parts.length ? { in: "put in the rotation", out: "taken out of the rotation", moved: "moved" }[placed]
    : { in: "Put in the rotation", out: "Taken out of the rotation", moved: "Moved in the rotation" }[placed]);
  return parts.length ? parts.join(" · ") : null;
}
/* The same, short enough for a tile: "2 changes, not sent". */
export function tileWords(pend, n) {
  const p = pend.pages[n], placed = pend.placed[n];
  if (!unsentWords(pend, n)) return null;
  const k = p ? changeCount(p) : 0;
  const what = p?.status === "added" ? "New" : p?.status === "removed" ? "Removed" : k ? plural(k)
    : p?.status === "renamed" ? "Renamed" : p ? "Changed" : { in: "Put in rotation", out: "Taken out", moved: "Moved" }[placed];
  return `${what}, not sent`;
}

export function renderStrip(app) {
  const doc = app.doc, spec = doc.spec, pend = doc.pending();
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
    return tile(app, n, { again, slot: i, pend });
  }).filter(Boolean);
  slots.forEach((t) => list.append(t.box));
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
    out.forEach((n) => { const t = tile(app, n, { out: true, pend }); t.addEventListener("click", () => doc.openPage(n)); list.append(t.box); });
  }
  if (alerts.length) {
    list.append(h("span", { class: "groupsep", role: "presentation" }), h("span", { class: "grouplab", text: "Alerts" }));
    alerts.forEach((n) => { const t = tile(app, n, { pend }); t.addEventListener("click", () => doc.openPage(n)); list.append(t.box); });
  }
  // Pages removed since the last send stay in sight until it, to put back.
  const gone = Object.keys(pend.pages).filter((n) => pend.pages[n].status === "removed" && !pend.pages[n].to && doc.live.pages[n]);
  if (gone.length) {
    list.append(h("span", { class: "groupsep", role: "presentation" }), h("span", { class: "grouplab", text: "Removed, not sent" }));
    gone.forEach((n) => list.append(ghostTile(app, n)));
  }
  // It slides like New page's shelves: edges that fade while there's more, arrows towards more.
  strip.style.setProperty("--aspect", String(app.geometry().W / app.geometry().H));
  strip.append(slider(list, { name: "the pages", vertical: () => app.stripVertical() }));
  return strip;
}

/* A page removed since the last send: what the panel still has, greyed; a click puts it back. */
function ghostTile(app, n) {
  const img = h("img", { class: "thumb", alt: "", "data-thumb": n, draggable: "false" });
  const t = h("button", { class: "tile ghost unsent", title: "Put it back", "aria-label": `${pageTitle(n)}. Removed, not sent. Put it back`, onclick: () => app.revertPage(n) },
    h("span", { class: "thumbwrap", style: { aspectRatio: `${app.geometry().W} / ${app.geometry().H}` } }, img, h("span", { class: "ghostact", "aria-hidden": "true" }, icon("revert", "sm"), "Put back")),
    h("span", { class: "tname" }, h("span", { class: "udot", "aria-hidden": "true" }), h("span", { class: "tn", text: pageTitle(n) })), h("span", { class: "tsub", text: "Removed, not sent" }));
  requestAnimationFrame(() => thumbnail(app, n, img, app.doc.live.pages[n]));
  return h("span", { class: "tilebox" }, t);
}

function tile(app, n, { again, out, slot, pend }) {
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
  // Not sent yet: an orange ring and dot, and what's waiting in the line under it (on its first tile).
  const words = unsentWords(pend, n), short = words && tileWords(pend, n);
  if (short && !again) sub = short;
  const img = h("img", { class: "thumb", alt: "", "data-thumb": n, draggable: "false" });
  const t = h("button", { class: "tile" + (dim ? " dim" : "") + (words ? " unsent" : ""), role: "option", title: words ? `${words}. Not sent yet` : null, "aria-selected": String(n === doc.cur && !again), "aria-current": n === doc.cur && !again ? "page" : null,
    "aria-label": `${pageTitle(n)}. ${words ? `Not sent yet: ${words}` : sub}${p.tier === "when" ? ". " + describe(p.show_if, app.entMap).text : ""}` },
    h("span", { class: "thumbwrap", style: { aspectRatio: `${app.geometry().W} / ${app.geometry().H}` } }, img),
    h("span", { class: "tname" }, words ? h("span", { class: "udot", "aria-hidden": "true" }) : null, h("span", { class: "tn", text: pageTitle(n) }), badge), h("span", { class: "tsub", text: sub }));
  // A right-click opens the page's menu. A long press on a touch screen is the hold that shows its
  // buttons (holdToReveal), so the menu Android opens with it would only cover them.
  t.addEventListener("contextmenu", (e) => { e.preventDefault(); if (!t.dataset.touched) app.openPageMenu(e, n); });
  // A countdown says what its page does (render/countdown.status): Passed is outlined and greyed,
  // to reuse with another date or delete; one waiting says when it starts showing.
  img.addEventListener("thumbmeta", (e) => {
    const c = (e.detail || []).find((m) => m.countdown)?.countdown;
    t.classList.toggle("passed", c?.state === "passed");
    box.classList.toggle("passed", c?.state === "passed");       // its buttons stay showing
    if (!c || c.state === "showing" || again || out) return;
    const said = c.state === "passed" ? `Passed · ${c.on}` : `Shows from ${c.from}`;
    t.classList.add("dim");
    if (words) { t.setAttribute("aria-label", `${pageTitle(n)}. ${said}. Not sent yet: ${words}`); return; }   // what's waiting keeps the line
    t.querySelector(".tsub").textContent = said;
    t.setAttribute("aria-label", `${pageTitle(n)}. ${said}`);
  });
  requestAnimationFrame(() => thumbnail(app, n, img));
  // The tile and, beside it, its page's two buttons over its picture (the user's design, 21 Oct):
  // Duplicate, and Delete, which offers Delete page or Take out of rotation (that choice is the guard
  // against a slip, never an "are you sure"). Over the last third, Duplicate above Delete, or across
  // the bottom half, half each: Settings › Editor, for each strip size (app.tileButtons). They show
  // on hover or focus and on a hold on a touch screen, and stay on a passed countdown. Each is 44 pt
  // to touch at every size. Beside the tile, not inside: a button can't hold other buttons.
  // The right-click menu keeps the fuller list (Show again and the rest).
  const g = app.geometry();
  const dup = h("button", { class: "tileact dup", "aria-label": `Duplicate ${pageTitle(n)}`, title: "Duplicate", tabindex: "-1",
    onclick: (ev) => { ev.stopPropagation(); box.classList.remove("held"); app.duplicatePage(n); } }, icon("dup", "sm"));
  const del = h("button", { class: "tileact del", "aria-label": `Delete ${pageTitle(n)}…`, title: "Delete", "aria-haspopup": "menu", tabindex: "-1",
    onclick: (ev) => { ev.stopPropagation(); box.classList.remove("held"); app.openDeleteMenu(n, del, slot); } }, icon("trash", "sm"));
  const acts = h("span", { class: "tileacts", style: { aspectRatio: `${g.W} / ${g.H}` } }, dup, del);
  const box = h("span", { class: "tilebox" }, t, acts);
  holdToReveal(t, box);
  t.box = box;
  return t;
}

/* On a touch screen, holding a tile without moving shows its buttons (and a
   tap anywhere else puts them away); the hold doesn't open the page. */
function holdToReveal(t, box) {
  let timer = null, at = null;
  const stop = () => { clearTimeout(timer); timer = null; };
  t.addEventListener("pointerdown", (e) => {
    if (e.pointerType !== "touch") { delete t.dataset.touched; return; }
    t.dataset.touched = "1";
    at = { x: e.clientX, y: e.clientY };
    timer = setTimeout(() => {
      timer = null; t.dataset.held = "1"; box.classList.add("held");
      navigator.vibrate?.(8);
      const away = (ev) => { if (!box.contains(ev.target)) { box.classList.remove("held"); document.removeEventListener("pointerdown", away, true); } };
      document.addEventListener("pointerdown", away, true);
    }, 480);
  });
  t.addEventListener("pointermove", (e) => { if (timer && at && Math.hypot(e.clientX - at.x, e.clientY - at.y) > 10) stop(); });
  t.addEventListener("pointerup", stop); t.addEventListener("pointercancel", stop);
  // The click a hold ends with isn't an open.
  t.addEventListener("click", (e) => { if (t.dataset.held) { e.stopImmediatePropagation(); e.preventDefault(); delete t.dataset.held; } }, true);
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
        if (!drag) { if (it.dataset.held) delete it.dataset.held; else onOpen(idx); return; }   // a hold showed its buttons
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
