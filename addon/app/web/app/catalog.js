// What the add-on knows and the editor reads, never copies (framework review
// #5–#7): the leagues and racing series it follows, each sport's words, Home
// Assistant's state words by device, every widget's descriptor (name, icon,
// box, fields, how often what it shows changes), the time format, the languages a
// device can speak and the words presets write on a page in each. Served
// by GET /api/catalog (web.api_catalog) and set once at the editor's start.
// No imports from util.js: the tests read this file under node.

const C = { leagues: [], series: [], sport_words: {}, states: {}, widgets: {}, time_format: "24h",
  languages: { choices: [["en", "English"]], home: "en", home_offered: true }, page_words: {} };

export function setCatalog(cat) {
  if (!cat || typeof cat !== "object") return;
  for (const k of Object.keys(C)) if (cat[k] !== undefined) C[k] = cat[k];
}
export const catalog = () => C;

/* Leagues and series, in the order the add-on offers them. */
export const leagues = () => C.leagues;
export const series = () => C.series;
export const leagueOptions = () => C.leagues.map((l) => [l.path, l.name]);
export const seriesOptions = () => C.series.map((s) => [s.slug, s.title]);
const lower = (x) => String(x || "").trim().toLowerCase();
export const leagueOf = (raw) => { const k = lower(raw || "soccer/eng.1"); return C.leagues.find((l) => l.path === k || l.slug === k || (l.aliases || []).includes(k)); };
export const seriesOf = (raw) => { const k = lower(raw || "f1"); return C.series.find((s) => s.slug === k || lower(s.code) === k || (s.aliases || []).includes(k)); };

/* What one event is called in a sport ("match", "game", "race"), by the league's sport. */
export function sportWords(league) {
  const lg = leagueOf(league);
  if (lg?.words) return lg.words;
  const sport = lower(league).split("/")[0];
  return C.sport_words[sport] || C.sport_words.other || { event: "match" };
}
export const sportWord = (league) => sportWords(league).event;

/* Home Assistant's words and icons for an entity's states, by "domain.device_class", then the domain:
   { on: { word, icon }, off: {...} }, or null when it has none. */
export function stateWords(entityId, deviceClass) {
  const domain = String(entityId || "").split(".")[0];
  return C.states[deviceClass ? `${domain}.${deviceClass}` : ""] || C.states[domain] || null;
}

/* The language of the device being edited (its `speaks`, from GET /api/devices): presets write
   their words on a page in it, when the page is made. From then on they're the person's own. */
let speaks = "en";
export function setSpeaking(lang) { speaks = lang || "en"; }
export const speaking = () => speaks;

/* A word a preset writes on a page ("page.<key>" in the add-on's table), in the device's language,
   English when it has none; {n} filled in. */
export function pageWord(key, n) {
  const row = C.page_words["page." + key] || {};
  const text = row[speaks] || row.en || key;
  return n === undefined ? text : text.replace("{n}", String(n));
}

/* Home Assistant's word for a state (stateWords' "word"), in the device's language. */
export const stateWord = (word) => (C.page_words["state." + word] || {})[speaks] || word;

/* A page's name as a preset gives it: the device's word, its accents folded, since a page's
   name is a plain-letter slug ("Météo" is "meteo", "Gerät" is "Geraet"). */
const FOLD = { ä: "ae", ö: "oe", ü: "ue", Ä: "Ae", Ö: "Oe", Ü: "Ue", ß: "ss" };
export function pageNameWord(key) {
  const text = (C.page_words["page.name." + key] || {})[speaks] || (C.page_words["page.name." + key] || {}).en || "";
  return text.replace(/[äöüÄÖÜß]/g, (c) => FOLD[c]).normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
}

/* Widgets: their descriptors, in offer order. */
export const widgets = () => C.widgets;
export const widget = (type) => C.widgets[type] || null;
export const isWidgetType = (type) => !!C.widgets[type];

/* How often what a widget shows changes, in minutes (null: only when Home Assistant changes it).
   The descriptors give seconds, and only for what really changes (a calendar's fetch interval
   isn't one); `changes_when` names the fields that make it live (a Weather with your own station). */
export function widgetChangesEvery(el) {
  const w = widget(el?.type);
  const s = w?.changes_every;
  if (!s) return null;
  if (Array.isArray(w.changes_when) && !w.changes_when.some((k) => el[k])) return null;
  return Math.max(1, Math.round(s / 60));
}
