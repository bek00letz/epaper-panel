/* Phone notifications for a page (notify.py, ARCHITECTURE.md › Phone notifications).

   The editor never sends one and keeps no notification settings: "Also notify
   my phone…" makes a normal automation in Home Assistant from the add-on's
   blueprint, with the phones picked here; after that the page only says what
   uses its sensor, with a link to change it in Home Assistant. A page's
   `notify` id is all the page keeps. */
import { h, icon, api, pageTitle } from "./util.js";
import { sheet, menu, toast, linkButton } from "./ui.js";

// Answers are kept a while, so redrawing the inspector doesn't make the line blink.
const asked = new Map();
function askStatus(nid, fresh = false) {
  const had = asked.get(nid);
  if (had && !fresh && Date.now() - had.at < 15000) return had;
  const entry = { at: Date.now(), got: had?.got, done: null };
  entry.done = api("api/notify?id=" + encodeURIComponent(nid))
    .then((r) => { entry.got = r.body; return entry; }, (e) => { entry.got = { ready: true, problem: e.message, automations: [] }; return entry; });
  asked.set(nid, entry);
  return entry;
}

function newId() {
  const a = new Uint8Array(8);
  crypto.getRandomValues(a);
  return [...a].map((b) => "0123456789abcdefghijklmnopqrstuvwxyz"[b % 36]).join("");
}

const nameOf = (app, id) => app.entMap.get(id)?.name || id;
function names(app, ids) {
  const n = ids.map((id) => nameOf(app, id));
  return n.length <= 1 ? n.join("") : n.slice(0, -1).join(", ") + " and " + n[n.length - 1];
}
const editUrl = (a) => "/config/automation/edit/" + encodeURIComponent(a.id);
function haLink(a) {
  // The editor is inside Home Assistant (Ingress): the automation opens in its window, not the frame.
  return h("a", { class: "linkbtn inline", href: editUrl(a), target: "_top" }, "Edit in Home Assistant");
}

/* Under "Shows": the page's notifications, or the way to set one up. */
export function notifyRows(app, p, name) {
  const wrap = h("div", { class: "notify", "aria-live": "polite" });
  const nid = p.notify;
  if (!nid) {
    if ((p.tier || "rotate") !== "rotate") wrap.append(linkButton("Also notify my phone…", (e) => openSetup(app, p, name, e.currentTarget)));
    return wrap;
  }
  // Held back (its space kept) until there's an answer, so it doesn't flash "checking".
  const line = h("div", { class: "note pending", role: "note" }, h("span", { class: "led" }), h("span", { text: "Checking Home Assistant…" }));
  wrap.append(line);
  const fill = (entry) => {
    const s = entry.got;
    if (!s) return;
    const rows = [];
    const ours = s.automations.filter((a) => a.ours), theirs = s.automations.filter((a) => !a.ours);
    if (!s.ready || s.problem) rows.push(h("p", { class: "note warn" }, icon("warn", "sm"), h("span", { text: s.problem })));
    for (const a of ours) rows.push(h("div", { class: "note info nrow" }, icon("bell", "sm"),
      h("span", { text: a.targets.length ? `Notifies ${names(app, a.targets)}` : `Used by “${a.name}”` }), haLink(a)));
    for (const a of theirs) rows.push(h("div", { class: "note info nrow" }, icon("bell", "sm"), h("span", { text: `Used by “${a.name}”` }), haLink(a)));
    if (s.ready && !s.problem && !s.automations.length)
      rows.push(h("p", { class: "fnote", text: "Nothing in Home Assistant notifies you about it any more." }),
        linkButton("Also notify my phone…", (e) => openSetup(app, p, name, e.currentTarget)));
    if ((p.tier || "rotate") === "rotate")
      rows.push(h("p", { class: "fnote", text: "It doesn't notify while the page always shows. Pick Only when or As an alert." }));
    if (s.ready) rows.push(linkButton("Stop notifying", (e) => stopNotifying(app, p, name, s, e.currentTarget)));
    wrap.replaceChildren(...rows);
  };
  const entry = askStatus(nid);
  fill(entry);
  entry.done.then(fill);
  setTimeout(() => line.classList.replace("pending", "waiting"), 600);
  return wrap;
}

/* "Also notify my phone…": pick what to notify; the add-on makes the automation. */
async function openSetup(app, p, name) {
  let targets = null, problem = "";
  try { targets = (await api("api/notify/targets")).body.targets; } catch (e) { problem = e.message; }
  const st = (await askStatus("", true).done).got;
  if (st && !st.ready) problem = st.problem;
  const phones = (targets || []).filter((t) => t.phone);
  const chosen = new Set(phones.length === 1 ? [phones[0].entity_id] : []);
  const title = pageTitle(name);
  sheet("Notify your phone", (node, close) => {
    const list = h("div", { class: "optlist", role: "group", "aria-label": "What to notify" });
    const err = h("p", { class: "note bad", role: "alert", hidden: true }, icon("warn", "sm"), h("span"));
    const go = h("button", { class: "btn primary", onclick: () => submit() }, "Notify");
    const draw = () => {
      list.replaceChildren(...(targets || []).map((t) => h("button", { class: "opt", role: "checkbox", "aria-checked": String(chosen.has(t.entity_id)),
        onclick: () => { chosen.has(t.entity_id) ? chosen.delete(t.entity_id) : chosen.add(t.entity_id); draw(); } },
        h("span", { class: "ock", "aria-hidden": "true" }, chosen.has(t.entity_id) ? icon("check", "sm") : null),
        h("span", { class: "otext" }, h("span", { class: "o1", text: nameOf(app, t.entity_id) }), h("span", { class: "o2", text: t.entity_id })),
        t.phone ? h("span", { class: "otag", text: "Phone" }) : null)));
      if (targets && !targets.length) list.append(h("p", { class: "empty-note", text: "Home Assistant has nothing to notify yet. Install the Home Assistant app on your phone and sign in, then try again." }));
      go.disabled = !chosen.size || !!problem;
    };
    const fail = (text) => { err.hidden = !text; err.lastChild.textContent = text || ""; };
    async function submit() {
      go.disabled = true; go.textContent = "Setting up…";
      fail("");
      p = app.doc.spec.pages[name] || p;          // the page as it is now
      const nid = p.notify || newId();
      try {
        const r = await api("api/notify", { method: "POST", body: { page: name, id: nid, tier: p.tier, targets: [...chosen] } });
        if (p.notify !== nid) { p.notify = nid; app.doc.commit(); }
        asked.delete(nid);
        close();
        app.refresh();
        toast(`${title} now notifies ${names(app, r.body.automation.targets)}.`);
      } catch (e) {
        fail(e.message);
        go.textContent = "Notify";
        go.disabled = !chosen.size;
      }
    }
    const what = p.tier === "alert" ? `When ${title} takes over the panel` : `When ${title} starts showing`;
    node.append(h("div", { class: "sheet-body" },
      h("p", { class: "fnote", text: `${what}, Home Assistant sends a notification.` }),
      problem ? h("p", { class: "note warn" }, icon("warn", "sm"), h("span", { text: problem })) : list,
      err,
      h("p", { class: "fnote", text: "It's made as an automation in Home Assistant, where you can change the message, add a title or keep it quiet for a while." })),
      h("div", { class: "sheet-foot" }, h("button", { class: "btn tinted", onclick: () => close() }, "Cancel"), go));
    draw();
  }, { cls: "notifysheet" });
}

async function stop(app, p, name, del) {
  const nid = p.notify;
  try {
    const r = await api("api/notify/stop", { method: "POST", body: { id: nid, delete: del } });
    asked.delete(nid);
    return r.body;
  } catch (e) {
    toast(e.message);
    return null;
  }
}

/* "Stop notifying": with an automation still using it, a choice, never a question. */
function stopNotifying(app, p, name, s, anchor) {
  const done = async (del) => {
    const r = await stop(app, p, name, del);
    if (!r) return;
    delete (app.doc.spec.pages[name] || p).notify;
    app.doc.commit();
    app.refresh();
    toast(r.kept.length ? `${pageTitle(name)} no longer notifies you. “${r.kept[0].name}” stays in Home Assistant.` : `${pageTitle(name)} no longer notifies your phone.`);
  };
  const ours = s.automations.filter((a) => a.ours);
  if (!s.automations.length) return done([]);
  menu(anchor, [
    { heading: s.automations.length === 1 ? `“${s.automations[0].name}” uses it in Home Assistant.` : `${s.automations.length} automations use it in Home Assistant.` },
    ours.length ? { label: ours.length === 1 ? "Delete automation and stop" : "Delete automations and stop", icon: "trash", danger: true, run: () => done(ours.map((a) => a.id)) } : null,
    { label: ours.length ? "Keep it and stop" : "Stop, keep the automation", run: () => done([]) },
  ], { label: "Stop notifying" });
}

/* Deleting a page that notifies: its automation goes with it, or stays; a choice, not a confirmation. */
export async function deleteNotifying(app, name, del) {
  const p = app.doc.spec.pages[name];
  if (!p?.notify) return del();
  const s = (await askStatus(p.notify).done).got;          // usually just asked by the inspector
  const ours = (s?.automations || []).filter((a) => a.ours);
  if (!ours.length) return del();
  sheet(`Delete ${pageTitle(name)}?`, (node, close) => {
    node.append(h("div", { class: "sheet-body" },
      h("p", { class: "fnote", text: ours.length === 1 ? `“${ours[0].name}” in Home Assistant notifies you about this page.` : `${ours.length} automations in Home Assistant notify you about this page.` })),
      h("div", { class: "sheet-foot wrap" },
        h("button", { class: "btn tinted", onclick: () => { close(); del(); } }, "Delete page only"),
        h("button", { class: "btn tinted danger", onclick: async () => {
          close();
          if (await stop(app, p, name, ours.map((a) => a.id))) del(`Deleted ${pageTitle(name)} and its automation.`);
        } }, ours.length === 1 ? "Delete page and automation" : "Delete page and automations")));
  });
}
