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

import { gateOf, gateShowIf, todoShowIf, WIDGET_WRITES_CONDITION } from "./legacy.js";
import { leagues, series, widgetChangesEvery, stateWords, stateWord, pageWord, pageNameWord } from "./catalog.js";

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

// The leagues and series come from the add-on's catalog (catalog.js), never a copy here:
// Scores and Race weekend offer exactly what it fetches, in its order. Their Hours before and
// after are left unset: the add-on's own number (sources.HOURS_AROUND) until the person changes them.
const memo = (fn) => { let key, val; return () => { const k = fn.key(); if (k !== key) { key = k; val = fn(); } return val; }; };
const leagueLooks = Object.assign(() => leagues().map((lg) => ({
  id: "sports_match_" + lg.slug, name: lg.name, tier: "when", widget: true,
  note: `Shows on ${(lg.words || {}).event || "match"} days.`,
  make: () => [boxed({ type: "sports_match", league: lg.path, team: "", entity: "", auto_window: true })],
})), { key: () => leagues() });
const seriesLooks = Object.assign(() => series().map((sr) => ({
  id: "sports_racing_" + sr.slug, name: sr.title, tier: "when", widget: true,
  make: () => [boxed({ type: "sports_racing", series: sr.slug, entity: "", window_mode: "session", auto_window: true })],
})), { key: () => series() });
const LEAGUE_LOOKS = memo(leagueLooks), SERIES_LOOKS = memo(seriesLooks);

const calendarMonth = (ent, box) => ({ type: "calendar_month", ...box, show_header: true, show_weekdays: true, first_weekday: 0, highlight_today: true, show_border: true, entity: ent || "" });
const watchLook = (id, name, make) => ({ id, name, tier: "when", showIf: watchShowIf, make });

export const PRESETS = [
  /* ---------- your day ---------- */
  {
    id: "clock", group: "day", title: "Clock", desc: "The time, very large, and today's date; or the time in up to four cities.", kw: "time date world clock time zones cities",
    asks: "", onSleeping: "Shows the date here", choose: "Style",
    looks: [{ id: "clock", name: "Clock", onSleeping: "This device sleeps between updates, so it shows the date instead of a time that would stop.", make: () => [
      // The add-on's own clock (framework review #9): 12- or 24-hour as Settings › Time and language says.
      { type: "text", show: "now", format: "time", size: 110, bold: true, x: 40, y: 20, w: 450, h: 140, align: "left" },
      { type: "text", show: "now", format: "day_full", size: 36, bold: false, x: 44, y: 168, w: 500, h: 46, align: "left" },
      { type: "icon", icon: "mdi:clock-outline", x: 620, y: 40, w: 120, h: 120 },
    ] },
    // A world clock (the world_clock widget): up to four cities, laid out alike by the renderer.
    { id: "world_clock", name: "Time zones", needs: "zones",
      onSleeping: "This device sleeps between updates, so each city shows how many hours it's ahead or behind, not a time that would stop.",
      exampleExtra: () => ({ zones: [{ tz: "", label: "" }, { tz: "America/New_York", label: "" }, { tz: "Asia/Tokyo", label: "" }] }),
      make: (_, x = {}) => [{ type: "world_clock", zones: x.zones?.length ? x.zones : [{ tz: "", label: "" }], x: 24, y: 14, w: 744, h: 208 }] }],
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
        { type: "calendar_agenda", x: 396, y: 12, w: 380, h: 228, title: pageWord("coming_up"), max_events: 4, show_border: true, entity: ent || "" },
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
    asks: "", choose: "Counts down to", name: (look, extra) => (look.id === "countdown_bins" ? pageNameWord("bin_day") : extra?.name || pageNameWord("countdown")),
    looks: [
      { id: "countdown_date", name: "A date", needs: "date",
        exampleExtra: () => ({ name: pageWord("holiday"), at: isoDay(12) }),
        make: (_, x = {}) => [{ type: "countdown", to: "date", name: x.name || "", at: x.at || "", yearly: !!x.yearly, show_before: x.show_before || 0, x: 24, y: 14, w: 744, h: 208 }] },
      { id: "countdown_bins", name: "Bin day", needs: "bins",
        exampleExtra: () => ({ bins: [{ name: pageWord("recycling"), from: isoDay(1), every: 2 }, { name: pageWord("general_waste"), from: isoDay(8), every: 2 }], today_until: "noon" }),
        make: (_, x = {}) => [{ type: "countdown", to: "bins", today_until: x.today_until || "noon", ...(x.numbers ? { numbers: true } : {}), bins: x.bins || [], show_before: x.show_before || 0, x: 24, y: 14, w: 744, h: 208 }] },
      { id: "event_countdown", name: "A calendar event", asks: "calendar", example: "calendar.bins", make: (ent) => [
        { type: "icon", icon: "mdi:calendar-clock", x: 32, y: 40, w: 110, h: 110 },
        { type: "number", entity: ent || "", show: "days_until", suffix: pageWord("days"), decimals: 0, x: 160, y: 24, w: 340, h: 130, align: "left" },
        { type: "text", entity: ent || "", show: "calendar_title", size: 30, bold: false, x: 164, y: 166, w: 300, h: 42, align: "left" },
        { type: "text", entity: ent || "", show: "date_formatted", format: "day_date", size: 28, bold: false, x: 470, y: 166, w: 290, h: 42, align: "right" },
      ] },
    ],
  },

  {
    // Travel times from Home Assistant (Waze Travel Time needs no key), each against its own usual.
    id: "commute", group: "day", title: "Commute", kw: "travel time traffic waze google here route drive driving work school car",
    desc: "How long the drive takes now, against the usual for this hour, from the travel times in Home Assistant. Waze Travel Time needs no account.",
    asks: "", needs: "found", found: "commute",
    looks: [{ id: "commute", name: "Commute", make: (_, x = {}) => [{ type: "commute", entities: x.entities || [], x: 24, y: 14, w: 744, h: 208 }] }],
  },
  {
    // The next departures from any transit integration: the add-on reads each one's shape (sources/departures.py).
    id: "departures", group: "day", title: "Departures", kw: "bus tram train metro subway transit public transport gtfs timetable stop station",
    desc: "The next buses, trams or trains from your stop, from any transit integration in Home Assistant.",
    asks: "", needs: "found", found: "departures",
    looks: [{ id: "departures", name: "Departures", make: (_, x = {}) => [{ type: "departures", entities: x.entities || [], x: 24, y: 14, w: 744, h: 208 }] }],
  },

  /* ---------- home ---------- */
  {
    id: "climate", group: "home", title: "Room temperature", desc: "A temperature with a 24-hour curve.", kw: "climate thermometer heat",
    asks: "sensor", prefer: { device_class: ["temperature"], units: ["°C", "°F", "K"] }, example: "sensor.indoor_temperature",
    looks: [{ id: "climate", name: "Room temperature", make: (ent) => [
      { type: "icon", icon: "mdi:thermometer", x: 32, y: 44, w: 116, h: 116 },
      { type: "number", entity: ent || "", show: "state", unit: "entity", decimals: 1, x: 160, y: 30, w: 320, h: 128, align: "left" },
      { type: "text", value: pageWord("room_climate"), size: 30, bold: false, x: 164, y: 170, w: 320, h: 40, align: "left" },
      { type: "curve", entity: ent || "", hours: 24, x: 490, y: 100, w: 270, h: 86 },
    ] }],
  },
  {
    id: "status", group: "home", title: "Status", was: "Door or pet", kw: "door pet cat presence window state since open closed",
    desc: "Any sensor's state in your own words (Open, Home, Running) and how long it's been that way.",
    asks: "binary_sensor", alsoShows: ["person", "device_tracker", "lock", "cover", "input_boolean", "switch", "sensor"],
    example: "binary_sensor.front_door", namedByEntity: true,
    looks: [{ id: "presence_door", name: "Status", make: (ent) => [
      // Its words and icon are the picked sensor's kind's (framework review #2): Home Assistant's own.
      { type: "icon", entity: ent || "", icon: "entity", x: 32, y: 44, w: 116, h: 116 },
      { type: "text", entity: ent || "", show: "state", words: "entity", max_size: 80, bold: true, x: 164, y: 30, w: 580, h: 128, align: "left" },
      { type: "text", entity: ent || "", show: "last_changed", format: "relative", prefix: pageWord("for"), size: 30, bold: false, x: 164, y: 170, w: 420, h: 40, align: "left" },
    ] }],
  },
  {
    id: "dynamic_status", group: "home", title: "Dynamic status", was: "On now", kw: "what's on heaters lights devices dynamic running",
    desc: "Up to eight things, each shown only while it's in a state you choose: on, open, home, running.",
    asks: "", example: ["timer.dryer_cycle", "person.partner", "sensor.cat_location", "binary_sensor.front_door"],
    looks: [{ id: "dynamic_entities", name: "Dynamic status", tier: "when", make: (ent, ex) => [{
      type: "dynamic_grid", x: 20, y: 16, w: 752, h: 214,
      header_icon: "mdi:lightning-bolt", header_title: pageWord("on_now"), filter_state: "on",
      layout_mode: "grid", show_labels: "both", icon_size: "auto", secondary_mode: "runtime",
      items: ex ? ex.map((e) => ({ entity: e, name: "", icon: "" }))
        : ["mdi:radiator", "mdi:radiator", "mdi:paw", "mdi:bed"].map((icon, k) => ({ entity: k ? "" : ent || "", name: pageWord("spot", k + 1), icon })),
    }] }],
  },
  {
    // Dynamic status by a number (the user's call, 22 Oct): each battery shows while it's below the
    // page's number (or its own), the page only while one does; or, the other way, the charged ones.
    id: "batteries", group: "home", title: "Batteries", kw: "battery batteries low charge charged level remote sensor phone alert",
    desc: "The batteries that need charging, emptiest first, or the ones that are charged. Shows only while one does.",
    asks: "", needs: "batteries", name: (_, x = {}) => pageNameWord(x.rule === "at_least" ? "charged" : "low_batteries"),
    looks: [{ id: "batteries", name: "Batteries", tier: (x = {}) => (x.tier === "alert" ? "alert" : "when"),
      exampleExtra: () => ({ rule: "below", value: 40, items: ["sensor.smoke_alarm_battery", "sensor.door_sensor_battery", "sensor.remote_battery", "sensor.thermostat_battery"] }),
      make: (_, x = {}) => [batteryGrid(x)] }],
  },
  {
    id: "guest_wifi", group: "home", title: "Guest Wi-Fi", desc: "A code guests scan with their phone camera to join your Wi-Fi.", kw: "qr code network password",
    asks: "", needs: "wifi",
    looks: [{ id: "guest_wifi", name: "Guest Wi-Fi", make: (_, w = {}) => guestWifi(w) }],
  },
  {
    // Home Assistant's bell. Its page shows by the add-on's own count (widgets.py "sensor").
    id: "notifications", group: "home", title: "Notifications", kw: "bell alerts messages persistent home assistant",
    desc: "Home Assistant's notifications, newest first, and how long ago each came. Only shows while there are any.",
    asks: "",
    looks: [{ id: "notifications", name: "Notifications", tier: "when", widget: true,
      make: () => [{ type: "notifications", x: 40, y: 14, w: 712, h: 220 }] }],
  },
  {
    id: "updates", group: "home", title: "Updates", kw: "upgrade firmware add-ons hacs integrations version home assistant",
    desc: "Every update waiting in Home Assistant, by Home Assistant, add-ons, integrations and devices. Only shows while there are any.",
    asks: "",
    looks: [{ id: "updates", name: "Updates", tier: "when", widget: true,
      make: () => [{ type: "updates", x: 40, y: 14, w: 712, h: 220 }] }],
  },

  {
    // Home Assistant's IMAP integration holds the password; the add-on hears the new mail it announces.
    id: "mail", group: "home", title: "Mail", kw: "email e-mail inbox imap unread messages letters",
    desc: "Your latest unread mail, who it's from and the subject, from Home Assistant's IMAP integration. Only shows while there's unread mail.",
    asks: "", needs: "mail",
    looks: [{ id: "mail", name: "Mail", tier: "when", widget: true,
      make: (_, x = {}) => [{ type: "mail_list", entity: x.entity || "", x: 40, y: 14, w: 712, h: 220 }] }],
  },
  {
    // A square per day (render/yeargrid.py): one widget, many sources; the grid never knows which.
    id: "year_grid", group: "home", title: "Year grid", kw: "github contributions streak heatmap days year history statistics solar steps heating",
    desc: "A square for each day of the past year, larger for more, with the total and streaks beside it: any daily number from Home Assistant, or someone's GitHub contributions.",
    asks: "", choose: "From", prefer: { device_class: ["energy", "duration", "water", "gas"], units: ["kWh", "h", "min", "steps", "L", "m³"] },
    example: "sensor.solar_today_production",
    looks: [
      { id: "year_grid_sensor", name: "A sensor", asks: "sensor",
        make: (ent) => [{ type: "year_grid", source: "statistic", entity: ent || "", x: 24, y: 14, w: 744, h: 208 }] },
      { id: "year_grid_github", name: "GitHub", needs: "github", exampleExtra: () => ({}),
        make: (_, x = {}) => [{ type: "year_grid", source: "github", user: x.user || "", x: 24, y: 14, w: 744, h: 208 }] },
    ],
  },

  /* ---------- energy ---------- */
  {
    id: "solar", group: "energy", title: "Solar today", desc: "What the panels made today, with a 24-hour curve.", kw: "pv panels kwh production",
    asks: "sensor", prefer: { energy: "solar", device_class: ["energy"], units: ["kWh", "Wh", "MWh"] }, example: "sensor.solar_today_production",
    looks: [{ id: "solar", name: "Solar today", make: (ent) => [
      { type: "icon", icon: "mdi:white-balance-sunny", x: 32, y: 44, w: 116, h: 116 },
      { type: "number", entity: ent || "", show: "state", unit: "entity", total: "today", decimals: 1, x: 160, y: 30, w: 310, h: 128, align: "left" },
      { type: "text", value: pageWord("produced_today"), size: 30, bold: false, x: 164, y: 170, w: 320, h: 40, align: "left" },
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
      { type: "text", value: pageWord("energy_storage"), size: 18, bold: true, invert: true, radius: 8, x: 34, y: 28, w: 280, h: 32, align: "center" },
      { type: "bar", entity: x.battery || "", title: pageWord("home_battery"), bar_style: "segmented", segments: 10, min_val: 0, max_val: 100, unit: "entity", decimals: 0, show_label: true, x: 34, y: 74, w: 324, h: 66 },
      { type: "bar", entity: x.load || "", title: pageWord("house_power"), bar_style: "solid", min_val: 0, max_val: "power", unit: "entity", decimals: 0, show_label: true, x: 34, y: 152, w: 324, h: 64 },
      { type: "bar_chart", entity: x.solar || "", title: pageWord("generation_24h"), hours: 24, bars: 12, show_labels: true, show_border: true, x: 390, y: 14, w: 384, h: 218 },
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
    get kw() { return "match game football soccer score basketball hockey baseball " + leagues().map((l) => l.name).join(" "); },
    desc: "The live score and clock, and who scored where the sport says. Shows only around your league's days, from shortly before the start to just after the end.",
    asks: "", choose: "League", name: (look) => look.name,
    get looks() { return LEAGUE_LOOKS(); },
  },
  {
    id: "race_weekend", group: "sports", title: "Race weekend", was: "Formula 1",
    get kw() { return "racing motorsport grand prix f1 " + series().map((x) => `${x.title} ${x.code}`).join(" "); },
    desc: "The top ten and their gaps while a session runs; the countdown to the next one the rest of the week.",
    asks: "", choose: "Series", name: (look) => look.name,
    get looks() { return SERIES_LOOKS(); },
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
        { type: "text", value: pageWord("new_to_watch"), size: 26, bold: false, x: 40, y: 28, w: 300, h: 36, align: "left" },
        { type: "text", entity: watchEnt(ent), show: "attribute", attribute: "detail", size: 26, bold: false, x: 352, y: 28, w: 400, h: 36, align: "right" },
        { type: "text", entity: watchEnt(ent), x: 40, y: 74, w: 712, h: 150, align: "left" },
      ]),
      watchLook("episode", "Episode card", (ent) => [
        { type: "text", entity: watchEnt(ent), x: 40, y: 22, w: 712, h: 96, align: "left" },
        { type: "text", entity: watchEnt(ent), show: "attribute", attribute: "about", size: 34, bold: false, x: 40, y: 128, w: 712, h: 46, align: "left" },
        { type: "text", entity: watchEnt(ent), show: "attribute", attribute: "added_ago", prefix: pageWord("added"), size: 26, bold: false, x: 40, y: 188, w: 420, h: 36, align: "left" },
      ]),
      watchLook("up_next", "Up next", (ent) => [
        { type: "text", value: pageWord("up_next"), size: 26, bold: false, x: 40, y: 18, w: 300, h: 34, align: "left" },
        { type: "text", entity: watchEnt(ent), show: "attribute", attribute: "count", suffix: pageWord("n_new"), size: 26, bold: false, x: 452, y: 18, w: 300, h: 34, align: "right" },
        { type: "text", entity: watchEnt(ent), show: "attribute", attribute: "up_next", wrap: true, size: 26, bold: false, x: 40, y: 68, w: 712, h: 160, align: "left" },
      ]),
    ],
  },
];

/* Guest Wi-Fi: the network's name and password go into the code (and the
   name onto the page), so the page is asked for them, not left with a sample.
   The words sit left of the code, wrapping inside their box at every size. */
export function guestWifi({ ssid = "", password = "", auth = "WPA" } = {}) {
  const name = ssid || pageWord("your_network");
  return [
    { type: "box", x: 18, y: 14, w: 756, h: 218, fill: "outline", radius: 16, thickness: 3 },
    { type: "icon", icon: "mdi:wifi", invert: true, radius: 14, x: 42, y: 38, w: 72, h: 72 },
    { type: "text", value: pageWord("guest_wifi"), size: 42, bold: true, x: 132, y: 36, w: 400, h: 52, align: "left" },
    { type: "text", value: pageWord("scan_hint"), size: 22, bold: false, wrap: true, x: 132, y: 94, w: 400, h: 64, align: "left" },
    { type: "text", value: name, size: 22, bold: true, pill: true, radius: 8, x: 42, y: 172, w: 490, h: 38, align: "center" },
    { type: "qr", qr_mode: "wifi", wifi_ssid: ssid, wifi_password: password, wifi_auth: auth, title: pageWord("scan"), x: 568, y: 24, w: 184, h: 198 },
  ];
}

/* Presets are drawn on the 5.79" (792 × 272). On any other canvas the add-on
   places them as it places a design on another size (POST /api/fit,
   arrange.auto_box); upright, the editor then rearranges the page as
   turning a page upright does (newpage.fitToDevice). */
export const CANVAS = { w: 792, h: 272, band: 32 };

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
   presets: a widget says how often in its descriptor (planes overhead,
   what's playing, a score, a race, the grid now), and a plain sensor as
   the add-on's entity list says (/api/entities `changes_every`, from Home
   Assistant's own device class: power, wind...). A value with no sensor the
   list knows, only its unit, counts as "now" when it's in watts.
   On a device that sleeps longer than that between updates, such a page is
   noted, never hidden (the user's call, 21 Oct: "14 minute old plane data
   isn't tragic"); a clock is the exception, it becomes the Date. In minutes;
   null when it changes slowly enough. */
const POWER_UNIT = /^\s*[kMm]?W\s*$/;                    // W, kW, MW; never Wh
export function changesEvery(el, entMap) {
  if (!el) return null;
  const live = widgetChangesEvery(el);                      // a widget's, from its descriptor (the add-on's)
  if (live != null) return live;
  if (["number", "text", "bar", "curve", "bar_chart"].includes(el.type)) {
    const ent = el.entity && entMap?.get?.(el.entity);
    if (ent && "changes_every" in ent) return ent.changes_every ? Math.max(1, Math.round(ent.changes_every / 60)) : null;
    // A unit that follows its sensor is the sensor's (an example's in a thumbnail: EXAMPLE_UNITS).
    const unit = ent?.unit || (el.unit === "entity" ? EXAMPLE_UNITS[el.entity] || "" : el.suffix) || "";
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

/* What a look's page is: its elements and when it shows. Since 0.21.1 a
   widget's own part is the page's "Something on it to show", answered by the
   add-on (widgets.widget_part), never written as the page's condition. */
export function pageFor(p, look, ent, extra, unitOf = () => "") {
  const tier = typeof look.tier === "function" ? look.tier(extra) : look.tier;    // a look may ask its step (Batteries: an alert)
  const page = { tier: tier || p.tier || "rotate", elements: withUnits(look.make(ent, extra), unitOf) };
  const showIf = look.showIf || p.showIf;
  if (showIf) { const s = showIf(ent, extra); if (s) page.show_if = s; }
  if (look.widget && WIDGET_WRITES_CONDITION) {
    const c = gateShowIf(page.elements[0]);          // the widget's own, from its descriptor's gate
    if (c) page.show_if = c;
  }
  // A look's condition that only says what its widget's part says (a to-do list's count) is the part.
  if (!WIDGET_WRITES_CONDITION && typeof page.show_if === "string" && page.elements.some((el) => gateOf(el) && page.show_if === gateShowIf(el)))
    delete page.show_if;
  return page;
}

/* A preset never writes a unit (framework review #1): an element marked
   unit: "entity" shows its sensor's own unit, or none when it has none, so a
   °F home reads °F. A gauge marked max_val: "power" goes to 5000 in watts,
   5 in kW. `unitOf(entityId)` is the editor's entity list; the thumbnails'
   examples use the example sensors' own units (render/fixture.json). */
/* The example sensors' units (and, for a running total, its state class) as the fixture has them. */
export const EXAMPLE_UNITS = { "sensor.indoor_temperature": "°C", "sensor.solar_today_production": "kWh", "sensor.home_battery": "%",
  "sensor.house_power": "W", "sensor.solar_pv_power": "W" };
const EXAMPLE_CLASSES = { "binary_sensor.front_door": "door" };
const EXAMPLE_PARTS = { battery: "sensor.home_battery", load: "sensor.house_power", solar: "sensor.solar_pv_power" };
const exampleUnit = (id) => ({ unit: EXAMPLE_UNITS[id] || "", device_class: EXAMPLE_CLASSES[id] || "" });
const POWER_MAX = { W: 5000, kW: 5, MW: 0.005 };
/* `total: "today"` (Solar today, framework review #3): a running total (state class total or
   total_increasing: an inverter's lifetime meter, or a daily one) shows how much it went up
   today (binding show "change_today", from long-term statistics), never "18,532 kWh today";
   anything else shows its state. The sensor is still the one you pick. */
const RUNNING = ["total", "total_increasing"];
export function withUnits(elements, infoOf = () => "") {
  const info = (id) => { const r = id ? infoOf(id) : ""; return typeof r === "string" ? { unit: r } : r || {}; };
  return elements.map((el) => {
    if (el.unit !== "entity" && el.max_val !== "power" && !el.total && el.words !== "entity" && el.icon !== "entity") return el;
    const e = { ...el }, about = info(e.entity), u = String(about.unit || "");
    // A state's words and icons, by the sensor's domain and device class (the catalog's): you can still edit them.
    if (e.words === "entity" || (e.type === "icon" && e.icon === "entity")) {
      const words = e.entity ? stateWords(e.entity, about.device_class) : null;
      if (e.words === "entity") { delete e.words; if (words) e.replace = Object.fromEntries(Object.entries(words).map(([k, v]) => [k, stateWord(v.word)])); }
      if (e.icon === "entity") {
        const icons = words ? Object.fromEntries(Object.entries(words).filter(([, v]) => v.icon).map(([k, v]) => [k, v.icon])) : {};
        e.icon = (words && (words.off || Object.values(words)[0])?.icon) || "mdi:information-outline";   // its resting state's
        if (Object.keys(icons).length) e.state_icons = icons;
      }
    }
    if (e.total) { if (RUNNING.includes(about.state_class)) e.show = "change_today"; delete e.total; }
    // The unit follows the sensor at every render (review 2 #3): kept as unit "entity", never copied in,
    // so a unit Home Assistant changes later (°C to °F) changes on the page too (render/units.py).
    if (e.unit === "entity") delete e.suffix;
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
  return pageNameWord(p.id) || p.title;               // in the device's language (catalog.js)
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

/* Batteries (the preset): a Dynamic status grid by a number. Low: below the number, emptiest first;
   charged: at least it, fullest first (render/layout._draw_dynamic_grid). With no icon of its own,
   each shows Home Assistant's glyph for its level. It stores a rule, never today's list (review 2 #5,
   the user's call): every battery of its kind (swap: you change it; charge: you charge it), minus
   `except`, plus `also`, resolved by the add-on at each render (sources/batteries.chosen), so a
   battery added next month shows too. `items` are each battery's own settings, not the list. */
export const BATTERY_DEFAULT = { below: 20, at_least: 90 };
export function batteryGrid(x = {}) {
  const low = x.rule !== "at_least";
  return {
    type: "dynamic_grid", x: 20, y: 16, w: 752, h: 214,
    header_icon: low ? "mdi:battery-alert-variant-outline" : "mdi:battery-check", header_title: pageWord(low ? "name.low_batteries" : "name.charged"),
    filter_rule: low ? "below" : "at_least", filter_value: Number.isFinite(Number(x.value)) && x.value !== "" ? Number(x.value) : BATTERY_DEFAULT[low ? "below" : "at_least"],
    layout_mode: "list", show_labels: "both", icon_size: "auto",          // a row each, so every name reads (the user's call)
    batteries: low ? "swap" : "charge", except: [...(x.except || [])], also: [...(x.also || [])], items: [],
  };
}
/* The rule's lists from the ticks: of this kind and not ticked, left out; of the other kind and
   ticked, also shown. `kindOf(e)` is "charge" or "swap". */
export function batteryRule(all, chosen, rule, kindOf) {
  const kind = rule === "at_least" ? "charge" : "swap";
  return { except: all.filter((e) => kindOf(e) === kind && !chosen.has(e.entity_id)).map((e) => e.entity_id),
           also: all.filter((e) => kindOf(e) !== kind && chosen.has(e.entity_id)).map((e) => e.entity_id) };
}
/* Which batteries a rule shows (the editor's mirror of sources/batteries.chosen, for its ticks). */
export function ruleTicks(all, el, kindOf) {
  const out = new Set(el.also || []), left = new Set(el.except || []);
  for (const e of all) if (kindOf(e) === (el.batteries || "swap") && !left.has(e.entity_id)) out.add(e.entity_id);
  return out;
}
const levelOf = (e) => { if (isLowSensor(e)) return e.state === "on" ? 0 : null; const v = parseFloat(e?.state); return Number.isFinite(v) ? v : null; };
/* Home Assistant's batteries: sensors of device class battery in %, and "battery low" binary sensors
   (on is low), the emptiest first (a low one counts as empty while on). */
export const isLowSensor = (e) => String(e?.entity_id || "").startsWith("binary_sensor.") && e.device_class === "battery";
/* One its integration no longer provides (Home Assistant keeps it, restored) is a leftover, never a
   battery: the editor's mirror of sources/batteries.leftover. */
export function batterySensors(ents) {
  return (ents || []).filter((e) => !e.restored && e.device_class === "battery" && ((String(e.unit || "").trim() === "%" && String(e.entity_id).startsWith("sensor.")) || isLowSensor(e)))
    .map((e, k) => ({ e, k, v: levelOf(e) }))
    .sort((a, b) => (a.v == null) - (b.v == null) || (a.v ?? 0) - (b.v ?? 0) || a.k - b.k)
    .map(({ e }) => e);
}
/* Something you charge yourself (a phone, a watch, a laptop, a car, a home battery) says whether
   it's charging; a battery you swap (a remote, a door sensor) doesn't. `byDevice` is the add-on's
   answer from Home Assistant's registry (GET /api/batteries, sources/batteries.py): its device
   has a charging-state entity, or not. Only a battery with no device (null, or no answer) goes
   by its name: a charging-state sensor named beside it, as the mobile app names them. */
export function chargedByYou(e, ids, byDevice = {}) {
  const said = byDevice[e.entity_id];
  if (said === true || said === false) return said;
  const base = String(e.entity_id).replace(/^(binary_)?sensor\./, "").replace(/_battery(_level|_low)?$/, "");
  return [`sensor.${base}_battery_state`, `sensor.${base}_charging`, `binary_sensor.${base}_charging`, `binary_sensor.${base}_battery_charging`].some((x) => ids.has(x));
}
/* The ones ticked to start with: for Low, every battery with a level that you swap; for Charged,
   the ones you charge. You change the ticks; nothing here is about one home. */
export function preselectBatteries(ents, rule, byDevice = {}) {
  const ids = new Set((ents || []).map((e) => e.entity_id));
  return batterySensors(ents).filter((e) => (levelOf(e) != null || isLowSensor(e)) && chargedByYou(e, ids, byDevice) === (rule === "at_least")).map((e) => e.entity_id);
}
/* A battery that hasn't answered for a while (unavailable or unknown since `changed`) counts on a Low
   page, never a Charged one: the editor's mirror of sources/batteries.silent. `hours` is the rule's
   `no_answer_hours`: 12 when it has none, "never" for none (the way it was before 0.21.1). */
export const NO_ANSWER_HOURS = 12;
export const NO_ANSWER_WAITS = [[1, "1 hour"], [3, "3 hours"], [6, "6 hours"], [12, "12 hours"], [24, "1 day"], [48, "2 days"], ["never", "Never"]];
export function silentBattery(e, rule, hours, now = Date.now()) {
  if (rule === "at_least" || hours == null || !e || !["unavailable", "unknown"].includes(e.state)) return false;
  const at = Date.parse(e.changed || "");
  return Number.isFinite(at) && now - at >= hours * 3600e3;
}
/* How many would show now, as the step says it: past the number, or silent past the wait. */
export function batteriesPast(ents, chosen, rule, value, hours = NO_ANSWER_HOURS, now = Date.now()) {
  const by = new Map((ents || []).map((e) => [e.entity_id, e])), t = Number(value);
  if (!Number.isFinite(t)) return 0;
  return [...chosen].filter((id) => { const e = by.get(id), v = levelOf(e);
    return (v != null && (rule === "at_least" ? v >= t : v < t)) || silentBattery(e, rule, hours, now); }).length;
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
