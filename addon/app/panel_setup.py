"""Panel setup: its saved settings and the ESPHome YAML it writes."""

import base64
import health
import json
import os
import re
import secrets
import urllib.parse
from pathlib import Path
import aiohttp

import firmware_gen
from render import binding, epf, layout, sleep, stripmeta, subitems, theme as T
import config
import devices
import kinds
import runtime
from config import ADDON_VERSION, FRAME_PORT, HA_TOKEN
from fixture import load_fixture
from layouts_store import load_layouts


def _new_api_key() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def load_panel_setup(dev: dict, default_host: str = "homeassistant.local") -> dict:
    """A panel's setup (its ESPHome settings), with defaults filled in and kept.

    The size and orientation are the device's own (`display` is shown here
    for the form, and saving it changes the device)."""
    cfg = dict(dev.get("setup") or {})
    changed = False
    defaults = {
        "device_name": (runtime.ESPHOME_DEVICE if dev.get("install_token") else
                        re.sub(r"[^a-z0-9]+", "-", str(dev.get("name") or "").lower()).strip("-")
                        or f"epaper-{dev['id']}").replace("_", "-"),
        "ha_host": default_host,
        "wifi_ssid": "",
        "wifi_password": "",
        "api_encryption_key": _new_api_key(),
        "use_secrets": False,
        # Its own Wi-Fi when it finds no network it knows (wifi_block).
        "hotspot": True,
        "hotspot_password": _new_hotspot_password(),
    }
    for k, v in defaults.items():
        if not cfg.get(k) and k not in ("wifi_ssid", "wifi_password", "use_secrets", "hotspot"):
            cfg[k] = v
            changed = True
        elif k not in cfg:
            cfg[k] = v
            changed = True
    if changed:
        cfg = save_panel_setup(dev["id"], cfg)
    cfg["display"] = T.get_display(load_layouts(dev["id"]).get("display"))["id"]
    return cfg


def save_panel_setup(device_id, cfg: dict) -> dict:
    """Keep a panel's setup with its device (devices.json is 0600: the Wi-Fi password and API key)."""
    cfg = {k: v for k, v in cfg.items() if k != "display"}
    dev_name = re.sub(r"[^a-z0-9-]+", "-", str(cfg.get("device_name") or "crowpanel-epaper").strip().lower()).strip("-")
    cfg["device_name"] = dev_name or "crowpanel-epaper"
    devices.update(device_id, setup=cfg)
    return dict(cfg)


def _new_hotspot_password() -> str:
    """Easy to type on a phone: no characters that look alike."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(12))


def hotspot_name(dev: dict) -> str:
    """The panel's own Wi-Fi: the screen's name, so you know which panel it is (32 characters at most)."""
    return (ha_name(dev)[:26].strip() + " setup")[:32]


def ha_name(dev: dict) -> str:
    """What Home Assistant calls the panel once it's installed from this file: the screen's name."""
    return str(dev.get("name") or "E-paper panel")[:60]


def more_networks(cfg: dict) -> list[dict]:
    """Wi-Fi networks besides the first (somewhere the screen goes, like work)."""
    out = []
    for n in cfg.get("wifi_networks") or []:
        if isinstance(n, dict) and str(n.get("ssid") or "").strip():
            out.append({"ssid": str(n["ssid"]).strip()[:32], "password": str(n.get("password") or "")[:64]})
    return out[:8]


def _yaml_str(s: str) -> str:
    escaped = str(s or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _inspect_existing_secrets() -> set[str]:
    """Secret names declared in the ESPHome folder's secrets.yaml."""
    for p in (config.ESPHOME_DIR / "secrets.yaml", Path(__file__).parent / "secrets.yaml"):
        if p.exists() and p.is_file():
            found = set()
            try:
                for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and ":" in line:
                        k = line.split(":", 1)[0].strip()
                        if k:
                            found.add(k)
                if found:
                    return found
            except Exception:
                pass
    return set()


def generate_esphome_yaml(cfg: dict, dev: dict, public_base: str | None = None) -> tuple[str, str]:
    """Build a panel's ready-to-flash ESPHome YAML and companion secrets.yaml.

    `public_base`: the address screens use away from home (reach.public_base),
    or None to fetch on the home network."""
    view = load_layouts(dev["id"])
    display_id = cfg.get("display") or view.get("display", T.DEFAULT_DISPLAY)
    disp = T.get_display(display_id)
    dw, dh = disp["w"], disp["h"]
    dev_name = cfg.get("device_name") or "crowpanel-epaper"
    raw_host = (cfg.get("ha_host") or "homeassistant.local").strip()
    port = cfg.get("frame_port") or FRAME_PORT
    if raw_host.startswith(("http://", "https://")):
        parsed = urllib.parse.urlsplit(raw_host)
        host_only = parsed.hostname or "homeassistant.local"
        if parsed.port:
            port = parsed.port
        scheme = parsed.scheme
    else:
        if ":" in raw_host:
            parts = raw_host.split(":")
            host_only = parts[0]
            try:
                port = int(parts[1])
            except ValueError:
                pass
        else:
            host_only = raw_host.split("/")[0] or "homeassistant.local"
        scheme = "http"

    base_url = public_base or f"{scheme}://{host_only}:{port}"
    token_q = f"?token={urllib.parse.quote(devices.key_of(dev))}"
    frames_epf_url = f"{base_url}/frames.epf{token_q}"

    use_secrets = bool(cfg.get("use_secrets"))
    ssid = (cfg.get("wifi_ssid") or "").strip()
    pw = cfg.get("wifi_password") or ""
    api_key = (cfg.get("api_encryption_key") or "").strip() or _new_api_key()
    # Its own timer, which runs only while it's always on: Update every (timing.py), never a setting here.
    initial_min = kinds.of(dev).update_minutes(dev)
    try:
        orient = int(cfg.get("orientation") if "orientation" in cfg else view.get("orientation", 0))
    except (TypeError, ValueError):
        orient = 0

    known_secrets = _inspect_existing_secrets()
    if use_secrets and "api_encryption_key" in known_secrets:
        api_key_line = "!secret api_encryption_key"
    else:
        api_key_line = _yaml_str(api_key)


    if (use_secrets or not ssid) and "wifi_ssid" in known_secrets:
        wifi_ssid_line = "!secret wifi_ssid"
    else:
        wifi_ssid_line = _yaml_str(ssid)

    if (use_secrets or not pw) and "wifi_password" in known_secrets:
        wifi_pw_line = "!secret wifi_password"
    else:
        wifi_pw_line = _yaml_str(pw)

    more = [(_yaml_str(n.get("ssid")), _yaml_str(n.get("password") or "")) for n in more_networks(cfg)]
    yaml_text = firmware_gen.render(
        disp=disp, version=ADDON_VERSION, device_name=dev_name, frames_url=_yaml_str(frames_epf_url),
        api_key=api_key_line, wifi_ssid=wifi_ssid_line, wifi_password=wifi_pw_line,
        interval_min=initial_min, orientation=orient, friendly_name=_yaml_str(ha_name(dev)),
        more_networks=more,
        hotspot=(_yaml_str(hotspot_name(dev)), _yaml_str(cfg.get("hotspot_password") or _new_hotspot_password()))
        if cfg.get("hotspot", True) else None)

    secrets_text = f"""# Put these in your ESPHome secrets.yaml if using !secret references:
wifi_ssid: {_yaml_str(ssid or "your-wifi-ssid")}
wifi_password: {_yaml_str(pw or "your-wifi-password")}
api_encryption_key: {_yaml_str(api_key)}
"""
    return yaml_text, secrets_text


async def _detect_panel_connection(dev: dict) -> dict:
    """Whether Home Assistant sees the panel, found by its registry IDs (see PanelLink)."""
    link = kinds.of(dev).link(dev)
    if not HA_TOKEN or link is None:
        panel_fix = load_fixture().get("panel") or {}
        return {"connected": False, "ip": None, "rssi": panel_fix.get("rssi"), "node": None,
                "problem": "running without Home Assistant" if not HA_TOKEN else "the add-on can't reach this screen"}
    return await link.connection()


async def _detect_external_port(session: aiohttp.ClientSession | None = None) -> int:
    if not HA_TOKEN:
        return FRAME_PORT
    try:
        sess = session or runtime.SESSION
        if sess:
            async with sess.get(
                "http://supervisor/addons/self/info",
                headers={"Authorization": f"Bearer {HA_TOKEN}"},
                timeout=aiohttp.ClientTimeout(total=2.0)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    net = (data.get("data") or {}).get("network") or {}
                    p = net.get(f"{FRAME_PORT}/tcp") or net.get("8099/tcp")
                    if p:
                        return int(p)
    except Exception as exc:
        print(f"could not query supervisor for external port: {health.describe(exc)}", flush=True)
    return FRAME_PORT
