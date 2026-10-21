// The built-in presets: what the New page sheet offers, on one shelf per
// group. One preset per thing a page shows; its looks, leagues or series are
// picked in the next step, not separate cards.
//
// A preset is data: { id, group, title, desc, kw, asks, choose, looks, ... }.
//   asks     what it shows, picked in the next step: an entity domain
//            ("calendar", "todo", "sensor", "binary_sensor", "weather"), or "" for nothing.
//   prefer   which sensors come first in that list (rankSensors).
//   choose   "Style", "League" or "Series": what its looks are called. Leagues and
//            series are chips; styles are pictures.
//   looks    [{ id, name, make(ent) → elements, ...page fields }]; the first is the default.
//   example  the entity a thumbnail is drawn with (the add-on's example values,
//            never the person's own): a string, or a function of the look.
//   needs    something it sets up in place before it can show anything ("jellyfin",
//            "wifi"), in its own next step.
//   was      its old name, so search still finds it and the card can say so.
// No imports from util.js: the tests read this file under node.

import { getWidgetSensorId, todoShowIf, LEAGUE_TO_SLUG } from "./legacy.js";

export const GROUPS = [
  ["day", "Your day"],
  ["home", "Home"],
  ["energy", "Energy"],
  ["outside", "Outside"],
  ["sports", "Sports"],
  ["media", "Watch and listen"],
];

// The sensor a Jellyfin source makes; "watch" is the name it's seeded with.
const watchEnt = (ent) => ent || "sensor.epaper_watch";
const watchShowIf = (ent) => `{{ states('${watchEnt(ent)}_count') | int(0) > 0 }}`;
const boxed = (el) => ({ x: 18, y: 14, w: 756, h: 222, show_border: true, ...el });

// The leagues and series the add-on fetches (sources/sports.py, sources/racing.py).
export const LEAGUES = [
  ["soccer/eng.1", "Premier League"], ["soccer/uefa.champions", "Champions League"], ["soccer/esp.1", "La Liga"],
  ["soccer/ger.1", "Bundesliga"], ["soccer/ita.1", "Serie A"], ["soccer/usa.1", "MLS"],
  ["basketball/nba", "NBA"], ["basketball/wnba", "WNBA"], ["football/nfl", "NFL"],
  ["football/college-football", "College football"], ["baseball/mlb", "MLB"], ["hockey/nhl", "NHL"],
];
export const SERIES = [["f1", "Formula 1"], ["fe", "Formula E"], ["nascar", "NASCAR"], ["indycar", "IndyCar"]];

const calendarMonth = (ent, box) => ({ type: "calendar_month", ...box, show_header: true, show_weekdays: true, first_weekday: 0, highlight_today: true, show_border: true, entity: ent || "" });
const watchLook = (id, name, make) => ({ id, name, tier: "when", showIf: watchShowIf, make });

export const PRESETS = [
  /* ---------- your day ---------- */
  {
    id: "clock", group: "day", title: "Clock", desc: "The time, very large, and today's date.", kw: "time date",
    asks: "",
    looks: [{ id: "clock", name: "Clock", make: () => [
      { type: "text", value: "{{ now().strftime('%H:%M') }}", size: 110, bold: true, x: 40, y: 20, w: 450, h: 140, align: "left" },
      { type: "text", value: "{{ now().strftime('%A, %-d %B') }}", size: 36, bold: false, x: 44, y: 168, w: 500, h: 46, align: "left" },
      { type: "icon", icon: "mdi:clock-outline", x: 620, y: 40, w: 120, h: 120 },
    ] }],
  },
  {
    id: "calendar", group: "day", title: "Calendar", kw: "agenda month events",
    desc: "This month, with today marked and days with events dotted, and the next events beside it if you like.",
    asks: "calendar", choose: "Style", example: "calendar.family",
    looks: [
      { id: "calendar_combo", name: "Month and agenda", make: (ent) => [
        calendarMonth(ent, { x: 16, y: 12, w: 368, h: 228 }),
        { type: "calendar_agenda", x: 396, y: 12, w: 380, h: 228, title: "Coming up", max_events: 4, show_border: true, entity: ent || "" },
      ] },
      { id: "calendar_month", name: "Month", make: (ent) => [calendarMonth(ent, { x: 20, y: 14, w: 752, h: 222 })] },
    ],
  },
  {
    id: "to_do", group: "day", title: "To-do list", kw: "todo tasks shopping list chores groceries",
    desc: "A to-do list from Home Assistant, what's due first, with Overdue and Today marked. Only shows while there's something to do.",
    asks: "todo", choose: "Style", example: "todo.chores", namedByEntity: true,
    looks: [["urgency", "By urgency"], ["due", "Inverted when due"], ["outlined", "Outlined"]].map(([style, name]) => ({
      id: "to_do_" + style, name, tier: "when", showIf: (ent) => todoShowIf(ent),
      make: (ent) => [{ type: "todo_list", style, x: 40, y: 14, w: 712, h: 220, entity: ent || "" }],
    })),
  },
  {
    id: "event_countdown", group: "day", title: "Countdown", desc: "Days until the next event in a calendar, and its date.", kw: "days until",
    asks: "calendar", example: "calendar.family",
    looks: [{ id: "event_countdown", name: "Countdown", make: (ent) => [
      { type: "icon", icon: "mdi:calendar-clock", x: 32, y: 40, w: 110, h: 110 },
      { type: "number", entity: ent || "", show: "days_until", suffix: " days", decimals: 0, x: 160, y: 24, w: 340, h: 130, align: "left" },
      { type: "text", value: "days until event", size: 30, bold: false, x: 164, y: 166, w: 320, h: 42, align: "left" },
      { type: "text", entity: ent || "", show: "date_formatted", prefix: "date: ", format: "day_date", size: 28, bold: false, x: 450, y: 166, w: 300, h: 42, align: "right" },
    ] }],
  },
  {
    id: "bin_day", group: "day", title: "Bin day", desc: "Days until collection, and which bin.", kw: "trash rubbish recycling garbage waste",
    asks: "calendar", example: "calendar.bins",
    looks: [{ id: "bin_day", name: "Bin day", make: (ent) => [
      { type: "icon", icon: "mdi:trash-can", x: 32, y: 40, w: 110, h: 110 },
      { type: "number", entity: ent || "", show: "days_until", suffix: " days", decimals: 0, x: 160, y: 24, w: 340, h: 130, align: "left" },
      { type: "text", value: "until collection", size: 30, bold: false, x: 164, y: 166, w: 320, h: 42, align: "left" },
      { type: "text", entity: ent || "", show: "calendar_title", prefix: "type: ", size: 28, bold: false, x: 450, y: 166, w: 300, h: 42, align: "right" },
    ] }],
  },

  /* ---------- home ---------- */
  {
    id: "climate", group: "home", title: "Room temperature", desc: "A temperature with a 24-hour curve.", kw: "climate thermometer heat",
    asks: "sensor", prefer: { device_class: ["temperature"], units: ["°C", "°F", "K"] }, example: "sensor.indoor_temperature",
    looks: [{ id: "climate", name: "Room temperature", make: (ent) => [
      { type: "icon", icon: "mdi:thermometer", x: 32, y: 44, w: 116, h: 116 },
      { type: "number", entity: ent || "", show: "state", suffix: " °C", decimals: 1, x: 160, y: 30, w: 320, h: 128, align: "left" },
      { type: "text", value: "room climate", size: 30, bold: false, x: 164, y: 170, w: 320, h: 40, align: "left" },
      { type: "curve", entity: ent || "", hours: 24, x: 490, y: 100, w: 270, h: 86 },
    ] }],
  },
  {
    id: "status", group: "home", title: "Status", was: "Door or pet", kw: "door pet cat presence window state since open closed",
    desc: "Any sensor's state in your own words (Open, Home, Running) and how long it's been that way.",
    asks: "binary_sensor", alsoShows: ["person", "device_tracker", "lock", "cover", "input_boolean", "switch", "sensor"],
    example: "binary_sensor.front_door", namedByEntity: true,
    looks: [{ id: "presence_door", name: "Status", make: (ent) => [
      { type: "icon", icon: "mdi:door", x: 32, y: 44, w: 116, h: 116 },
      { type: "text", entity: ent || "", show: "state", replace: { on: "Open", off: "Closed" }, size: 80, bold: true, x: 164, y: 30, w: 360, h: 128, align: "left" },
      { type: "text", entity: ent || "", show: "last_changed", format: "relative", prefix: "since ", size: 30, bold: false, x: 164, y: 170, w: 420, h: 40, align: "left" },
    ] }],
  },
  {
    id: "dynamic_status", group: "home", title: "Dynamic status", was: "On now", kw: "what's on heaters lights devices dynamic running",
    desc: "Up to eight things, each shown only while it's in a state you choose: on, open, home, running.",
    asks: "", example: ["timer.dryer_cycle", "person.partner", "sensor.cat_location", "binary_sensor.front_door"],
    looks: [{ id: "dynamic_entities", name: "Dynamic status", tier: "when", make: (ent, ex) => [{
      type: "dynamic_grid", x: 20, y: 16, w: 752, h: 214,
      header_icon: "mdi:lightning-bolt", header_title: "On now", filter_state: "on",
      layout_mode: "grid", show_labels: "both", icon_size: "auto", secondary_mode: "runtime",
      items: ex ? ex.map((e) => ({ entity: e, name: "", icon: "" }))
        : [["Spot 1", "mdi:radiator"], ["Spot 2", "mdi:radiator"], ["Spot 3", "mdi:paw"], ["Spot 4", "mdi:bed"]].map(([name, icon], k) => ({ entity: k ? "" : ent || "", name, icon })),
    }] }],
  },
  {
    id: "guest_wifi", group: "home", title: "Guest Wi-Fi", desc: "A code guests scan with their phone camera to join your Wi-Fi.", kw: "qr code network password",
    asks: "", needs: "wifi",
    looks: [{ id: "guest_wifi", name: "Guest Wi-Fi", make: (_, w = {}) => guestWifi(w) }],
  },

  /* ---------- energy ---------- */
  {
    id: "solar", group: "energy", title: "Solar today", desc: "What the panels made today, with a 24-hour curve.", kw: "pv panels kwh production",
    asks: "sensor", prefer: { energy: "solar", device_class: ["energy"], units: ["kWh", "Wh", "MWh"] }, example: "sensor.solar_today_production",
    looks: [{ id: "solar", name: "Solar today", make: (ent) => [
      { type: "icon", icon: "mdi:white-balance-sunny", x: 32, y: 44, w: 116, h: 116 },
      { type: "number", entity: ent || "", show: "state", suffix: " kWh", decimals: 1, x: 160, y: 30, w: 310, h: 128, align: "left" },
      { type: "text", value: "produced today", size: 30, bold: false, x: 164, y: 170, w: 320, h: 40, align: "left" },
      { type: "curve", entity: ent || "", hours: 24, x: 490, y: 100, w: 270, h: 86 },
    ] }],
  },
  {
    id: "energy_gauges", group: "energy", title: "Battery and solar", desc: "Home battery and house load as gauges, with today's solar as bars.", kw: "load gauges storage",
    asks: "sensor", prefer: { energy: "battery", device_class: ["battery"], units: ["%"] }, example: "sensor.home_battery",
    looks: [{ id: "energy_gauges", name: "Battery and solar", make: (ent) => [
      { type: "box", x: 18, y: 14, w: 356, h: 218, fill: "outline", radius: 14, thickness: 3 },
      { type: "text", value: "ENERGY & STORAGE", size: 18, bold: true, invert: true, radius: 8, x: 34, y: 28, w: 280, h: 32, align: "center" },
      { type: "bar", entity: ent || "", title: "HOME BATTERY", bar_style: "segmented", segments: 10, min_val: 0, max_val: 100, suffix: "%", decimals: 0, show_label: true, x: 34, y: 74, w: 324, h: 66 },
      { type: "bar", entity: "", title: "HOUSE LOAD", bar_style: "solid", min_val: 0, max_val: 5000, suffix: " W", decimals: 0, show_label: true, x: 34, y: 152, w: 324, h: 64 },
      { type: "bar_chart", entity: "", title: "24H GENERATION", hours: 24, bars: 12, show_labels: true, show_border: true, x: 390, y: 14, w: 384, h: 218 },
    ] }],
  },

  /* ---------- outside ---------- */
  {
    id: "weather_forecast", group: "outside", title: "Weather", desc: "Now and the next four days, from your Home Assistant weather.", kw: "forecast rain temperature",
    asks: "weather", example: "weather.forecast_home",
    looks: [{ id: "weather_forecast", name: "Weather", make: (ent) => [boxed({ type: "weather_forecast", entity: ent || "" })] }],
  },
  {
    id: "sun_times", group: "outside", title: "Sunrise and sunset", kw: "sun dawn dusk daylight sunrise sunset",
    desc: "Today's sunrise and sunset, from Home Assistant's sun. Works in every home, with nothing to set up.",
    asks: "", choose: "Style",
    looks: [
      { id: "sun_next", name: "Next one first", note: "After sunrise it turns round: the sunset large, tomorrow's sunrise beside it.",
        make: () => [{ type: "sun_times", style: "next", x: 24, y: 14, w: 744, h: 208 }] },
      { id: "sun_both", name: "Both alike", make: () => [{ type: "sun_times", style: "both", x: 24, y: 14, w: 744, h: 208 }] },
    ],
  },
  {
    id: "planes", group: "outside", title: "Planes overhead", kw: "flights aircraft radar airport plane",
    desc: "When a plane comes near: its flight, airline, route, height and speed, or a radar of everything around. Only shows while one is near.",
    asks: "", choose: "Style",
    looks: [["flight_tracker", "Nearest plane", "card"], ["flight_radaronly", "Radar", "radar"], ["flight_radar", "Both", "split"]].map(([id, name, style]) => ({
      id, name, tier: "when", widget: true,
      make: () => [boxed({ type: "flight_tracker", style, radius: 35, auto_window: true })],
    })),
  },

  /* ---------- sports ---------- */
  {
    id: "match", group: "sports", title: "Match", kw: "football soccer score " + LEAGUES.map(([, n]) => n).join(" ") + " basketball hockey baseball",
    desc: "The live score, clock and scorers. Shows on match days, from before kick-off to after the whistle.",
    asks: "", choose: "League", name: (look) => look.name,
    looks: LEAGUES.map(([league, name]) => ({
      id: "sports_match_" + (LEAGUE_TO_SLUG[league] || league), name, tier: "when", widget: true,
      make: () => [boxed({ type: "sports_match", league, team: "", entity: "", pre_buffer_hours: 2, post_buffer_hours: 2, auto_window: true })],
    })),
  },
  {
    id: "race_weekend", group: "sports", title: "Race weekend", was: "Formula 1", kw: "racing f1 formula 1 formula e nascar indycar motorsport grand prix",
    desc: "The top ten with gaps and tyres while a session runs; the countdown to the next one the rest of the week.",
    asks: "", choose: "Series", name: (look) => look.name,
    looks: SERIES.map(([series, name]) => ({
      id: "sports_racing_" + series, name, tier: "when", widget: true,
      make: () => [boxed({ type: "sports_racing", series, entity: "", window_mode: "session", pre_buffer_hours: 2, post_buffer_hours: 2, auto_window: true })],
    })),
  },

  /* ---------- watch and listen ---------- */
  {
    id: "watch", group: "media", title: "New to watch", kw: "jellyfin tv episodes films movies new unwatched",
    desc: "What's new and unwatched in your Jellyfin library. Only shows while there's something new.",
    asks: "jellyfin", needs: "jellyfin", choose: "Style", example: "sensor.epaper_watch",
    looks: [
      watchLook("watch", "Newest", (ent) => [
        { type: "text", value: "new to watch", size: 26, bold: false, x: 40, y: 28, w: 300, h: 36, align: "left" },
        { type: "text", entity: watchEnt(ent), show: "attribute", attribute: "detail", size: 26, bold: false, x: 352, y: 28, w: 400, h: 36, align: "right" },
        { type: "text", entity: watchEnt(ent), x: 40, y: 74, w: 712, h: 150, align: "left" },
      ]),
      watchLook("episode", "Episode card", (ent) => [
        { type: "text", entity: watchEnt(ent), x: 40, y: 22, w: 712, h: 96, align: "left" },
        { type: "text", entity: watchEnt(ent), show: "attribute", attribute: "about", size: 34, bold: false, x: 40, y: 128, w: 712, h: 46, align: "left" },
        { type: "text", entity: watchEnt(ent), show: "attribute", attribute: "added_ago", prefix: "added ", size: 26, bold: false, x: 40, y: 188, w: 420, h: 36, align: "left" },
      ]),
      watchLook("up_next", "Up next", (ent) => [
        { type: "text", value: "up next", size: 26, bold: false, x: 40, y: 18, w: 300, h: 34, align: "left" },
        { type: "text", entity: watchEnt(ent), show: "attribute", attribute: "count", suffix: " new", size: 26, bold: false, x: 452, y: 18, w: 300, h: 34, align: "right" },
        { type: "text", entity: watchEnt(ent), show: "attribute", attribute: "up_next", wrap: true, size: 26, bold: false, x: 40, y: 68, w: 712, h: 160, align: "left" },
      ]),
    ],
  },
];

/* Guest Wi-Fi: the network's name and password go into the code (and the
   name onto the page), so the page is asked for them, not left with a sample.
   The words sit left of the code, wrapping inside their box at every size. */
export function guestWifi({ ssid = "", password = "", auth = "WPA" } = {}) {
  const name = ssid || "Your network";
  return [
    { type: "box", x: 18, y: 14, w: 756, h: 218, fill: "outline", radius: 16, thickness: 3 },
    { type: "icon", icon: "mdi:wifi", invert: true, radius: 14, x: 42, y: 38, w: 72, h: 72 },
    { type: "text", value: "GUEST WI-FI", size: 42, bold: true, x: 132, y: 36, w: 400, h: 52, align: "left" },
    { type: "text", value: "Point your phone camera at the code to join.", size: 22, bold: false, wrap: true, x: 132, y: 94, w: 400, h: 64, align: "left" },
    { type: "text", value: name, size: 22, bold: true, pill: true, radius: 8, x: 42, y: 172, w: 490, h: 38, align: "center" },
    { type: "qr", qr_mode: "wifi", wifi_ssid: ssid, wifi_password: password, wifi_auth: auth, title: "SCAN TO JOIN", x: 568, y: 24, w: 184, h: 198 },
  ];
}

/* Presets are drawn on the 5.79" (792 × 272, a 32 px footer band:
   theme.band_height(272), pinned by a test). On any other canvas they're
   placed the way the add-on places a design on another size
   (arrange.auto_box): scaled to fit the content area and centred. Upright,
   the page is then rearranged as turning a page upright does. */
export const CANVAS = { w: 792, h: 272, band: 32 };
export function fitToCanvas(elements, g, reflow) {
  if (g.W === CANVAS.w && g.H === CANVAS.h) return elements;
  const s = Math.min(g.W / CANVAS.w, g.safeH / (CANVAS.h - CANVAS.band));
  const ox = (g.W - CANVAS.w * s) / 2, oy = (g.safeH - (CANVAS.h - CANVAS.band) * s) / 2;
  const out = elements.map((el) => {
    const e = { ...el };
    for (const k of ["x", "w"]) if (typeof e[k] === "number") e[k] = Math.round(e[k] * s + (k === "x" ? ox : 0));
    for (const k of ["y", "h"]) if (typeof e[k] === "number") e[k] = Math.round(e[k] * s + (k === "y" ? oy : 0));
    if (typeof e.size === "number" && e.size) e.size = Math.max(8, Math.round(e.size * s));
    return e;
  });
  if (g.portrait && reflow) reflow({ elements: out }, true, g.d);
  return out;
}

export const presetById = (id) => PRESETS.find((p) => p.id === id);
export const groupName = (id) => (GROUPS.find(([g]) => g === id) || [id, id])[1];
export const lookOf = (p, i = 0) => p.looks[Math.min(Math.max(0, i | 0), p.looks.length - 1)];

/* What a look's page is: its elements and when it shows. A widget's own
   condition comes from the widget (conditions.syncWidgetShowIf), so a league
   or series always shows by its own sensor. */
export function pageFor(p, look, ent, extra) {
  const page = { tier: look.tier || p.tier || "rotate", elements: look.make(ent, extra) };
  const showIf = look.showIf || p.showIf;
  if (showIf) { const s = showIf(ent); if (s) page.show_if = s; }
  if (look.widget) {
    const w = page.elements[0], sid = getWidgetSensorId(w);
    page.show_if = w.type === "flight_tracker" ? `{{ states('${sid}') | int(0) > 0 }}` : `{{ is_state('${sid}','active') }}`;
  }
  return page;
}

/* The page a thumbnail draws: the look with the add-on's example values. */
export function examplePage(p, look) {
  const ex = typeof p.example === "function" ? p.example(look) : p.example;
  if (Array.isArray(ex)) return pageFor(p, look, ex[0], ex);
  if (p.needs === "wifi") return pageFor(p, look, "", { ssid: "Guests", password: "example-only", auth: "WPA" });
  return pageFor(p, look, ex || "");
}

/* What a new page is called: the list or sensor it shows, the league or
   series, or else the preset. */
export function pageName(p, look, ent, entName) {
  if (p.namedByEntity && ent) return entName || ent.split(".")[1];
  if (p.name) return p.name(look);
  return p.title;
}

/* Search: every word somewhere in its title, old name, words, group or looks. */
export function matches(p, query) {
  const words = String(query || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const hay = [p.title, p.was || "", p.desc, groupName(p.group), p.kw || "", ...p.looks.map((l) => l.name)].join(" ").toLowerCase();
  return words.every((w) => hay.includes(w));
}

/* Which entities a preset can show, sensible ones first: the Energy
   dashboard's own (tagged), then the right kind (device class, then unit),
   then the rest of its domain, then the other domains it can show
   (`alsoShows`). Each comes back as { e, tag }. */
export function rankSensors(p, ents, energy = {}) {
  const domain = (e) => e.entity_id.split(".")[0];
  const also = p.alsoShows || [];
  const fits = (e) => (p.asks === "jellyfin" ? e.feed === "jellyfin" : domain(e) === p.asks || also.includes(domain(e)));
  const pref = p.prefer || {};
  const fromEnergy = new Set((pref.energy && energy[pref.energy]) || []);
  const score = (e) => fromEnergy.has(e.entity_id) ? 0
    : (pref.device_class || []).includes(e.device_class) ? 1
    : (pref.units || []).includes(e.unit) ? 2
    : p.asks === "jellyfin" || domain(e) === p.asks ? 3 : 4 + also.indexOf(domain(e));
  return ents.filter(fits)
    .map((e, k) => ({ e, k, s: score(e) }))
    .sort((a, b) => a.s - b.s || a.k - b.k)
    .map(({ e, s }) => ({ e, tag: s === 0 ? "From your Energy dashboard" : "" }));
}

/* A data source a preset sets up: the sensor it makes, and a name no other
   source has (feeds publish sensor.epaper_<name>). */
export const sensorOf = (src) => `sensor.epaper_${src.name}`;
export function freeSourceName(sources, base = "watch") {
  const taken = new Set(sources.map((s) => s.name));
  if (!taken.has(base)) return base;
  let k = 2; while (taken.has(`${base}_${k}`)) k++;
  return `${base}_${k}`;
}

/* Every look as a preset of its own, the shape the 0.10 sheet used: kept for
   the way back (sheets.openPresetsGrid) and for the tests. */
export const LOOKS = PRESETS.flatMap((p) => p.looks.map((l) => ({
  id: l.id, title: p.looks.length > 1 ? `${p.title}: ${l.name}` : p.title, desc: p.desc, asks: p.asks, preset: p.id, look: l.id,
  namedByEntity: p.namedByEntity, tier: l.tier || p.tier,
  showIf: (ent) => pageFor(p, l, ent).show_if || "",
  makeElements: (ent) => l.make(ent),
})));
