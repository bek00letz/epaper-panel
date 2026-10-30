"""The reporter's commands (`python3 run.py <command>`):

    setup --address URL [--address URL] --code CODE [--no-status-line]
                connect to the add-on with the code the editor shows, keep the key in this computer's
                key store, set up Claude Code's status line, run every 5 minutes, and send a first report
    report      read and send, once (what the schedule runs). Quiet unless something's wrong
    show        what it would send, in plain words; sends nothing
    status-line what Claude Code runs as its status line (statusline.py)
    status      whether it's connected, scheduled, and how its last report went
    uninstall   stop, forget the key, put Claude Code's status line back, and remove its files

Only the numbers leave this computer: no file, path, prompt or key is ever in a report.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import APP, VERSION, platforms, readers, shape, statusline

MINUTES = 5
CONFIG = "config.json"
LAST = "last-report.json"
TIMEOUT = 20
LOG_MAX = 256 * 1024


class Reporter:
    def __init__(self, home: Path | None = None, platform=None, env: dict | None = None, now=None):
        self.home = home or Path.home()
        self.pf = platform or platforms.current()
        self.env = dict(os.environ if env is None else env)
        self.now = now
        self.dir = self.pf.data_dir(self.home)

    # ------------------------------------------------------------ files
    def config(self) -> dict:
        try:
            got = json.loads((self.dir / CONFIG).read_text())
        except (OSError, ValueError):
            return {}
        return got if isinstance(got, dict) else {}

    def save_config(self, cfg: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / (CONFIG + ".tmp")
        tmp.write_text(json.dumps(cfg, indent=2))
        tmp.replace(self.dir / CONFIG)

    def log(self, line: str) -> None:
        path = self.pf.log_path(self.home)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > LOG_MAX:
                path.write_text(path.read_text()[-LOG_MAX // 2:])
            with open(path, "a") as f:
                f.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {line}\n")
        except OSError:
            pass

    # ------------------------------------------------------------ reading
    def read(self) -> dict:
        cfg = self.config()
        own = cfg.get("readers") or {}
        now = self.now or datetime.now(timezone.utc)

        def ctx_for(mod):
            return readers.Context(home=self.home, state=self.dir, now=now, settings=own.get(mod.ID) or {},
                                   env=self.env, log=self.log)
        found, skipped = readers.read_all(ctx_for)
        found = [p for p in found if (own.get(p.provider) or {}).get("off") is not True]
        return shape.report(found, skipped, self.pf.ID, now)

    # ------------------------------------------------------------ sending
    def post(self, base: str, path: str, body: dict, key: str = "") -> tuple[int, dict]:
        data = json.dumps(body).encode()
        req = urllib.request.Request(base.rstrip("/") + path, data=data, method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": f"{APP}/{VERSION}",
                                              **({"X-EPF-Key": key} if key else {})})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context()) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")[:300]
            return e.code, {"error": text}

    def send(self, report: dict) -> str:
        """Send to the first address that answers. Returns what happened, in words."""
        cfg = self.config()
        key = self.pf.load_key(self.home)
        if not key or not cfg.get("addresses"):
            return "Not connected yet. Run setup with the code the editor shows."
        problems = []
        for base in cfg["addresses"]:
            try:
                status, got = self.post(base, "/api/usage", report, key)
            except (urllib.error.URLError, socket.timeout, OSError, ValueError) as e:
                problems.append(f"{_host(base)} didn't answer ({getattr(e, 'reason', e)})")
                continue
            if status == 200:
                n = got.get("windows", 0)
                dropped = got.get("dropped") or []
                said = f"Sent {n} limit window{'s' if n != 1 else ''} to {_host(base)}."
                return said + (f" Left out: {'; '.join(dropped)}." if dropped else "")
            if status == 401:
                return (f"{_host(base)} didn't accept this computer's key. It may have been removed in Settings › "
                        "AI usage: connect it again with a new code.")
            problems.append(f"{_host(base)} said {status}: {got.get('error', '')}".strip())
        return "Couldn't send: " + "; ".join(problems) + "."

    def report(self) -> str:
        rep = self.read()
        said = self.send(rep)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / LAST).write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                                 "said": said}))
        self.log(said)
        return said


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc or url


def describe(rep: dict) -> list:
    """A report in plain words, for `show`."""
    lines = []
    for p in rep["providers"]:
        lines.append(p["name"] + (f" ({p['account']})" if p.get("account") else ""))
        for w in p["windows"]:
            name = f"{w['hours']:g}-hour session" if w["window"] == "session" else {"day": "Daily", "week": "Weekly", "month": "Monthly"}[w["window"]]
            if w.get("scope"):
                name += f" · {w['scope']}"
            if "amount" in w:
                used = f"{w['amount']:g}" + (f" of {w['limit']:g}" if "limit" in w else "") + f" {w.get('unit', '')}"
            else:
                used = f"{round(w['used'] * 100)}% used"
            resets = f", resets {w['resets_at']}" if w.get("resets_at") else ""
            lines.append(f"  {name}: {used.strip()}{resets} (read {w['read_at']})")
        ex = p.get("extras") or {}
        bits = [f"{ex['tokens']:,} tokens" if "tokens" in ex else "", f"{ex['sessions']} sessions" if "sessions" in ex else "",
                f"{round(ex['cache'] * 100)}% from cache" if "cache" in ex else "",
                f"{ex['streak_days']}-day streak" if "streak_days" in ex else ""]
        bits = [b for b in bits if b]
        if bits:
            lines.append(f"  Today: {', '.join(bits)}")
    for s in rep["skipped"]:
        lines.append(f"{s['name']}: " + {"not_found": "not on this computer", "no_limits": "nothing to read yet",
                                          "error": "couldn't be read (see the log)"}[s["reason"]])
    return lines or ["Nothing to report."]


def here() -> tuple[str, str]:
    """(the Python running this, the run.py that starts it): what the schedule and the status line run."""
    return sys.executable, str(Path(__file__).resolve().parent.parent / "run.py")


def setup(r: Reporter, addresses: list, code: str, status_line: bool = True, schedule: bool = True, out=print) -> int:
    addrs = []
    for a in addresses:
        a = a.strip().rstrip("/")
        parts = urllib.parse.urlsplit(a)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            out(f"“{a}” isn't an address like http://homeassistant.local:8099. Copy the command from the editor again.")
            return 2
        if parts.scheme == "http" and not _private(parts.hostname or ""):
            out(f"{a} is on the internet without https: the key would travel in the open. Use the https address.")
            return 2
        addrs.append(a)
    got, base = None, None
    for a in addrs:
        try:
            status, body = r.post(a, "/api/usage/pair", {"code": code, "platform": r.pf.ID})
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            out(f"Couldn't reach {_host(a)} ({getattr(e, 'reason', e)}). Is this computer on the same network?")
            continue
        if status == 200 and body.get("key"):
            got, base = body, a
            break
        out(body.get("error") or f"{_host(a)} said {status}.")
        return 1
    if got is None:
        return 1
    where = r.pf.save_key(r.home, got["key"])
    cfg = r.config()
    cfg.update(addresses=addrs, id=got.get("id"), minutes=MINUTES)
    r.save_config(cfg)
    out(f"Connected to {_host(base)}. Its key is {where}.")
    python, script = here()
    if status_line:
        out(statusline.install(r.home, r.env, r.dir, python, script))
    if schedule:
        try:
            out(r.pf.schedule(r.home, python, script, MINUTES))
        except RuntimeError as e:
            out(str(e))
    out(r.report())
    return 0


def _private(host: str) -> bool:
    import ipaddress
    if host.endswith((".local", ".lan", ".home", ".internal", ".home.arpa")) or "." not in host:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def uninstall(r: Reporter, out=print) -> int:
    out(r.pf.unschedule(r.home))
    out(statusline.uninstall(r.home, r.env, r.dir))
    r.pf.delete_key(r.home)
    out("Its key is gone from this computer. Remove it in the editor's Settings › AI usage too.")
    shutil.rmtree(r.dir, ignore_errors=True)
    out(f"Its folder is gone ({r.dir}).")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="run.py", description="Reports your AI usage to your e-Paper Panel add-on.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="connect with the code the editor shows")
    s.add_argument("--address", action="append", required=True, help="the add-on's address (more than one: tried in order)")
    s.add_argument("--code", required=True)
    s.add_argument("--no-status-line", action="store_true", help="leave Claude Code's status line alone (no limits from it)")
    s.add_argument("--no-schedule", action="store_true")
    for name, text in (("report", "read and send, once"), ("show", "what it would send, sending nothing"),
                       ("status-line", "Claude Code's status line"), ("status", "how it's doing"),
                       ("uninstall", "stop and remove it")):
        sub.add_parser(name, help=text)
    args = ap.parse_args(argv)
    r = Reporter()
    if args.cmd == "status-line":
        return statusline.run(r.dir)
    if args.cmd == "setup":
        return setup(r, args.address, args.code, not args.no_status_line, not args.no_schedule)
    if args.cmd == "report":
        said = r.report()
        if said.startswith(("Couldn't", "Not connected")) or "didn't accept" in said:
            print(said, file=sys.stderr)
            return 1
        return 0
    if args.cmd == "show":
        print("\n".join(describe(r.read())))
        return 0
    if args.cmd == "status":
        cfg = r.config()
        try:
            last = json.loads((r.dir / LAST).read_text())
        except (OSError, ValueError):
            last = {}
        print("Connected to " + ", ".join(_host(a) for a in cfg.get("addresses") or []) if cfg.get("addresses") else "Not connected.")
        print("Runs every 5 minutes." if r.pf.scheduled(r.home) else "Not scheduled: run setup again.")
        if last:
            print(f"Last report, {last.get('at')}: {last.get('said')}")
        return 0
    if args.cmd == "uninstall":
        return uninstall(r)
    return 2
