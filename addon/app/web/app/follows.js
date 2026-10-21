// An icon that follows a sensor ("Changes with a sensor", in the Icon section
// of the inspector): its entity and a state_icons map, which the renderer
// reads (render/layout.icon_for_state, matching a state whatever its case).
// Its own icon is what shows for anything else. What states a sensor has, and
// Home Assistant's icon for each, come from GET /api/entity_states
// (render/states.offered); the editor keeps no copy. No imports from util.js:
// the tests read this file under node.

const key = (s) => String(s ?? "").trim().toLowerCase();

/* A look is an icon's Style: Plain, Inverted (a filled shape, the icon in white) or Outlined. Each
   state has its own (the user's design, 21 Oct); the icon's own Style is "Anything else"'s. A row
   is { icon, look }; one that's just an icon (the first shape, and the Status preset's) draws
   with the icon's Style. render/layout.icon_in_state reads both. */
export const LOOKS = [["plain", "Plain"], ["invert", "Inverted"], ["pill", "Outlined"]];
export const styleOf = (el) => (el.invert ? "invert" : el.pill ? "pill" : "plain");
export function setStyle(el, look) {
  delete el.invert; delete el.pill;
  if (look === "invert") el.invert = true;
  if (look === "pill") el.pill = true;
}
const entry = (v) => (v && typeof v === "object" ? v : { icon: String(v || "") });
export const iconOf = (v) => entry(v).icon || "";
export function lookOf(el, state) {
  const k = rowFor(el, state), l = k === undefined ? "" : entry(el.state_icons[k]).look;
  return LOOKS.some(([v]) => v === l) ? l : styleOf(el);
}
/* Whether anything it draws has a shape around it, so its Corners matter. */
export const framed = (el) => styleOf(el) !== "plain" || (isFollowing(el) && Object.keys(el.state_icons).some((k) => lookOf(el, k) !== "plain"));

export const isFollowing = (el) => !!el && el.type === "icon" && !!el.state_icons && typeof el.state_icons === "object" && !Array.isArray(el.state_icons);

/* The switch: on keeps the icon as "Anything else", off keeps it as the plain icon. */
export function startFollowing(el) {
  if (!isFollowing(el)) el.state_icons = {};
}
export function stopFollowing(el) {
  delete el.state_icons;
  delete el.entity;
}

/* Another sensor: the states of the one before aren't its states. How many were cleared. */
export function setEntity(el, id) {
  const was = el.entity || "";
  if (id) el.entity = id; else delete el.entity;
  if (!isFollowing(el) || was === (id || "")) return 0;
  const n = Object.keys(el.state_icons).length;
  el.state_icons = {};
  return n;
}

/* The state's own row, if it has one, whatever its case. */
export const rowFor = (el, state) => Object.keys(el.state_icons || {}).find((k) => key(k) === key(state));

/* A row for a state, with its icon (or the icon's own). The key it's under; "" for no state,
   or the row it already had. */
export function addState(el, state, icon) {
  const s = String(state ?? "").trim();
  if (!s || !isFollowing(el)) return "";
  const had = rowFor(el, s);
  if (had !== undefined) return "";
  el.state_icons[s] = { icon: icon || el.icon || "mdi:help-circle-outline", look: styleOf(el) };
  return s;
}
export function removeState(el, state) {
  const k = rowFor(el, state);
  if (k !== undefined) delete el.state_icons[k];
}
export function setStateIcon(el, state, icon) {
  const k = rowFor(el, state);
  if (k !== undefined && icon) el.state_icons[k] = { icon, look: lookOf(el, k) };
}
export function setStateLook(el, state, look) {
  const k = rowFor(el, state);
  if (k !== undefined && LOOKS.some(([v]) => v === look)) el.state_icons[k] = { icon: iconOf(el.state_icons[k]), look };
}

/* What's offered and not added yet, each with the icon it would get. */
export function suggestions(el, offered) {
  return (Array.isArray(offered) ? offered : [])
    .filter((o) => o && key(o.state) && rowFor(el, o.state) === undefined)
    .map((o) => ({ state: String(o.state), word: o.word || String(o.state), icon: o.icon || el.icon || "" }));
}

/* A row's name: Home Assistant's word for it ("Open" for a door's on), else the state. */
export function wordFor(state, offered, kindWords) {
  const o = (Array.isArray(offered) ? offered : []).find((x) => key(x?.state) === key(state));
  if (o?.word) return o.word;
  const w = kindWords && Object.entries(kindWords).find(([k]) => key(k) === key(state));
  return w?.[1]?.word || String(state);
}
