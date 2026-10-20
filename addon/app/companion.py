"""The companion integration: installed into Home Assistant by the add-on, kept at the add-on's version.

Reaching home through Home Assistant's address (reach.py, "ha") needs it.
The editor installs it into /config/custom_components (the add-on maps
/config), asks for one Home Assistant restart, then sets it up: there's
nothing to fill in. Each add-on update refreshes the copy, and the editor
says when a restart is still needed for it. After the restart the add-on
creates the integration's config entry itself (`keep_set_up`).
"""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import config
import health
from hass import HassError

DOMAIN = "epaper_panel"
SOURCE = Path(__file__).parent / "companion" / DOMAIN


def target_dir() -> Path:
    return config.HA_CONFIG_DIR / "custom_components" / DOMAIN


def installed_version() -> str | None:
    try:
        return json.loads((target_dir() / "manifest.json").read_text()).get("version")
    except (OSError, ValueError):
        return None


def _version() -> str:
    """The add-on's version, as a version Home Assistant accepts."""
    v = config.ADDON_VERSION
    return v if v[:1].isdigit() else "0.0.0"


def install(service_url: str) -> None:
    """Put the integration in place (all of it or none), at this add-on's version, pointed at `service_url`."""
    if not service_url:
        raise ValueError("The add-on couldn't find its own address on Home Assistant's network.")
    dest = target_dir()
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = dest.with_name(DOMAIN + ".new")
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(SOURCE, staging, ignore=shutil.ignore_patterns("__pycache__"))
    manifest = json.loads((staging / "manifest.json").read_text())
    manifest["version"] = _version()
    (staging / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (staging / "target.json").write_text(json.dumps({"url": service_url}))
    old = dest.with_name(DOMAIN + ".old")
    shutil.rmtree(old, ignore_errors=True)
    if dest.exists():
        dest.rename(old)
    staging.rename(dest)
    shutil.rmtree(old, ignore_errors=True)
    print(f"companion: installed version {manifest['version']} in {dest}", flush=True)


def refresh(service_url: str) -> bool:
    """Bring an installed copy up to this add-on's version and address. Returns whether it changed."""
    if installed_version() is None:
        return False
    try:
        target = json.loads((target_dir() / "target.json").read_text()).get("url")
    except (OSError, ValueError):
        target = None
    if installed_version() == _version() and (target == service_url or not service_url):
        return False
    try:
        install(service_url or target or "")
        return True
    except (OSError, ValueError) as exc:
        print(f"companion: couldn't update it: {health.describe(exc)}", flush=True)
        return False


# What Home Assistant does with it, asked of Home Assistant itself (`state`).
ABSENT = "absent"          # not in custom_components
RESTART = "restart"        # installed, but Home Assistant hasn't loaded it: it needs a restart
SET_UP = "set_up"          # loaded, with no config entry yet: the add-on creates it (`ensure`)
RUNNING = "running"        # its config entry is loaded: /api/epaper answers
STOPPED = "stopped"        # its entry exists but isn't loaded (turned off, or it failed to start)
UNKNOWN = "unknown"        # Home Assistant didn't answer

# How often the add-on checks, so the entry exists a minute after Home Assistant restarts.
CHECK_SECONDS = 60


async def state(hass) -> dict:
    """{state, version, entry_state, disabled}: what Home Assistant runs, never a guess from the add-on.

    Home Assistant reads custom_components once, when it starts, so it only
    knows the integration (its manifest) after a restart. Its view, and with
    it /api/epaper, exists only once its config entry is set up.
    """
    installed = installed_version()
    out = {"state": ABSENT, "version": installed, "entry_state": None, "disabled": False}
    if installed is None:
        return out
    try:
        await hass.ws({"type": "manifest/get", "integration": DOMAIN})
    except HassError as exc:
        out["state"] = RESTART if exc.code == "not_found" else UNKNOWN
        return out
    try:
        entries = await hass.ws({"type": "config_entries/get", "domain": DOMAIN}) or []
    except HassError:
        out["state"] = UNKNOWN
        return out
    if not entries:
        out["state"] = SET_UP
        return out
    entry = entries[0]
    out["entry_state"] = entry.get("state")
    out["disabled"] = bool(entry.get("disabled_by"))
    out["state"] = RUNNING if entry.get("state") == "loaded" else STOPPED
    return out


async def set_up(hass) -> tuple[bool, str]:
    """Create its one config entry (the flow asks nothing). Returns (done, problem)."""
    try:
        entries = await hass.ws({"type": "config_entries/get", "domain": DOMAIN})
        if entries:
            return True, ""
        result = await hass.rest("POST", "/config/config_entries/flow", json={"handler": DOMAIN}) or {}
        if result.get("type") == "create_entry" or result.get("reason") == "already_configured":
            return True, ""
        return False, str(result.get("reason") or result.get("type") or "no answer")[:200]
    except HassError as exc:
        return False, str(exc)[:200]


async def ensure(hass) -> dict:
    """Bring it to running where only the add-on can: create the entry once Home Assistant has loaded it.

    Returns `state`, with `problem` when setting it up failed."""
    s = await state(hass)
    if s["state"] != SET_UP:
        return s
    ok, problem = await set_up(hass)
    print("companion: set up in Home Assistant" if ok else f"companion: Home Assistant didn't set it up: {problem}",
          flush=True)
    s = await state(hass) if ok else s
    if not ok:
        s["problem"] = problem
    return s


async def keep_set_up(hass, sleep=asyncio.sleep) -> None:
    """At start and every CHECK_SECONDS: set it up after Home Assistant restarts, without a visit to the editor."""
    while True:
        if installed_version() is not None and hass.available:
            try:
                await ensure(hass)
            except Exception as exc:     # a check that fails must not end the loop
                print(f"companion: check failed: {health.describe(exc)}", flush=True)
        await sleep(CHECK_SECONDS)


async def restart_home_assistant(hass) -> tuple[bool, str]:
    try:
        await hass.rest("POST", "/services/homeassistant/restart", json={})
        return True, ""
    except HassError as exc:
        return False, str(exc)[:200]
