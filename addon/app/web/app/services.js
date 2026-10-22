// Outside services in the editor (services.py, the add-on's one list of them): the status card's
// lines for the ones whose problem sensor is on, and Settings › Services, where every service shows
// what uses it, how it's doing in plain words, and Try again. Nothing here asks a service on its
// own: only Try again does, because a person pressed it.

import { h, api, pageTitle } from "./util.js";
import { catalog } from "./catalog.js";

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
  return s.used_by?.length ? "Not asked yet." : "Not asked: nothing uses it now.";
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
      tryBtn ? h("span", { class: "rowbtns" }, tryBtn) : null);
    return r;
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
    box.replaceChildren(...parts);
    if (focus) {
      const at = box.querySelector(`.gr.svc[data-id="${CSS.escape(focus)}"]`);
      if (at) { at.classList.add("focus"); at.scrollIntoView({ block: "center" }); at.querySelector("button")?.focus({ preventScroll: true }); }
      focus = null;
    }
  }
  await load();
}
