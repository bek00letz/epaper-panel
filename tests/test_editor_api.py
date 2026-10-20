"""The editor's API: version check on saves, drafts, presets, and the panel's own settings."""
import asyncio
import json
import unittest

from aiohttp.test_utils import TestClient, TestServer

import support
import frames
import layouts_store
import panel_link
import web
from test_panel_link_and_entities import PANEL_REGISTRY, FakeHass


class EditorClient(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # A data folder of its own: saves here land in devices.json and more,
        # so backing up a list of files would always miss one.
        support.fresh_data_dir()
        await frames.refresh_frames(None)
        _, editor = web.make_apps()
        self.ed = TestClient(TestServer(editor))
        await self.ed.start_server()

    async def asyncTearDown(self):
        await self.ed.close()
        support.use_test_data_dir()

    async def spec_and_tag(self):
        r = await self.ed.get("/api/layouts")
        return await r.json(), r.headers["ETag"]


class TestVersionCheck(EditorClient):
    async def test_get_carries_a_version(self):
        spec, tag = await self.spec_and_tag()
        self.assertIn("pages", spec)
        self.assertRegex(tag, r'^"[0-9a-f]{16}"$')

    async def test_save_with_the_current_version_goes_through(self):
        spec, tag = await self.spec_and_tag()
        spec["rotate_seconds"] = 45
        r = await self.ed.put("/api/layouts", json=spec, headers={"If-Match": tag})
        self.assertEqual(r.status, 200)
        body = await r.json()
        self.assertNotEqual(f'"{body["etag"]}"', tag, "a save changes the version")
        self.assertEqual(r.headers["ETag"], f'"{body["etag"]}"')

    async def test_second_window_gets_409_and_what_is_there_now(self):
        spec, tag = await self.spec_and_tag()
        first = json.loads(json.dumps(spec))
        first["rotate_seconds"] = 45
        self.assertEqual((await self.ed.put("/api/layouts", json=first, headers={"If-Match": tag})).status, 200)

        second = json.loads(json.dumps(spec))
        second["rotate_seconds"] = 120
        r = await self.ed.put("/api/layouts", json=second, headers={"If-Match": tag})
        self.assertEqual(r.status, 409)
        body = await r.json()
        self.assertEqual(body["current"]["rotate_seconds"], 45, "the 409 carries the other window's save")
        self.assertEqual(f'"{body["etag"]}"', r.headers["ETag"])
        self.assertEqual(layouts_store.load_layouts()["rotate_seconds"], 45, "nothing was overwritten")

    async def test_save_without_if_match_still_works(self):
        spec, _ = await self.spec_and_tag()
        spec["rotate_seconds"] = 60
        r = await self.ed.put("/api/layouts", json=spec)
        self.assertEqual(r.status, 200)
        self.assertEqual(layouts_store.load_layouts()["rotate_seconds"], 60)

    async def test_version_ignores_file_formatting(self):
        spec, tag = await self.spec_and_tag()
        self.assertEqual(f'"{layouts_store.layouts_etag(json.loads(json.dumps(spec, indent=4)))}"', tag)


class TestDrafts(EditorClient):
    async def test_draft_saves_without_going_live(self):
        spec, tag = await self.spec_and_tag()
        edited = json.loads(json.dumps(spec))
        edited["rotate_seconds"] = 15
        r = await self.ed.put("/api/draft", json={"spec": edited, "base": spec, "base_etag": tag.strip('"')},
                              headers={"If-Match": "0"})
        self.assertEqual(r.status, 200)
        self.assertEqual((await r.json())["version"], 1)
        self.assertNotEqual(layouts_store.load_layouts().get("rotate_seconds"), 15, "a draft never reaches the panel")
        got = await (await self.ed.get("/api/draft")).json()
        self.assertEqual(got["draft"]["spec"]["rotate_seconds"], 15)
        self.assertEqual(got["draft"]["base_etag"], tag.strip('"'))
        self.assertEqual(f'"{got["etag"]}"', tag)

    async def test_stale_draft_version_gets_409_with_both_copies(self):
        spec, tag = await self.spec_and_tag()
        put = lambda v, ver: self.ed.put("/api/draft", json={"spec": dict(spec, rotate_seconds=v), "base": spec,
                                                             "base_etag": tag.strip('"')}, headers={"If-Match": ver})
        self.assertEqual((await put(15, "0")).status, 200)
        self.assertEqual((await put(20, "1")).status, 200)
        r = await put(25, "1")                            # another window, one save behind
        self.assertEqual(r.status, 409)
        body = await r.json()
        self.assertEqual(body["draft"]["spec"]["rotate_seconds"], 20)
        self.assertIn("pages", body["live"])
        self.assertEqual(f'"{body["etag"]}"', tag)

    async def test_sending_clears_the_draft(self):
        spec, tag = await self.spec_and_tag()
        await self.ed.put("/api/draft", json={"spec": spec, "base": spec, "base_etag": tag.strip('"')})
        self.assertIsNotNone(layouts_store.load_draft())
        await self.ed.put("/api/layouts", json=spec, headers={"If-Match": tag})
        self.assertIsNone(layouts_store.load_draft())
        got = await (await self.ed.get("/api/draft")).json()
        self.assertIsNone(got["draft"])

    async def test_draft_can_be_thrown_away(self):
        spec, tag = await self.spec_and_tag()
        await self.ed.put("/api/draft", json={"spec": spec, "base": spec, "base_etag": tag.strip('"')})
        r = await self.ed.delete("/api/draft")
        self.assertEqual(r.status, 200)
        self.assertIsNone(layouts_store.load_draft())

    async def test_draft_is_checked_like_a_save(self):
        r = await self.ed.put("/api/draft", json={"spec": {"pages": "nope"}})
        self.assertEqual(r.status, 400)


class TestEditorFiles(EditorClient):
    async def test_editor_serves_its_fonts(self):
        r = await self.ed.get("/fonts/Lato-Regular.ttf")
        self.assertEqual(r.status, 200)
        self.assertEqual((await self.ed.get("/fonts/..%2Fweb.py")).status, 404)

    async def test_classic_editor_stays_reachable(self):
        new = await (await self.ed.get("/")).text()
        old = await (await self.ed.get("/?classic=1")).text()
        self.assertIn("<html", old)
        self.assertFalse(new == old, "the new editor is served by default, the classic one on request")


class TestPresets(unittest.TestCase):
    def test_presets_saved_by_the_editor_survive(self):
        spec = {"pages": {}, "custom_presets": [
            {"id": "mine", "title": "My solar page", "desc": "", "elements": [{"type": "text"}]},
            {"id": "old", "name": "Saved by 0.8", "elements": []},
            {"title": "No elements"}]}
        presets = layouts_store.sanitize_layouts(spec)["custom_presets"]
        self.assertEqual([p["title"] for p in presets], ["My solar page", "Saved by 0.8"])
        self.assertEqual(presets[0]["name"], "My solar page", "older readers still find a name")


DEVICE_REGISTRY = PANEL_REGISTRY + [
    {"entity_id": "switch.e_paper_panel_sleep", "platform": "esphome", "device_id": "dev1",
     "unique_id": "44:1B:F6:D1:45:04/0/switch/Sleep"},
    {"entity_id": "number.e_paper_panel_ghost_clear_after", "platform": "esphome", "device_id": "dev1",
     "unique_id": "44:1B:F6:D1:45:04/0/number/Ghost clear after"},
    {"entity_id": "select.e_paper_panel_ghost_clearing", "platform": "esphome", "device_id": "dev1",
     "unique_id": "44:1B:F6:D1:45:04/0/select/Ghost clearing"},
    {"entity_id": "button.e_paper_panel_clear_ghosting", "platform": "esphome", "device_id": "dev1",
     "unique_id": "44:1B:F6:D1:45:04/0/button/Clear ghosting"},
]


class DeviceHass(FakeHass):
    async def rest(self, method, path, json=None, timeout=15):
        if method == "POST" and path.split("/")[2] in ("switch", "number", "select", "button"):
            self.calls.append((method, path, json))
            return []
        return await super().rest(method, path, json, timeout)


class TestPanelDeviceSettings(unittest.TestCase):
    def link(self, registry=DEVICE_REGISTRY):
        hass = DeviceHass(registry=registry)
        hass.states = {
            "switch.e_paper_panel_sleep": {"state": "off"},
            "number.e_paper_panel_ghost_clear_after": {"state": "10.0"},
            "select.e_paper_panel_ghost_clearing": {"state": "On automatic changes",
                                                     "attributes": {"options": ["On automatic changes", "Every Nth refresh"]}},
        }
        return panel_link.PanelLink(hass, lambda: ""), hass

    def test_reads_the_panels_settings(self):
        link, _ = self.link()
        got = asyncio.run(link.device_settings())
        self.assertTrue(got["available"])
        self.assertIs(got["sleep"], False)
        self.assertEqual(got["ghost_after"], 10)
        self.assertEqual(got["ghost_mode"], "On automatic changes")
        self.assertEqual(len(got["ghost_modes"]), 2)
        self.assertTrue(got["can_clear"])

    def test_changes_go_through_the_right_actions(self):
        link, hass = self.link()
        for key, value in (("sleep", True), ("ghost_after", 99), ("ghost_mode", "Every Nth refresh"), ("clear_ghosting", True)):
            ok, err = asyncio.run(link.set_device_setting(key, value))
            self.assertTrue(ok, err)
        posted = [(p, j) for m, p, j in hass.calls if m == "POST"]
        self.assertEqual(posted, [
            ("/services/switch/turn_on", {"entity_id": "switch.e_paper_panel_sleep"}),
            ("/services/number/set_value", {"entity_id": "number.e_paper_panel_ghost_clear_after", "value": 60}),
            ("/services/select/select_option", {"entity_id": "select.e_paper_panel_ghost_clearing", "option": "Every Nth refresh"}),
            ("/services/button/press", {"entity_id": "button.e_paper_panel_clear_ghosting"}),
        ])

    def test_older_firmware_says_so_instead_of_guessing(self):
        link, _ = self.link(registry=PANEL_REGISTRY)
        got = asyncio.run(link.device_settings())
        self.assertIsNone(got["sleep"])
        self.assertFalse(got["can_clear"])
        ok, err = asyncio.run(link.set_device_setting("sleep", True))
        self.assertFalse(ok)
        self.assertIn("firmware", err)

    def test_only_known_settings(self):
        link, _ = self.link()
        ok, _ = asyncio.run(link.set_device_setting("refresh", 5))
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
