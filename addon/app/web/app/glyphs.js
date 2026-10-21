// Icons in the editor, drawn from the same outlines the panel draws: the
// sets the add-on has (GET /api/icons: Material Design, copied from Home
// Assistant or shipped, and custom sets), and each icon's outline fetched in
// pages as it's shown (POST /api/icons/outlines; render/icons.py). The
// picker offers exactly these, so it never offers an icon the panel can't
// draw. An outline is numbers only, built into an <svg> here with
// setAttribute: nothing from a custom SVG file is ever shown as it is.
// No imports from util.js: the tests read this file under node.

const NS = "http://www.w3.org/2000/svg";
const GRID = [0, 0, 24, 24];
const PAGE = 600;                         // outlines asked for at once (the route's limit)

/* "mdi:cat" for "cat", "mdi:Cat" or "mdi:cat"; a custom set's names keep their case. */
export function fullName(name) {
  const s = String(name ?? "").trim();
  const i = s.indexOf(":");
  if (i < 0) return s ? "mdi:" + s.toLowerCase() : "";
  const prefix = s.slice(0, i).trim().toLowerCase(), rest = s.slice(i + 1).trim();
  return rest ? `${prefix}:${prefix === "mdi" ? rest.toLowerCase() : rest}` : "";
}
export const prefixOf = (name) => fullName(name).split(":")[0];
export const shortName = (name) => fullName(name).replace(/^[^:]*:/, "");

/* An outline record (render/vector) as what an <svg> needs: { view, layers: [{ d, rule } | { d, width }] }. */
export function layersOf(record) {
  if (typeof record === "string") return { view: GRID, layers: [{ d: record, rule: "nonzero" }] };
  if (!record || typeof record !== "object") return null;
  const view = Array.isArray(record.v) && record.v.length === 4 ? record.v.map(Number) : GRID;
  const layers = [];
  if (record.d) layers.push({ d: String(record.d), rule: "nonzero" });
  if (record.e) layers.push({ d: String(record.e), rule: "evenodd" });
  for (const s of Array.isArray(record.s) ? record.s : []) if (Array.isArray(s) && s[0]) layers.push({ d: String(s[0]), width: Number(s[1]) || 1 });
  return { view, layers };
}

function paint(svg, record) {
  const got = layersOf(record);
  if (!got) return;
  svg.setAttribute("viewBox", got.view.join(" "));
  svg.replaceChildren(...got.layers.map((l) => {
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", l.d);
    if (l.width) { p.setAttribute("fill", "none"); p.setAttribute("stroke", "currentColor"); p.setAttribute("stroke-width", String(l.width)); p.setAttribute("stroke-linecap", "round"); p.setAttribute("stroke-linejoin", "round"); }
    else p.setAttribute("fill-rule", l.rule);
    return p;
  }));
  svg.classList.add("drawn");
}

/* Which icons match a search: by name, Material Design's categories through `terms` (a word ->
   names it means, legacy.js CATEGORY_TERMS), whole words first. `names`: { prefix: [name] };
   `only` limits it to one set. Full names ("phu:France2"), at most `most`. */
export function search(names, q, { only = "", terms = {}, popular = [], most = 250 } = {}) {
  const out = [], seen = new Set();
  const prefixes = Object.keys(names || {}).filter((p) => !only || p === only);
  const sets = Object.fromEntries(prefixes.map((p) => [p, new Set(names[p])]));
  const push = (p, n) => { const k = `${p}:${n}`; if (!seen.has(k) && sets[p]?.has(n)) { seen.add(k); out.push(k); } };
  q = String(q || "").trim();
  const qp = q.includes(":") ? q.slice(0, q.indexOf(":")).toLowerCase() : "";
  if (qp && sets[qp]) return search({ [qp]: names[qp] }, q.slice(q.indexOf(":") + 1), { terms, popular, most });
  const low = q.toLowerCase();
  if (!low) {
    if (sets.mdi) popular.forEach((n) => push("mdi", n));
    for (const p of prefixes) for (const n of names[p]) { if (out.length >= Math.min(most, 96)) return out; push(p, n); }
    return out;
  }
  const words = (terms[low] || low.split(/\s+/)).filter(Boolean);
  if (sets.mdi) words.forEach((w) => push("mdi", w));
  const pass = (test) => { for (const w of words) for (const p of prefixes) for (const n of names[p]) { if (out.length >= most) return; if (test(n.toLowerCase(), w)) push(p, n); } };
  pass((n, w) => n === w);
  pass((n, w) => n.startsWith(w) || n.includes("-" + w) || n.includes("/" + w));
  pass((n, w) => n.includes(w));
  return out;
}

export class Glyphs {
  /* `post(path, body)` and `get(path)` return the parsed JSON (the editor's api, or a stand-in). */
  constructor(get, post) {
    this.get = get; this.post = post;
    this.sets = null; this.names = {}; this.known = new Set();
    this.outlines = new Map(); this.pending = new Map(); this.timer = 0; this.waiters = [];
  }
  ready() { return this.sets !== null; }
  whenReady(f) { if (this.ready()) f(); else this.waiters.push(f); }
  async load() {
    try {
      const got = await this.get("api/icons");
      this.sets = Array.isArray(got?.sets) ? got.sets : [];
      this.names = got?.names && typeof got.names === "object" ? got.names : {};
    } catch (_) {
      // Not this time: the picker says it's loading, and the list is asked for again shortly.
      setTimeout(() => this.load().then(() => this.onLoad?.()), (this.tries = (this.tries || 0) + 1) < 5 ? 2000 : 15000);
      return;
    }
    this.known = new Set(Object.entries(this.names).flatMap(([p, ns]) => ns.map((n) => `${p}:${n}`)));
    const w = this.waiters; this.waiters = []; w.forEach((f) => f());
  }
  /* Whether the panel can draw it (the add-on's own "custom:" drawings aren't outlines). */
  has(name) { return this.known.has(fullName(name)); }
  setName(prefix) { return (this.sets || []).find((s) => s.prefix === prefix)?.name || prefix; }
  search(q, opts = {}) { return search(this.names, q, opts); }
  /* An <svg> for the icon, sized 1em by the stylesheet: drawn now when its outline is here, else as
     soon as it arrives (the space is kept, so nothing moves). Empty for one the panel can't draw. */
  node(name, cls = "") {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", ("glyph-svg " + cls).trim());
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    svg.setAttribute("viewBox", GRID.join(" "));
    const k = fullName(name);
    if (!k) return svg;
    if (this.outlines.has(k)) { paint(svg, this.outlines.get(k)); return svg; }
    const ask = () => {
      if (!this.has(k)) return;
      if (!this.pending.has(k)) this.pending.set(k, []);
      this.pending.get(k).push(svg);
      if (!this.timer) this.timer = setTimeout(() => this.fetch(), 0);
    };
    if (this.ready()) ask(); else this.whenReady(ask);
    return svg;
  }
  async fetch() {
    this.timer = 0;
    // Asking again: only icons still on screen (a closed picker's aren't asked for).
    if (this.wait) for (const [k, svgs] of this.pending) { const still = svgs.filter((s) => s.isConnected !== false); if (still.length) this.pending.set(k, still); else this.pending.delete(k); }
    const want = [...this.pending.keys()].slice(0, PAGE);
    const nodes = want.map((k) => [k, this.pending.get(k)]);
    want.forEach((k) => this.pending.delete(k));
    if (!want.length) return;
    if (this.pending.size) this.timer = setTimeout(() => this.fetch(), 0);
    let got;
    try { got = (await this.post("api/icons/outlines", { names: want }))?.icons || {}; } catch (_) { got = null; }
    if (got === null) {
      // The add-on didn't answer (restarting, or the connection dropped): ask again for the icons
      // still on screen, a little later each time, so none is left blank for good.
      for (const [k, svgs] of nodes) {
        const still = svgs.filter((s) => s.isConnected !== false);
        if (still.length) this.pending.set(k, [...(this.pending.get(k) || []), ...still]);
      }
      this.wait = Math.min(30000, (this.wait || 1000) * 2);
      if (this.pending.size && !this.timer) this.timer = setTimeout(() => this.fetch(), this.wait);
      return;
    }
    this.wait = 0;
    for (const [k, svgs] of nodes) {
      if (!(k in got)) continue;
      this.outlines.set(k, got[k]);
      svgs.forEach((s) => paint(s, got[k]));
    }
  }
}
