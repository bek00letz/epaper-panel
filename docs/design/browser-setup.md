# Setup from the browser: research and options

> **Parked (the user, 26 Oct).** Not built for now. Instead, today's ESPHome
> route drops the key paste (Home Assistant 2026.8 sets the key itself), and
> the decision waits for the Seeed 7.5" with TRMNL's firmware: living with it
> may show whether CrowPanels should keep our firmware at all.
> The user's answers, should this come back: **design A**; the add-on adds the
> panel to Home Assistant for you; on plain http, all three fallbacks (link to
> the secure address, flash through Home Assistant's USB, download under
> Advanced); our own install sheet; keep extra networks and the hotspot
> (password given at pairing); firmware from the GitHub release at first
> Install. The user's worry, 26 Oct: owning a whole install line (CI builds,
> a firmware store, pairing, the sheet) is a lot to carry.

Research for the design session with the user (worker browser-setup-research,
26 Oct 2026). Nothing is built. Checked against ESPHome 2026.10.0 and Home
Assistant 2026.10.4 (the current releases), and both projects' main branches of
26 Oct, by reading their source, not only their docs.

**The goal (the user, 26 Oct):** plug the panel into the computer, press
Install in the editor, pick Wi-Fi, and it pairs, like a TRMNL. No ESPHome
add-on, no YAML, no key to paste. Today's YAML path stays, under Advanced,
until the new one has proven itself.

## The short answer

The open question has an answer that didn't exist a few months ago. ESPHome
and Home Assistant now support exactly our case: **one firmware for every
device, with the key set by Home Assistant when it adds the device.**

- ESPHome: `api: encryption:` with no `key:` builds a firmware that starts
  without a key and takes one at its first connection. A `provisioning:`
  window limits when that's possible (it closes after a timeout, and a power
  cycle opens it again). ESPHome 2026.7 and later.
- Home Assistant: when it adds such a device, it makes a key, sends it over an
  encrypted connection (Noise with a well-known all-zeros key: safe from
  anyone listening, not from someone actively in the middle), keeps it per MAC
  address, and uses it from then on. Home Assistant 2026.8 and later, which
  every install of this add-on already runs.
- Updates over Wi-Fi are then secured by that same key, with no password
  (ESPHome 2026.9 and later), as our decision in STATUS wants.

So the key is no longer the hard part. **What the roadmap missed is the
second thing the YAML carries: where the panel fetches its pages, and its
frame key** (`frames_url` with `?token=`). A ready-made firmware can't carry
those either, so every design needs a pairing step with the add-on. The
designs below differ in how that pairing happens and who the panel's Home
Assistant link belongs to.

My recommendation is **design A, "Home Assistant adds it"**: Home Assistant sets the
key, and the add-on pairs the panel through Home Assistant's encrypted link.
Reasons and open questions at the end.

## What a ready-made firmware can't carry

Everything per panel in today's YAML (`firmware/panel.yaml`, filled by
`panel_setup.generate_esphome_yaml`):

| Value | Today | In a ready-made firmware |
|---|---|---|
| ESPHome encryption key | Made by the add-on, kept in `devices.json`, pasted into Home Assistant by hand | Set by Home Assistant when it adds the panel |
| Where to fetch, and the frame key | `frames_url` with `?token=` | Given at pairing, kept in the panel's flash |
| Device and friendly name | The screen's name | One name plus the MAC's last six digits (`name_add_mac_suffix`); the add-on can rename the device in Home Assistant |
| Wi-Fi network | In the YAML | Chosen at install (Improv) or from the hotspot page |
| Other networks (work, a holiday home) | Up to 8 in the YAML | **Lost** unless the firmware learns to keep extra networks it's given at pairing (custom code; ESPHome stores one) |
| Its own Wi-Fi when lost, and its password | Per panel | **A password built into a public firmware is no password.** Either the add-on gives one at pairing (custom code) or there's no hotspot after setup. Matters: ESPHome's captive portal also takes a firmware upload |
| Orientation | Decides which pins are next/previous at build time | Must become a runtime setting the add-on sends |
| Model | The display driver | One build per model: fine |
| First Update every | Initial value | Already overridden by the add-on (`keep_its_timer`) |

Entities and actions stay what they are today, so `panel_link` keeps working.
It should find a panel by MAC address (Home Assistant's device registry has
it) instead of by name: more reliable, and it's what the pairing knows.

## What ESPHome and Home Assistant offer now

| Feature | ESPHome | Home Assistant | What it gives us |
|---|---|---|---|
| Key set when Home Assistant adds the device | 2026.7 (`provisioning:`, esphome#17152); keyless `encryption:` older | 2026.8 (core#176144) | The key without a paste. Home Assistant keeps it; the add-on never sees it |
| Key told to the ESPHome add-on | – | 2026.8 | If the person later adopts the panel in the ESPHome add-on, it gets the same key instead of locking Home Assistant out |
| Device dials Home Assistant (`outgoing_connection`) | 2026.10 (esphome#18919) | 2026.10 (core#180961) | Panels on another subnet, and woken panels reach Home Assistant at once. **Not away from home**: raw TCP to port 6054, an IP address only, and only for a device Home Assistant has added before |
| Setup wizard shown when added (`api: wizard:`) | 2026.10 (esphome#19966) | 2026.11 (beta now) | Nice to have: Home Assistant's own add dialog could show the panel's settings. Not needed |
| Update pulled by the device (`update: http_request`, `ota: http_request`) | Since 2024 | Shows as an update entity | The panel can update itself from the add-on. Checks an MD5 only, no signature |
| Improv Wi-Fi over USB (`improv_serial`) and Bluetooth (`improv_ble`) | Long-standing | Improv over Bluetooth hands over to ESPHome's add flow | Picking Wi-Fi in the same sheet as Install |

## Flashing from the browser

- **Web Serial** (the browser talks to the USB cable) works in Chrome and Edge 89+,
  Opera, **Firefox 151+** and Chrome on Android 156 (a phone with a USB-C
  cable). **Not in Safari, on Mac or iPhone**, and WebKit is against adding
  it. Firefox on Android, Samsung Internet: no.
- **Secure pages only.** Web Serial exists only on HTTPS (or localhost).
  Many people open Home Assistant as `http://homeassistant.local:8123`, and
  there the Install button can't work. ESPHome's own add-on has the same limit
  and sends people to ESPHome Web. This is the biggest practical gap.
- **Inside Home Assistant's sidebar.** The editor runs in Home Assistant's
  add-on frame, which gives it no `allow=` attribute (frontend
  `ha-panel-app.ts`). It's on the same address as Home Assistant, and Web
  Serial is allowed by default on the same address, so it should work (the
  ESPHome add-on does browser installs from the same frame). **To try on
  hardware.**
- **The tools.** ESP Web Tools (Apache 2.0) is ESPHome's install button: a
  manifest per chip, a full erase on a new install, then Improv's Wi-Fi
  picker. Its dialog has Google's Material look, unlike the editor. Under it
  are esptool-js (flashing) and Improv's serial SDK, which we could drive from
  our own sheet in the editor's style. Either way it's **bundled into the
  add-on**, never loaded from unpkg (privacy).
- **Where Web Serial can't run**, the options are:
  1. *Open the editor through Home Assistant's secure address*, when it has
     one (its external URL, or Home Assistant Cloud). The editor can say so
     and link there.
  2. *Plug the panel into Home Assistant itself.* The add-on flashes it
     over its own USB (`uart: true` in the add-on's config, esptool in the
     add-on), like ESPHome's "Plug into the computer running ESPHome". Works
     from Safari and phones. Needs the Home Assistant box within reach of a
     cable, and USB passed through when Home Assistant runs in a virtual
     machine (the user's does).
  3. *Under Advanced:* download the firmware and use ESPHome Web
     (ESPHome's own page, which flashes from the browser without uploading
     the file anywhere) or esptool.
- **A phone can't do the first install** (unless it's Android with Chrome and
  a cable). After that, Wi-Fi changes are the phone's job: the panel's
  hotspot page, or Improv over Bluetooth through Home Assistant.

## Hosting the ready-made firmware

- **Built by GitHub Actions** for each release tag and each model the editor
  offers (5.79", 4.2", 2.9" today), with the ESPHome version pinned. Assets on
  the GitHub release: the parts ESP Web Tools needs (bootloader, partitions,
  app) and the app alone for updates, with a manifest and hashes. GitHub is
  where the add-on itself comes from, so no new party; no server of ours.
- **Served by the add-on.** It downloads its own version's assets from that
  release the first time someone presses Install (the person asked), checks
  them against the release's manifest, keeps them in `/data`, and serves them
  to the editor and to panels. Bundling them into the add-on's build instead
  ties every add-on build to the release's CI having finished first.
- ESPHome builds aren't reproducible byte for byte (they carry their build
  time), so the add-on's source can't pin the hashes of assets built after the
  tag. Trust is the release on GitHub over HTTPS, the same as the add-on's
  code. A release that touches the firmware has to wait for the build before
  it's announced.
- About 1.5 to 2 MB per model (unmeasured).

## The designs

### A. Home Assistant adds it (recommended)

ESPHome's own route for products, plus one action to pair.

**Setting up a panel**
1. In the editor: Add a screen, CrowPanel, the model. Press Install.
2. Plug the panel in with USB-C. The browser asks which port; the add-on's
   firmware for that model goes on (about a minute).
3. In the same sheet: the panel lists the Wi-Fi networks it sees; pick one,
   type its password.
4. The panel joins. Home Assistant finds it on the network; the editor sees
   that discovery for the MAC it just flashed and adds it to Home Assistant
   for the person (they pressed Install), or shows "Add it in Home
   Assistant" if they'd rather confirm there (a question for the user).
   Home Assistant sets its key.
5. The add-on finds the new ESPHome device by MAC and calls its pairing
   action with the address to fetch from and a one-time code. The panel
   trades the code for its frame key at the add-on and shows its first page.
6. Unplug, put it where it goes.

**Needs:** Home Assistant 2026.8 or newer (set as the add-on's minimum; no
install runs anything older); the ESPHome integration that's built into Home Assistant; no
ESPHome add-on. The firmware is built with ESPHome 2026.10 or newer (in CI, not
by the person).

**Security**
- Home Assistant makes and keeps the key; the add-on never holds it. That's
  better than today, where `devices.json` keeps every panel's key.
- The key travels encrypted. During the window, another program on the
  network could set a key first; Home Assistant then can't connect, the
  editor says so, and a reinstall over USB starts again. The window is short
  (proposal: 15 minutes after power-on) and only opens while the panel has no
  key.
- The pairing action carries a one-time code, not the frame key: Home
  Assistant's database records action data by default (`call_service`
  events), and a key there would outlive the code.
- The frame key then crosses the home network the way it does today, in every
  fetch.
- Updates over Wi-Fi: the add-on calls an update action through Home Assistant
  with the image's address and MD5; the panel downloads it from the add-on and
  checks it. The MD5 comes over the encrypted link, so a stranger on the network
  can't swap the image (MD5 is broken for collisions, not for matching an image
  someone else made). A SHA-256 check in our own component would be a small,
  stronger upgrade.

**What breaks or stays**
- Frames, buttons, sleeping, Update every: as today.
- Entities and actions: as today, the same names, found by MAC.
- Other networks and a per-panel hotspot password need firmware work (above).

**Away from home, asleep, TRMNL, privacy**
- Away: frames over HTTPS through Home Assistant's address, as today. Pairing,
  actions and updates need the panel at home, as today. `outgoing_connection`
  doesn't help through a tunnel.
- Asleep: a new panel stays awake until it's paired (only an answer from the
  add-on puts it to sleep). Updates use the existing "stay awake at the next
  update". With `outgoing_connection`, a woken panel reports to Home Assistant
  at once.
- TRMNL: unchanged.
- Privacy: nothing new leaves the house. The firmware comes from the
  project's GitHub release when the person presses Install.

**Size:** large, as the roadmap says. The ready-made firmware (keyless API,
window, Improv, pairing action and stored settings, orientation at runtime,
hotspot password and extra networks): medium to large. The CI build: small to
medium. The add-on's firmware store and pairing (by MAC, one-time code,
adding the device to Home Assistant): medium. The editor's install sheet with
Web Serial, Wi-Fi, progress and every error: medium. Updates through the
action: small to medium.

**Risks:** frames wait on Home Assistant adding the panel; adding it for the
person drives Home Assistant's discovery flow (the same API Home Assistant's
own pages use, but step names could change; the fallback is the person's
click); networks where Home Assistant can't find devices (no multicast,
separate subnets) need the device added by address; plain-HTTP Home
Assistant needs one of the fallbacks above.

### B. Paired like a TRMNL

The add-on is the panel's only partner: no ESPHome connection to Home
Assistant at all.

**Setting up a panel**
1–3. As in A: Install, plug in, pick Wi-Fi.
4. Over the same cable, the editor gives the panel the add-on's address and a
   one-time code (our own serial command, since Improv carries only Wi-Fi and
   names). A panel installed some other way takes them from its hotspot page
   instead.
5. The panel pairs with the add-on (`kinds/trmnl.py`'s window and `rekey`,
   shared by both kinds) and shows its first page.

**Needs:** nothing from Home Assistant's ESPHome integration. The companion
integration (`companion/epaper_panel/`) grows from a pass-through into the
panel's Home Assistant device: its entities and actions, for TRMNLs too. MQTT
stays optional. Actions reach an always-on panel through a request the panel
holds open to the add-on.

**Security:** the add-on holds every key. Updates come over plain HTTP at home
with no encrypted link to vouch for them, so the images must be signed by the
project (a release key in GitHub's secrets, the public half in the firmware,
checked before the new firmware is switched on): a key the maintainer has to
guard and be able to replace.

**What breaks or stays:** the panel is no longer an ESPHome device in Home
Assistant, so automations would use the companion's actions instead of
`esphome.*` ones; `panel_link` is replaced.

**Away, asleep, TRMNL, privacy:** the one design where Home Assistant can wake
an always-on panel **away from home** (the held-open request goes through
Home Assistant's address). Sleeping panels as today. TRMNL gains a Home
Assistant device through the companion. Privacy as A.

**Size:** the largest. A custom integration that has to keep up with Home
Assistant's changes, a push channel, signed updates, and pairing over serial
and the hotspot page.

### C. Paired over the cable, added by Home Assistant

A, except that the add-on's address and the one-time code go over the USB
cable at install (as in B), so pages show even if the panel is never added
to Home Assistant. Home Assistant still sets the key, and actions, entities
and updates work as in A.

**Gains over A:** pages don't wait on Home Assistant, and the pairing is tied to the
very panel on the cable. **Costs:** a second way in for panels not installed from the
editor (plugged into Home Assistant, ESPHome Web), so two
pairing routes to keep in step, against the "one source of truth" rule. Size
between A and B.

## The panel set up today

The add-on is ten days old, and the only panel set up through YAML is the
user's own, so nothing needs a migration feature. That panel keeps working on
its YAML, which stays under Advanced. To move it to the new setup, install the
ready-made firmware over USB and set it up like a new panel.

## Recommendation

**A.** It's ESPHome's own route for ready-made devices (built for the
European rule EN 18031 against default passwords), so ESPHome and Home
Assistant maintain the hard parts: the key, its safe handover, updates
secured by it. Whatever installed the
firmware (the editor, Home Assistant's USB, ESPHome Web), the pairing is the
same single path through Home Assistant. It keeps today's entities, actions and
`panel_link`, and Home Assistant holds the key instead of the add-on. B's real
gain (waking a panel away from home) is a feature for later, not a reason
to build our own Home Assistant integration now. C is worth it only if pages
must show before the panel is added to Home Assistant.

Built in this order, each step useful alone: every model built by CI and served
by the add-on (also lets Advanced users install without ESPHome); the
ready-made firmware; the install sheet; pairing through Home Assistant;
updates through the action.

## Questions only the user can answer

1. **A, B or C?**
2. **When Home Assistant finds the panel, may the add-on add it for you**, since
   you pressed Install? Or should you confirm in Home Assistant's own card?
3. **Home Assistant on plain HTTP (no Install button):** link to its secure
   address when there is one, flash through Home Assistant's own USB, or only
   download and ESPHome Web under Advanced? (They can stack.)
4. **The install sheet:** our own, in the editor's style, or ESP Web Tools'
   ready-made dialog (faster to build, Material look)?
5. **Other networks and the hotspot when lost:** keep both for new panels
   (more firmware code: extra networks and a hotspot password given at
   pairing), or drop the hotspot after setup and the extra networks?
6. **Firmware files:** downloaded from the GitHub release at the first
   Install (recommended), or built into the add-on?

## Not confirmed

- Web Serial inside Home Assistant's add-on frame: reasoned from the frontend
  source and Permissions Policy defaults, not tried.
- Improv over the CrowPanel's USB-serial chip with our logger settings: should
  work, not tried.
- The browser list comes from caniuse, not tried (Firefox 151+, Chrome on
  Android).
- That Home Assistant's database keeps `call_service` events by default: read
  from the source (the event carries the action's data, and the recorder
  excludes no event types by default), not checked in a real database.
- The setup wizard ships in Home Assistant 2026.11, in beta today.
- Firmware sizes per model: estimated.
- Whether ESPHome's Wi-Fi can be given extra networks at runtime without
  patching it: not checked.

## Sources

- ESPHome API docs (encryption key optional, `outgoing_connection`, `wizard`):
  https://esphome.io/components/api/
- ESPHome provisioning window: https://esphome.io/components/provisioning/ ;
  esphome/esphome#17152 (merged 8 Jul 2026, in 2026.7.0)
- Outgoing connections: esphome/esphome#18919 (in 2026.10.0);
  home-assistant/core#180961 (in 2026.10.0)
- Device wizard: esphome/esphome#19966 (in 2026.10.0); Home Assistant 2026.11
  per the ESPHome docs
- Key over an encrypted zero-key connection: home-assistant/core#176144
  (in 2026.8.0); source `homeassistant/components/esphome/manager.py`
  (`_handle_dynamic_encryption_key`, `_async_provision_key_over_noise`,
  dashboard key sync), `encryption_key_storage.py` (keys per MAC)
- ESPHome source: `components/api/api_connection.cpp` (set-key request,
  plain-text set deprecated until 2027.2.0), `api_server.cpp` (saved key),
  `components/esphome/ota/__init__.py` (updates secured by the provisioned key, 2026.9.0 on),
  `components/http_request/ota/__init__.py` (MD5 only)
- Releases checked: ESPHome 2026.6.0 to 2026.10.0, Home Assistant 2025.6.0 to
  2026.10.4 (GitHub tags, 26 Oct 2026)
- Home Assistant frontend, add-on frame: `src/panels/app/ha-panel-app.ts`
- Web Serial support: https://caniuse.com/web-serial
- ESP Web Tools: https://esphome.github.io/esp-web-tools/
- Improv serial: https://www.improv-wifi.com/serial/
- ESPHome update over HTTP: https://esphome.io/components/update/http_request/
