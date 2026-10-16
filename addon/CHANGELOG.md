# Changelog

## 0.6.0
- **Mounting Orientation & Rotation (`0°`, `90°`, `180°`, `270°`):** Switch between `Landscape (0°)`, `Upside-down (180°)`, `Portrait CW (90°)`, and `Portrait CCW (270°)` directly from the editor header or `Panel setup` wizard. Pages are rendered in their logical aspect ratio (`792×272` or `272×792`) in the editor and automatically rotated into the panel's physical `792×272` framebuffer on the server, so orientation changes take effect on `Save` / `Push to panel` without reflashing ESPHome.
- **One-Click Page Reflow:** Switching between Landscape (`792×272`) and Portrait (`272×792`) adapts the canvas aspect ratio and safe-area guides (`y >= 752` in portrait) and offers a `Reflow` button (with Undo) to restack elements cleanly for the new orientation.
- **Automatic Rocker Button Swap (`180°` / `270°`):** Generating ESPHome YAML in the `Panel setup` wizard for `180°` or `270°` mounts automatically swaps `key_next` and `key_prev` GPIO pins (`4` and `6`) so the physical rocker buttons match the inverted/rotated mount.

## 0.5.0
- **Panel Setup & ESPHome Firmware Wizard:** Configure your Home Assistant host/IP, device name, Wi-Fi, and auto-generated API encryption key & OTA password directly in the editor UI (`Panel setup`), with one-click YAML copy/download and live Home Assistant panel connection status.
- **Visual `Show if` Condition Builder:** Configure `only when true` and `interrupt only` page conditions without writing raw Jinja (with a `Custom Jinja` mode still available for complex expressions).
- **Interactive Rotation Bar & Full Strip Preview:** Reorder, add/weight, or remove rotation pages via interactive pills, and preview the full rendered `/frames.png` strip directly from the header status pill or `Full strip` button.
- **Canvas Safe-Area Guides & Quick Alignment:** Toggle footer (`y >= 232`) and held-page padlock (`x >= 752`) margin guides on the canvas, and use quick-align (`Center X`, `Center Y`, `Full W`) and layer order (`↑` / `↓`) buttons in the inspector.

## 0.4.0
- Hardened security across the editor UI, Jinja bindings, Home Assistant API paths, and data source credentials.
- Fixed numeric elements with suffixes (`°`, `%`) rendering `--`, negative sparkline curves, and 1-page alert strip holds.
- Added font caching, shared HTTP sessions, `ETag` / `304 Not Modified` frame responses, and immediate re-render on save/push.
