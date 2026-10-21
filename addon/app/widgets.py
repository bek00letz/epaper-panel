"""One descriptor per widget: everything about a kind of widget, in one place.

A widget is an element that draws itself from a value the render cycle
fetches (weather, a calendar, scores, sunrise...). Before 0.15 a new one was
named in about ten places in two languages, and forgetting one failed
quietly. Here each widget says, once:

- what it's called and its icon, its default box and settings, and its
  inspector fields (served to the editor, /api/catalog);
- how its value is fetched (always through live_data, so a render never
  waits) and how often that value changes (from its fetchers' own
  @runtime.live intervals);
- its example value, for thumbnails (examples.py);
- how it's drawn (render/), and whether a list value is several items of
  its page (1 of 3), like planes overhead.

frames.enrich_page_values, examples.page_values, render.layout's dispatch
and render.subitems all read it. Basics (text, value, icon, card, line,
charts, QR) are the editor's own and aren't here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable

import examples
from render import layout, subitems
from sources import energy, flights, ha_services, home, racing, sports, station

# A default box: "fill" takes the content area less `inset` (from `y`); otherwise each size is clamped to it.
FILL = {"fill": True, "y": 14, "inset": 20}
BORDER = {"kind": "toggle", "key": "show_border", "label": "Border", "def": True}


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


@dataclass
class Widget:
    type: str
    name: str
    icon: str                                   # the editor's icon for it
    fetch: Callable[[Any, dict, Ctx], Awaitable[Any]] | None
    example: Callable[[dict, datetime], Any] | None
    readers: tuple = ()                         # its live_data readers: how often its value changes
    box: dict = field(default_factory=lambda: dict(FILL))
    defaults: dict = field(default_factory=dict)
    fields: list = field(default_factory=list)
    items: tuple[int, str] | None = None        # (most, kind): a list value is up to `most` items of its page
    window: bool = False                        # its page can show only around its events (a sensor of ours)
    breakable: bool = False                     # the editor can break it into plain elements

    def changes_every(self) -> int | None:
        """Seconds: how often its value can change, from its fetchers' own intervals; None when it
        changes only as Home Assistant's states do (a template)."""
        got = [r.interval for r in self.readers if getattr(r, "interval", None)]
        return int(min(got)) if got else None

    def describe(self) -> dict:
        """What the editor reads (/api/catalog)."""
        return {"name": self.name, "icon": self.icon, "box": self.box, "defaults": self.defaults,
                "fields": self.fields, "changes_every": self.changes_every(),
                "sub_items": self.items is not None, "window": self.window, "breakable": self.breakable}


# ---------------------------------------------------------------- fetches

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


async def _flights(session, el, ctx):
    lat, lon, radius, _ = flights.place_of(el)
    return await flights.fetch_overhead_aircraft(session, radius_km=radius, lat=lat, lon=lon)


async def _racing(session, el, ctx):
    got = await racing.fetch_racing_data(session, el.get("entity") or el.get("series") or "f1", fallback=ctx.prev,
                                         tz_name=el.get("timezone") or ctx.home_tz)
    return got or None


async def _match(session, el, ctx):
    got = await sports.fetch_sports_match(session, el.get("entity") or el.get("league") or "soccer/eng.1",
                                          team=el.get("team"), fallback=ctx.prev, tz_name=el.get("timezone") or ctx.home_tz)
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
           readers=(ha_services.fetch_weather_forecast, station.fetch_station),
           defaults={"entity": "", "show_border": True}, breakable=True,
           fields=[entity("entity", "Weather", ["weather"], ph="The first one Home Assistant has"),
                   sel("layout_mode", "Layout", [["auto", "Fit the box"], ["split", "Now and forecast side by side"],
                                                 ["stacked", "Now above the forecast"], ["hero_only", "Now only, very large"],
                                                 ["forecast_only", "Forecast only"]], "auto"),
                   sel("forecast_days", "Days", [["3", "3"], ["4", "4"], ["5", "5"]], "4"),
                   toggle("show_details", "Humidity and wind", True), BORDER, *STATION_FIELDS]),
    Widget("sun_times", "Sunrise and sunset", "sun", _sun, lambda el, now: {**examples.sun(now), "tz": None},
           readers=(home.fetch_sun,), defaults={"style": "next"},
           fields=[sel("style", "Style", [["next", "Next one first"], ["both", "Both alike"]], "next")]),
    Widget("energy_total", "Energy total", "chart", _energy_total,
           lambda el, now: examples.total(str(el.get("period") or "month"), now),
           readers=(energy.fetch_total,), defaults={"source": "solar", "entity": "", "period": "month"},
           fields=[sel("source", "Shows", [["solar", "Solar, from the Energy dashboard"], ["grid_import", "Bought from the grid"],
                                           ["grid_export", "Sold to the grid"], ["entity", "A sensor"]], "solar"),
                   entity("entity", "Sensor", when={"key": "source", "is": "entity"}),
                   sel("period", "For", [["day", "Today"], ["month", "This month"], ["year", "This year"]], "month")]),
    Widget("grid_now", "Grid now", "plug", _grid, lambda el, now: examples.grid(now),
           readers=(energy.fetch_grid_power, energy.fetch_grid_hours), defaults={"entity": "", "invert": False},
           fields=[entity("entity", "Power sensor, if not the dashboard's"), toggle("invert", "Above zero when selling", False)]),
    Widget("energy_cost", "Energy cost", "value", _cost, lambda el, now: dict(examples.COST), readers=(energy.fetch_cost,)),
    Widget("now_playing", "Now playing", "play", _now_playing, lambda el, now: list(examples.PLAYING),
           readers=(home.fetch_now_playing,), defaults={"entity": ""}, items=(5, "media"),
           fields=[text("entity", "Players", "All of them")]),
    Widget("tv_week", "On TV this week", "calendar", _tv, lambda el, now: {"events": examples.episodes(now), "tz": None},
           readers=(ha_services.fetch_calendar_events,), defaults={"entity": "", "days": 7},
           fields=[entity("entity", "Calendar of shows", ["calendar"]), num("days", "Days ahead", "7", 1, 31),
                   text("title", "Title", "On TV this week")]),
    Widget("calendar_month", "Month", "calendar", _calendar,
           lambda el, now: examples.eval_fixture_template(layout.collect_templates({"elements": [el]}).get(0, ""), own=False) or None,
           readers=(ha_services.fetch_calendar_events,),
           box={"x": 20, "y": 14, "w": 360, "h": 230},
           defaults={"show_header": True, "show_weekdays": True, "first_weekday": 0, "highlight_today": True,
                     "show_border": True, "entity": ""},
           fields=[entity("entity", "Calendar", ["calendar"]), sel("first_weekday", "Week starts", [["0", "Monday"], ["6", "Sunday"]], "0"),
                   toggle("show_header", "Month name", True), toggle("show_weekdays", "Weekday names", True),
                   toggle("highlight_today", "Mark today", True), BORDER]),
    Widget("calendar_agenda", "Agenda", "list", _calendar,
           lambda el, now: examples.eval_fixture_template(layout.collect_templates({"elements": [el]}).get(0, ""), own=False) or None,
           readers=(ha_services.fetch_calendar_events,), breakable=True,
           box={"x": "margin", "y": 14, "w": 380, "h": 230},
           defaults={"title": "Coming up", "max_events": 4, "show_border": True, "entity": ""},
           fields=[entity("entity", "Calendar", ["calendar"]), text("title", "Title", "Coming up"),
                   sel("max_events", "Events", [["2", "2, extra large"], ["3", "3, large"], ["4", "4"], ["5", "5"], ["6", "6"]], "4"),
                   toggle("show_sub", "Times and places", True), BORDER]),
    Widget("todo_list", "To-do list", "todo", _todo,
           lambda el, now: (lambda got: {**got, "tz": None} if got else None)(
               examples.fixture_todo(str(el.get("entity") or "todo.chores")) or examples.fixture_todo("todo.chores")),
           readers=(ha_services.fetch_todo_items,), defaults={"entity": ""}, window=True,
           fields=[entity("entity", "List", ["todo"]),
                   sel("show", "Shows", [["open", "Everything to do"], ["due", "Due today or overdue"]], "open"),
                   # render/todo.STYLES but "plain" (kept as the way back, not offered).
                   sel("style", "Style", [["urgency", "By urgency"], ["due", "Inverted when due"], ["outlined", "Outlined"]], "urgency"),
                   text("title", "Title", "The list's name"),
                   {"kind": "window", "label": {"show": {"due": "Only show when something's due"},
                                                "else": "Only show when there's something to do"}},
                   {"kind": "sensorid"}]),
    Widget("dynamic_grid", "Devices", "grid", None, None, box={"fill": True, "y": 16, "inset": 24},
           defaults={"header_icon": "mdi:lightning-bolt", "header_title": "On now", "filter_state": "on", "layout_mode": "grid",
                     "show_labels": "both", "icon_size": "auto", "secondary_mode": "runtime",
                     "items": [{"entity": "", "name": "Spot 1", "icon": "mdi:radiator"}, {"entity": "", "name": "Spot 2", "icon": "mdi:radiator"}]},
           fields=[{"kind": "grid"}]),
    Widget("flight_tracker", "Flights", "plane", _flights, lambda el, now: list(examples.AIRCRAFT),
           readers=(flights.fetch_overhead_aircraft,), items=(5, "flight"), window=True, breakable=True,
           defaults={"radius": 35, "style": "card", "show_border": True},
           fields=[sel("style", "Style", [["card", "Details"], ["split", "Radar and details"], ["radar", "Radar"]], "card"),
                   {"kind": "place"}, num("radius", "Radius, km", "35", 5, 250),
                   {"kind": "window", "label": "Only show while a plane is near"},
                   toggle("show_sub_metrics", "Second units", True), BORDER, {"kind": "sensorid"}]),
    Widget("sports_racing", "Racing", "flag", _racing, lambda el, now: examples.race(el.get("series") or "f1"),
           readers=(racing.fetch_racing_data,), window=True, breakable=True,
           defaults={"series": "f1", "entity": "", "show_border": True},
           fields=[sel("series", "Series", "series", "f1"), entity("entity", "Sensor, if you have one"),
                   sel("max_drivers", "Leaderboard", [["6", "Top 6, extra large"], ["8", "Top 8, large"], ["10", "Top 10"]], "10"),
                   {"kind": "window", "label": "Only show around sessions"},
                   sel("window_mode", "Around", [["session", "Each session"], ["weekend", "The whole weekend"]], "session"),
                   num("pre_buffer_hours", "Hours before", "2", 0, 24, 0.5), num("post_buffer_hours", "Hours after", "2", 0, 24, 0.5),
                   toggle("show_teams", "Team names", True), text("timezone", "Time zone", "Home Assistant's"), BORDER,
                   {"kind": "sensorid"}]),
    Widget("sports_match", "Scores", "ball", _match,
           lambda el, now: examples.match(el.get("league") or el.get("entity") or "soccer/eng.1"),
           readers=(sports.fetch_sports_match,), items=(6, "sports"), window=True, breakable=True,
           defaults={"league": "soccer/eng.1", "team": "", "entity": "", "show_border": True},
           fields=[sel("league", "League", "leagues", "soccer/eng.1"), text("team", "Team", "Any team"),
                   entity("entity", "Team Tracker sensor"),
                   # {event}: the league's sport's word for one (render/sport.py): "match", "game".
                   {"kind": "window", "label": "Only show on {event} days"},
                   num("pre_buffer_hours", "Hours before", "2", 0, 24, 0.5), num("post_buffer_hours", "Hours after", "2", 0, 24, 0.5),
                   text("timezone", "Time zone", "Home Assistant's"), toggle("show_stats", "Team stats", True),
                   toggle("show_scorers", "Scorers", True), BORDER, {"kind": "sensorid"}]),
)}

# Render-side facts come from here: which types take their fetched value, and which make items of a page.
subitems.WIDGET_ITEMS.update({t: w.items for t, w in WIDGETS.items() if w.items})


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
