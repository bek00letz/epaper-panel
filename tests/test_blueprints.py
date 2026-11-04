"""The blueprints the add-on publishes. The remote blueprint (blueprints/remote.yaml) calls the
panel's own ESPHome actions by name, so every action it can call must be one the panel's
firmware offers (firmware/panel.yaml): rename one there and this fails, not someone's remote.

There's no YAML library in the test environment, so these read the files as text; the
blueprint was also loaded by Home Assistant's YAML rules when it was written."""
import re
import unittest

import support

BLUEPRINTS = support.APP / "blueprints"
FIRMWARE = (support.APP / "firmware" / "panel.yaml").read_text()
FIRMWARE_ACTIONS = set(re.findall(r"^\s*- action: (\w+)\s*$", FIRMWARE, flags=re.M))


class TestRemoteBlueprint(unittest.TestCase):
    def setUp(self):
        self.text = (BLUEPRINTS / "remote.yaml").read_text()

    def test_every_action_it_can_call_is_one_the_panel_has(self):
        choices = set(re.findall(r"^\s*value: (\w+)\s*$", self.text, flags=re.M)) - {"none"}
        called = set(re.findall(r'action: "\{\{ actions \}\}_(\w+)"', self.text))
        self.assertEqual(choices, {"mode_toggle", "lock_toggle", "refresh_now"})
        self.assertEqual(called, {"page_step"})
        self.assertLessEqual(choices | called, FIRMWARE_ACTIONS)

    def test_both_button_choices_offer_the_same_things_and_default_to_ones_offered(self):
        click = self.text.split("    click:\n", 1)[1].split("    long_press:\n", 1)[0]
        press = self.text.split("    long_press:\n", 1)[1].split("\nmode:", 1)[0]
        values = lambda block: re.findall(r"value: (\w+)", block)          # noqa: E731
        self.assertEqual(values(click), values(press))
        self.assertIn("default: mode_toggle", click)
        self.assertIn("default: lock_toggle", press)

    def test_it_names_the_panel_the_way_esphome_names_its_actions(self):
        self.assertIn("default: crowpanel_epaper", self.text)                 # the add-on's own default device
        self.assertIn("\"esphome.{{ panel | trim | lower | replace('-', '_') }}\"", self.text)

    def test_turns_wait_their_turn_and_a_restart_isnt_a_press(self):
        self.assertIn("mode: queued", self.text)
        self.assertEqual(self.text.count("not_from: unavailable"), 3)
        self.assertEqual(self.text.count("not_to: [unavailable, unknown]"), 3)

    def test_its_source_link_is_where_it_lives(self):
        self.assertIn("source_url: https://github.com/bek00letz/epaper-panel/blob/main/addon/app/blueprints/remote.yaml", self.text)


class TestReadmeOffersIt(unittest.TestCase):
    def test_the_readme_has_its_import_button(self):
        readme = (support.APP.parent.parent / "README.md").read_text()
        self.assertIn("blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fbek00letz%2Fepaper-panel%2Fblob%2Fmain%2Faddon%2Fapp%2Fblueprints%2Fremote.yaml", readme)


if __name__ == "__main__":
    unittest.main()
