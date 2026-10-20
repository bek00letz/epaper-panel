# Roadmap

From 0.12.0 on. Drafted 20 Oct 2026 with the user; the coordinator keeps it
current next to [STATUS.md](STATUS.md), which holds what's released and in
flight. This file says where we're going and why; STATUS says where we are.

## Where it stands

**What it is.** A Home Assistant add-on that turns what you care about into
calm pages for e-ink screens, designed in an editor whose canvas is drawn by
the same engine as the screen. Pages appear only when they matter, and an
alert can take over.

**Who it's for.** Home Assistant owners who want a screen they glance at,
not a dashboard they read: on a desk, by the bed, on a wall, at work. They
own a CrowPanel or a TRMNL (or will), and don't want an account anywhere.

**Strongest.** Legibility comes first (the editor knows the viewing distance
and says what reads from there). One engine for canvas and screen. Smart
pages with no keys or accounts (scores, racing, planes, Jellyfin). Private by
default. A thin client, so a button press redraws in under a second.

**Weakest.** Four of the five sizes the editor offers can't build their
firmware today (found by break-it), and most of the rest hasn't met real
hardware: Low Power Mode, TRMNL, away from home, a second panel. Setting up
a panel takes the ESPHome add-on, a YAML paste, a USB cable and a key paste.
The screen's words are English only. Two days of fast, parallel building
left a lot of surface; the next release should make it solid, not wider.

**Where it can win.** TRMNL's value is its software, but that software is a
cloud service. The self-hosted servers for TRMNL (Terminus, LaraPaper) have
no visual editor. Ours is the best editor for e-ink, at home, with no
account. That's the position to grow from.

## Next release (0.13): prove it and make it solid

| Item | You get | Size | Firmware | Depends on |
|---|---|---|---|---|
| break-it's fixes (#1, #2, #6, #7, #8) | Low Power Mode sleeps after a press and through Home Assistant's address; tighter wrong-key slowdown | done | no | merging the `break-it` branch |
| Every offered size builds (break-it #3) | The 4.2", 2.9" and 7.5" get firmware that compiles, marked "builds, not tried". A size that still can't build (likely the 10.2") is hidden until someone has one. A test builds every size the editor offers | medium | yes | which 4.2" controller ships, and the other boards' SPI pins, from Elecrow's demo source |
| Low Power Mode keeps sleeping when the add-on is down (break-it #4) | An update or restart no longer drains a panel away from home; only a 200 or 304 without the sleep header means "stay connected" | small | yes | – |
| No firmware ESPHome refuses (break-it #5) | No network plus its own Wi-Fi gives a setup-only Wi-Fi; no network and no own Wi-Fi is caught in the editor, as are short Wi-Fi passwords | small | yes (generated YAML) | – |
| break-it's smaller items (#9, #10) | The panel's own refresh timer is off in Low Power Mode; the right wake time on the night the clocks change; a stalled MQTT broker can't hold up a render; a note on going back to 0.11 with a TRMNL saved | small | yes (the timer) | – |
| Update every / Rotate every | Two timers per screen replace the Low Power Mode switch and its wake interval. 1 minute is always on; 2 minutes or more sleeps between updates, and rotation is every Nth update. Always on by default, and first-time users see plainly that there's a choice | medium | yes | – |
| No flash after a wake (TRMNL's way) | The display stays powered in its memory-keeping sleep, so the first change after a wake is a partial refresh; a full one every 8th change | medium | yes | confirmed and measured on the user's 5.79" |
| Low Power Mode on the real 5.79" | Real numbers in the README, not estimates; buttons that wake it reliably; how long the first press takes | medium (mostly measuring) | likely small fixes | the user's panel and a USB power meter (ordered). Through USB the reading is an upper bound (the USB-serial chip stays powered, and the meter can't read below about 1 mA); a LiPo reading follows when the user has one |
| The 5.79" away from home | HTTPS through the tunnel and a second Wi-Fi network, tried | small | maybe | the user's panel and tunnel |
| Audit #9: setup address | A panel set up through a tunnel is never told to fetch over plain HTTP | small | no | – |
| Audit #14: footer positions checked | A broken or forged frame file can't freeze the panel | small | yes | – |
| Remove the classic editor | One editor | small | no | decided 20 Oct |

Firmware changes ride together, so the panel is installed again once per
release, not once per fix. Every size building is also the ground the
browser setup stands on: a ready-made firmware per model has to build.

## Next month: easier to start, nicer to live with

| Item | You get | Size | Firmware | Depends on |
|---|---|---|---|---|
| Setup from the browser | Plug the panel into the computer, press Install in the editor, pick Wi-Fi, and it pairs like a TRMNL. No ESPHome add-on, no YAML. Today's YAML path stays, under Advanced, until this has proven itself | large | yes | every offered size building (0.13); a ready-made firmware built for each release and model; a design pass first (see Open questions) |
| The screen speaks your language | Dates, weekdays, "updated", the sleep screen and presets in Home Assistant's language | medium | no | translators for languages beyond the first few |
| Share a page | Export a page or a screen's pages as a file; importing asks for your own sensors, like New page does | medium | no | – |
| To-do lists | The shopping list or any Home Assistant to-do list as a page, shown only when it has items | small | no | – |
| "How it went" report | One button copies a report (kind, size, firmware, errors; no names, addresses or entities) for a GitHub issue | small | no | – |
| TRMNL-compatible screens | Seeed's reTerminal and other screens running TRMNL's firmware, listed and sized properly. The next kind of screen we grow toward | small | no | someone with one to try it |

## Later

| Item | You get | Size | Firmware | Depends on |
|---|---|---|---|---|
| Grey for screens that have it | Real grey on a TRMNL X (16 levels) or OG, softer charts, larger text with a grey tone | large | no (TRMNL), n/a (CrowPanel is 1-bit) | a TRMNL to try; the "no grey" rule becomes per screen |
| Screens you already own | A Kindle, Boox or old tablet as a screen, through a page it opens in its browser | medium | no | the user's Boox Go 6 to try; the lessons in Paperhub |
| Battery reading on a CrowPanel | Battery sensors like a TRMNL's | small | yes | a board with a resistor divider soldered on |
| Colour e-paper | Red or yellow accents on colour panels | large | depends | a colour panel |
| 1.0 | Tested on what it claims, set up in minutes without YAML, in more than one language | – | – | the above |

## Decided with the user (20 Oct)

- **0.13 only proves and hardens.** Nothing new until what shipped has met
  real hardware. Low Power Mode is reshaped in 0.13 (two timers, no flash
  after a wake) so the measuring is of the design that stays, and the panel
  is installed once.
- **Setup moves to the browser**: a ready-made firmware, installed from the
  editor, paired like a TRMNL. The YAML path stays as the way back.
- **Sizes: fix what builds, hide the rest.** A size the firmware can't
  build isn't offered; README's table says "builds, not tried" instead of
  "should work".
- **Screens: TRMNL-compatible devices first.** Kindle, Boox and tablets, and
  grey on a TRMNL X, come later.
- **Low Power Mode is measured through USB first** (meter ordered, no LiPo
  yet), and the README says that the number is an upper bound.

## Open questions

- **Browser setup and Home Assistant.** A ready-made firmware can't carry a
  per-panel encryption key. How does the panel still get its Home Assistant
  actions and entities: a key set by Home Assistant when it adopts the
  panel (to check against current ESPHome), or the same pairing a TRMNL
  uses, with Home Assistant reaching it through the add-on? To settle in the
  design pass, with the user, before any code.
- **Which languages first** for the screen's words, beyond English.

## Deliberately not building

- **Screenshots of Home Assistant dashboards.** Grey dithers badly, it needs
  a browser on the Home Assistant box, and it breaks on frontend updates.
  Our pages are designed for e-ink instead.
- **Running TRMNL's 1,000+ recipes.** They're web pages drawn by a browser:
  a second engine, so the canvas could disagree with the screen.
- **Anything with an account or a server of ours.** Sharing is a file; a
  gallery, if ever, is plain files on GitHub.
- **Dense dashboards on small screens.** One fact per glance is the product.
- **Photos.** Dithered pictures fight hard edges; revisit only with grey.
- **Touch and input on e-readers** (Paperhub's idea). A different product;
  the browser screen above shows pages, it doesn't take input.
