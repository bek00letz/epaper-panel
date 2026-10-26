"""Panel setup: its saved settings and the ESPHome YAML it writes."""

import base64
import health
import json
import os
import re
import unicodedata
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


def _new_update_key() -> str:
    """A panel's update key: what its updates over Wi-Fi are encrypted with (ESPHome's form)."""
    return base64.b64encode(os.urandom(32)).decode("ascii")


def _take_old_key(cfg: dict) -> bool:
    """Before 0.22 a panel's one key was its Home Assistant key too (`api_encryption_key`). Home
    Assistant sets that one now; the panel still runs the old key for updates, so it becomes the
    update key and the next Install from ESPHome is accepted. Whether anything changed."""
    old = cfg.pop("api_encryption_key", None)
    if old and not cfg.get("ota_key"):
        cfg["ota_key"] = old
    return old is not None


def load_panel_setup(dev: dict, default_host: str = "homeassistant.local") -> dict:
    """A panel's setup (its ESPHome settings), with defaults filled in and kept.

    The size and orientation are the device's own (`display` is shown here
    for the form, and saving it changes the device)."""
    cfg = dict(dev.get("setup") or {})
    changed = _take_old_key(cfg)
    defaults = {
        "device_name": (runtime.ESPHOME_DEVICE if dev.get("install_token") else
                        re.sub(r"[^a-z0-9]+", "-", str(dev.get("name") or "").lower()).strip("-")
                        or f"epaper-{dev['id']}").replace("_", "-"),
        "ha_host": default_host,
        "wifi_ssid": "",
        "wifi_password": "",
        # Never shown, logged or sent to the browser (web._masked_setup).
        "ota_key": _new_update_key(),
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
    """Keep a panel's setup with its device (devices.json is 0600: the Wi-Fi password and update key)."""
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


def _wpa_ok(password: str) -> bool:
    """A Wi-Fi password ESPHome takes: none (an open network), 8 to 63 characters, or a 64-digit hex key."""
    n = len(password)
    return n == 0 or 8 <= n <= 63 or (n == 64 and all(c in "0123456789abcdefABCDEF" for c in password))


def hotspot_password_ok(password: str) -> bool:
    """Its own Wi-Fi is never open: a password ESPHome takes, 8 to 63 characters (or a 64-digit hex key)."""
    return bool(password) and _wpa_ok(password)


def wifi_problems(cfg: dict) -> list[str]:
    """What in a panel's Wi-Fi would make ESPHome refuse its file, said so it can be fixed before Install.
    Mirrors what generate_esphome_yaml writes (a value from secrets.yaml can't be checked)."""
    known = _inspect_existing_secrets()
    use_secrets = bool(cfg.get("use_secrets"))
    ssid = str(cfg.get("wifi_ssid") or "").strip()
    pw = str(cfg.get("wifi_password") or "")
    more = more_networks(cfg)
    problems = []
    if not ssid and "wifi_ssid" not in known and not more and not cfg.get("hotspot", True):
        problems.append("It has no way online: add a Wi-Fi network, or turn on its own Wi-Fi when it's lost.")
    first = [(ssid, pw)] if ssid and not ((use_secrets or not pw) and "wifi_password" in known) else []
    for name, password in first + [(n["ssid"], n["password"]) for n in more]:
        if not _wpa_ok(password):
            problems.append(f"The password for {name} is {len(password)} characters. Wi-Fi passwords are 8 to 63; "
                            "check it, or leave it empty for an open network.")
    own = str(cfg.get("hotspot_password") or "")
    if cfg.get("hotspot", True) and not hotspot_password_ok(own):
        problems.append(f"The password for its own Wi-Fi is {len(own)} characters. It needs 8 to 63.")
    return problems


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
    ota_key = (cfg.get("ota_key") or "").strip() or _new_update_key()
    # Its own timer, which runs only while it's always on: Update every (timing.py), never a setting here.
    initial_min = kinds.of(dev).update_minutes(dev)
    try:
        orient = int(cfg.get("orientation") if "orientation" in cfg else view.get("orientation", 0))
    except (TypeError, ValueError):
        orient = 0

    known_secrets = _inspect_existing_secrets()
    # A panel whose key lived in secrets.yaml keeps it there: that's the key it runs.
    if use_secrets and "api_encryption_key" in known_secrets:
        ota_key_line = "!secret api_encryption_key"
    else:
        ota_key_line = _yaml_str(ota_key)


    if (use_secrets or not ssid) and "wifi_ssid" in known_secrets:
        wifi_ssid_line = "!secret wifi_ssid"
    else:
        wifi_ssid_line = _yaml_str(ssid)

    if (use_secrets or not pw) and "wifi_password" in known_secrets:
        wifi_pw_line = "!secret wifi_password"
    else:
        wifi_pw_line = _yaml_str(pw)

    more = [(_yaml_str(n.get("ssid")), _yaml_str(n.get("password") or "")) for n in more_networks(cfg)]
    if wifi_ssid_line == '""' and more:
        # No first network but others: the first of them leads (ESPHome refuses a blank name).
        (wifi_ssid_line, wifi_pw_line), more = more[0], more[1:]
    yaml_text = firmware_gen.render(
        disp=disp, version=ADDON_VERSION, device_name=dev_name, frames_url=_yaml_str(frames_epf_url),
        ota_key=ota_key_line, wifi_ssid=wifi_ssid_line, wifi_password=wifi_pw_line,
        interval_min=initial_min, orientation=orient, friendly_name=_yaml_str(ha_name(dev)),
        more_networks=more,
        hotspot=(_yaml_str(hotspot_name(dev)), _yaml_str(cfg.get("hotspot_password") or _new_hotspot_password()))
        if cfg.get("hotspot", True) else None)

    secrets_text = f"""# Put these in your ESPHome secrets.yaml if using !secret references:
wifi_ssid: {_yaml_str(ssid or "your-wifi-ssid")}
wifi_password: {_yaml_str(pw or "your-wifi-password")}
"""
    return yaml_text, secrets_text


async def _detect_panel_connection(dev: dict) -> dict:
    """Whether Home Assistant sees the panel, found by its registry IDs (see PanelLink)."""
    link = kinds.of(dev).link(dev)
    # Firmware from 0.22 on says its MAC when it downloads: it's installed and fetching.
    st = devices.state(dev["id"])
    seen = {"installed": bool(st.get("mac")), "home_ip": st.get("ip") or None}
    if not HA_TOKEN or link is None:
        panel_fix = load_fixture().get("panel") or {}
        return {"connected": False, "ip": None, "rssi": panel_fix.get("rssi"), "network": None, "node": None,
                "waiting": None, **seen,
                "problem": "running without Home Assistant" if not HA_TOKEN else "the add-on can't reach this device"}
    return {**await link.connection(), **seen}


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


# ---------------------------------------------------------------- the file in ESPHome's folder

# Before 0.13.1, saving the setup also wrote the file into ESPHome's folder. Now
# only Send to ESPHome does (the user's call): True brings the old way back.
WRITE_ON_SAVE = False

# The ESPHome add-on, by its own slug (the repository's prefix varies): stable first.
_ESPHOME_SLUG = re.compile(r"^(?:[0-9a-f]{8}_)?esphome(-beta|-dev)?$")
_dashboard_cache: dict = {"at": 0.0, "url": None}


def esphome_file_name(name: str) -> str:
    """A device name as ESPHome's own wizard names its file (esphome.helpers.friendly_name_slugify):
    accents dropped, lower case, spaces and underscores as dashes. "CrowPanel epaper" -> "crowpanel-epaper"."""
    value = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    value = value.lower().replace(" ", "_").replace("-", "_").replace("__", "_").strip("_")
    value = "".join(c for c in value if c in "abcdefghijklmnopqrstuvwxyz0123456789-_")
    return value.replace("_", "-")


def esphome_path(cfg: dict) -> Path:
    """Where ESPHome finds this panel's file: named as ESPHome's own wizard would (dashes), so a panel
    set up in ESPHome first keeps one file. Before 0.15 the add-on wrote underscores; a file it wrote
    then is kept, so nobody gets a second one."""
    name = str(cfg.get("device_name") or "crowpanel-epaper")
    before = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_") or "crowpanel_epaper"
    now = esphome_file_name(name) or "crowpanel-epaper"
    old = config.ESPHOME_DIR / f"{before}.yaml"
    if before != now and old.is_file():
        return old
    return config.ESPHOME_DIR / f"{now}.yaml"


def esphome_state(cfg: dict, disk_yaml: str) -> dict:
    """{state, file}: whether ESPHome's copy is what the editor would write now.

    state: "same", "differs", "missing", or "no_folder" (no ESPHome folder in Home Assistant)."""
    path = esphome_path(cfg)
    out = {"file": f"esphome/{path.name}"}
    if not config.ESPHOME_DIR.is_dir():
        return {**out, "state": "no_folder"}
    try:
        current = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {**out, "state": "missing"}
    except (OSError, ValueError):
        return {**out, "state": "differs"}
    return {**out, "state": "same" if current == disk_yaml else "differs"}


def write_to_esphome(dev: dict, cfg: dict, disk_yaml: str) -> Path:
    """Put the file in ESPHome's folder, keeping the one there as `<name>.yaml.previous`.

    The caller checks wifi_problems first: a file ESPHome would refuse is never written."""
    if not config.ESPHOME_DIR.is_dir():
        raise FileNotFoundError("Home Assistant has no ESPHome folder")
    target = esphome_path(cfg)
    previous = target.read_text(encoding="utf-8") if target.exists() else None
    if previous != disk_yaml:
        if previous is not None:
            # A way back: ESPHome ignores this name, a rename restores it.
            target.with_suffix(".yaml.previous").write_text(previous, encoding="utf-8")
        tmp = target.with_suffix(".yaml.tmp")
        tmp.write_text(disk_yaml, encoding="utf-8")
        tmp.replace(target)
    # The name Home Assistant will know this panel by once it's installed from this file.
    devices.update(dev["id"], setup={**(devices.get(dev["id"]).get("setup") or {}), "installed_name": ha_name(dev)})
    print(f"esphome: wrote {target}", flush=True)
    return target


async def esphome_dashboard(hass, clock=None) -> str | None:
    """The ESPHome add-on's page in Home Assistant (its ingress), or None when it isn't installed.

    Asked of the Supervisor through Home Assistant, so the add-on needs no Supervisor rights."""
    import time
    from hass import HassError
    now = (clock or time.time)()
    if now - _dashboard_cache["at"] < (600 if _dashboard_cache["url"] else 60):
        return _dashboard_cache["url"]
    url = None
    try:
        res = await hass.ws({"type": "supervisor/api", "endpoint": "/addons", "method": "get"})
        found = [a for a in (res or {}).get("addons") or [] if _ESPHOME_SLUG.match(str(a.get("slug") or ""))]
        found.sort(key=lambda a: (a.get("state") != "started", bool(_ESPHOME_SLUG.match(a["slug"]).group(1))))
        if found:
            url = f"/hassio/ingress/{found[0]['slug']}"
    except HassError as exc:
        print(f"esphome: couldn't look for its add-on: {exc}", flush=True)
    _dashboard_cache.update(at=now, url=url)
    return url
