"""The firmware against the server, without a panel.

* Footer geometry the server sends matches the footer it draws, in every orientation.
* The firmware core (components/epf/epf_core.h), compiled on this machine,
  parses the server's real frame files, maps pixels exactly as the server's
  rotate-and-mirror pipeline does, refuses bad files, and keeps locks.
* The generated ESPHome YAML has no gaps, is pinned to the release, and the
  repository's copy is exactly what the generator produces.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import support  # noqa: E402,F401
from PIL import Image  # noqa: E402

import firmware_gen  # noqa: E402
from frames import panel_geometry  # noqa: E402
from render import epf, theme as T  # noqa: E402

DISPLAY = "crowpanel_579"
CLOCK = "12:34"


def pipeline(logical: Image.Image, deg: int, display: str = DISPLAY) -> Image.Image:
    """Exactly what build_frames + encode_epf do to a page before packing."""
    phys = T.orient_for_panel(T.to_1bit(logical), deg, display=display)
    if display in epf.MIRRORED_MODELS:
        phys = phys.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return phys


def physical_of(points, deg, display=DISPLAY):
    """Map logical points through the real pipeline, one Pillow image per point."""
    cw, ch = T.canvas_dims(deg, display=display)
    out = []
    for x, y in points:
        img = Image.new("L", (cw, ch), 255)
        img.putpixel((x, y), 0)
        phys = pipeline(img, deg, display)
        black = [(i % phys.width, i // phys.width) for i, v in enumerate(phys.convert("L").tobytes()) if v == 0]
        assert len(black) == 1, (deg, x, y, black)
        out.append(black[0])
    return out


def in_rounded_box(px, py, x0, y0, x1, y1, r=4):
    if px < x0 or px > x1 or py < y0 or py > y1:
        return False
    cx = x0 + r if px < x0 + r else (x1 - r if px > x1 - r else px)
    cy = y0 + r if py < y0 + r else (y1 - r if py > y1 - r else py)
    return (px - cx) ** 2 + (py - cy) ** 2 <= r * r


def footer_page(deg, pages=(("solar", 1), ("cat", 1), ("watch", 1))):
    plan = T.footer_plan(clock=CLOCK, pages=list(pages), orientation=deg, display=DISPLAY)
    img, draw = T.new_canvas(deg, display=DISPLAY)
    T.footer(draw, plan, page=0)
    w = plan["pages"][0]["w"]
    return img, {**plan, "cat_w": w, "cat_x1": plan["cat_x0"] + w}


def write_windows(tmp: Path, name: str, wants: list[int], room: int) -> None:
    """A rotation's windows as the add-on packs them (window.Window), for core_test's AddOn."""
    import window
    pw, ph = T.panel_dims("crowpanel_290")
    raw = ((pw + 7) // 8) * ph
    pages = [[bytes([i, k]) * (raw // 2) for k in range(n)] for i, n in enumerate(wants)]
    sleep = window.Sleep(b"\xff" * raw, 9000, 9001, epf.CAT_FLAG_SLEEP)
    w = window.Window(pages, [100 + i for i in range(len(wants))], [[1000 * (i + 1) + k for k in range(n)]
                      for i, n in enumerate(wants)], [0] * len(wants), epf.encoded_size(room + 1, room + 1, raw),
                      sleep, dict(display_model="crowpanel_290", width=pw, height=ph))
    (tmp / f"{name}.wants").write_text(" ".join(map(str, wants)))
    for at, n in enumerate(wants):
        for item in range(n):
            (tmp / f"{name}_w_{at}_{item}.epf").write_bytes(w.file(at, item)[0])
    for page in range(sum(wants)):
        (tmp / f"{name}_p_{page}.epf").write_bytes(w.file(page=page)[0])


def blank(n):
    return [Image.new("1", (792, 272), 1) for _ in range(n)]


class TestGeometry(unittest.TestCase):
    def test_server_mapping_matches_its_own_pipeline(self):
        for q, deg in enumerate((0, 90, 180, 270)):
            cw, ch = T.canvas_dims(deg, display=DISPLAY)
            geo = panel_geometry(T.footer_plan(clock=CLOCK, orientation=deg, display=DISPLAY), deg, DISPLAY)
            pts = [(0, 0), (cw - 1, 0), (0, ch - 1), (cw - 1, ch - 1), (cw // 3, ch // 5)]
            self.assertEqual([epf.to_physical(geo, x, y) for x, y in pts], physical_of(pts, deg), deg)

    def test_sent_geometry_is_where_the_pill_is_drawn(self):
        for deg in (0, 90, 180, 270):
            img, fg = footer_page(deg)
            mid = (fg["pill_y0"] + fg["pill_y1"]) // 2
            self.assertEqual(img.getpixel((fg["cat_x0"], mid)), 0, f"{deg}: left edge of the pill")
            self.assertEqual(img.getpixel((fg["cat_x1"], mid)), 0, f"{deg}: right edge of the pill")
            self.assertEqual(img.getpixel((fg["cat_x0"] + 2, fg["pill_y0"] - 2)), 255, f"{deg}: above the pill")

    def test_an_upright_panel_gets_its_pages_turned(self):
        # The 2.9"'s memory is upright (128 x 296; ESPHome's driver and Elecrow's demo):
        # at 0° a page is turned 270° into it, and the overlays follow.
        self.assertEqual(T.panel_dims("crowpanel_290"), (128, 296))
        self.assertEqual(T.panel_dims(DISPLAY), (792, 272))
        for deg in ORIENTATIONS:
            cw, ch = T.canvas_dims(deg, display="crowpanel_290")
            geo = panel_geometry(T.footer_plan(clock=CLOCK, orientation=deg, display="crowpanel_290"), deg,
                                 "crowpanel_290")
            self.assertEqual(pipeline(Image.new("L", (cw, ch), 255), deg, "crowpanel_290").size, (128, 296), deg)
            pts = [(0, 0), (cw - 1, 0), (0, ch - 1), (cw - 1, ch - 1), (cw // 3, ch // 5)]
            self.assertEqual([epf.to_physical(geo, x, y) for x, y in pts], physical_of(pts, deg, "crowpanel_290"),
                             deg)
        # Elecrow's landscape (USE_HORIZONTIAL 2): memory x = y, memory y = 295 - x.
        geo = panel_geometry(T.footer_plan(clock=CLOCK, orientation=0, display="crowpanel_290"), 0, "crowpanel_290")
        self.assertEqual(epf.to_physical(geo, 10, 3), (3, 285))

    def test_geometry_roundtrips_through_the_file(self):
        img, fg = footer_page(90)
        geo = panel_geometry(fg, 90, DISPLAY)
        data = epf.encode_epf([pipeline(img, 90)], [1], [0], [1], [fg["cat_w"]], [7], display_model=DISPLAY,
                              geometry=geo)
        self.assertEqual(epf.decode_epf(data).geometry, geo)


STRIPS = {
    "one page": [("solar", 1)],
    "long names": [("solar", 1), ("weather_forecast", 3), ("cat", 1), ("energy", 2), ("calendar", 1)],
    "two-digit counts": [(f"page_{i}", 12 if i == 3 else 1) for i in range(12)],
}
ORIENTATIONS = (0, 90, 180, 270)


def every_footer():
    for display in T.DISPLAYS:
        for deg in ORIENTATIONS:
            for strip, pages in STRIPS.items():
                yield display, deg, strip, pages, T.footer_plan(clock=CLOCK, pages=pages, orientation=deg,
                                                                display=display)


def overlays(plan, page, items):
    """What the panel draws over the footer, as (x0, x1) column ranges (components/epf/epf_core.h)."""
    cat_x1 = plan["cat_x0"] + plan["pages"][page]["w"]
    boxes = {"page pill": (plan["cat_x0"], cat_x1), "page padlock": (cat_x1 + 8, cat_x1 + 29),
             "screen padlock": ((plan["sub_x0"] - 30, plan["sub_x0"] - 9) if items > 1
                                else (plan["sub_x1"] - 22, plan["sub_x1"] - 1))}
    if items > 1:
        boxes["item pill"] = (plan["sub_x0"], plan["sub_x1"])
    return boxes


def ink_columns(img, plan, x0=0, x1=None):
    img = T.to_1bit(img)
    x1 = plan["canvas"][0] - 1 if x1 is None else x1
    return [x for y in range(plan["pill_y0"], plan["pill_y1"] + 1) for x in range(x0, x1 + 1)
            if img.getpixel((x, y)) == 0]


class TestFooterAtEverySize(unittest.TestCase):
    def test_nothing_the_footer_or_the_panel_draws_collides(self):
        for display, deg, strip, pages, plan in every_footer():
            at = (display, deg, strip)
            cw, ch = plan["canvas"]
            self.assertLess(plan["rule_y"], plan["pill_y0"], at)
            self.assertLessEqual(plan["pill_y0"] + 2 + 20 - 1, plan["pill_y1"], at)   # the padlock's rows
            self.assertLess(plan["pill_y1"], ch, at)
            img, draw = T.new_canvas(deg, display=display)
            T.footer(draw, plan)                                       # the clock alone
            self.assertLessEqual(max(ink_columns(img, plan)), plan["cat_x0"] - 6, at)
            pf = T.font(plan["pill_font"], bold=True)
            for i, (_, items) in enumerate(pages):
                boxes = sorted(overlays(plan, i, items).items(), key=lambda kv: kv[1])
                self.assertGreaterEqual(boxes[0][1][0], 0, at)
                self.assertLess(boxes[-1][1][1], cw, at)
                for (a, (a0, a1)), (b, (b0, b1)) in zip(boxes, boxes[1:]):
                    if {a, b} == {"page padlock", "screen padlock"} and (a0, a1) == (b0, b1):
                        self.assertTrue(plan["shared_lock"], at)        # one spot for both, on purpose
                        continue
                    self.assertLess(a1, b0, (at, i, a, b))
                self.assertLessEqual(T.text_width(plan["pages"][i]["label"], pf), plan["pages"][i]["w"] - 6, at)

    def test_what_gives_way_and_in_which_order(self):
        for display, deg, strip, pages, plan in every_footer():
            at = (display, deg, strip)
            labels = [p["label"] for p in plan["pages"]]
            n = len(pages)
            for i, label in enumerate(labels):              # every page always shows where it is
                self.assertTrue(label.startswith(f"{i + 1}" if plan["short"] else f"{i + 1}/{n}"), (at, label))
            if any(" " in label for label in labels):       # a name shows only while nothing else gave way
                self.assertFalse(plan["short"] or plan["shared_lock"], at)
            if plan["short"]:
                self.assertTrue(plan["shared_lock"], at)    # the padlocks share before the counts shorten
            if plan["pill_font"] < T.PILL_FONT:
                self.assertTrue(plan["short"], at)
            if plan["clock_size"] < T._footer_size(plan["canvas"][1]):
                self.assertTrue(plan["short"], at)          # the clock is the last to give way

    def test_names_fit_where_there_is_room(self):
        plan = T.footer_plan(clock=CLOCK, pages=STRIPS["long names"], orientation=0, display="crowpanel_420")
        self.assertEqual(plan["pages"][1]["label"], "2/5  WEATHER FORECAST")
        plan = T.footer_plan(clock=CLOCK, pages=STRIPS["long names"], orientation=0, display="crowpanel_290")
        self.assertEqual(plan["pages"][1]["label"], "2/5  WEATH\u2026")

    def test_the_smallest_screen_keeps_one_row(self):
        plan = T.footer_plan(clock=CLOCK, pages=STRIPS["long names"], orientation=90, display="crowpanel_290")
        self.assertEqual([p["label"] for p in plan["pages"]], ["1", "2", "3", "4", "5"])
        self.assertTrue(plan["shared_lock"])
        self.assertEqual(plan["canvas"][1] - plan["rule_y"], 32)

    def test_the_band_does_not_grow(self):
        band = {(792, 272): 32, (272, 792): 36, (400, 300): 32, (300, 400): 36, (296, 128): 25, (128, 296): 32,
                (800, 480): 36, (480, 800): 36, (960, 640): 36, (640, 960): 36}
        for display, deg, strip, pages, plan in every_footer():
            self.assertEqual(plan["canvas"][1] - plan["rule_y"], band[plan["canvas"]], (display, deg))
            self.assertEqual(T.footer_band(deg, display), band[plan["canvas"]])

    def test_the_pills_stay_put_as_the_minutes_change(self):
        for display in T.DISPLAYS:
            for deg in (0, 90):
                plans = [T.footer_plan(clock=c, pages=STRIPS["long names"], orientation=deg, display=display)
                         for c in ("00:00", "11:11", "14:05", "23:59")]
                self.assertEqual(len({(p["cat_x0"], p["sub_x0"]) for p in plans}), 1, (display, deg))

    def test_a_label_without_pills_stays_clear_of_the_clock(self):
        for display in T.DISPLAYS:
            for deg in ORIENTATIONS:
                plan = T.footer_plan(clock=CLOCK, orientation=deg, display=display)
                img, draw = T.new_canvas(deg, display=display)
                T.footer(draw, plan, label="A preview label much longer than any footer")
                self.assertEqual(ink_columns(img, plan, plan["clock_end"] + 1, plan["cat_x0"] - 1), [],
                                 (display, deg))


@unittest.skipUnless(shutil.which("c++"), "no C++ compiler")
class TestFirmwareCore(unittest.TestCase):
    def test_core_against_real_frame_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for q, deg in enumerate((0, 90, 180, 270)):
                img, fg = footer_page(deg)
                geo = panel_geometry(fg, deg, DISPLAY)
                (tmp / f"orient{q}.epf").write_bytes(epf.encode_epf(
                    [pipeline(img, deg)], [11], [0], [1], [fg["cat_w"]], [21], display_model=DISPLAY,
                    orientation_180=(deg == 180), geometry=geo))
                cw, ch = T.canvas_dims(deg, display=DISPLAY)
                pts = [(0, 0), (cw - 1, ch - 1), (fg["cat_x0"], fg["pill_y0"]), (cw // 2, ch // 3)]
                (tmp / f"orient{q}.vectors").write_text(
                    "".join(f"{x} {y} {px} {py}\n" for (x, y), (px, py) in zip(pts, physical_of(pts, deg))))
                mask = Image.new("L", (cw, ch), 255)
                for y in range(fg["pill_y0"], fg["pill_y1"] + 1):
                    for x in range(fg["cat_x0"], fg["cat_x1"] + 1):
                        if in_rounded_box(x, y, fg["cat_x0"], fg["pill_y0"], fg["cat_x1"], fg["pill_y1"]):
                            mask.putpixel((x, y), 0)
                phys = pipeline(mask, deg)
                (tmp / f"orient{q}.pill").write_text("".join(
                    f"{i % phys.width} {i // phys.width}\n" for i, v in enumerate(phys.convert("L").tobytes()) if v == 0))

            plan = T.footer_plan(clock=CLOCK, pages=[("solar", 1)], orientation=0, display="crowpanel_290")
            page, _ = T.new_canvas(0, display="crowpanel_290")
            pw, ph = T.panel_dims("crowpanel_290")
            (tmp / "upright.epf").write_bytes(epf.encode_epf(
                [pipeline(page, 0, "crowpanel_290")], [1], [0], [1], [plan["pages"][0]["w"]], [2],
                display_model="crowpanel_290", width=pw, height=ph,
                geometry=panel_geometry(plan, 0, "crowpanel_290")))

            (tmp / "legacy180.epf").write_bytes(epf.encode_epf(
                blank(1), [1], [0], [1], [110], [2], display_model=DISPLAY, orientation_180=True))
            (tmp / "nav_a.epf").write_bytes(epf.encode_epf(
                blank(5), [100, 200, 300], [0, 1, 4], [1, 3, 1], [110] * 3, [1, 21, 22, 23, 3], display_model=DISPLAY))
            (tmp / "nav_b.epf").write_bytes(epf.encode_epf(
                blank(6), [100, 150, 200, 300], [0, 1, 2, 5], [1, 1, 3, 1], [110] * 4, [1, 15, 21, 22, 23, 3],
                display_model=DISPLAY))
            (tmp / "nav_alert.epf").write_bytes(epf.encode_epf(
                blank(1), [900], [0], [1], [110], [90], display_model=DISPLAY, alert_interrupt=True))

            # The same 800 x 480 pages of words, deflated and as they are.
            words = []
            for n in range(3):
                pg, draw = T.new_canvas(0, display="seeed_xiao_750")
                draw.text((40, 40 + 30 * n), f"Page {n}: 21.5 degrees, rain at 16:00", fill=0, font=T.font(48))
                words.append(T.to_1bit(pg))
            for name, deflate in (("deflated", True), ("as_is", False)):
                (tmp / f"{name}.epf").write_bytes(epf.encode_epf(
                    words, [1, 2, 3], [0, 1, 2], [1, 1, 1], [0, 0, 0], [11, 12, 13], display_model="seeed_xiao_750",
                    width=800, height=480, deflate=deflate))

            # A moving window's files (window.py), every place, item and show_page, for two
            # rotations too big to hold: 20 pages of one item with room for 10, and one with a
            # page of nine items with room for six pictures.
            for name, wants, room in (("wide", [1] * 20, 10), ("tall", [1, 1, 3, 1, 1, 9, 1, 1], 6)):
                write_windows(tmp, name, wants, room)

            exe = tmp / "core_test"
            # With AddressSanitizer and UndefinedBehaviorSanitizer where the compiler has them,
            # so the parser fuzzer in core_test catches memory errors, not only wrong answers.
            source = str(ROOT / "tests" / "firmware" / "core_test.cpp")
            flags = ["c++", "-std=c++17", "-O1", "-Wall", "-Wextra", "-o", str(exe), source, "-lz"]
            build = subprocess.run(flags[:1] + ["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                                                "-fno-omit-frame-pointer"] + flags[1:], capture_output=True, text=True)
            if build.returncode != 0:
                build = subprocess.run(flags, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(exe), str(tmp)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


# The repository's copies of the generator's output for a reference setup, one per
# board family: the CrowPanel 5.79" (upside down) and the Seeed XIAO 7.5".
REFERENCES = {
    DISPLAY: ("crowpanel-epaper", 180, ROOT / "esphome" / "crowpanel-epaper.yaml"),
    "seeed_xiao_750": ("xiao-epaper", 0, ROOT / "esphome" / "xiao-epaper.yaml"),
}


def reference_yaml(display=DISPLAY):
    version = re.search(r'^version:\s*"([^"]+)"', (ROOT / "addon" / "config.yaml").read_text(), re.M).group(1)
    name, orientation, _ = REFERENCES[display]
    return firmware_gen.render(
        disp=T.get_display(display), version=version, device_name=name,
        frames_url='"http://homeassistant.local:8099/frames.epf"', ota_key="!secret api_encryption_key",
        wifi_ssid="!secret wifi_ssid", wifi_password="!secret wifi_password",
        interval_min=5, orientation=orientation), version


def offered_sizes():
    """The CrowPanel sizes the editor offers."""
    return [k for k, d in T.DISPLAYS.items() if d.get("kind") == "crowpanel" and d.get("offered", True)]


# A made-up key that isn't all zeros (ESPHome refuses that one).
TEST_KEY = '"AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="'


def local_build(display, **kw):
    """What Panel setup writes for `display`, with the epf component taken from this
    checkout instead of the release tag (the tag doesn't exist yet)."""
    text = firmware_gen.render(
        disp=T.get_display(display), version="1.2.3", device_name="kitchen",
        frames_url='"http://192.0.2.1:8099/frames.epf"', ota_key=TEST_KEY, interval_min=5,
        **{"wifi_ssid": '"home"', "wifi_password": '"password1"', "orientation": 0, **kw})
    tagged = "  - source: github://bek00letz/epaper-panel@v1.2.3\n"
    assert tagged in text
    return text.replace(tagged, f"  - source:\n      type: local\n      path: {ROOT / 'components'}\n")


class TestFirmwareYaml(unittest.TestCase):
    def test_pinned_to_the_release_and_complete(self):
        text, version = reference_yaml()
        self.assertIn(f"github://bek00letz/epaper-panel@v{version}\n", text)
        self.assertNotIn("@main", text)
        self.assertNotIn("refresh: 0s", text)
        self.assertIn(firmware_gen.CROWPANEL_COMPONENT, text)
        self.assertNotIn("online_image", text)
        self.assertNotRegex(text, r"@[A-Z][A-Z_]+@")

    def test_it_names_its_network_to_home_assistant(self):
        """The editor's Connection row says which Wi-Fi it's on (panel_link's "network")."""
        text, _ = reference_yaml()
        self.assertRegex(text, r"ssid:\n\s+id: wifi_ssid\n\s+name: Panel Wi-Fi network\n")

    def test_repository_copy_is_the_generator_output(self):
        for display, (_, _, path) in REFERENCES.items():
            text, _ = reference_yaml(display)
            self.assertEqual(path.read_text(), text,
                             f"esphome/{path.name} is out of date; regenerate it with "
                             "`python tests/test_firmware.py --write-reference`")

    def test_one_network_connects_straight_away_several_are_scanned_for(self):
        one = firmware_gen.wifi_block([('"home"', '"pw"')])
        self.assertIn("fast_connect: true", one)
        several = firmware_gen.wifi_block([('"home"', '"pw"'), ('"work"', '"pw2"')])
        self.assertNotIn("fast_connect", several, "a fast connect only ever tries the first network")
        self.assertEqual(several.count("- ssid:"), 2)

    def test_its_own_wifi_when_it_finds_none_it_knows(self):
        block = firmware_gen.wifi_block([('"home"', '"pw"')], ('"Kitchen setup"', '"abcdefghjkmn"'))
        self.assertIn('  ap:\n    ssid: "Kitchen setup"\n    password: "abcdefghjkmn"', block)
        self.assertIn("\ncaptive_portal:", block, "a page for choosing a network")
        self.assertNotIn("ap:", firmware_gen.wifi_block([('"home"', '"pw"')]))

    def test_a_blank_network_is_left_out(self):
        # ESPHome refuses `ssid: ""` (break-it #5): with its own Wi-Fi on, a panel
        # with no network yet gets only that, and chooses one from a phone.
        hotspot = ('"Kitchen setup"', '"abcdefghjkmn"')
        only = firmware_gen.wifi_block([('""', '""')], hotspot)
        self.assertNotIn("ssid: \"\"", only)
        self.assertNotIn("networks:", only)
        self.assertNotIn("fast_connect", only)
        self.assertIn('  ap:\n    ssid: "Kitchen setup"', only)
        self.assertIn("\ncaptive_portal:", only)
        rest = firmware_gen.wifi_block([('""', '""'), ('"work"', '"pw2"')], hotspot)
        self.assertNotIn('ssid: ""', rest)
        self.assertIn('  ssid: "work"\n  password: "pw2"\n  fast_connect: true', rest, "one network left: straight away")
        text = firmware_gen.render(
            disp=T.get_display(DISPLAY), version="1.2.3", device_name="kitchen", frames_url='"http://x/frames.epf"',
            ota_key=TEST_KEY, wifi_ssid='""', wifi_password='""', interval_min=5, orientation=0, hotspot=hotspot)
        self.assertNotIn('ssid: ""', text)

    def test_panel_setup_turns_it_on_with_its_own_password(self):
        import devices
        import panel_setup
        from test_devices import fresh_data_dir
        fresh_data_dir()
        try:
            dev = devices.add("crowpanel", "A rather long kitchen panel name", "crowpanel_579")
            cfg = panel_setup.load_panel_setup(dev)
            self.assertEqual(len(cfg["hotspot_password"]), 12)
            name = panel_setup.hotspot_name(devices.get(dev["id"]))
            self.assertLessEqual(len(name), 32, "a Wi-Fi name holds 32 characters")
            self.assertTrue(name.endswith(" setup"))
            text, _ = panel_setup.generate_esphome_yaml(cfg, devices.get(dev["id"]))
            self.assertIn(f'password: "{cfg["hotspot_password"]}"', text)
            text, _ = panel_setup.generate_esphome_yaml({**cfg, "hotspot": False}, devices.get(dev["id"]))
            self.assertNotIn("captive_portal", text)
        finally:
            support.use_test_data_dir()

    def test_home_assistant_calls_the_panel_by_its_screens_name(self):
        text = firmware_gen.render(
            disp=T.get_display(DISPLAY), version="1.2.3", device_name="kitchen", frames_url='"https://x/frames.epf"',
            ota_key=TEST_KEY, wifi_ssid='"a"', wifi_password='"b"', interval_min=5, orientation=0,
            friendly_name='"Kitchen"')
        self.assertIn('friendly_name: "Kitchen"', text)

    def test_the_client_checks_https_against_the_certificate_bundle(self):
        client = (ROOT / "components" / "epf" / "epf_client.h").read_text()
        self.assertIn("esp_crt_bundle_attach", client)
        self.assertIn("CONFIG_MBEDTLS_CERTIFICATE_BUNDLE", (ROOT / "components" / "epf" / "__init__.py").read_text())

    def test_low_power_mode_is_compiled_in_and_never_sleeps_on_its_own(self):
        text, _ = reference_yaml()
        block = text.split("\ndeep_sleep:\n", 1)[1].split("\n\n", 1)[0]
        self.assertNotIn("run_duration", block, "only an answer from the add-on puts it to sleep")
        self.assertNotIn("sleep_duration", block)
        self.assertNotIn("esp32_ext1_wakeup", block, "the buttons are set as wake sources at sleep time")
        self.assertIn("epf::power_prepare_sleep(millis(), (1ULL << 1) | (1ULL << 2) | (1ULL << 4) | (1ULL << 5) | (1ULL << 6))",
                      text, "all five buttons wake it, whichever way it's mounted")
        self.assertIn("reboot_timeout: 0s", text.split("\napi:\n", 1)[1].split("\n\n", 1)[0],
                      "Home Assistant being away never restarts it")
        self.assertIn("epf::power_begin(7);", text, "the first download says why it's awake")
        self.assertIn("epf::power_note_download(millis(), result);", text)
        self.assertIn("on_begin:\n      - lambda: 'epf::PowerPolicy::instance().hold(true);'", text, "never asleep mid-update")
        self.assertEqual(text.count("epf::PowerPolicy::instance().note_press(millis());"), 5, "every button counts as a press")

    def test_it_sleeps_only_once_the_display_is_done(self):
        # Deep sleep cuts the display's power: a refresh still running would be cut short.
        self.assertEqual(firmware_gen.display_settled(T.get_display("crowpanel_579")), "id(epd).is_idle()")
        waveshare = T.get_display("crowpanel_290")
        self.assertIn("last_redraw_ms", firmware_gen.display_settled(waveshare))
        self.assertTrue(firmware_gen.display_settled(waveshare).startswith("id(last_redraw_ms) == 0 ||"),
                        "nothing redrawn since it woke: settled at once, not 6 s later (break-it #10)")
        for disp in ("crowpanel_579", "crowpanel_290"):
            text = firmware_gen.render(
                disp=T.get_display(disp), version="1.2.3", device_name="kitchen", frames_url='"http://x/frames.epf"',
                ota_key=TEST_KEY, wifi_ssid='"a"', wifi_password='"b"', interval_min=5, orientation=0)
            self.assertIn(f"!({firmware_gen.display_settled(T.get_display(disp))})", text)

    def test_it_builds_with_or_without_its_own_wifi(self):
        # get_ap() only exists when the panel has its own Wi-Fi (ESPHome's USE_WIFI_AP):
        # unguarded, a panel set up without it didn't compile (fixed 2026-10-20).
        text, _ = reference_yaml()
        self.assertNotIn("captive_portal", text, "the reference is the setup without it")
        body = text.split("#ifdef USE_WIFI_AP", 1)
        self.assertEqual(len(body), 2, "the setup-Wi-Fi screen is only built with its own Wi-Fi")
        guarded, after = body[1].split("#endif", 1)
        self.assertIn("get_ap()", guarded)
        self.assertNotIn("get_ap()", body[0] + after)

    @unittest.skipUnless((ROOT / ".esphome-venv" / "bin" / "python").exists(), "no ESPHome here")
    def test_esphome_reads_it_with_or_without_its_own_wifi(self):
        # A text check isn't enough: a "#" at the start of a line inside a lambda
        # ends the lambda and reads as a YAML comment.
        for hotspot in (None, ('"Kitchen setup"', '"abcdefghjkmn"')):
            text = firmware_gen.render(
                disp=T.get_display(DISPLAY), version="1.2.3", device_name="kitchen",
                frames_url='"http://x/frames.epf"', ota_key=TEST_KEY, wifi_ssid='"a"', wifi_password='"b"',
                interval_min=5, orientation=0, hotspot=hotspot)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "panel.yaml"
                path.write_text(text)
                out = subprocess.run(
                    [str(ROOT / ".esphome-venv" / "bin" / "python"), "-c",
                     "import sys, pathlib; from esphome import yaml_util; "
                     "d = yaml_util.load_yaml(pathlib.Path(sys.argv[1])); "
                     "print(str(d['display'][0]['lambda']))", str(path)],
                    capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr[-500:])
            self.assertIn("#ifdef USE_WIFI_AP", out.stdout, "the guard is inside the lambda")
            self.assertIn("get_ap()", out.stdout)

    @unittest.skipUnless((ROOT / ".esphome-venv" / "bin" / "esphome").exists(), "no ESPHome here")
    def test_esphome_accepts_every_offered_size(self):
        # break-it #3: only the 5.79" was ever checked, and the other sizes didn't
        # build. ESPHome's own check (`esphome config`) on what Panel setup writes,
        # with the epf component from this checkout, for every size the editor
        # offers: one network; no network with its own Wi-Fi, upside down; several.
        offered = offered_sizes()
        self.assertIn(DISPLAY, offered)
        variants = [
            dict(wifi_ssid='"home"', wifi_password='"password1"', orientation=0),
            dict(wifi_ssid='""', wifi_password='""', orientation=180, hotspot=('"Kitchen setup"', '"abcdefghjkmn"')),
            dict(wifi_ssid='"home"', wifi_password='"password1"', orientation=90,
                 more_networks=[('"work"', '"password2"')], hotspot=('"Kitchen setup"', '"abcdefghjkmn"')),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "ESPHOME_DATA_DIR": str(Path(tmp) / "data")}   # the driver is fetched once
            for display in offered:
                for i, variant in enumerate(variants):
                    path = Path(tmp) / f"{display}-{i}.yaml"
                    path.write_text(local_build(display, **variant))
                    out = subprocess.run([str(ROOT / ".esphome-venv" / "bin" / "esphome"), "config", str(path)],
                                         capture_output=True, text=True, timeout=300, env=env)
                    self.assertEqual(out.returncode, 0, f"{display}, variant {i}:\n{out.stdout[-1500:]}{out.stderr[-500:]}")

    def test_every_offered_size_has_a_full_refresh_its_driver_has(self):
        # force_full_update() is the CrowPanel driver's; the Waveshare one has no such
        # call (break-it #3: the 7.5" didn't compile because of it). A driver whose every
        # refresh is full (the Seeed XIAO 7.5") needs none, and has no count to set.
        for display in offered_sizes():
            disp = T.get_display(display)
            call = firmware_gen.full_refresh(disp)
            self.assertEqual(call == "{}", bool(disp.get("always_full")), display)
            text = local_build(display)
            redraw = text.split("  - id: redraw\n", 1)[1].split("\n\n", 1)[0]
            self.assertIn(f"begin_redraw()) {call}", redraw, display)
            self.assertEqual(text.count("force_full_update()"), redraw.count("force_full_update()"),
                             "only the redraw script asks for a full refresh")
            self.assertEqual("full_update_every" in text, not disp.get("always_full"), display)
            if disp["esphome_component"] == "waveshare_epaper":
                spi = firmware_gen.board_of(disp)["spi"]
                self.assertIn(f"\nspi:\n  clk_pin: {spi['clk']}\n  mosi_pin: {spi['mosi']}\n", text, display)
                self.assertNotIn("force_full_update", text, display)

    def test_a_sleeping_panel_keeps_its_picture(self):
        # TRMNL's way (0.13): the display stays powered through deep sleep, and its
        # driver is told it still holds the picture, so the first change is partial.
        # A board whose display is always powered and fully refreshed (the Seeed XIAO
        # 7.5") holds no pin and keeps nothing: its every change is a full refresh.
        for display in offered_sizes():
            disp = T.get_display(display)
            pin = firmware_gen.board_of(disp)["display_power"]
            text = local_build(display)
            boot = text.split("  on_boot:\n", 1)[1].split("\n\n", 1)[0]
            self.assertIn(f"if (epf::PowerPolicy::instance().picture_kept()) {firmware_gen.keep_picture(disp)}", boot)
            if disp.get("always_full"):
                self.assertIn("epf::power_begin(-1);", boot, display)
                self.assertEqual(firmware_gen.keep_picture(disp), "{}", display)
                continue
            self.assertNotEqual(firmware_gen.keep_picture(disp), "{}", display)
            if pin is None:
                # Always powered (the Seeed XIAO 7.5"): it keeps its picture with nothing to hold.
                self.assertIn("epf::power_begin(epf::DISPLAY_ALWAYS_POWERED);", boot, display)
                self.assertNotIn("id: epd_power", text, display)
                continue
            self.assertIn(f"epf::power_begin({pin});", boot, display)
            self.assertIn(f"switch:\n  - platform: gpio\n    pin: {pin}\n", text, "the pin it holds is the display's power")

    def test_the_first_refresh_after_a_sleep_drives_every_pixel(self):
        # The 5.79", 29 Oct: the controller's memory of the picture didn't survive deep
        # sleep, so each page's black stayed on screen. After the first picture of such a
        # wake is drawn, and before its refresh, its driver's call writes it inverted into
        # that memory (epf_client.h): a partial refresh then drives every pixel.
        for display in offered_sizes():
            disp = T.get_display(display)
            call = firmware_gen.drive_every_pixel(disp)
            self.assertEqual(call, disp["drive_every_pixel"] or "{}", display)
            self.assertEqual(call == "{}", bool(disp.get("always_full")), "only a full refresh needs no help")
            text = local_build(display)
            lam = text.split("    lambda: |-\n", 1)[1].split("\n\n", 1)[0]
            line = f"if (epf::PowerPolicy::instance().take_first_refresh()) {call}"
            self.assertIn(line, lam, display)
            self.assertGreater(lam.index(line), lam.index("client.draw_overlays"), "after the whole picture is drawn")
            self.assertEqual(text.count("take_first_refresh()"), 1, "asked once, where the picture is drawn")
        # Each driver's own call, and a cascade says it's two controllers.
        self.assertIn("crowpanel_drive_every_pixel(id(epd), 2)", T.get_display("crowpanel_579")["drive_every_pixel"])
        self.assertIn("crowpanel_drive_every_pixel(id(epd), 1)", T.get_display("crowpanel_420")["drive_every_pixel"])
        self.assertIn("waveshare_drive_every_pixel(id(epd))", T.get_display("crowpanel_290")["drive_every_pixel"])
        self.assertIn("uc8179_drive_every_pixel(id(epd))", T.get_display("seeed_xiao_750")["drive_every_pixel"])

    def test_a_size_that_cant_drive_every_pixel_switches_its_display_off(self):
        # Without a way to make its first refresh after a wake drive every pixel, a partial
        # refresh would stack pictures: that size sleeps as 0.12 did, a full refresh after
        # every wake. Decided by its profile, never by its name.
        disp = dict(T.get_display(DISPLAY))
        disp["drive_every_pixel"] = ""
        self.assertEqual(firmware_gen.keep_display_pin(disp), -1)
        self.assertEqual(firmware_gen.keep_picture(disp), "{}")
        self.assertEqual(firmware_gen.drive_every_pixel(disp), "{}")
        text = firmware_gen.render(disp=disp, version="0.22.0", device_name="p", frames_url="http://h/f.epf", ota_key="k",
                                   wifi_ssid='"x"', wifi_password='"y"', interval_min=5, orientation=0)
        self.assertIn("epf::power_begin(-1);", text)
        self.assertIn("if (epf::PowerPolicy::instance().take_first_refresh()) {}", text)

    def test_a_press_before_the_frames_arrive_keeps_the_picture(self):
        # After a deep sleep the frames aren't in memory: a redraw then drew "waiting
        # for frames" over the picture on screen.
        text, _ = reference_yaml()
        redraw = text.split("  - id: redraw\n", 1)[1].split("\n\n", 1)[0]
        self.assertIn("if (epf::may_redraw()) return true;", redraw)
        self.assertLess(redraw.index("epf::may_redraw()"), redraw.index("component.update: epd"))
        client = (ROOT / "components" / "epf" / "epf_client.h").read_text()
        self.assertIn("has_stream() || (PowerPolicy::instance().wake() == Wake::BOOT && !c.lost_stream())", client)
        self.assertIn("if (c.replacing()) {", client, "one buffer: nothing drawn while a download fills it")

    def test_the_way_back_switches_the_display_off_in_deep_sleep(self):
        # Until it's proven on a real panel: KEEP_DISPLAY_ASLEEP = False is 0.12's way.
        keep = firmware_gen.KEEP_DISPLAY_ASLEEP
        try:
            firmware_gen.KEEP_DISPLAY_ASLEEP = False
            text = local_build(DISPLAY)
        finally:
            firmware_gen.KEEP_DISPLAY_ASLEEP = keep
        self.assertIn("epf::power_begin(-1);", text)
        self.assertIn("if (epf::PowerPolicy::instance().picture_kept()) {}", text)
        self.assertIn("if (epf::PowerPolicy::instance().take_first_refresh()) {}", text)

    def test_mounting_upside_down_swaps_the_buttons(self):
        crowpanel = T.BOARDS["crowpanel_s3"]
        self.assertEqual(firmware_gen.button_pins(crowpanel, 180)["next"], 6)
        self.assertEqual(firmware_gen.button_pins(crowpanel, 0)["next"], 4)
        self.assertEqual(firmware_gen.button_pins(crowpanel, 270)["ok"], 5, "the centre stays the centre")
        xiao = T.BOARDS["xiao_c3"]
        self.assertEqual(firmware_gen.button_pins(xiao, 0), firmware_gen.button_pins(xiao, 180), "one button")


def render_for(display, **kw):
    return firmware_gen.render(**{
        "disp": T.get_display(display), "version": "1.2.3", "device_name": "kitchen",
        "frames_url": '"http://x/frames.epf"', "ota_key": TEST_KEY, "wifi_ssid": '"a"', "wifi_password": '"b"',
        "interval_min": 5, "orientation": 0, **kw})


class TestBoards(unittest.TestCase):
    """The board is part of a size's profile (theme.BOARDS): one template, switched by it."""

    def test_a_way_back_overrides_only_firmware_facts(self):
        for d, p in T.DISPLAYS.items():
            back = p.get("full_only")
            if back:
                self.assertLessEqual(set(back), {"esphome_model", "always_full", "full_refresh", "keep_picture",
                                                 "drive_every_pixel", "refresh_waits"}, d)

    def test_every_esphome_size_names_a_board_the_generator_knows(self):
        for d, p in T.DISPLAYS.items():
            if p.get("kind") != "crowpanel":
                continue
            self.assertIn(p.get("board"), T.BOARDS, d)
        for name, board in T.BOARDS.items():
            self.assertIn(board["chip"], firmware_gen.CHIPS, name)
            self.assertTrue(board["buttons"], f"{name}: a board needs a button (binary_sensor can't be empty)")
            self.assertEqual(set(board["buttons"]), set(board["buttons_turned"]), f"{name}: the same buttons turned over")
            self.assertLessEqual(set(board["buttons"]), set(firmware_gen.BUTTON_ROLES), name)
            used = [*board["spi"].values(), *board["display_pins"].values(), *set(board["buttons"].values())]
            if board["display_power"] is not None:
                used.append(board["display_power"])
            self.assertEqual(len(used), len(set(used)), f"{name}: no pin does two jobs")

    def test_the_crowpanel_wakes_on_all_five_buttons_the_xiao_on_none(self):
        self.assertEqual(firmware_gen.wake_mask(T.BOARDS["crowpanel_s3"]),
                         "(1ULL << 1) | (1ULL << 2) | (1ULL << 4) | (1ULL << 5) | (1ULL << 6)")
        # The C3 wakes only on GPIO 0-5, and the display uses them: Boot (GPIO 9) can't.
        self.assertEqual(firmware_gen.wake_mask(T.BOARDS["xiao_c3"]), "0")
        self.assertIn("power_prepare_sleep(millis(), 0);", render_for("seeed_xiao_750"))
        # Decided by the chip, never by the board's name: a C3 button on GPIO 3 would wake it.
        other = {**T.BOARDS["xiao_c3"], "buttons": {"next": 3, "one": 9}}
        self.assertEqual(firmware_gen.wake_buttons(other), [3])
        self.assertEqual(firmware_gen.wake_mask(other), "(1ULL << 3)")

    def test_the_xiao_builds_for_its_own_board(self):
        text = render_for("seeed_xiao_750")
        self.assertIn("esp32:\n  board: esp32-c3-devkitm-1\n  framework:\n    type: esp-idf\n", text)
        self.assertNotIn("psram:", text, "no PSRAM on the XIAO ESP32-C3")
        self.assertNotIn("id: epd_power", text, "its display is always powered")
        # Seeed's ESPHome cookbook for this panel's pins; ESPHome's partial-refresh driver for its screen.
        self.assertIn('  - platform: waveshare_epaper\n    id: epd\n    model: "7.50inv2p"\n    cs_pin: 3\n    dc_pin: 5\n'
                      "    busy_pin:\n      number: 4\n      inverted: true\n    reset_pin: 2\n", text)
        self.assertIn("\nspi:\n  clk_pin: 8\n  mosi_pin: 10\n", text)
        # One button, the XIAO's Boot, and it counts as a press.
        self.assertIn("pin: {number: 9, mode: {input: true, pullup: true}, inverted: true}", text)
        self.assertEqual(text.count("- platform: gpio\n    id: key_"), 1)
        self.assertEqual(text.count("epf::PowerPolicy::instance().note_press(millis());"), 1)
        # Its refresh returns once the screen is done: asleep as soon as it's drawn.
        self.assertIn("|| !(true);", text)
        self.assertNotRegex(text, r"@[A-Z][A-Z_]+@|@IF ")

    def test_the_xiao_refreshes_partially_by_the_panels_policy(self):
        # Partial refresh, as on a CrowPanel: the ghost-clearing policy decides when a
        # refresh is full (the driver's own count restarts), the driver's count is out of
        # reach, and a sleep keeps the picture with the display always powered, its first
        # refresh after a wake driving every pixel.
        text = render_for("seeed_xiao_750")
        redraw = text.split("  - id: redraw\n", 1)[1].split("\n\n", 1)[0]
        self.assertIn("begin_redraw()) epf::full_refresh_next(id(epd));", redraw)
        self.assertIn("    full_update_every: 1000000\n", text)
        for setting in ('name: "Ghost clear after"', 'name: "Ghost clearing"', 'name: "Clear ghosting"'):
            self.assertIn(setting, text)
        self.assertIn("epf::power_begin(epf::DISPLAY_ALWAYS_POWERED);", text)
        self.assertIn("picture_kept()) epf::waveshare_picture_kept(id(epd));", text)
        self.assertIn("take_first_refresh()) epf::uc8179_drive_every_pixel(id(epd));", text)
        self.assertIn("first change is partial", text.split("  - id: go_to_sleep\n", 1)[0].rsplit("script:", 1)[1])
        client = (ROOT / "components" / "epf" / "epf_client.h").read_text()
        self.assertIn("constexpr int DISPLAY_ALWAYS_POWERED = -2;", client)
        self.assertEqual(firmware_gen.ALWAYS_POWERED, -2, "the generator and the firmware agree")
        self.assertIn("s->command(0x10);", client.split("uc8179_drive_every_pixel", 1)[1].split("Ram::seed", 1)[0],
                      "the UC8179's previous-picture memory")

    def test_it_asks_for_deflated_pages_unless_switched_back(self):
        # On by default (the component's own default), so a CrowPanel's file doesn't change.
        self.assertIn("\nepf:\n", render_for(DISPLAY))
        client = (ROOT / "components" / "epf" / "epf_client.h").read_text()
        self.assertIn('(INFLATER ? "&deflate=1" : "")', client, "asks only when it can inflate")
        self.assertIn("cv.Optional(CONF_DEFLATE, default=True)", (ROOT / "components" / "epf" / "__init__.py").read_text())
        keep = firmware_gen.DEFLATE_FRAMES
        try:
            firmware_gen.DEFLATE_FRAMES = False
            self.assertIn("\nepf:\n  deflate: false\n", render_for(DISPLAY))
            self.assertIn("\nepf:\n  deflate: false\n", render_for("seeed_xiao_750"))
        finally:
            firmware_gen.DEFLATE_FRAMES = keep

    def test_it_moves_a_window_unless_switched_back(self):
        # On by default (the component's own default), so `epf:` stays as it was. The firmware
        # says where it is on every download, and starts the download the window asks for.
        self.assertIn("\nepf:\n", render_for(DISPLAY))
        client = (ROOT / "components" / "epf" / "epf_client.h").read_text()
        self.assertIn("+ window_query_();", client)
        self.assertIn("#ifdef USE_EPF_WINDOW", client)
        self.assertIn("cv.Optional(CONF_WINDOW, default=True)", (ROOT / "components" / "epf" / "__init__.py").read_text())
        for display in (DISPLAY, "seeed_xiao_750"):
            text = render_for(display)
            self.assertIn("panel.take_window_fetch(id(redraw).is_running())", text)
            self.assertIn("if (result != epf::FetchResult::OK) panel.window_unanswered();", text)
        keep = firmware_gen.MOVING_WINDOW
        try:
            firmware_gen.MOVING_WINDOW = False
            self.assertIn("\nepf:\n  window: false\n", render_for(DISPLAY))
            self.assertIn("\nepf:\n  window: false\n", render_for("seeed_xiao_750"))
        finally:
            firmware_gen.MOVING_WINDOW = keep

    def test_the_way_back_is_a_full_refresh_every_time(self):
        # Until partial refresh is proven on a real XIAO: PARTIAL_REFRESH = False builds
        # it as first built (ESPHome's 7.50inv2, a flash on every change). CrowPanels don't change.
        crow = render_for(DISPLAY)
        keep = firmware_gen.PARTIAL_REFRESH
        try:
            firmware_gen.PARTIAL_REFRESH = False
            text = render_for("seeed_xiao_750")
            self.assertEqual(render_for(DISPLAY), crow, "only a screen with a way back")
        finally:
            firmware_gen.PARTIAL_REFRESH = keep
        self.assertIn('model: "7.50inv2"\n', text)
        self.assertNotIn("full_update_every", text, "ESPHome refuses a count for a full-only driver")
        self.assertIn("epf::power_begin(-1);", text)
        self.assertIn("picture_kept()) {}", text)
        self.assertIn("take_first_refresh()) {}", text)
        self.assertIn("begin_redraw()) {}", text)
        for setting in ('name: "Ghost clear after"', 'name: "Ghost clearing"', 'name: "Clear ghosting"', "id(ghost_"):
            self.assertNotIn(setting, text)

    def test_the_crowpanel_keeps_everything_it_had(self):
        text = render_for(DISPLAY)
        for part in ("psram:\n  mode: octal\n", "id: epd_power", "id: ghost_clear_after", "id: ghost_mode",
                     'name: "Clear ghosting"', "id: key_next", "id: key_prev", "id: key_ok", "id: key_top",
                     "id: key_bottom", "board: esp32-s3-devkitc-1"):
            self.assertIn(part, text)
        self.assertNotIn("id: key_one", text)

    def test_sections_are_switched_by_flags_only(self):
        self.assertEqual(firmware_gen.sections("a\n@IF X@\nb\n@END@\nc\n", {"X": True}), "a\nb\nc\n")
        self.assertEqual(firmware_gen.sections("a\n@IF X@\nb\n@END@\nc\n", {"X": False}), "a\nc\n")
        with self.assertRaises(ValueError):
            firmware_gen.sections("@IF Y@\nb\n@END@\n", {"X": True})

    def test_a_driver_that_waits_is_settled_when_the_redraw_is(self):
        # ESPHome's 7.50inv2 returns from its refresh only once the screen is done: the
        # panel sleeps straight after, not 6 s later.
        self.assertEqual(firmware_gen.display_settled(T.get_display("seeed_xiao_750")), "true")

    def test_a_panel_without_psram_is_taken_at_its_word(self):
        # About 100 KB on a XIAO ESP32-C3: rounding it up would send files it can't hold.
        import devices
        import runtime
        from test_devices import fresh_data_dir
        fresh_data_dir()
        try:
            dev = devices.add("crowpanel", "Hall", "seeed_xiao_750")
            runtime.set_panel_capacity(dev["id"], 100 * 1024)
            self.assertEqual(runtime.panel_capacity(dev["id"]), 100 * 1024)
            runtime.set_panel_capacity(dev["id"], 12)
            self.assertEqual(runtime.panel_capacity(dev["id"]), runtime.MIN_CAPACITY, "a number that can't be real")
        finally:
            support.use_test_data_dir()

    def test_the_editor_offers_it_with_the_crowpanels(self):
        from kinds import crowpanel
        self.assertIn("seeed_xiao_750", crowpanel.CrowPanel().displays())
        self.assertEqual(T.get_display("seeed_xiao_750")["name"], 'Seeed XIAO 7.5"')


if __name__ == "__main__":
    if "--write-reference" in sys.argv:
        for display, (_, _, path) in REFERENCES.items():
            path.write_text(reference_yaml(display)[0])
            print(f"wrote esphome/{path.name}")
    else:
        unittest.main()


class TestASizesFactsAreInItsProfile(unittest.TestCase):
    """A CrowPanel size's firmware facts live in its profile, so a new size can't miss one quietly (review #8)."""
    FACTS = ("frame_model", "mirrored", "full_refresh", "keep_picture", "drive_every_pixel")

    def test_every_offered_size_has_each(self):
        offered = [d for d, p in T.DISPLAYS.items() if p.get("kind") == "crowpanel" and p.get("offered", True)]
        self.assertGreaterEqual(len(offered), 3)
        models = [T.DISPLAYS[d]["frame_model"] for d in T.DISPLAYS if "frame_model" in T.DISPLAYS[d]]
        self.assertEqual(len(models), len(set(models)), "frame ids are unique")
        for d in offered:
            p = T.DISPLAYS[d]
            for fact in self.FACTS:
                self.assertIn(fact, p, f"{d} has no {fact}")
            self.assertIsInstance(p["mirrored"], bool)
            # A driver whose every refresh is full needs none of the three; any other, all of them.
            calls = [bool(p["full_refresh"]), bool(p["keep_picture"]), bool(p["drive_every_pixel"])]
            self.assertEqual(calls, [not p.get("always_full")] * 3, d)
            self.assertEqual(epf.MODEL_MAP[d], p["frame_model"])
            self.assertEqual(d in epf.MIRRORED_MODELS, p["mirrored"])

    def test_the_firmware_reads_them_from_the_profile(self):
        for d in ("crowpanel_579", "crowpanel_290"):
            disp = dict(T.get_display(d))
            disp["full_refresh"], disp["keep_picture"] = "full_marker();", "kept_marker();"
            disp["drive_every_pixel"] = "drive_marker();"
            text = firmware_gen.render(disp=disp, version="0.15.0", device_name="p", frames_url="http://h/f.epf", ota_key="k",
                                       wifi_ssid='"x"', wifi_password='"y"', interval_min=1, orientation=0)
            self.assertIn("full_marker();", text)
            self.assertIn("kept_marker();", text)
            self.assertIn("drive_marker();", text)
