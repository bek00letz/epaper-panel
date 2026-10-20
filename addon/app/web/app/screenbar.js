// The screen bar under the canvas: how this screen runs, always in sight. Folded,
// a pill says it in one line; open, a row of cards changes it. Like Control Center
// next to Settings: these four are also in Settings › Screen, which has the rest.
// Nothing else gets a second place (AGENTS.md, Editor design decisions).

import { h, icon, prefs, span, seconds } from "./util.js";
import { select, seg, toggle } from "./ui.js";
import { openSettings, changeTimers, updateSaid, rotateOptions, rotateChange, ORIENTATIONS, setMounted } from "./sheets.js";

const short = (text) => text.replace(/ seconds?/, " s").replace(/ minutes?/, " min").replace(/ hours?/, " h");

/* One line: power, how pages turn, quiet hours. Also the pill's spoken label. */
export function screenLine(app) {
  const t = app.screen?.timing, qh = app.doc.spec?.quiet_hours || {};
  if (!t) return "";
  const power = t.always_on ? "Always on" : `Sleeps · updates every ${short(span(t.update_minutes))}`;
  const pages = `next page every ${short(t.always_on ? seconds(t.rotate_seconds) : span(t.update_minutes * t.rotate_updates))}`;
  const quiet = qh.enabled ? `quiet ${qh.start}–${qh.end}` : "no quiet hours";
  return `${power} · ${pages} · ${quiet}`;
}

export function renderScreenBar(app) {
  const host = app.el.screenbar, scr = app.screen, t = scr?.timing;
  if (!host) return;
  // Toasts rise above the bar instead of covering it (#toast in editor.css).
  if (!host.dataset.watched) {
    host.dataset.watched = "1";
    const room = () => document.documentElement.style.setProperty("--sb-room", `${Math.max(0, Math.round(innerHeight - host.getBoundingClientRect().top))}px`);
    new ResizeObserver(room).observe(host);
    addEventListener("resize", room);
    host.room = room;
  }
  if (!scr || !t || !app.doc.spec) { host.replaceChildren(); host.room(); return; }
  // Keep focus where it was across a redraw (a change redraws everything).
  const had = host.contains(document.activeElement) ? document.activeElement.dataset.k : null;
  const open = prefs.get("screenbar") === "open";
  host.classList.toggle("open", open);
  const setOpen = (v, focusKey) => {
    prefs.set("screenbar", v ? "open" : "closed");
    renderScreenBar(app);
    host.querySelector(`[data-k="${focusKey}"]`)?.focus({ preventScroll: true });
  };
  const line = screenLine(app);

  if (!open) {
    host.replaceChildren(h("button", { class: "sbpill", data: { k: "pill" }, "aria-expanded": "false", "aria-controls": "screenbar",
      "aria-label": `${scr.name}: ${line}. Show the screen's settings`, onclick: () => setOpen(true, "power") },
      icon(t.always_on ? "plug" : "moon", "sm"), h("span", { class: "sbline", text: line }), icon("down", "sm up")));
  } else {
    const spec = app.doc.spec, qh = spec.quiet_hours || {}, info = scr.info || {}, pairs = scr.setup === "pair";
    const sleepChoices = t.update_choices.filter((m) => m !== 1);
    const every = select(sleepChoices.map((m) => [m, `Every ${span(m)}`]), t.always_on ? t.asleep_default : t.update_minutes,
      (v) => changeTimers(app, scr, { update_minutes: Number(v) }, updateSaid(Number(v))), { "aria-label": "Updates every", data: { k: "every" } });
    const card = (label, ...kids) => h("div", { class: "sbcard", role: "group", "aria-label": label }, h("span", { class: "sbl", text: label }), ...kids);
    const power = t.can_stay_on
      ? card("Power", seg([["on", "Always on"], ["sleep", "Sleeps"]], t.always_on ? "on" : "sleep", (v) => {
        if ((v === "on") === t.always_on) return;
        const m = v === "on" ? 1 : t.asleep_default;
        changeTimers(app, scr, { update_minutes: m }, updateSaid(m));
      }, "Power"), t.always_on ? h("span", { class: "sbsub", text: "Updates every minute" }) : every)
      : card("Power", h("span", { class: "sbsub", text: "Sleeps between updates" }), every);
    power.querySelectorAll(".segc button").forEach((b) => { b.dataset.k = b.getAttribute("aria-checked") === "true" ? "power" : "power-other"; });
    // A panel set to sleep whose firmware can't yet: say so, and where to fix it.
    if (!t.always_on && !pairs && !info.firmware_sleeps) power.append(h("button", { class: "linkbtn sbwarn", onclick: () => openSettings(app, "install") }, icon("warn", "sm"), "Needs new firmware"));
    const rotate = card("Next page", select(rotateOptions(t).map(([v, l]) => [v, t.always_on ? `Every ${l}` : l === "Every update" ? l : `Every ${l}`]),
      t.always_on ? t.rotate_seconds : t.rotate_updates, (v) => changeTimers(app, scr, ...rotateChange(t, v)), { "aria-label": "Next page every", data: { k: "rotate" } }));
    const quiet = card("Quiet hours",
      h("div", { class: "sbrow" }, h("button", { class: "linkbtn sbtimes", "aria-label": `Quiet hours ${qh.start} to ${qh.end}. Change the times in Settings`, onclick: () => openSettings(app, "quiet") }, `${qh.start}–${qh.end}`),
        toggle(!!qh.enabled, (v) => { qh.enabled = v; app.doc.commit(); }, "Quiet hours")),
      h("span", { class: "sbsub", text: "Sent with your pages" }));
    quiet.querySelector(".switch").dataset.k = "quiet";
    const mounted = card("Mounted", select(ORIENTATIONS, spec.orientation || 0, (v) => setMounted(app, v), { "aria-label": "Mounted", data: { k: "mounted" } }));
    const end = h("div", { class: "sbend" },
      h("button", { class: "btn icon", data: { k: "settings" }, "aria-label": `All of ${scr.name}'s settings`, title: "Settings › Screen", onclick: () => openSettings(app, "panel") }, icon("gear")),
      h("button", { class: "btn icon", data: { k: "close" }, "aria-label": "Hide the screen's settings", "aria-expanded": "true", title: "Hide", onclick: () => setOpen(false, "pill") }, icon("down")));
    host.replaceChildren(h("div", { class: "sbcards" }, power, rotate, quiet, mounted, end));
    host.onkeydown = (e) => { if (e.key === "Escape") { e.stopPropagation(); setOpen(false, "pill"); } };
  }
  if (had) host.querySelector(`[data-k="${had}"]`)?.focus({ preventScroll: true });
  host.room();
}
