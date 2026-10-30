"""The panel's ESPHome YAML, from one template (firmware/panel.yaml).

This is the only source of the panel firmware's configuration. Panel setup
writes its output into Home Assistant's ESPHome folder, and the repository's
esphome/crowpanel-epaper.yaml is the same output for a reference setup (a test
keeps the two identical).
"""
from __future__ import annotations

import re
from pathlib import Path

from render import theme as T

TEMPLATE = Path(__file__).parent / "firmware" / "panel.yaml"
REPO = "bek00letz/epaper-panel"

# The CrowPanel display driver, pinned to the commit this firmware was built
# and tested against.
CROWPANEL_COMPONENT = "github://ESPBoards/esphome-lvgl-crowpanel-epaper-5.79-4.2@319ad7c6ffc5e15092c7fbff2ce2b7f4500efc05"


def component_ref(version: str) -> str:
    """The git ref the firmware's `epf` component is built from: the add-on's own release tag."""
    v = (version or "").strip()
    return f"v{v}" if re.fullmatch(r"\d+\.\d+\.\d+", v) else "main"


# What each chip can do, for the boards in theme.BOARDS: its name, and the pins
# that can wake it from deep sleep (the ESP32-S3's RTC pins; on the ESP32-C3,
# GPIO 0-5 only, as Espressif's datasheet and Seeed's XIAO ESP32-C3 wiki say).
CHIPS = {
    "esp32s3": {"name": "ESP32-S3", "wake_pins": range(0, 22)},
    "esp32c3": {"name": "ESP32-C3", "wake_pins": range(0, 6)},
}

# What each button does is in the template, once per role (firmware/panel.yaml,
# "@IF BUTTON_<ROLE>@"); a board says which roles it has and on which pins.
BUTTON_ROLES = ("next", "prev", "ok", "top", "bottom", "one")


def board_of(disp: dict) -> dict:
    """The board a display profile is wired to (theme.BOARDS)."""
    return T.BOARDS[disp["board"]]


def button_pins(board: dict, orientation: int) -> dict[str, int]:
    """Each button's pin by what it does. Turning the panel over (180° or 270°) swaps
    which physical buttons mean what, as the board says."""
    return dict(board["buttons_turned"] if int(orientation) in (180, 270) else board["buttons"])


def wake_buttons(board: dict) -> list[int]:
    """The buttons' pins that can wake the panel from deep sleep, lowest first."""
    can = CHIPS[board["chip"]]["wake_pins"]
    return sorted({p for p in board["buttons"].values() if p in can})


def wake_mask(board: dict) -> str:
    """The C++ bit mask of those pins, for epf::power_prepare_sleep ("0": none)."""
    return " | ".join(f"(1ULL << {p})" for p in wake_buttons(board)) or "0"


_COUNTS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def sleep_note(disp: dict) -> str:
    """The comment over go_to_sleep: what wakes the panel, and how the display sleeps."""
    board = board_of(disp)
    chip, pins = CHIPS[board["chip"]], wake_buttons(board)
    every = sorted(set(board["buttons"].values()))
    listed = ", ".join(str(p) for p in pins)
    if pins and pins == every:
        lines = [f"check or a press of any of the {_COUNTS.get(len(pins), len(pins))} buttons (GPIO {listed}, all",
                 f"RTC-capable on the {chip['name']}; active-low, so any one pressed wakes it)."]
    elif pins:
        lines = [f"check or a press of a button on GPIO {listed} (active-low); its other buttons",
                 f"can't wake the {chip['name']}."]
    else:
        can = chip["wake_pins"]
        lines = [f"check. Its buttons can't wake it (on the {chip['name']} only GPIO {can.start}-{can.stop - 1}",
                 "can), so the add-on's next check or its Reset button does."]
    if keeps_picture(disp):
        lines.append("The display sleeps too, powered: the next wake's first change is partial.")
    elif board["display_power"] is None:
        lines.append("The display sleeps too, still powered; its first change after a wake is a full refresh.")
    else:
        lines.append("Its display is switched off: the first change after a wake is a full refresh.")
    return "\n".join(f"  # {line}" for line in lines)


def display_settled(disp: dict) -> str:
    """A C++ expression: the display has finished its last refresh, so the panel may sleep
    (deep sleep cuts the display's power). The CrowPanel driver refreshes in the
    background and parks its loop when done. A Waveshare driver whose refresh returns
    only once the screen is done (the profile's "refresh_waits") is settled when the
    redraw is; one that can't say gets long enough for a full refresh after its last
    redraw, and not at all when nothing was redrawn since it woke."""
    if disp["esphome_component"].startswith("github://"):
        return "id(epd).is_idle()"
    if disp.get("refresh_waits"):
        return "true"
    return "id(last_redraw_ms) == 0 || millis() - id(last_redraw_ms) > 6000"


# How the redraw script asks each driver for a full (ghost-clearing) refresh is
# the profile's "full_refresh" (theme.DISPLAYS). Full refreshes are the panel's
# policy (WaveformPolicy), so each driver's own count is set out of reach.


# Low Power Mode, TRMNL's way (0.13): the display stays powered through deep
# sleep, so the first change after a wake is a partial refresh, no flash. Its
# controller's memory of the picture doesn't survive that sleep (the 5.79", 29
# Oct: every page stayed on screen), so that first refresh drives every pixel
# (epf_core.h, "The first refresh after a deep sleep"). False is the way back to
# 0.12's behaviour (the display switched off in deep sleep, a full refresh after
# every wake that changes the picture).
KEEP_DISPLAY_ASLEEP = True

# After such a sleep, how each driver is told the screen still shows the
# picture, so it doesn't start with a full refresh, is the profile's
# "keep_picture"; how its first refresh is made to drive every pixel is its
# "drive_every_pixel" (epf_client.h). A size without both always switches its
# display off in deep sleep: a full refresh after every wake.


def keeps_picture(disp: dict) -> bool:
    """Whether the display keeps its picture through deep sleep, so the next wake's first
    change is partial: powered through it (its pin held, or a board with no switch), and
    its driver has both calls for it."""
    return bool(KEEP_DISPLAY_ASLEEP and disp.get("keep_picture") and disp.get("drive_every_pixel"))


# What epf::power_begin is told when the display is always powered, with no pin to hold
# (epf_client.h); -1 is switched off in deep sleep.
ALWAYS_POWERED = -2


def keep_display_pin(disp: dict) -> int:
    """The pin the firmware holds on through deep sleep; ALWAYS_POWERED when it keeps its
    picture on a board with no pin for the display; -1 when it's switched off."""
    if not keeps_picture(disp):
        return -1
    pin = board_of(disp)["display_power"]
    return ALWAYS_POWERED if pin is None else pin


def power_begin_arg(disp: dict) -> str:
    """What the firmware's start-up passes to epf::power_begin, by name where it isn't a pin."""
    pin = keep_display_pin(disp)
    return "epf::DISPLAY_ALWAYS_POWERED" if pin == ALWAYS_POWERED else str(pin)


def keep_picture(disp: dict) -> str:
    """The C++ statement run at start-up when the display kept its picture through sleep."""
    return disp["keep_picture"] if keeps_picture(disp) else "{}"


def drive_every_pixel(disp: dict) -> str:
    """The C++ statement run once the first picture after such a sleep is drawn, before
    its refresh: it makes that refresh drive every pixel."""
    return disp["drive_every_pixel"] if keeps_picture(disp) else "{}"


# Partial refresh on a screen whose profile keeps a full-refresh way back ("full_only":
# the Seeed XIAO 7.5", 30 Oct, untried on a real panel). False builds those screens as
# first built: ESPHome's full-refresh driver, a flash on every change.
PARTIAL_REFRESH = True


def firmware_profile(disp: dict) -> dict:
    """The profile the firmware is built from: the size's own, or its way back."""
    if not PARTIAL_REFRESH and disp.get("full_only"):
        return {**disp, **disp["full_only"]}
    return disp


def full_refresh(disp: dict) -> str:
    """The C++ statement that makes the display's next refresh a full one. A driver
    not listed (one whose every refresh is full, "always_full", or a size the editor
    doesn't offer) is left to refresh as it does."""
    return disp.get("full_refresh") or "{}"


def _busy_pin(board: dict) -> str:
    pin = board["display_pins"]["busy"]
    return f"\n      number: {pin}\n      inverted: true" if board["busy_inverted"] else f" {pin}"


def display_blocks(disp: dict) -> tuple[str, str]:
    """(extra external component line, display: block without its lambda), wired as its board is."""
    board = board_of(disp)
    spi, pins = board["spi"], board["display_pins"]
    if disp["esphome_component"].startswith("github://"):
        component = f"  - source: {CROWPANEL_COMPONENT}\n"
        block = f"""display:
  - platform: crowpanel_epaper
    id: epd
    model: "{disp["esphome_model"]}"
    clk_pin: {spi["clk"]}
    mosi_pin: {spi["mosi"]}
    cs_pin: {pins["cs"]}
    dc_pin: {pins["dc"]}
    reset_pin: {pins["reset"]}
    busy_pin:{_busy_pin(board)}
    invert_colors: true
    # Full refreshes are decided by the panel's ghost-clearing policy
    # (WaveformPolicy), not by a fixed count.
    full_update_every: 1000000
    update_interval: never
    auto_clear_enabled: false"""
    else:
        component = ""
        block = f"""spi:
  clk_pin: {spi["clk"]}
  mosi_pin: {spi["mosi"]}

display:
  - platform: waveshare_epaper
    id: epd
    model: "{disp["esphome_model"]}"
    cs_pin: {pins["cs"]}
    dc_pin: {pins["dc"]}
    busy_pin:{_busy_pin(board)}
    reset_pin: {pins["reset"]}
{_refresh_count(disp)}    update_interval: never
    auto_clear_enabled: false"""
    return component, block


def _refresh_count(disp: dict) -> str:
    """The Waveshare driver's own count of partial refreshes, set out of reach: the panel's
    policy decides. A driver whose every refresh is full has no count (ESPHome refuses one)."""
    if disp.get("always_full"):
        return ""
    return """    # Full refreshes are decided by the panel's ghost-clearing policy
    # (WaveformPolicy), not by a fixed count.
    full_update_every: 1000000
"""


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


_SECTION = re.compile(r"^@IF ([A-Z_]+)@\n(.*?)^@END@\n", re.M | re.S)


def sections(text: str, flags: dict[str, bool]) -> str:
    """The template's board-dependent parts: each "@IF NAME@" line up to its "@END@"
    line is kept (without those two lines) when the flag is on, dropped when it's off."""
    def keep(m):
        if m.group(1) not in flags:
            raise ValueError(f"firmware template has an unknown section: {m.group(1)}")
        return m.group(2) if flags[m.group(1)] else ""
    return _SECTION.sub(keep, text)


def render(*, disp: dict, version: str, device_name: str, frames_url: str, ota_key: str,
           wifi_ssid: str, wifi_password: str, interval_min: int,
           orientation: int, friendly_name: str = '"E-paper panel"',
           more_networks: list[tuple[str, str]] = (), hotspot: tuple[str, str] | None = None) -> str:
    """The YAML text. Credential and name arguments are YAML scalars, e.g. '"abc"' or '!secret x'.

    `friendly_name` is what Home Assistant calls the panel (the screen's name).
    `more_networks`: Wi-Fi networks besides the first, as (ssid, password).
    `hotspot`: (ssid, password) of its own setup Wi-Fi, or None for none."""
    disp = firmware_profile(disp)
    component, block = display_blocks(disp)
    board = board_of(disp)
    buttons = button_pins(board, orientation)
    flags = {
        "PSRAM": bool(board["psram"]),
        "DISPLAY_POWER": board["display_power"] is not None,
        "GHOST": not disp.get("always_full"),
        **{f"BUTTON_{role.upper()}": role in buttons for role in BUTTON_ROLES},
    }
    values = {
        "DISPLAY_NAME": disp["name"], "SKU": disp["sku"], "W": str(disp["w"]), "H": str(disp["h"]),
        "VERSION": version or "dev", "DEVICE_NAME": device_name, "FRAMES_URL": frames_url,
        "COMPONENT_REF": component_ref(version), "DISPLAY_COMPONENT": component,
        "DISPLAY_BLOCK": block, "DISPLAY_SETTLED": display_settled(disp), "FULL_REFRESH": full_refresh(disp),
        "ESPHOME_BOARD": board["esphome_board"], "PSRAM_MODE": board["psram"],
        "DISPLAY_POWER_PIN": str(board["display_power"]), "KEEP_DISPLAY_PIN": power_begin_arg(disp),
        "KEEP_PICTURE": keep_picture(disp), "DRIVE_EVERY_PIXEL": drive_every_pixel(disp), "OTA_KEY": ota_key,
        "WIFI_BLOCK": wifi_block([(wifi_ssid, wifi_password), *more_networks], hotspot),
        "FRIENDLY_NAME": friendly_name,
        "INTERVAL_MIN": str(max(1, min(60, int(interval_min)))),
        "BUTTONS_NOTE": "\n".join(f"# {line}" for line in board["buttons_note"]),
        "SLEEP_NOTE": sleep_note(disp), "WAKE_BUTTONS": wake_mask(board),
        **{f"{role.upper()}_PIN": str(pin) for role, pin in buttons.items()},
    }
    unknown = set(buttons) - set(BUTTON_ROLES)
    if unknown:
        raise ValueError(f"{disp['board']} has buttons the template doesn't know: {sorted(unknown)}")
    text = sections(TEMPLATE.read_text(), flags)
    for key, val in values.items():
        text = text.replace(f"@{key}@", val)
    left = re.findall(r"@[A-Z][A-Z_]+@|@IF [A-Z_]+@", text)
    if left:
        raise ValueError(f"firmware template has unfilled placeholders: {sorted(set(left))}")
    return text
