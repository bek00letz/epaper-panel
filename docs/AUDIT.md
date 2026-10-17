# E-Paper Panel Code Audit & Remediation Log

## Overview
This document records the security, stability, and code quality audit conducted on the `epaper-panel` repository (Home Assistant Add-on v0.8.16).

---

## Findings & Remediations

### 1. Fatal Runtime Crash: `UnboundLocalError: cat_pill_widths`
- **Component:** `addon/app/server.py`
- **Severity:** Critical
- **Details:** `cat_pill_widths` was returned by `build_frames()` but never initialized in the function body, leading to an immediate crash on every render cycle.
- **Fix:** Initialized `cat_pill_widths = []`, populated it with clamped widths, and added a safe fallback `[110]` on the empty frame path.

### 2. Physical Refresh Denial-of-Service & Auth Bypass
- **Component:** `addon/app/server.py`
- **Severity:** High
- **Details:** The frame server on LAN port 8099 exposed `/api/action/refresh` and `/api/action/page` without verifying tokens, allowing unauthenticated network actors to trigger continuous physical e-paper flashes. Furthermore, the server only checked `X-Frame-Token` and `?token=`, rejecting legitimate daemons sending `Authorization: Bearer <token>`.
- **Fix:** Added Bearer token parsing to `_check_frame_auth(request)` and enforced token verification on both action endpoints. Implemented `step_panel_page` to properly forward page step requests to ESPHome.

### 3. ESP32-S3 PSRAM Buffer Overflow in Firmware
- **Component:** `esphome/crowpanel-epaper.yaml` and `addon/app/server.py`
- **Severity:** High
- **Details:** Active pill inversion loops in the display lambda lacked screen boundary validation (`rx < dw && ry < dh`). Category pills extending past margins wrote to invalid PSRAM offsets, causing `LoadProhibited`/`StoreProhibited` crash loops on the ESP32-S3.
- **Fix:** Enforced `if (rx >= 0 && rx < dw && ry >= 0 && ry < dh)` across both Category and Sub-item inversion loops.

### 4. Credential Disclosure in Setup Endpoints
- **Component:** `addon/app/server.py`
- **Severity:** Medium
- **Details:** `api_panel_setup_get` masked `config.wifi_password` in the JSON metadata object but passed raw unmasked configuration to `generate_esphome_yaml`, returning plaintext Wi-Fi passwords and OTA keys inside `yaml` and `secrets_yaml`.
- **Fix:** Ensured `generate_esphome_yaml` uses the masked config on GET requests and preserves masking on POST requests when unchanged.

### 5. Feed Secret Cross-Contamination
- **Component:** `addon/app/feeds/__init__.py`
- **Severity:** Medium
- **Details:** `unmask_secrets` fell back to `existing[idx]` by numerical index if a feed name didn't match. Reordering or inserting feeds caused new feeds to inherit secrets belonging to other feeds.
- **Fix:** Removed positional fallback (`prev = by_name.get(slug) or {}`). Secrets are now matched strictly by feed slug.

### 6. Runaway 10-Second Render Loop
- **Component:** `addon/app/server.py`
- **Severity:** High
- **Details:** `render_loop()` capped sleep duration with `min(10, REFRESH)`, ignoring configured refresh intervals and rendering every 10 seconds.
- **Fix:** Changed to `await asyncio.sleep(REFRESH)` so the user-configured interval (e.g. 5m, 10m) is honored.

### 7. Stale Layout State in ESPHome
- **Component:** `esphome/crowpanel-epaper.yaml` and `addon/app/server.py`
- **Severity:** Medium
- **Details:** Sensors `ha_cat_offsets` and `ha_cat_sizes` checked `if (id(...).empty())`, ignoring subsequent configuration updates until the ESP32 was power-cycled.
- **Fix:** Rewrote sensor handlers to parse into a temporary vector and overwrite existing vectors dynamically. Added `ha_cat_pill_widths` text sensor for real-time pill width synchronization.

### 8. Defensive Jinja Template & Replace Hardening
- **Component:** `addon/app/render/binding.py`
- **Severity:** Medium
- **Details:** Accessing `states['...'].last_changed` failed with Jinja undefined errors if an entity was not yet loaded. In addition, non-dict `replace` values caused an `AttributeError`.
- **Fix:** Wrapped `last_changed` with `states[qent] is defined and states[qent] is not none` conditional checks and validated `isinstance(repl_map, dict)`.

### 9. Layout Boundary Clamping
- **Component:** `addon/app/render/layout.py` and `addon/app/render/theme.py`
- **Severity:** Low
- **Details:** Invalid `month` / `year` values crashed calendar rendering. Unchecked grid rows/columns caused division-by-zero or negative box heights. Category pill widths in the footer could overlap sub-item pills.
- **Fix:** Clamped `month` to 1..12, clamped grid dimensions to `>= 16px`, and bounded footer category pill width against the sub-item pill.
