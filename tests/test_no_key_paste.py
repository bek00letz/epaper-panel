"""Nobody pastes a key (0.22): Home Assistant sets a panel's encryption key when it adds it.

* The panel's file has no key under `api:`, a 15-minute window for Home Assistant to
  set one (`provisioning:`), and the panel's own update key under `ota:`, which ESPHome
  2026.10 needs to refuse updates from anyone else.
* The add-on makes one update key per panel and keeps it in one place, the panel's
  setup. It never reaches the browser, the shown file or the secrets.yaml lines.
* A panel set up before keeps the key it runs as its update key, so an Install from
  ESPHome is still accepted.
* The editor never asks to paste a key, and the add-on needs Home Assistant 2026.8.
* A panel says its MAC when it downloads, which is how the add-on finds it.
"""
import base64
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import support  # noqa: E402
from aiohttp.test_utils import make_mocked_request  # noqa: E402

import config  # noqa: E402
import devices  # noqa: E402
import firmware_gen  # noqa: E402
import frames  # noqa: E402
import panel_setup  # noqa: E402
import web  # noqa: E402
from kinds import crowpanel  # noqa: E402
from render import theme as T  # noqa: E402

OLD_KEY = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="


def block(text: str, name: str) -> str:
    """A top-level YAML block, up to the next blank line."""
    return text.split(f"\n{name}:\n", 1)[1].split("\n\n", 1)[0]


class TestTheFile(unittest.TestCase):
    def render(self, **kw):
        return firmware_gen.render(disp=T.get_display("crowpanel_579"), version="1.2.3", device_name="kitchen",
                                   frames_url='"http://x/frames.epf"', ota_key=f'"{OLD_KEY}"', wifi_ssid='"a"',
                                   wifi_password='"b"', interval_min=1, orientation=0, **kw)

    def test_home_assistant_sets_the_key_in_a_window(self):
        text = self.render()
        api = text.split("\napi:\n", 1)[1].split("\n  actions:", 1)[0]
        self.assertIn("  encryption: {}", api)
        self.assertNotIn("key", api.split("encryption", 1)[1], "no key for Home Assistant's connection")
        self.assertEqual(block(text, "provisioning").strip(), "timeout: 15min")

    def test_updates_need_the_panels_own_key(self):
        ota = block(self.render(), "ota")
        self.assertIn(f'    encryption:\n      key: "{OLD_KEY}"', ota)
        self.assertNotIn("password", ota, "no password route: ESPHome drops it")
        self.assertEqual(self.render().count(OLD_KEY), 1, "the key is written once, for updates")

    def test_the_reference_takes_its_key_from_secrets(self):
        ref = (ROOT / "esphome" / "crowpanel-epaper.yaml").read_text()
        self.assertIn("      key: !secret api_encryption_key", block(ref, "ota"))
        self.assertNotIn("key", ref.split("\napi:\n", 1)[1].split("\n  actions:", 1)[0].split("encryption", 1)[1])


class TestOneUpdateKeyPerPanel(unittest.TestCase):
    def setUp(self):
        support.fresh_data_dir()

    def tearDown(self):
        support.use_test_data_dir()

    def test_made_once_kept_and_never_shown(self):
        a = devices.add("crowpanel", "Kitchen", "crowpanel_579")
        b = devices.add("crowpanel", "Hall", "crowpanel_579")
        ka = panel_setup.load_panel_setup(a)["ota_key"]
        kb = panel_setup.load_panel_setup(b)["ota_key"]
        self.assertNotEqual(ka, kb, "every panel has its own")
        self.assertEqual(len(base64.b64decode(ka)), 32)
        dev = devices.get(a["id"])
        cfg = panel_setup.load_panel_setup(dev)
        self.assertEqual(cfg["ota_key"], ka, "kept, not made again")
        self.assertEqual(dev["setup"]["ota_key"], ka, "one place: the panel's setup")
        text, secrets = panel_setup.generate_esphome_yaml(cfg, dev)
        self.assertIn(f'key: "{ka}"', block(text, "ota"))
        self.assertNotIn(ka, secrets)
        shown_cfg = web._masked_setup(cfg, dev)
        shown, shown_secrets = panel_setup.generate_esphome_yaml(shown_cfg, dev)
        self.assertNotIn(ka, json.dumps(shown_cfg) + shown + shown_secrets, "the browser never gets it")

    def test_a_panel_from_before_keeps_the_key_it_runs(self):
        dev = devices.add("crowpanel", "Kitchen", "crowpanel_579")
        devices.update(dev["id"], setup={"device_name": "kitchen", "api_encryption_key": OLD_KEY})
        cfg = panel_setup.load_panel_setup(devices.get(dev["id"]))
        self.assertEqual(cfg["ota_key"], OLD_KEY)
        self.assertNotIn("api_encryption_key", cfg)
        self.assertNotIn("api_encryption_key", devices.get(dev["id"])["setup"], "moved, not copied")
        text, _ = panel_setup.generate_esphome_yaml(cfg, devices.get(dev["id"]))
        self.assertIn(f'key: "{OLD_KEY}"', block(text, "ota"))

    def test_a_key_kept_in_secrets_stays_there(self):
        dev = devices.add("crowpanel", "Kitchen", "crowpanel_579")
        cfg = {**panel_setup.load_panel_setup(dev), "use_secrets": True}
        with mock.patch.object(panel_setup, "_inspect_existing_secrets", return_value={"api_encryption_key"}):
            text, secrets = panel_setup.generate_esphome_yaml(cfg, devices.get(dev["id"]))
        self.assertIn("key: !secret api_encryption_key", block(text, "ota"))
        self.assertNotIn("api_encryption_key", secrets, "the lines to copy never hold a key")

    def test_the_setup_form_takes_no_key(self):
        source = (ROOT / "addon" / "app" / "web.py").read_text()
        self.assertNotIn("regenerate_keys", source)
        self.assertNotIn("api_encryption_key", source)


class TestNoPasteAnywhere(unittest.TestCase):
    def test_the_editor_never_asks_for_a_key(self):
        app = ROOT / "addon" / "app" / "web" / "app"
        text = "\n".join(p.read_text() for p in app.glob("*.js"))
        for words in ("api_encryption_key", "paste the encryption key", "Encryption key", "Make a new key", "ota_key"):
            self.assertNotIn(words, text)

    def test_the_readme_never_asks_for_a_key(self):
        readme = (ROOT / "README.md").read_text()
        self.assertNotRegex(readme, r"(?i)paste the (encryption )?key")

    def test_it_needs_home_assistant_2026_8(self):
        found = re.search(r'^homeassistant:\s*"?(\d+)\.(\d+)\.(\d+)"?$', (ROOT / "addon" / "config.yaml").read_text(), re.M)
        self.assertIsNotNone(found)
        self.assertGreaterEqual(tuple(int(x) for x in found.groups()), (2026, 8, 0))


class TestThePanelSaysWhichItIs(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        support.use_test_data_dir()
        await frames.refresh_frames(None)

    async def test_its_mac_is_kept_and_a_bad_one_ignored(self):
        dev = devices.get("1")
        devices.set_state(dev["id"], mac=None, ip=None)
        await crowpanel.frames_epf(make_mocked_request("GET", "/frames.epf?cap=1048576&mac=zz"))
        self.assertIsNone(devices.state(dev["id"]).get("mac"))
        await crowpanel.frames_epf(make_mocked_request("GET", "/frames.epf?cap=1048576&mac=00005e005301"))
        self.assertEqual(devices.state(dev["id"])["mac"], "00:00:5e:00:53:01")

    def test_the_firmware_says_it_on_every_download(self):
        client = (ROOT / "components" / "epf" / "epf_client.h").read_text()
        self.assertIn('"&mac=" +', client)
        self.assertIn("get_mac_address_raw", client)


if __name__ == "__main__":
    unittest.main()
