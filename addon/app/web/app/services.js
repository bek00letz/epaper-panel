// Outside services in the editor (services.py, the add-on's one list of them): the status card's
// lines for the ones whose problem sensor is on, and Settings › Services, where every service shows
// what uses it, how it's doing in plain words, and Try again. Nothing here asks a service on its
// own: only Try again does, because a person pressed it.

import { h, api, pageTitle } from "./util.js";
import { catalog } from "./catalog.js";
import { toggleRow, toast } from "./ui.js";

const GROUPS = [["outside", "Outside services"], ["home", "Home Assistant"], ["source", "Your data sources"]];

/* A time of day as Settings › Time and language says (12- or 24-hour), with the weekday when it
   wasn't today. `sec`: seconds since 1970, as health records them. */
export function clockAt(sec) {
  if (!sec) return "";
  const d = new Date(sec * 1000), today = new Date();
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hourCycle: catalog().time_format === "12h" ? "h12" : "h23" });
  if (d.toDateString() === today.toDateString()) return time;
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
  return `${d.toDateString() === yesterday.toDateString() ? "yesterday" : d.toLocaleDateString([], { weekday: "long" })} ${time}`;
}

/* How a service is doing, in one line. */
export function stateLine(s) {
  if (s.problem) return `Not answering since ${clockAt(s.failing_since)}.`;
  if (s.failing_since) return `Didn't answer at ${clockAt(s.failing_since)}. Trying again.`;
  if (s.ok_at) return `Answered at ${clockAt(s.ok_at)}.`;
  return s.by_pages && !s.used_by?.length ? "Not asked: no page uses it now." : "Not asked yet.";
}

const listed = (names) => (names.length < 3 ? names.join(" and ") : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`);
const usedBy = (s) => (s.used_by?.length ? `Used by ${listed(s.used_by.map(pageTitle))}` : s.gives || "");

/* The status card's part: one line per service whose problem sensor is on, each opening Settings ›
   Services at it. Nothing at all when every service is answering. */
export function problemLines(app, close, openServices) {
  const problems = app.status?.service_problems || [];
  if (!problems.length) return [];
  const rows = problems.map((p) => h("div", { class: "urow" },
    h("button", { class: "uopen svc", "aria-label": `${p.name}: not answering since ${clockAt(p.since)}. ${p.plain} Open it in Settings`, onclick: () => { close(); openServices(p.id); } },
      h("span", { class: "un" }, h("span", { class: "led bad", "aria-hidden": "true" }), p.name),
      h("span", { class: "uw", text: `Not answering since ${clockAt(p.since)}. ${p.plain}` }))));
  return [h("div", { class: "poplab", text: "Outside services" }), h("div", { class: "ulist", role: "group", "aria-label": "Outside services not answering" }, ...rows),
    h("p", { class: "fnote", text: problems.length === 1 ? "Pages that use it keep what they last had." : "Pages that use them keep what they last had." })];
}

/* Settings › Services. `focus`: a service's id, scrolled to and outlined (from the status card). */
export async function servicesPane(app, pane, focus) {
  const box = h("div");
  pane.append(h("p", { class: "fnote", text: "What the add-on asks outside your pages' sensors, and how each one is doing. A service is only asked when a page needs it, or when you press Try again." }), box);
  let list = null;
  // "Change service addresses" (Advanced): off every time Settings opens, so an address field is
  // only ever in reach after reading what it's for.
  let changing = false;
  const marked = focus;
  // The list is the add-on's answer; it fades in only when it's slow (editor.css), so a quick one never flashes.
  box.replaceChildren(h("p", { class: "fnote waiting", text: "Getting the services…" }));

  async function load() {
    try { list = (await api("api/services")).body.services; }
    catch (e) {
      box.replaceChildren(h("p", { class: "fnote bad", text: `Couldn't read the services: ${e.message}` }),
        h("div", { class: "btnrow" }, h("button", { class: "btn tinted", onclick: load }, "Try again")));
      return;
    }
    draw();
  }

  function row(s) {
    const status = h("small", { class: s.problem || s.failing_since ? "bad" : "", text: stateLine(s) });
    const why = s.plain ? h("small", { class: "bad", text: s.plain }) : null;
    // The add-on's own words for it, small, for whoever reports it: never a header or a key (health.describe).
    const detail = s.error && s.error !== s.plain ? h("small", { class: "detail", text: s.error }) : null;
    const said = h("small", { role: "status", "aria-live": "polite" });
    const what = h("small", { text: usedBy(s) });
    const tryBtn = s.can_try ? h("button", { class: "btn tinted", "aria-label": `Try ${s.name} again`, onclick: () => tryAgain(s, tryBtn, said) }, "Try again") : null;
    const r = h("div", { class: "gr svc", data: { id: s.id } }, h("span", { class: "gl" }, s.name, what, status, why, detail, said),
      tryBtn ? h("span", { class: "rowbtns" }, tryBtn) : null, ...(s.addresses || []).flatMap((a) => addressRows(s, a)));
    return r;
  }

  /* An address of a service: when it's the person's own, it says so with the way back, always in
     reach; with "Change service addresses" on, a field and Check and use. */
  function addressRows(s, a) {
    const own = a.current !== a.original;
    const several = s.addresses.length > 1;
    const out = [];
    if (own) out.push(h("div", { class: "addr" },
      h("small", {}, `${several ? a.label + ": u" : "U"}sing your address `, h("code", { text: a.current })),
      h("button", { class: "btn tinted", onclick: () => setAddress(s, a, "", a.current) }, "Use the original address")));
    if (!changing || !a.changeable) return out;
    const said = h("small", { class: "addrsaid", role: "status", "aria-live": "polite" });
    const field = h("input", { class: "inp", type: "url", inputmode: "url", autocomplete: "off", spellcheck: "false",
      "aria-label": `Another address for ${s.name}${several ? `, ${a.label}` : ""}`, placeholder: a.original, value: own ? a.current : "" });
    const go = h("button", { class: "btn tinted", onclick: () => setAddress(s, a, field.value.trim(), null, go, said) }, "Check and use");
    field.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go.click(); } });
    out.push(h("div", { class: "addr edit" }, h("label", { class: "addrlab", text: several ? a.label : "Address" }), field, go, said));
    return out;
  }

  /* Check an address with the add-on's own reader and use it, or say why not. "" is the original;
     `back` (the address it had) offers Undo. */
  async function setAddress(s, a, address, back, btn, said) {
    if (btn) btn.disabled = true;
    const slow = said && setTimeout(() => { said.className = "addrsaid waiting"; said.textContent = "Checking what it answers…"; }, 400);
    let got;
    try { got = (await api(`api/services/${encodeURIComponent(s.id)}/address`, { method: "PUT", body: { key: a.key, address } })).body; }
    catch (e) { got = { ok: false, error: e.message }; }
    clearTimeout(slow);
    if (btn) btn.disabled = false;
    if (!got.ok) {
      if (said) { said.className = "addrsaid bad"; said.textContent = `Not used: ${got.error}`; }
      else toast(`Couldn't change it: ${got.error}`);
      return;
    }
    list = got.services || list;
    draw();
    if (address) toast(`${s.name} uses your address now. It answered: ${got.said}.`);
    else toast(`${s.name} is back on its original address.`, back ? { label: "Undo", run: () => setAddress(s, a, back) } : null);
  }

  async function tryAgain(s, btn, said) {
    btn.disabled = true;
    // "Asking…" only once it's taken a moment: a quick answer never flashes it.
    const slow = setTimeout(() => { said.className = "waiting"; said.textContent = "Asking…"; }, 400);
    let got;
    try { got = (await api(`api/services/${encodeURIComponent(s.id)}/try`, { method: "POST" })).body; }
    catch (e) { got = { ok: false, error: e.message }; }
    clearTimeout(slow);
    btn.disabled = false;
    try { list = (await api("api/services")).body.services; } catch (_) { /* keep what's shown */ }
    draw();
    const now = box.querySelector(`.gr.svc[data-id="${CSS.escape(s.id)}"]`);
    const out = now?.querySelector("small[role=status]");
    if (out) { out.className = got.ok ? "good" : "bad"; out.textContent = got.ok ? `It answered: ${got.said}.` : `It didn't work: ${got.error}`; }
    now?.querySelector("button")?.focus({ preventScroll: true });
    app.poll?.();                                // the status card's lines follow
  }

  function draw() {
    const parts = [];
    for (const [g, title] of GROUPS) {
      const rows = list.filter((s) => s.group === g);
      if (!rows.length) continue;
      parts.push(h("h4", { class: "gtitle", text: title }), h("div", { class: "group" }, ...rows.map(row)));
    }
    if (list.some((s) => (s.addresses || []).some((a) => a.changeable))) {
      parts.push(h("h4", { class: "gtitle", text: "Advanced" }), h("div", { class: "group advanced" },
        toggleRow("Change service addresses", changing, (v) => { changing = v; draw(); box.querySelector(".advanced .switch")?.focus({ preventScroll: true }); },
          "Only touch this if you know what you're doing. Another address has to answer exactly like the original, as a mirror does. The add-on checks what it answers before using it.")));
    }
    box.replaceChildren(...parts);
    // The row the status card opened stays marked while the pane is open; it's scrolled to once.
    const at = marked && box.querySelector(`.gr.svc[data-id="${CSS.escape(marked)}"]`);
    if (at) at.classList.add("focus");
    if (at && focus) { at.scrollIntoView({ block: "center" }); at.querySelector("button")?.focus({ preventScroll: true }); }
    focus = null;
  }
  await load();
}
