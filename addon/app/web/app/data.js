// A widget's data, in the inspector (descriptor field kind "data"; shapes.py): where it reads from,
// the add-on's services or one of your data sources, and its fields in the add-on's own form with what
// they hold now. The form is the add-on's, never an outside service's, so a source of yours that
// answers in it can stand in for the service. Closed by default: it's rarely touched.

import { h, icon, api } from "./util.js";
import { field, select, linkButton } from "./ui.js";
import { widget } from "./catalog.js";
import { clockAt } from "./services.js";

const ISO = /^\d{4}-\d\d-\d\d(T\d\d:\d\d)?/;
// A time the add-on gives as ISO, as a person reads it (12- or 24-hour as Settings says).
const said = (v) => (ISO.test(v) && !Number.isNaN(Date.parse(v)) ? clockAt(Date.parse(v) / 1000) : v);
// The elements whose section is open, so a change (which draws the inspector again) keeps it open.
const opened = new Set();
const ownOf = (el) => (el.data && typeof el.data === "object" ? ("entity" in el.data ? "entity" : String(el.data.source || "")) : "");

/* `pickSensor(entityId, onPick)`: the inspector's sensor button, for a Home Assistant sensor whose
   attributes carry the fields. */
export function dataRows(app, el, pickSensor) {
  const shape = widget(el.type)?.shape;
  if (!shape) return [];
  const own = ownOf(el);
  const box = h("div", { class: "datarows" });
  const d = h("details", { class: "more" }, h("summary", {}, icon("chev", "sm"), "Its data"), box);
  let filled = false;
  d.addEventListener("toggle", () => {
    if (d.open) opened.add(el.id); else opened.delete(el.id);
    if (d.open && !filled) { filled = true; fill(); }
  });
  if (opened.has(el.id)) d.open = true;

  async function fill() {
    box.replaceChildren(h("p", { class: "fnote waiting", text: "Reading what it shows…" }));
    let srcs = [], got = null;
    try { srcs = ((await api("api/sources")).body || []).filter((s) => s.fills === shape.kind); } catch (_) { /* no list: only the services */ }
    try { got = (await api("api/widget_data", { method: "POST", body: { element: el } })).body; } catch (e) { got = { error: e.message }; }
    const choices = [["", got?.services?.length ? `The add-on's services (${got.services.join(", ")})` : "The add-on's services"],
      ...srcs.map((s) => [s.id, `Your source “${s.name}”`])];
    choices.push(["entity", "A Home Assistant sensor"]);
    if (own && own !== "entity" && !srcs.some((s) => s.id === own)) choices.push([own, "A source that was removed"]);
    const from = field("From", select(choices, own, (v) => {
      if (v === "entity") el.data = { entity: "" }; else if (v) el.data = { source: v }; else delete el.data;
      app.doc.commit();                 // the inspector draws again, with this section as it is now
    }, { "aria-label": "Where it reads from" }));
    const rows = [from];
    if (own === "entity") {
      rows.push(field("Sensor", pickSensor(el.data.entity || "", (id) => { el.data = { entity: id || "" }; app.doc.commit(); })),
        h("p", { class: "fnote", text: el.data.entity ? `Its attributes give the fields: a list "${shape.list}" in the add-on's form.`
          : `Choose a sensor whose attributes have a list "${shape.list}" in the add-on's form. Until then it reads the add-on's services.` }));
      if (got?.entity?.problem) rows.push(h("p", { class: "fnote bad", text: got.entity.problem }));
    }
    if (got?.source?.missing) rows.push(h("p", { class: "fnote bad", text: "Its data source was removed, so it shows nothing. Choose another, or the add-on's services." }));
    if (got?.error) rows.push(h("p", { class: "fnote bad", text: `Couldn't read what it shows: ${got.error}` }));
    else if (got?.fields?.length) {
      rows.push(h("dl", { class: "fields", "aria-label": "Its fields, now" },
        ...got.fields.flatMap((f) => [h("dt", { text: f.label }), h("dd", { text: said(f.value) || "–" })])));
    } else rows.push(h("p", { class: "fnote", text: "Nothing to show yet. Its fields fill in once it has answered." }));
    rows.push(h("p", { class: "fnote" },
      `The add-on reads ${shape.name} pages in its own form. A data source that answers in that form, or a sensor whose attributes have it, can take the services' place: `,
      linkButton("Add one in Data sources", async () => (await import("./sheets.js")).openSettings(app, "sources"))),
      formNote(shape));
    box.replaceChildren(...rows);
  }
  return [d];
}

/* The add-on's form for a kind of page: its fields, what's needed, and an example to copy. */
export function formNote(shape) {
  const line = (f) => h("li", {}, h("code", { text: f.key }), ` ${f.label}${f.needed ? "" : " (if it has one)"}${f.says ? `: ${f.says}` : ""}`);
  const example = JSON.stringify(shape.example, null, 2);
  return h("details", { class: "more" }, h("summary", {}, icon("chev", "sm"), "Its form"),
    h("p", { class: "fnote" }, "A list ", h("code", { text: shape.list }), `, each ${shape.item} with:`),
    h("ul", { class: "formlist" }, ...shape.fields.map(line)),
    ...shape.more.flatMap((m) => [h("p", { class: "fnote" }, "and ", h("code", { text: m.list }), ", each with:"), h("ul", { class: "formlist" }, ...m.fields.map(line))]),
    h("p", { class: "fnote", text: "For example:" }),
    h("pre", { class: "formex", tabindex: "0", "aria-label": "An example" }, example));
}
