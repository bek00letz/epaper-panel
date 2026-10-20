"""One design on several sizes, and adding screens: new, copy, linked."""
import unittest

import support  # noqa: F401
import devices
from layouts_store import load_layouts, sanitize_layouts, save_layouts
from render import arrange, theme as T
from test_devices import fresh_data_dir

BASE, SMALL = "792x272", "400x300"


def page(*els):
    return {"tier": "rotate", "elements": [dict(e) for e in els]}


class TestPlacing(unittest.TestCase):
    def test_automatic_placement_and_back_meet(self):
        el = {"x": 40, "y": 30, "w": 300, "h": 120, "size": 90}
        there = arrange.auto_box(el, BASE, SMALL)
        self.assertLessEqual(there["x"] + there["w"], 400)
        self.assertLessEqual(there["y"] + there["h"], arrange.content_height(SMALL))
        back = arrange.base_box(there, BASE, SMALL)
        for k in ("x", "y", "w", "h", "size"):
            self.assertAlmostEqual(back[k], el[k], delta=2, msg=k)

    def test_ids_are_steady_until_saved_and_copies_get_their_own(self):
        pages = {"a": page({"type": "text"}, {"type": "icon"}), "b": page({"type": "text"})}
        ids = arrange.ensure_ids(pages)
        self.assertEqual([e["id"] for p in ids.values() for e in p["elements"]], ["e0", "e1", "e2"],
                         "unique in the design, so a page can be renamed")
        copied = {"a": page({"type": "text", "id": "x"}), "a_copy": page({"type": "text", "id": "x"})}
        got = [e["id"] for p in arrange.ensure_ids(copied).values() for e in p["elements"]]
        self.assertEqual(got[0], "x")
        self.assertNotEqual(got[1], "x")

    def test_on_its_own_canvas_a_design_is_as_made(self):
        design = {"pages": arrange.ensure_ids({"a": page({"type": "text", "x": 10, "y": 10, "w": 50, "h": 20})})}
        self.assertEqual(arrange.pages_for(design, BASE, BASE), design["pages"])

    def test_elsewhere_unarranged_elements_are_placed_and_marked(self):
        design = {"pages": arrange.ensure_ids({"a": page({"type": "text", "x": 10, "y": 10, "w": 50, "h": 20})})}
        el = arrange.pages_for(design, BASE, SMALL)["a"]["elements"][0]
        self.assertTrue(el[arrange.AUTO])


def every_canvas():
    return sorted({arrange.canvas_key(*T.canvas_dims(deg, d)) for d in T.DISPLAYS for deg in (0, 90)})


class TestPlacingAboveTheFooter(unittest.TestCase):
    """Automatic placement maps the area above one canvas's footer band onto
    the area above the other's: theme.band_height(), not a fixed 36. With 36
    content ran up to 24 px into the footer (2.9" flat to 5.79" flat) or left
    up to 11 px empty above it (anything to the 2.9" flat)."""

    def test_the_whole_content_area_fits_the_other_one_on_every_pair(self):
        for base in every_canvas():
            for target in every_canvas():
                if base == target:
                    continue
                bw, _ = arrange.parse_canvas(base)
                tw, _ = arrange.parse_canvas(target)
                tch = arrange.content_height(target)
                with self.subTest(base=base, target=target):
                    box = arrange.auto_box({"x": 0, "y": 0, "w": bw, "h": arrange.content_height(base)}, base, target)
                    self.assertGreaterEqual(min(box["x"], box["y"]), 0)
                    self.assertLessEqual(box["x"] + box["w"], tw)
                    self.assertLessEqual(box["y"] + box["h"], tch, "never into the footer")
                    fills_width = box["x"] == 0 and box["w"] == tw
                    fills_height = box["y"] == 0 and abs(box["h"] - tch) <= 1
                    self.assertTrue(fills_width or fills_height, box)
                    if fills_width:          # centred in the room above the band
                        self.assertLessEqual(abs(box["y"] - (tch - box["h"] - box["y"])), 1)
                    else:
                        self.assertLessEqual(abs(box["x"] - (tw - box["w"] - box["x"])), 1)

    def test_where_the_fixed_band_was_wrong(self):
        # The 2.9" flat's bottom row of content, on the 5.79" flat: right on its hairline now.
        el = {"x": 0, "y": 0, "w": 296, "h": 103}
        self.assertEqual(arrange.auto_box(el, "296x128", "792x272"), {"x": 51, "y": 0, "w": 690, "h": 240})
        # The 5.79" flat on the 2.9" flat: centred in its 103 px, not in 92.
        el = {"x": 0, "y": 0, "w": 792, "h": 240}
        self.assertEqual(arrange.auto_box(el, "792x272", "296x128"), {"x": 0, "y": 7, "w": 296, "h": 90})
        # The 4.2" flat on the 7.5" flat: down to its hairline at 444, not 451 (7 px into the footer).
        el = {"x": 0, "y": 0, "w": 400, "h": 268}
        self.assertEqual(arrange.auto_box(el, "400x300", "800x480"), {"x": 69, "y": 0, "w": 663, "h": 444})


class TestSavingOnAnotherSize(unittest.TestCase):
    def setUp(self):
        self.design = {"canvas": BASE, "pages": arrange.ensure_ids(
            {"a": page({"type": "text", "value": "hi", "x": 40, "y": 30, "w": 300, "h": 120},
                       {"type": "icon", "icon": "mdi:cat", "x": 400, "y": 30, "w": 100, "h": 100})})}

    def edited(self, change):
        pages = arrange.pages_for(self.design, BASE, SMALL)
        change(pages["a"]["elements"])
        return arrange.merge_pages(self.design, pages, BASE, SMALL)

    def test_moving_it_arranges_it_for_that_size_only(self):
        def move(els):
            els[0].update(x=5, y=6, w=200, h=50)
            els[0].pop(arrange.AUTO)
        out = self.edited(move)
        self.assertEqual(out["pages"]["a"]["elements"][0]["x"], 40, "the design's own canvas is untouched")
        self.assertEqual(out["arrangements"][SMALL]["e0"]["x"], 5)
        self.assertNotIn("e1", out["arrangements"][SMALL], "the other is still placed automatically")

    def test_what_it_shows_changes_everywhere(self):
        out = self.edited(lambda els: els[0].update(value="hello"))
        self.assertEqual(out["pages"]["a"]["elements"][0]["value"], "hello")
        self.assertEqual(out["pages"]["a"]["elements"][0]["x"], 40)

    def test_a_new_element_gets_a_place_on_the_designs_canvas_too(self):
        out = self.edited(lambda els: els.append({"type": "text", "id": "n1", "value": "new", "x": 20, "y": 20, "w": 100, "h": 30}))
        new = out["pages"]["a"]["elements"][2]
        self.assertEqual(new["value"], "new")
        self.assertNotEqual((new["x"], new["w"]), (20, 100), "scaled back to the design's size")
        self.assertEqual(out["arrangements"][SMALL]["n1"]["x"], 20)

    def test_renaming_a_page_keeps_its_arrangement(self):
        def move(els):
            els[0].update(x=5)
            els[0].pop(arrange.AUTO)
        out = self.edited(move)
        renamed = arrange.pages_for(out, BASE, BASE)
        renamed = {"b": renamed["a"]}
        out = arrange.merge_pages(out, renamed, BASE, BASE)
        self.assertEqual(arrange.pages_for(out, BASE, SMALL)["b"]["elements"][0]["x"], 5)

    def test_a_deleted_element_leaves_every_arrangement(self):
        def move(els):
            els[1].pop(arrange.AUTO)
        out = self.edited(move)
        self.assertIn("e1", out["arrangements"][SMALL])
        out = arrange.merge_pages(out, {"a": page(out["pages"]["a"]["elements"][0])}, BASE, BASE)
        self.assertNotIn("arrangements", out)


class TestAddingScreens(unittest.TestCase):
    def setUp(self):
        fresh_data_dir()
        self.first = devices.primary()

    def tearDown(self):
        support.use_test_data_dir()

    def test_every_screen_gets_its_own_id_and_key(self):
        a = devices.add("crowpanel", "A", "crowpanel_420", design=self.first["design"])
        b = devices.add("crowpanel", "B", "crowpanel_579")
        ids = [d["id"] for d in devices.all_devices()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotEqual(a["key"], b["key"])

    def test_linked_screens_share_what_pages_show_but_not_where_things_sit(self):
        kitchen = devices.add("crowpanel", "Kitchen", "crowpanel_420", design=self.first["design"])
        spec = sanitize_layouts(load_layouts(kitchen["id"]))
        name = spec["rotation"][0]
        el = spec["pages"][name]["elements"][0]
        first_box = {k: load_layouts()["pages"][name]["elements"][0][k] for k in ("x", "y")}
        el.update(x=1, y=2)
        el.pop("_auto", None)
        el["hidden_note"] = "shared"
        save_layouts(spec, kitchen["id"])
        mine = load_layouts(kitchen["id"])["pages"][name]["elements"][0]
        theirs = load_layouts()["pages"][name]["elements"][0]
        self.assertEqual((mine["x"], mine["y"]), (1, 2))
        self.assertEqual({k: theirs[k] for k in ("x", "y")}, first_box, "the first screen's layout is its own")
        self.assertEqual(theirs["hidden_note"], "shared", "what it shows is the same everywhere")

    def test_a_copy_is_placed_for_its_screen_then_independent(self):
        desk = devices.add("crowpanel", "Desk", "crowpanel_420", copy_from=self.first["id"])
        self.assertNotEqual(desk["design"], self.first["design"])
        copied = load_layouts(desk["id"])
        self.assertEqual(copied["rotation"], load_layouts()["rotation"])
        self.assertFalse(any("_auto" in e for p in copied["pages"].values() for e in p["elements"]),
                         "a copy is made on its own size: nothing left to arrange")
        copied["rotation"] = copied["rotation"][:1]
        save_layouts(sanitize_layouts(copied), desk["id"])
        self.assertGreater(len(load_layouts()["rotation"]), 1)

    def test_set_up_as_new_starts_from_the_starter_page(self):
        new = devices.add("crowpanel", "Hall", "crowpanel_579")
        self.assertEqual(load_layouts(new["id"])["rotation"], devices.starter_design()["rotation"])

    def test_stop_sharing_keeps_the_pages_as_they_were_placed(self):
        kitchen = devices.add("crowpanel", "Kitchen", "crowpanel_420", design=self.first["design"])
        before = load_layouts(kitchen["id"])
        kitchen = devices.unlink(kitchen["id"])
        self.assertNotEqual(kitchen["design"], self.first["design"])
        after = load_layouts(kitchen["id"])
        strip = lambda v: {n: [{k: e[k] for k in ("x", "y", "w", "h") if k in e} for e in p["elements"]]
                           for n, p in v["pages"].items()}
        self.assertEqual(strip(after), strip(before))

    def test_taking_a_screen_out_can_be_undone(self):
        kitchen = devices.add("crowpanel", "Kitchen", "crowpanel_420", design=self.first["design"])
        devices.remove(kitchen["id"])
        self.assertEqual(len(devices.all_devices()), 1)
        devices.restore(kitchen["id"])
        self.assertEqual(devices.get(kitchen["id"])["key"], kitchen["key"], "back with the same key")
        with self.assertRaises(ValueError):
            devices.restore(kitchen["id"])
        devices.remove(kitchen["id"])
        with self.assertRaises(ValueError):
            devices.remove(self.first["id"])

    def test_a_new_model_starts_from_an_automatic_fit(self):
        spec = load_layouts()
        pages = devices.place(spec, self.first["id"], "crowpanel_420", 0)
        el = next(iter(pages.values()))["elements"][0]
        self.assertTrue(el.get("_auto"))
        self.assertLessEqual(el["x"] + el["w"], 400)
