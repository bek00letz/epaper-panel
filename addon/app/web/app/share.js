// A shared page's file, filled in (the add-on's share.py writes and opens it). Its sender's sensors
// are numbered slots, "%slot:3%" (or one part of a slot's answer, "%slot:1.ssid%"), wherever they
// were: a sensor, a Devices grid's items, a condition, a template. New page's steps answer them
// with the importer's own, and `fill` puts the answers in. One answer per slot: an entity ID, or a
// Wi-Fi network ({ ssid, password, auth }). A slot left out is "", as a preset's skipped sensor is.
// No imports from util.js: the tests read this file under node.

const TOKEN = /%slot:(\d+)(?:\.([a-z]+))?%/g;

const said = (answer, part) => {
  if (answer == null) return "";
  if (typeof answer === "object") return part ? String(answer[part] ?? "") : "";
  return part ? "" : String(answer);
};

/* The pages with every slot's answer in place. `answers` is { slotId: answer }. */
export function fill(pages, answers) {
  const put = (v) => (typeof v === "string" ? v.replace(TOKEN, (_, id, part) => said(answers[id], part))
    : Array.isArray(v) ? v.map(put)
    : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, put(x)]))
    : v);
  return pages.map(put);
}

/* What a thumbnail shows before anything is picked: each slot's example, the add-on's own. */
export const exampleAnswers = (slots) => Object.fromEntries(slots.map((s) => [s.id, s.example ?? ""]));

