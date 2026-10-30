"""Windows: the key in a file Windows encrypts for this account (DPAPI, the way Windows apps keep
their own secrets), a Task Scheduler task every few minutes, files in %LOCALAPPDATA%.

DPAPI is called through ctypes (crypt32's CryptProtectData), so nothing needs installing. The task
runs `pythonw.exe`, which opens no window, every few minutes while you're logged in.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
from pathlib import Path

from . import SERVICE

ID = "windows"


def data_dir(home: Path) -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else home / "AppData" / "Local") / SERVICE


def log_path(home: Path) -> Path:
    return data_dir(home) / "reporter.log"


def _key_file(home: Path) -> Path:
    return data_dir(home) / "key.dpapi"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _crypt(data: bytes, protect: bool) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32           # type: ignore[attr-defined]
    src, out = _blob(data), _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    # No UI (CRYPTPROTECT_UI_FORBIDDEN): the task runs with nobody to ask.
    ok = fn(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(out))
    if not ok:
        raise RuntimeError("Windows couldn't protect the key for your account.")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def save_key(home: Path, key: str) -> str:
    path = _key_file(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_crypt(key.encode(), True))
    return "in a file Windows encrypts for your account"


def load_key(home: Path) -> str:
    try:
        return _crypt(_key_file(home).read_bytes(), False).decode()
    except (OSError, RuntimeError, AttributeError, ValueError):
        return ""


def delete_key(home: Path) -> None:
    try:
        _key_file(home).unlink()
    except OSError:
        pass


def windowless(python: str) -> str:
    """pythonw.exe beside python.exe, so the task opens no window every few minutes."""
    p = Path(python)
    w = p.with_name("pythonw.exe")
    return str(w) if p.name.lower() == "python.exe" and w.exists() else python


def task_command(python: str, script: str, minutes: int) -> list:
    return ["schtasks", "/Create", "/F", "/SC", "MINUTE", "/MO", str(int(minutes)), "/TN", SERVICE,
            "/TR", f'"{windowless(python)}" "{script}" report']


def schedule(home: Path, python: str, script: str, minutes: int) -> str:
    got = subprocess.run(task_command(python, script, minutes), capture_output=True, text=True)
    if got.returncode != 0:
        raise RuntimeError(f"Task Scheduler didn't take the reporter's task: {(got.stderr or got.stdout).strip()}")
    return f"It runs every {minutes} minutes while you're logged in (a Task Scheduler task)."


def unschedule(home: Path) -> str:
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", SERVICE], capture_output=True, text=True)
    return "Its task is off."


def scheduled(home: Path) -> bool:
    got = subprocess.run(["schtasks", "/Query", "/TN", SERVICE], capture_output=True, text=True)
    return got.returncode == 0
