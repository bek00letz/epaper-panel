"""One descriptor per widget: everything about a kind of widget, in one place.

A widget is an element that draws itself from a value the render cycle
fetches (weather, a calendar, scores, sunrise...). Before 0.15 a new one was
named in about ten places in two languages, and forgetting one failed
quietly. Here each widget says, once:

- what it's called and its icon, its default box and settings, and its
  inspector fields (served to the editor, /api/catalog);
- how its value is fetched (always through live_data, so a render never
  waits) and, for what's live, how often it changes (its live readers' own
  @runtime.live intervals);
- its example value, for thumbnails (examples.py);
- how it's drawn (render/), and whether a list value is several items of
  its page (1 of 3), like planes overhead.

frames.enrich_page_values, examples.page_values, render.layout's dispatch
and render.subitems all read it. Basics (text, value, icon, card, line,
charts, QR) are the editor's own and aren't here.
"""
from __future__ import annotations

import re
import time as _time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable

import examples
import shapes
from render import arrange, layout, sport, subitems
from sources import HOURS_AROUND, batteries, energy, flights, ha_services, home, needs_you, racing, sports, station

# A default box: "fill" takes the content area less `inset` (from `y`); otherwise each size is clamped to it.
FILL = {"fill": True, "y": 14, "inset": 20}
BORDER = {"kind": "toggle", "key": "show_border", "label": "Border", "def": True}
AROUND = f"{HOURS_AROUND:g}"        # what "Hours before" and "Hours after" show until a page says


def sel(key, label, options, default):
    return {"kind": "sel", "key": key, "label": label, "options": options, "def": default}


def entity(key, label, domains=None, **more):
    return {"kind": "entity", "key": key, "label": label, **({"domains": domains} if domains else {}), **more}


def text(key, label, ph):
    return {"kind": "text", "key": key, "label": label, "ph": ph}


def num(key, label, ph, lo=None, hi=None, step=None):
    return {"kind": "num", "key": key, "label": label, "ph": ph,
            **{k: v for k, v in (("min", lo), ("max", hi), ("step", step)) if v is not None}}


def toggle(key, label, default):
    return {"kind": "toggle", "key": key, "label": label, "def": default}


@dataclass
class Ctx:
    """What a fetch knows besides its element: Home Assistant's time zone, and the value the
    page's template gave (the entity's state, which some fetches build on)."""
    home_tz: str | None = None
    prev: Any = None


@dataclass(frozen=True)
class Gate:
    """A widget's part in when its page shows (review 2 #4): "something on it to show". Since 0.21.1
    (the user's call, 22 Oct) it's one part of the page's "Shows", ANDed with the page's own
    condition, never either/or (widget_part, frames.eligible_pages and check_alerts). Read by the
    render cycle, the editor (the catalog) and entities.publish_computed:

    - `rule`: what its sensor says: "active" (it's active), or "count" (above 0);
    - `sensor`: that sensor, or `sensor_of` to find it per element ("league", "series", "todo");
    - `check`: the add-on answers it from the element's own settings, so changing a league or a
      radius in the inspector takes effect at once (async (session, el, home_tz) -> bool); only
      for elements with the setting `check_if` names, when it names one ("batteries");
    - `condition`: otherwise, the condition Home Assistant answers for it (a Devices grid of states);
      without one, its sensor's `rule` (asks);
    - `markers`: sensor names a page's condition may say for it, older ones included: what the
      editor wrote for it before 0.21.1 (frames.follow_widget_parts takes those out);
    - `applies`: only for elements it says yes to;
    - `publish`: which of entities.py's publishers keeps its sensors;
    - `says`: the part in words for the editor ("a plane is near"), or {setting: {value: words},
      "else": words}, nested, as a window field's label is.
    """
    rule: str = ""
    sensor: str = ""
    sensor_of: str = ""
    check: Callable[[Any, dict, str | None], Awaitable[bool]] | None = None
    markers: tuple = ()
    applies: Callable[[dict], bool] | None = None
    publish: str = ""
    check_if: str = ""
    condition: Callable[[dict], str] | None = None
    says: Any = ""

    def describe(self) -> dict:
        return {"rule": self.rule, "sensor": self.sensor, "sensor_of": self.sensor_of,
                "markers": list(self.markers), "checked": self.check is not None, "says": self.says,
                "check_if": self.check_if, "own_condition": self.condition is not None}

    def checks(self, el: dict) -> bool:
        """Whether the add-on answers this element's part itself."""
        return self.check is not None and (not self.check_if or bool(el.get(self.check_if)))

    def sensors_for(self, el: dict) -> list[str]:
        """The sensors this element's part reads, the one it goes by first."""
        if self.sensor:
            return [self.sensor]
        if self.sensor_of == "league":
            return [f"sensor.epaper_sports_{sports.league_slug(el.get('league'))[1]}"]
        if self.sensor_of == "series":
            return [f"sensor.epaper_racing_{racing.series_slug(el.get('series') or 'f1')[0]}"]
        if self.sensor_of == "todo":
            lst = ha_services.todo_list_id(el.get("entity"))
            due = f"sensor.epaper_todo_{lst[5:]}_due" if lst else ""
            return [x for x in ((due, lst) if el.get("show") == "due" else (lst, due)) if x]
        return []

    def asks(self, el: dict) -> str:
        """The condition Home Assistant answers for this element's part when the add-on doesn't check
        it: "" when there's nothing to wait for (no list chosen, a grid of any state)."""
        if self.condition is not None:
            return self.condition(el)
        sid = (self.sensors_for(el) or [""])[0]
        if not sid:
            return ""
        return f"{{{{ is_state('{sid}','active') }}}}" if self.rule == "active" else count_condition(sid)


@dataclass
class Widget:
    type: str
    name: str
    icon: str                                   # the editor's icon for it
    fetch: Callable[[Any, dict, Ctx], Awaitable[Any]] | None
    example: Callable[[dict, datetime], Any] | None
    # What it shows that's live (planes, scores, the grid now, what's playing): the live_data readers of
    # that, whose own interval says how often it changes. Empty: it changes slowly (a calendar, a total).
    live: tuple = ()
    live_when: tuple = ()                       # live only when one of these fields is set (weather: a station)
    box: dict = field(default_factory=lambda: dict(FILL))
    defaults: dict = field(default_factory=dict)
    fields: list = field(default_factory=list)
    # (most, kind): a list value is up to `most` items of its page; `most` None: all of them, as many
    # as the panel holds (frames.fit_counts shares its room out, most important first).
    items: tuple[int | None, str] | None = None
    busiest: Callable[[dict], int] | None = None    # with no cap: the most items an element can have at once
    items_word: Callable[[dict], str] | None = None  # what its items are called: "planes", a sport's "games"
    gate: Gate | None = None                    # how its page shows "only when" (Gate)
    keeps_size: bool = False                    # its box keeps its real size on a smaller screen (arrange.KEEP_SIZE)
    breakable: bool = False                     # the editor can break it into plain elements
    # What it shows from outside, in the add-on's own fields (shapes.py): the editor shows them, and one
    # of your data sources that gives them can stand in for the add-on's services (el["data"]["source"]).
    shape: str = ""

    def changes_every(self, el: dict | None = None) -> int | None:
        """Seconds: how often what it shows changes, for the editor's "changes faster than this device
        updates" (the user's list: planes, scores, races, what's playing, the grid now, a weather
        station), from its live readers' own intervals; None for what changes slowly. With an element,
        `live_when` is checked against it."""
        if el is not None and self.live_when and not any(str(el.get(k) or "").strip() for k in self.live_when):
            return None
        got = [r.interval for r in self.live if getattr(r, "interval", None)]
        return int(min(got)) if got else None

    def describe(self) -> dict:
        """What the editor reads (/api/catalog)."""
        return {"name": self.name, "icon": self.icon, "box": self.box, "defaults": self.defaults,
                "fields": self.fields, "changes_every": self.changes_every(),
                **({"changes_when": list(self.live_when)} if self.live_when else {}),
                "sub_items": self.items is not None, "breakable": self.breakable,
                **({"gate": self.gate.describe()} if self.gate else {}),
                **({"shape": shapes.get(self.shape).describe()} if self.shape else {})}

    def gates(self, el: dict) -> Gate | None:
        """Its gate, if it applies to this element."""
        g = self.gate
        return g if g and (g.applies is None or g.applies(el)) else None


# ---------------------------------------------------------------- gates: answered from the element itself

def hours_around(el: dict, key: str) -> float:
    """A page's "Hours before" or "Hours after" (`pre_buffer_hours`, `post_buffer_hours`): the one
    reading of it, for its gate, its data and its window sensor (entities.py)."""
    try:
        return float(el.get(key)) if el.get(key) is not None else HOURS_AROUND
    except (TypeError, ValueError):
        return HOURS_AROUND


async def _match_on(session, el, home_tz):
    win = await sports.compute_sports_active_window(session, el.get("league") or "soccer/eng.1",
                                                    pre_buffer_hours=hours_around(el, "pre_buffer_hours"),
                                                    post_buffer_hours=hours_around(el, "post_buffer_hours"),
                                                    tz_name=el.get("timezone") or home_tz, team=el.get("team"),
                                                    own=shapes.own_source(el))
    return bool((win or {}).get("is_active"))               # None: not fetched yet


async def _race_on(session, el, home_tz):
    win = await racing.compute_racing_active_window(session, el.get("series") or "f1",
                                                    pre_buffer_hours=hours_around(el, "pre_buffer_hours"),
                                                    post_buffer_hours=hours_around(el, "post_buffer_hours"),
                                                    window_mode=el.get("window_mode") or "session",
                                                    tz_name=el.get("timezone") or home_tz, own=shapes.own_source(el))
    return bool((win or {}).get("is_active"))


async def _planes_near(session, el, home_tz):
    lat, lon, radius, _ = flights.place_of(el)
    return len(await flights.fetch_overhead_aircraft(session, radius_km=radius, lat=lat, lon=lon,
                                                     own=shapes.own_source(el)) or []) > 0


def _is_batteries(el: dict) -> bool:
    return bool(el.get("batteries"))


_BATTERIES_SAY = {"filter_rule": {"at_least": "one of its batteries is charged"}, "else": "one of its batteries is low"}


def count_condition(sid: str) -> str:
    """A count above 0, guarded so a sensor with no value isn't 0 (the editor's legacy.countShowIf)."""
    return f"{{{{ has_value('{sid}') and states('{sid}') | float(0) > 0 }}}}"


def _js_number(t: float) -> str:
    return str(int(t)) if float(t).is_integer() else repr(float(t))


def grid_condition(el: dict) -> str:
    """A Devices grid's part: any item in its state, or past its number (its own `threshold`, or the
    grid's). The editor's conditions.gridShowIf, which wrote it into the page before 0.21.1. "" when
    it shows something whatever happens (any state), or watches nothing."""
    items = [str(x.get("entity") or "").strip() for x in el.get("items") or [] if isinstance(x, dict)]
    own = {str(x.get("entity") or "").strip(): x.get("threshold") for x in el.get("items") or [] if isinstance(x, dict)}
    items = [e for e in items if e]
    if not items:
        return ""
    rule = el.get("filter_rule")
    if rule in ("below", "at_least"):
        sym = "<" if rule == "below" else ">="
        parts = []
        for e in items:
            raw = own.get(e)
            try:
                t = float(raw if raw not in (None, "") else el.get("filter_value"))
            except (TypeError, ValueError):
                continue
            e = e.replace("'", "")
            parts.append(f"(has_value('{e}') and states('{e}') | float(0) {sym} {_js_number(t)})")
        return "{{ " + " or ".join(parts) + " }}" if parts else ""
    st = str(el.get("filter_state") or "on").lower()
    if st == "*":
        return ""
    return "{{ " + " or ".join(f"is_state('{e}','{st}')" for e in items) + " }}"


async def _batteries_past(session, el, home_tz):
    """A Batteries page shows while one of the batteries its rule picks is past its number, or hasn't
    answered for its wait (sources/batteries.needs_you)."""
    import time
    every = await batteries.fetch_every(session)
    return batteries.needs_you(el, batteries.chosen(el, every or []), time.time())


# ---------------------------------------------------------------- fetches

async def _batteries_list(session, el, ctx):
    """A Devices grid of batteries by rule: the batteries it picks, now (sources/batteries.chosen).
    A grid of its own entities is answered by its template (render/layout.collect_templates)."""
    if not _is_batteries(el):
        return None
    every = await batteries.fetch_every(session)
    if every is None:
        return None
    return _in_zone(batteries.shown(el, batteries.chosen(el, every), _time.time()), getattr(ctx, "home_tz", None))


def _in_zone(rows: list[dict], tz: str | None) -> list[dict]:
    """A silent battery's since-when in Home Assistant's time zone, so the panel says it as you'd read it."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    out = []
    for r in rows:
        if r.get("no_answer"):
            try:
                at = datetime.fromisoformat(str(r["no_answer"]).replace("Z", "+00:00"))
                r = {**r, "no_answer": (at.astimezone(ZoneInfo(tz)) if tz else at.astimezone()).isoformat()}
            except (TypeError, ValueError, KeyError):
                pass
        out.append(r)
    return out


def _batteries_example(el, now):
    """Batteries by rule: the offline examples it picks; a grid of states: the fixture answers (None)."""
    if not _is_batteries(el):
        return None
    return _in_zone(batteries.shown(el, batteries.chosen(el, batteries.offline()), now.timestamp()), None)

def _num(value, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


async def _weather(session, el, ctx):
    ent = str(el.get("entity") or "").strip() or await ha_services.default_weather(session)
    if not ent:
        return None
    got = await ha_services.fetch_weather_forecast(session, ent, fallback=ctx.prev)
    value = got or ctx.prev
    wanted = station.wanted(el)
    if wanted:                                  # "now" from your own station, over the forecast
        now_data = await station.fetch_station(session, **wanted)
        merged = station.merge(layout._parse_val_json(value) if value else None, now_data)
        if isinstance(merged, dict):
            value = merged
    return value or None


async def _calendar(session, el, ctx):
    ent = el.get("entity")
    return (await ha_services.fetch_calendar_events(session, ent, days=31, fallback=ctx.prev) or None) if ent else None


async def _todo(session, el, ctx):
    eid = ha_services.todo_list_id(el.get("entity"))
    got = await ha_services.fetch_todo_items(session, eid) if eid else None
    return {**got, "tz": ctx.home_tz} if got else None          # "Today" is Home Assistant's today


async def _sun(session, el, ctx):
    got = await home.fetch_sun(session)
    return None if got is None else {**got, "tz": ctx.home_tz}


async def _countdown(session, el, ctx):
    return {"tz": ctx.home_tz}                  # it counts from the element itself (render/countdown.py)


async def _world_clock(session, el, ctx):
    return {"tz": ctx.home_tz}                  # its cities' times are drawn from the clock (render/worldclock.py)


async def _energy_total(session, el, ctx):
    return await energy.fetch_total(session, str(el.get("source") or "solar"), str(el.get("entity") or ""),
                                    str(el.get("period") or "month"))


async def _grid(session, el, ctx):
    ent, inv = str(el.get("entity") or ""), bool(el.get("invert"))
    power = await energy.fetch_grid_power(session, ent, inv)
    hours = await energy.fetch_grid_hours(session, ent, inv)
    if power is None and hours is None:
        return None
    return {"watts": None, "bars": [], "today": None, **(hours or {}), **(power or {})}


async def _cost(session, el, ctx):
    return await energy.fetch_cost(session)


async def _now_playing(session, el, ctx):
    return await home.fetch_now_playing(session, tuple(home.players(el.get("entity"))))


async def _tv(session, el, ctx):
    if not str(el.get("entity") or "").strip():
        return None
    events = await home.episodes(session, str(el["entity"]), days=_num(el.get("days"), 7))
    return None if events is None else {"events": events, "tz": ctx.home_tz}


async def _notifications(session, el, ctx):
    got = await needs_you.fetch_notifications(session)
    return None if got is None else {"items": got, "tz": ctx.home_tz}


async def _updates(session, el, ctx):
    got = await needs_you.fetch_updates(session)
    return None if got is None else {"items": got}


async def _badge(session, el, ctx):
    counts = needs_you.badge_counts(el)
    return (await needs_you.counts(session, (counts,))).get(counts)


async def _flights(session, el, ctx):
    lat, lon, radius, _ = flights.place_of(el)
    return await flights.fetch_overhead_aircraft(session, radius_km=radius, lat=lat, lon=lon, own=shapes.own_source(el))


async def _racing(session, el, ctx):
    # Its "Hours after" is its gate's (_race_on): a session's result shows as long as the page does.
    got = await racing.fetch_racing_data(session, el.get("entity") or el.get("series") or "f1", fallback=ctx.prev,
                                         tz_name=el.get("timezone") or ctx.home_tz, own=shapes.own_source(el),
                                         post_buffer_hours=hours_around(el, "post_buffer_hours"))
    return got or None


async def _match(session, el, ctx):
    got = await sports.fetch_sports_match(session, el.get("entity") or el.get("league") or "soccer/eng.1",
                                          team=el.get("team"), fallback=ctx.prev, tz_name=el.get("timezone") or ctx.home_tz,
                                          own=shapes.own_source(el))
    return got or None


# ---------------------------------------------------------------- the widgets, in the order the editor offers them

STATION_FIELDS = [
    # "Now" from your own station, each part optional (sources/station.py); the forecast keeps the days.
    entity("now_entity", "Now from", ["weather"]),
    entity("temperature_sensor", "Temperature sensor", ["sensor"]),
    entity("humidity_sensor", "Humidity sensor", ["sensor"]),
    entity("wind_sensor", "Wind sensor", ["sensor"]),
    entity("rain_sensor", "Rain sensor", ["sensor", "binary_sensor"],
           accepts={"unit_ends": ["/h", "/hr"], "domains": ["binary_sensor"], "reason": station.RAIN_TOTAL}),
    entity("pressure_sensor", "Pressure sensor", ["sensor"]),
    # Opt-in: only a chosen sunlight sensor turns the sky guess on (a station in the shade reads cloudy in full sun).
    entity("solar_sensor", "Guess the sky from sunlight", ["sensor"]),
]

WIDGETS: dict[str, Widget] = {w.type: w for w in (
    Widget("weather_forecast", "Weather", "cloud", _weather,
           lambda el, now: layout._parse_val_json(examples.eval_fixture_template(
               layout.collect_templates({"elements": [{**el, "entity": el.get("entity") or "weather.forecast_home"}]})[0], own=False)),
           live=(station.fetch_station,), live_when=("now_entity",) + station.SENSORS,
           defaults={"entity": "", "show_border": True}, breakable=True,
           fields=[entity("entity", "Weather", ["weather"], ph="The first one Home Assistant has"),
                   sel("layout_mode", "Layout", [["auto", "Fit the box"], ["split", "Now and forecast side by side"],
                                                 ["stacked", "Now above the forecast"], ["hero_only", "Now only, very large"],
                                                 ["forecast_only", "Forecast only"]], "auto"),
                   sel("forecast_days", "Days", [["3", "3"], ["4", "4"], ["5", "5"]], "4"),
                   toggle("show_details", "Humidity and wind", True), BORDER, *STATION_FIELDS]),
    Widget("sun_times", "Sunrise and sunset", "sun", _sun, lambda el, now: {**examples.sun(now), "tz": None},
           defaults={"style": "next"},
           fields=[sel("style", "Style", [["next", "Next one first"], ["both", "Both alike"]], "next")]),
    # A date of yours or your bins, no calendar needed; nothing fetched, so it changes only as the day does.
    Widget("countdown", "Countdown", "calendar", _countdown, lambda el, now: {"tz": None},
           defaults={"to": "date", "name": "", "at": "", "yearly": False, "show_before": 0},
           fields=[sel("to", "Counts down to", [["date", "A date"], ["bins", "Bin day"]], "date"), {"kind": "countdown"}]),
    # Up to four cities, alike, fitted to the box; "" is Home Assistant's own zone. A sleeping device shows hours apart.
    Widget("world_clock", "World clock", "clock", _world_clock, lambda el, now: {"tz": None},
           defaults={"zones": [{"tz": "", "label": ""}]},
           fields=[{"kind": "zones", "key": "zones", "most": 4, "label": "Cities"}]),
    Widget("energy_total", "Energy total", "chart", _energy_total,
           lambda el, now: examples.total(str(el.get("period") or "month"), now),
           defaults={"source": "solar", "entity": "", "period": "month"},
           fields=[sel("source", "Shows", [["solar", "Solar, from the Energy dashboard"], ["grid_import", "Bought from the grid"],
                                           ["grid_export", "Sold to the grid"], ["entity", "A sensor"]], "solar"),
                   entity("entity", "Sensor", when={"key": "source", "is": "entity"}),
                   sel("period", "For", [["day", "Today"], ["month", "This month"], ["year", "This year"]], "month")]),
    Widget("grid_now", "Grid now", "plug", _grid, lambda el, now: examples.grid(now),
           live=(energy.fetch_grid_power,), defaults={"entity": "", "invert": False},
           fields=[entity("entity", "Power sensor, if not the dashboard's"), toggle("invert", "Above zero when selling", False)]),
    Widget("energy_cost", "Energy cost", "value", _cost, lambda el, now: dict(examples.COST)),
    Widget("now_playing", "Now playing", "play", _now_playing, lambda el, now: list(examples.PLAYING),
           live=(home.fetch_now_playing,), defaults={"entity": ""}, items=(5, "media"), items_word=lambda el: "players",
           fields=[text("entity", "Players", "All of them")]),
    Widget("tv_week", "On TV this week", "calendar", _tv, lambda el, now: {"events": examples.episodes(now), "tz": None},
           defaults={"entity": "", "days": 7},
           fields=[entity("entity", "Calendar of shows", ["calendar"]), num("days", "Days ahead", "7", 1, 31),
                   text("title", "Title", "On TV this week")]),
    Widget("calendar_month", "Month", "calendar", _calendar,
           lambda el, now: examples.eval_fixture_template(layout.collect_templates({"elements": [el]}).get(0, ""), own=False) or None,
           box={"x": 20, "y": 14, "w": 360, "h": 230},
           defaults={"show_header": True, "show_weekdays": True, "first_weekday": 0, "highlight_today": True,
                     "show_border": True, "entity": ""},
           fields=[entity("entity", "Calendar", ["calendar"]), sel("first_weekday", "Week starts", [["0", "Monday"], ["6", "Sunday"]], "0"),
                   toggle("show_header", "Month name", True), toggle("show_weekdays", "Weekday names", True),
                   toggle("highlight_today", "Mark today", True), BORDER]),
    Widget("calendar_agenda", "Agenda", "list", _calendar,
           lambda el, now: examples.eval_fixture_template(layout.collect_templates({"elements": [el]}).get(0, ""), own=False) or None,
           breakable=True,
           box={"x": "margin", "y": 14, "w": 380, "h": 230},
           defaults={"title": "Coming up", "max_events": 4, "show_border": True, "entity": ""},
           fields=[entity("entity", "Calendar", ["calendar"]), text("title", "Title", "Coming up"),
                   sel("max_events", "Events", [["2", "2, extra large"], ["3", "3, large"], ["4", "4"], ["5", "5"], ["6", "6"]], "4"),
                   toggle("show_sub", "Times and places", True), BORDER]),
    Widget("todo_list", "To-do list", "todo", _todo,
           lambda el, now: (lambda got: {**got, "tz": None} if got else None)(
               examples.fixture_todo(str(el.get("entity") or "todo.chores")) or examples.fixture_todo("todo.chores")),
           defaults={"entity": ""}, gate=Gate("count", sensor_of="todo", markers=("todo.", "sensor.epaper_todo_"),
                     says={"show": {"due": "something on its list is due"}, "else": "its list has something to do"}),
           fields=[entity("entity", "List", ["todo"]),
                   sel("show", "Shows", [["open", "Everything to do"], ["due", "Due today or overdue"]], "open"),
                   # render/todo.STYLES but "plain" (kept as the way back, not offered).
                   sel("style", "Style", [["urgency", "By urgency"], ["due", "Inverted when due"], ["outlined", "Outlined"]], "urgency"),
                   text("title", "Title", "The list's name"),
                   {"kind": "window", "label": {"show": {"due": "Only show when something's due"},
                                                "else": "Only show when there's something to do"}},
                   {"kind": "sensorid", "note": "The add-on counts what's due today or overdue as {sensor}. "
                                                "An alert can show by it, or your own automations.",
                    "none": "sensor.epaper_todo_…_due"}]),
    # Home Assistant's notifications (the bell), newest first; dismissing one there clears it at the next update.
    Widget("notifications", "Notifications", "bell", _notifications,
           lambda el, now: {"items": examples.notifications(now), "tz": None},
           defaults={"title": ""},
           gate=Gate("count", sensor=needs_you.SENSOR["notifications"], markers=(needs_you.SENSOR["notifications"],),
                     says="there are notifications"),
           fields=[text("title", "Title", "Notifications"),
                   {"kind": "window", "label": "Only show while there are any"},
                   {"kind": "sensorid", "note": "The add-on counts them as {sensor}, its own value: a page's "
                                                "\"Only when\" or an alert can show by it."}]),
    # Every update waiting, by group as Home Assistant shows them; a skipped version isn't one.
    Widget("updates", "Updates", "update", _updates, lambda el, now: {"items": examples.updates()},
           defaults={"title": ""},
           gate=Gate("count", sensor=needs_you.SENSOR["updates"], markers=(needs_you.SENSOR["updates"],),
                     says="there are updates"),
           fields=[text("title", "Title", "Updates"),
                   {"kind": "window", "label": "Only show while there are any"},
                   {"kind": "sensorid", "note": "The add-on counts them as {sensor}, its own value: a page's "
                                                "\"Only when\" or an alert can show by it."}]),
    # A number on an icon, as on an app's icon, for a corner of any page; nothing at all at zero.
    Widget("badge", "Badge", "badge", _badge, lambda el, now: examples.badge(needs_you.badge_counts(el)),
           box={"x": 672, "y": 14, "w": 96, "h": 96}, defaults={"counts": "updates"}, keeps_size=True,
           fields=[sel("counts", "Counts", [["updates", "Updates"], ["notifications", "Notifications"],
                                            ["repairs", "Repairs"], ["all", "All of these"]], "updates"),
                   {"kind": "note", "text": "It's hidden while the count is zero, so it may not show on the canvas right now."}]),
    Widget("dynamic_grid", "Devices", "grid", _batteries_list, _batteries_example,
           # Something to show: one of its items in its state or past its number; Batteries by rule
           # (review 2 #5) asks the add-on, which knows every battery the rule picks, and which are silent.
           gate=Gate(check=_batteries_past, check_if="batteries", condition=grid_condition,
                     says={"batteries": {"swap": _BATTERIES_SAY, "charge": _BATTERIES_SAY},
                           "else": {"filter_rule": {"below": "one of them is below its number",
                                                    "at_least": "one of them has reached its number"},
                                    "else": {"filter_state": {"off": "one of them is off"}, "else": "one of them is on"}}}),
           box={"fill": True, "y": 16, "inset": 24},
           defaults={"header_icon": "mdi:lightning-bolt", "header_title": "On now", "filter_state": "on", "layout_mode": "grid",
                     "show_labels": "both", "icon_size": "auto", "secondary_mode": "runtime",
                     "items": [{"entity": "", "name": "Spot 1", "icon": "mdi:radiator"}, {"entity": "", "name": "Spot 2", "icon": "mdi:radiator"}]},
           fields=[{"kind": "grid"}]),
    Widget("flight_tracker", "Flights", "plane", _flights, lambda el, now: list(examples.AIRCRAFT),
           live=(flights.fetch_overhead_aircraft,), items=(5, "flight"), items_word=lambda el: "planes",
           breakable=True, shape="flights",
           gate=Gate("count", sensor="sensor.epaper_flights_overhead", check=_planes_near, publish="flights", says="a plane is near",
                     markers=("sensor.epaper_flights_overhead", "sensor.overhead_aircraft_count")),
           defaults={"radius": 35, "style": "card", "show_border": True},
           fields=[sel("style", "Style", [["card", "Details"], ["split", "Radar and details"], ["radar", "Radar"]], "card"),
                   {"kind": "place"}, num("radius", "Radius, km", "35", 5, 250),
                   {"kind": "window", "label": "Only show while a plane is near"},
                   toggle("show_sub_metrics", "Second units", True), BORDER, {"kind": "data"}, {"kind": "sensorid"}]),
    Widget("sports_racing", "Racing", "flag", _racing, lambda el, now: examples.race(el.get("series") or "f1"),
           live=(racing.fetch_racing_data,), breakable=True, shape="racing",
           # sensor.f1_status and sensor.formula_e_status: what 0.9 pages say.
           gate=Gate("active", sensor_of="series", check=_race_on, publish="racing",
                     says={"window_mode": {"weekend": "it's a race weekend"}, "else": "it's around a session"},
                     markers=("sensor.epaper_racing_", "sensor.f1_status", "sensor.formula_e_status")),
           defaults={"series": "f1", "entity": "", "show_border": True},
           fields=[sel("series", "Series", "series", "f1"), entity("entity", "Sensor, if you have one"),
                   sel("max_drivers", "Leaderboard", [["6", "Top 6, extra large"], ["8", "Top 8, large"], ["10", "Top 10"]], "10"),
                   {"kind": "window", "label": "Only show around sessions"},
                   sel("window_mode", "Around", [["session", "Each session"], ["weekend", "The whole weekend"]], "session"),
                   num("pre_buffer_hours", "Hours before", AROUND, 0, 24, 0.5), num("post_buffer_hours", "Hours after", AROUND, 0, 24, 0.5),
                   toggle("show_teams", "Team names", True), text("timezone", "Time zone", "Home Assistant's"), BORDER,
                   {"kind": "data"}, {"kind": "sensorid"}]),
    Widget("sports_match", "Scores", "ball", _match,
           lambda el, now: examples.match(el.get("league") or el.get("entity") or "soccer/eng.1"),
           # Every game of the day (the user's call, 21 Oct); the way back is items=(6, "sports").
           live=(sports.fetch_sports_match,), items=(None, "sports"), breakable=True, shape="scores",
           gate=Gate("active", sensor_of="league", check=_match_on, publish="sports", says="it's a {event} day",
                     markers=("sensor.epaper_sports_", "sensor.sports_")),
           # A Team Tracker sensor is one game; a league, its busiest day.
           busiest=lambda el: 1 if str(el.get("entity") or "").strip() else sports.busiest_day(el.get("league")),
           items_word=lambda el: sport.words(sports.path_of(el.get("league"))).events,
           defaults={"league": "soccer/eng.1", "team": "", "entity": "", "show_border": True},
           fields=[sel("league", "League", "leagues", "soccer/eng.1"), text("team", "Team", "Any team"),
                   entity("entity", "Team Tracker sensor"),
                   # {event}: the league's sport's word for one (render/sport.py): "match", "game".
                   {"kind": "window", "label": "Only show on {event} days"},
                   num("pre_buffer_hours", "Hours before", AROUND, 0, 24, 0.5), num("post_buffer_hours", "Hours after", AROUND, 0, 24, 0.5),
                   text("timezone", "Time zone", "Home Assistant's"), toggle("show_stats", "Team stats", True),
                   toggle("show_scorers", "Scorers", True), BORDER, {"kind": "data"}, {"kind": "sensorid"}]),
)}

# Render-side facts come from here: which types take their fetched value, and which make items of a page.
subitems.WIDGET_ITEMS.update({t: w.items for t, w in WIDGETS.items() if w.items})
subitems.WIDGET_BUSIEST.update({t: w.busiest for t, w in WIDGETS.items() if w.busiest})
subitems.WIDGET_WORDS.update({t: w.items_word for t, w in WIDGETS.items() if w.items_word})
arrange.KEEP_SIZE.update(t for t, w in WIDGETS.items() if w.keeps_size)


# A plain sensor whose value changes all the time (power, wind...), as Home Assistant describes it.
FAST_CLASSES = {"power", "apparent_power", "reactive_power", "current", "voltage", "power_factor", "frequency",
                "wind_speed", "speed", "irradiance", "data_rate", "sound_pressure"}


def sensor_changes_every(attributes: dict) -> int | None:
    """Seconds: how often a plain sensor's value changes, for the editor's "faster than this device" note:
    a measurement that's always moving (state_class measurement, a power-like device class) changes every
    minute; anything else, None (only as often as Home Assistant says it does)."""
    a = attributes or {}
    if a.get("state_class") == "measurement" and a.get("device_class") in FAST_CLASSES:
        return 60
    return None


def widget_part(page: dict) -> list[tuple[dict, Gate]]:
    """The page's widget part, "something on it to show": each element with a gate and something to
    wait for, unless the page switched it off (`by_widget: false`). It holds while any of them has
    something (frames). Since 0.21.1 it's ANDed with the page's own condition (the user's call,
    22 Oct): before, one or the other decided, and the other was silently left out."""
    if page.get("by_widget") is False:
        return []
    out = []
    for el in page.get("elements") or []:
        w = get(el.get("type")) if isinstance(el, dict) else None
        g = w.gates(el) if w else None
        if g is not None and (g.checks(el) or g.asks(el)):
            out.append((el, g))
    return out



# What the editor wrote into a page for its widget before 0.21.1 (legacy.gateShowIf, older forms, and
# conditions.gridShowIf): now its widget part, so not the page's own condition.
_SENSOR_FORMS = [re.compile(r"^" + f + r"$") for f in (
    r"is_state\(\s*'(?P<s>[^']+)'\s*,\s*'active'\s*\)",
    r"has_value\(\s*'(?P<s>[^']+)'\s*\)\s+and\s+states\(\s*'(?P=s)'\s*\)\s*\|\s*float\(0\)\s*>\s*0",
    r"states\(\s*'(?P<s>[^']+)'\s*\)\s*\|\s*(?:int|float)(?:\(\s*0?\s*\))?\s*>\s*0")]
_GRID_PART = re.compile(r"^(?:is_state\('([^']+)','[^']*'\)"
                        r"|\(has_value\('([^']+)'\) and states\('\2'\) \| float\(0\) (?:<|>=) -?\d+(?:\.\d+)?\))$")


def wrote_for_widget(page: dict) -> bool:
    """Whether the page's own condition is only what the editor wrote for its widget part: its sensor
    active or above 0 (the element's own sensor, or an older name for it), or a grid's own parts joined
    by "or" (at least one on its items). A condition that says anything else is yours."""
    s = page.get("show_if")
    if not isinstance(s, str) or not s.strip().startswith("{{") or not s.strip().endswith("}}"):
        return False
    inner = s.strip()[2:-2].strip()
    parts = widget_part(page)
    own, prefixes, grids = set(), set(), []
    for el, g in parts:
        own |= set(g.sensors_for(el)) | {m for m in g.markers if not m.endswith(("_", "."))}
        prefixes |= {g.sensor} if g.sensor else set()
        if el.get("type") == "dynamic_grid":
            grids.append(el)
    for form in _SENSOR_FORMS:
        m = form.match(inner)
        if m and (m["s"] in own or any(m["s"].startswith(p) for p in prefixes)):
            return True
    if grids:
        mine = {str(x.get("entity") or "").strip() for el in grids for x in el.get("items") or [] if isinstance(x, dict)}
        got = [_GRID_PART.match(p.strip()) for p in re.split(r"\s+or\s+(?=is_state|\(has_value)", inner)]
        if all(got) and (any((m[1] or m[2]) in mine for m in got)
                         or any(el.get("batteries") for el in grids) and all(m[2] for m in got)):
            return True
    return False


def follow_widget_parts(pages: dict, _=None) -> list[str]:
    """Pages from before 0.21.1: a condition the editor wrote for its widget goes, since the widget's
    part (on unless switched off) says the same; your own stays, and both hold from now on. Once:
    after it, nothing's left to take out. Returns the pages changed."""
    changed = []
    for name, page in (pages or {}).items():
        if isinstance(page, dict) and page.get("tier") in ("when", "alert") and wrote_for_widget(page):
            page.pop("show_if", None)
            changed.append(name)
    return changed


def get(widget_type) -> Widget | None:
    return WIDGETS.get(str(widget_type or ""))


async def fetch(session, el: dict, ctx: Ctx):
    """An element's value from its widget's fetch, or None (not a widget, nothing yet)."""
    w = get(el.get("type"))
    return await w.fetch(session, el, ctx) if w and w.fetch else None


def example(el: dict, now: datetime):
    w = get(el.get("type"))
    return w.example(el, now) if w and w.example else None


def catalog() -> dict:
    return {t: w.describe() for t, w in WIDGETS.items()}
