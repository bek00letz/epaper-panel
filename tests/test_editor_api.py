"""The editor's API: version check on saves, drafts, presets, and the panel's own settings."""
import asyncio
import json
import unittest
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

import support
import frames
import layouts_store
import panel_link
import runtime
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
        spec.setdefault("quiet_hours", {})["start"] = "21:45"
        r = await self.ed.put("/api/layouts", json=spec, headers={"If-Match": tag})
        self.assertEqual(r.status, 200)
        body = await r.json()
        self.assertNotEqual(f'"{body["etag"]}"', tag, "a save changes the version")
        self.assertEqual(r.headers["ETag"], f'"{body["etag"]}"')

    async def test_second_window_gets_409_and_what_is_there_now(self):
        spec, tag = await self.spec_and_tag()
        first = json.loads(json.dumps(spec))
        first.setdefault("quiet_hours", {})["start"] = "21:45"
        self.assertEqual((await self.ed.put("/api/layouts", json=first, headers={"If-Match": tag})).status, 200)

        second = json.loads(json.dumps(spec))
        second.setdefault("quiet_hours", {})["start"] = "22:00"
        r = await self.ed.put("/api/layouts", json=second, headers={"If-Match": tag})
        self.assertEqual(r.status, 409)
        body = await r.json()
        self.assertEqual(body["current"]["quiet_hours"]["start"], "21:45", "the 409 carries the other window's save")
        self.assertEqual(f'"{body["etag"]}"', r.headers["ETag"])
        self.assertEqual(layouts_store.load_layouts()["quiet_hours"]["start"], "21:45", "nothing was overwritten")

    async def test_save_without_if_match_still_works(self):
        spec, _ = await self.spec_and_tag()
        spec.setdefault("quiet_hours", {})["start"] = "21:00"
        r = await self.ed.put("/api/layouts", json=spec)
        self.assertEqual(r.status, 200)
        self.assertEqual(layouts_store.load_layouts()["quiet_hours"]["start"], "21:00")

    async def test_a_size_from_another_kind_of_screen_is_refused(self):
        # A CrowPanel given a TRMNL's size saved fine, then could never be drawn again.
        spec, tag = await self.spec_and_tag()
        spec["display"] = "trmnl_og"
        r = await self.ed.put("/api/layouts", json=spec, headers={"If-Match": tag})
        self.assertEqual(r.status, 400)
        self.assertIn("CrowPanel sizes", await r.text())
        await frames.refresh_frames(None)
        self.assertIsNone(support.first_frames().error, "it still draws")
        spec.pop("display")
        spec.setdefault("quiet_hours", {})["start"] = "20:50"
        r = await self.ed.put("/api/layouts", json=spec, headers={"If-Match": tag})
        self.assertEqual(r.status, 200, "no size: it keeps its own")
        self.assertEqual(layouts_store.load_layouts()["display"], "crowpanel_579")

    async def test_a_body_that_isnt_json_is_the_senders_mistake(self):
        for method, path in (("put", "/api/layouts"), ("put", "/api/draft"), ("post", "/api/panel-setup"),
                             ("post", "/api/preview"), ("put", "/api/sources"), ("post", "/api/sources/test"),
                             ("post", "/api/panel-device"), ("post", "/api/devices")):
            for body in (b"{nope", b""):
                r = await getattr(self.ed, method)(path, data=body, headers={"Content-Type": "application/json"})
                self.assertEqual(r.status, 400, f"{method.upper()} {path} with {body!r}")

    async def test_version_ignores_file_formatting(self):
        spec, tag = await self.spec_and_tag()
        self.assertEqual(f'"{layouts_store.layouts_etag(json.loads(json.dumps(spec, indent=4)))}"', tag)


class ConfigHass:
    """Home Assistant's /api/config, with or without an internal URL."""

    def __init__(self, internal_url):
        self.internal_url = internal_url

    async def rest(self, method, path, json=None, timeout=15):
        assert (method, path) == ("GET", "/config")
        return {"internal_url": self.internal_url}


class TestTheirHomeAddress(EditorClient):
    """Audit #9: opened through a tunnel, Panel setup took the browser's address, and the panel
    was told to fetch from the tunnel's name over plain HTTP. It's Home Assistant's own now."""

    async def setup_through_a_tunnel(self, internal_url):
        with mock.patch.object(runtime, "HASS", ConfigHass(internal_url)):
            r = await self.ed.get("/api/panel-setup", headers={"X-Forwarded-Host": "ha.example-tunnel.com",
                                                                "Host": "ha.example-tunnel.com"})
        self.assertEqual(r.status, 200)
        return await r.json()

    async def test_its_internal_url(self):
        got = await self.setup_through_a_tunnel("http://192.168.1.5:8123")
        self.assertEqual(got["config"]["ha_host"], "192.168.1.5")
        self.assertNotIn("example-tunnel", got["yaml"])

    async def test_never_the_browsers(self):
        got = await self.setup_through_a_tunnel(None)
        self.assertEqual(got["config"]["ha_host"], "homeassistant.local", "no internal URL, no Supervisor: the usual name")
        self.assertNotIn("example-tunnel", got["yaml"])

    async def test_a_blank_address_goes_back_to_it(self):
        with mock.patch.object(runtime, "HASS", ConfigHass("http://ha.lan:8123")):
            r = await self.ed.post("/api/panel-setup", json={"ha_host": "  "})
        self.assertEqual((await r.json())["config"]["ha_host"], "ha.lan")


class TestDrafts(EditorClient):
    async def test_draft_saves_without_going_live(self):
        spec, tag = await self.spec_and_tag()
        edited = json.loads(json.dumps(spec))
        edited.setdefault("quiet_hours", {})["start"] = "20:15"
        r = await self.ed.put("/api/draft", json={"spec": edited, "base": spec, "base_etag": tag.strip('"')},
                              headers={"If-Match": "0"})
        self.assertEqual(r.status, 200)
        self.assertEqual((await r.json())["version"], 1)
        self.assertNotEqual(layouts_store.load_layouts().get("quiet_hours", {}).get("start"), "20:15", "a draft never reaches the panel")
        got = await (await self.ed.get("/api/draft")).json()
        self.assertEqual(got["draft"]["spec"]["quiet_hours"]["start"], "20:15")
        self.assertEqual(got["draft"]["base_etag"], tag.strip('"'))
        self.assertEqual(f'"{got["etag"]}"', tag)

    async def test_stale_draft_version_gets_409_with_both_copies(self):
        spec, tag = await self.spec_and_tag()
        put = lambda v, ver: self.ed.put("/api/draft", json={"spec": dict(spec, location_presets=[{"label": v, "lat": 1, "lon": 2}]), "base": spec,
                                                             "base_etag": tag.strip('"')}, headers={"If-Match": ver})
        self.assertEqual((await put("one", "0")).status, 200)
        self.assertEqual((await put("two", "1")).status, 200)
        r = await put("three", "1")                            # another window, one save behind
        self.assertEqual(r.status, 409)
        body = await r.json()
        self.assertEqual(body["draft"]["spec"]["location_presets"][0]["label"], "two")
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

    async def test_one_editor(self):
        # The 0.9 editor (?classic=1) was removed in 0.13; an old bookmark opens this one.
        new = await (await self.ed.get("/")).text()
        self.assertIn("<html", new)
        self.assertEqual(await (await self.ed.get("/?classic=1")).text(), new)


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
