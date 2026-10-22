"""Icons from Home Assistant: the outlines the panel draws (render/vector), the sets it has
(render/icons: shipped, copied from Home Assistant, custom), the copy itself (iconsets), the
editor's routes and its picker (web/app/glyphs.js under node)."""
import asyncio
import gzip
import io
import json
import shutil
import subprocess
import time
import unittest
import urllib.parse
import zipfile
from pathlib import Path
from unittest import mock

import support
import config
import hass as hass_api
import health
import iconsets
from render import icons, layout, vector
from render import theme as T
from test_editor_api import EditorClient

GLYPHS_JS = support.APP / "web" / "app" / "glyphs.js"
SQUARE = "M2,2H22V22H2Z"
CAT_OUTLINE = "M12,4C9,4 4,7 4,13C4,18 8,21 12,21C16,21 20,18 20,13C20,7 15,4 12,4M12,6A3,3 0 0,1 15,9A3,3 0 0,1 12,12A3,3 0 0,1 9,9A3,3 0 0,1 12,6Z"


def ink(img) -> int:
    """Black pixels in a page or mask (a page: 0 is ink; a mask: 255 is)."""
    return img.convert("L").histogram()[0]


def mask_ink(m) -> int:
    return sum(m.convert("L").histogram()[128:])


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            import aiohttp
            raise aiohttp.ClientResponseError(None, (), status=self.status)

    async def json(self, content_type=None):
        return self.body


class FakeFrontend:
    """Home Assistant's frontend files: /static/mdi/iconMetadata.json and its chunks."""

    def __init__(self, version="7.5.0", icons_by_part=None, broken=(), hang=None, down=False):
        self.version, self.broken, self.hang, self.down = version, set(broken), hang, down
        # Home Assistant's set: everything shipped, and one icon more.
        self.parts = icons_by_part or [dict(icons.shipped()["icons"]), {"cat-outline": CAT_OUTLINE}]
        self.asked = []

    def get(self, url, **kw):
        self.asked.append(url)
        if self.down:
            import aiohttp
            raise aiohttp.ClientConnectionError("Cannot connect to host homeassistant:8123")
        path = url.split("8123", 1)[1]
        if self.hang is not None:
            return self._hanging()
        if path == "/static/mdi/iconMetadata.json":
            return FakeResponse({"version": self.version, "parts": [{"file": f"p{i}"} for i in range(len(self.parts))]})
        i = int(path.rsplit("/p", 1)[1].removesuffix(".json"))
        return FakeResponse(["not", "icons"] if i in self.broken else self.parts[i])

    def _hanging(self):
        hang = self.hang

        class Hanging:
            async def __aenter__(self):
                await hang.wait()
                raise asyncio.TimeoutError()

            async def __aexit__(self, *a):
                return False
        return Hanging()


class FakeHass(hass_api.Hass):
    """The add-on's own Home Assistant client, with its calls answered here."""

    def __init__(self, version="2026.11.0", active=None):
        super().__init__("http://supervisor/core", "token", lambda: object())
        self.version, self.active, self.asked = version, active, []

    async def rest(self, method, path, json=None, timeout=15):
        assert (method, path) == ("GET", "/config")
        return {"version": self.version}


class IconTest(unittest.TestCase):
    """A data folder of its own, and the sets as shipped."""

    def setUp(self):
        support.fresh_data_dir()
        self._sets = dict(icons._sets)
        icons._sets.clear()

    def tearDown(self):
        icons._sets.clear()
        icons._sets.update(self._sets)
        support.use_test_data_dir()


class TestOutlines(unittest.TestCase):
    def test_every_command_reads(self):
        d = "M2 2h4v4H2zM8,8 l2,0 0,2 -2,0z m4,0 c1,0 2,1 2,2 s-1,2 -2,2 q-1,0 -1,-1 t1,-1 Z M3 20a2 2 0 1 0 4 0a2 2 0 01 -4 0"
        segs = vector.segments(d)
        self.assertTrue(segs and all(s[0] in "MLCZ" for s in segs))
        self.assertTrue(vector.check(d))
        # arc flags run together ("01") read as two flags
        self.assertEqual(vector.segments("M0 0a1 1 0 012 0"), vector.segments("M0 0a1 1 0 0 1 2 0"))

    def test_a_hole_is_a_subpath_the_other_way_round(self):
        hole = vector.mask("M2,2H22V22H2ZM8,8V16H16V8Z", 24)      # inner square wound the other way
        same = vector.mask("M2,2H22V22H2ZM8,8H16V16H8Z", 24)      # the same way: no hole (non-zero)
        self.assertLess(hole.getpixel((12, 12)), 128)
        self.assertGreaterEqual(same.getpixel((12, 12)), 128)
        odd = vector.mask({"e": "M2,2H22V22H2ZM8,8H16V16H8Z"}, 24)  # even-odd: a hole either way
        self.assertLess(odd.getpixel((12, 12)), 128)
        self.assertGreaterEqual(odd.getpixel((4, 4)), 128)

    def test_a_view_box_is_fitted_and_centred(self):
        wide = vector.mask({"d": "M0,0H48V24H0Z", "v": [0, 0, 48, 24]}, 48)
        self.assertGreaterEqual(wide.getpixel((24, 24)), 128)
        self.assertLess(wide.getpixel((24, 4)), 128, "a 2:1 view box sits in the middle of the square")

    def test_a_stroke_draws_a_line(self):
        m = vector.mask({"s": [["M4,12L20,12", 2]]}, 24)
        self.assertGreaterEqual(m.getpixel((12, 12)), 128)
        self.assertLess(m.getpixel((12, 4)), 128)

    def test_normalize_keeps_the_shape(self):
        d = "M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2Z"
        n = vector.normalize(d)
        self.assertNotRegex(n, r"[AaSsQqTtHhVv]")
        self.assertEqual(vector.cut(d, 48).tobytes(), vector.cut(n, 48).tobytes())
        moved = vector.normalize(d, (0.5, 0, 0, 0.5, 6, 6))           # half size, in the middle
        self.assertLess(mask_ink(vector.cut(moved, 48)), mask_ink(vector.cut(d, 48)) / 3)

    def test_bad_paths_are_refused_not_drawn(self):
        for bad in ("", "12 12", "M1", "Mx,y", {"d": SQUARE, "v": [0, 0, 0, 24]}, 42):
            self.assertFalse(vector.check(bad), repr(bad))

    def test_a_crafted_outline_cant_make_a_render_slow(self):
        # Each refused when its set is copied, and drawn as nothing (quickly) if it got through anyway.
        tiny = "M1 1h.1v.1h-.1z"
        crafted = {
            "too long": "M0 0" + " L1 1" * 200_000,
            "too many commands": "M0 0" + "L1 1L2 2" * 20_000,
            "too many shapes": tiny * 7_000,
            "covering too much": "M0 0H24V24H0Z" * 40,
            "even-odd, too much": {"e": "M0 0H24V24H0Z" * 40},
            "strokes, too much": {"s": [["M0 0L24 24", 2]] * 7_000},
            "svg, too many shapes": iconsets.svg_record("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'>"
                                                        + "<circle cx='12' cy='12' r='11'/>" * 30 + "</svg>"),
        }
        for what, rec in crafted.items():
            t = time.monotonic()
            self.assertFalse(rec and vector.check(rec), what)
            if rec:
                self.assertIsNone(vector.cut(rec, 272, crop=True), what)
            self.assertLess(time.monotonic() - t, 2.0, what)
        # Many curves within the limits: allowed, but cut coarser, so it still draws quickly.
        curvy = "M2 12" + "C2 2 22 2 22 12C22 22 2 22 2 12" * 9_000 + "Z"
        self.assertTrue(vector.check(curvy))
        t = time.monotonic()
        vector.cut(curvy, 272)
        self.assertLess(time.monotonic() - t, 3.0)

    def test_the_same_shapes_as_the_old_font(self):
        # Drawn from outlines, every icon matches what the font drew to within a few percent of its
        # ink at 48 px, an edge pixel here and there (the font's hinting differs most at small sizes).
        from PIL import Image, ImageChops, ImageDraw
        for name in ("cat", "paw", "radiator", "washing-machine", "door-open", "weather-partly-cloudy", "lightbulb-on", "fan"):
            rec = icons.get("mdi:" + name)
            mine = vector.cut(rec, 48)
            img = Image.new("L", (48, 48), 255)
            ImageDraw.Draw(img).text((24, 24), chr(layout.mdi_codepoint(name)), font=layout._mdi_font(48), fill=0, anchor="mm")
            font = img.point(lambda p: 255 if p < 128 else 0)
            off = sum(ImageChops.difference(mine, font).histogram()[1:])
            self.assertLess(off / max(1, mask_ink(font)), 0.10, name)


class TestPagesLookAsBefore(unittest.TestCase):
    def test_an_icon_is_the_size_it_was_in_its_box(self):
        # Pages drawn before icons came from outlines: the same icons at the same sizes, give or take
        # an edge pixel (the old font measured an icon across by its whole square).
        spec = json.loads((support.APP / "default_layouts.json").read_text())
        from PIL import ImageChops
        try:
            for name, page in spec["pages"].items():
                icons.FROM_FONT = True
                old = T.to_1bit(layout.render_page(page, {})).convert("L")
                icons.FROM_FONT = False
                new = T.to_1bit(layout.render_page(page, {})).convert("L")
                off = sum(ImageChops.difference(old, new).histogram()[1:])
                self.assertLess(off, max(300, ink(old) * 0.02), name)
        finally:
            icons.FROM_FONT = False


class TestTheShippedSet(IconTest):
    def test_it_is_home_assistants_version_and_complete(self):
        s = icons.shipped()
        self.assertEqual(s["version"], "7.4.47")
        self.assertGreaterEqual(len(s["icons"]), 7447)
        font = json.loads((support.APP / "fonts" / "mdi-codepoints.json").read_text())
        self.assertEqual(set(font) - set(s["icons"]), {"blank"}, "everything the font drew, but its empty one")

    def test_every_shipped_icon_reads(self):
        bad = [n for n, d in icons.shipped()["icons"].items() if not vector.check(d)]
        self.assertEqual(bad, [])

    def test_names(self):
        self.assertEqual(icons.split("mdi:Cat"), ("mdi", "cat"))
        self.assertEqual(icons.split("cat"), ("mdi", "cat"))
        self.assertEqual(icons.split("phu:France2"), ("phu", "France2"), "a custom set's names keep their case")
        self.assertTrue(layout.can_draw_icon("mdi:cat") and layout.can_draw_icon("cat"))
        self.assertFalse(layout.can_draw_icon("mdi:cat-outline"), "not in Material Design 7.4.47")


class TestCopyingHomeAssistantsSet(IconTest):
    def copy(self, frontend, hass=None):
        return asyncio.run(iconsets.copy_home_assistant(frontend, hass or FakeHass()))

    def test_an_icon_missing_from_the_shipped_set_draws_once_copied(self):
        page = {"elements": [{"type": "icon", "icon": "mdi:cat-outline", "x": 10, "y": 10, "w": 120, "h": 120}]}
        self.assertFalse(layout.can_draw_icon("mdi:cat-outline"))
        self.assertEqual(ink(layout.render_page(page, {})), ink(layout.render_page({"elements": []}, {})))
        said = self.copy(FakeFrontend())
        self.assertEqual(said, f"copied {len(icons.shipped()['icons']) + 1} icons (7.5.0)")
        self.assertTrue(layout.can_draw_icon("mdi:cat-outline"))
        self.assertGreater(ink(layout.render_page(page, {})), ink(layout.render_page({"elements": []}, {})) + 500)
        # Kept in the add-on's data and used again at the next start, before anything is drawn.
        icons._sets.clear()
        self.assertFalse(layout.can_draw_icon("mdi:cat-outline"))
        iconsets.load_copies()
        self.assertTrue(layout.can_draw_icon("mdi:cat-outline"))

    def test_only_when_home_assistants_version_changes(self):
        fe = FakeFrontend()
        self.copy(fe)
        asked = len(fe.asked)
        self.assertEqual(self.copy(fe), "unchanged")
        self.assertEqual(len(fe.asked), asked, "nothing fetched while Home Assistant's version is the same")
        self.assertIn("already copied", self.copy(fe, FakeHass("2026.12.0")))

    def test_the_same_set_as_shipped_isnt_copied(self):
        fe = FakeFrontend(version=icons.shipped()["version"])
        self.assertIn("the same as the add-on's", self.copy(fe))
        self.assertEqual(len(fe.asked), 1, "only the list, never the chunks")
        self.assertFalse((iconsets.icon_dir() / "mdi.json.gz").exists())
        self.assertIs(icons.set_for("mdi"), icons.shipped())

    def test_all_or_nothing(self):
        fe = FakeFrontend(icons_by_part=[dict(icons.shipped()["icons"]), {"cat-outline": CAT_OUTLINE}], broken={1})
        with self.assertRaises(ValueError):
            self.copy(fe)
        self.assertIs(icons.set_for("mdi"), icons.shipped())
        fe = FakeFrontend(icons_by_part=[dict(icons.shipped()["icons"]), {"cat-outline": "M1 nonsense"}])
        with self.assertRaises(ValueError):
            self.copy(fe)
        self.assertFalse(layout.can_draw_icon("mdi:cat-outline"))
        self.assertFalse((iconsets.icon_dir() / "mdi.json.gz").exists())

    def test_too_few_icons_is_not_a_set(self):
        with self.assertRaises(ValueError):
            iconsets._checked_mdi({"cat": SQUARE}, "7.5.0", shipped_count=7447)

    def test_home_assistant_unreachable_falls_back_to_the_shipped_set(self):
        health._services.pop(iconsets.HEALTH, None)

        async def go():
            with mock.patch.object(iconsets, "CHECK_EVERY", 3600), mock.patch.object(iconsets, "copy_custom", lambda *a: "unchanged"):
                task = asyncio.create_task(iconsets.keep_in_step(FakeFrontend(down=True), FakeHass()))
                await asyncio.sleep(0.05)
                task.cancel()
        asyncio.run(go())
        self.assertIsNotNone(health._services[iconsets.HEALTH]["failing_since"], "shown in the problem sensors")
        self.assertIs(icons.set_for("mdi"), icons.shipped())
        self.assertTrue(layout.can_draw_icon("mdi:cat"))
        page = {"elements": [{"type": "icon", "icon": "mdi:cat", "x": 10, "y": 10, "w": 120, "h": 120}]}
        self.assertGreater(ink(layout.render_page(page, {})), ink(layout.render_page({"elements": []}, {})) + 500)

    def test_a_render_never_waits_on_the_copy(self):
        page = {"elements": [{"type": "icon", "icon": "mdi:cat", "x": 10, "y": 10, "w": 120, "h": 120}]}

        async def go():
            hang = asyncio.Event()
            task = asyncio.create_task(iconsets.copy_home_assistant(FakeFrontend(hang=hang), FakeHass()))
            await asyncio.sleep(0.01)                      # the copy is waiting on Home Assistant
            t = time.monotonic()
            img = layout.render_page(page, {})
            took = time.monotonic() - t
            self.assertFalse(task.done())
            hang.set()
            with self.assertRaises(asyncio.TimeoutError):
                await task
            return img, took
        img, took = asyncio.run(go())
        self.assertLess(took, 2.0)
        self.assertGreater(ink(img), ink(layout.render_page({"elements": []}, {})) + 500, "drawn from the shipped set meanwhile")

    def test_drawing_never_reaches_out(self):
        for f in ("render/icons.py", "render/vector.py", "render/layout.py"):
            text = (support.APP / f).read_text()
            for word in ("aiohttp", "iconsets", "urllib", "requests"):
                self.assertNotIn(f"import {word}", text, f"{f} imports {word}")


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


LOCAL = frozenset({"local"})
LOCAL_DEFAULTS_NEVER_HEARD = frozenset({"local", "fa6-regular", "fa6-solid", "fa6-brands"})
# An Iconify set as Iconify publishes it: an icon, one turned, an alias and an alias flipped.
PH = {"prefix": "ph", "info": {"name": "Phosphor", "license": {"title": "MIT"}, "version": "2.1"}, "width": 256, "height": 256,
      "icons": {"cat": {"body": '<path fill="currentColor" d="M16 16H240V240H16Z"/>'}, "spin": {"body": "<path d='M0 0H9V9Z'/>", "rotate": 1}},
      "aliases": {"kitty": {"parent": "cat"}, "mirrored": {"parent": "cat", "hFlip": True}}}


CAT_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <g transform="translate(16 16)"><circle r="12"/></g>
  <rect x="2" y="2" width="6" height="6" rx="1" fill="currentColor" style="fill:#000"/>
  <path d="M4 28H28" stroke="black" stroke-width="2" fill="none"/>
</svg>"""


class TestCustomSets(IconTest):
    def setUp(self):
        super().setUp()
        self.cfg = support.temp_dir()

    def test_svg_shapes_become_one_outline(self):
        rec = iconsets.svg_record(CAT_SVG)
        self.assertEqual(rec["v"], [0, 0, 32, 32])
        self.assertIn("s", rec, "the stroked line")
        m = vector.mask(rec, 32)
        self.assertGreaterEqual(m.getpixel((16, 16)), 128, "the circle, moved by its group")
        self.assertGreaterEqual(m.getpixel((4, 4)), 128, "the rectangle")
        self.assertGreaterEqual(m.getpixel((16, 28)), 128, "the line")
        self.assertLess(m.getpixel((30, 4)), 128)

    def test_nothing_in_an_svg_runs_or_is_kept_as_it_is(self):
        evil = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" onload="alert(1)">
          <script>alert(1)</script><image href="http://example.invalid/x.png" width="24" height="24"/>
          <a href="javascript:alert(1)"><path d="M0 0H24V24H0Z"/></a><path d="M2 2H10V10H2Z" onclick="alert(1)"/></svg>"""
        rec = iconsets.svg_record(evil)
        self.assertEqual(set(rec), {"d", "v"})
        self.assertNotRegex(json.dumps(rec), r"alert|script|href|onload|onclick|example")
        self.assertIsNone(iconsets.svg_record('<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "aaaa">]><svg>&a;</svg>'))
        self.assertIsNone(iconsets.svg_record("<svg xmlns='http://www.w3.org/2000/svg'><text>Hi</text></svg>"), "nothing to draw")
        self.assertIsNone(iconsets.svg_record("not svg"))
        self.assertIsNone(iconsets.svg_record("<svg>" + "<path d='M0 0H1V1Z'/>" * 40000 + "</svg>"), "too big")

    def test_a_file_no_icon_is_like_is_left_out_not_the_set(self):
        # Thousands of groups inside groups used to stop the whole folder copying; numbers too big to
        # be real used to reach the editor as JSON no browser reads.
        ns = 'xmlns="http://www.w3.org/2000/svg"'
        deep = f"<svg {ns} viewBox='0 0 24 24'>" + "<g>" * 3000 + "<path d='M0 0H9V9Z'/>" + "</g>" * 3000 + "</svg>"
        self.assertIsNone(iconsets.svg_record(deep))
        self.assertIsNone(iconsets.svg_record(f"<svg {ns} viewBox='0 0 1e309 24'><path d='M0 0H9V9Z'/></svg>"))
        self.assertIsNone(iconsets.svg_record(f"<svg {ns} width='1e309' height='5'><path d='M0 0H9V9Z'/></svg>"))
        self.assertIsNone(iconsets.svg_record(f"<svg {ns} viewBox='0 0 24 24'><path stroke='black' stroke-width='1e309' d='M0 0L9 9'/></svg>"))
        # Finite but absurd: accepted, it raised OverflowError when drawn and its page was left out.
        huge = iconsets.svg_record(f"<svg {ns} viewBox='0 0 24 24'><path stroke='black' stroke-width='1e300' d='M0 0L9 9'/></svg>")
        self.assertIsNone(huge)
        self.assertFalse(vector.check({"s": [[SQUARE, 1e300]], "v": [0, 0, 24, 24]}))
        self.assertTrue(vector.check({"s": [[SQUARE, 3]], "v": [0, 0, 24, 24]}), "a real stroke still draws")
        self.assertFalse(vector.check({"d": SQUARE, "v": [0, 0, float("nan"), 24]}))
        self.assertFalse(vector.check({"s": [[SQUARE, float("inf")]]}))
        write(self.cfg / "custom_icons" / "deep.svg", deep)
        write(self.cfg / "custom_icons" / "cat-outside.svg", CAT_SVG)
        self.assertEqual(iconsets.copy_custom(self.cfg, LOCAL), "local: 1")

    def test_custom_icons_old_folder_without_custom_icons(self):
        # Custom Icons' folder is still read, with nothing asked of Home Assistant: it can be uninstalled.
        write(self.cfg / "custom_icons" / "cat-outside.svg", CAT_SVG)
        write(self.cfg / "custom_icons" / "pets" / "Dog.svg", CAT_SVG)
        write(self.cfg / "custom_icons" / "broken.svg", "<svg><path d='nonsense'/></svg>")
        write(self.cfg / "custom_icons" / "rpg-webfont.svg", CAT_SVG)
        said = iconsets.copy_custom(self.cfg)
        self.assertEqual(said, "local: 2")
        self.assertTrue(layout.can_draw_icon("local:cat-outside") and layout.can_draw_icon("local:pets/Dog"))
        self.assertFalse(layout.can_draw_icon("local:broken") or layout.can_draw_icon("local:rpg-webfont"))
        page = {"elements": [{"type": "icon", "icon": "local:cat-outside", "x": 10, "y": 10, "w": 120, "h": 120}]}
        self.assertGreater(ink(layout.render_page(page, {})), ink(layout.render_page({"elements": []}, {})) + 500)

    def test_your_own_folder(self):
        write(self.cfg / "epaper" / "icons" / "pawpaw.svg", CAT_SVG)
        write(self.cfg / "custom_icons" / "pawpaw.svg", "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path d='M0 0H2V2Z'/></svg>")
        write(self.cfg / "custom_icons" / "old.svg", CAT_SVG)
        self.assertEqual(iconsets.copy_custom(self.cfg), "local: 2")
        self.assertEqual(icons.get("local:pawpaw"), iconsets.svg_record(CAT_SVG), "the own folder wins a name both have")
        self.assertTrue(layout.can_draw_icon("local:old"))
        self.assertEqual(icons.set_for("local")["name"], "Your own icons")
        own = iconsets.status(self.cfg)["own"]
        self.assertEqual((own["folder"], own["count"], own["legacy"]), ("epaper/icons", 1, 1))

    def test_the_way_back_asks_custom_icons(self):
        # Switched off: e-paper's own choice. Switched on, Custom Icons' collections stand for it, as in 0.19.
        self.assertFalse(iconsets.ASK_CUSTOM_ICONS)
        write(self.cfg / "custom_icons" / "cat-outside.svg", CAT_SVG)
        self.assertEqual(iconsets.copy_custom(self.cfg, frozenset()), "none", "Custom Icons isn't set up, or Local is off")
        self.assertEqual(iconsets.copy_custom(self.cfg, LOCAL), "local: 1", "switched on: copied")
        self.assertEqual(iconsets.heard_from_custom_icons(None), LOCAL_DEFAULTS_NEVER_HEARD, "never heard: its defaults")
        self.assertEqual(iconsets.heard_from_custom_icons(frozenset({"local", "ph"})), {"local", "ph"})
        self.assertEqual(iconsets.heard_from_custom_icons(None), {"local", "ph"}, "can't say: the last answer stands")

    def test_custom_icons_is_never_asked(self):
        write(self.cfg / "custom_icons" / "cat-outside.svg", CAT_SVG)

        async def go(way_back):
            asked = mock.AsyncMock(return_value=LOCAL)
            with mock.patch.object(iconsets, "CHECK_EVERY", 3600), mock.patch.object(config, "HA_CONFIG_DIR", self.cfg), \
                    mock.patch.object(iconsets, "collections_on", asked), mock.patch.object(iconsets, "ASK_CUSTOM_ICONS", way_back):
                task = asyncio.create_task(iconsets.keep_in_step(None, None))
                await asyncio.sleep(0.05)
                task.cancel()
            return asked.await_count
        self.assertEqual(asyncio.run(go(False)), 0)
        self.assertTrue(layout.can_draw_icon("local:cat-outside"), "your own icons without Custom Icons")
        self.assertEqual(asyncio.run(go(True)), 1, "the way back still asks")

    def test_which_collections_are_on_comes_from_home_assistant(self):
        from hass import HassError

        class Ws(FakeHass):
            def __init__(self, answer):
                super().__init__()
                self.answer = answer

            async def ws(self, payload, timeout=10):
                self.asked.append(payload)
                if isinstance(self.answer, Exception):
                    raise self.answer
                return self.answer
        on = lambda h: asyncio.run(iconsets.collections_on(h))  # noqa: E731
        h = Ws(["local", "ph", 3])
        self.assertEqual(on(h), {"local", "ph"})
        self.assertEqual(h.asked, [{"type": "custom_icons/activesets"}])
        self.assertEqual(on(Ws(None)), set(), "installed, not set up")
        self.assertEqual(on(Ws(HassError("Unknown command.", code="unknown_command"))), set(), "not installed")
        self.assertIsNone(on(Ws(HassError("Cannot connect to host"))), "can't say")
        self.assertIsNone(on(None))

    def test_nothing_reads_home_assistants_storage(self):
        # Home Assistant's own storage holds every integration's credentials: never read, by any code.
        for f in sorted(support.APP.rglob("*.py")) + sorted((support.APP / "web").rglob("*.js")):
            self.assertNotIn(".storage", f.read_text(), f.relative_to(support.APP).as_posix())
        write(self.cfg / ".storage" / "core.config_entries", '{"secret": "token"}')
        write(self.cfg / "custom_icons" / "cat-outside.svg", CAT_SVG)
        real_open = open
        seen = []

        def watch(path, *a, **k):
            seen.append(str(path))
            return real_open(path, *a, **k)
        with mock.patch("builtins.open", watch), mock.patch("io.open", watch):
            iconsets.copy_custom(self.cfg, None)
            iconsets.copy_custom(self.cfg, LOCAL)
        self.assertFalse([p for p in seen if ".storage" in p])
        self.assertTrue(any("cat-outside.svg" in p for p in seen), "the watch sees what's read")

    def test_copied_whole_only_when_the_files_change(self):
        write(self.cfg / "custom_icons" / "a.svg", CAT_SVG)
        self.assertEqual(iconsets.copy_custom(self.cfg, LOCAL), "local: 1")
        with mock.patch.object(iconsets, "read_custom_sets", side_effect=AssertionError("read again")):
            self.assertEqual(iconsets.copy_custom(self.cfg, LOCAL), "unchanged")
        write(self.cfg / "custom_icons" / "b.svg", CAT_SVG)
        self.assertEqual(iconsets.copy_custom(self.cfg, LOCAL), "local: 2")
        (self.cfg / "custom_icons" / "a.svg").unlink()
        (self.cfg / "custom_icons" / "b.svg").unlink()
        self.assertEqual(iconsets.copy_custom(self.cfg, LOCAL), "none")
        self.assertFalse(layout.can_draw_icon("local:a"), "a set that's gone isn't offered any more")

    def test_a_chosen_set_custom_icons_downloaded_is_taken_from_there_once(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("icon-sets-master/json/ph.json", json.dumps(PH))
            zf.writestr("icon-sets-master/json/other.json", json.dumps({"prefix": "other", "icons": {"x": {"body": "<path d='M0 0H9V9Z'/>"}}}))
        zp = write(self.cfg / "custom_icons" / "x.svg", CAT_SVG).parent / "iconify-icon-sets-master.zip"
        zp.write_bytes(buf.getvalue())
        self.assertEqual(iconsets.copy_custom(self.cfg), "local: 1", "only chosen sets")
        iconsets.set_chosen(["ph"])
        self.assertEqual(iconsets.copy_custom(self.cfg), "local: 1, ph: 2")
        self.assertTrue(layout.can_draw_icon("ph:cat") and layout.can_draw_icon("ph:kitty"), "an alias is its parent")
        self.assertFalse(layout.can_draw_icon("ph:spin") or layout.can_draw_icon("ph:mirrored"), "turned or flipped: left out")
        self.assertEqual(icons.set_for("ph")["name"], "Phosphor")
        zp.unlink()
        self.assertEqual(iconsets.copy_custom(self.cfg, force=True), "local: 1, ph: 2", "kept: the download can go")
        self.assertEqual(iconsets.status(self.cfg)["sets"][0]["source"], "custom_icons")

    def test_a_zip_that_lies_about_its_size_is_read_no_further(self):
        # A member that says it's small and inflates to 50 MB: reading stops at the size it states,
        # which is what's checked, and the set is left out.
        import struct
        body = json.dumps({"prefix": "ph", "icons": {"cat": {"body": "<path d='M0 0H9V9Z'/>"}}}).encode() + b" " * 50_000_000
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("icon-sets-master/json/ph.json", body)
        raw = bytearray(buf.getvalue())
        for sig, at in ((b"PK\x03\x04", 22), (b"PK\x01\x02", 24)):      # its uncompressed size, both copies
            i = raw.find(sig)
            struct.pack_into("<I", raw, i + at, 1000)
        write(self.cfg / "custom_icons" / "x.svg", CAT_SVG)
        (self.cfg / "custom_icons" / "iconify-icon-sets-master.zip").write_bytes(bytes(raw))
        with zipfile.ZipFile(self.cfg / "custom_icons" / "iconify-icon-sets-master.zip") as zf:
            self.assertEqual(zf.getinfo("icon-sets-master/json/ph.json").file_size, 1000)
            with zf.open("icon-sets-master/json/ph.json") as f:
                with self.assertRaises(zipfile.BadZipFile):
                    f.read()
        t = time.monotonic()
        iconsets.set_chosen(["ph"])
        self.assertEqual(iconsets.copy_custom(self.cfg), "local: 1")
        self.assertLess(time.monotonic() - t, 2.0)

    def test_a_script_set_like_brand_icons(self):
        js = """var icons = {
  "02tv":[0,0,24,24,"M2 2H22V22H2Z"],
  "Hydro-Québec":[0,0,48,24,"M0 0H48V24H0Z","M1 1H2V2Z"],
  "bad":[0,0,24,24,"M nonsense"],
};

window.customIcons = window.customIcons || {};
window.customIcons["phu"] = { getIcon, getIconList };
"""
        write(self.cfg / "www" / "community" / "custom-brand-icons" / "custom-brand-icons.js", js)
        write(self.cfg / "www" / "community" / "other-card" / "card.js", "customElements.define('x', class {});")
        write(self.cfg / "www" / "community" / "clash" / "clash.js", js.replace('"phu"', '"mdi"'))
        self.assertEqual(iconsets.copy_custom(self.cfg), "phu: 2")
        self.assertTrue(layout.can_draw_icon("phu:Hydro-Québec") and layout.can_draw_icon("phu:02tv"))
        self.assertFalse(layout.can_draw_icon("phu:bad"))
        self.assertEqual(icons.set_for("phu")["name"], "Custom brand icons")
        self.assertIs(icons.set_for("mdi"), icons.shipped(), "a set can't take Material Design's prefix")

    def test_a_bad_file_never_stops_the_loop(self):
        async def go():
            with mock.patch.object(iconsets, "copy_custom", side_effect=OSError("disk")), mock.patch.object(iconsets, "CHECK_EVERY", 3600):
                task = asyncio.create_task(iconsets.keep_in_step(None, None))
                await asyncio.sleep(0.02)
                self.assertFalse(task.done())
                task.cancel()
        asyncio.run(go())


class TestUpgrading(IconTest):
    def test_the_sets_it_drew_draw_on_without_custom_icons(self):
        # 0.19 drew Custom Icons' sets from its download; the first start after keeps every one, even
        # once Custom Icons, its settings and its download are gone.
        old = {"local": {"name": "Your own icons", "from": "custom_icons", "icons": {"pawpaw": SQUARE}},
               "ph": {"name": "Phosphor", "from": "custom_icons", "icons": {"cat": SQUARE}},
               "phu": {"name": "Custom brand icons", "from": "script", "icons": {"02tv": SQUARE}}}
        iconsets._write_json(iconsets.icon_dir() / "custom.json.gz", old, compress=True)
        iconsets._write_json(iconsets._state_path(), {"custom_on": ["local", "ph", "fa6-solid"]})
        iconsets.load_copies()
        self.assertEqual(iconsets.chosen(), ["ph"], "what it drew, not what it last heard")
        self.assertTrue(layout.can_draw_icon("ph:cat"))
        cfg = support.temp_dir()
        self.assertEqual(iconsets.copy_custom(cfg), "ph: 1")
        icons._sets.clear()
        iconsets.load_copies()
        self.assertTrue(layout.can_draw_icon("ph:cat"), "and after the next start")

    def test_a_new_install_chooses_nothing(self):
        self.assertEqual(iconsets.chosen(), [])
        self.assertEqual(iconsets.set_chosen(["ph", "mdi", "custom", "local", "Bad!", "ph", "tabler"]), ["ph", "tabler"])


class TestAddIcons(IconTest):
    def setUp(self):
        super().setUp()
        self.cfg = support.temp_dir()

    def test_a_cleaned_copy_lands_in_the_folder(self):
        evil = CAT_SVG.replace("<g ", "<script>alert(1)</script><image href='http://example.invalid/x.png'/><g onload='alert(1)' ")
        said = iconsets.save_own([{"name": "Paw Paw.svg", "svg": evil}], self.cfg)
        self.assertEqual(said, {"added": ["Paw Paw"], "replaced": [], "refused": []})
        saved = (self.cfg / "epaper" / "icons" / "Paw Paw.svg").read_text()
        self.assertNotRegex(saved, r"alert|script|href=|onload|example|image")
        self.assertEqual(iconsets.svg_record(saved), iconsets.svg_record(CAT_SVG), "it reads back as the same outline")
        self.assertEqual(iconsets.copy_custom(self.cfg), "local: 1")
        self.assertTrue(layout.can_draw_icon("local:Paw Paw"))
        again = iconsets.save_own([{"name": "Paw Paw.SVG", "svg": CAT_SVG}], self.cfg)
        self.assertEqual(again["replaced"], ["Paw Paw"])

    def test_what_isnt_an_icon_is_refused_in_words(self):
        said = iconsets.save_own([
            {"name": "notes.svg", "svg": "<svg xmlns='http://www.w3.org/2000/svg'><text>Hi</text></svg>"},
            {"name": "../../secrets.svg", "svg": CAT_SVG},
            {"name": "...svg", "svg": CAT_SVG},
            {"name": "huge.svg", "svg": "<svg>" + " " * (iconsets.MAX_SVG + 1) + "</svg>"},
            {"name": "x.svg", "svg": 4}], self.cfg)
        self.assertEqual(said["added"], ["secrets"], "a path is only ever its file's name")
        self.assertEqual([r["file"] for r in said["refused"]], ["notes.svg", "...svg", "huge.svg", "x.svg"])
        self.assertTrue(all(r["why"] and not r["why"].endswith(".") for r in said["refused"]))
        self.assertEqual(sorted(p.name for p in (self.cfg / "epaper" / "icons").iterdir()), ["secrets.svg"])


class FakeBody:
    def __init__(self, raw, step=1 << 16):
        self.raw, self.step = raw, step

    async def iter_chunked(self, n):
        for i in range(0, len(self.raw), self.step):
            yield self.raw[i:i + self.step]


class FakeIconifyResponse:
    def __init__(self, status, raw=b"", etag="", length=None):
        self.status, self.headers = status, {"ETag": etag} if etag else {}
        self.content, self.content_length = FakeBody(raw), len(raw) if length is None else length

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


COLLECTIONS = {
    "ph": {"name": "Phosphor", "total": 2, "samples": ["cat", "kitty", "gone"], "license": {"title": "MIT"}, "author": {"name": "Phosphor Icons"}, "category": "UI 16px / 32px", "palette": False},
    "tabler": {"name": "Tabler Icons", "total": 1, "palette": False},
    "twemoji": {"name": "Twitter Emoji", "total": 3000, "palette": True},
    "old": {"name": "Old", "total": 1, "palette": False, "hidden": True},
    "mdi": {"name": "Material Design Icons", "total": 7000, "palette": False},
}


class FakeIconify:
    """Iconify's published files: collections.json and json/<prefix>.json, each with an ETag."""

    def __init__(self, files=None, down=False):
        self.files = files if files is not None else {
            "/collections.json": json.dumps(COLLECTIONS).encode(), "/json/ph.json": json.dumps(PH).encode(),
            "/json/tabler.json": json.dumps({"prefix": "tabler", "icons": {"home": {"body": "<path d='M2 2H22V22H2Z'/>"}}, "width": 24, "height": 24}).encode()}
        self.down, self.asked = down, []

    def get(self, url, headers=None, allow_redirects=True, timeout=None):
        assert not allow_redirects, url
        if url.startswith(iconsets.ICONIFY_API + "/"):         # a few icons of a set: /ph.json?icons=a,b
            path, _, query = url[len(iconsets.ICONIFY_API):].partition("?icons=")
            self.asked.append((path, query))
            if self.down:
                import aiohttp
                raise aiohttp.ClientConnectionError("Cannot connect to host api.iconify.design:443")
            whole = json.loads(self.files.get("/json" + path, b"null"))
            if whole is None:
                return FakeIconifyResponse(404)
            want = urllib.parse.unquote(query).split(",")
            return FakeIconifyResponse(200, json.dumps({**whole, "icons": {n: i for n, i in whole["icons"].items() if n in want},
                                                         "aliases": {n: a for n, a in whole.get("aliases", {}).items() if n in want}}).encode())
        assert url.startswith(iconsets.ICONIFY + "/"), url
        path = url[len(iconsets.ICONIFY):]
        self.asked.append((path, (headers or {}).get("If-None-Match", "")))
        if self.down:
            import aiohttp
            raise aiohttp.ClientConnectionError("Cannot connect to host raw.githubusercontent.com:443")
        raw = self.files.get(path)
        if raw is None:
            return FakeIconifyResponse(404)
        etag = f'"{hash(raw) & 0xffff:x}"'
        if (headers or {}).get("If-None-Match") == etag:
            return FakeIconifyResponse(304)
        return FakeIconifyResponse(200, raw, etag)


class TestIconifySets(IconTest):
    def setUp(self):
        super().setUp()
        self.cfg = support.temp_dir()
        self._cfg = mock.patch.object(config, "HA_CONFIG_DIR", self.cfg)
        self._cfg.start()
        iconsets._jobs.clear()
        iconsets._check.clear()
        iconsets._samples = None

    def tearDown(self):
        self._cfg.stop()
        super().tearDown()

    def run_async(self, coro):
        async def go():
            out = await coro
            while iconsets._tasks:
                await asyncio.gather(*list(iconsets._tasks))
            return out
        return asyncio.run(go())

    def row(self, prefix):
        return next(s for s in iconsets.status()["sets"] if s["prefix"] == prefix)

    def test_only_single_color_sets_are_offered_and_the_list_is_kept(self):
        web = FakeIconify()
        got = self.run_async(iconsets.available(web))
        self.assertEqual([s["prefix"] for s in got], ["ph", "tabler"], "no colored, hidden or Material Design set")
        self.assertEqual(got[0]["license"], "MIT")
        self.run_async(iconsets.available(FakeIconify(down=True)))      # kept: no need to reach Iconify
        self.assertEqual(len(web.asked), 1)
        self.run_async(iconsets.available(web, refresh=True))
        self.assertTrue(web.asked[-1][1], "asked again only whether it changed")
        self.assertEqual(len(self.run_async(iconsets.available(FakeIconify(down=True), refresh=True))), 2, "a failed refresh keeps the list")

    def test_no_list_and_no_internet_says_what_to_do(self):
        with self.assertRaises(iconsets.SetError) as cm:
            self.run_async(iconsets.available(FakeIconify(down=True)))
        self.assertIn("Check that Home Assistant is online", str(cm.exception))

    def test_adding_a_set_downloads_it_and_only_it(self):
        web = FakeIconify()
        self.run_async(iconsets.add(web, "ph"))
        self.assertEqual([p for p, _ in web.asked], ["/collections.json", "/json/ph.json"])
        self.assertEqual(iconsets.chosen(), ["ph"])
        self.assertTrue(layout.can_draw_icon("ph:cat"))
        row = self.row("ph")
        self.assertEqual((row["state"], row["count"], row["license"], row["source"], row["name"]), ("ready", 2, "MIT", "iconify", "Phosphor"))
        icons._sets.clear()
        iconsets.load_copies()
        self.assertTrue(layout.can_draw_icon("ph:cat"), "kept for the next start")
        with self.assertRaises(iconsets.SetError):
            self.run_async(iconsets.add(web, "twemoji"))
        self.assertEqual(iconsets.chosen(), ["ph"])

    def test_converted_once_not_when_other_icons_change(self):
        self.run_async(iconsets.add(FakeIconify(), "ph"))
        write(self.cfg / "epaper" / "icons" / "pawpaw.svg", CAT_SVG)
        with mock.patch.object(iconsets, "_convert_iconify", side_effect=AssertionError("converted again")):
            self.assertEqual(iconsets.copy_custom(), "local: 1, ph: 2")

    def test_a_failed_download_says_why_and_can_be_tried_again(self):
        self.run_async(iconsets.add(FakeIconify(), "tabler"))      # the list is kept from here on
        self.run_async(iconsets.add(FakeIconify(down=True), "ph"))
        row = self.row("ph")
        self.assertEqual(row["state"], "failed")
        self.assertIn("Couldn't reach Iconify", row["error"])
        self.assertEqual(iconsets.chosen(), ["tabler", "ph"], "still chosen, to try again")
        self.run_async(iconsets.add(FakeIconify(), "ph"))
        self.assertEqual(self.row("ph")["state"], "ready")

    def test_what_isnt_the_set_is_never_kept(self):
        files = FakeIconify().files
        cases = {
            "the wrong set": json.dumps({**PH, "prefix": "tabler"}).encode(),
            "not JSON": b"<html>rate limited</html>",
            "nothing to draw": json.dumps({"prefix": "ph", "icons": {"x": {"body": "<text>Hi</text>"}}}).encode(),
        }
        for why, raw in cases.items():
            with self.subTest(why):
                iconsets._jobs.clear()
                self.run_async(iconsets.add(FakeIconify({**files, "/json/ph.json": raw}), "ph"))
                self.assertEqual(self.row("ph")["state"], "failed")
                self.assertFalse(layout.can_draw_icon("ph:cat"))
                self.assertFalse((iconsets.iconify_dir() / "ph.json.gz").exists())

    def test_too_large_is_refused_while_it_downloads(self):
        big = b" " * (iconsets.MAX_DOWNLOAD + 1)

        class Lying(FakeIconify):
            def get(self, url, **kw):
                r = super().get(url, **kw)
                if url.endswith("/ph.json"):
                    r.content, r.content_length = FakeBody(big, 1 << 20), None     # says no size, sends too much
                return r
        self.run_async(iconsets.add(Lying(), "ph"))
        self.assertIn("32 MB", self.row("ph")["error"])

    def test_check_for_updates_downloads_only_what_changed(self):
        web = FakeIconify()
        self.run_async(iconsets.add(web, "ph"))
        self.run_async(iconsets.add(web, "tabler"))
        web.asked.clear()
        self.run_async(iconsets.check_updates(web))
        self.assertEqual([bool(etag) for _, etag in web.asked], [True, True], "asked only whether each changed")
        self.assertEqual(iconsets.status()["check"]["updated"], [])
        web.files["/json/ph.json"] = json.dumps({**PH, "icons": {**PH["icons"], "dog": PH["icons"]["cat"]}}).encode()
        self.run_async(iconsets.check_updates(web))
        check = iconsets.status()["check"]
        self.assertEqual((check["updated"], check["failed"], check["running"]), (["Phosphor"], [], False))
        self.assertTrue(layout.can_draw_icon("ph:dog"))
        self.run_async(iconsets.check_updates(FakeIconify(down=True)))
        self.assertEqual(sorted(iconsets.status()["check"]["failed"]), ["Phosphor", "tabler"], "named as the editor shows them")
        self.assertTrue(layout.can_draw_icon("ph:dog"), "a failed check keeps the set")

    def test_a_set_from_custom_icons_download_needs_no_internet(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("icon-sets-master/json/ph.json", json.dumps(PH))
        (self.cfg / "custom_icons").mkdir()
        (self.cfg / "custom_icons" / "iconify-icon-sets-master.zip").write_bytes(buf.getvalue())
        iconsets.set_chosen(["ph"])
        web = FakeIconify(down=True)
        self.run_async(iconsets.add(web, "ph"))
        self.assertEqual(web.asked, [])
        self.assertEqual((self.row("ph")["state"], self.row("ph")["source"]), ("ready", "custom_icons"))
        self.run_async(iconsets.check_updates(FakeIconify()))
        self.assertEqual(self.row("ph")["source"], "iconify", "Check for updates swaps in Iconify's own")

    def test_removing_is_undone_without_the_internet(self):
        self.run_async(iconsets.add(FakeIconify(), "ph"))
        self.run_async(iconsets.remove("ph"))
        self.assertEqual(iconsets.chosen(), [])
        self.assertFalse(layout.can_draw_icon("ph:cat"))
        web = FakeIconify()
        self.run_async(iconsets.available(web))
        web.asked.clear()
        self.run_async(iconsets.add(web, "ph"))
        self.assertEqual(web.asked, [], "Undo: the copy was kept")
        self.run_async(iconsets.remove("ph"))
        iconsets.load_copies()
        self.assertEqual(list(iconsets.iconify_dir().glob("ph.*")), [], "gone at the next start")

    def test_previews_are_a_few_outlines_asked_for_once(self):
        web = FakeIconify()
        self.run_async(iconsets.available(web))
        web.asked.clear()
        got = self.run_async(iconsets.samples(web, ["ph", "tabler", "nope"]))
        self.assertEqual(list(got), ["ph"], "only a set Iconify lists with samples")
        self.assertEqual(len(got["ph"]), 2, "an alias draws as its parent; a sample that's gone is left out")
        self.assertTrue(all(vector.check(r) for r in got["ph"]))
        self.assertEqual(web.asked, [("/ph.json", "cat,kitty,gone")])
        iconsets._samples = None                    # kept across starts
        iconsets.load_copies()
        self.assertEqual(self.run_async(iconsets.samples(FakeIconify(down=True), ["ph"])), got)
        self.assertEqual(iconsets.chosen(), [], "a preview chooses nothing")
        self.assertFalse(layout.can_draw_icon("ph:cat"))

    def test_a_preview_that_cant_be_had_is_just_left_out(self):
        self.run_async(iconsets.available(FakeIconify()))
        self.assertEqual(self.run_async(iconsets.samples(FakeIconify(down=True), ["ph"])), {})
        self.assertEqual(len(self.run_async(iconsets.samples(FakeIconify(), ["ph"]))["ph"]), 2, "asked again later")

    def test_the_loop_never_downloads(self):
        iconsets.set_chosen(["ph"])

        class NoInternet:
            def get(self, url, **kw):
                raise AssertionError(f"reached {url}")

        async def go():
            with mock.patch.object(iconsets, "CHECK_EVERY", 3600):
                task = asyncio.create_task(iconsets.keep_in_step(NoInternet(), None))
                await asyncio.sleep(0.05)
                task.cancel()
        asyncio.run(go())
        self.assertEqual(self.row("ph")["state"], "missing")


class TestEditorRoutes(EditorClient):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._sets = dict(icons._sets)

    async def asyncTearDown(self):
        icons._sets.clear()
        icons._sets.update(self._sets)
        icons.FROM_FONT = False
        await super().asyncTearDown()

    async def test_the_list_is_what_the_panel_can_draw(self):
        r = await self.ed.get("/api/icons")
        body = await r.json()
        self.assertEqual([s["prefix"] for s in body["sets"]], ["mdi"])
        self.assertIn("cat", body["names"]["mdi"])
        self.assertNotIn("cat-outline", body["names"]["mdi"])
        again = await self.ed.get("/api/icons", headers={"If-None-Match": r.headers["ETag"]})
        self.assertEqual(again.status, 304)
        icons.install("phu", {"name": "Custom brand icons", "icons": {"02tv": SQUARE}})
        icons.install("mdi", {"version": "7.5.0", "from": "home_assistant", "icons": {**icons.shipped()["icons"], "cat-outline": CAT_OUTLINE}})
        r2 = await self.ed.get("/api/icons", headers={"If-None-Match": r.headers["ETag"]})
        self.assertEqual(r2.status, 200, "a new set is a new list")
        body = await r2.json()
        self.assertEqual([s["prefix"] for s in body["sets"]], ["mdi", "phu"])
        self.assertIn("cat-outline", body["names"]["mdi"])
        self.assertEqual(body["names"]["phu"], ["02tv"])

    async def test_outlines_in_pages(self):
        icons.install("phu", {"icons": {"02tv": {"d": SQUARE, "v": [0, 0, 48, 24]}}})
        r = await self.ed.post("/api/icons/outlines", json={"names": ["mdi:cat", "phu:02tv", "mdi:nope", "custom:cat-sitting", 4]})
        got = (await r.json())["icons"]
        self.assertEqual(set(got), {"mdi:cat", "phu:02tv"})
        self.assertEqual(got["phu:02tv"]["v"], [0, 0, 48, 24])
        r = await self.ed.post("/api/icons/outlines", json={"names": ["mdi:cat"] * 601})
        self.assertEqual(r.status, 400)

    async def test_settings_icons(self):
        import runtime
        cfg = support.temp_dir()
        iconsets._jobs.clear()
        with mock.patch.object(config, "HA_CONFIG_DIR", cfg), mock.patch.object(runtime, "SESSION", FakeIconify()):
            st = await (await self.ed.get("/api/iconsets")).json()
            self.assertEqual((st["own"]["count"], st["sets"]), (0, []))
            r = await self.ed.post("/api/icons/own", json={"files": [{"name": "pawpaw.svg", "svg": CAT_SVG}, {"name": "a.txt", "svg": "hi"}]})
            body = await r.json()
            self.assertEqual((body["added"], len(body["refused"]), body["own"]["count"]), (["pawpaw"], 1, 1))
            self.assertTrue(layout.can_draw_icon("local:pawpaw"))
            self.assertEqual((await self.ed.post("/api/icons/own", json={"files": []})).status, 400)
            got = await (await self.ed.get("/api/iconsets/available")).json()
            self.assertEqual([s["prefix"] for s in got["sets"]], ["ph", "tabler"])
            r = await self.ed.post("/api/iconsets", json={"prefix": "ph"})
            self.assertEqual([(s["prefix"], s["state"]) for s in (await r.json())["sets"]], [("ph", "ready")], "ready in the answer")
            self.assertEqual((await self.ed.post("/api/iconsets", json={"prefix": "twemoji"})).status, 502)
            self.assertEqual((await self.ed.post("/api/iconsets", json={"prefix": "../x"})).status, 400)
            self.assertEqual((await self.ed.post("/api/iconsets/check")).status, 200)
            r = await self.ed.post("/api/iconsets/samples", json={"prefixes": ["ph"]})
            self.assertEqual(len((await r.json())["samples"]["ph"]), 2)
            self.assertEqual((await self.ed.post("/api/iconsets/samples", json={"prefixes": ["ph"] * 25})).status, 400)
            self.assertEqual((await self.ed.post("/api/iconsets/samples", json={"prefixes": ["../x"]})).status, 400)
            r = await self.ed.delete("/api/iconsets/ph")
            self.assertEqual((await r.json())["sets"], [])
            self.assertFalse(layout.can_draw_icon("ph:cat"))
            while iconsets._tasks:
                await asyncio.gather(*list(iconsets._tasks))
        with mock.patch.object(runtime, "SESSION", FakeIconify(down=True)):
            (iconsets.iconify_dir() / "collections.json").unlink()
            r = await self.ed.get("/api/iconsets/available")
            self.assertEqual(r.status, 502)
            self.assertIn("Couldn't reach Iconify", (await r.json())["error"])

    async def test_the_way_back_lists_the_fonts_icons(self):
        icons.install("phu", {"icons": {"02tv": SQUARE}})
        icons.FROM_FONT = True
        body = await (await self.ed.get("/api/icons")).json()
        self.assertEqual([s["prefix"] for s in body["sets"]], ["mdi"])
        font = json.loads((support.APP / "fonts" / "mdi-codepoints.json").read_text())
        self.assertEqual(set(body["names"]["mdi"]), set(font) - {"blank"})


@unittest.skipUnless(shutil.which("node"), "no node to run the editor's icons")
class TestThePicker(unittest.TestCase):
    def run_js(self, body):
        script = f"import * as G from {json.dumps(str(GLYPHS_JS))};\n{body}"
        return json.loads(subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True).stdout)

    def test_search_across_sets_and_one_set(self):
        got = self.run_js("""
const names = { mdi: ["cat", "cat-outline", "paw", "television", "radiator"], phu: ["France2", "catalan-tv", "02tv"], local: ["pets/cat-outside"] };
console.log(JSON.stringify([
  G.search(names, "cat"),
  G.search(names, "cat", { only: "phu" }),
  G.search(names, "tv"),
  G.search(names, "phu:fr"),
  G.search(names, "pets", { terms: { pets: ["cat", "paw"] } }),
  G.search(names, "", { popular: ["paw"] }).slice(0, 2),
  [G.fullName("Cat"), G.fullName("mdi:Cat"), G.fullName("phu:France2"), G.fullName(""), G.prefixOf("x"), G.shortName("local:pets/a")],
  G.layersOf({ d: "M0 0Z", e: "M1 1Z", s: [["M2 2L3 3", 2]], v: [0, 0, 48, 24] }),
]));""")
        cat, cat_phu, tv, phu_fr, pets, popular, names, layers = got
        self.assertEqual(cat[:2], ["mdi:cat", "mdi:cat-outline"])
        self.assertIn("phu:catalan-tv", cat)
        self.assertIn("local:pets/cat-outside", cat)
        self.assertEqual(cat_phu, ["phu:catalan-tv"])
        self.assertEqual(set(tv), {"phu:catalan-tv", "phu:02tv"}, "found by its words, in any set")
        self.assertEqual(phu_fr, ["phu:France2"], "a prefix in the search picks the set")
        self.assertEqual(pets[:2], ["mdi:cat", "mdi:paw"], "a shortcut's own icons first")
        self.assertEqual(popular[0], "mdi:paw")
        self.assertEqual(names, ["mdi:cat", "mdi:cat", "phu:France2", "", "mdi", "pets/a"])
        self.assertEqual(layers, {"view": [0, 0, 48, 24], "layers": [{"d": "M0 0Z", "rule": "nonzero"}, {"d": "M1 1Z", "rule": "evenodd"}, {"d": "M2 2L3 3", "width": 2}]})

    def test_an_icon_that_didnt_arrive_is_asked_for_again(self):
        # The add-on restarting while the picker is open: no icon stays blank for good.
        got = self.run_js("""
const made = [];
globalThis.document = { createElementNS: (ns, t) => { const n = { t, a: {}, kids: [], isConnected: true, classList: { add() {} },
  setAttribute(k, v) { this.a[k] = v; }, getAttribute(k) { return this.a[k]; }, replaceChildren(...k) { this.kids = k; } }; made.push(n); return n; } };
let calls = 0, listCalls = 0;
const post = async (path, body) => { calls++; if (calls === 1) throw new Error("Failed to fetch"); return { icons: Object.fromEntries(body.names.map((n) => [n, "M0 0H24V24H0Z"])) }; };
const get = async () => { listCalls++; if (listCalls === 1) throw new Error("Failed to fetch"); return { sets: [{ prefix: "phu", count: 2 }], names: { phu: ["ARD", "Kika"] } }; };
const g = new G.Glyphs(get, post);
const a = g.node("phu:ARD"), b = g.node("phu:Kika"), gone = g.node("phu:Kika");
await g.load();                                   // the list fails: not ready, asked again
const readyAfterFail = g.ready();
await new Promise((r) => setTimeout(r, 2100));    // ... and arrives
gone.isConnected = false;
await new Promise((r) => setTimeout(r, 50));      // the outlines fail once
const blankAfterFail = a.kids.length === 0;
await new Promise((r) => setTimeout(r, 2100));    // asked again
console.log(JSON.stringify({ readyAfterFail, ready: g.ready(), blankAfterFail, a: a.kids.length, b: b.kids.length, gone: gone.kids.length, calls }));""")
        self.assertEqual(got, {"readyAfterFail": False, "ready": True, "blankAfterFail": True, "a": 1, "b": 1, "gone": 0, "calls": 2})

    def test_the_editor_draws_from_outlines_only(self):
        web = support.APP / "web"
        for f in [*sorted((web / "app").glob("*.js")), web / "index.html", web / "editor.css"]:
            text = f.read_text()
            self.assertNotIn("api/mdi", text, f"{f.name} still uses the old icon font")
            self.assertNotIn("mdiGlyph", text, f.name)
            if f.name != "glyphs.js":
                self.assertNotRegex(text, r"innerHTML\s*=.*(icon|glyph|outline)", f.name)
        pickers = (web / "app" / "pickers.js").read_text()
        self.assertIn("app.searchIcons(", pickers)
        self.assertIn("setRow.hidden = sets.length < 2", pickers, "set chips only when there's more than one set")


class TestEverySize(unittest.TestCase):
    def test_icons_draw_at_every_offered_size(self):
        # An icon element filling a box, on every screen size the add-on offers, from 24 px to the
        # whole height: ink in it, and none outside its box.
        names = ["mdi:cat", "mdi:radiator", "mdi:weather-partly-cloudy", "mdi:door-open"]
        for key, disp in T.DISPLAYS.items():
            w, h = disp["w"], disp["h"]
            for side in sorted({24, 48, 96, min(w, h) - 20}):
                page = {"elements": [{"type": "icon", "icon": n, "x": 10 + i * (side + 4), "y": 10, "w": side, "h": side}
                                     for i, n in enumerate(names) if 10 + (i + 1) * (side + 4) <= w]}
                img = layout.render_page(page, {}, display=key)
                blank = layout.render_page({"elements": []}, {}, display=key)
                self.assertGreater(ink(img), ink(blank), f"{key} at {side}")


if __name__ == "__main__":
    unittest.main()
