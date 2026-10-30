"""The 0.15 widgets: what each shows, at every size a screen can have."""
import asyncio
import io
import urllib.parse
import unittest.mock
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from PIL import Image

import support  # noqa: F401

import frames
from render import arrange, layout, sun, theme as T

BASE = "792x272"
SIZES = (("crowpanel_579", 0), ("crowpanel_420", 0), ("crowpanel_290", 0), ("trmnl_og", 0), ("crowpanel_420", 90))
TZ = ZoneInfo("Europe/Bucharest")


def render(el: dict, value, disp="crowpanel_579", orient=0):
    target = arrange.canvas_key(*T.canvas_dims(orient, disp))
    page = arrange.pages_for({"pages": {"p": {"elements": [{"id": "w", **el}]}}}, BASE, target)["p"]
    return T.to_1bit(layout.render_page(page, {0: value}, clock="12:45", orientation=orient, display=disp))


def ink(img, box=None) -> int:
    """Black pixels, above the footer (or in a box)."""
    w, h = img.size
    box = box or (0, 0, w, h - T.band_height(h) - 2)
    return img.crop(box).histogram()[0]


class Sizes:
    """Mixin: a widget draws something, inside its box, at every size."""
    element: dict = {}
    value = None

    def test_draws_inside_its_box_at_every_size(self):
        for disp, orient in SIZES:
            target = arrange.canvas_key(*T.canvas_dims(orient, disp))
            el = {**self.element, **arrange.auto_box(self.element, BASE, target)}
            img = render(self.element, self.value, disp, orient)
            self.assertGreater(ink(img), 200, (disp, orient))
            x, y, w, h = el["x"], el["y"], el["w"], el["h"]
            outside = ink(img) - ink(img, (x, y, x + w + 1, y + h + 1))
            self.assertEqual(outside, 0, f"drew outside its box on {disp} {orient}")


class TestSun(Sizes, unittest.TestCase):
    element = {"type": "sun_times", "style": "next", "x": 24, "y": 14, "w": 744, "h": 208}
    value = {"rising": "2026-10-22T07:43:00+03:00", "setting": "2026-10-22T18:22:00+03:00", "tz": "Europe/Bucharest"}

    def test_the_next_one_comes_first_and_it_turns_round(self):
        data = {"rising": "2026-10-22T07:43:00+03:00", "setting": "2026-10-21T18:22:00+03:00"}
        self.assertFalse(sun.next_first(data, datetime(2026, 10, 21, 12, 0, tzinfo=TZ)))
        data = {"rising": "2026-10-22T07:43:00+03:00", "setting": "2026-10-22T18:22:00+03:00"}
        self.assertTrue(sun.next_first(data, datetime(2026, 10, 21, 20, 0, tzinfo=TZ)))

    def test_a_time_just_past_is_no_longer_next(self):
        # Home Assistant's value is a little behind: the sunrise has just happened.
        data = {"rising": "2026-10-22T07:43:00+03:00", "setting": "2026-10-22T18:22:00+03:00"}
        self.assertFalse(sun.next_first(data, datetime(2026, 10, 22, 7, 45, tzinfo=TZ)))

    def test_times_are_in_home_assistants_zone_and_far_ones_say_the_day(self):
        data = {"rising": "2026-12-20T05:41:00+00:00", "setting": "2026-10-21T15:22:00+00:00"}
        rise, set_ = sun.facts(data, datetime(2026, 10, 21, 12, 0, tzinfo=TZ))
        self.assertEqual((set_.value, set_.caption), ("18:22", "sunset"))
        self.assertEqual((rise.value, rise.caption), ("07:41", "sunrise 20 Dec"))

    def test_both_alike(self):
        img = render({**self.element, "style": "both"}, self.value)
        self.assertGreater(ink(img), 2000)

    def test_not_fetched_yet_is_blank_and_no_sun_says_what_to_do(self):
        self.assertEqual(ink(render(self.element, None)), 0)
        self.assertGreater(ink(render(self.element, {"rising": "", "setting": "", "tz": "UTC"})), 200)

    def test_the_render_cycle_fetches_it_without_waiting(self):
        page = {"elements": [self.element]}
        vals = {}
        from sources import home
        self.assertTrue(hasattr(home.fetch_sun, "direct"))
        asyncio.run(frames.enrich_page_values(None, page, vals))     # first read: nothing yet, never waits
        got = asyncio.run(home.fetch_sun.direct(None))                # offline: example times
        self.assertTrue(got["rising"] and got["setting"])


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- energy

from render import energy as energy_draw  # noqa: E402
from sources import energy  # noqa: E402

PREFS_2025 = {"energy_sources": [
    {"type": "solar", "stat_energy_from": "sensor.pv_a", "stat_rate": "sensor.pv_a_power"},
    {"type": "solar", "stat_energy_from": "sensor.pv_b"},
    {"type": "grid", "stat_energy_from": "sensor.bought", "stat_energy_to": "sensor.sold", "stat_cost": None,
     "entity_energy_price": "input_number.price", "power_config": {"stat_rate_inverted": "sensor.grid_w"}},
]}
PREFS_OLD = {"energy_sources": [
    {"type": "grid", "flow_from": [{"stat_energy_from": "sensor.bought", "stat_cost": "sensor.my_cost"}],
     "flow_to": [{"stat_energy_to": "sensor.sold"}], "stat_rate": "sensor.grid_w"},
]}
INFO = {"cost_sensors": {"sensor.bought": "sensor.bought_cost", "sensor.sold": "sensor.sold_compensation"}}


class FakeHass:
    """Home Assistant's websocket: the dashboard, and statistics a row per bar."""

    def __init__(self, prefs=PREFS_2025, rows=None):
        self.prefs, self.rows, self.asked = prefs, rows or {}, []

    async def ws(self, payload, timeout=10):
        self.asked.append(payload)
        if payload["type"] == "energy/get_prefs":
            return self.prefs
        if payload["type"] == "energy/info":
            return INFO
        if payload["type"] == "recorder/statistics_during_period":
            return {k: v for k, v in self.rows.items() if k in payload["statistic_ids"]}
        raise AssertionError(payload)


class TestEnergyDashboard(unittest.TestCase):
    def test_both_ways_home_assistant_writes_a_grid_mean_the_same(self):
        new, old = energy.summarise(PREFS_2025, INFO), energy.summarise(PREFS_OLD, INFO)
        self.assertEqual(energy.stats_for(new, "grid_import"), ["sensor.bought"])
        self.assertEqual(energy.stats_for(old, "grid_export"), ["sensor.sold"])
        self.assertEqual(energy.stats_for(new, "solar"), ["sensor.pv_a", "sensor.pv_b"])

    def test_costs_are_home_assistants_own_unless_you_gave_one(self):
        new, old = energy.summarise(PREFS_2025, INFO), energy.summarise(PREFS_OLD, INFO)
        self.assertEqual(new["grid"][0]["flows"][0]["cost"], "sensor.bought_cost")
        self.assertEqual(new["grid"][0]["flows"][0]["compensation"], "sensor.sold_compensation")
        self.assertEqual(old["grid"][0]["flows"][0]["cost"], "sensor.my_cost")
        self.assertTrue(new["has_cost"])
        self.assertFalse(energy.summarise({"energy_sources": [{"type": "grid", "stat_energy_from": "sensor.x"}]})["has_cost"])

    def test_every_way_of_reading_grid_power(self):
        def power(cfg):
            return energy._grid_power(cfg)
        self.assertEqual(power({"power_config": {"stat_rate": "a"}}), {"plus": "a", "minus": ""})
        self.assertEqual(power({"power_config": {"stat_rate_inverted": "a"}}), {"plus": "", "minus": "a"})
        self.assertEqual(power({"power_config": {"stat_rate_from": "a", "stat_rate_to": "b"}}), {"plus": "a", "minus": "b"})
        self.assertEqual(power({"stat_rate": "a"}), {"plus": "a", "minus": ""})
        self.assertIsNone(power({}))

    def test_rows_land_in_their_bar_and_bars_to_come_are_empty(self):
        now = datetime(2026, 10, 21, 13, 30, tzinfo=TZ)
        at = lambda d, h=0: datetime(2026, 10, d, h, tzinfo=TZ).timestamp() * 1000    # noqa: E731
        rows = {"a": [{"start": at(1), "change": 2.0}, {"start": at(21), "change": 1.5}],
                "b": [{"start": at(1), "change": 1.0}]}
        got = energy.buckets(rows, "month", now)
        self.assertEqual(len(got), 31)
        self.assertEqual((got[0], got[20], got[21]), (3.0, 1.5, None))
        hours = energy.buckets({"a": [{"start": datetime(2026, 10, 21, 13, tzinfo=TZ).isoformat(), "change": 0.4}]}, "day", now)
        self.assertEqual((hours[13], hours[14]), (0.4, None))


class TestEnergyFetches(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import runtime
        self.old = (energy.HA_TOKEN, runtime.HASS)
        energy.HA_TOKEN = "t"
        self.runtime = runtime
        today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        self.rows = {"sensor.pv_a": [{"start": today.timestamp() * 1000, "change": 3.0}],
                     "sensor.pv_b": [{"start": today.isoformat(), "change": 1.5}],
                     "sensor.bought_cost": [{"start": today.timestamp() * 1000, "change": 2.0}],
                     "sensor.sold_compensation": [{"start": today.timestamp() * 1000, "change": 5.5}]}
        runtime.HASS = FakeHass(rows=self.rows)

        async def no_web(session, path, **kw):
            return {"currency": "RON", "time_zone": "Europe/Bucharest"} if path == "/config" else {}
        async def fresh_dashboard(session):          # never the shared store: other tests read it too
            return await energy.fetch_dashboard.direct(session)
        self.patches = [unittest.mock.patch.object(energy, "ha_json", no_web),
                        unittest.mock.patch.object(energy, "dashboard", fresh_dashboard),
                        unittest.mock.patch.object(energy, "get_home_timezone", unittest.mock.AsyncMock(return_value="Europe/Bucharest"))]
        for p in self.patches:
            p.start()
        self.runtime.LIVE._entries.clear()

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        energy.HA_TOKEN, self.runtime.HASS = self.old
        self.runtime.LIVE._entries.clear()

    async def test_solar_adds_up_every_solar_source(self):
        got = await energy.fetch_total.direct(None, "solar", "", "month")
        self.assertEqual(got["total"], 4.5)
        asked = [p for p in self.runtime.HASS.asked if p["type"] == "recorder/statistics_during_period"][0]
        self.assertEqual((asked["period"], asked["units"]), ("day", {"energy": "kWh"}))

    async def test_no_solar_in_the_dashboard_says_so(self):
        self.runtime.HASS = FakeHass(prefs={"energy_sources": []})
        got = await energy.fetch_total.direct(None, "solar", "", "day")
        self.assertEqual(got["missing"], "solar")

    async def test_cost_is_earned_minus_spent_in_home_assistants_currency(self):
        got = await energy.fetch_cost.direct(None)
        self.assertEqual((got["today"], got["month"], got["currency"], got["sells"]), (3.5, 3.5, "RON", True))


class TestEnergyTotal(Sizes, unittest.TestCase):
    element = {"type": "energy_total", "source": "solar", "period": "month", "x": 24, "y": 14, "w": 744, "h": 208}
    value = {"total": 214.3, "bars": [8, 9, 7, 10, 3, None, None], "unit": "kWh"}

    def test_numbers_read_well(self):
        self.assertEqual([energy_draw.kwh(v) for v in (4.25, 214.3, 1830)], ["4.2 kWh", "214 kWh", "1.8 MWh"])
        self.assertEqual([energy_draw.watts(v) for v in (-640, 1830)], ["640 W", "1.8 kW"])
        self.assertEqual([energy_draw.money(4.2, c) for c in ("EUR", "USD", "CHF", "")], ["4.20 €", "$4.20", "4.20 CHF", "4.20"])

    def test_nothing_set_up_says_where_to_set_it_up(self):
        self.assertGreater(ink(render(self.element, {"total": None, "bars": [], "missing": "solar"})), 200)
        self.assertEqual(ink(render(self.element, None)), 0)


class TestGridNow(Sizes, unittest.TestCase):
    element = {"type": "grid_now", "x": 24, "y": 14, "w": 744, "h": 208}
    value = {"watts": -1830, "bars": [0.4, 0.3, -0.9, -1.8, None], "today": -2.0}

    def test_selling_bars_go_down_and_buying_bars_up(self):
        img = render(self.element, {"watts": None, "bars": [1.0, -1.0], "today": 0.0})
        w, _ = img.size
        right = img.crop((w // 2, 0, w, 220))
        top, bottom = right.crop((0, 0, right.width, 110)), right.crop((0, 120, right.width, 220))
        self.assertGreater(top.histogram()[0], 50)
        self.assertGreater(bottom.histogram()[0], 50)


class TestEnergyCost(Sizes, unittest.TestCase):
    element = {"type": "energy_cost", "x": 24, "y": 14, "w": 744, "h": 208}
    value = {"today": 4.2, "month": 38.9, "currency": "RON", "sells": True}

    def test_no_prices_says_where_to_add_them(self):
        self.assertGreater(ink(render(self.element, {"today": None, "month": None, "missing": "prices"})), 200)


import web  # noqa: E402
from test_editor_api import EditorClient  # noqa: E402


class TestEnergyForTheEditor(EditorClient):
    async def test_the_editor_learns_what_the_dashboard_has(self):
        import runtime
        runtime.LIVE._entries.clear()
        r = await self.ed.get("/api/energy")
        self.assertEqual(r.status, 200)
        got = await r.json()
        self.assertEqual(energy.stats_for(got, "solar"), ["sensor.solar_energy"])      # offline example
        self.assertTrue(got["has_cost"])
        self.assertIn("currency", got)


# ---------------------------------------------------------------- watch and listen

from render import media, subitems  # noqa: E402
from sources import racing  # noqa: E402
from sources import home  # noqa: E402

PLAYING = [{"entity": "media_player.tv", "key": "media_player.tv", "player": "Living room TV", "title": "Trojan's Horse",
            "series": "Severance", "season": 2, "episode": 5, "kind": "episode", "since": "2026-10-21T10:05:00+00:00"},
           {"entity": "media_player.kitchen", "key": "media_player.kitchen", "player": "Kitchen", "title": "Clair de lune",
            "artist": "Debussy", "kind": "music", "since": "2026-10-21T10:00:00+00:00"}]


class TestNowPlaying(Sizes, unittest.TestCase):
    element = {"type": "now_playing", "entity": "", "x": 24, "y": 14, "w": 744, "h": 208}
    value = PLAYING

    def test_says_what_and_where(self):
        self.assertEqual(media.describe(PLAYING[0])[:2], ("Trojan's Horse", "Severance · S2 E5 · Living room TV"))
        self.assertEqual(media.describe(PLAYING[1])[:2], ("Clair de lune", "Debussy · Kitchen"))
        self.assertEqual(media.describe({"app": "YouTube", "player": "Chromecast"})[:2], ("YouTube", "Chromecast"))
        self.assertEqual(media.describe({"title": "Warm up", "app": "YouTube", "player": "Chromecast"})[1], "YouTube on Chromecast")

    def test_each_playing_player_is_an_item_kept_by_its_player(self):
        page = {"elements": [self.element]}
        n, kind, keys, _, _ = subitems.inspect_category_subitems(page, {0: PLAYING})
        self.assertEqual((n, kind, keys), (2, "media", ["media_player.tv", "media_player.kitchen"]))
        one = render({**self.element, "sub_index": 1}, PLAYING)
        self.assertNotEqual(one.tobytes(), render(self.element, PLAYING).tobytes())

    def test_nothing_playing_and_not_fetched_yet(self):
        self.assertGreater(ink(render(self.element, [])), 200)
        self.assertEqual(ink(render(self.element, None)), 0)

    def test_players_to_follow(self):
        self.assertEqual(home.players("media_player.a, media_player.b,sensor.x, nope"), ["media_player.a", "media_player.b"])
        self.assertIn("expand(['media_player.a'])", home._now_playing_template(["media_player.a"]))
        self.assertIn("states.media_player", home._now_playing_template([]))


class TestTvWeek(Sizes, unittest.TestCase):
    element = {"type": "tv_week", "entity": "calendar.sonarr", "x": 24, "y": 14, "w": 744, "h": 208}
    value = {"tz": "Europe/Bucharest", "events": [
        {"summary": "Slow Horses - S06E06 - Judgement Day", "start": datetime.now(TZ).replace(hour=21).isoformat()}]}

    def test_reads_the_ways_shows_are_written(self):
        self.assertEqual(media.episode_of("Slow Horses - S06E06 - Judgement Day"), ("Slow Horses", "S6 E6", "Judgement Day"))
        self.assertEqual(media.episode_of("Brothers (2026) - S01E06 - The Dance")[:2], ("Brothers", "S1 E6"))
        self.assertEqual(media.episode_of("The Bear - 4x01 - Groundhog")[:2], ("The Bear", "S4 E1"))
        self.assertEqual(media.episode_of("Severance S02E05")[:2], ("Severance", "S2 E5"))
        self.assertEqual(media.episode_of("Dune: Part Three"), ("Dune: Part Three", "", ""))

    def test_from_today_on_in_order_with_days_in_words(self):
        now = datetime(2026, 10, 21, 13, 0, tzinfo=TZ)
        events = [{"summary": "C - S01E03", "start": "2026-10-24T20:00:00+03:00"},
                  {"summary": "Old - S01E01", "start": "2026-10-20T20:00:00+03:00"},
                  {"summary": "A - S01E01", "start": {"dateTime": "2026-10-21T21:00:00+03:00"}},
                  {"summary": "B - S01E02", "start": "2026-10-22T07:00:00+03:00"},
                  {"summary": "Far - S01E09", "start": "2026-10-30T07:00:00+03:00"}]
        got = media.upcoming(events, now)
        self.assertEqual([(r["day"], r["show"]) for r in got], [("Tonight", "A"), ("Tomorrow", "B"), ("Saturday", "C")])

    def test_no_calendar_and_nothing_this_week_say_so(self):
        self.assertGreater(ink(render({**self.element, "entity": ""}, None)), 200)
        self.assertGreater(ink(render(self.element, {"tz": "UTC", "events": []})), 200)


# ---------------------------------------------------------------- weather from your own station

from sources import ha_services, station  # noqa: E402


class TestStation(unittest.TestCase):
    def test_only_the_parts_you_chose(self):
        el = {"type": "weather_forecast", "entity": "weather.forecast_home", "now_entity": "weather.idumbr13",
              "rain_sensor": "sensor.rain_rate", "solar_sensor": "", "pressure_sensor": "not an id"}
        self.assertEqual(station.wanted(el), {"now_entity": "weather.idumbr13", "rain_sensor": "sensor.rain_rate"})

    def test_rain_falling_now(self):
        self.assertEqual(station.raining({"state": "0.0", "attributes": {"unit_of_measurement": "mm/h"}}), None)
        self.assertEqual(station.raining({"state": "1.2", "attributes": {"unit_of_measurement": "mm/h"}}), "rainy")
        self.assertEqual(station.raining({"state": "0.4", "attributes": {"unit_of_measurement": "in/h"}}), "pouring")
        self.assertEqual(station.raining({"state": "on"}, "binary_sensor.rain"), "rainy")
        self.assertEqual(station.raining({"state": "off"}, "binary_sensor.rain"), None)
        # A total after one shower would say rain all day: never.
        self.assertEqual(station.raining({"state": "3.2", "attributes": {"unit_of_measurement": "mm"}}), None)
        self.assertEqual(station.rain_problem("sensor.rain_today", "mm"), station.RAIN_TOTAL)
        self.assertEqual(station.rain_problem("sensor.rain_rate", "mm/h"), "")
        self.assertEqual(station.rain_problem("binary_sensor.raining", ""), "")
        self.assertEqual(station.raining({"state": "unavailable"}), None)

    def test_sky_from_sunlight_only_when_the_sun_is_up_enough(self):
        clear = station.clear_sky(45)
        self.assertEqual(station.sky(clear * 0.9, 45), "sunny")
        self.assertEqual(station.sky(clear * 0.5, 45), "partlycloudy")
        self.assertEqual(station.sky(clear * 0.1, 45), "cloudy")
        self.assertIsNone(station.sky(5.0, 4))           # dawn: too rough to judge
        self.assertIsNone(station.sky(None, 45))

    def test_pressure_says_where_its_heading(self):
        now = datetime(2026, 10, 21, 12, tzinfo=TZ)
        rows = lambda a, b: [{"last_changed": (now - timedelta(hours=3)).isoformat(), "state": a},   # noqa: E731
                             {"last_changed": now.isoformat(), "state": b}]
        self.assertEqual(station.trend(rows("1012.0", "1009.5"), now), "falling")
        self.assertEqual(station.trend(rows("1009.0", "1011.0"), now), "rising")
        self.assertEqual(station.trend(rows("1011.0", "1011.4"), now), "steady")
        self.assertEqual(station.trend(rows("29.90", "29.80"), now, "inHg"), "falling")
        self.assertEqual(station.trend(rows("101.3", "101.0"), now, "kPa"), "falling")    # 3 hPa, once read as 0.3
        self.assertEqual(station.trend(rows("760.0", "758.0"), now, "mmHg"), "falling")
        self.assertIsNone(station.trend(rows("1", "5"), now, "°C"))
        self.assertIsNone(station.trend(rows("1011", "1012")[1:], now))

    def test_now_goes_over_the_forecast_and_the_days_stay(self):
        fc = {"condition": "sunny", "temperature": 20.6, "humidity": 49, "forecast": [{"temperature": 22}]}
        got = station.merge(fc, {"temperature": 23, "humidity": 82, "condition": "rainy"})
        self.assertEqual((got["temperature"], got["humidity"], got["condition"]), (23, 82, "rainy"))
        self.assertEqual(got["forecast"], [{"temperature": 22}])
        self.assertIs(station.merge(fc, {}), fc)


class TestStationFetch(unittest.IsolatedAsyncioTestCase):
    STATES = {
        "weather.idumbr13": {"state": "partlycloudy", "attributes": {"temperature": 23, "temperature_unit": "°C",
                                                                    "humidity": 82, "wind_speed": 0, "wind_speed_unit": "km/h"}},
        "sensor.rain_rate": {"state": "0.0", "attributes": {"unit_of_measurement": "mm/h"}},
        "sensor.solar": {"state": "13.3", "attributes": {"unit_of_measurement": "W/m²"}},
        "sensor.outside": {"state": "21.44", "attributes": {"unit_of_measurement": "°C"}},
        "sun.sun": {"state": "above_horizon", "attributes": {"elevation": 33.4}},
    }

    async def asyncSetUp(self):
        async def fake(session, path, **kw):
            eid = urllib.parse.unquote(path.removeprefix("/states/"))
            return self.STATES.get(eid)
        self.patches = [unittest.mock.patch.object(station, "ha_json", fake),
                        unittest.mock.patch.object(station, "HA_TOKEN", "t")]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()

    async def test_the_stations_own_weather_and_a_sensor_over_it(self):
        got = await station.fetch_station.direct(None, now_entity="weather.idumbr13", temperature_sensor="sensor.outside",
                                                 rain_sensor="sensor.rain_rate")
        self.assertEqual((got["temperature"], got["humidity"], got["condition"]), (21.4, 82, "partlycloudy"))

    async def test_a_dim_sensor_under_trees_reads_cloudy_only_if_you_chose_it(self):
        got = await station.fetch_station.direct(None, now_entity="weather.idumbr13")
        self.assertEqual(got["condition"], "partlycloudy")
        got = await station.fetch_station.direct(None, now_entity="weather.idumbr13", solar_sensor="sensor.solar")
        self.assertEqual(got["condition"], "cloudy")

    async def test_rain_now_beats_everything(self):
        self.STATES = {**self.STATES, "sensor.rain_rate": {"state": "2.0", "attributes": {"unit_of_measurement": "mm/h"}}}
        got = await station.fetch_station.direct(None, now_entity="weather.idumbr13", rain_sensor="sensor.rain_rate",
                                                 solar_sensor="sensor.solar")
        self.assertEqual(got["condition"], "rainy")


class TestStationInTheRenderCycle(unittest.IsolatedAsyncioTestCase):
    async def test_the_weather_page_gets_now_from_the_station(self):
        el = {"type": "weather_forecast", "entity": "weather.forecast_home", "now_entity": "weather.idumbr13"}
        vals = {0: '{"condition": "sunny", "temperature": 20.6, "unit": "°C"}'}

        async def reader(session, **kw):
            self.assertEqual(kw, {"now_entity": "weather.idumbr13"})
            return {"temperature": 23, "condition": "partlycloudy"}
        with unittest.mock.patch.object(station, "fetch_station", reader), \
             unittest.mock.patch.object(ha_services, "fetch_weather_forecast", unittest.mock.AsyncMock(return_value=None)):
            await frames.enrich_page_values(None, {"elements": [el]}, vals)
        self.assertEqual((vals[0]["temperature"], vals[0]["condition"], vals[0]["unit"]), (23, "partlycloudy", "°C"))


class TestWeatherAtEverySize(Sizes, unittest.TestCase):
    element = {"type": "weather_forecast", "x": 24, "y": 14, "w": 744, "h": 208}
    value = {"condition": "rainy", "temperature": 23, "unit": "°C", "humidity": 82, "wind_speed": 0, "wind_unit": "km/h",
             "pressure_trend": "falling", "forecast": [
                 {"datetime": f"2026-10-2{k}T09:00:00+00:00", "condition": "sunny", "temperature": 20, "templow": 9,
                  "precipitation_probability": 70} for k in range(1, 6)]}

    def test_details_that_dont_fit_are_left_out_not_run_on(self):
        txt, f = layout._fit_parts(["HUM 82%", "WIND 0 km/h", "PRESSURE FALLING"], 160, 15, "  •  ")
        self.assertLessEqual(T.text_width(txt, f), 160)
        self.assertTrue(txt.startswith("HUM 82%"))
        self.assertNotIn("PRESSURE", txt)

    def test_a_wide_small_box_splits_instead_of_stacking_portrait_rows(self):
        # The 2.9" box (about 285 x 80) once got the portrait layout: day rows drawn over each other.
        target = arrange.canvas_key(*T.canvas_dims(0, "crowpanel_290"))
        box = arrange.auto_box(self.element, BASE, target)
        img = render(self.element, self.value, "crowpanel_290")
        divider = box["x"] + int(box["w"] * 0.42)              # the split layout's line between now and the days
        self.assertGreater(ink(img, (divider, box["y"], divider + 1, box["y"] + box["h"])), box["h"] // 2)

    def test_no_weather_from_home_assistant_draws_none_rather_than_made_up_weather(self):
        self.assertEqual(ink(render({**self.element, "show_border": False}, "")), 0)


class TestNoMadeUpScores(unittest.TestCase):
    def test_racing_and_matches_with_nothing_yet_draw_nothing_but_their_border(self):
        for el in ({"type": "sports_racing", "series": "nascar"}, {"type": "sports_match", "league": "soccer/eng.1"}):
            el = {**el, "x": 24, "y": 14, "w": 744, "h": 208, "show_border": False}
            self.assertEqual(ink(render(el, None)), 0, el["type"])
            self.assertEqual(ink(render(el, [])), 0, el["type"])


class TestEntitiesForPresets(EditorClient):
    async def test_rows_say_what_kind_of_sensor_they_are(self):
        rows = {r["entity_id"]: r for r in await (await self.ed.get("/api/entities")).json()}
        self.assertEqual(rows["sensor.indoor_temperature"]["device_class"], "temperature")
        self.assertEqual(rows["binary_sensor.front_door"]["device_class"], "door")
        self.assertEqual(rows["sensor.cat_location"]["device_class"], "")
        for eid in ("calendar.family", "calendar.bins", "calendar.tv", "weather.forecast_home", "media_player.living_room"):
            self.assertIn(eid, rows)


# ---------------------------------------------------------------- example thumbnails

import examples  # noqa: E402

EVERY_WIDGET = [
    {"type": "number", "entity": "sensor.solar_today_production", "show": "state", "x": 10, "y": 10, "w": 200, "h": 60},
    {"type": "sun_times"}, {"type": "energy_total", "source": "solar", "period": "month"}, {"type": "grid_now"},
    {"type": "energy_cost"}, {"type": "now_playing", "entity": "media_player.living_room"},
    {"type": "tv_week", "entity": "calendar.tv"}, {"type": "weather_forecast", "entity": "weather.forecast_home"},
    {"type": "todo_list", "entity": "todo.chores"}, {"type": "flight_tracker"},
    {"type": "sports_match", "league": "basketball/nba"}, {"type": "sports_racing", "series": "nascar"},
    {"type": "notifications"}, {"type": "updates"}, {"type": "badge", "counts": "all"},
    {"type": "curve", "entity": "sensor.solar_pv_power"},
]


class TestExamples(EditorClient):
    async def test_every_widget_has_an_example_and_nothing_is_asked_of_anyone(self):
        import ha
        import runtime
        runtime.PUBLISHED["sensor.solar_today_production"] = {"state": "99.9", "attributes": {}}   # the person's own
        boom = unittest.mock.AsyncMock(side_effect=AssertionError("an example asked Home Assistant or the internet"))
        try:
            with unittest.mock.patch.object(ha, "ha_json", boom), unittest.mock.patch.object(ha, "ha_template", boom), \
                 unittest.mock.patch.object(runtime, "HASS", unittest.mock.Mock(ws=boom)), \
                 unittest.mock.patch.object(runtime, "SESSION", unittest.mock.Mock(get=boom, request=boom)), \
                 unittest.mock.patch.object(web, "enrich_page_values", boom), \
                 unittest.mock.patch.object(web, "resolve_templates", boom), \
                 unittest.mock.patch.object(web, "curve_series", boom):
                for el in EVERY_WIDGET[1:]:
                    page = {"elements": [{"x": 24, "y": 14, "w": 744, "h": 208, "show_if": "{{ false }}", **el}]}
                    vals, _ = examples.page_values(page)
                    self.assertIsNotNone(vals.get(0) if el["type"] != "curve" else True, el["type"])
                    r = await self.ed.post("/api/example", json={"page": page})
                    self.assertEqual(r.status, 200, el["type"])
                    img = Image.open(io.BytesIO(await r.read())).convert("1")
                    self.assertGreater(ink(img), 300, f"{el['type']} drew no example")
                vals, _ = examples.page_values({"elements": EVERY_WIDGET[:1]})
                self.assertEqual(vals[0], "10.6")                     # the fixture's, never the person's 99.9
        finally:
            runtime.PUBLISHED.pop("sensor.solar_today_production", None)

    def test_each_league_and_series_has_its_own(self):
        self.assertEqual(examples.match("basketball/nba")["home_team"], "LAKERS")
        self.assertEqual(sport.badge(examples.match("soccer/eng.1")), "74' · SECOND HALF")
        self.assertEqual(examples.race("indycar")["series"], "INDYCAR")
        self.assertEqual(examples.race("nascar")["standings"][0]["driver"], "LAR")


# ---------------------------------------------------------------- each sport's own words

from render import sport  # noqa: E402
from sources import sports  # noqa: E402


class TestSportWords(unittest.TestCase):
    def test_a_premier_league_match_is_never_a_game(self):
        self.assertEqual(sport.words("soccer/eng.1").event, "match")
        self.assertEqual(sport.words("basketball/nba").event, "game")
        self.assertEqual(sport.words("football/nfl").event, "game")
        self.assertEqual(sport.words("racing").event, "race")
        self.assertEqual(sport.words("rugby/premiership").event, "match")
        self.assertEqual((sport.words("soccer/eng.1").events, sport.words("hockey/nhl").events), ("matches", "games"))
        self.assertEqual(sport.catalog()["other"].events, "matches")

    def test_every_league_knows_its_busiest_day(self):
        # What the editor's "on a busy day" line counts with: a round, a week, a busy Saturday.
        busiest = {lg.slug: lg.busiest_day for lg in sports.LEAGUES}
        self.assertEqual((busiest["premier_league"], busiest["nba"], busiest["nfl"], busiest["bundesliga"]), (10, 15, 16, 9))
        self.assertGreater(busiest["college_football"], 50)
        for lg in sports.LEAGUES:
            self.assertGreater(lg.busiest_day, 1, lg.slug)

    def _event(self, league):
        start = datetime.now(TZ).replace(hour=20, minute=0, second=0, microsecond=0)
        ev = {"date": start.isoformat(), "competitions": [{"status": {"type": {"state": "pre"}},
              "competitors": [{"homeAway": "home", "team": {"displayName": "A"}}, {"homeAway": "away", "team": {"displayName": "B"}}]}]}
        return sports._parse_espn_event(ev, "", tz_name="Europe/Bucharest", league=league)

    def test_the_start_says_the_sports_word(self):
        self.assertEqual(sport.badge(self._event("soccer/eng.1"), "soccer/eng.1"), "Kick-off 20:00")
        self.assertEqual(sport.badge(self._event("basketball/nba"), "basketball/nba"), "Tip-off 20:00")
        self.assertEqual(sport.badge(self._event("baseball/mlb"), "baseball/mlb"), "First pitch 20:00")

    def test_with_no_league_name_the_heading_is_the_sports_word(self):
        for league, word in (("soccer/eng.1", "MATCH"), ("hockey/nhl", "GAME")):
            self.assertEqual(self._event(league)["league"], "", "the page says it, in its language")
            el = {"type": "sports_match", "league": league, "x": 24, "y": 14, "w": 744, "h": 208}
            self.assertIn(word, words_drawn(el, self._event(league)))


class TestEveryGame(unittest.TestCase):
    def test_a_scores_page_has_every_game_of_the_day(self):
        # Not six: the panel's room is the only limit, shared out by frames.fit_counts.
        games = [{"id": str(i), "home_team": f"H{i}", "away_team": f"A{i}"} for i in range(15)]
        page = {"elements": [{"type": "sports_match", "league": "basketball/nba"}]}
        n, kind, keys, items, _ = subitems.inspect_category_subitems(page, {0: games})
        self.assertEqual((n, kind, len(set(keys)), len(items)), (15, "sports", 15, 15))

    def test_planes_still_stop_at_five(self):
        planes = [{"id": f"p{i}", "callsign": f"P{i}"} for i in range(9)]
        n, kind, *_ = subitems.inspect_category_subitems({"elements": [{"type": "flight_tracker"}]}, {0: planes})
        self.assertEqual((n, kind), (5, "flight"))


class TestRaceColumns(unittest.TestCase):
    def test_a_wide_driver_code_never_runs_into_the_team(self):
        import examples
        data = examples.race("nascar")
        data["standings"] = [{"pos": 1, "driver": "WWW", "team": "Team", "gap": "LEADER"}]
        el = {"type": "sports_racing", "x": 24, "y": 14, "w": 744, "h": 208, "show_border": False}
        img = render(el, data)
        drv_f = T.font(layout._s(min(19, max(13, int((208 - 52) * 0.54))), 1.0, 12, 28), bold=True)
        pos_f = T.font(layout._s(min(15, max(11, int((208 - 52) * 0.42))), 1.0, 10, 22), bold=True)
        code_end = 24 + 15 + max(32, T.text_width("P10", pos_f) + 6) + T.text_width("WWW", drv_f)
        gap = img.crop((code_end + 1, 60, code_end + 6, 200))       # between the code and the team: paper
        self.assertEqual(gap.histogram()[0], 0)


OFF_SEASON = {"series": "FE", "series_name": "Formula E", "event_name": "Jeddah E-Prix", "circuit": "Jeddah",
              "status": "OFF", "season": "Season 13", "next_start": "2026-12-18T12:00:00+00:00", "tz": "UTC",
              "standings": []}


def words_drawn(el, value) -> list[str]:
    from PIL import ImageDraw
    said = []
    real = ImageDraw.ImageDraw.text

    def text(self, xy, txt, *a, **kw):
        said.append(txt)
        return real(self, xy, txt, *a, **kw)
    with unittest.mock.patch.object(ImageDraw.ImageDraw, "text", text):
        render(el, value)
    return said[:-1]                    # the footer's clock last


class TestOffSeason(Sizes, unittest.TestCase):
    """The user's choice (22 Oct): the next season's first race as the card, an OFF SEASON badge."""
    element = {"type": "sports_racing", "series": "fe", "x": 24, "y": 14, "w": 744, "h": 208}
    value = OFF_SEASON

    def test_the_season_its_first_race_and_when(self):
        said = words_drawn({**self.element, "show_border": False}, OFF_SEASON)
        self.assertEqual(said, ["OFF SEASON", "FE · SEASON 13", "Jeddah E-Prix", "Season starts Fri 18 Dec"])

    def test_with_no_calendar_out_the_season_is_over(self):
        value = {**OFF_SEASON, "series": "INDYCAR", "series_name": "IndyCar", "event_name": "", "circuit": ""}
        value.pop("season")
        value.pop("next_start")
        said = words_drawn(self.element, value)
        self.assertEqual(said, ["OFF SEASON", "INDYCAR", "Season over", "Next season's calendar isn't out yet"])


class TestBeforeARace(Sizes, unittest.TestCase):
    element = {"type": "sports_racing", "series": "nascar", "x": 24, "y": 14, "w": 744, "h": 208}
    value = {"series": "NASCAR", "series_name": "NASCAR", "event_name": "NASCAR Cup Series at Talladega", "circuit": "",
             "status": "PRE", "session": "Race", "session_start": "2026-10-25T21:00:00+00:00", "tz": "Europe/Bucharest",
             "standings": []}

    def test_a_race_no_calendar_places_is_named_in_the_middle_not_left_blank(self):
        said = words_drawn(self.element, self.value)
        self.assertEqual(said, ["SCHEDULED", "NASCAR", "NASCAR Cup Series at Talladega", "Race · Sun 25 Oct · 23:00 EET"])


class TestExampleTemplates(unittest.TestCase):
    def test_the_clock_and_a_calendars_title_and_date(self):
        from render import binding
        from fixture import eval_fixture_template as ev
        # The clock answers with the time, as the add-on's own does; the page writes it (binding.now_text).
        el = {"type": "text", "value": "{{ now().strftime('%H:%M') }}"}
        self.assertEqual(binding.now_text(el, ev(el["value"], own=False)), datetime.now().strftime("%H:%M"))
        self.assertTrue(ev("{{ now().strftime('%A, %-d %B') }}", own=False))
        bins = {"entity": "calendar.bins"}
        self.assertEqual(ev(binding.template_for({**bins, "show": "calendar_title"}), own=False), "Recycling")
        self.assertIn(ev(binding.template_for({**bins, "show": "days_until"}), own=False), ("3", "4"))   # by time of day
        self.assertTrue(ev(binding.template_for({"entity": "calendar.family", "show": "date_formatted"}), own=False))


# ---------------------------------------------------------------- 12- or 24-hour

import timeformat  # noqa: E402
from render import binding, clock, todo  # noqa: E402


class TestTimeFormat(unittest.TestCase):
    def tearDown(self):
        clock.use(False)
        try:
            (support.DATA_DIR / timeformat.FILE).unlink()
        except FileNotFoundError:
            pass
        support.use_test_data_dir()

    def test_automatic_follows_home_assistants_country(self):
        support.use_test_data_dir()
        self.assertTrue(timeformat.twelve_hour("US", "en"))
        self.assertFalse(timeformat.twelve_hour("RO", "ro"))
        self.assertFalse(timeformat.twelve_hour("CA", "fr"))
        self.assertTrue(timeformat.twelve_hour("CA", "en"))
        self.assertFalse(timeformat.twelve_hour(None, None))

    def test_the_setting_overrides_it(self):
        support.use_test_data_dir()
        timeformat.save("24h")
        self.assertFalse(timeformat.twelve_hour("US"))
        timeformat.save("12h")
        self.assertEqual(timeformat.describe("RO"), {"format": "12h", "resolved": "12h", "country": "RO"})
        with self.assertRaises(ValueError):
            timeformat.save("13h")

    def test_every_time_on_the_panel_follows_it(self):
        at = datetime(2026, 10, 21, 14, 5, tzinfo=TZ)
        clock.use(True)
        self.assertEqual(clock.hm(at), "2:05 PM")
        self.assertEqual(sun.facts({"rising": at.isoformat(), "setting": at.isoformat()}, at)[0].value, "2:05 PM")
        self.assertEqual(todo.due_label({"due": at.isoformat()}, at.replace(hour=9))[0], "Today 2:05 PM")
        self.assertEqual(binding.now_text({"show": "now"}, at), "2:05 PM")
        self.assertEqual(binding.shown({"entity": "sensor.door", "show": "last_changed", "format": "time"}, at.isoformat()), "2:05 PM")
        # A kick-off today reads "Kick-off": today on the real clock, whatever day the tests run.
        kick = datetime.now(TZ).replace(hour=14, minute=5, second=0, microsecond=0)
        self.assertEqual(sport.badge(sports._parse_espn_event({"date": kick.isoformat(), "competitions": [{"status": {"type": {"state": "pre"}}}]},
                                                              "", tz_name="Europe/Bucharest", league="soccer/eng.1"), "soccer/eng.1"), "Kick-off 2:05 PM")
        clock.use(False)
        self.assertEqual(clock.hm(at), "14:05")
        self.assertEqual(binding.now_text({"show": "now", "format": "day_full"}, at), "Wednesday, 21 October")


class TestTimeForTheEditor(EditorClient):
    async def test_set_and_read_and_which_elements_show_the_time(self):
        r = await self.ed.put("/api/settings/time", json={"format": "12h"})
        self.assertEqual((await r.json())["resolved"], "12h")
        self.assertTrue(clock.twelve_hour())
        r = await self.ed.put("/api/settings/time", json={"format": "sometimes"})
        self.assertEqual(r.status, 400)
        await self.ed.put("/api/settings/time", json={"format": "auto"})
        r = await self.ed.post("/api/shows-time", json={"page": {"elements": [
            {"type": "text", "value": "{{ states('sensor.time') }}"}, {"type": "text", "value": "Hello"}, {"type": "text", "show": "now"}]}})
        self.assertEqual(await r.json(), {"time": [0, 2]})
        clock.use(False)


# ---------------------------------------------------------------- a running total's change today

class TestChangeToday(unittest.IsolatedAsyncioTestCase):
    EL = {"type": "number", "entity": "sensor.inverter_lifetime", "show": "change_today", "decimals": 1, "suffix": " kWh"}

    async def test_a_lifetime_meter_shows_today_not_its_lifetime(self):
        self.assertEqual(binding.template_for(self.EL), "")             # never states(): that's 18,532 kWh
        asked = []

        async def total(session, source, entity, period):
            asked.append((source, entity, period))
            return {"total": 12.4, "bars": [], "unit": "kWh"}
        vals = {}
        with unittest.mock.patch.object(energy, "fetch_total", total):
            await frames.enrich_page_values(None, {"elements": [self.EL]}, vals)
        self.assertEqual(asked, [("entity", "sensor.inverter_lifetime", "day")])
        self.assertEqual(layout.element_text(self.EL, vals, 0), "12.4 kWh")

    async def test_in_the_sensors_own_unit(self):
        import runtime
        hass = FakeHass(rows={"sensor.meter": []})
        with unittest.mock.patch.object(energy, "HA_TOKEN", "t"), unittest.mock.patch.object(runtime, "HASS", hass), \
             unittest.mock.patch.object(energy, "get_home_timezone", unittest.mock.AsyncMock(return_value="UTC")):
            await energy.fetch_total.direct(None, "entity", "sensor.meter", "day")
        asked = [p for p in hass.asked if p["type"] == "recorder/statistics_during_period"][0]
        self.assertNotIn("units", asked)


class TestStateClassForPresets(EditorClient):
    async def test_rows_say_whether_its_a_running_total(self):
        rows = {r["entity_id"]: r for r in await (await self.ed.get("/api/entities")).json()}
        self.assertEqual(rows["sensor.solar_today_production"]["state_class"], "total_increasing")
        self.assertEqual(rows["sensor.indoor_temperature"]["state_class"], "")


# ---------------------------------------------------------------- state words

from render import states as state_words  # noqa: E402


class TestStateWords(unittest.TestCase):
    def test_a_switch_never_reads_open(self):
        self.assertEqual(state_words.words("switch.guest_mode")["on"][0], "On")
        self.assertEqual(state_words.words("binary_sensor.hall", "motion")["on"][0], "Detected")
        self.assertEqual(state_words.words("binary_sensor.front", "door")["off"][0], "Closed")
        self.assertEqual(state_words.words("binary_sensor.washer", "running")["on"][0], "Running")
        self.assertEqual(state_words.words("binary_sensor.thing", "")["on"][0], "On")
        self.assertEqual(state_words.words("lock.front")["locked"][0], "Locked")
        self.assertEqual(state_words.words("person.ada")["not_home"][0], "Away")
        self.assertEqual(state_words.words("sensor.temperature"), {})

    def test_every_icon_is_in_the_panels_icon_font(self):
        for key, by_state in state_words.STATES.items():
            for st, (word, icon) in by_state.items():
                self.assertIsNotNone(layout.mdi_codepoint(icon), f"{key} {st}: {icon}")
                self.assertTrue(word and word[0].isupper(), f"{key} {st}: sentence case")


class TestEveryLeagueHasItsExample(unittest.TestCase):
    def test_both_ways(self):
        offered = {lg.path for lg in sports.LEAGUES}
        self.assertEqual(set(examples._TEAMS), offered, "every offered league has its own teams, and only those")
        for path in offered:
            self.assertNotIn(examples.match(path)["home_team"], ("HOME", "AWAY"), path)


# ---------------------------------------------------------------- one descriptor per widget, one catalog

import widgets  # noqa: E402


class TestWidgetDescriptors(unittest.TestCase):
    def test_every_widget_the_panel_draws_from_a_value_is_described(self):
        drawn = set(layout.WIDGETS) | {"weather_forecast", "calendar_month", "calendar_agenda", "todo_list",
                                       "flight_tracker", "sports_racing", "sports_match", "dynamic_grid"}
        self.assertEqual(set(widgets.WIDGETS), drawn)
        for t, w in widgets.WIDGETS.items():
            self.assertIn(t, layout.DRAWERS, t)
            d = w.describe()
            self.assertTrue(d["name"] and d["icon"] and isinstance(d["box"], dict) and isinstance(d["fields"], list), t)

    def test_how_often_what_it_shows_changes(self):
        # The user's list: planes, scores, races, what's playing, the grid now, a weather station; and
        # (ha-pages, 30 Oct) travel times and departures, which change by the minute too.
        live = {t: w.changes_every() for t, w in widgets.WIDGETS.items() if w.changes_every()}
        self.assertEqual(live, {"now_playing": 10, "grid_now": 15, "flight_tracker": 30, "sports_racing": 30,
                                "sports_match": 30, "weather_forecast": 60, "commute": 120, "departures": 60})
        weather = widgets.get("weather_forecast")
        self.assertIsNone(weather.changes_every({"entity": "weather.home"}), "a forecast alone changes slowly")
        self.assertEqual(weather.changes_every({"entity": "weather.home", "rain_sensor": "sensor.rain"}), 60)
        self.assertIn("now_entity", weather.describe()["changes_when"])

    def test_every_widget_with_a_fetch_has_an_example(self):
        for t, w in widgets.WIDGETS.items():
            self.assertEqual(w.fetch is None, w.example is None, t)

    def test_items_of_a_page_come_from_the_descriptors(self):
        self.assertEqual(subitems.WIDGET_ITEMS, {t: w.items for t, w in widgets.WIDGETS.items() if w.items})


class TestCatalog(EditorClient):
    async def test_the_editor_reads_the_servers_tables(self):
        got = await (await self.ed.get("/api/catalog")).json()
        self.assertEqual([lg["path"] for lg in got["leagues"]], [lg.path for lg in sports.LEAGUES])
        nfl = next(lg for lg in got["leagues"] if lg["slug"] == "nfl")
        self.assertEqual((nfl["sensor"], nfl["words"]["event"]), ("sensor.epaper_sports_nfl", "game"))
        self.assertEqual((nfl["busiest_day"], nfl["words"]["events"]), (16, "games"))
        nascar = next(s for s in got["series"] if s["slug"] == "nascar")
        self.assertIn("nascar_cup", nascar["aliases"])
        self.assertEqual({s["slug"] for s in got["series"]}, set(racing.SERIES), "every series is offered")
        self.assertEqual(got["sport_words"]["soccer"]["event"], "match")
        self.assertEqual(got["states"]["binary_sensor.motion"]["on"]["word"], "Detected")
        self.assertEqual(set(got["widgets"]), set(widgets.WIDGETS))
        self.assertEqual(got["widgets"]["now_playing"]["changes_every"], 10)
        self.assertIsNone(got["widgets"]["calendar_month"]["changes_every"])
        self.assertIn(got["time_format"], ("12h", "24h"))


class TestNoGuessedWeather(unittest.IsolatedAsyncioTestCase):
    async def test_a_weather_widget_without_one_shows_the_first_home_assistant_has(self):
        async def states(session, path, **kw):
            return [{"entity_id": "sensor.x"}, {"entity_id": "weather.zz_station"}, {"entity_id": "weather.home"}]
        import runtime
        with unittest.mock.patch.object(ha_services, "HA_TOKEN", "t"), unittest.mock.patch.object(ha_services, "ha_json", states), \
             unittest.mock.patch.dict(runtime.ENTITY_CACHE, {"items": []}):
            self.assertEqual(await ha_services.default_weather(None), "weather.home")
        self.assertNotIn(0, layout.collect_templates({"elements": [{"type": "weather_forecast"}]}))


# ---------------------------------------------------------------- presets-015's asks: fit, a sensor's pace, state icons

class TestFitForADevice(EditorClient):
    async def test_a_page_made_on_the_579_placed_for_the_29(self):
        el = {"type": "text", "value": "Hi", "x": 24, "y": 14, "w": 744, "h": 208}
        r = await self.ed.post("/api/fit", json={"elements": [el], "from_canvas": "792x272", "display": "crowpanel_290"})
        got = (await r.json())["elements"][0]
        target = arrange.canvas_key(*T.canvas_dims(0, "crowpanel_290"))
        self.assertEqual({k: got[k] for k in ("x", "y", "w", "h")}, arrange.auto_box(el, "792x272", target))
        self.assertEqual(got["value"], "Hi")
        r = await self.ed.post("/api/fit", json={"elements": [el], "from_canvas": "big"})
        self.assertEqual(r.status, 400)

    async def test_preview_and_example_take_from_canvas(self):
        page = {"elements": [{"type": "sun_times", "x": 24, "y": 14, "w": 744, "h": 208}]}
        for route in ("/api/preview", "/api/example"):
            r = await self.ed.post(route, json={"page": page, "from_canvas": "792x272", "display": "crowpanel_290"})
            self.assertEqual(r.status, 200, route)
            self.assertEqual(Image.open(io.BytesIO(await r.read())).size, T.canvas_dims(0, "crowpanel_290"))

    async def test_a_power_sensor_changes_every_minute(self):
        rows = {r["entity_id"]: r for r in await (await self.ed.get("/api/entities")).json()}
        self.assertEqual(rows["sensor.solar_pv_power"]["changes_every"], 60)
        self.assertIsNone(rows["sensor.indoor_temperature"]["changes_every"])


class TestIconsFollowTheirState(unittest.TestCase):
    EL = {"type": "icon", "entity": "binary_sensor.front_door", "icon": "mdi:door-closed",
          "state_icons": {"on": "mdi:door-open", "off": "mdi:door-closed"}, "x": 300, "y": 40, "w": 160, "h": 160}

    def test_the_state_picks_the_icon_and_its_own_is_the_fallback(self):
        self.assertIn(0, layout.collect_templates({"elements": [self.EL]}))
        open_, closed, unknown = (render(self.EL, v) for v in ("on", "off", "jammed"))
        self.assertNotEqual(open_.tobytes(), closed.tobytes())
        self.assertEqual(unknown.tobytes(), closed.tobytes(), "no match: its own icon")
        self.assertEqual(render(self.EL, None).tobytes(), closed.tobytes(), "not known yet: its own icon")

    def test_a_state_matches_whatever_its_case(self):
        # Home Assistant says "Outdoor Cat"; a row typed "outdoor cat" is the same state.
        el = {**self.EL, "entity": "sensor.pawpaw_location", "icon": "mdi:help",
              "state_icons": {"outdoor cat": "mdi:cat-outline", "Indoor Cat ": "mdi:cat"}}
        out, in_, other = (render(el, v) for v in ("Outdoor Cat", "INDOOR CAT", "Away"))
        self.assertEqual(out.tobytes(), render({**el, "state_icons": {"Outdoor Cat": "mdi:cat-outline"}}, "Outdoor Cat").tobytes())
        self.assertNotEqual(out.tobytes(), other.tobytes())
        self.assertNotEqual(in_.tobytes(), other.tobytes())
        self.assertEqual(other.tobytes(), render({**el, "state_icons": {}}, "Away").tobytes(), "no match: its own icon")

    def test_a_state_has_its_own_look(self):
        # "Outdoor Cat" inverted to stand out; an entry that's just an icon keeps the element's Style.
        el = {**self.EL, "state_icons": {"on": {"icon": "mdi:door-open", "look": "invert"}, "off": "mdi:door-closed"}}
        inverted = {**self.EL, "icon": "mdi:door-open", "invert": True}
        inverted.pop("state_icons")
        self.assertEqual(render(el, "on").tobytes(), render(inverted, None).tobytes())
        self.assertEqual(render(el, "off").tobytes(), render(self.EL, "off").tobytes(), "a plain string: just an icon")
        outlined = {**el, "pill": True}
        self.assertEqual(render(outlined, "on").tobytes(), render({**inverted, "pill": True}, None).tobytes(),
                         "its own look wins over the element's")
        plain_state = {**self.EL, "invert": True, "state_icons": {"off": {"icon": "mdi:door-closed", "look": "plain"}}}
        self.assertEqual(render(plain_state, "off").tobytes(), render({**self.EL, "state_icons": {}}, "x").tobytes(),
                         "plain is a look too: an inverted icon drawn plain in that state")
        self.assertEqual(render(plain_state, "jammed").tobytes(), render({**self.EL, "invert": True, "state_icons": {}}, "x").tobytes(),
                         "anything else: the element's own Style")

    def test_an_unknown_look_is_the_elements(self):
        got = layout.icon_in_state({"icon": "mdi:a", "invert": True, "state_icons": {"on": {"icon": "mdi:b", "look": "sparkly"}}}, "ON")
        self.assertEqual((got["icon"], got["invert"]), ("mdi:b", True))
        self.assertEqual(layout.icon_for_state({"on": {"icon": "mdi:b", "look": "invert"}}, "on"), "mdi:b", "spots read the icon of either shape")

    def test_one_lookup_for_icons_and_status_spots(self):
        si = {"Outdoor Cat": "mdi:cat-outline", "on": ""}
        self.assertEqual(layout.icon_for_state(si, " outdoor cat "), "mdi:cat-outline")
        self.assertEqual(layout.icon_for_state(si, "on"), "", "an empty icon is no icon")
        self.assertEqual(layout.icon_for_state(None, "on"), "")
        self.assertEqual(layout._resolve_spot_icon({"state_icons": si, "icon": "mdi:cat"}, "OUTDOOR CAT"), "mdi:cat-outline")


# ---------------------------------------------------------------- world clock

from datetime import timezone as dt_timezone  # noqa: E402

from render import clocktime, worldclock  # noqa: E402

CITIES = [{"tz": "", "label": ""}, {"tz": "America/New_York", "label": "New York"},
          {"tz": "Asia/Kolkata", "label": "Mumbai"}, {"tz": "Australia/Sydney", "label": "Sydney"}]


class TestWorldClock(Sizes, unittest.TestCase):
    element = {"type": "world_clock", "zones": CITIES[:3], "x": 24, "y": 14, "w": 744, "h": 208}
    value = {"tz": "Europe/Bucharest"}

    def test_times_from_the_database_with_daylight_saving_and_a_day_mark(self):
        el = {"zones": CITIES}
        winter = datetime(2026, 1, 15, 14, 0, tzinfo=dt_timezone.utc)
        summer = datetime(2026, 7, 15, 14, 0, tzinfo=dt_timezone.utc)
        w, s = worldclock.slots(el, "Europe/Bucharest", winter), worldclock.slots(el, "Europe/Bucharest", summer)
        self.assertEqual([x[:2] for x in w], [("Bucharest", "16:00"), ("New York", "09:00"), ("Mumbai", "19:30"), ("Sydney", "01:00")])
        self.assertEqual(w[3][2], "+1")
        self.assertEqual(s[1][1], "10:00", "New York in summer time")
        # 23:30 UTC: Los Angeles is still the 15th, Bucharest already the 16th.
        self.assertEqual(worldclock.slots({"zones": [{"tz": "America/Los_Angeles"}]}, "Europe/Bucharest",
                                          datetime(2026, 1, 15, 23, 30, tzinfo=dt_timezone.utc))[0][2], "−1")

    def test_asleep_each_city_says_how_far_it_is(self):
        el = {"zones": CITIES, "asleep": True}
        got = worldclock.slots(el, "Europe/Bucharest", datetime(2026, 1, 15, 20, 0, tzinfo=dt_timezone.utc))
        self.assertEqual([x[1] for x in got], ["Same time", "−7 h", "+3:30 h", "+9 h"])
        self.assertEqual(got[3][2], "Fri", "Sydney is on another day")

    def test_a_sleeping_device_marks_it_and_leaves_a_date_beside_it_alone(self):
        page = {"elements": [{"type": "world_clock", "zones": CITIES[:2]},
                             {"type": "text", "value": "{{ now().strftime('%A, %-d %B') }}"}]}
        got, vals, times = clocktime.date_for_time(page, {1: "Thursday, 15 January"}, datetime(2026, 1, 15, 12, 0))
        self.assertEqual(times, {0})
        self.assertTrue(got["elements"][0]["asleep"])
        self.assertEqual(vals[1], "Thursday, 15 January")
        self.assertNotIn("asleep", page["elements"][0], "the design keeps its clock")

    def test_cities_fill_the_box_however_many(self):
        for n in (1, 2, 3, 4):
            el = {**self.element, "zones": CITIES[:n]}
            self.assertGreater(ink(render(el, self.value)), 500 * n)
        rows, cols, _, _ = worldclock.layout(2, 744, 208, worldclock.slots({"zones": CITIES[:2]}, "UTC", datetime.now(dt_timezone.utc)))
        self.assertEqual((rows, cols), (1, 2), "side by side on the wide 5.79\"")
        rows, cols, _, _ = worldclock.layout(2, 260, 420, worldclock.slots({"zones": CITIES[:2]}, "UTC", datetime.now(dt_timezone.utc)))
        self.assertEqual((rows, cols), (2, 1), "stacked when upright")

    def test_an_unknown_zone_is_left_out_and_none_says_what_to_do(self):
        self.assertEqual(len(worldclock.zones({"zones": [{"tz": "Mars/Olympus"}, {"tz": "Asia/Tokyo"}]}, "UTC")), 1)
        self.assertGreater(ink(render({**self.element, "zones": []}, self.value)), 200)

    def test_the_editor_gets_every_city_and_the_descriptor(self):
        cities = {z["tz"]: z for z in worldclock.catalog(datetime(2026, 1, 15, tzinfo=dt_timezone.utc))}
        self.assertEqual(cities["America/New_York"]["city"], "New York")
        self.assertEqual(cities["Asia/Kolkata"]["offset"], "+05:30")
        self.assertNotIn("US/Eastern", cities)
        self.assertIsNone(widgets.get("world_clock").changes_every(), "a sleeping device shows hours apart instead")
        self.assertTrue(clocktime.shows_time({"type": "world_clock"}))


class TestOneNameOneThing(unittest.TestCase):
    """A module that defines a name twice keeps only the last: 0.20.2's Batteries fetch and the
    Grid now fetch were both widgets._grid, and the Batteries page asked for the power grid."""

    def test_no_module_defines_a_name_twice(self):
        import ast
        import collections
        twice = {}
        for path in sorted(support.APP.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = collections.Counter(n.name for n in tree.body
                                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
            if dup := sorted(k for k, v in names.items() if v > 1):
                twice[str(path.relative_to(support.APP))] = dup
        self.assertEqual(twice, {})
