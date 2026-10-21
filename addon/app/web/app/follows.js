// An icon that follows a sensor ("Changes with a sensor", in the Icon section
// of the inspector): its entity and a state_icons map, which the renderer
// reads (render/layout.icon_for_state, matching a state whatever its case).
// Its own icon is what shows for anything else. What states a sensor has, and
// Home Assistant's icon for each, come from GET /api/entity_states
// (render/states.offered); the editor keeps no copy. No imports from util.js:
// the tests read this file under node.

const key = (s) => String(s ?? "").trim().toLowerCase();

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
  el.state_icons[s] = icon || el.icon || "mdi:help-circle-outline";
  return s;
}
export function removeState(el, state) {
  const k = rowFor(el, state);
  if (k !== undefined) delete el.state_icons[k];
}
export function setStateIcon(el, state, icon) {
  const k = rowFor(el, state);
  if (k !== undefined && icon) el.state_icons[k] = icon;
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
