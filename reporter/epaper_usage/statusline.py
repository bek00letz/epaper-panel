"""Claude Code's status line: the one place it shares its limit windows (readers/claude_code.py).

Claude Code runs a status line command with JSON on its standard input at each update; since
v2.1.80 that has `rate_limits` (code.claude.com/docs/en/statusline). The reporter's status line,
`run.py status-line`, does two things and must never get in the way:

1. saves just `rate_limits` (its known windows and numbers, nothing else) to the reporter's folder,
   each window with when it was saved, keeping a window Claude Code has stopped sending (it drops one
   once it resets) so the add-on can say it reset;
2. runs the status line you had before, if any, with the same input, and prints what it prints. If
   you had none, it prints a short line of its own ("Opus · 5-hour 42% · weekly 18%").

Setup puts it in Claude Code's settings (`statusLine`), keeping a backup of the file and your own
status line command, and only when the file can be read: a settings file Claude Code itself can't
parse is never rewritten. Removing the reporter puts yours back.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

LIMITS_FILE = "claude-limits.json"
PREVIOUS_FILE = "claude-statusline-before.json"
BACKUP_SUFFIX = ".before-epaper-usage"
MARK = "status-line"                     # what tells our command from anyone else's
KNOWN = {"five_hour": ("used_percentage", "resets_at"),
         "seven_day": ("used_percentage", "resets_at"),
         "spend_limit": ("used_percentage", "resets_at", "used_usd", "limit_usd", "period")}
PREVIOUS_TIMEOUT = 5


def _number(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def keep_limits(state: Path, given: dict, now: float | None = None) -> bool:
    """Save what Claude Code said about its limits. True when something was saved."""
    rl = given.get("rate_limits") if isinstance(given, dict) else None
    if not isinstance(rl, dict):
        return False
    now = time.time() if now is None else now
    path = state / LIMITS_FILE
    try:
        old = json.loads(path.read_text()).get("rate_limits") or {}
    except (OSError, ValueError, AttributeError):
        old = {}
    new = {k: v for k, v in old.items() if k in KNOWN and isinstance(v, dict)}
    saved = False
    for key, fields in KNOWN.items():
        got = rl.get(key)
        if not isinstance(got, dict) or _number(got.get("used_percentage")) is None:
            continue
        clean = {f: got[f] for f in fields if f in got and (_number(got[f]) is not None or f == "period")}
        if key == "spend_limit" and key in new:
            # The amounts come in a separate request: keep the last ones until new ones come.
            for f in ("used_usd", "limit_usd", "period"):
                if f not in clean and f in new[key]:
                    clean[f] = new[key][f]
        new[key] = {**clean, "saved_at": now}
        saved = True
    if not saved:
        return False
    state.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"saved_at": now, "rate_limits": new}))
    tmp.replace(path)
    return True


def own_line(given: dict) -> str:
    """A short line for someone who had no status line: the model and the limits."""
    parts = []
    model = ((given.get("model") or {}).get("display_name") or "") if isinstance(given, dict) else ""
    if model:
        parts.append(str(model))
    rl = (given.get("rate_limits") or {}) if isinstance(given, dict) else {}
    for key, word in (("five_hour", "5-hour"), ("seven_day", "weekly")):
        pct = _number((rl.get(key) or {}).get("used_percentage"))
        if pct is not None:
            parts.append(f"{word} {round(pct)}%")
    return " · ".join(parts)


def run(state: Path, stdin=None, stdout=None) -> int:
    """`run.py status-line`: what Claude Code runs. Whatever happens, it shows a status line."""
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout
    raw = stdin.read()
    try:
        given = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, ValueError):
        given = {}
    try:
        keep_limits(state, given)
    except OSError:
        pass                                     # the status line still shows
    before = previous(state)
    if before.get("command"):
        try:
            got = subprocess.run(before["command"], shell=True, input=raw, capture_output=True,
                                 timeout=PREVIOUS_TIMEOUT)
            stdout.write(got.stdout.decode("utf-8", "replace"))
        except (OSError, subprocess.SubprocessError):
            pass
        return 0
    line = own_line(given)
    if line:
        stdout.write(line + "\n")
    return 0


# ---------------------------------------------------------------- putting it in Claude Code's settings

def settings_path(home: Path, env: dict) -> Path:
    own = env.get("CLAUDE_CONFIG_DIR")
    return (Path(own).expanduser() if own else home / ".claude") / "settings.json"


def previous(state: Path) -> dict:
    try:
        got = json.loads((state / PREVIOUS_FILE).read_text())
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def command_for(python: str, script: str) -> str:
    if sys.platform.startswith("win"):
        return f'"{python}" "{script}" {MARK}'
    return f"{shlex.quote(python)} {shlex.quote(script)} {MARK}"


def is_ours(line: dict) -> bool:
    cmd = str((line or {}).get("command") or "")
    return cmd.endswith(f" {MARK}") and "run.py" in cmd


def install(home: Path, env: dict, state: Path, python: str, script: str) -> str:
    """Our status line in Claude Code's settings, keeping yours to run inside it. Says what it did."""
    path = settings_path(home, env)
    if not path.parent.is_dir():
        return "Claude Code isn't set up on this computer, so its limits aren't read."
    try:
        text = path.read_text() if path.exists() else "{}"
        cfg = json.loads(text or "{}")
        if not isinstance(cfg, dict):
            raise ValueError("not an object")
    except (OSError, ValueError):
        return (f"Claude Code's settings file ({path}) isn't valid JSON, so it was left alone. Fix it, then "
                f"run setup again; or add this yourself as its \"statusLine\" command: {command_for(python, script)}")
    line = cfg.get("statusLine") if isinstance(cfg.get("statusLine"), dict) else None
    if line and is_ours(line):
        line["command"] = command_for(python, script)            # where it runs from may have moved
    else:
        state.mkdir(parents=True, exist_ok=True)
        (state / PREVIOUS_FILE).write_text(json.dumps(line or {}))
        if path.exists():
            backup = path.with_name(path.name + BACKUP_SUFFIX)
            if not backup.exists():
                backup.write_text(text)
        line = {**(line or {}), "type": "command", "command": command_for(python, script)}
    cfg["statusLine"] = line
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2) + "\n")
    tmp.replace(path)
    had = previous(state).get("command")
    return ("Claude Code shares its limits through its status line, so the reporter's runs inside yours "
            "and shows what yours showed." if had else
            "Claude Code shares its limits through its status line, so the reporter added a short one: "
            "the model and your limits.")


def uninstall(home: Path, env: dict, state: Path) -> str:
    path = settings_path(home, env)
    try:
        cfg = json.loads(path.read_text())
    except (OSError, ValueError):
        return "Claude Code's settings were left as they are."
    if not isinstance(cfg, dict) or not is_ours(cfg.get("statusLine") or {}):
        return "Claude Code's status line isn't the reporter's; it was left as it is."
    before = previous(state)
    if before:
        cfg["statusLine"] = before
    else:
        cfg.pop("statusLine", None)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2) + "\n")
    tmp.replace(path)
    return "Claude Code's status line is yours again." if before else "Claude Code's status line is gone, as before."
