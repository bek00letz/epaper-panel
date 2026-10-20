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


def display_settled(disp: dict) -> str:
    """A C++ expression: the display has finished its last refresh, so the panel may sleep
    (deep sleep cuts the display's power). The CrowPanel driver refreshes in the
    background and parks its loop when done; the Waveshare driver can't say, so the
    panel waits long enough for a full refresh after its last redraw, and not at all
    when nothing was redrawn since it woke."""
    if disp["esphome_component"].startswith("github://"):
        return "id(epd).is_idle()"
    return "id(last_redraw_ms) == 0 || millis() - id(last_redraw_ms) > 6000"


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


def wifi_block(networks: list[tuple[str, str]], hotspot: tuple[str, str] | None = None) -> str:
    """One network connects straight away; several are scanned for, so the panel
    joins whichever it finds (at home, at work). Values are YAML scalars.

    `hotspot` (ssid, password): when it finds none of them, the panel opens
    its own Wi-Fi with a page for choosing a network from a phone. A network
    chosen there replaces these until the panel is installed again (ESPHome).

    A network with a blank name is left out (ESPHome refuses one). With none
    left and its own Wi-Fi on, the block has only that: the network is chosen
    from a phone. With neither, ESPHome says a network is needed; the editor
    asks for one before it gets here."""
    networks = [(s, p) for s, p in networks if not _blank(s)]
    if not networks and hotspot:
        lines = ["wifi:", "  # No network yet: it opens its own Wi-Fi to choose one from a phone."]
        return "\n".join(lines + _hotspot_lines(hotspot))
    if len(networks) <= 1:
        ssid, password = networks[0] if networks else ('""', '""')
        lines = ["wifi:", f"  ssid: {ssid}", f"  password: {password}", "  fast_connect: true"]
    else:
        lines = ["wifi:", "  # Joins whichever of these it finds.", "  networks:"]
        for ssid, password in networks:
            lines += [f"    - ssid: {ssid}", f"      password: {password}"]
    if hotspot:
        lines += ["  # Finds none of them: its own Wi-Fi, to choose a network from a phone."]
        lines += _hotspot_lines(hotspot)
    return "\n".join(lines)


def _blank(scalar: str) -> bool:
    """A YAML scalar that is an empty string ('""', "''" or nothing)."""
    return str(scalar or "").strip() in ("", '""', "''")


def _hotspot_lines(hotspot: tuple[str, str]) -> list[str]:
    return ["  ap:", f"    ssid: {hotspot[0]}", f"    password: {hotspot[1]}", "", "captive_portal:"]


def render(*, disp: dict, version: str, device_name: str, frames_url: str, api_key: str,
           wifi_ssid: str, wifi_password: str, interval_min: int,
           orientation: int, friendly_name: str = '"E-paper panel"',
           more_networks: list[tuple[str, str]] = (), hotspot: tuple[str, str] | None = None) -> str:
    """The YAML text. Credential and name arguments are YAML scalars, e.g. '"abc"' or '!secret x'.

    `friendly_name` is what Home Assistant calls the panel (the screen's name).
    `more_networks`: Wi-Fi networks besides the first, as (ssid, password).
    `hotspot`: (ssid, password) of its own setup Wi-Fi, or None for none."""
    component, block = display_blocks(disp)
    values = {
        "DISPLAY_NAME": disp["name"], "SKU": disp["sku"], "W": str(disp["w"]), "H": str(disp["h"]),
        "VERSION": version or "dev", "DEVICE_NAME": device_name, "FRAMES_URL": frames_url,
        "COMPONENT_REF": component_ref(version), "DISPLAY_COMPONENT": component,
        "DISPLAY_BLOCK": block, "DISPLAY_SETTLED": display_settled(disp), "API_KEY": api_key,
        "WIFI_BLOCK": wifi_block([(wifi_ssid, wifi_password), *more_networks], hotspot),
        "FRIENDLY_NAME": friendly_name,
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
