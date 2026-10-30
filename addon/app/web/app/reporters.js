// AI usage: the computers that report it (reporters.py, docs/ai-usage.md). One place builds
// what a person sees about them, used twice: Settings › AI usage, and New page › AI usage's
// own next step (setup.js, SETUPS.reporter), so connecting works the same from either.
//
// Connecting is pairing, the TRMNL's way: a ten-minute window, a six-letter code and one
// command to paste into a terminal, on a Mac, Linux or Windows. The key never comes to the
// browser: the reporter is given it by the add-on and keeps it in the computer's own key store.

import { h, icon, api, isMac } from "./util.js";
import { toast, linkButton, seg } from "./ui.js";

// Each computer the reporter runs on: what it's called, and the three steps there.
export const PLATFORMS = {
  macos: { name: "Mac", own: "Mac", steps: [
    "On your Mac, open Terminal (in Applications › Utilities).",
    "Paste this command and press Return. It sets up a small reporter that reads Claude Code and Codex every 5 minutes.",
    "If your Mac asks, allow it to use your Keychain: that's where it keeps its key."] },
  linux: { name: "Linux", own: "Linux computer", steps: [
    "Open a terminal.",
    "Paste this command and press Return. It needs Python 3.9 or later and curl, and sets up a reporter that reads Claude Code and Codex every 5 minutes.",
    "It keeps its key in your desktop's key store, or in a file only you can read if there's none."] },
  windows: { name: "Windows", own: "Windows PC", steps: [
    "Open PowerShell from the Start menu.",
    "Paste this command and press Enter. It needs Python 3.9 or later from python.org, and sets up a reporter that reads Claude Code and Codex every 5 minutes.",
    "It keeps its key in a file Windows encrypts for your account."] },
};
const guessPlatform = () => (isMac ? "macos" : /Win/.test(navigator.platform || navigator.userAgent) ? "windows" : "linux");

const PROVIDERS_SAID = { not_found: "isn't on it", no_limits: "hasn't said its limits yet", error: "couldn't be read" };
const mmss = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

/* "14:05", "Yesterday 14:05", "Tue 28 Oct": when a computer last reported, as a person says it. */
export function heardWords(iso) {
  if (!iso) return "Not heard from yet";
  const t = new Date(iso), now = new Date();
  const hm = t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const days = Math.round((new Date(now.toDateString()) - new Date(t.toDateString())) / 86400000);
  if (days === 0) return `Last heard at ${hm}`;
  if (days === 1) return `Last heard yesterday at ${hm}`;
  return `Last heard ${t.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })}`;
}

export const computerName = (r) => r.name || PLATFORMS[r.platform]?.own || "Computer";

function copy(text, what) {
  const done = () => toast(`Copied ${what}.`);
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, fallback);
  else fallback();
  function fallback() {
    const t = h("textarea", { style: { position: "fixed", left: "-9999px" } }); t.value = text; document.body.append(t); t.select();
    let ok = false; try { ok = document.execCommand("copy"); } catch (_) { /* told below */ }
    t.remove();
    if (ok) done(); else toast("Your browser didn't allow copying. Select the command and copy it yourself.");
  }
}

/* Connect a computer: opens the window, shows the code and the command, and says when it joined.
   `onJoined(reporter)` once one has. Returns { node, dispose }. */
export function connectPart({ onJoined } = {}) {
  let info = null, left = 0, problem = "", poll = null, tick = null, joined = null, away = false, pf = guessPlatform();
  const node = h("div", { class: "stepsec connect" });
  const state = h("p", { class: "fnote pairstate", role: "status", "aria-live": "polite" });
  const stop = () => { clearInterval(poll); clearInterval(tick); poll = tick = null; };
  // Held back a moment, so a quick answer never flashes "Getting ready…".
  const slow = setTimeout(() => { if (!info && !problem) { node.replaceChildren(h("p", { class: "fnote", text: "Getting ready…" })); } }, 300);

  async function open() {
    problem = ""; joined = null;
    try { info = (await api("api/reporters/pair", { method: "POST" })).body; left = info.left; }
    catch (e) { problem = e.message; info = null; }
    clearTimeout(slow);
    draw(); start();
  }
  async function check() {
    try {
      const r = (await api("api/reporters/pair")).body || {};
      left = r.left;
      if (r.reporter && !joined) { joined = r.reporter; stop(); draw(); onJoined && onJoined(joined); return; }
    } catch (_) { /* the next poll tries again */ }
    drawState();
  }
  function start() {
    stop();
    if (problem) return;
    poll = setInterval(check, 3000);
    tick = setInterval(() => { if (left > 0) { left -= 1; drawState(); if (left === 0) draw(); } }, 1000);
  }
  function drawState() {
    if (!info || joined) return;
    state.classList.toggle("bad", left <= 0);
    state.replaceChildren(h("span", { class: "led " + (left > 0 ? "wait listening" : "bad") }),
      left > 0 ? ` Waiting for your computer · ${mmss(left)} left` : " The ten minutes are up and nothing connected. Run the command again after you get a new code.");
  }
  function draw() {
    if (problem) {
      node.replaceChildren(h("p", { class: "fnote bad", text: `Couldn't get a code: ${problem}` }),
        h("div", { class: "btnrow" }, h("button", { class: "btn tinted", onclick: open }, "Try again")));
      return;
    }
    if (!info) return;
    if (joined) {
      node.replaceChildren(h("div", { class: "pairdone" }, icon("check"), h("h3", { text: `${computerName(joined)} is connected` }),
        h("p", { class: "fnote", text: "Its first report comes within a minute, then every 5 minutes while it's awake." })));
      return;
    }
    const cmds = info.commands || {}, there = away && cmds.away ? cmds.away : cmds.home || {};
    const cmd = there[pf] || "", plat = PLATFORMS[pf];
    const code = h("code", { class: "sel addrtext cmd", text: cmd, "aria-label": `Command for ${pf === "windows" ? "PowerShell" : "Terminal"}` });
    node.replaceChildren(
      h("h3", { class: "slab", text: "Connect a computer" }),
      seg(Object.entries(PLATFORMS).map(([k, p]) => [k, p.name]), pf, (v) => { pf = v; draw(); node.querySelector('.segc [aria-checked="true"]')?.focus(); }, "Your computer"),
      h("ol", { class: "steps" }, ...plat.steps.map((t) => h("li", { text: t }))),
      h("div", { class: "addr" }, h("div", { class: "inline" }, code, h("button", { class: "btn tinted", onclick: () => copy(cmd, "the command") }, "Copy"))),
      h("p", { class: "fnote", text: `Its code is ${info.code}: it works once, for ten minutes. Your usage stays on your network, and no key or file leaves your computer.` }),
      cmds.away
        ? h("div", {}, linkButton(away ? "Use the home address instead" : "This computer travels: report from anywhere", () => { away = !away; draw(); }))
        : h("p", { class: "fnote", text: "To report away from home too, turn on Reaching home in Settings first." }),
      left <= 0 ? h("div", { class: "btnrow" }, h("button", { class: "btn primary", onclick: open }, "Get a new code")) : null,
      state);
    drawState();
  }
  open();
  return { node, dispose: () => { clearTimeout(slow); stop(); } };
}

/* What each computer reads, in words: "Reads Claude Code. Codex isn't on it." */
function readsWords(r, providers) {
  const mine = providers.filter((p) => (p.reporters || []).includes(r.id)).map((p) => p.name);
  const parts = [];
  if (mine.length) parts.push(`Reads ${mine.join(" and ")}.`);
  for (const s of r.skipped || []) parts.push(`${s.name} ${PROVIDERS_SAID[s.reason] || "wasn't read"}.`);
  return parts.join(" ");
}

/* Settings › AI usage. */
export async function reportersPane(app, pane) {
  let view = null;
  const list = h("div", { class: "group" });
  const below = h("div");
  let part = null;
  const say = h("p", { class: "fnote", role: "status", "aria-live": "polite" });
  pane.append(h("p", { class: "fnote", text: "Computers that report how much of your AI plans you've used. An AI usage page shows it, and each number is a sensor in Home Assistant too." }),
    list, below, say);

  async function load() {
    try { view = (await api("api/reporters")).body; say.textContent = ""; }
    catch (e) { say.textContent = `Couldn't read your computers: ${e.message}`; view = view || { reporters: [], providers: [] }; }
    draw();
  }
  function rename(r, inp) {
    const name = inp.value.trim();
    if (name === (r.name || "")) return;
    api(`api/reporters/${encodeURIComponent(r.id)}`, { method: "PUT", body: { name } })
      .then(() => { r.name = name; toast("Renamed."); }, (e) => { inp.value = r.name || ""; toast(`Couldn't rename it: ${e.message}`); });
  }
  async function remove(r) {
    try { await api(`api/reporters/${encodeURIComponent(r.id)}`, { method: "DELETE" }); }
    catch (e) { toast(`Couldn't remove it: ${e.message}`); return; }
    await load();
    toast(`Removed ${computerName(r)}. Its key stopped working.`, { label: "Undo", run: async () => {
      try { await api(`api/reporters/${encodeURIComponent(r.id)}/restore`, { method: "POST" }); await load(); }
      catch (e) { toast(`Couldn't put it back: ${e.message}`); }
    } });
  }
  function draw() {
    list.replaceChildren();
    const reps = view.reporters || [];
    if (!reps.length) list.append(h("div", { class: "gr" }, h("span", { class: "gl" }, "No computers yet", h("small", { text: "Connect one below. It takes a minute." }))));
    for (const r of reps) {
      const inp = h("input", { class: "inp", value: r.name || "", placeholder: computerName(r), maxlength: "32", "aria-label": "Name", autocomplete: "off", spellcheck: "false" });
      inp.addEventListener("change", () => rename(r, inp));
      inp.addEventListener("keydown", (e) => { if (e.key === "Enter") inp.blur(); });
      const reads = readsWords(r, view.providers || []);
      list.append(h("div", { class: "gr" },
        h("span", { class: "gl" }, inp, h("small", { text: [heardWords(r.heard_at) + (r.quiet ? ". It's been quiet for a while: is it asleep or off?" : "."), reads].filter(Boolean).join(" ") })),
        h("button", { class: "btn tinted danger", onclick: () => remove(r), "aria-label": `Remove ${computerName(r)}` }, "Remove")));
    }
    if (!part) below.replaceChildren(h("div", { class: "btnrow" }, h("button", { class: "btn tinted", onclick: connect }, reps.length ? "Connect another computer" : "Connect a computer")));
  }
  function connect() {
    part = connectPart({ onJoined: () => setTimeout(load, 1500) });
    below.replaceChildren(part.node);
  }
  await load();
}
