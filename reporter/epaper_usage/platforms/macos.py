"""macOS: the key in the Keychain, a LaunchAgent every few minutes, files in Application Support.

The key goes to the Keychain through `security -i`, which reads its command from standard input,
so the key is never in a command line another program could see. `security` itself makes the item,
so only it (and this reporter, through it) can read it without asking.
"""
from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

from . import LABEL, SERVICE

ID = "macos"
ACCOUNT = "reporter-key"


def data_dir(home: Path) -> Path:
    return home / "Library" / "Application Support" / SERVICE


def log_path(home: Path) -> Path:
    return home / "Library" / "Logs" / f"{SERVICE}.log"


def _keychain() -> list:
    # A keychain of its own, for the tests: never the person's login keychain there.
    own = os.environ.get("EPAPER_USAGE_KEYCHAIN")
    return [own] if own else []


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save_key(home: Path, key: str) -> str:
    cmd = " ".join(["add-generic-password", "-U", "-s", _quote(SERVICE), "-a", _quote(ACCOUNT),
                    "-l", _quote(SERVICE), "-w", _quote(key), *map(_quote, _keychain())]) + "\n"
    got = subprocess.run(["/usr/bin/security", "-i"], input=cmd, capture_output=True, text=True, timeout=30)
    if got.returncode != 0 or "error" in (got.stderr or "").lower():
        raise RuntimeError("The Keychain didn't take the key. Unlock your Mac's login keychain and run setup again.")
    return "in your Mac's Keychain"


def load_key(home: Path) -> str:
    got = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w",
                          *_keychain()], capture_output=True, text=True, timeout=30)
    return got.stdout.strip() if got.returncode == 0 else ""


def delete_key(home: Path) -> None:
    subprocess.run(["/usr/bin/security", "delete-generic-password", "-s", SERVICE, "-a", ACCOUNT, *_keychain()],
                   capture_output=True, text=True, timeout=30)


def _plist(home: Path) -> Path:
    return home / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def plist_for(home: Path, python: str, script: str, minutes: int) -> bytes:
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [python, script, "report"],
        "StartInterval": int(minutes) * 60,
        "RunAtLoad": True,
        # Below everything you're doing: it's a background read of a few files.
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "Nice": 10,
        "StandardOutPath": str(log_path(home)),
        "StandardErrorPath": str(log_path(home)),
    })


def schedule(home: Path, python: str, script: str, minutes: int) -> str:
    path = _plist(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    log_path(home).parent.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["/bin/launchctl", "bootout", domain, str(path)], capture_output=True)
    path.write_bytes(plist_for(home, python, script, minutes))
    got = subprocess.run(["/bin/launchctl", "bootstrap", domain, str(path)], capture_output=True, text=True)
    if got.returncode != 0:
        raise RuntimeError(f"macOS didn't start the reporter's schedule: {got.stderr.strip() or got.returncode}")
    return f"It runs every {minutes} minutes while you're logged in (a LaunchAgent)."


def unschedule(home: Path) -> str:
    path = _plist(home)
    subprocess.run(["/bin/launchctl", "bootout", f"gui/{os.getuid()}", str(path)], capture_output=True)
    try:
        path.unlink()
    except OSError:
        pass
    return "Its schedule is off."


def scheduled(home: Path) -> bool:
    return _plist(home).exists()
