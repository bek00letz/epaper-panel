"""The companion integration: installed into Home Assistant by the add-on, kept at the add-on's version.

Reaching home through Home Assistant's address (reach.py, "ha") needs it.
The editor installs it into /config/custom_components (the add-on maps
/config), asks for one Home Assistant restart, then sets it up: there's
nothing to fill in. Each add-on update refreshes the copy, and the editor
says when a restart is still needed for it.
"""
from __future__ import annotations

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


async def loaded(hass) -> bool:
    """Whether Home Assistant is running it (installed, and restarted since)."""
    try:
        cfg = await hass.rest("GET", "/config")
        return DOMAIN in ((cfg or {}).get("components") or [])
    except HassError:
        return False


async def set_up(hass) -> tuple[bool, str]:
    """Create its one config entry (the flow asks nothing). Returns (done, problem)."""
    try:
        entries = await hass.ws({"type": "config_entries/get", "domain": DOMAIN})
        if entries:
            return True, ""
        await hass.rest("POST", "/config/config_entries/flow", json={"handler": DOMAIN})
        return True, ""
    except HassError as exc:
        return False, str(exc)[:200]


async def restart_home_assistant(hass) -> tuple[bool, str]:
    try:
        await hass.rest("POST", "/services/homeassistant/restart", json={})
        return True, ""
    except HassError as exc:
        return False, str(exc)[:200]
