// The canvas. What you see is the add-on's own render of the page
// (POST /api/preview), so it can't disagree with the panel. On top sit only
// outlines: hover, selection, the stack under the pointer, snapping guides.
//
// Picking: a click selects the smallest thing under the pointer. Clicking
// again without moving goes to the next bigger one, round and round; while
// you do, every candidate is outlined in dashes and a label says "2 of 3".
// A drag starts only after 4 px (8 on touch), so a click never moves anything.

import { h, api, clone, pageTitle } from "./util.js";
import { elName, makeEntityElement, normalizeLineParity } from "./elements.js";

const SNAP = 6;

export class Canvas {
  constructor(app) {
    this.app = app;
    this.doc = app.doc;
    this.hover = -1; this.rowHover = -1;
    this.stack = null; this.lastClick = null; this.press = null;
    this.metrics = [];
    this.build();
  }

  get g() { return this.app.geometry(); }
  els() { return this.doc.els(); }

  build() {
    this.panel = h("div", { class: "panel", tabindex: "0", role: "application",
      "aria-roledescription": "canvas", "aria-describedby": "canvas-help" });
    this.ov = h("div", { class: "ov", "aria-hidden": "true" });
    this.zones = h("div", { class: "zones", "aria-hidden": "true" },
      h("div", { class: "zone footer" }, h("span", { text: "Footer: time, page and padlock" })));
    this.panel.append(this.zones, this.ov);
    this.device = h("div", { class: "device" }, this.panel);
    this.wire();
  }

  /* ---------- the page image ---------- */
  layout() {
    const g = this.g;
    this.panel.style.aspectRatio = `${g.W} / ${g.H}`;
    this.device.style.setProperty("--ar", String(g.W / g.H));
    this.device.style.setProperty("--pw", g.W + "px");
    this.device.classList.toggle("portrait", g.portrait);
    const f = this.zones.querySelector(".footer");
    Object.assign(f.style, { top: (g.safeH / g.H * 100) + "%", height: (g.footer / g.H * 100) + "%" });
    this.panel.setAttribute("aria-label", `${pageTitle(this.doc.cur || "")} on the panel. Click an item to select it; click again to reach what's underneath.`);
  }

  preview(now) {
    clearTimeout(this.previewT);
    const run = async () => {
      if (this.previewing) { this.previewAgain = true; return; }
      const page = this.doc.page();
      if (!page) { this.panel.style.backgroundImage = ""; return; }
      this.previewing = true;
      const spec = this.doc.spec;
      try {
        const r = await api("api/preview", { method: "POST", raw: true, body: {
          page, label: this.doc.cur, orientation: Number(spec.orientation || 0),
          distance: Number(this.app.prefs.get("view_dist", "3.0")), display: spec.display } });
        try { this.metrics = JSON.parse(r.headers.get("X-Metrics") || "[]"); } catch (_) { this.metrics = []; }
        const url = URL.createObjectURL(await r.blob());
        // Swap once the new image has decoded, so the canvas never blinks; a
        // hidden tab may never decode, so don't wait more than a moment.
        const img = new Image(); img.src = url;
        await Promise.race([img.decode().catch(() => {}), new Promise((res) => setTimeout(res, 250))]);
        this.panel.style.backgroundImage = `url(${url})`;
        if (this.prevUrl) URL.revokeObjectURL(this.prevUrl);
        this.prevUrl = url;
        this.panel.classList.remove("stale");
        this.app.onMetrics(this.metrics);
      } catch (e) {
        this.panel.classList.add("stale");
        this.app.notice(`The preview didn't render: ${e.message}`);
      } finally {
        this.previewing = false;
        if (this.previewAgain) { this.previewAgain = false; run(); }
      }
    };
    if (now) run(); else this.previewT = setTimeout(run, 160);
  }

  /* ---------- hit testing ---------- */
  toPanel(e) {
    const r = this.panel.getBoundingClientRect(), g = this.g;
    return { x: (e.clientX - r.left) * g.W / r.width, y: (e.clientY - r.top) * g.H / r.height, scale: g.W / r.width };
  }
  hitsAt(p) {
    const out = [];
    this.els().forEach((el, i) => {
      const tol = el.type === "line" ? 6 : 2;
      if (p.x >= el.x - tol && p.x <= el.x + el.w + tol && p.y >= el.y - tol && p.y <= el.y + el.h + tol) out.push(i);
    });
    const els = this.els();
    return out.sort((a, b) => (els[a].w * els[a].h) - (els[b].w * els[b].h) || b - a);
  }

  /* ---------- pointer ---------- */
  wire() {
    const p = this.panel;
    p.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      const hits = this.hitsAt(this.toPanel(e));
      if (hits.length && !hits.some((k) => this.doc.sel.includes(k))) this.doc.select([hits[0]]);
      this.app.openCanvasMenu(e, hits);
    });
    p.addEventListener("pointermove", (e) => {
      if (this.press) return this.onDragMove(e);
      if (e.pointerType === "touch") return;
      const hits = this.hitsAt(this.toPanel(e));
      const hv = hits.length ? hits[0] : -1;
      if (hv !== this.hover) { this.hover = hv; this.draw(); }
    });
    p.addEventListener("pointerleave", () => { if (!this.press && this.hover !== -1) { this.hover = -1; this.draw(); } });
    p.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      p.focus({ preventScroll: true });
      const pt = this.toPanel(e);
      try { p.setPointerCapture(e.pointerId); } catch (_) {}
      const hd = e.target.closest(".hd");
      if (hd) {
        const i = this.doc.sel[0];
        this.press = { mode: "size", corner: hd.dataset.c, sx: e.clientX, sy: e.clientY, scale: pt.scale, orig: clone(this.els()[i]), i, dragging: true };
        return;
      }
      this.press = { mode: "move", sx: e.clientX, sy: e.clientY, p: pt, scale: pt.scale, hits: this.hitsAt(pt),
        shift: e.shiftKey, alt: e.altKey, dragging: false, thr: e.pointerType === "touch" ? 8 : 4 };
    });
    p.addEventListener("pointerup", () => this.onUp());
    p.addEventListener("pointercancel", () => { this.press = null; this.clearGuides(); this.app.refresh(); });
    p.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("application/x-epaper-entity")) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; } });
    p.addEventListener("drop", (e) => {
      const id = e.dataTransfer.getData("application/x-epaper-entity");
      if (!id) return;
      e.preventDefault();
      const ent = this.app.entMap.get(id) || { entity_id: id, state: "" };
      const el = makeEntityElement(ent, this.g, this.toPanel(e));
      this.els().push(el);
      this.doc.sel = [this.els().length - 1];
      this.doc.commit();
      this.app.say(`Added ${ent.name || id}`);
    });
  }

  onDragMove(e) {
    const pr = this.press;
    const dx = (e.clientX - pr.sx) * pr.scale, dy = (e.clientY - pr.sy) * pr.scale;
    if (pr.mode === "size") return this.resizeTo(pr, dx, dy, e.altKey);
    if (!pr.dragging) {
      if (Math.hypot(e.clientX - pr.sx, e.clientY - pr.sy) < pr.thr || !pr.hits.length) return;
      // Dragging something that's already selected moves the selection, even
      // when it sits underneath something else.
      const under = pr.hits.find((i) => this.doc.sel.includes(i));
      const i = under !== undefined ? under : pr.hits[0];
      if (!this.doc.sel.includes(i)) this.doc.sel = this.withMembers(pr.shift ? [...this.doc.sel, i] : [i]);
      pr.dragging = true; pr.lead = i;
      pr.orig = this.doc.sel.map((k) => ({ k, el: clone(this.els()[k]) }));
      this.stack = null;
      this.app.inspectorSoon();
    }
    const els = this.els(), g = this.g;
    pr.moved = true;
    if (pr.orig.length > 1) {
      // Several move as one: the box around them snaps like a single element would.
      const moved = pr.orig.filter(({ el: o }) => o.type !== "group");
      const box = (ox, oy) => {
        const xs = moved.map(({ el: o }) => o.x + ox), ys = moved.map(({ el: o }) => o.y + oy);
        const x0 = Math.min(...xs), y0 = Math.min(...ys);
        return { x: x0, y: y0, w: Math.max(...moved.map(({ el: o }) => o.x + ox + o.w)) - x0, h: Math.max(...moved.map(({ el: o }) => o.y + oy + o.h)) - y0 };
      };
      let ox = dx, oy = dy, guides = null;
      if (moved.length) {
        const b = box(dx, dy);
        ox -= Math.min(0, b.x); oy -= Math.min(0, b.y);                       // keep them on the panel
        ox -= Math.max(0, b.x + b.w - g.W); oy -= Math.max(0, b.y + b.h - g.H);
        if (!e.altKey) {
          const snap = this.snapRect(box(ox, oy), (j) => this.doc.sel.includes(j));
          ox += snap.dx; oy += snap.dy; guides = [snap.gx, snap.gy];
        }
      }
      pr.orig.forEach(({ k, el: o }) => {
        els[k].x = Math.round(o.x + ox);
        els[k].y = Math.round(o.y + oy);
      });
      this.draw(guides);
    } else {
      const el = els[pr.lead], o = pr.orig[0].el;
      el.x = Math.max(0, Math.min(g.W - o.w, Math.round(o.x + dx)));
      el.y = Math.max(0, Math.min(g.H - o.h, Math.round(o.y + dy)));
      this.draw(e.altKey ? null : this.snapMove(el, pr.lead));
    }
    this.livePreview();
  }

  onUp() {
    const pr = this.press; if (!pr) return;
    this.press = null;
    this.clearGuides();
    if (pr.dragging) {
      if (pr.moved) { this.doc.commit(); this.app.say("Moved"); }
      else this.app.refresh();
      return;
    }
    this.click(pr);
  }

  click(pr) {
    const hits = pr.hits;
    if (!hits.length) {
      this.stack = null; this.lastClick = null;
      if (!pr.shift) this.doc.select([]);
      this.app.say(`Nothing selected. The inspector shows the page.`);
      return;
    }
    const sig = hits.join(",");
    const again = this.lastClick && Math.hypot(pr.sx - this.lastClick.x, pr.sy - this.lastClick.y) < 5 && this.lastClick.sig === sig;
    const idx = again ? (this.lastClick.idx + 1) % hits.length : 0;
    const picked = hits[idx];
    this.lastClick = { x: pr.sx, y: pr.sy, sig, idx };
    let sel;
    if (pr.shift) sel = this.doc.sel.includes(picked) ? this.doc.sel.filter((k) => k !== picked) : [...this.doc.sel, picked];
    else sel = [picked];
    sel = this.withMembers(sel);
    if (hits.length > 1) {
      this.stack = { hits, idx, p: pr.p, fresh: true };
      clearTimeout(this.stackT);
      this.stackT = setTimeout(() => { this.stack = null; this.draw(); }, 1800);
    } else this.stack = null;
    this.doc.select(sel);
    const { t, d } = elName(this.els()[picked], this.app.entMap);
    this.app.say(`${t}${d ? ", " + d : ""} selected${hits.length > 1 ? `, ${idx + 1} of ${hits.length} under the pointer` : ""}.`);
  }

  /* A group comes with its members, so moving it moves them. */
  withMembers(sel) {
    const els = this.els(), out = new Set(sel);
    for (const k of sel) {
      const g = els[k];
      if (g?.type === "group") els.forEach((e, j) => { if ((g.members || []).includes(e.id)) out.add(j); });
    }
    return [...out];
  }

  livePreview() {
    // While dragging, keep the image following at the speed the add-on renders.
    if (!this.previewing) this.preview(true); else this.previewAgain = true;
  }

  /* ---------- snapping (from 0.9: margins, centre, footer line, other elements) ---------- */
  targets(skip) {
    const g = this.g;
    const xs = [0, g.margin, g.W / 2, g.W - g.margin, g.W], ys = [0, 26, g.H / 2, g.safeH, g.H];
    this.els().forEach((o, j) => {
      if (skip(j)) return;
      if (o.type === "line" && o.h >= o.w) { xs.push(o.x + o.w / 2); ys.push(o.y, o.y + o.h / 2, o.y + o.h); }
      else if (o.type === "line") { xs.push(o.x, o.x + o.w / 2, o.x + o.w); ys.push(o.y + o.h / 2); }
      else { xs.push(o.x, o.x + o.w / 2, o.x + o.w); ys.push(o.y, o.y + o.h / 2, o.y + o.h); }
    });
    return { xs, ys };
  }
  /* How far to shift a box so one of its edges or centres meets a guide. */
  snapRect(r, skip) {
    const { xs, ys } = this.targets(skip);
    let gx = null, gy = null, bx = SNAP + 0.01, by = SNAP + 0.01, dx = 0, dy = 0;
    for (const v of [r.x + r.w / 2, r.x, r.x + r.w]) for (const t of xs) { const d = Math.abs(v - t); if (d < bx) { bx = d; gx = t; dx = t - v; } }
    for (const v of [r.y + r.h / 2, r.y, r.y + r.h]) for (const t of ys) { const d = Math.abs(v - t); if (d < by) { by = d; gy = t; dy = t - v; } }
    return { dx: Math.round(dx), dy: Math.round(dy), gx, gy };
  }
  snapMove(el, i) {
    const { xs, ys } = this.targets((j) => j === i || this.doc.sel.includes(j));
    const vline = el.type === "line" && el.h >= el.w, hline = el.type === "line" && el.w > el.h;
    const xc = vline ? [[el.x + el.w / 2, "c"]] : [[el.x + el.w / 2, "c"], [el.x, "l"], [el.x + el.w, "r"]];
    const yc = hline ? [[el.y + el.h / 2, "m"]] : [[el.y + el.h / 2, "m"], [el.y, "t"], [el.y + el.h, "b"]];
    let gx = null, gy = null, bx = SNAP + 0.01, by = SNAP + 0.01, sx = null, sy = null;
    for (const [v, s] of xc) for (const t of xs) { const d = Math.abs(v - t); if (d < bx) { bx = d; gx = t; sx = s; } }
    for (const [v, s] of yc) for (const t of ys) { const d = Math.abs(v - t); if (d < by) { by = d; gy = t; sy = s; } }
    if (gx !== null) { if (vline) normalizeLineParity(el, gx, "x"); else el.x = Math.round(gx - (sx === "c" ? el.w / 2 : sx === "r" ? el.w : 0)); }
    if (gy !== null) { if (hline) normalizeLineParity(el, gy, "y"); else el.y = Math.round(gy - (sy === "m" ? el.h / 2 : sy === "b" ? el.h : 0)); }
    return [gx, gy];
  }
  resizeTo(pr, dx, dy, noSnap) {
    const el = this.els()[pr.i], o = pr.orig, g = this.g, c = pr.corner;
    const minW = el.type === "line" ? 4 : 16, minH = 4;
    let { x, y, w, h: hh } = o;
    if (c.includes("e")) w = o.w + dx;
    if (c.includes("s")) hh = o.h + dy;
    if (c.includes("w")) { x = o.x + dx; w = o.w - dx; }
    if (c.includes("n")) { y = o.y + dy; hh = o.h - dy; }
    if (w < minW) { if (c.includes("w")) x -= minW - w; w = minW; }
    if (hh < minH) { if (c.includes("n")) y -= minH - hh; hh = minH; }
    x = Math.max(0, x); y = Math.max(0, y);
    w = Math.min(g.W - x, w); hh = Math.min(g.H - y, hh);
    Object.assign(el, { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(hh) });
    let guides = null;
    if (!noSnap) {
      const { xs, ys } = this.targets((j) => j === pr.i);
      const near = (v, list) => { let best = null, bd = SNAP + 0.01; for (const t of list) { const d = Math.abs(v - t); if (d < bd) { bd = d; best = t; } } return best; };
      const ex = c.includes("w") ? el.x : el.x + el.w, ey = c.includes("n") ? el.y : el.y + el.h;
      const gx = near(ex, xs), gy = near(ey, ys);
      if (gx !== null) { if (c.includes("w")) { el.w += el.x - gx; el.x = Math.round(gx); } else el.w = Math.round(gx - el.x); }
      if (gy !== null) { if (c.includes("n")) { el.h += el.y - gy; el.y = Math.round(gy); } else el.h = Math.round(gy - el.y); }
      guides = [gx, gy];
    }
    pr.moved = true;
    this.draw(guides);
    this.app.liveFields(el);
    this.livePreview();
  }

  /* ---------- outlines ---------- */
  clearGuides() { this.ov.querySelectorAll(".guide").forEach((n) => n.remove()); }
  draw(guides) {
    const g = this.g, els = this.els(), sel = this.doc.sel;
    this.ov.replaceChildren();
    this.panel.classList.toggle("show-guides", this.app.prefs.get("guides") === "1");
    const pct = (el) => ({ left: (el.x / g.W * 100) + "%", top: (el.y / g.H * 100) + "%", width: (el.w / g.W * 100) + "%", height: (el.h / g.H * 100) + "%" });
    const box = (el, cls) => { const b = h("div", { class: "ob " + cls, style: pct(el) }); this.ov.append(b); return b; };
    if (this.app.prefs.get("guides") === "1") els.forEach((el, i) => { if (!sel.includes(i)) box(el, "all"); });
    els.forEach((el, i) => { if (el._auto && !sel.includes(i)) box(el, "auto"); });
    if (this.stack) this.stack.hits.forEach((k) => { if (!sel.includes(k) && els[k]) box(els[k], "stk"); });
    const hv = this.rowHover >= 0 ? this.rowHover : this.hover;
    if (hv >= 0 && els[hv] && !sel.includes(hv) && !this.press?.dragging) box(els[hv], "hov");
    const single = sel.length === 1;
    sel.forEach((k) => {
      if (!els[k]) return;
      const picking = this.stack && this.stack.fresh && this.stack.hits[this.stack.idx] === k;
      const b = box(els[k], single ? (picking ? "sel pick" : "sel") : "sel multi");
      if (single && !(this.press?.dragging && this.press.mode === "move")) ["nw", "ne", "sw", "se"].forEach((c) => b.append(h("span", { class: "hd " + c, data: { c } })));
    });
    if (this.stack && this.stack.fresh) {
      const k = this.stack.hits[this.stack.idx], el = els[k];
      if (el) {
        const { t, d } = elName(el, this.app.entMap);
        this.ov.append(h("div", { class: "pickchip", text: `${this.stack.idx + 1} of ${this.stack.hits.length} · ${t}${d ? " " + d : ""}`,
          style: { left: Math.max(10, Math.min(90, this.stack.p.x / g.W * 100)) + "%", top: Math.max(12, this.stack.p.y / g.H * 100) + "%" } }));
      }
    }
    if (guides) {
      if (guides[0] !== null && guides[0] !== undefined) this.ov.append(h("div", { class: "guide v", style: { left: (guides[0] / g.W * 100) + "%" } }));
      if (guides[1] !== null && guides[1] !== undefined) this.ov.append(h("div", { class: "guide h", style: { top: (guides[1] / g.H * 100) + "%" } }));
    }
  }
}
