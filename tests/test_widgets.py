"""The 0.15 widgets: what each shows, at every size a screen can have."""
import asyncio
import urllib.parse
import unittest.mock
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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

from sources import station  # noqa: E402


class TestStation(unittest.TestCase):
    def test_only_the_parts_you_chose(self):
        el = {"type": "weather_forecast", "entity": "weather.forecast_home", "now_entity": "weather.idumbr13",
              "rain_sensor": "sensor.rain_rate", "solar_sensor": "", "pressure_sensor": "not an id"}
        self.assertEqual(station.wanted(el), {"now_entity": "weather.idumbr13", "rain_sensor": "sensor.rain_rate"})

    def test_rain_falling_now(self):
        self.assertEqual(station.raining({"state": "0.0", "attributes": {"unit_of_measurement": "mm/h"}}), None)
        self.assertEqual(station.raining({"state": "1.2", "attributes": {"unit_of_measurement": "mm/h"}}), "rainy")
        self.assertEqual(station.raining({"state": "0.4", "attributes": {"unit_of_measurement": "in/h"}}), "pouring")
        self.assertEqual(station.raining({"state": "on"}), "rainy")
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
        self.assertEqual(station.trend(rows("29.90", "29.80"), now), "falling")       # inHg
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
             unittest.mock.patch.object(frames, "fetch_weather_forecast", unittest.mock.AsyncMock(return_value=None)):
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
