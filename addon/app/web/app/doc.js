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
const TOP_KEYS = ["display", "orientation", "quiet_hours", "custom_presets", "location_presets"];

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
  delete spec.rotate_seconds;     // Rotate every is the screen's own since 0.13 (Settings), never sent with pages
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

/* What a person calls each setting sent with the pages. */
export const SETTING_NAMES = { quiet_hours: "Quiet hours", custom_presets: "Your presets", location_presets: "Saved places", display: "Panel model", orientation: "Mounting" };

/* What differs from `base` in `mine`: the one comparison. The merge below
   reads it, and so do the page strip and "Not sent yet" (base = what the
   panel has, mine = the draft).
     pages     by name, each page whose content differs: "added", "removed",
               "renamed" (an added page holding a removed one's elements, by
               ID; `from` names it, and the removed one has `to`) or
               "changed"; with its elements by ID (added, removed, changed),
               whether their order changed and whether the page's own
               settings did
     placed    by name, a page whose place in the rotation changed: "in",
               "out" or "moved" (not in the longest run of pages both keep
               in the same order, so dragging one page marks only it)
     rotation  whether the rotation differs at all
     settings  the settings sent with the pages that differ */
export function changes(base, mine) {
  base = base || { pages: {}, rotation: [] };
  const bp = base.pages || {}, mp = mine.pages || {};
  const pages = {};
  for (const n of new Set([...Object.keys(bp), ...Object.keys(mp)])) {
    const b = bp[n], m = mp[n];
    if (same(m, b)) continue;
    pages[n] = !b ? { status: "added" } : !m ? { status: "removed" } : { status: "changed", ...pageChanges(b, m) };
  }
  // Renamed: an added page that took at least half of a removed one's elements with it.
  const names = {};
  for (const [r, rc] of Object.entries(pages)) {
    if (rc.status !== "removed") continue;
    const ids = new Set((bp[r].elements || []).map((e) => e?.id).filter(Boolean));
    if (!ids.size) continue;
    const to = Object.keys(pages).find((a) => pages[a].status === "added" && !pages[a].from
      && (mp[a].elements || []).filter((e) => ids.has(e?.id)).length * 2 >= ids.size);
    if (!to) continue;
    pages[to] = { status: "renamed", from: r, ...pageChanges(bp[r], mp[to]) };
    rc.to = to; names[r] = to;
  }
  // Places in the rotation, of pages on both sides (a renamed one under its new name).
  const both = (n) => mp[n] && (bp[n] || Object.values(names).includes(n));
  const bseq = (base.rotation || []).map((n) => names[n] || n).filter(both), mseq = (mine.rotation || []).filter(both);
  const kept = lcs(bseq, mseq), placed = {};
  const left = (seq, used) => seq.filter((_, i) => !used.has(i));
  for (const n of new Set([...left(bseq, kept.a), ...left(mseq, kept.b)])) {
    placed[n] = !bseq.includes(n) ? "in" : !mseq.includes(n) ? "out" : "moved";
  }
  const settings = TOP_KEYS.filter((k) => !same(mine[k], base[k]));
  const rotation = !same(mine.rotation, base.rotation);
  return { pages, placed, rotation, settings, any: !!(Object.keys(pages).length || rotation || settings.length) };
}

/* A page's elements by ID, and its own settings (everything but its elements). */
function pageChanges(b, m) {
  const be = (b.elements || []).filter(Boolean), me = (m.elements || []).filter(Boolean);
  const bi = new Map(be.map((e) => [e.id, e])), mi = new Map(me.map((e) => [e.id, e]));
  // A group's box follows its members (syncGroups): moving them isn't a change of its own.
  const own = (e) => (e.type === "group" ? { ...e, ...Object.fromEntries(ARRANGE_KEYS.map((k) => [k, 0])) } : e);
  const added = me.filter((e) => !bi.has(e.id)).map((e) => e.id);
  const removed = be.filter((e) => !mi.has(e.id)).map((e) => e.id);
  const changed = me.filter((e) => bi.has(e.id) && !same(own(e), own(bi.get(e.id)))).map((e) => e.id);
  const order = !same(be.map((e) => e.id).filter((i) => mi.has(i)), me.map((e) => e.id).filter((i) => bi.has(i)));
  const { elements: _b, ...bs } = b, { elements: _m, ...ms } = m;
  return { elements: { added, removed, changed }, order, settings: !same(bs, ms) };
}

/* The longest run two sequences keep in the same order: which indexes of each are in it. */
function lcs(a, b) {
  const L = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--) L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const ka = new Set(), kb = new Set();
  for (let i = 0, j = 0; i < a.length && j < b.length;) {
    if (a[i] === b[j]) { ka.add(i++); kb.add(j++); } else if (L[i + 1][j] >= L[i][j + 1]) i++; else j++;
  }
  return { a: ka, b: kb };
}

/* Three-way merge: by page, then rotation, then each setting. A part changed
   on only one side takes that side; changed on both, differently, is a clash. */
export function merge(base, mine, theirs) {
  base = base || { pages: {} };
  const out = clone(theirs);
  const clashes = [];
  const ours = changes(base, mine), their = changes(base, theirs);
  for (const n of Object.keys(ours.pages)) {
    const m = mine.pages?.[n], t = theirs.pages?.[n];
    if (same(m, t)) continue;
    if (!their.pages[n]) { if (m) out.pages[n] = clone(m); else delete out.pages[n]; continue; }
    clashes.push({ kind: "page", name: n, mine: m, theirs: t });
  }
  // Page order: keep theirs, with any pages only you added at the end.
  const ordered = {};
  for (const k of Object.keys(out.pages)) ordered[k] = out.pages[k];
  out.pages = ordered;
  if (ours.rotation) {
    if (!their.rotation) out.rotation = clone(mine.rotation);
    else if (!same(theirs.rotation, mine.rotation)) clashes.push({ kind: "rotation", name: "rotation", mine: mine.rotation, theirs: theirs.rotation });
  }
  for (const k of ours.settings) {
    if (!their.settings.includes(k)) out[k] = clone(mine[k]);
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

  /* What the panel doesn't have yet (`changes`), worked out once per version of the pages. */
  pending() {
    const key = this.hist[this.hpos];
    if (this._pending?.key !== key || this._pending.live !== this.live) this._pending = { key, live: this.live, c: changes(this.live, this.spec) };
    return this._pending.c;
  }

  /* One page back to what the panel has: its content, its name and its place
     in the rotation. One undoable step, like everything else. */
  revertPage(name) {
    const c = changes(this.live, this.spec), p = c.pages[name];
    const names = [...new Set([name, p?.from, p?.to].filter(Boolean))];
    for (const n of names) { if (this.live.pages[n]) this.spec.pages[n] = clone(this.live.pages[n]); else delete this.spec.pages[n]; }
    let rot = this.spec.rotation.filter((n) => !names.includes(n));
    const lr = this.live.rotation;
    lr.forEach((n, i) => {
      if (!names.includes(n)) return;
      // After the page it follows on the panel, or first.
      let at = 0;
      for (let k = i - 1; k >= 0; k--) { const j = rot.lastIndexOf(lr[k]); if (j >= 0) { at = j + 1; break; } }
      rot.splice(at, 0, n);
    });
    this.spec.rotation = rot;
    if (!this.spec.pages[this.cur]) this.cur = (p?.from && this.spec.pages[p.from]) ? p.from : this.firstPage();
    this.sel = [];
    this.commit();
  }

  /* One setting sent with the pages back to what the panel has. */
  revertSetting(k) {
    this.spec[k] = clone(this.live[k]);
    this.commit();
  }

  /* Throw away everything not sent: one undoable step. */
  revert() {
    this.spec = clone(this.live);
    if (!this.spec.pages[this.cur]) this.cur = this.firstPage();
    this.sel = [];
    this.commit();
  }
}
