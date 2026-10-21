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

// A day counted from today, as a date field writes it (for example values).
const isoDay = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };

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

/* What one sporting event is called, by sport (the user's call: a Premier
   League match is never a game). The sport is the league's first part
   ("soccer/eng.1"); ESPN's "football" is American football. Racing is a race.
   A sport not listed reads as a match. The panel's words are render/sport.py,
   keyed the same way; a test keeps the two the same. */
export const SPORT_WORDS = { soccer: "match", rugby: "match", tennis: "match", cricket: "match",
  basketball: "game", football: "game", baseball: "game", hockey: "game", racing: "race" };
export const sportWord = (league) => SPORT_WORDS[String(league || "soccer/eng.1").trim().toLowerCase().split("/")[0]] || "match";

const calendarMonth = (ent, box) => ({ type: "calendar_month", ...box, show_header: true, show_weekdays: true, first_weekday: 0, highlight_today: true, show_border: true, entity: ent || "" });
const watchLook = (id, name, make) => ({ id, name, tier: "when", showIf: watchShowIf, make });

export const PRESETS = [
  /* ---------- your day ---------- */
  {
    id: "clock", group: "day", title: "Clock", desc: "The time, very large, and today's date.", kw: "time date",
    asks: "", onSleeping: "Shows the date here",
    looks: [{ id: "clock", name: "Clock", make: () => [
      { type: "text", value: "{{ now().strftime('%H:%M') }}", size: 110, bold: true, x: 40, y: 20, w: 450, h: 140, align: "left" },
      { type: "text", value: "{{ now().strftime('%A, %-d %B') }}", size: 36, bold: false, x: 44, y: 168, w: 500, h: 46, align: "left" },
      { type: "icon", icon: "mdi:clock-outline", x: 620, y: 40, w: 120, h: 120 },
    ] }],
  },
  {
    // For anyone who wants only the day and date, on any device (framework review #10).
    id: "date", group: "day", title: "Date", desc: "Today's weekday, large, and the date.", kw: "day weekday today",
    asks: "", looks: [{ id: "date", name: "Date", make: () => DATE_LOOK.make() }],
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
    // Bin day is a countdown that repeats (the user's call, 21 Oct): one preset, what it counts to picked next.
    id: "countdown", group: "day", title: "Countdown", sub: "A date, bin day or an event", kw: "days until date birthday holiday bin bins trash rubbish recycling garbage waste collection",
    desc: "Days until a date of yours, or until the bins go out. No calendar needed; one from Home Assistant works too.",
    asks: "", choose: "Counts down to", name: (look, extra) => (look.id === "countdown_bins" ? "Bin day" : extra?.name || "Countdown"),
    looks: [
      { id: "countdown_date", name: "A date", needs: "date",
        exampleExtra: () => ({ name: "Holiday", at: isoDay(12) }),
        make: (_, x = {}) => [{ type: "countdown", to: "date", name: x.name || "", at: x.at || "", yearly: !!x.yearly, show_before: x.show_before || 0, x: 24, y: 14, w: 744, h: 208 }] },
      { id: "countdown_bins", name: "Bin day", needs: "bins",
        exampleExtra: () => ({ bins: [{ name: "Recycling", from: isoDay(1), every: 2 }, { name: "General waste", from: isoDay(8), every: 2 }], today_until: "noon" }),
        make: (_, x = {}) => [{ type: "countdown", to: "bins", today_until: x.today_until || "noon", bins: x.bins || [], show_before: x.show_before || 0, x: 24, y: 14, w: 744, h: 208 }] },
      { id: "event_countdown", name: "A calendar event", asks: "calendar", example: "calendar.bins", make: (ent) => [
        { type: "icon", icon: "mdi:calendar-clock", x: 32, y: 40, w: 110, h: 110 },
        { type: "number", entity: ent || "", show: "days_until", suffix: " days", decimals: 0, x: 160, y: 24, w: 340, h: 130, align: "left" },
        { type: "text", entity: ent || "", show: "calendar_title", size: 30, bold: false, x: 164, y: 166, w: 300, h: 42, align: "left" },
        { type: "text", entity: ent || "", show: "date_formatted", format: "day_date", size: 28, bold: false, x: 470, y: 166, w: 290, h: 42, align: "right" },
      ] },
    ],
  },

  /* ---------- home ---------- */
  {
    id: "climate", group: "home", title: "Room temperature", desc: "A temperature with a 24-hour curve.", kw: "climate thermometer heat",
    asks: "sensor", prefer: { device_class: ["temperature"], units: ["°C", "°F", "K"] }, example: "sensor.indoor_temperature",
    looks: [{ id: "climate", name: "Room temperature", make: (ent) => [
      { type: "icon", icon: "mdi:thermometer", x: 32, y: 44, w: 116, h: 116 },
      { type: "number", entity: ent || "", show: "state", unit: "entity", decimals: 1, x: 160, y: 30, w: 320, h: 128, align: "left" },
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
      { type: "number", entity: ent || "", show: "state", unit: "entity", decimals: 1, x: 160, y: 30, w: 310, h: 128, align: "left" },
      { type: "text", value: "produced today", size: 30, bold: false, x: 164, y: 170, w: 320, h: 40, align: "left" },
      { type: "curve", entity: ent || "", hours: 24, x: 490, y: 100, w: 270, h: 86 },
    ] }],
  },
  {
    id: "solar_month", group: "energy", title: "Solar this month", kw: "pv panels kwh month statistics production",
    desc: "This month's production, with a bar for each day, from Home Assistant's long-term statistics.",
    asks: "", needs: "energy", energy: "solar",
    looks: [{ id: "solar_month", name: "Solar this month", make: (_, x = {}) => [
      { type: "energy_total", source: x.entity ? "entity" : "solar", entity: x.entity || "", period: "month", x: 24, y: 14, w: 744, h: 208 },
    ] }],
  },
  {
    id: "energy_gauges", group: "energy", title: "Battery and solar", desc: "Home battery and house power as gauges, with today's solar as bars.", kw: "load gauges storage battery house power",
    asks: "", needs: "parts",
    // Each part it shows is asked for in its step (a preset sets up what it needs); the Energy dashboard's first.
    parts: [
      { key: "battery", label: "Home battery", prefer: { device_class: ["battery"], units: ["%"] } },
      { key: "load", label: "House power", prefer: { device_class: ["power"], units: ["W", "kW"], names: ["house", "home", "load", "consumption"] } },
      { key: "solar", label: "Solar power", prefer: { energy: "solar_power", device_class: ["power"], units: ["W", "kW"] } },
    ],
    looks: [{ id: "energy_gauges", name: "Battery and solar", make: (_, x = {}) => [
      { type: "box", x: 18, y: 14, w: 356, h: 218, fill: "outline", radius: 14, thickness: 3 },
      { type: "text", value: "ENERGY & STORAGE", size: 18, bold: true, invert: true, radius: 8, x: 34, y: 28, w: 280, h: 32, align: "center" },
      { type: "bar", entity: x.battery || "", title: "HOME BATTERY", bar_style: "segmented", segments: 10, min_val: 0, max_val: 100, unit: "entity", decimals: 0, show_label: true, x: 34, y: 74, w: 324, h: 66 },
      { type: "bar", entity: x.load || "", title: "HOUSE POWER", bar_style: "solid", min_val: 0, max_val: "power", unit: "entity", decimals: 0, show_label: true, x: 34, y: 152, w: 324, h: 64 },
      { type: "bar_chart", entity: x.solar || "", title: "24H GENERATION", hours: 24, bars: 12, show_labels: true, show_border: true, x: 390, y: 14, w: 384, h: 218 },
    ] }],
  },
  {
    id: "grid_now", group: "energy", title: "Grid now", kw: "import export buying selling power electricity",
    desc: "Buying or selling right now, and today's hours, from your Energy dashboard's grid sensors.",
    asks: "", needs: "energy", energy: "grid",
    looks: [{ id: "grid_now", name: "Grid now", make: (_, x = {}) => [{ type: "grid_now", entity: x.entity || "", invert: !!x.invert, x: 24, y: 14, w: 744, h: 208 }] }],
  },
  {
    id: "energy_cost", group: "energy", title: "Energy cost", kw: "money profit net cost tariff price earned spent",
    desc: "What you earned or spent today and this month, from the prices in your Energy dashboard, in your Home Assistant currency.",
    asks: "", needs: "energy", energy: "cost",
    looks: [{ id: "energy_cost", name: "Energy cost", make: () => [{ type: "energy_cost", x: 24, y: 14, w: 744, h: 208 }] }],
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
    id: "match", group: "sports", title: "Scores", was: "Match score",
    kw: "match game football soccer score " + LEAGUES.map(([, n]) => n).join(" ") + " basketball hockey baseball",
    desc: "The live score and clock, and who scored where the sport says. Shows only around your league's days, from shortly before the start to just after the end.",
    asks: "", choose: "League", name: (look) => look.name,
    looks: LEAGUES.map(([league, name]) => ({
      id: "sports_match_" + (LEAGUE_TO_SLUG[league] || league), name, tier: "when", widget: true,
      note: `Shows on ${sportWord(league)} days.`,
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
    id: "now_playing", group: "media", title: "Now playing", kw: "music spotify sonos media player song apple tv plex jellyfin chromecast",
    desc: "What's playing on any media player in Home Assistant: Spotify, Sonos, Apple TV, Plex, Jellyfin through JellyHA. Only shows while something plays.",
    asks: "", needs: "players", example: "media_player.living_room",
    looks: [{ id: "now_playing", name: "Now playing", tier: "when", showIf: (_, x) => playingShowIf(x?.entity),
      make: (_, x = {}) => [{ type: "now_playing", entity: x.entity || "", x: 24, y: 14, w: 744, h: 208 }] }],
  },
  {
    id: "tv_week", group: "media", title: "On TV this week", kw: "episodes shows sonarr trakt upcoming series calendar",
    desc: "The next episodes from any calendar of shows you follow, such as Sonarr's, or Trakt's through its add-on.",
    asks: "calendar", prefer: { names: ["sonarr", "trakt", "tv", "show", "episode", "series"] }, example: "calendar.tv",
    looks: [{ id: "tv_week", name: "On TV this week", make: (ent) => [{ type: "tv_week", entity: ent || "", days: 7, x: 24, y: 14, w: 744, h: 208 }] }],
  },
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

/* Now playing shows while one of its players plays (all of them when none
   are chosen). */
export function playingShowIf(entity) {
  const chosen = String(entity || "").split(",").map((e) => e.trim()).filter((e) => /^media_player\.[a-z0-9_]+$/.test(e));
  const which = chosen.length ? `expand(${JSON.stringify(chosen).replace(/"/g, "'")})` : "states.media_player";
  return `{{ ${which} | selectattr('state', 'eq', 'playing') | list | count > 0 }}`;
}

/* A device that sleeps between updates (Update every 2 minutes or more, a
   TRMNL) shows what it got at its last update, so a clock there would stop
   at that time, and changing at every wake it would download and flash each
   time. There the Clock preset is a large Date instead (the user's call,
   21 Oct); the footer says "updated HH:MM" for the same reason. Read from the
   device's timers (timing.py), never its kind. */
export const sleepsBetweenUpdates = (screen) => (screen?.timing ? !screen.timing.always_on : !!screen?.sleeps);
export const DATE_LOOK = { id: "date", name: "Date", make: () => [
  { type: "text", value: "{{ now().strftime('%A') }}", size: 96, bold: true, x: 40, y: 24, w: 560, h: 120, align: "left" },
  { type: "text", value: "{{ now().strftime('%-d %B %Y') }}", size: 40, bold: false, x: 44, y: 152, w: 560, h: 52, align: "left" },
  { type: "icon", icon: "mdi:calendar-today", x: 620, y: 40, w: 120, h: 120 },
] };
/* The 0.15 draft's Clock-becomes-Date at creation, kept off as the way back:
   it changed a design shared with an always-on device (framework review #10).
   New page now offers Clock everywhere, says "Shows the date here" on a device
   that sleeps, and the renderer does the rest (render/clocktime.py). */
export function forDevice(p, sleeps) {
  if (p.id !== "clock" || !sleeps) return p;
  return { ...p, title: "Date", kw: `${p.kw} clock day weekday`, looks: [DATE_LOOK],
    desc: "Today's weekday and date, large. This device sleeps between updates, so a clock would stop at the time of its last one." };
}

/* Used only by the way back (sheets.offerTheDate, kept off): what shows the
   time is render/clocktime.py's to say, and the editor reads it from the
   render's metrics (date_for_time). A clock on a page: a text whose template
   shows the time of day. */
const TIME = /now\(\)[^}]*strftime\([^)]*%-?[HIklMp]/;
export const showsTime = (el) => el?.type === "text" && TIME.test(String(el.value || ""));
export const clockPages = (pages) => Object.keys(pages || {}).filter((n) => (pages[n].elements || []).some(showsTime));
/* The date instead: a page made from the Clock preset becomes the Date
   look, in the same place on the canvas; elsewhere a clock's text shows the
   day and month. Returns the elements, ready to replace the page's. */
export function dateInstead(elements) {
  const clockish = elements.every((e) => showsTime(e) || (e.type === "text" && /strftime/.test(String(e.value || ""))) || (e.type === "icon" && /clock/.test(String(e.icon || ""))));
  if (clockish && elements.some(showsTime)) {
    const made = DATE_LOOK.make();
    const time = elements.find(showsTime), base = presetById("clock").looks[0].make()[0];
    const s = time.w / base.w || 1, ox = time.x - base.x * s, oy = time.y - base.y * s;   // where the clock was put, and how big
    // Each keeps the ID of the part it replaces, so its places on other sizes stay its own.
    const was = [time, elements.find((e) => e !== time && e.type === "text"), elements.find((e) => e.type === "icon")];
    return made.map((e, k) => ({ ...e, ...(was[k]?.id ? { id: was[k].id } : {}), x: Math.round(e.x * s + ox), y: Math.round(e.y * s + oy), w: Math.round(e.w * s), h: Math.round(e.h * s),
      ...(e.size ? { size: Math.max(8, Math.round(e.size * s)) } : {}) }));
  }
  return elements.map((e) => (showsTime(e) ? { ...e, value: "{{ now().strftime('%-d %B') }}" } : e));
}

/* How fast what a page shows changes, as a rule rather than a list of
   presets: live things (planes overhead, what's playing, a score, the grid
   now) and any value in watts (power is always "now") change every minute.
   On a device that sleeps longer than that between updates, such a page is
   noted, never hidden (the user's call, 21 Oct: "14 minute old plane data
   isn't tragic"); a clock is the exception, it becomes the Date. In minutes;
   null when it changes slowly enough. */
export const LIVE_TYPES = ["flight_tracker", "now_playing", "sports_match", "grid_now"];
const POWER_UNIT = /^\s*[kMm]?W\s*$/;                    // W, kW, MW; never Wh
export function changesEvery(el, entMap) {
  if (!el) return null;
  if (LIVE_TYPES.includes(el.type)) return 1;
  if (["number", "text", "bar", "curve", "bar_chart"].includes(el.type)) {
    const unit = (el.entity && entMap?.get?.(el.entity)?.unit) || el.suffix || "";
    if (POWER_UNIT.test(unit)) return 1;
  }
  return null;
}
export function pageChangesEvery(elements, entMap) {
  const all = (elements || []).map((e) => changesEvery(e, entMap)).filter((m) => m != null);
  return all.length ? Math.min(...all) : null;
}
const inWords = (m) => (m < 60 ? `${m} min` : m % 60 ? `${+(m / 60).toFixed(1)} hours` : m === 60 ? "1 hour" : `${m / 60} hours`);
/* The one line, with the device's own interval; "" when it keeps up. `short` for a card. */
export function staleNote(minutes, screen, { short = false } = {}) {
  const every = screen?.timing?.update_minutes;
  if (minutes == null || !sleepsBetweenUpdates(screen) || !every || every <= minutes) return "";
  return short ? `Up to ${inWords(every)} old here`
    : `Changes faster than this device updates (every ${inWords(every)}), so it can be up to ${inWords(every)} old.`;
}
/* A preset's, from what its looks show. */
export const presetChangesEvery = (p) => {
  const all = p.looks.map((l) => pageChangesEvery(examplePage(p, l).elements)).filter((m) => m != null);   // with real units
  return all.length ? Math.min(...all) : null;
};

export const presetById = (id) => PRESETS.find((p) => p.id === id);
export const groupName = (id) => (GROUPS.find(([g]) => g === id) || [id, id])[1];
export const lookOf = (p, i = 0) => p.looks[Math.min(Math.max(0, i | 0), p.looks.length - 1)];
/* What a look asks for or sets up: its own, or else its preset's. */
export const asksOf = (p, look) => (look.asks !== undefined ? look.asks : p.asks);
export const needsOf = (p, look) => (look.needs !== undefined ? look.needs : p.needs);

/* What a look's page is: its elements and when it shows. A widget's own
   condition comes from the widget (conditions.syncWidgetShowIf), so a league
   or series always shows by its own sensor. */
export function pageFor(p, look, ent, extra, unitOf = () => "") {
  const page = { tier: look.tier || p.tier || "rotate", elements: withUnits(look.make(ent, extra), unitOf) };
  const showIf = look.showIf || p.showIf;
  if (showIf) { const s = showIf(ent, extra); if (s) page.show_if = s; }
  if (look.widget) {
    const w = page.elements[0], sid = getWidgetSensorId(w);
    page.show_if = w.type === "flight_tracker" ? `{{ states('${sid}') | int(0) > 0 }}` : `{{ is_state('${sid}','active') }}`;
  }
  return page;
}

/* A preset never writes a unit (framework review #1): an element marked
   unit: "entity" shows its sensor's own unit, or none when it has none, so a
   °F home reads °F. A gauge marked max_val: "power" goes to 5000 in watts,
   5 in kW. `unitOf(entityId)` is the editor's entity list; the thumbnails'
   examples use the example sensors' own units (render/fixture.json). */
export const EXAMPLE_UNITS = { "sensor.indoor_temperature": "°C", "sensor.solar_today_production": "kWh", "sensor.home_battery": "%",
  "sensor.house_power": "W", "sensor.solar_pv_power": "W" };
const EXAMPLE_PARTS = { battery: "sensor.home_battery", load: "sensor.house_power", solar: "sensor.solar_pv_power" };
const exampleUnit = (id) => EXAMPLE_UNITS[id] || "";
const POWER_MAX = { W: 5000, kW: 5, MW: 0.005 };
export function withUnits(elements, unitOf = () => "") {
  return elements.map((el) => {
    if (el.unit !== "entity" && el.max_val !== "power") return el;
    const e = { ...el }, u = e.entity ? String(unitOf(e.entity) || "") : "";
    // No unit is an empty suffix, not a missing one: a gauge with none would add its own "%".
    if (e.unit === "entity") { delete e.unit; e.suffix = !u ? "" : u === "%" ? "%" : ` ${u}`; }
    if (e.max_val === "power") { e.max_val = POWER_MAX[u] ?? 5000; if (u === "kW" || u === "MW") e.decimals = 1; }
    return e;
  });
}

/* The page a thumbnail draws: the look with the add-on's example values. */
export function examplePage(p, look) {
  if (look.exampleExtra) return pageFor(p, look, "", look.exampleExtra(), exampleUnit);
  if (p.needs === "parts") return pageFor(p, look, "", EXAMPLE_PARTS, exampleUnit);
  const ex = look.example || (typeof p.example === "function" ? p.example(look) : p.example);
  if (Array.isArray(ex)) return pageFor(p, look, ex[0], ex, exampleUnit);
  if (p.needs === "wifi") return pageFor(p, look, "", { ssid: "Guests", password: "example-only", auth: "WPA" });
  return pageFor(p, look, ex || "", undefined, exampleUnit);
}

/* What a new page is called: the list or sensor it shows, the league or
   series, or else the preset. */
export function pageName(p, look, ent, entName, extra) {
  if (p.namedByEntity && ent) return entName || ent.split(".")[1];
  if (p.name) return p.name(look, extra);
  return p.title;
}

/* Search: every word somewhere in its title, old name, words, group or
   looks. What you typed as a name comes first ("on now" finds Dynamic status,
   then Now playing). */
export function matches(p, query) {
  const words = String(query || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const hay = [p.title, p.was || "", p.desc, groupName(p.group), p.kw || "", ...p.looks.map((l) => l.name)].join(" ").toLowerCase();
  return words.every((w) => hay.includes(w));
}
export function search(query, list = PRESETS) {
  const q = String(query || "").trim().toLowerCase();
  const named = (p) => [p.title, p.was || "", ...p.looks.map((l) => l.name)].some((n) => n.toLowerCase().includes(q));
  return list.filter((p) => matches(p, q)).map((p, k) => ({ p, k, s: named(p) ? 0 : 1 })).sort((a, b) => a.s - b.s || a.k - b.k).map(({ p }) => p);
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
  const named = (e) => (pref.names || []).some((n) => `${e.entity_id} ${e.name || ""}`.toLowerCase().includes(n));
  const score = (e) => fromEnergy.has(e.entity_id) ? 0
    : (pref.device_class || []).includes(e.device_class) || named(e) ? 1
    : (pref.units || []).includes(e.unit) ? 2
    : pref.names ? (domain(e) === p.asks ? 3 : 4)
    : p.asks === "jellyfin" || domain(e) === p.asks ? 3 : 4 + also.indexOf(domain(e));
  return ents.filter(fits)
    .map((e, k) => ({ e, k, s: score(e) }))
    .sort((a, b) => a.s - b.s || a.k - b.k)
    .map(({ e, s }) => ({ e, tag: s === 0 ? "From your Energy dashboard" : "" }));
}

/* The Energy dashboard, asked once per editor session (GET /api/energy:
   {solar: [{energy, power}], grid: [{flows, power}], has_cost, currency}),
   with the sensors it uses by role for rankSensors. `known` is false when
   Home Assistant didn't say. */
export function energyRoles(body) {
  const solar = body.solar || [], grid = body.grid || [];
  const ids = (xs) => [...new Set(xs.filter(Boolean))];
  return {
    known: true, has_cost: !!body.has_cost, currency: body.currency || "",
    solar: ids(solar.flatMap((x) => [x.energy, x.power])),
    solar_energy: ids(solar.map((x) => x.energy)),
    solar_power: ids(solar.map((x) => x.power)),
    grid: ids(grid.flatMap((x) => [...(x.flows || []).flatMap((f) => [f.import, f.export]), x.power?.plus, x.power?.minus])),
    grid_power: ids(grid.flatMap((x) => [x.power?.plus, x.power?.minus])),
  };
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
