// The pages being edited: undo, saving as you go, sending, and merging with
// changes made in another window.
//
// Three copies matter:
//   live    what the add-on renders for the panel (sent)
//   synced  what this window last wrote to the server (the draft, or live)
//   spec    what you're looking at now
// Edits are saved to the draft a moment after you stop (never to the panel).
// Send writes the draft as the live pages, with a version check.

import { api, clone, same } from "./util.js";
import { groupBox } from "./elements.js";

const HISTORY = 60;
const AUTOSAVE_MS = 700;
const TOP_KEYS = ["display", "orientation", "rotate_seconds", "quiet_hours", "custom_presets", "location_presets"];

/* Every element has an ID, unique across the pages: a screen of another
   size keeps its own place for each element by it. New, pasted and
   duplicated elements get theirs here, in one place. */
export const ARRANGE_KEYS = ["x", "y", "w", "h", "size", "font_scale"];
const newId = (taken) => { let id; do { id = "e" + Math.random().toString(16).slice(2, 8); } while (taken.has(id)); return id; };
export function ensureIds(spec) {
  const seen = new Set();
  for (const p of Object.values(spec.pages || {})) {
    for (const el of p.elements || []) {
      if (!el || typeof el !== "object") continue;
      if (!el.id || seen.has(el.id)) el.id = newId(seen);
      seen.add(el.id);
    }
  }
  return spec;
}

export function normalize(spec) {
  spec = spec && typeof spec === "object" ? spec : {};
  if (!spec.pages || typeof spec.pages !== "object") spec.pages = {};
  if (!Array.isArray(spec.rotation)) spec.rotation = [];
  if (!spec.display) spec.display = "crowpanel_579";
  if (spec.orientation === undefined) spec.orientation = 0;
  if (spec.rotate_seconds === undefined) spec.rotate_seconds = 30;
  if (!spec.quiet_hours) spec.quiet_hours = { enabled: false, start: "23:00", end: "07:00", presence_entity: "", allow_alerts: true, sleep_screen: true };
  if (!Array.isArray(spec.custom_presets)) spec.custom_presets = [];
  if (!Array.isArray(spec.location_presets)) spec.location_presets = [];
  for (const p of Object.values(spec.pages)) if (!Array.isArray(p.elements)) p.elements = [];
  return ensureIds(spec);
}

/* Groups follow their members: their box is recomputed, members that are
   gone leave, and a group with no members left goes too. */
function syncGroups(spec) {
  for (const p of Object.values(spec.pages)) {
    const ids = new Set(p.elements.filter((e) => e.type !== "group").map((e) => e.id));
    p.elements = p.elements.filter((g) => {
      if (g.type !== "group") return true;
      g.members = (g.members || []).filter((m) => ids.has(m));
      const b = groupBox(g, p.elements);
      if (!b) return false;
      Object.assign(g, b);
      return true;
    });
  }
}

/* An element placed automatically for this screen's size stays automatic
   until someone moves or resizes it; then this size has its own place for it. */
function settleAuto(spec, prevJson) {
  let prev = null;
  for (const [name, p] of Object.entries(spec.pages)) {
    for (const el of p.elements) {
      if (!el._auto) continue;
      prev = prev || JSON.parse(prevJson);
      const was = (prev.pages[name]?.elements || []).find((e) => e.id === el.id);
      if (!was || ARRANGE_KEYS.some((k) => !same(was[k], el[k]))) delete el._auto;
    }
  }
}

/* Three-way merge: by page, then rotation, then each setting. A part changed
   on only one side takes that side; changed on both, differently, is a clash. */
export function merge(base, mine, theirs) {
  base = base || { pages: {} };
  const out = clone(theirs);
  const clashes = [];
  const names = new Set([...Object.keys(base.pages || {}), ...Object.keys(mine.pages || {}), ...Object.keys(theirs.pages || {})]);
  for (const n of names) {
    const b = base.pages?.[n], m = mine.pages?.[n], t = theirs.pages?.[n];
    if (same(m, b) || same(m, t)) continue;
    if (same(t, b)) { if (m) out.pages[n] = clone(m); else delete out.pages[n]; continue; }
    clashes.push({ kind: "page", name: n, mine: m, theirs: t });
  }
  // Page order: keep theirs, with any pages only you added at the end.
  const ordered = {};
  for (const k of Object.keys(out.pages)) ordered[k] = out.pages[k];
  out.pages = ordered;
  if (!same(mine.rotation, base.rotation)) {
    if (same(theirs.rotation, base.rotation)) out.rotation = clone(mine.rotation);
    else if (!same(theirs.rotation, mine.rotation)) clashes.push({ kind: "rotation", name: "rotation", mine: mine.rotation, theirs: theirs.rotation });
  }
  for (const k of TOP_KEYS) {
    if (same(mine[k], base[k])) continue;
    if (same(theirs[k], base[k])) out[k] = clone(mine[k]);
    else if (!same(theirs[k], mine[k])) clashes.push({ kind: "setting", name: k, mine: mine[k], theirs: theirs[k] });
  }
  out.rotation = (out.rotation || []).filter((n) => out.pages[n]);
  return { merged: out, clashes };
}

export class Doc {
  constructor() {
    this.spec = normalize({});
    this.live = this.spec; this.liveEtag = "";
    this.synced = this.spec; this.draftVersion = 0;
    this.cur = null; this.sel = [];
    this.hist = []; this.hpos = -1;
    this.saving = "saved"; this.saveError = "";
    this.listeners = {};
    this.resolveClashes = null;       // set by the UI: async (clashes) => {name: "mine"|"theirs"}
  }

  on(ev, fn) { (this.listeners[ev] ||= []).push(fn); }
  emit(ev, arg) { (this.listeners[ev] || []).forEach((fn) => fn(arg)); }

  get dirty() { return !same(this.spec, this.live); }
  page() { return this.spec.pages[this.cur]; }
  els() { const p = this.page(); return p ? p.elements : []; }
  selected() { return this.sel.map((i) => this.els()[i]).filter(Boolean); }

  async load() {
    const [layouts, draft] = await Promise.all([api("api/layouts"), api("api/draft").catch(() => ({ body: {} }))]);
    this.live = normalize(layouts.body);
    this.liveEtag = layouts.etag || draft.body?.etag || "";
    const d = draft.body?.draft;
    this.spec = clone(this.live);
    this.synced = clone(this.live);
    this.draftVersion = 0;
    let note = "";
    if (d && d.spec) {
      this.draftVersion = d.version || 0;
      const dspec = normalize(d.spec);
      if (d.base_etag === this.liveEtag || !d.base) {
        this.spec = dspec;
      } else {
        // Sent from somewhere else since this draft began: carry the draft onto it.
        const { merged, clashes } = merge(normalize(d.base), dspec, this.live);
        this.spec = await this.settle(merged, clashes, dspec);
        note = "Your unsent changes were carried onto pages sent from another window.";
      }
      this.synced = clone(dspec);
    }
    this.hist = [JSON.stringify(this.spec)]; this.hpos = 0;
    this.cur = this.firstPage();
    this.sel = [];
    this.emit("load");
    return note;
  }

  firstPage() { return this.spec.rotation.find((n) => this.spec.pages[n]) || Object.keys(this.spec.pages)[0] || null; }

  /* Record an edit. `kind` coalesces bursts (arrow nudges, typing) into one undo step. */
  commit(kind) {
    ensureIds(this.spec);
    const before = this.sel.map((i) => this.els()[i]);
    syncGroups(this.spec);
    if (before.length) this.sel = before.map((e) => this.els().indexOf(e)).filter((i) => i >= 0);
    settleAuto(this.spec, this.hist[this.hpos]);
    const json = JSON.stringify(this.spec);
    if (json === this.hist[this.hpos]) { this.emit("change"); return; }
    const now = Date.now();
    if (kind && kind === this.lastKind && now - this.lastAt < 1000 && this.hpos === this.hist.length - 1 && this.hpos > 0) {
      this.hist[this.hpos] = json;
    } else {
      this.hist = this.hist.slice(0, this.hpos + 1);
      this.hist.push(json);
      if (this.hist.length > HISTORY) this.hist.shift();
      this.hpos = this.hist.length - 1;
    }
    this.lastKind = kind; this.lastAt = now;
    this.scheduleSave();
    this.emit("change");
  }
  get canUndo() { return this.hpos > 0; }
  get canRedo() { return this.hpos < this.hist.length - 1; }
  undo() { this.restore(this.hpos - 1); }
  redo() { this.restore(this.hpos + 1); }
  restore(i) {
    if (i < 0 || i >= this.hist.length) return;
    this.hpos = i;
    this.spec = JSON.parse(this.hist[i]);
    if (!this.spec.pages[this.cur]) this.cur = this.firstPage();
    this.sel = this.sel.filter((k) => k < this.els().length);
    this.lastKind = null;
    this.scheduleSave();
    this.emit("change");
  }

  select(idxs) { this.sel = idxs.filter((i) => i >= 0 && i < this.els().length); this.emit("select"); }
  openPage(name) {
    if (!this.spec.pages[name]) return;
    this.cur = name; this.sel = [];
    this.emit("page");
  }

  /* ---------- saving as you go ---------- */
  scheduleSave() {
    clearTimeout(this.saveT);
    this.saving = "pending";
    this.emit("saving");
    this.saveT = setTimeout(() => this.saveDraft(), AUTOSAVE_MS);
  }
  async flush() { if (this.saving === "pending") { clearTimeout(this.saveT); await this.saveDraft(); } }

  async saveDraft() {
    if (this.inflight) { this.again = true; return; }
    this.inflight = true;
    const spec = clone(this.spec);
    try {
      if (same(spec, this.live)) {
        // Back to what's on the panel: no draft needed.
        if (this.draftVersion) await api("api/draft", { method: "DELETE" });
        this.draftVersion = 0;
      } else {
        const r = await this.putDraft(spec);
        this.draftVersion = r.version;
      }
      this.synced = spec;
      this.saving = "saved"; this.saveError = "";
    } catch (e) {
      if (e.status === 409) {
        await this.absorb(e.body);
        this.inflight = false;
        return this.saveDraft();
      }
      this.saving = "error";
      this.saveError = e.message;
      clearTimeout(this.retryT);
      this.retryT = setTimeout(() => this.saveDraft(), 10000);
    } finally {
      this.inflight = false;
    }
    this.emit("saving");
    if (this.again) { this.again = false; this.saveDraft(); }
  }
  putDraft(spec) {
    return api("api/draft", { method: "PUT", headers: { "If-Match": String(this.draftVersion) },
      body: { spec, base: this.live, base_etag: this.liveEtag } }).then((r) => r.body);
  }

  /* Another window saved first: take its version, put ours on top. */
  async absorb(body) {
    const theirDraft = body?.draft;
    if (body?.live) { this.live = normalize(body.live); this.liveEtag = body.etag || this.liveEtag; }
    const theirs = theirDraft ? normalize(theirDraft.spec) : this.live;
    const { merged, clashes } = merge(this.synced, this.spec, theirs);
    this.spec = await this.settle(merged, clashes, this.spec);
    this.synced = clone(theirs);
    this.draftVersion = theirDraft ? theirDraft.version : 0;
    this.pushHistory();
    this.emit("change");
    this.emit("merged", clashes.length);
  }

  async settle(merged, clashes, mine) {
    if (!clashes.length) return merged;
    const choice = this.resolveClashes ? await this.resolveClashes(clashes) : {};
    for (const c of clashes) {
      const take = choice[c.name] === "theirs" ? c.theirs : c.mine;
      if (c.kind === "page") { if (take) merged.pages[c.name] = clone(take); else delete merged.pages[c.name]; }
      else if (c.kind === "rotation") merged.rotation = clone(take || []);
      else merged[c.name] = clone(take);
    }
    merged.rotation = merged.rotation.filter((n) => merged.pages[n]);
    if (!merged.pages[this.cur]) this.cur = Object.keys(merged.pages)[0] || null;
    return merged;
  }
  pushHistory() {
    this.hist = this.hist.slice(0, this.hpos + 1);
    this.hist.push(JSON.stringify(this.spec));
    this.hpos = this.hist.length - 1;
    this.sel = this.sel.filter((k) => k < this.els().length);
  }

  /* ---------- sending ---------- */
  async send() {
    clearTimeout(this.saveT);
    for (let attempt = 0; attempt < 3; attempt++) {
      const spec = clone(this.spec);
      try {
        const r = await api("api/layouts", { method: "PUT", headers: { "If-Match": this.liveEtag || "*" }, body: spec });
        this.live = normalize(clone(spec));
        // The server tidies what it saves; adopt its rotation and settings.
        if (r.body?.rotation) this.live.rotation = r.body.rotation;
        this.liveEtag = r.body?.etag || r.etag;
        if (r.body?.rotation && same(spec.rotation.filter((n) => spec.pages[n]), r.body.rotation)) this.spec.rotation = r.body.rotation;
        this.synced = clone(this.spec);
        this.draftVersion = 0;
        this.saving = "saved";
        this.emit("saving"); this.emit("change");
        return true;
      } catch (e) {
        if (e.status !== 409) throw e;
        const theirs = normalize(e.body.current);
        const { merged, clashes } = merge(this.live, this.spec, theirs);
        this.live = theirs; this.liveEtag = e.body.etag;
        this.spec = await this.settle(merged, clashes, this.spec);
        this.pushHistory();
        this.emit("change");
        this.emit("merged", clashes.length);
      }
    }
    throw new Error("The pages kept changing in another window. Try again in a moment.");
  }

  /* Throw away everything not sent: one undoable step. */
  revert() {
    this.spec = clone(this.live);
    if (!this.spec.pages[this.cur]) this.cur = this.firstPage();
    this.sel = [];
    this.commit();
  }
}
