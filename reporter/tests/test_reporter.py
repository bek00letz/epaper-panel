"""The reporter: each reader's parsing, the report's shape, Claude Code's status line, the platforms'
schedules and key stores, and sending. Only the invented files in samples/ and a throwaway home
folder: never anyone's real files, key store or schedule."""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from epaper_usage import cli, readers, shape, statusline  # noqa: E402
from epaper_usage.platforms import linux, macos, windows  # noqa: E402
from epaper_usage.readers import _files, claude_code, codex  # noqa: E402

SAMPLES = HERE / "samples"
NOW = datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)


def setUpModule():
    # Days are the computer's own; the samples are written for UTC.
    os.environ["TZ"] = "UTC"
    if hasattr(time, "tzset"):
        time.tzset()


class Home:
    """A copy of the samples' home folder, and the reporter's folder inside it."""

    def __enter__(self):
        self.root = Path(tempfile.mkdtemp(prefix="epaper-usage-test-"))
        self.home = self.root / "home"
        shutil.copytree(SAMPLES / "home", self.home)
        self.state = self.root / "state"
        self.state.mkdir()
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.root, ignore_errors=True)

    def ctx(self, **settings):
        return readers.Context(home=self.home, state=self.state, now=NOW, settings=settings, env={})

    def tap(self, name="statusline-input.json"):
        statusline.run(self.state, stdin=io.BytesIO((SAMPLES / name).read_bytes()), stdout=io.StringIO())


class TestClaudeCode(unittest.TestCase):
    def test_the_days_extras_each_answer_once(self):
        with Home() as h:
            got = claude_code.read(h.ctx())
        ex = got.extras
        # msg_A is written twice in its session and copied into another: counted once.
        self.assertEqual(ex["tokens"], 10500 + 6000 + 300)
        self.assertEqual(ex["sessions"], 2)
        self.assertAlmostEqual(ex["cache"], 13950 / 15310, places=4)
        self.assertEqual(ex["streak_days"], 3)                # the 30th, 29th and 28th; the 26th is after a gap
        self.assertEqual(ex["day"], "2026-10-30")

    def test_no_limits_until_the_status_line_has_run(self):
        with Home() as h:
            self.assertEqual(claude_code.read(h.ctx()).windows, [])

    def test_its_limits_from_the_status_line(self):
        with Home() as h:
            h.tap()
            ws = claude_code.read(h.ctx()).windows
        self.assertEqual([(w["window"], w.get("hours")) for w in ws], [("session", 5), ("week", None), ("month", None)])
        self.assertEqual(ws[0]["used"], 0.235)
        self.assertEqual(ws[0]["resets_at"], "2026-10-30T16:00:00+00:00")
        self.assertEqual({k: ws[2][k] for k in ("used", "amount", "limit", "unit")},
                         {"used": 0.628, "amount": 314.12, "limit": 500, "unit": "USD"})
        for w in ws:
            shape.check_window(w)

    def test_read_again_only_whats_new(self):
        with Home() as h:
            claude_code.read(h.ctx())
            f = h.home / ".claude/projects/-Users-someone-demo/aaaa-1111.jsonl"
            with open(f, "a") as out:
                out.write(json.dumps({"type": "assistant", "sessionId": "s-one", "requestId": "req_3",
                                      "timestamp": "2026-10-30T14:00:00Z",
                                      "message": {"id": "msg_G", "usage": {"input_tokens": 7, "output_tokens": 3}}}) + "\n")
                out.write('{"type":"assistant","half written')           # no newline yet: waits for the next run
            got = claude_code.read(h.ctx()).extras
        self.assertEqual(got["tokens"], 16800 + 10)

    def test_a_file_rewritten_smaller_is_read_again(self):
        with Home() as h:
            claude_code.read(h.ctx())
            f = h.home / ".claude/projects/-Users-someone-demo/aaaa-1111.jsonl"
            f.write_text(f.read_text().splitlines()[1] + "\n")       # only msg_A left
            got = claude_code.read(h.ctx()).extras
        self.assertEqual(got["tokens"], 10500 + 300)

    def test_not_there(self):
        with Home() as h:
            shutil.rmtree(h.home / ".claude")
            got = claude_code.read(h.ctx())
        self.assertEqual((got.provider, got.reason), ("claude", "not_found"))

    def test_its_own_config_folder(self):
        with Home() as h:
            moved = h.root / "elsewhere"
            shutil.move(str(h.home / ".claude"), moved)
            ctx = h.ctx()
            ctx.env = {"CLAUDE_CONFIG_DIR": str(moved)}
            self.assertEqual(claude_code.read(ctx).extras["sessions"], 2)


class TestCodex(unittest.TestCase):
    def test_the_newest_reading_of_each_limit(self):
        with Home() as h:
            got = codex.read(h.ctx())
        self.assertEqual(got.account, "Plus")
        plan = [w for w in got.windows if not w.get("scope")]
        self.assertEqual([(w["window"], w.get("hours"), w["used"]) for w in plan], [("session", 5, 0.125), ("week", None, 0.25)])
        self.assertEqual(plan[0]["resets_at"], "2026-10-30T12:00:00+00:00")
        self.assertEqual(plan[0]["read_at"], "2026-10-30T11:05:00+00:00")
        named = [w for w in got.windows if w.get("scope")]
        self.assertEqual([(w["scope"], w["used"]) for w in named], [("Sample Model", 0.4), ("Sample Model", 0.1)])
        for w in got.windows:
            shape.check_window(w)

    def test_a_limit_with_only_a_code_name_is_left_out(self):
        with Home() as h:
            got = codex.read(h.ctx())
        self.assertNotIn(0.99, [w["used"] for w in got.windows])

    def test_tokens_split_at_midnight(self):
        with Home() as h:
            ex = codex.read(h.ctx()).extras
        # The first session ran past midnight: only what it used after counts today.
        self.assertEqual(ex["tokens"], (5000 - 1000) + (500 - 100) + 2000 + 300)
        self.assertEqual(ex["sessions"], 2)
        self.assertAlmostEqual(ex["cache"], (3400 + 1000) / (4000 + 2000), places=4)
        self.assertEqual(ex["streak_days"], 2)

    def test_your_own_account_name_wins(self):
        with Home() as h:
            self.assertEqual(codex.read(h.ctx(account="Work")).account, "Work")

    def test_older_resets_in_seconds(self):
        w = codex._windows({"primary": {"used_percent": 50, "window_minutes": 300, "resets_in_seconds": 600}},
                           "2026-10-30T11:00:00+00:00", _files.when("2026-10-30T11:00:00Z"))
        self.assertEqual(w[0]["resets_at"], "2026-10-30T11:10:00+00:00")

    def test_not_there(self):
        with Home() as h:
            shutil.rmtree(h.home / ".codex")
            self.assertEqual(codex.read(h.ctx()).reason, "not_found")


class TestTheShape(unittest.TestCase):
    def test_every_reader_is_found_and_answers_in_the_shape(self):
        self.assertEqual([m.ID for m in readers.modules()], ["claude", "codex"])
        with Home() as h:
            h.tap()
            found, skipped = readers.read_all(lambda m: h.ctx())
            rep = shape.report(found, skipped, "macos", NOW)
        self.assertEqual(rep["format"], 1)
        self.assertEqual([p["provider"] for p in rep["providers"]], ["claude", "codex"])
        self.assertEqual(rep["reporter"]["platform"], "macos")
        text = json.dumps(rep)
        for private in ("/Users/someone", "invented", "An invented", "s-one", "msg_A", "req_1"):
            self.assertNotIn(private, text, "only numbers leave the computer")

    def test_a_reader_that_breaks_is_an_error_not_a_crash(self):
        class Broken:
            ID, NAME = "broken", "Broken"

            @staticmethod
            def read(ctx):
                raise RuntimeError("boom at /Users/someone/secret")
        logged = []
        with mock.patch.object(readers, "modules", return_value=[Broken]):
            found, skipped = readers.read_all(lambda m: readers.Context(home=Path("/x"), state=Path("/x"), log=logged.append))
        self.assertEqual((found, [(s.provider, s.reason) for s in skipped]), ([], [("broken", "error")]))
        rep = shape.report(found, skipped, "linux", NOW)
        self.assertNotIn("/Users/someone", json.dumps(rep), "an error's text stays in the log")
        self.assertTrue(logged)

    def test_window_lengths(self):
        self.assertEqual(shape.window_for_minutes(300), {"window": "session", "hours": 5})
        self.assertEqual(shape.window_for_minutes(1440), {"window": "day"})
        self.assertEqual(shape.window_for_minutes(10080), {"window": "week"})
        self.assertEqual(shape.window_for_minutes(43200), {"window": "month"})
        self.assertIsNone(shape.window_for_minutes(0))

    def test_a_window_out_of_shape_is_refused(self):
        for bad in ({"window": "fortnight", "used": 0.1, "read_at": "2026-10-30T10:00:00+00:00"},
                    {"window": "session", "used": 0.1, "read_at": "2026-10-30T10:00:00+00:00"},
                    {"window": "week", "read_at": "2026-10-30T10:00:00+00:00"},
                    {"window": "week", "used": 0.1, "read_at": "2026-10-30T10:00:00"}):
            with self.assertRaises(ValueError):
                shape.check_window(bad)


class TestStatusLine(unittest.TestCase):
    def test_keeps_only_the_limits(self):
        with Home() as h:
            h.tap()
            saved = json.loads((h.state / statusline.LIMITS_FILE).read_text())
        self.assertEqual(set(saved["rate_limits"]), {"five_hour", "seven_day", "spend_limit"})
        self.assertNotIn("Sample", json.dumps(saved), "nothing but the limits is kept")
        self.assertNotIn("/Users/someone", json.dumps(saved))

    def test_runs_your_own_and_shows_what_it_showed(self):
        with Home() as h:
            (h.state / statusline.PREVIOUS_FILE).write_text(json.dumps({"type": "command", "command": "cat > /dev/null; echo mine"}))
            out = io.StringIO()
            statusline.run(h.state, stdin=io.BytesIO(b'{"rate_limits": {}}'), stdout=out)
        self.assertEqual(out.getvalue().strip(), "mine")

    def test_its_own_line_without_yours(self):
        with Home() as h:
            out = io.StringIO()
            statusline.run(h.state, stdin=io.BytesIO((SAMPLES / "statusline-input.json").read_bytes()), stdout=out)
        self.assertEqual(out.getvalue().strip(), "Sample · 5-hour 24% · weekly 41%")

    def test_a_window_claude_code_stopped_sending_is_kept(self):
        with Home() as h:
            h.tap()
            statusline.keep_limits(h.state, {"rate_limits": {"seven_day": {"used_percentage": 50, "resets_at": 1793808000}}})
            saved = json.loads((h.state / statusline.LIMITS_FILE).read_text())["rate_limits"]
        self.assertEqual(saved["five_hour"]["used_percentage"], 23.5)
        self.assertEqual(saved["seven_day"]["used_percentage"], 50)
        self.assertEqual(saved["spend_limit"]["used_usd"], 314.12, "the amounts come separately: kept until new ones")

    def test_never_fails_the_status_line(self):
        with Home() as h:
            out = io.StringIO()
            self.assertEqual(statusline.run(h.state, stdin=io.BytesIO(b"not json"), stdout=out), 0)

    def test_installs_inside_yours_and_puts_it_back(self):
        with Home() as h:
            path = h.home / ".claude" / "settings.json"
            before = path.read_text()
            said = statusline.install(h.home, {}, h.state, "/usr/bin/python3", "/opt/r/run.py")
            cfg = json.loads(path.read_text())
            self.assertTrue(statusline.is_ours(cfg["statusLine"]))
            self.assertEqual(cfg["statusLine"]["padding"], 0, "your own settings for it are kept")
            self.assertEqual(cfg["theme"], "dark")
            self.assertEqual(statusline.previous(h.state)["command"], "echo mine")
            self.assertIn("runs inside yours", said)
            self.assertEqual((path.parent / ("settings.json" + statusline.BACKUP_SUFFIX)).read_text(), before)
            statusline.install(h.home, {}, h.state, "/usr/bin/python3", "/opt/r/run.py")   # again: still yours inside
            self.assertEqual(statusline.previous(h.state)["command"], "echo mine")
            statusline.uninstall(h.home, {}, h.state)
            self.assertEqual(json.loads(path.read_text())["statusLine"]["command"], "echo mine")

    def test_a_settings_file_that_isnt_json_is_left_alone(self):
        with Home() as h:
            path = h.home / ".claude" / "settings.json"
            path.write_text('{"permissions": {"allow": ["A" "B"]}}')          # a missing comma
            said = statusline.install(h.home, {}, h.state, "/usr/bin/python3", "/opt/r/run.py")
            self.assertEqual(path.read_text(), '{"permissions": {"allow": ["A" "B"]}}')
        self.assertIn("isn't valid JSON", said)
        self.assertIn("run.py", said, "it says what to add instead")


class TestPlatforms(unittest.TestCase):
    """The same parts on every platform (platforms/__init__.py), and what each writes."""

    def test_every_platform_has_every_part(self):
        for mod in (macos, linux, windows):
            for part in ("ID", "data_dir", "log_path", "save_key", "load_key", "delete_key", "schedule", "unschedule", "scheduled"):
                self.assertTrue(hasattr(mod, part), f"{mod.__name__}.{part}")

    def test_macos_runs_every_5_minutes_in_the_background(self):
        import plistlib
        p = plistlib.loads(macos.plist_for(Path("/Users/someone"), "/usr/bin/python3", "/opt/r/run.py", 5))
        self.assertEqual(p["ProgramArguments"], ["/usr/bin/python3", "/opt/r/run.py", "report"])
        self.assertEqual(p["StartInterval"], 300)
        self.assertEqual(p["ProcessType"], "Background")

    def test_macos_key_never_on_a_command_line(self):
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stderr="", stdout="")
            macos.save_key(Path("/x"), "the-secret-key")
        argv, kw = run.call_args
        self.assertNotIn("the-secret-key", " ".join(argv[0]))
        self.assertIn("the-secret-key", kw["input"])

    def test_linux_timer(self):
        units = linux.units_for("/usr/bin/python3", "/home/someone/.local/share/x/app/run.py", 5)
        self.assertIn('ExecStart="/usr/bin/python3" "/home/someone/.local/share/x/app/run.py" report', units["epaper-usage-reporter.service"])
        self.assertIn("OnUnitActiveSec=5min", units["epaper-usage-reporter.timer"])

    def test_linux_key_without_a_key_store_is_only_yours(self):
        with Home() as h, mock.patch.dict(os.environ, {"EPAPER_USAGE_NO_KEYRING": "1", "XDG_DATA_HOME": str(h.root / "xdg")}):
            said = linux.save_key(h.home, "k-123")
            path = linux._key_file(h.home)
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
            self.assertEqual(linux.load_key(h.home), "k-123")
            self.assertIn("only you can read", said)
            linux.delete_key(h.home)
            self.assertEqual(linux.load_key(h.home), "")

    def test_linux_key_store_reads_the_key_from_stdin(self):
        with mock.patch.object(linux, "_secret_tool", return_value="/usr/bin/secret-tool"), mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            self.assertIn("key store", linux.save_key(Path("/nonexistent"), "the-secret-key"))
        argv, kw = run.call_args
        self.assertNotIn("the-secret-key", " ".join(argv[0]))
        self.assertEqual(kw["input"], "the-secret-key")

    def test_windows_task_opens_no_window(self):
        with Home() as h:
            exe = h.root / "Python" / "python.exe"
            exe.parent.mkdir()
            exe.write_text("")
            (exe.parent / "pythonw.exe").write_text("")
            cmd = windows.task_command(str(exe), r"C:\r\run.py", 5)
        self.assertEqual(cmd[cmd.index("/MO") + 1], "5")
        self.assertIn("pythonw.exe", cmd[-1])
        self.assertTrue(cmd[-1].endswith('"C:\\r\\run.py" report'))

    def test_the_shell_installer_uses_the_same_folders(self):
        sh = (HERE.parent / "install.sh").read_text()
        self.assertIn('"$HOME/Library/Application Support/' + macos.SERVICE + '"', sh)
        self.assertIn("/epaper-usage-reporter", sh)
        self.assertEqual(linux.UNIT, "epaper-usage-reporter")
        ps = (HERE.parent / "install.ps1").read_text()
        self.assertIn('Join-Path $env:LOCALAPPDATA "' + windows.SERVICE + '"', ps)


class TestSending(unittest.TestCase):
    def reporter(self, h, key="k"):
        pf = mock.Mock(ID="macos", data_dir=lambda home: h.state, log_path=lambda home: h.state / "log",
                       load_key=lambda home: key)
        return cli.Reporter(home=h.home, platform=pf, env={}, now=NOW)

    def test_the_first_address_that_answers(self):
        with Home() as h:
            r = self.reporter(h)
            r.save_config({"addresses": ["http://homeassistant.local:8099", "https://example.org/api/epaper"]})
            calls = []

            def post(base, path, body, key=""):
                calls.append((base, path, key))
                if "local" in base:
                    raise OSError("no route")
                return 200, {"ok": True, "windows": 3, "dropped": []}
            with mock.patch.object(r, "post", side_effect=post):
                said = r.report()
        self.assertEqual([c[0] for c in calls], ["http://homeassistant.local:8099", "https://example.org/api/epaper"])
        self.assertEqual(calls[-1][1:], ("/api/usage", "k"))
        self.assertEqual(said, "Sent 3 limit windows to example.org.")

    def test_a_key_the_add_on_doesnt_know_says_what_to_do(self):
        with Home() as h:
            r = self.reporter(h)
            r.save_config({"addresses": ["http://homeassistant.local:8099"]})
            with mock.patch.object(r, "post", return_value=(401, {"error": "invalid"})):
                self.assertIn("connect it again", r.report())

    def test_not_connected(self):
        with Home() as h:
            self.assertIn("Run setup", self.reporter(h, key="").report())

    def test_no_plain_http_across_the_internet(self):
        with Home() as h:
            said = []
            code = cli.setup(self.reporter(h), ["http://example.org:8099"], "ABCDEF", out=said.append)
        self.assertEqual(code, 2)
        self.assertIn("https", said[0])

    def test_show_says_it_in_words(self):
        with Home() as h:
            h.tap()
            lines = cli.describe(self.reporter(h).read())
        self.assertIn("Claude Code", lines)
        self.assertTrue(lines[1].startswith("  5-hour session: 24% used, resets 2026-10-30T16:00:00+00:00 (read "), lines[1])


if __name__ == "__main__":
    unittest.main()
