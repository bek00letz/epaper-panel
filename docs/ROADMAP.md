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

## 0.13 (released 20 Oct): prove it and make it solid

| Item | You get | Size | Firmware | Depends on |
|---|---|---|---|---|
| break-it's fixes (#1, #2, #6, #7, #8) | Low Power Mode sleeps after a press and through Home Assistant's address; tighter wrong-key slowdown | done | no | merging the `break-it` branch |
| Every offered size builds (break-it #3) | The 4.2" and 2.9" get firmware that compiles, marked "builds, not tried". The 7.5" and 10.2" are hidden: Elecrow doesn't make them. A test builds every size the editor offers | medium | yes | which 4.2" controller ships, and the other boards' SPI pins, from Elecrow's demo source |
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

## The New page sheet and its presets (agreed with the user 21 Oct; when it lands is the user's call)

Mockup: https://claude.ai/artifact/STc9a9gWKX7fgX511pmdE6 (private).

| Item | You get | Size | Firmware | Depends on |
|---|---|---|---|---|
| Shelves | One shelf per group that slides sideways; the group's count beside its name ("Energy (5)"); arrows at the edges on hover, only towards more presets; the edge fades while there's more, under the arrow too. Phones swipe and keep the fade. Blank page stays pinned in the sheet's footer as a tinted "+ Blank page" button; your own presets get a shelf when you have some | small–medium | no | – |
| One preset per thing a page shows | A preset's looks, leagues or series are picked next, not separate cards: Planes overhead (Nearest plane, Radar, Both), Calendar (Month, Month and agenda), New to watch (three styles), Match (league), Race weekend (series) | small | no | – |
| Groups | Your day (with the To-do list from the alerts-todo branch, in three styles the user chose: By urgency (Overdue row inverted, Today row outlined, the rest plain), Inverted when due (Overdue and Today rows inverted, the rest outlined), Outlined (every row in a pill); the label sits inside its row), Home, Energy, Outside, Sports, Watch and listen. Planes leave the sports shelf for Outside, with Weather and a new Sunrise and sunset (two styles: the next one large with the other beside it, swapping at sunrise and sunset; or both alike) | small | no | – |
| Clearer names | "Door or pet" becomes Status (any sensor's state in your words, and since when); "On now" becomes Dynamic status (the user's name: up to eight things, each shown only while in a state you choose); "Formula 1" becomes Race weekend; "Match" becomes Scores (NBA and MLB play games, not matches) | small | no | – |
| Sensible sensor first | Energy presets open with the Energy dashboard's sensor picked and labelled; temperature presets list temperature sensors first; thumbnails use example values, never "--" | small | no | – |
| More energy presets | Solar this month (long-term statistics), Grid now (buying or selling), Energy cost (today and this month, from the Energy dashboard's prices, in Home Assistant's currency) | medium | no | – |
| A preset sets up what it needs, in place (a rule for every preset, the user's call: framework, not patch) | A preset that needs a data source asks for it in its own next step: New to watch asks for the Jellyfin address and API key (saying where to find the key), connects, then asks whose unwatched to show; Solar this month sets up its statistic the same way. It saves the same data source Settings > Data sources shows (one store, no second path), and a second Jellyfin page reuses it. With JellyHA installed, the address is filled in from it; the key is still typed, since JellyHA doesn't expose it | small-medium | no | - |
| Watch and listen through Home Assistant | Now playing (any media player: Spotify, Sonos, Apple TV, Plex, Jellyfin through JellyHA) and On TV this week (any calendar of shows: Sonarr, Trakt through its add-on), beside New to watch. Jellyfin becomes one source among several. JellyHA (checked 21 Oct) gets no Jellyfin-specific path: it offers one latest episode, one latest movie and library-wide counts, not the lists New to watch draws, so the add-on keeps its own Jellyfin source; JellyHA's players already work in Now playing and its sensors in any sensor preset | medium | no | - |

## Alerts beyond the screen (agreed 22 Oct)

"Also notify my phone…" on an alert or a when-page creates just the Home
Assistant entity that condition needs (nothing by default) and opens a shipped
blueprint, prefilled, so the notification is an ordinary automation. The add-on
never sends notifications itself.

## Outside services, visible in the editor (agreed 22 Oct; all of it in 0.21, worker services-021)

Today a failing outside service (icons, racing calendars, scores) shows only in
the add-on's log and Home Assistant's problem sensors; the editor never shows
it. The user chose: the status card lists any service whose problem sensor is
on. They also want the sources visible and, behind an "only touch this if you
know what you're doing" step, editable. Proposal to design with them:
- Settings › Services lists every service: what uses it, its last answer, the
  error, Try again. The status card shows only the failing ones. These two can
  ship first, on their own.
- Advanced: "Use another address" per service, for a mirror in the same
  format. The add-on's own reader checks it before saving and refuses it with
  the reason otherwise.
- Show the add-on's own fields per widget (for racing: series, race, session,
  start, result), not the raw outside formats, and let a user's own data
  source fill them. That makes swapping a source real without documenting
  outside formats that change without warning.

The user's design choices (22 Oct): the status card's dot stays about the
panel, failing services get their own section; addresses change behind an
Advanced switch in Settings › Services that turns itself off each time
Settings opens; a source fills a widget either by answering in the add-on's
own shape or through a Home Assistant entity's attributes. Mapping each field
to a path in a source's own format may come later on top.

## Later

| Item | You get | Size | Firmware | Depends on |
|---|---|---|---|---|
| Grey for screens that have it | Real grey on a TRMNL X (16 levels) or OG, softer charts, larger text with a grey tone | large | no (TRMNL), n/a (CrowPanel is 1-bit) | a TRMNL to try; the "no grey" rule becomes per screen |
| Screens you already own | A Kindle, Boox or old tablet as a screen, through a page it opens in its browser | medium | no | the user's Boox Go 6 to try; the lessons in Paperhub |
| Battery reading on a CrowPanel | Battery sensors like a TRMNL's | small | yes | a board with a resistor divider soldered on |
| Colour e-paper | Red or yellow accents on colour panels | large | depends | a colour panel |
| 1.0 | Tested on what it claims, set up in minutes without YAML, in more than one language | – | – | the above |
| Act from the panel (noted, not convinced) | A page that asks ("Bins out tonight?") and a press that answers, recorded in Home Assistant. The user finds the panel's buttons cumbersome and drives it with a scroll remote; it belongs with touch screens | medium | yes | a touch screen kind, if ever |
| A first screen made for you (noted, not convinced) | Pages built from what Home Assistant knows for certain on first run. Picking entities for someone is a game of chance (calendars they don't use, an inverter's 185 sensors); the starter page and its guide stay the way in | medium | no | a reliable way to know what matters to someone |
| A source in its own form (option B of 0.21's services, noted 22 Oct) | Pick, per field, where in a data source's own JSON a widget's field is (like "Value at"), with a live preview, so an API in another form can fill a Racing, Scores or Flights page without reshaping it first. 0.21 reads the add-on's own form from a source or a sensor's attributes; this would sit on top as an adapter (`shapes.read`) | medium | no | – |
| A guide behind the starter page's QR code | A current guide with worked examples, at an address that won't move. Today the QR code opens the README's three-step "Your first page" | small–medium | no | – |

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
