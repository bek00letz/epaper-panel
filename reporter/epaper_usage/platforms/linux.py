"""Linux: the key in the desktop's key store (the Secret Service, through `secret-tool`), a systemd
user timer every few minutes, files under ~/.local/share.

Without a key store (a server with no desktop), the key goes in a file only this user can read
(0600), and setup says so. `secret-tool store` reads the key from standard input, so it's never in
a command line.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import SERVICE

ID = "linux"
UNIT = "epaper-usage-reporter"
ATTRS = ["service", SERVICE, "account", "reporter-key"]


def data_dir(home: Path) -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else home / ".local" / "share") / UNIT


def log_path(home: Path) -> Path:
    return data_dir(home) / "reporter.log"


def _key_file(home: Path) -> Path:
    return data_dir(home) / "key"


def _secret_tool() -> str | None:
    return None if os.environ.get("EPAPER_USAGE_NO_KEYRING") else shutil.which("secret-tool")


def save_key(home: Path, key: str) -> str:
    tool = _secret_tool()
    if tool:
        got = subprocess.run([tool, "store", f"--label={SERVICE}", *ATTRS], input=key, capture_output=True,
                             text=True, timeout=30)
        if got.returncode == 0:
            try:
                _key_file(home).unlink()
            except OSError:
                pass
            return "in your desktop's key store"
    path = _key_file(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key)
    os.chmod(path, 0o600)
    return f"in {path}, which only you can read (there's no key store to keep it in)"


def load_key(home: Path) -> str:
    tool = _secret_tool()
    if tool:
        got = subprocess.run([tool, "lookup", *ATTRS], capture_output=True, text=True, timeout=30)
        if got.returncode == 0 and got.stdout.strip():
            return got.stdout.strip()
    try:
        return _key_file(home).read_text().strip()
    except OSError:
        return ""


def delete_key(home: Path) -> None:
    tool = _secret_tool()
    if tool:
        subprocess.run([tool, "clear", *ATTRS], capture_output=True, timeout=30)
    try:
        _key_file(home).unlink()
    except OSError:
        pass


def _units(home: Path) -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else home / ".config") / "systemd" / "user"


def _q(s: str) -> str:
    """A path in a unit file's ExecStart, quoted as systemd reads it."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def units_for(python: str, script: str, minutes: int) -> dict:
    return {
        f"{UNIT}.service": (f"[Unit]\nDescription={SERVICE}\n\n[Service]\nType=oneshot\n"
                            f"ExecStart={_q(python)} {_q(script)} report\nNice=10\nIOSchedulingClass=idle\n"),
        f"{UNIT}.timer": (f"[Unit]\nDescription={SERVICE}, every {minutes} minutes\n\n[Timer]\nOnBootSec=1min\n"
                          f"OnUnitActiveSec={int(minutes)}min\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n"),
    }


def schedule(home: Path, python: str, script: str, minutes: int) -> str:
    ctl = shutil.which("systemctl")
    if not ctl:
        raise RuntimeError("This computer has no systemd to run it. Add this to your crontab instead (crontab -e):\n"
                           f"*/{minutes} * * * * {_q(python)} {_q(script)} report")
    folder = _units(home)
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in units_for(python, script, minutes).items():
        (folder / name).write_text(text)
    for args in (["daemon-reload"], ["enable", "--now", f"{UNIT}.timer"]):
        got = subprocess.run([ctl, "--user", *args], capture_output=True, text=True)
        if got.returncode != 0:
            raise RuntimeError(f"systemd didn't start the reporter's timer: {got.stderr.strip() or got.returncode}")
    return f"It runs every {minutes} minutes while you're logged in (a systemd user timer)."


def unschedule(home: Path) -> str:
    ctl = shutil.which("systemctl")
    if ctl:
        subprocess.run([ctl, "--user", "disable", "--now", f"{UNIT}.timer"], capture_output=True)
    for name in (f"{UNIT}.service", f"{UNIT}.timer"):
        try:
            (_units(home) / name).unlink()
        except OSError:
            pass
    if ctl:
        subprocess.run([ctl, "--user", "daemon-reload"], capture_output=True)
    return "Its timer is off."


def scheduled(home: Path) -> bool:
    return (_units(home) / f"{UNIT}.timer").exists()
