"""The panel's ESPHome YAML, from one template (firmware/panel.yaml).

This is the only source of the panel firmware's configuration. Panel setup
writes its output into Home Assistant's ESPHome folder, and the repository's
esphome/crowpanel-epaper.yaml is the same output for a reference setup (a test
keeps the two identical).
"""
from __future__ import annotations

import re
from pathlib import Path

TEMPLATE = Path(__file__).parent / "firmware" / "panel.yaml"
REPO = "bek00letz/epaper-panel"

# The CrowPanel display driver, pinned to the commit this firmware was built
# and tested against.
CROWPANEL_COMPONENT = "github://ESPBoards/esphome-lvgl-crowpanel-epaper-5.79-4.2@319ad7c6ffc5e15092c7fbff2ce2b7f4500efc05"


def component_ref(version: str) -> str:
    """The git ref the firmware's `epf` component is built from: the add-on's own release tag."""
    v = (version or "").strip()
    return f"v{v}" if re.fullmatch(r"\d+\.\d+\.\d+", v) else "main"


def button_pins(orientation: int) -> dict[str, int]:
    """Turning the panel over swaps which physical buttons mean next/previous and top/bottom."""
    if int(orientation) in (180, 270):
        return {"NEXT_PIN": 6, "PREV_PIN": 4, "TOP_PIN": 1, "BOTTOM_PIN": 2}
    return {"NEXT_PIN": 4, "PREV_PIN": 6, "TOP_PIN": 2, "BOTTOM_PIN": 1}


def display_blocks(disp: dict) -> tuple[str, str]:
    """(extra external component line, display: block without its lambda)."""
    if disp["esphome_component"].startswith("github://"):
        component = f"  - source: {CROWPANEL_COMPONENT}\n"
        block = f"""display:
  - platform: crowpanel_epaper
    id: epd
    model: "{disp["esphome_model"]}"
    clk_pin: 12
    mosi_pin: 11
    cs_pin: 45
    dc_pin: 46
    reset_pin: 47
    busy_pin: 48
    invert_colors: true
    # Full refreshes are decided by the panel's ghost-clearing policy
    # (WaveformPolicy), not by a fixed count.
    full_update_every: 1000000
    update_interval: never
    auto_clear_enabled: false"""
    else:
        component = ""
        block = f"""display:
  - platform: waveshare_epaper
    id: epd
    model: "{disp["esphome_model"]}"
    cs_pin: 45
    dc_pin: 46
    busy_pin: 48
    reset_pin: 47
    reset_duration: 2ms
    update_interval: never
    auto_clear_enabled: false"""
    return component, block


def render(*, disp: dict, version: str, device_name: str, frames_url: str, api_key: str,
           wifi_ssid: str, wifi_password: str, interval_min: int,
           orientation: int) -> str:
    """The YAML text. Credential arguments are YAML scalars, e.g. '"abc"' or '!secret x'."""
    component, block = display_blocks(disp)
    values = {
        "DISPLAY_NAME": disp["name"], "SKU": disp["sku"], "W": str(disp["w"]), "H": str(disp["h"]),
        "VERSION": version or "dev", "DEVICE_NAME": device_name, "FRAMES_URL": frames_url,
        "COMPONENT_REF": component_ref(version), "DISPLAY_COMPONENT": component,
        "DISPLAY_BLOCK": block, "API_KEY": api_key,
        "WIFI_SSID": wifi_ssid, "WIFI_PASSWORD": wifi_password,
        "INTERVAL_MIN": str(max(1, min(60, int(interval_min)))),
        **{k: str(v) for k, v in button_pins(orientation).items()},
    }
    text = TEMPLATE.read_text()
    for key, val in values.items():
        text = text.replace(f"@{key}@", val)
    left = re.findall(r"@[A-Z][A-Z_]+@", text)
    if left:
        raise ValueError(f"firmware template has unfilled placeholders: {sorted(set(left))}")
    return text
