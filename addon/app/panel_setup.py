"""Panel setup: its saved settings and the ESPHome YAML it writes."""

import base64
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
import runtime
from config import ADDON_VERSION, FRAME_PORT, HA_TOKEN
from fixture import load_fixture
from layouts_store import load_layouts


def _new_api_key() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def _new_ota_password() -> str:
    return secrets.token_urlsafe(12)


def load_panel_setup(default_host: str = "homeassistant.local") -> dict:
    """Load or initialize the ESPHome panel setup wizard state."""
    cfg = {}
    if config.panel_setup_path().exists():
        try:
            cfg = json.loads(config.panel_setup_path().read_text())
        except Exception:
            cfg = {}
    changed = False
    defaults = {
        "device_name": runtime.ESPHOME_DEVICE.replace("_", "-"),
        "display": load_layouts().get("display", T.DEFAULT_DISPLAY),
        "ha_host": default_host,
        "wifi_ssid": "",
        "wifi_password": "",
        "api_encryption_key": _new_api_key(),
        "ota_password": _new_ota_password(),
        "refresh_interval": "5min",
        "use_secrets": False,
    }
    for k, v in defaults.items():
        if not cfg.get(k) and k not in ("wifi_ssid", "wifi_password", "use_secrets"):
            cfg[k] = v
            changed = True
        elif k not in cfg:
            cfg[k] = v
            changed = True
    if changed:
        save_panel_setup(cfg)
    return cfg


def save_panel_setup(cfg: dict) -> dict:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    dev = re.sub(r"[^a-z0-9-]+", "-", str(cfg.get("device_name") or "crowpanel-epaper").strip().lower()).strip("-")
    cfg["device_name"] = dev or "crowpanel-epaper"
    runtime.ESPHOME_DEVICE = cfg["device_name"].replace("-", "_")
    tmp = config.panel_setup_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(config.panel_setup_path())
    return cfg


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


def generate_esphome_yaml(cfg: dict) -> tuple[str, str]:
    """Build ready-to-flash crowpanel-epaper.yaml and companion secrets.yaml."""
    display_id = cfg.get("display") or load_layouts().get("display", T.DEFAULT_DISPLAY)
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

    base_url = f"{scheme}://{host_only}:{port}"
    token_q = f"?token={urllib.parse.quote(config.FRAME_TOKEN)}" if config.FRAME_TOKEN else ""
    frames_epf_url = f"{base_url}/frames.epf{token_q}"

    use_secrets = bool(cfg.get("use_secrets"))
    ssid = (cfg.get("wifi_ssid") or "").strip()
    pw = cfg.get("wifi_password") or ""
    api_key = (cfg.get("api_encryption_key") or "").strip() or _new_api_key()
    ota_pw = (cfg.get("ota_password") or "").strip() or _new_ota_password()
    raw_interval = cfg.get("refresh_interval") or "5min"
    m_int = re.search(r"\d+", str(raw_interval))
    initial_min = max(1, min(60, int(m_int.group(0)))) if m_int else 5
    try:
        orient = int(cfg.get("orientation") if "orientation" in cfg else load_layouts().get("orientation", 0))
    except (TypeError, ValueError):
        orient = 0

    known_secrets = _inspect_existing_secrets()
    if use_secrets and "api_encryption_key" in known_secrets:
        api_key_line = "!secret api_encryption_key"
    else:
        api_key_line = _yaml_str(api_key)

    if use_secrets and "ota_password" in known_secrets:
        ota_pw_line = "!secret ota_password"
    else:
        ota_pw_line = _yaml_str(ota_pw)

    if (use_secrets or not ssid) and "wifi_ssid" in known_secrets:
        wifi_ssid_line = "!secret wifi_ssid"
    else:
        wifi_ssid_line = _yaml_str(ssid)

    if (use_secrets or not pw) and "wifi_password" in known_secrets:
        wifi_pw_line = "!secret wifi_password"
    else:
        wifi_pw_line = _yaml_str(pw)

    yaml_text = firmware_gen.render(
        disp=disp, version=ADDON_VERSION, device_name=dev_name, frames_url=_yaml_str(frames_epf_url),
        api_key=api_key_line, ota_password=ota_pw_line, wifi_ssid=wifi_ssid_line, wifi_password=wifi_pw_line,
        interval_min=initial_min, orientation=orient)

    secrets_text = f"""# Put these in your ESPHome secrets.yaml if using !secret references:
wifi_ssid: {_yaml_str(ssid or "your-wifi-ssid")}
wifi_password: {_yaml_str(pw or "your-wifi-password")}
api_encryption_key: {_yaml_str(api_key)}
ota_password: {_yaml_str(ota_pw)}
"""
    return yaml_text, secrets_text


async def _detect_panel_connection(device_slug: str) -> dict:
    """Whether Home Assistant sees the panel, found by its registry IDs (see PanelLink)."""
    if not HA_TOKEN:
        panel_fix = load_fixture().get("panel") or {}
        return {"connected": False, "ip": None, "rssi": panel_fix.get("rssi"), "node": None,
                "problem": "running without Home Assistant"}
    return await runtime.LINK.connection()


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
        print(f"could not query supervisor for external port: {exc!r}", flush=True)
    return FRAME_PORT
