// What a Stocks and coins page shows (the markets widget's `holdings`), picked
// in place: up to eight, found by name or symbol on any exchange (a Bucharest,
// Frankfurt or Tokyo listing, an index, a currency pair, a coin), each with a
// name you may change, in the order you drag them to (or Alt with ↑ and ↓).
// The same editor serves New page's step and the inspector. The search is the
// add-on's (GET /api/markets/find, which asks Yahoo Finance and CoinGecko only
// while you type); how the rows are laid out is the renderer's.

import { h, icon, api } from "./util.js";

/* `el.holdings`: [{ symbol, label, name }] or [{ coin, currency, label, name }]. `name` is what the
   search called it, kept so the list reads; the page shows `label` when you give one. */
export const keyOf = (x) => (x.coin ? `coin:${x.coin}` : `quote:${x.symbol}`);
export const holdingOf = (found) => (found.kind === "coin"
  ? { coin: found.symbol, currency: "", label: "", name: found.name }
  : { symbol: found.symbol, label: "", name: found.name });

export function holdingsEditor(el, changed, { most = 8, live = false } = {}) {
  if (!Array.isArray(el.holdings)) el.holdings = [];
  let searching = el.holdings.length === 0;          // an empty list opens on its search
  const box = h("div", { class: "cities holdings" });
  const nameOf = (x) => x.name || x.symbol || x.coin || "";
  const codeOf = (x) => (x.coin ? "Coin" : x.symbol);

  function move(from, to) {
    if (to < 0 || to >= el.holdings.length || to === from) return;
    const [x] = el.holdings.splice(from, 1); el.holdings.splice(to, 0, x);
    draw(); changed();
    box.querySelectorAll(".zgrip")[to]?.focus();
  }

  function search() {
    const q = h("input", { type: "search", placeholder: "A company, an index, a currency or a coin", "aria-label": "Search", autocomplete: "off", spellcheck: "false" });
    const list = h("div", { class: "optlist", role: "listbox", "aria-label": "Found" });
    const say = h("p", { class: "fnote", role: "status", "aria-live": "polite" });
    let timer = 0, slow = 0, asked = 0;
    const hint = () => list.replaceChildren(h("p", { class: "empty-note", text: "Type a name or a symbol: Banca Transilvania or TLV.RO, DAX, EUR RON, Bitcoin." }));
    const find = async () => {
      const s = q.value.trim();
      if (s.length < 2) { hint(); say.textContent = ""; return; }
      const mine = ++asked;
      clearTimeout(slow);
      slow = setTimeout(() => { if (mine === asked) say.textContent = "Searching…"; }, 400);   // only if it's slow
      let got;
      try { got = await api(`api/markets/find?q=${encodeURIComponent(s)}`); } catch (e) { got = { body: { error: e.message } }; }
      if (mine !== asked) return;
      clearTimeout(slow); say.textContent = "";
      const found = got.body?.found;
      if (!found) { list.replaceChildren(h("p", { class: "empty-note", text: got.body?.error || "The search didn't answer. Try again in a minute." })); return; }
      const have = new Set(el.holdings.map(keyOf));
      list.replaceChildren(...found.map((f) => {
        const added = have.has(keyOf(holdingOf(f)));
        return h("button", { class: "opt", role: "option", "aria-selected": String(added), disabled: added || el.holdings.length >= most,
          onclick: () => { el.holdings.push(holdingOf(f)); searching = el.holdings.length < most && searching; draw(); changed(); box.querySelector('input[type="search"]')?.focus(); } },
          h("span", { class: "ock", "aria-hidden": "true" }, added ? icon("check", "sm") : null),
          h("span", { class: "otext" }, h("span", { class: "o1", text: f.name }), h("span", { class: "o2", text: f.kind === "coin" ? f.where : [f.symbol, f.where].filter(Boolean).join(" · ") })));
      }));
      if (!found.length) list.append(h("p", { class: "empty-note", text: "Nothing by that name. Try its symbol as the exchange writes it, or a shorter name." }));
    };
    q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(find, 350); });
    q.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); clearTimeout(timer); find(); }
      if (e.key === "Escape" && el.holdings.length) { e.preventDefault(); e.stopPropagation(); searching = false; draw(); box.querySelector(".btnrow .btn")?.focus(); }
    });
    hint();
    return h("div", { class: "picker zpick", "data-own-esc": "" }, h("div", { class: "search" }, icon("search", "sm"), q), say, list);
  }

  function row(x, k) {
    const label = h("input", { class: "inp", value: x.label || "", placeholder: nameOf(x), maxlength: "40", autocomplete: "off", spellcheck: "false", "aria-label": `Name for ${nameOf(x)}` });
    label.addEventListener(live ? "input" : "change", () => { x.label = label.value.trim(); changed(); });
    const grip = h("button", { class: "btn icon zgrip", "aria-label": `Move ${nameOf(x)}. Drag, or Alt with an arrow key`, title: "Drag to reorder" }, icon("grip", "sm"));
    grip.addEventListener("keydown", (e) => {
      if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) { e.preventDefault(); move(k, k + (e.key === "ArrowUp" ? -1 : 1)); }
    });
    dragToReorder(grip, k);
    return h("div", { class: "gr zrow", role: "listitem" }, grip,
      h("span", { class: "hcode", text: codeOf(x), title: nameOf(x) }),
      label,
      h("button", { class: "btn icon", "aria-label": `Remove ${nameOf(x)}`, onclick: () => { el.holdings.splice(k, 1); searching = searching || !el.holdings.length; draw(); changed(); } }, icon("close", "sm")));
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
    box.replaceChildren(...[
      el.holdings.length ? h("div", { class: "group zlist", role: "list", "aria-label": "Holdings" }, ...el.holdings.map(row)) : null,
      searching && el.holdings.length < most ? search() : null,
      !searching && el.holdings.length < most
        ? h("div", { class: "btnrow" }, h("button", { class: "btn tinted", onclick: () => { searching = true; draw(); box.querySelector('input[type="search"]')?.focus(); } }, icon("plus", "sm"), "Add"))
        : el.holdings.length >= most ? h("p", { class: "fnote", text: `Up to ${most} on a page.` }) : null,
      el.holdings.some((x) => x.coin) ? h("p", { class: "fnote", text: "Coins are priced in your Home Assistant currency." }) : null,
    ].filter(Boolean));
  }
  draw();
  return box;
}
