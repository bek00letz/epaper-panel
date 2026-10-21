"""Jellyfin: `detail` stays as it was, and its parts are there on their own."""
import json
import shutil
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

import support
import frames
import runtime
import web
from feeds import jellyfin
from render import binding, layout, subitems

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)


def at(days_ago):
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


EPISODE = {"Id": "e1", "Type": "Episode", "Name": "The Signal", "SeriesName": "Northern Lights",
           "ParentIndexNumber": 2, "IndexNumber": 4, "RunTimeTicks": 27_000_000_000, "DateCreated": at(1)}
SERIES = {"Id": "s1", "Type": "Series", "Name": "Harbour Town", "ChildCount": 2,
          "RunTimeTicks": 30_000_000_000, "ProductionYear": 2019, "DateCreated": at(3)}
FILM = {"Id": "m1", "Type": "Movie", "Name": "Paper Moon", "ProductionYear": 1973,
        "RunTimeTicks": 67_200_000_000, "DateCreated": at(0)}


class TestParts(unittest.TestCase):
    def test_an_episode(self):
        d = jellyfin.describe(EPISODE, NOW)
        self.assertEqual(d["title"], "Northern Lights")
        self.assertEqual(d["detail"], "The Signal · yesterday")
        self.assertEqual(d["kind"], "episode")
        self.assertEqual(d["what_is_new"], "The Signal")
        self.assertEqual(d["episode_name"], "The Signal")
        self.assertEqual(d["episode_number"], "S02E04")
        self.assertEqual(d["new_episodes"], 1)
        self.assertEqual(d["added_ago"], "yesterday")
        self.assertEqual(d["added"], "2026-03-09T12:00:00+00:00")

    def test_a_series_with_several_new_episodes(self):
        d = jellyfin.describe(SERIES, NOW)
        self.assertEqual(d["detail"], "2 new episodes · 3 days ago")
        self.assertEqual(d["what_is_new"], "2 new episodes")
        self.assertEqual(d["new_episodes"], 2)
        self.assertEqual((d["kind"], d["episode_name"], d["episode_number"]), ("series", "", ""))

    def test_one_new_episode_reads_singular(self):
        d = jellyfin.describe({**SERIES, "ChildCount": 1}, NOW)
        self.assertEqual(d["detail"], "1 new episode · 3 days ago")

    def test_a_film(self):
        d = jellyfin.describe(FILM, NOW)
        self.assertEqual(d["detail"], "film · today")
        self.assertEqual((d["kind"], d["what_is_new"], d["new_episodes"]), ("film", "film", 0))

    def test_episode_numbers(self):
        self.assertEqual(jellyfin.episode_number({"IndexNumber": 4}), "E04")
        self.assertEqual(jellyfin.episode_number({"ParentIndexNumber": 1, "IndexNumber": 1,
                                                  "IndexNumberEnd": 2}), "S01E01–E02")
        self.assertEqual(jellyfin.episode_number({"ParentIndexNumber": 1}), "")

    def test_the_line_under_the_name(self):
        self.assertEqual(jellyfin.describe(EPISODE, NOW)["about"], "S02E04 · The Signal")
        self.assertEqual(jellyfin.describe(SERIES, NOW)["about"], "2 new episodes")
        self.assertEqual(jellyfin.describe(FILM, NOW)["about"], "1973 · 1 h 52 min")
        self.assertEqual(jellyfin.describe({**FILM, "ProductionYear": None, "RunTimeTicks": None}, NOW)["about"], "")

    def test_running_time(self):
        self.assertEqual(jellyfin.runtime({"RunTimeTicks": 27_000_000_000}), "45 min")
        self.assertEqual(jellyfin.runtime({"RunTimeTicks": 72_000_000_000}), "2 h")
        self.assertEqual(jellyfin.runtime({}), "")
        self.assertEqual(jellyfin.describe(SERIES, NOW)["runtime"], "", "a series' episode length isn't what's new")

    def test_up_next_is_one_short_line_each(self):
        long = {**FILM, "Id": "m2", "Name": "A Very Long Film Title That Goes On For A While"}
        items = [jellyfin.describe(i, NOW) for i in (EPISODE, SERIES, FILM, long, EPISODE, FILM)]
        rows = jellyfin.up_next(items).split("\n")
        self.assertEqual(len(rows), jellyfin.UP_NEXT_ROWS)
        self.assertEqual(rows[:3], ["Northern Lights · S02E04 · yesterday",
                                    "Harbour Town · 2 new · 3 days ago", "Paper Moon · film · today"])
        self.assertEqual(rows[3], "A Very Long Film Title That… · film · today")
        self.assertEqual(jellyfin.up_next([]), "")

    def test_no_date_is_left_out(self):
        self.assertIsNone(jellyfin.describe({**FILM, "DateCreated": None}, NOW))
        self.assertIsNone(jellyfin.describe({**FILM, "DateCreated": "soon"}, NOW))


class TestSensor(unittest.IsolatedAsyncioTestCase):
    async def fetch(self, items):
        src = {"name": "watch", "base": "http://jellyfin.local:8096", "key": "k", "days": 30}
        with mock.patch.object(jellyfin, "_fetch_items", mock.AsyncMock(return_value=items)):
            return await jellyfin.fetch(src, {"session": object()})

    async def test_the_top_item_parts_are_attributes(self):
        recent = {**EPISODE, "DateCreated": datetime.now(timezone.utc).isoformat()}
        (eid, state, attrs), _ = await self.fetch([recent, {**FILM, "DateCreated": recent["DateCreated"]}])
        self.assertEqual((eid, state), ("sensor.epaper_watch", "Northern Lights"))
        self.assertEqual(attrs["detail"], f"The Signal · {attrs['added_ago']}")
        self.assertEqual(attrs["episode_name"], "The Signal")
        self.assertEqual(attrs["episode_number"], "S02E04")
        self.assertEqual(attrs["count"], 2)
        self.assertEqual([i["kind"] for i in attrs["items"]], ["episode", "film"])
        self.assertNotIn("_added", attrs["items"][0])

    async def test_old_items_are_left_out(self):
        (_, state, attrs), (_, count, _) = await self.fetch([{**FILM, "DateCreated": "2001-01-01T00:00:00Z"}])
        self.assertEqual((state, count), ("nothing new", 0))
        self.assertEqual(attrs["detail"], "")
        self.assertEqual(attrs["episode_name"], "")
        self.assertEqual(attrs["new_episodes"], 0)


class TestPagesShowTheParts(unittest.TestCase):
    ENT = "sensor.epaper_watch"

    def setUp(self):
        self.items = [jellyfin.describe(EPISODE, NOW), jellyfin.describe(SERIES, NOW)]
        top = self.items[0]
        self.registry = {self.ENT: {"state": top["title"],
                                    "attributes": {k: top[k] for k in ("detail", *jellyfin.PARTS)}}}

    def el(self, attribute, **more):
        return {"type": "text", "entity": self.ENT, "show": "attribute", "attribute": attribute, **more}

    def test_text_binding_reads_each_part(self):
        self.assertEqual(binding.local_value(self.el("episode_number"), self.registry), "S02E04")
        self.assertEqual(binding.local_value(self.el("added_ago"), self.registry), "yesterday")
        self.assertEqual(binding.local_value(self.el("new_episodes"), self.registry), "1")

    def test_each_slice_shows_its_own_item(self):
        el = self.el("what_is_new")
        self.assertEqual([subitems.item_value(el, self.ENT, i) for i in self.items],
                         ["The Signal", "2 new episodes"])

    def test_replacements_apply_on_every_slice(self):
        el = self.el("added_ago", replace={"yesterday": "Yesterday"})
        self.assertEqual(subitems.item_value(el, self.ENT, self.items[0]), "Yesterday")

    def test_other_bindings_keep_the_old_path(self):
        item = self.items[0]
        self.assertIsNone(subitems.item_value(self.el("count"), self.ENT, item))
        self.assertIsNone(subitems.item_value({**self.el("episode_name"), "entity": "sensor.other"}, self.ENT, item))
        self.assertIsNone(subitems.item_value({"type": "text", "entity": self.ENT}, self.ENT, item))
        self.assertIsNone(subitems.item_value(self.el("episode_name", value="{{ 1 }}"), self.ENT, item))


class TestListPagesDontStep(unittest.TestCase):
    ENT = "sensor.epaper_watch"

    def page(self, attribute):
        return {"elements": [{"type": "text", "entity": self.ENT, "show": "attribute", "attribute": attribute}]}

    def test_whole_feed_details_are_one_screen(self):
        items = [jellyfin.describe(i, NOW) for i in (EPISODE, SERIES, FILM)]
        for attribute in ("up_next", "count"):
            n, kind, *_ = subitems.inspect_category_subitems(self.page(attribute), {}, {self.ENT: items})
            self.assertEqual((n, kind), (1, None), attribute)
        n, kind, *_ = subitems.inspect_category_subitems(self.page("about"), {}, {self.ENT: items})
        self.assertEqual((n, kind), (3, "feed"))


@unittest.skipUnless(shutil.which("node"), "no node to read the editor's presets")
class TestPresets(unittest.TestCase):
    """The editor's Jellyfin presets, drawn by the real renderer with real-looking values."""
    ENT = "sensor.epaper_films"

    @classmethod
    def setUpClass(cls):
        script = (f"import {{ PRESETS }} from {json.dumps(str(support.APP / 'web/app/legacy.js'))};"
                  f"console.log(JSON.stringify(PRESETS.filter((p) => p.asks === 'jellyfin')"
                  f".map((p) => ({{ id: p.id, show_if: p.showIf({json.dumps(cls.ENT)}),"
                  f" elements: p.makeElements({json.dumps(cls.ENT)}) }}))))")
        out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
        cls.presets = {p["id"]: p for p in json.loads(out.stdout)}

    def setUp(self):
        long = {**FILM, "Id": "m2", "Name": "A Very Long Film Title That Goes On For A While"}
        items = [jellyfin.describe(i, NOW) for i in (EPISODE, SERIES, FILM, long, EPISODE)]
        for d in items:
            d.pop("_added")
        top = items[0]
        runtime.PUBLISHED[self.ENT] = {"state": top["title"], "attributes": {
            "detail": top["detail"], "count": len(items), **{k: top[k] for k in jellyfin.PARTS},
            "up_next": jellyfin.up_next(items), "items": items}}

    def tearDown(self):
        runtime.PUBLISHED.pop(self.ENT, None)

    def test_three_screens_on_the_chosen_sensor(self):
        self.assertEqual(sorted(self.presets), ["episode", "up_next", "watch"])
        for p in self.presets.values():
            self.assertEqual(p["show_if"], "{{ states('sensor.epaper_films_count') | int(0) > 0 }}")
            self.assertTrue(all(el.get("entity") in (None, self.ENT) for el in p["elements"]))

    def test_everything_fits(self):
        for pid, p in self.presets.items():
            vals, templates = frames.split_page_values(p)
            self.assertEqual(templates, {}, f"{pid} reads only the add-on's own values")
            metrics = []
            layout.render_page(p, vals, metrics=metrics)
            self.assertTrue(metrics)
            self.assertEqual([m for m in metrics if m.get("overflow")], [], pid)

    def test_the_list_shows_every_row(self):
        vals, _ = frames.split_page_values(self.presets["up_next"])
        rows = [v for v in vals.values() if "\n" in v][0].split("\n")
        self.assertEqual(len(rows), jellyfin.UP_NEXT_ROWS)
        self.assertIn("Harbour Town · 2 new · 3 days ago", rows)


class TestEditorListsTheParts(unittest.IsolatedAsyncioTestCase):
    ENT = "sensor.epaper_jellyfin_test"

    async def asyncSetUp(self):
        top = jellyfin.describe(EPISODE, NOW)
        runtime.PUBLISHED[self.ENT] = {"entity_id": self.ENT, "state": top["title"],
                                       "attributes": {k: top[k] for k in ("detail", *jellyfin.PARTS)}}
        _, editor = web.make_apps()
        self.ed = TestClient(TestServer(editor))
        await self.ed.start_server()

    async def asyncTearDown(self):
        await self.ed.close()
        runtime.PUBLISHED.pop(self.ENT, None)

    async def test_jellyfin_sensors_are_marked(self):
        data = support.use_test_data_dir()
        f = data / "sources.json"
        before = f.read_bytes() if f.exists() else None
        try:
            f.write_text(json.dumps([{"type": "jellyfin", "name": "jellyfin_test", "base": "", "key": ""}]))
            r = await self.ed.get("/api/entities")
            mine = [e for e in await r.json() if e["entity_id"] == self.ENT]
            self.assertEqual(mine[0].get("feed"), "jellyfin")
        finally:
            if before is None:
                f.unlink(missing_ok=True)
            else:
                f.write_bytes(before)

    async def test_names_with_samples(self):
        r = await self.ed.get("/api/attributes", params={"entity": self.ENT})
        got = {a["name"]: a["sample"] for a in await r.json()}
        self.assertEqual(got["episode_name"], "The Signal")
        self.assertEqual(got["episode_number"], "S02E04")
        self.assertEqual(got["added"], "2026-03-09T12:00:00+00:00")
        self.assertEqual(got["detail"], "The Signal · yesterday")


if __name__ == "__main__":
    unittest.main()


class TestConnectInPlace(unittest.IsolatedAsyncioTestCase):
    """New to watch connects Jellyfin in its own step: the address and key are tried before saving."""

    async def asyncSetUp(self):
        from aiohttp import web as aioweb

        async def users(request):
            if request.headers.get("X-Emby-Token") != "good":
                raise aioweb.HTTPUnauthorized()
            return aioweb.json_response([{"Id": "u1", "Name": "bek"}, {"Id": "u2", "Name": "Ada"}])

        async def counts(request):
            return aioweb.json_response({"MovieCount": 12, "SeriesCount": 30, "EpisodeCount": 900})

        app = aioweb.Application()
        app.add_routes([aioweb.get("/Users", users), aioweb.get("/Items/Counts", counts)])
        self.server = TestServer(app)
        await self.server.start_server()
        self.base = str(self.server.make_url("")).rstrip("/")

    async def asyncTearDown(self):
        await self.server.close()

    async def test_a_good_key_lists_whose_unwatched_to_show(self):
        got = await jellyfin.check(self.base, "good")
        self.assertEqual(got, {"ok": True, "titles": 42, "users": [{"id": "u1", "name": "bek"}, {"id": "u2", "name": "Ada"}]})

    async def test_each_failure_says_what_to_do(self):
        self.assertIn("API key", (await jellyfin.check(self.base, "bad"))["error"])
        self.assertIn("web address", (await jellyfin.check("jellyfin.local:8096", "good"))["error"])
        self.assertIn("Couldn't reach", (await jellyfin.check("http://127.0.0.1:9", "good"))["error"])
        self.assertIn("not like Jellyfin", (await jellyfin.check(self.base + "/web", "good"))["error"])

    async def test_through_the_editor_with_a_saved_key(self):
        import config
        import feeds
        support.fresh_data_dir()
        feeds.save(config.DATA_DIR, [{"type": "jellyfin", "name": "watch", "base": self.base, "key": "good"}])
        _, editor = web.make_apps()
        async with TestClient(TestServer(editor)) as ed:
            r = await ed.post("/api/sources/jellyfin/check", json={"base": self.base, "key": feeds.SECRET_MASK, "name": "watch"})
            self.assertTrue((await r.json())["ok"])
            r = await ed.get("/api/sources/jellyfin/suggest")
            self.assertEqual(await r.json(), {"address": ""})          # no Home Assistant here
        support.use_test_data_dir()


class TestJellyHAAddress(unittest.IsolatedAsyncioTestCase):
    async def test_jellyha_gives_the_address_and_nothing_else_does(self):
        class Registry:
            async def ws(self, payload, timeout=10):
                return [{"entity_id": "media_player.living_room", "platform": "cast"},
                        {"entity_id": "media_player.jellyha_user_bek", "platform": "jellyha"}]

        async def states(session, path, **kw):
            return {"attributes": {"config_external_url": "https://jelly.example.org/"}} if "jellyha" in path else {}
        _, editor = web.make_apps()
        with mock.patch.object(runtime, "HASS", Registry()), mock.patch.object(web, "HA_TOKEN", "t"), \
             mock.patch.object(web, "ha_json", states):
            async with TestClient(TestServer(editor)) as ed:
                r = await ed.get("/api/sources/jellyfin/suggest")
                self.assertEqual(await r.json(), {"address": "https://jelly.example.org"})
