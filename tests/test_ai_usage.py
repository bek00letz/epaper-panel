"""AI usage (docs/ai-usage.md): the shape a report comes in, pairing a computer and its key, what's
kept and merged, the sensors, and the page's layout rules at every size and language.

The reporter (reporter/) has its own tests; here its real output from the invented samples goes
through the add-on's reading, so the two halves of the contract can't drift apart."""
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

import support
import config
import devices
import kinds
import reporters
import usage
import web
from render import ai_usage, arrange, layout, theme as T, words

REPORTER = Path(support.APP).parents[1] / "reporter"
NOW = datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)


def window(**kw):
    return {"window": "week", "used": 0.4, "read_at": "2026-10-30T14:00:00+00:00",
            "resets_at": "2026-11-03T08:00:00+00:00", **kw}


def body(*providers, **more):
    return {"format": 1, "sent_at": "2026-10-30T15:00:00+01:00",
            "reporter": {"app": "epaper-usage-reporter", "version": "1.0", "platform": "macos"},
            "providers": list(providers), **more}


def provider(pid="claude", name="Claude Code", windows=None, **kw):
    return {"provider": pid, "name": name, "account": "", "windows": windows if windows is not None else [window()], **kw}


class TestTheShape(unittest.TestCase):
    def test_a_report_in_the_add_ons_form(self):
        got, dropped = usage.clean(body(provider(windows=[
            window(window="session", hours=5, used=0.235),
            window(),
            {"window": "month", "amount": 314.12, "limit": 500, "unit": "USD", "read_at": "2026-10-30T14:00:00+00:00"}])))
        self.assertEqual(dropped, [])
        ws = got["providers"][0]["windows"]
        self.assertEqual([usage.window_slug(w) for w in ws], ["session_5h", "week", "month_spend"])
        self.assertAlmostEqual(ws[2]["used"], 314.12 / 500, places=4)
        self.assertEqual(got["platform"], "macos")

    def test_a_bad_window_is_left_out_saying_why_and_the_rest_kept(self):
        got, dropped = usage.clean(body(provider(windows=[
            window(), window(window="fortnight"), window(used="lots", window="day"),
            window(window="session"), window(window="month", read_at="2026-10-30T14:00:00"), window()])))
        self.assertEqual(len(got["providers"][0]["windows"]), 1)
        self.assertEqual(len(dropped), 5)
        self.assertTrue(any("used isn't a number" in d for d in dropped))
        self.assertTrue(any("sent twice" in d for d in dropped))
        self.assertTrue(any("offset" in d for d in dropped))

    def test_what_isnt_a_report_at_all(self):
        for bad in ([], {"format": 2, "providers": []}, {"format": 1}):
            with self.assertRaises(ValueError):
                usage.clean(bad)

    def test_never_an_email_address(self):
        got, _ = usage.clean(body(provider(account="someone@example.com")))
        self.assertEqual(got["providers"][0]["account"], "")

    def test_a_provider_id_is_lowercase(self):
        got, dropped = usage.clean(body(provider(pid="Claude Code")))
        self.assertEqual((got["providers"], len(dropped)), ([], 1))

    def test_the_reporters_own_output_reads_with_nothing_left_out(self):
        """Both halves of the contract: the reporter's report from its samples is the add-on's shape."""
        sys.path.insert(0, str(REPORTER))
        try:
            from epaper_usage import readers, shape, statusline
        finally:
            sys.path.remove(str(REPORTER))
        root = Path(tempfile.mkdtemp())
        try:
            home, state = root / "home", root / "state"
            shutil.copytree(REPORTER / "tests" / "samples" / "home", home)
            state.mkdir()
            statusline.run(state, stdin=io.BytesIO((REPORTER / "tests/samples/statusline-input.json").read_bytes()),
                           stdout=io.StringIO())
            found, skipped = readers.read_all(lambda m: readers.Context(home=home, state=state, now=NOW, env={}))
            rep = shape.report(found, skipped, "macos", NOW)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        got, dropped = usage.clean(json.loads(json.dumps(rep)))
        self.assertEqual(dropped, [])
        self.assertEqual(sum(len(p["windows"]) for p in got["providers"]), sum(len(p["windows"]) for p in rep["providers"]))
        self.assertEqual({p["provider"] for p in got["providers"]}, {"claude", "codex"})


class TestNow(unittest.TestCase):
    def test_a_window_that_has_reset_is_empty(self):
        w = usage.window_now(window(resets_at="2026-10-27T08:00:00+00:00"), NOW)
        self.assertEqual((w["used"], w["reset"]), (0.0, "2026-10-27T08:00:00+00:00"))
        self.assertEqual(w["resets_at"], "2026-11-03T08:00:00+00:00", "a week resets again a week on")
        s = usage.window_now(window(window="session", hours=5, resets_at="2026-10-30T12:00:00+00:00"), NOW)
        self.assertNotIn("resets_at", s, "a session starts again only when it's used")

    def test_several_computers_the_newest_reading_wins_and_the_day_adds_up(self):
        a = {"providers": [provider(windows=[window(used=0.2, read_at="2026-10-30T10:00:00+00:00")],
                                    extras={"day": "2026-10-30", "tokens": 1000, "sessions": 1, "cache": 0.5, "streak_days": 3})]}
        b = {"providers": [provider(windows=[window(used=0.3, read_at="2026-10-30T11:00:00+00:00")],
                                    extras={"day": "2026-10-30", "tokens": 3000, "sessions": 2, "cache": 0.9, "streak_days": 7})]}
        got = usage.merge([({"id": "1"}, a), ({"id": "2"}, b)])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["windows"][0]["used"], 0.3)
        ex = got[0]["extras"]
        self.assertEqual((ex["tokens"], ex["sessions"], ex["streak_days"]), (4000, 3, 7))
        self.assertAlmostEqual(ex["cache"], (0.5 * 1000 + 0.9 * 3000) / 4000)
        self.assertEqual(got[0]["reporters"], ["1", "2"])

    def test_yesterdays_extras_arent_todays(self):
        ex = {"day": "2026-10-29", "tokens": 5, "streak_days": 4}
        self.assertEqual(usage.extras_now(ex, "UTC", NOW), {"day": "2026-10-29", "streak_days": 4})
        self.assertEqual(usage.extras_now({**ex, "day": "2026-10-20"}, "UTC", NOW), {})


class TestSensors(unittest.TestCase):
    def test_the_contracts_names(self):
        view = {"providers": [{"provider": "codex", "name": "Codex", "account": "", "reporters": ["1"], "windows": [
            window(window="session", hours=5), window(), window(scope="Sample Model"),
            {"window": "month", "amount": 12.0, "limit": 50, "unit": "USD", "used": 0.24, "read_at": "2026-10-30T14:00:00+00:00"}],
            "extras": {"day": "2026-10-30", "tokens": 9, "sessions": 1, "cache": 0.5, "streak_days": 2,
                       "cost": {"amount": 1.2, "unit": "USD"}}}],
            "reporters": [{"id": "1", "name": "", "platform": "macos", "heard_at": "2026-10-30T14:58:00+00:00", "quiet": False}]}
        got = {eid: (state, attrs) for eid, state, attrs in usage.sensors(view, "UTC", NOW)}
        self.assertEqual(sorted(got), sorted([
            "sensor.epaper_ai_codex_session_5h", "sensor.epaper_ai_codex_week", "sensor.epaper_ai_codex_week_sample_model",
            "sensor.epaper_ai_codex_month_spend", "sensor.epaper_ai_codex_tokens_today", "sensor.epaper_ai_codex_sessions_today",
            "sensor.epaper_ai_codex_cache_today", "sensor.epaper_ai_codex_streak", "sensor.epaper_ai_codex_cost_today",
            "sensor.epaper_ai_reporter_1"]))
        state, attrs = got["sensor.epaper_ai_codex_week"]
        self.assertEqual((state, attrs["unit_of_measurement"], attrs["provider"], attrs["resets_at"]),
                         (40.0, "%", "codex", "2026-11-03T08:00:00+00:00"))
        self.assertEqual(got["sensor.epaper_ai_reporter_1"][1]["device_class"], "timestamp")

    def test_an_account_has_its_own(self):
        p = {"provider": "claude", "name": "Claude Code", "account": "Work", "reporters": [], "windows": [window()], "extras": {}}
        got = [eid for eid, _, _ in usage.sensors({"providers": [p], "reporters": []}, None, NOW)]
        self.assertEqual(got, ["sensor.epaper_ai_claude_work_week"])


class TestPairingAndReports(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        support.fresh_data_dir()
        kinds.WRONG_KEYS = kinds.WrongKeys()
        reporters._PAIRING.clear()
        panel, editor = web.make_apps()
        self.lan, self.ed = TestClient(TestServer(panel)), TestClient(TestServer(editor))
        await self.lan.start_server()
        await self.ed.start_server()

    async def asyncTearDown(self):
        await self.lan.close()
        await self.ed.close()

    async def pair(self):
        with mock.patch("kinds.device_port_addresses", mock.AsyncMock(return_value=[{"where": "home", "url": "http://homeassistant.local:8099"}])):
            opened = await (await self.ed.post("/api/reporters/pair")).json()
        r = await self.lan.post("/api/usage/pair", json={"code": opened["code"].lower(), "platform": "macos"})
        self.assertEqual(r.status, 200)
        return opened, await r.json()

    async def test_the_editor_hands_out_a_code_and_a_command_never_the_key(self):
        opened, got = await self.pair()
        self.assertEqual(len(opened["code"]), reporters.CODE_LEN)
        cmds = opened["commands"]["home"]
        self.assertEqual(set(cmds), {"macos", "linux", "windows"})
        self.assertIn(f"--code {opened['code']}", cmds["macos"])
        self.assertIn("raw.githubusercontent.com/bek00letz/epaper-panel/", cmds["linux"])
        self.assertIn("install.ps1", cmds["windows"])
        listed = await (await self.ed.get("/api/reporters")).json()
        self.assertEqual(len(listed["reporters"]), 1)
        self.assertNotIn(got["key"], json.dumps(listed))
        state = await (await self.ed.get("/api/reporters/pair")).json()
        self.assertEqual(state["reporter"]["id"], got["id"], "the editor sees it join")

    async def test_a_code_works_once_and_a_wrong_one_counts(self):
        opened, _ = await self.pair()
        again = await self.lan.post("/api/usage/pair", json={"code": opened["code"]})
        self.assertEqual(again.status, 401)
        for _ in range(kinds.WrongKeys.LIMIT):
            await self.lan.post("/api/usage/pair", json={"code": "ZZZZZZ"})
        blocked = await self.lan.post("/api/usage/pair", json={"code": "ZZZZZZ"})
        self.assertEqual(blocked.status, 429)

    async def test_outside_the_window_nothing_pairs(self):
        r = await self.lan.post("/api/usage/pair", json={"code": "ABCDEF"})
        self.assertEqual(r.status, 401)
        reporters.open_pairing(clock=lambda: time.monotonic() - reporters.PAIR_SECONDS - 1)
        r = await self.lan.post("/api/usage/pair", json={"code": reporters._PAIRING["code"]})
        self.assertEqual(r.status, 401)

    async def test_a_report_with_its_key(self):
        _, got = await self.pair()
        r = await self.lan.post("/api/usage", headers={reporters.KEY_HEADER: got["key"]},
                                json=body(provider(windows=[window(), window(window="fortnight")])))
        answer = await r.json()
        self.assertEqual((r.status, answer["windows"], len(answer["dropped"])), (200, 1, 1))
        self.assertEqual(usage.load(got["id"])["providers"][0]["name"], "Claude Code")

    async def test_no_key_no_report(self):
        r = await self.lan.post("/api/usage", json=body(provider()))
        self.assertEqual(r.status, 401)
        r = await self.lan.post("/api/usage", headers={reporters.KEY_HEADER: "nope"}, json=body(provider()))
        self.assertEqual(r.status, 401)

    async def test_too_big(self):
        _, got = await self.pair()
        r = await self.lan.post("/api/usage", headers={reporters.KEY_HEADER: got["key"]},
                                data=b"{" + b" " * (usage.MAX_BYTES + 10) + b"}")
        self.assertEqual(r.status, 413)

    async def test_its_key_only_sends_usage(self):
        _, got = await self.pair()
        self.assertEqual(devices.authenticate(got["key"])[1], "wrong", "a reporter's key is no device's key")
        r = await self.lan.get("/frames.epf", params={"token": got["key"]})
        self.assertEqual(r.status, 401)

    async def test_removing_it_stops_its_key_and_undo_puts_it_back(self):
        _, got = await self.pair()
        await self.ed.delete(f"/api/reporters/{got['id']}")
        r = await self.lan.post("/api/usage", headers={reporters.KEY_HEADER: got["key"]}, json=body(provider()))
        self.assertEqual(r.status, 401)
        await self.ed.post(f"/api/reporters/{got['id']}/restore")
        r = await self.lan.post("/api/usage", headers={reporters.KEY_HEADER: got["key"]}, json=body(provider()))
        self.assertEqual(r.status, 200)

    async def test_its_store_is_private(self):
        await self.pair()
        self.assertEqual(oct((config.DATA_DIR / reporters.STORE).stat().st_mode & 0o777), "0o600")


OFFERED = [k for k, d in T.DISPLAYS.items() if d.get("offered") is not False]
BASE = arrange.canvas_key(792, 272)


def placed(display, orientation=0):
    el = {"type": "ai_usage", "x": 24, "y": 14, "w": 744, "h": 220}
    w, h = T.canvas_dims(orientation, display)
    el.update(arrange.auto_box(el, BASE, arrange.canvas_key(w, h)))
    return (int(el["x"]), int(el["y"]), int(el["w"]), int(el["h"])), el


def example(n=2, quiet=False):
    got = usage.for_page(usage.example(NOW), {}, None, NOW)
    got["providers"], got["tz"] = got["providers"][:n], "UTC"
    if quiet:
        got["reporters"] = [{**got["reporters"][0], "quiet": True, "heard_at": "2026-10-30T09:40:00+00:00"}]
    return got


class TestThePage(unittest.TestCase):
    """The layout rules (render/ai_usage.plan): nothing drawn outside its box or wider than its cell,
    in every language at every size offered, and what gives way when it doesn't fit."""

    def check(self, p, box):
        x, y, w, h = box
        sf = T.font(p.c, bold=False)          # the words are regular, the headings and numbers bold
        for b in p.blocks:
            for c in b.cells:
                cx, cy, cw, ch = c.box
                self.assertTrue(x <= cx and cx + cw <= x + w and y <= cy and cy + ch <= y + h, (box, c.box))
                self.assertLessEqual(T.text_width(c.label, sf), cw, c.label)
            if b.extras_text:
                self.assertLessEqual(T.text_width(b.extras_text, sf), w)
        if p.quiet:
            self.assertLessEqual(T.text_width(p.quiet, T.font(p.c, bold=True)), w)

    def test_fits_everywhere_in_every_language(self):
        for lang in words.LANGUAGES:
            for display in OFFERED:
                for orientation in (0, 90):
                    box, el = placed(display, orientation)
                    for n in (1, 2):
                        for quiet in (False, True):
                            with self.subTest(lang=lang, display=display, orientation=orientation, providers=n, quiet=quiet), \
                                    words.speaking(lang):
                                p = ai_usage.plan(box, example(n, quiet), el, NOW)
                                if p.message:
                                    continue
                                self.check(p, box)

    def test_one_provider_on_the_5_79_says_everything(self):
        box, el = placed("crowpanel_579")
        p = ai_usage.plan(box, example(1), el, NOW)
        self.assertEqual((p.way.heading, p.way.extras, p.dropped), ("top", True, 0))
        self.assertGreaterEqual(p.v, ai_usage.legible(box[3]))
        self.assertTrue(all(c.reset for c in p.blocks[0].cells))
        self.assertTrue(p.blocks[0].extras_text.startswith("1.2M tokens today"))

    def test_two_providers_on_the_5_79_keep_every_window(self):
        box, el = placed("crowpanel_579")
        p = ai_usage.plan(box, example(2), el, NOW)
        self.assertEqual((len(p.blocks), p.dropped), (2, 0))

    def test_too_small_for_bars_a_line_each(self):
        p = ai_usage.plan((0, 0, 200, 40), example(2), {"type": "ai_usage"}, NOW)
        self.assertEqual([t for t, _ in p.message], ["Claude Code: 42%", "Codex · Plus: 7%"])

    def test_resets_in_while_awake_and_when_while_asleep(self):
        box, el = placed("crowpanel_579")
        awake = ai_usage.plan(box, example(1), el, NOW).blocks[0].cells[0].reset
        asleep = ai_usage.plan(box, example(1), {**el, "asleep": True}, NOW).blocks[0].cells[0].reset
        self.assertEqual(awake, "Resets in 2 h 10 min")
        self.assertEqual(asleep, "Resets 17:10")

    def test_a_quiet_computer_is_said_plainly(self):
        box, el = placed("crowpanel_579")
        self.assertEqual(ai_usage.plan(box, example(1, quiet=True), el, NOW).quiet, "Last heard from your Mac at 09:40")

    def test_before_anything_to_show(self):
        box, el = placed("crowpanel_579")
        empty = ai_usage.plan(box, {"providers": [], "reporters": []}, el, NOW)
        self.assertEqual([t for t, _ in empty.message][:2], ["No AI usage yet", "In the editor, open Settings › AI usage"])
        waiting = ai_usage.plan(box, {"providers": [], "reporters": [{"id": "1", "heard_at": ""}]}, el, NOW)
        self.assertEqual(waiting.message[0][0], "Connected. Waiting for the first report.")
        found = ai_usage.plan(box, {"providers": [], "reporters": [{"id": "1", "heard_at": "2026-10-30T14:00:00+00:00", "skipped": [
            {"provider": "claude", "name": "Claude Code", "reason": "no_limits"}, {"provider": "codex", "name": "Codex", "reason": "no_limits"}]}]}, el, NOW)
        self.assertEqual(found.message[1][0], "Use Claude Code and Codex once and it shows here.")

    def test_spend_shows_the_money(self):
        w = {"window": "month", "amount": 314.12, "limit": 500, "unit": "USD", "used": 0.628, "read_at": "x"}
        self.assertEqual(ai_usage.big_text(w), ("$314", "of $500"))
        self.assertEqual(ai_usage.window_label(w), "Monthly spend")
        with words.speaking("de"):
            self.assertEqual(ai_usage.big_text(w), ("314 $", "von 500 $"))

    def test_counts_short(self):
        self.assertEqual([ai_usage.compact(n) for n in (950, 12_400, 1_240_000, 9_960_000)], ["950", "12K", "1.2M", "10M"])

    def test_it_draws(self):
        for display in OFFERED:
            box, el = placed(display)
            img = layout.render_page({"elements": [el]}, {0: example(2)}, display=display)
            self.assertLess(img.convert("L").getextrema()[0], 128, f"{display}: something is drawn")

    def test_the_presets_page_is_the_widget(self):
        src = (Path(support.APP) / "web" / "app" / "presets.js").read_text()
        self.assertIn('id: "ai_usage", group: "day"', src)
        self.assertIn('needs: "reporter"', src)
        self.assertIn("reporter: reporterSetup,", (Path(support.APP) / "web" / "app" / "setup.js").read_text())


if __name__ == "__main__":
    unittest.main()
