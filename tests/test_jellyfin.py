"""Jellyfin: `detail` stays as it was, and its parts are there on their own."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

import support  # noqa: F401  (puts the add-on on the path)
import runtime
import web
from feeds import jellyfin
from render import binding, subitems

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)


def at(days_ago):
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


EPISODE = {"Id": "e1", "Type": "Episode", "Name": "The Signal", "SeriesName": "Northern Lights",
           "ParentIndexNumber": 2, "IndexNumber": 4, "DateCreated": at(1)}
SERIES = {"Id": "s1", "Type": "Series", "Name": "Harbour Town", "ChildCount": 2,
          "DateCreated": at(3)}
FILM = {"Id": "m1", "Type": "Movie", "Name": "Paper Moon", "DateCreated": at(0)}


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

    async def test_names_with_samples(self):
        r = await self.ed.get("/api/attributes", params={"entity": self.ENT})
        got = {a["name"]: a["sample"] for a in await r.json()}
        self.assertEqual(got["episode_name"], "The Signal")
        self.assertEqual(got["episode_number"], "S02E04")
        self.assertEqual(got["added"], "2026-03-09T12:00:00+00:00")
        self.assertEqual(got["detail"], "The Signal · yesterday")


if __name__ == "__main__":
    unittest.main()
