// On a busy day, can the Scores pages have more games than the device holds? Said only where it
// matters: while setting up Scores (New page) and under its League in the inspector, and only for
// a device that keeps its whole rotation in memory (an always-on CrowPanel). The add-on works it
// out (POST /api/busy_day: each league's busiest day, the panel's own room, shared out as a render
// would); the editor only words it. The wording is the user's (21 Oct).
import { api, h, icon } from "./util.js";

const asked = new Map();       // what the add-on said, by what was asked: a redraw shows it at once

export function busyWords(scores, device) {
  if (!scores || !(scores.room < scores.busiest)) return "";
  const who = device || "this device";
  const leagues = scores.leagues > 1 ? "your leagues" : "your league";
  return `On a busy day ${leagues} can have a lot of scores, and ${who} can only show about ${scores.room} of them. ` +
    (scores.teams ? "Your teams' scores come first." : "Pick your teams to make sure their scores show.");
}

/* A note that fills itself in: nothing at all until (and unless) there is something to say.
   `spec` is the rotation as it would be: the draft, with a page being set up added at its end. */
export function busyNote(app, spec) {
  const node = h("p", { class: "note info busy", role: "note", hidden: true }, icon("info", "sm"), h("span"));
  const body = { pages: spec.pages, rotation: spec.rotation };
  const key = `${app.screen?.id || ""}:${JSON.stringify(body)}`;
  const show = (scores, fresh) => {
    const text = busyWords(scores, app.screen?.name);
    node.querySelector("span").textContent = text;
    node.hidden = !text;
    node.classList.toggle("fade", !!text && fresh);     // in with a fade the first time, never on a redraw
  };
  if (asked.has(key)) show(asked.get(key), false);
  else api("api/busy_day", { method: "POST", body }).then((r) => {
    const scores = r.body?.scores || null;
    if (asked.size > 50) asked.clear();
    asked.set(key, scores);
    if (node.isConnected) show(scores, true);
  }).catch(() => { /* nothing to say is better than a guess */ });
  return node;
}
