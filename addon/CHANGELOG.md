# Changelog

## Unreleased

- **Fixed:** a Batteries page showed a placeholder ("Sample Zone") instead of
  your batteries since 0.20.2: it asked for the power grid's numbers by
  mistake. It shows every battery its rule picks again. A test now fails
  if any part of the add-on gives two things the same name.
- **A battery that stops answering shows.** On a Low batteries page, a
  battery that has been unavailable for 12 hours now shows after the low
  ones, as "No answer since Tue 14:02", and the page shows for it. When all
  of one integration's batteries stop answering together, it's one line,
  such as "Salus: 3 not answering". Change the wait, or turn it off with
  Never, in the page's Batteries settings. A Home Assistant restart starts
  the wait again, so it can show later than it should, never early.
- **A page's widget and your own condition count together.** On a page
  set to "Only when" or "As an alert", the page's Shows section now has two
  parts: "Something on it to show", a switch for its widget (a low battery,
  a plane near, a game day, something to do), and "And when", your own
  condition. Both must hold, so a page can show for 2 minutes after you get
  home, only while a battery is low. The whole thing is said in one
  sentence. A widget's own "Only show while…" switch now points to the
  page's Shows section.
- **Changed:** before, a page went by either its widget or your own
  condition, and silently left the other out. Your pages show as they did,
  except where both were set: a page with your own condition and a widget
  that can say it has something to show (Batteries, Flights, Scores, Racing,
  To-do, Notifications, Updates, a Devices grid) now waits for both. Turn
  "Something on it to show" off to go by your condition alone.

## 0.21.0
Add-on only; no firmware change, so nothing to reinstall on the panel
and no Home Assistant restart. Update the add-on.

- **Outside services you can see.** When a service the add-on asks isn't
  answering (ESPN, a racing calendar, Flightradar24, Iconify…), the status
  card says so under "Outside services": which one, since when and why, in
  plain words. Pages that use it keep what they last had. A line opens
  Settings › Services at it.

- **Settings › Services.** Every service the add-on asks, in one place:
  outside ones, Home Assistant's own (the Energy dashboard, its
  notifications, updates and icons) and your data sources. Each says which
  pages use it, when it last answered, what went wrong if it didn't, and
  has Try again, which asks it now. Nothing is asked unless a page needs it
  or you press Try again.

- **Use another address for a service.** Under Settings › Services ›
  Advanced, "Change service addresses" lets you point a service at a mirror
  that answers in the same form. Only touch it if you know what you're
  doing: the add-on reads a test answer from the new address with its own
  reader first, and refuses it with the reason if it can't read it. "Use the
  original address" takes you back, with an Undo.

- **Your own data for racing, scores and flights.** Each of these widgets
  now has "Its data" in the inspector: where it reads from and its fields,
  in the add-on's own form (for racing: series, race, place, session,
  start, result), with what they hold now. A data source with "Any JSON
  address" can give a kind of page's data in that form ("Gives" in Settings
  › Data sources, which shows the form with an example), and a page can
  read it in place of ESPN, the racing calendars or the flight feeds. Test
  says whether it reads, or what's wrong. A Home Assistant sensor whose
  attributes carry the same form can do it too: choose "A Home Assistant
  sensor" in "Its data". Pages you have keep reading the add-on's services.

## 0.20.2
Add-on only; no firmware change, so nothing to reinstall on the panel
and no Home Assistant restart. Update the add-on.

- **Notify a group, not only a phone.** "Also notify my phone…" now lists
  notifiers that aren't entities too, such as a group written in YAML
  (notify.family), by their name, and the automation it makes sends to
  them. On Home Assistant before 2026.5, where the app's phones aren't
  notify entities yet, phones are listed this way too. The add-on's
  blueprint in Home Assistant updates itself the next time you set one up.

- **"Changed in the last N minutes" can't quietly change meaning.** It's
  now saved as what it is, not as a Home Assistant template, so the add-on
  always answers it from the sensor's history (a restart is never a
  change). If you turn one into a custom condition and change it, the
  editor says that Home Assistant answers it from then on, and that to it a
  restart counts as a change. Conditions saved before keep working.

- **A value's unit follows its sensor.** A number or gauge shows its
  sensor's unit as Home Assistant has it now, so switching Home Assistant
  to °F, or giving a sensor a unit of its own, changes the page too. Pages
  you already have follow wherever the unit after a value was the
  sensor's own; one you typed stays yours. In the inspector, "Its unit"
  says what it is now; switch it off to write your own.

- **Batteries follows a rule, not the batteries you had that day.** A
  Batteries page shows every battery of its kind (the ones you swap, or the
  ones you charge) that's past its number, minus the ones you untick. A
  door sensor added next month shows on its own, and "battery low" sensors
  (common on Zigbee and Z-Wave devices) count too, as low whenever they're
  on. Batteries pages you already have keep showing what they show today,
  then follow the rule; nothing to do.

- **Planes overhead pages say "only when" the same way as every other
  count**, so a page you set to show while a plane is near reads like one
  set by Notifications or a to-do list. Nothing changes in when it shows.

- **Fixed:** a TRMNL could be told to sleep less than a minute after a
  button press, which its firmware doesn't keep. Each kind of device now
  says its own shortest sleep (a TRMNL's is a minute, a CrowPanel's 30
  seconds).

- **Fixed:** a racing calendar whose format changed was ignored without a
  word, and one that said it had no races turned its problem sensor on and
  off every ten minutes. Both now keep the problem sensor on until the
  calendar reads again, and the page keeps the last season it read.

## 0.20.1
Add-on only; no firmware change. **Restart Home Assistant once** after
updating, so it loads the updated e-Paper Panel integration (it carries the
clock fix for panels that reach home through Home Assistant's address).


- **Fixed:** deleting a page that notified your phone could withdraw its
  sensor while an automation you had made by hand in the last ten minutes
  still used it. The add-on now asks Home Assistant again just before it
  withdraws one.
- **Fixed:** an icon file with an absurdly wide line was accepted, then
  couldn't be drawn, and the page using it was left out. Such a file is now
  left out of the set, like any other file no icon is like.
- **Fixed:** a panel that fetches through Home Assistant's address (Reaching
  home) never got its clock lined up (0.18): the e-Paper Panel integration
  dropped the add-on's "fetch next at" hint on the way. Restart Home
  Assistant once after updating the add-on so it loads the new integration.
- **Fixed:** adding an Iconify icon set made a "Racing calendar" problem
  sensor in Home Assistant, and a failed download said the racing calendar
  was failing. Iconify is now a service of its own, with its own problem
  sensor once you use it.
- **Fixed:** two times of day ignored the 12/24-hour setting: a Countdown to
  a timed event ("Thursday 24 December, 18:00") and the sunrise or sunset line
  on the first page a new device shows. That line is now the Sunrise and
  sunset widget, which also works before Home Assistant answers. A test now
  fails on any time of day that skips the setting.
- **Fixed:** when copying Home Assistant's own icons failed, the add-on
  downloaded them all again (about 2.7 MB) every five minutes. It now waits
  longer after each failure, up to four hours, and tries at once when Home
  Assistant updates.

## 0.20.0
Add-on only; no firmware change, so nothing to reinstall on the panel.

In short: your own icons and Iconify sets without the Custom Icons
integration; Home Assistant's notifications, an Updates page and a count
badge; a Batteries preset that shows what needs charging (or is charged);
"Also notify my phone…" for alerts, through a normal Home Assistant
automation; Bin day's wording made plain; no inspector row squeezes its
label.
The details:
- **A badge for any page.** Insert › Widgets › **Badge** puts an icon with
  a number in a solid dot on any page, like an app's icon on a phone: how
  many updates are waiting, notifications, Repairs issues, or all of these
  together (**Counts**, Updates to start with). It's not there at all when
  the number is zero; over 99 it reads 99+. Its size is its box: drag it
  bigger or smaller, and the note under it says how far away its number
  reads, from the distance in **Check legibility from**. On a smaller
  screen it keeps its real size instead of shrinking with the page.
- **Updates waiting, on a page.** New page › Home › **Updates** lists every
  update Home Assistant has waiting with its new version, grouped as Home
  Assistant shows them: Home Assistant itself, add-ons, integrations (HACS)
  and devices. More than fit end with "and 3 more"; a small screen leaves
  out the group's column and a version it can't show whole. The page shows
  only while something's waiting, and a version you skip in Home Assistant
  drops off it.
- **Home Assistant's notifications on a page.** New page › Home ›
  **Notifications** lists the notifications behind Home Assistant's bell,
  newest first, with how long ago each came ("12 min", "2 h", "Yesterday").
  With one or two, what they say shows under them when it fits; more than
  fit end with "and 3 more". The page shows only while there are any, and
  one you dismiss in Home Assistant is gone at the next update. A device that
  sleeps between updates shows the time each came instead, so nothing goes
  stale while it sleeps.
- **What needs you in Home Assistant, counted.** While a page uses them, the
  add-on keeps three counts of its own: `sensor.epaper_notifications` (Home
  Assistant's notifications, the bell), `sensor.epaper_updates` (updates
  waiting; a version you skipped isn't counted) and `sensor.epaper_repairs`
  (open Repairs issues, not the ones you ignored). A page's "Only when" or an
  alert can use them, for example an alert when notifications go from none
  to some. They aren't added to Home Assistant as entities: it has these
  numbers already.
- **Batteries, as a page or an alert.** New page › Batteries shows the
  batteries that need charging, emptiest first, each with its level and
  Home Assistant's battery glyph for it; or, the other way, the ones that
  are charged. Pick which batteries it watches (the ones you swap start
  ticked for Low, the ones you charge for Charged) and the level: 20% to
  start with, and any battery can have its own in the inspector. The page
  shows only while one is past it, with the other pages or as an alert. A
  row each, so names read on every size; what doesn't fit says "and 3 more".
- **Dynamic status can go by a number.** Besides On, Off and Any state,
  Shows each can be Below a number or At least a number, so a heater
  shows while above 25 °C, say. It has a List layout too, a row each. A
  Dynamic status page that shows only while something on it does now says
  so in words under Shows, instead of showing its template.
- **An alert can notify your phone.** On an alert or an "Only when" page,
  **Also notify my phone…** lets you pick your phone (or several), and Home
  Assistant sends a notification when the alert takes over the panel or the
  page starts showing. It's a normal automation in Home Assistant, made from
  a blueprint the add-on installs ("When an e-paper alert fires, notify"):
  change the message, add a title or keep it quiet for a while there, with
  **Edit in Home Assistant** next to the page. Only a page you ask for gets
  a sensor in Home Assistant (`binary_sensor.epaper_alert_<page>` or
  `binary_sensor.epaper_showing_<page>`), and it keeps its ID if you rename
  the page. **Stop notifying**, or deleting the page, offers to delete the
  automation too; a sensor an automation still uses is never removed.
  Needs the Mosquitto broker app. Add-on only, no firmware change.
- **Your own icons and icon sets, without Custom Icons.** A new **Settings ›
  Icons** (also **More icons…** in the icon picker) holds both:
  - **Your own icons:** **Add icons** takes SVG files, or drop them on the
    box. They're kept in `epaper/icons` in Home Assistant's configuration
    folder, and used as `local:name`, as before. Icons in `custom_icons`
    still work, so nothing has to move.
  - **Iconify sets:** **Add a set** lists Iconify's single-color sets with a
    few icons of each, its size and its license. A set is downloaded when you
    add it, only that set, and works offline from then on. **Check for
    updates** downloads only the sets that changed. If a download fails, the
    set says why and offers **Try again**.
  - **Coming from Custom Icons:** the sets you used keep drawing after this
    update and after you uninstall Custom Icons, because the add-on keeps its
    own copy. Its "Download Iconify icons" button breaks other integrations
    (for example, camera video) until Home Assistant restarts, so you no
    longer need it.
- **Fixed: one odd SVG file could stop all your own icons loading.** A file
  with thousands of groups inside groups made copying your icon folder fail
  as a whole; now that one file is left out and the rest load. An icon with
  sizes too large to be real is left out too: it used to leave other icons
  blank in the editor's picker.
- **No row squeezes its label or its control.** In the inspector, Settings
  and New page, a control that doesn't fit beside its label now goes under
  it, full width, with any note kept under the label. "Close to the day" on
  a Bin day read "Close / to / the / day" beside its menu, and "Starts
  showing" squeezed its note; a label too long for two lines takes the row
  too. Segmented controls follow the same rule.
- **Bin day's "Close to the day" is two plain choices.** "Bin day ends: At
  noon, At midnight" (then it counts to the next collection) and "Says:
  Tomorrow, Today, or 1 day, 0 days", in place of one long menu. Numbers
  can now last until midnight too. Bin days you set up before look the
  same.

## 0.19.0
Add-on only; no firmware change, so nothing to reinstall on the panel.

In short: race pages read each series' own calendar first, so Formula E
already shows season 13 (Jeddah, 18 Dec), and between seasons they say so
instead of showing an old race; setting up Scores says when a busy day won't
all fit an always-on panel, and a trimmed page says how many it shows; the
racing calendar no longer reports a failure for next year's file.
The details:

- **Fixed:** the add-on reported the racing calendar as failing every minute
  ("HTTP 404" in its log, and its problem sensor), because next year's F1
  and Formula E calendars aren't published yet. A missing next year is now a
  normal answer; this year's calendar was never affected.
- **A Scores page shows every game of the day,** not just six: your teams
  first, then live, upcoming and finished. On a busy day an always-on panel
  can run out of room; it then keeps the most important games.
- **A device that sleeps draws only what it can show next.** Each minute the
  add-on drew every item of every page for it; now it draws the page it's
  on, the next few, and the first of each page (where a button press goes).
  A busy Scores day costs the add-on a few pictures a minute, not 80.
- **Setting up Scores says when a busy day won't all fit.** On a device that's
  always on, picking a league (in New page, or under League in the
  inspector) shows a line when your leagues' busiest day, with your other
  pages, could have more games than the device holds: "On a busy day your
  leagues can have a lot of scores, and Kitchen can only show about 25 of
  them." Nothing shows when it all fits, or on a device that sleeps between
  updates or a TRMNL, which have no such limit.
- **A page that's cut short says so.** When an always-on device can't hold
  every game, its Scores page's tile says "Showing 14 of 23 games" (or
  matches, in football's word), and its inspector says which come first.
  Planes, Now playing and New to watch say it the same way, in their own
  words. It goes away by itself once everything fits again.
- **Fixed:** between seasons, the race page showed the season's last race as
  if it were still coming (Formula E's London race, in October). Each series
  now reads its own calendar first where it publishes one (Formula E's
  already has next season), then the community calendars, which add exact
  session times once they catch up. A finished race's result stays for a few
  hours, then the page moves on to the next race; NASCAR's no longer waits
  for ESPN to move on. When Formula E's calendar page stops listing its
  season, the add-on's problem sensor says so. Dates read "Fri 23 Oct", like
  the rest of the panel.
- **Fixed:** during a live Formula E session the badge said "runtime.LIVE".
- **New:** the race page between seasons shows the next season and its
  first race ("Jeddah E-Prix", "Season starts Fri 18 Dec") with an Off
  season badge, or "Season over" while no calendar has the next season yet.
  Outside race weekends the page still stays out of the rotation. The card
  before a race now fits on every device size, and names the race when no
  calendar says where it is.

## 0.18.0
**Firmware change:** install the panel again (Settings › Install or update,
then Send to ESPHome and Install in ESPHome) so its clock lines up with the
minute. Until then it keeps working as before.

In short: the clock on the panel is right within seconds (the add-on draws
just after each minute starts and the panel fetches right after); icons come
from your own Home Assistant, including your custom icon sets; condition
suggestions come from the add-on's one list of states.
The details:
- **Icons come from your Home Assistant.** The add-on still ships the whole
  Material Design set, so icons always draw, but when Home Assistant has a
  different version it copies Home Assistant's set across in one go and
  uses it, so a new icon Home Assistant shows can be on your pages too.
  Custom icon sets are copied the same way and appear in the icon picker:
  your own SVGs from Custom Icons (`local:`), its Iconify sets, and sets
  like Custom Brand Icons (`phu:`). The picker searches all of them, with a
  chip per set to narrow it down. Icons are now drawn from their outlines,
  so they're crisp at any size; they keep the size they had.
- **A page's "While" and an alert's "Until" suggest the values a sensor
  really has**: Home Assistant's own for its kind, named as Home Assistant
  names them ("Away" for not_home), then the choices it lists and the states
  it had in the last 10 days, so a sensor like a cat's location offers
  "Indoor Cat" and "Outdoor Cat". Before, only a dozen kinds had any.
Firmware change: reinstall the panel's firmware to get the second half.

- **The add-on draws just after each minute starts.** It used to draw every
  minute counted from when it started, so a clock on a page could be most of
  a minute old before a panel even asked for it. A render that runs long is
  followed by another straight away, never a skipped minute, and the log
  says so.
- **An always-on panel fetches just after the add-on draws** (firmware).
  Its first fetch after a start is still straight away; from then on it
  fetches a couple of seconds into each minute, so the time it shows is
  right within a few seconds, not up to two minutes behind. A button,
  Send, alerts and quiet hours still fetch at once; the next timed fetch
  lines up again. Until its firmware is reinstalled, a panel keeps
  fetching every minute from when it started, as before.
- **Devices that sleep between updates wake just after a minute starts**,
  a CrowPanel and a TRMNL alike, so what they show was drawn that minute.
  A wake is never later than Update every asks; the first one after a
  start or a press may come up to a minute sooner, to line up.

## 0.17.0
Add-on only; no firmware change, so nothing to reinstall on the panel.

In short: any icon can change with a sensor, with its own icon and look
(plain, inverted or outlined) for each state; a text's "From" switches from
any choice to any other; no switcher in the inspector cuts off a choice.
The details:
- **Any icon can change with a sensor.** Select an icon and turn on
  "Changes with a sensor" in its Icon section, pick the sensor, then tap
  the states you want: each comes with Home Assistant's own icon for it,
  from what kind of sensor it is, the choices it lists, or the icons it had
  in the last 10 days (so a cat's "Indoor Cat" brings its cat icon). "Other
  state" adds one it hasn't been yet, and "Anything else" is the icon for
  the rest. Turn it off and the icon stays as it was. An icon Home
  Assistant uses that the panel can't draw isn't offered.
- **Each state has its own look**: plain, inverted (a black tile with the
  icon in white) or outlined, chosen at the top of the icon picker, so
  "Outdoor Cat" can stand out. "Anything else" keeps the icon's own style.
  Inside an inverted group, an inverted state shows white so it still
  stands out. Pages made before keep drawing as they did.
- **A text's "From" goes from any choice to any other.** A template could
  switch to Text or Time but not to Sensor. Now Sensor picks the sensor
  the template reads when there's one (or asks which), and Template starts
  from what it showed, its detail, format and replaced words included.
- **No choice is cut off in a segmented control.** "Template" read "emplat"
  in the inspector; From, Style and "As" now move under their label when
  their choices don't fit beside it, and back when there's room.
- **No error in the browser's console as the editor opens.** The page
  strip asked what isn't sent yet before the pages had loaded.
- **An icon that follows a sensor matches its state whatever the case.**
  "outdoor cat" picks the same icon as "Outdoor Cat", as the Dynamic status
  spots already did.

## 0.16.0
Add-on only; no firmware change, so nothing to reinstall on the panel.

In short: the editor shows what isn't sent yet, page by page, with an undo
for each change; Duplicate and Delete on every page in the strip, which is
larger now; and a page can show for a while after something changes ("PawPaw
went outside"). The add-on's description lists the sizes it offers.
The details:
- **Duplicate and Delete on every page in the strip.** Hover a page (or
  hold it on a touch screen) and its last third shows two buttons:
  Duplicate, and Delete, which asks which you mean, Delete page or Take out
  of rotation, each with an Undo. They replace the "…" menu; right-click a
  page for the full list, Show again included. If you'd rather have them
  side by side across the bottom half of the picture, choose that in
  Settings › Editor; it's kept for each strip size.
- **Holding a page on a phone shows its buttons**, not the iPhone's "Save
  to Photos" menu for its picture (and on Android, not the page menu on
  top of them).
- **Larger page strip sizes**, so those buttons fit: Small, Standard and
  Large are now 188, 248 and 320 px wide (they were 104, 132 and 184). A
  size you'd picked before becomes the new Small.
- **"Not sent yet" no longer shows for pages you didn't change.** The
  add-on and the editor write a page's details in a different order, and
  after a reload that alone counted as a change.
- **The page strip shows what isn't on the panel yet.** A page you've
  changed since you last sent gets an orange outline and a dot by its name,
  and the line under it says what's waiting: "2 changes, not sent", "New,
  not sent", "Moved, not sent". A page you removed stays at the end of the
  strip, greyed, under "Removed, not sent", until you send; click it to put
  it back. A countdown that has passed is now greyed without an outline, so
  an orange outline only ever means "not sent yet".
- **"Not sent yet" says what isn't sent.** Click the pill at the head of
  the page strip: under it, a line for each page with something waiting
  ("Solar today · 2 changes", "Clock · Added", "Bins · Removed", "Cat ·
  Moved in the rotation") and for quiet hours and the other settings sent
  with your pages. Click a line to open that page with what changed
  outlined in orange (dashed where something was removed) until your first
  click; Undo puts just that page back to what the panel has, with an Undo
  of its own.
- **"Changed" conditions.** A page can show for a while after a sensor
  changes ("Pawpaw Location changed to Outdoor Cat in the last 30 minutes"),
  then leave on its own, and an alert can fire each time it changes. Only a
  new value counts: Home Assistant restarting, or a sensor dropping out and
  coming back with the same value, doesn't. No firmware change.
- **A page's condition reads in one row** again ("is" next to its value);
  it had picked up the look of Settings' choice cards.

## 0.15.0
**Firmware change:** install the panel again (Settings › Install or update,
then Send to ESPHome and Install in ESPHome) to see which Wi-Fi network it's
on. Everything else works without reinstalling.

In short: a new New page with presets on shelves, and new ones (Sunrise and
sunset, energy, Now playing, On TV this week, your own weather station, a
world clock, Countdown and Bin day without a calendar, to-do lists); alerts
that end when something happens; "device" everywhere; zoom; 12- or 24-hour
time; a clock that shows the date on a device that sleeps; and many fixes.
The details:

- **Connection says which Wi-Fi network the panel is on**, as in "Connected
  to Office, Wi-Fi −37 dBm" (Settings › Device). **Firmware change:** install
  the panel again (Send to ESPHome, then Install) to see it; until then the
  row shows the signal as before.
- **Zoom to any size between actual size and Fit.** Fit and Actual size are
  now one zoom control: − and + around a menu of Fit, 75%, 100%, 125%, 150%
  and 200%. ⌘+ and ⌘− step, ⌘0 is 100%, and a trackpad pinch zooms smoothly
  around your fingers. It remembers your size; on a phone it always fits.
- **They're called devices now.** Everywhere you read about the things you
  add and manage, the editor says "device" instead of "screen", so it isn't
  mistaken for a page: Add new device, Settings › Device, the menu, the bar
  under the canvas, its messages, the README and the add-on's TRMNL option.
  Nothing else changes: entity names and settings stay as they were.
- **The device menu can remove a device too.** Under the device's name: your
  devices, then Rename and Remove, then Add new device. Removing shows an
  Undo, as in Settings.
- **To-do lists as a page.** New page › To-do list shows any to-do list in
  Home Assistant (the shopping list, Local To-do, Google Tasks, Todoist):
  what's still to do, anything with a due date first, Overdue and Today
  marked, then "and 4 more" when they don't all fit. It shows only while
  the list has something on it. Each list is its own page, named after
  the list, so a work list and a chores list rotate, repeat or sit out like
  any other pages. Also under Insert › Widgets.
- **To-do rows that show what's urgent.** Under Style: By urgency (the
  start: an overdue item is a solid black row, today's is outlined, the
  rest plain), Inverted when due (overdue and today solid, the rest
  outlined), or Outlined (every row outlined). The due label sits inside
  its row, so it reads as part of the item.
- **Only what's due today.** A to-do list page can show only what's due
  today or overdue, and then shows only while something is. The add-on
  counts those items for each list on a page, so an alert can use the count
  too ("Bins out" in the morning), with or without an MQTT broker.
- **Alerts can end when something happens**, not only after a time. Under
  Ends, choose When something happens and pick what ends it: "Watch battery
  is below 20" until "Watch is charging" stays up until you put it on the
  charger, even though it's still below 20 while it charges, and comes back
  if you take it off too soon. At most sets how long it can hold if that
  never happens (2 hours to start with). Alerts that end after a time work
  as before.
- **Fixed:** a page or alert that shows by one of the add-on's own values
  (New to watch, for one) never showed without an MQTT broker, because Home
  Assistant was asked about a value it only learns through the broker. The
  add-on now answers those conditions itself, as it already did for what
  the pages show. Any condition or template that uses one of the add-on's
  own values now works without a broker, not only the simple form's, and
  one that reads a word ("nothing new") as a number counts as no value,
  not 0.
- **Fixed:** "Watch battery is below 20" came true for a moment every time
  Home Assistant restarted, because a sensor with no value yet counted as 0.
  A sensor that's unavailable or unknown now never meets "is below", "is
  above" or "isn't", so it can't fire an alert or show a page by accident.
  Conditions you already have are fixed too, without saving them again.
- **Fixed:** a panel asleep for quiet hours kept saying "back at 06:00" when
  the schedule ended but nobody was home, because nothing woke it to show
  "back when someone's home". It's now woken once when the sleep screen's
  words change, and never more often than that.
- **Sunrise and sunset**, from Home Assistant's sun, with nothing to set
  up. Next one first shows whichever comes next large and the other beside
  it, and turns round at sunrise and at sunset; Both alike shows them side
  by side. In the far north, a sunrise more than a day away says which day.
- **Energy at a glance**, straight from your Energy dashboard, with nothing
  to pick: Solar this month (the total and a bar for each day, from Home
  Assistant's long-term statistics; also by day or year, and for what you
  bought or sold), Grid now (buying or selling right now, with today's
  hours as bars, up when buying and down when selling) and Energy cost
  (earned or spent today and this month, from the prices in your Energy
  dashboard, in Home Assistant's currency). If the dashboard doesn't have
  what a page needs, the page says what to add there.
- **Now playing**: what's playing on any media player in Home Assistant
  (Spotify, Sonos, Apple TV, Chromecast, Plex, Jellyfin through JellyHA),
  with the artist or show and where it's playing. Follow the players you
  choose, or all of them; when several play, each is its own item of the
  page, latest started first, like planes overhead.
- **On TV this week**: the next episodes from any calendar of shows, such
  as Sonarr's or Trakt's, a row each ("Tonight  Slow Horses  S6 E6"), as
  many as read well and then "and 3 more".
- **Weather from your own station.** The Weather page can take what it
  says about now (temperature, humidity, wind) from your station's own
  weather entity or from single sensors, while highs, lows and the coming
  days stay with the forecast. With a rain sensor (one that measures rain
  per hour, or is on while it rains; a "rain today" total can't say it's
  raining now), the big icon shows rain whenever it's raining at your
  house, whatever the forecast says. With a pressure sensor in any unit
  (hPa, kPa, inHg, mmHg), it says when pressure is rising or falling. A solar
  radiation sensor can decide sunny or cloudy in the daytime, but only if
  you choose one: a station in the shade would read cloudy in full sun.
- **Fixed:** the Weather page drew over itself on the 4.2" and 2.9": the
  details ran into the coming days, and on the 2.9" the days were stacked
  on top of each other. It now keeps its usual look at every size, shows
  as many days and details as fit, and leaves out what doesn't.
- **Fixed:** while Home Assistant was restarting, the Weather page showed
  made-up weather (8.5° and rain). It now stays empty until the real
  weather is back, like every other value. Race weekend and Match did the
  same with a made-up race and match, before their results arrived or
  when there were none, and Planes overhead with two made-up aircraft;
  they now stay empty too. The examples live in one place and are only
  used for the New page sheet's pictures.
- **New to watch connects Jellyfin where you add it.** The address and
  API key are tried before anything is saved, with a plain answer when
  something's wrong (the key, the address, or not Jellyfin at all), and
  then you pick whose unwatched to show. With JellyHA installed, the
  address is filled in for you.
- **Each sport in its own words.** A football match is a match, an NBA or
  NFL game is a game, and the time before one starts reads "Kick-off
  20:00", "Tip-off 20:00", "First pitch 20:00" or "Puck drop 20:00". Home
  Assistant's sensor for a league says Matchday or Game day to match.
- **A clock is a clock however it's written.** A device that sleeps shows
  the date instead of the time it went to sleep with, now also for clocks
  written as `as_timestamp(now()) | timestamp_custom(...)`, the Time & Date
  sensor, or `now().hour`.
- **A Weather widget with no weather chosen shows the first one Home
  Assistant has**, instead of assuming it's called "Forecast Home".
- **Fixed:** Send to ESPHome named the panel's file with underscores
  (`crowpanel_epaper.yaml`), while ESPHome's own wizard uses dashes
  (`crowpanel-epaper.yaml`), so a panel first set up in ESPHome ended up
  with two files for one device. It now uses ESPHome's dashes; a file the
  add-on already wrote keeps its name, so nobody gets a second one.
- **An icon can follow its sensor.** An icon tied to an entity changes
  with its state (a door open or closed, a lock locked or unlocked), and
  keeps its own icon for any other state.
- **World clock**: up to four cities, each with its name (yours to change)
  and its time, all the same size and arranged to fill the space: side by
  side on the wide 5.79", stacked or two by two where that reads larger.
  Times follow each place's daylight saving and your 12- or 24-hour
  setting, and a city already on tomorrow says "+1". On a device that
  sleeps between updates, each city shows how many hours it is ahead or
  behind ("−7 h", "Same time"), which never goes stale.
  It's New page › Clock › Time zones: find each city by its name ("Here"
  is Home Assistant's own), rename it if you like, and drag the rows (or
  Alt with ↑ and ↓) to put them in order. The inspector edits the same
  list, and the page redraws as you add, remove or move a city.
- **Fixed:** a Race weekend page set to NASCAR or IndyCar showed Formula 1's
  race, drivers and status. Each series now reads its own results, and its
  page names it ("NASCAR · …"). Whether the page shows still followed the
  right series before; only what it showed was wrong. A wide driver code
  (HAM) no longer runs into its team's name.

- **New page, on shelves.** One shelf per group (Your day, Home, Energy,
  Outside, Sports, Watch and listen), each sliding sideways, with how many
  it holds beside its name. Arrows show at the edges as you point at a
  shelf, only where there's more, and the edge fades while there is; on a
  phone you swipe. Your own presets get a shelf of their own, first. Search
  finds a preset by any word, its old name too. "+ Blank page" sits in the
  footer. The arrow keys move along a shelf, and Esc goes back a step.
- **One preset per thing a page shows.** Its look is picked next: Planes
  overhead (Nearest plane, Radar or Both, now under Outside with the
  weather), Calendar (Month and agenda, or Month), New to watch (three
  styles), To-do list (By urgency, Inverted when due, Outlined), Scores (any
  league the add-on follows) and Race weekend (Formula 1, Formula E, NASCAR,
  IndyCar). It remembers the look you picked last.
- **Clearer names.** "Door or pet" is now Status, "On now" is Dynamic status,
  "Formula 1" is Race weekend and "Match score" is Scores, since an NBA or
  MLB game isn't a match. Where a single event is named, each sport keeps
  its own word: a match in football, a game in the NBA, a race in racing. Pages you already have don't change. A new
  Scores or Race weekend page is named after its league or series.

- **Guest Wi-Fi asks for your network.** Its next step asks for the
  network's name, password and security, and the code guests scan joins
  that network; the page shows the name and keeps the password in the
  code. Before, it came with a made-up network, and its words ran under
  the code.
- **Fixed:** a preset added on any device other than the 5.79" came out
  drawn for the 5.79", running off the canvas. It's now placed the way the
  add-on places a page on another size, and rearranged when the device
  stands upright. Every preset's words now fit their boxes at every size:
  New to watch's line at the top right and Battery and solar's heading no
  longer run over.

- **The likely sensor first.** A preset lists the sensors it's for first:
  temperature sensors for Room temperature, energy sensors for Solar today,
  and the one your Energy dashboard uses is picked for you and says so.
  Status takes any sensor's state now (a door, a person, a lock), door and
  window sensors first.

- **New to watch connects Jellyfin itself.** The first time, its next step
  asks for the server's address (filled in from JellyHA if you have it) and
  an API key, says where Jellyfin keeps it, connects, and asks whose
  unwatched to show. The connection is saved under Settings › Data sources
  like one you add there, and the next Jellyfin page offers it.

- **Fixed:** the scores widget's League menu offered nine leagues, though the add-on
  also follows MLS, the WNBA and college football. It offers all twelve now,
  the same list as New page.

- **Sunrise and sunset in New page**, under Outside, in two styles: Next
  one first (it turns round at sunrise and at sunset) or Both alike. It
  uses Home Assistant's sun, so there's nothing to set up. It's under
  Insert › Widgets too.

- **Solar this month, Grid now and Energy cost in New page**, under Energy.
  They read your Energy dashboard themselves, so there's nothing to pick:
  the next step says which of its sensors they use. When the dashboard
  hasn't got what they need, Solar this month and Grid now take a sensor
  of yours instead, right there, and Energy cost says where to add prices.
  Solar today opens with the dashboard's solar sensor picked. All three are
  under Insert › Widgets too.

- **Now playing and On TV this week in New page**, under Watch and listen
  beside New to watch. Now playing follows every media player, or the ones
  you tick, and shows only while one plays; On TV this week lists calendars
  of shows (Sonarr's, Trakt's) first. Both are under Insert › Widgets too.
- **Weather's "now" from your own station** can be set in the inspector:
  another weather entity, and sensors for temperature, humidity, wind,
  rain, pressure and sunlight, each optional.
- Search in New page puts presets whose name you typed first.

- **Fixed:** in New page, every preset that shows a sensor had "--" in its
  picture. They're drawn with example values now, never your own data, and
  the next step says "Example values" until you pick yours.

- **Fixed:** New page showed the word "null" above the shelves when you had
  no presets of your own, and in an energy preset's step.

- **A device that sleeps shows the date where a clock would be.** A device
  that sleeps between updates (Update every 2 minutes or more, and every
  TRMNL) shows what it got at its last update, so a clock there would stop
  at that time, and changing at every wake it would download and flash each
  time. Such a device now draws the date in place of any time on its pages,
  on its own: your pages keep their clock, and a device that's always on,
  even one showing the same pages, keeps showing the time. Switch it back
  to always on and the clock returns. The editor's canvas shows the date
  for that device, and the clock says why. New page offers Date there too.
- **Pages that change faster than a sleeping device say so.** On a device
  that sleeps between updates, Planes overhead, Now playing, Scores, Grid
  now and Battery and solar are still offered, with one line: "Changes
  faster than this device updates (every 15 min), so it can be up to 15
  min old." The same line shows in the inspector for a page like that.
  A sensor counts when Home Assistant describes it as always moving (power,
  current, wind and the like), whatever its unit.
  A Weather page counts only with your own weather station's sensors; a
  forecast alone changes slowly.

- **Countdown and Bin day without a calendar.** New page › Countdown now
  counts down to a date you pick (with a time if you like, and Every year
  for birthdays), to your bins, or, as before, to a calendar's next event.
  Bin day is now a Countdown: add each bin by name with its next collection
  and how often it comes (every week, or 2, 3 or 4 weeks), so alternating
  bins are two bins every 2 weeks. The evening before reads Tomorrow, the
  day Today until noon (or midnight, or numbers only: your choice). On the
  day of a date with a time it counts the hours. Starts showing keeps a
  countdown off the panel until it's near: set a trip six months ahead and
  have it show from a month before (its tile says "Shows from …"). Once a
  one-off date has passed the panel leaves it out, and it stays among your
  pages, outlined and marked Passed, its Delete showing on its tile, to
  give another date or delete.
  Nothing needs Home Assistant's calendar, and it's all editable later in
  the inspector. Pages you made from a calendar work as before.

- **The page strip slides like New page's shelves.** Its edges fade while
  there are more pages to see, with arrows at an edge only towards more as
  you point at it; down the side it fades top and bottom.
- **The page strip's size is yours to choose** in Settings › Editor, next to
  where it sits: Small, Standard (as it was) or Large.
- **A page's menu on its picture.** Point at a page in the strip, or hold
  it on a phone, and a "…" button shows on the right of its picture: it
  opens the page's menu (Duplicate, Delete and the rest, as a right-click
  does). On a countdown that has passed, it's Delete itself, showing all
  the time.
- **Fixed:** with the page strip down the side, New page shrank to a sliver
  and, with this release's sliding strip, the pages ran under the canvas.

- **Fixed:** presets wrote their own units, so a temperature in °F read
  "71.6 °C" and a solar meter in Wh read kWh. A value now shows its sensor's
  own unit, and changing a value's sensor in the inspector changes its unit
  too (words you typed yourself stay).
- **Battery and solar asks for each part it shows**: the home battery, the
  house power and the solar power, the Energy dashboard's own picked first.
  Before, two of its three gauges started empty.

- **Clock is offered on every device**, and on one that sleeps between
  updates its card says "Shows the date here": the device draws the date in
  place of the time by itself, so pages shared with an always-on device keep
  their clock there. **Date** is a preset of its own for anyone who wants
  only the day and date.

- **Fixed:** a gauge with no sensor showed a made-up "68%", and a gauge whose
  sensor has no unit added "%" of its own. With no value it now shows an
  empty gauge and no number; it shows its sensor's unit, or none, and its
  decimals ("1.8 kW").

- **Weather's rain field takes rain now, not rain so far.** Pick a rain total
  (mm, in) and it says plainly that the page would then say it's raining
  all day after a shower, and asks for a rate (mm/h, in/h) or a sensor
  that's on while it rains.

- **Solar today reads today, even from a lifetime meter.** It still shows the
  sensor you pick (your Energy dashboard's first), but when that sensor is a
  running total, as most inverters' are, the page shows how much it went up
  today rather than "18,532 kWh produced today", from Home Assistant's
  long-term statistics, in the sensor's own unit. Any value on a running
  total (a gas or water meter) can do the same.

- **12- or 24-hour time, in Settings › Time and language.** It starts as in
  Home Assistant (the way clocks read in its country: 2:05 PM in the US,
  14:05 in Romania) and changes every time on every device: clocks, sunrise
  and sunset, due times, kick-offs, race sessions, the clock in the corner
  and "updated". The Clock preset uses it, and any text can
  show the time or date the same way (Shows: Time, in the inspector).

- **The editor reads the add-on's own lists.** Leagues, racing series, each
  sport's words and every widget (its name, settings and how often what it
  shows changes) come from the add-on, so a league or series it learns
  appears in New page and the inspector by itself. Race weekend now says
  when it can be older than a sleeping device's update, like Scores. A
  preset added on a 4.2" or 2.9" is placed by the add-on itself, the same
  way it places any page on another size.

- **Status speaks your sensor's language.** A door says Open and Closed, a
  motion sensor Detected and Clear, a switch On and Off, a lock Locked and
  Unlocked, a person Home and Away, each with its own icon: Home
  Assistant's own words for that kind of device, which you can still
  change. Before, everything read "Open" with a door.

- **Turning a page upright knows a clock however it's written.** Rearrange
  this page, and New page on an upright device, ask the add-on which texts
  show the time, so a clock written any way Home Assistant allows is laid
  out as a clock.

## 0.14.0
**Firmware change:** install the panel again (Settings › Install or update,
then Send to ESPHome and Install in ESPHome) for the quiet-hours fix below.
Restart Home Assistant once after updating the add-on, so it loads the new
integration. Until you reinstall, the panel keeps working as before.

- **"Through your own address" can be chosen again.** Picking it asked for
  an address it hadn't shown you yet and said "The add-on couldn't read
  that", so it could never be picked. Now the address field appears, and
  until you save an https address there, screens keep reaching home the way
  they did, as the pane says.
- **How the screen runs is always in sight, under the canvas.** A small bar
  says whether it's always on or sleeps, how often pages turn and its quiet
  hours. Click it to change power, how often it updates, the next page, quiet
  hours on or off, and which way up it's mounted, without opening Settings.
  Settings › Screen still has all of these. The bar remembers whether you
  left it open.
- **Rename a screen right in the toolbar.** Choose Rename in the screen menu,
  or double-click its name, and type: Enter or clicking away keeps it, Esc
  puts it back. Settings › Screen still has its Name, now saying that
  Home Assistant takes a new name at the screen's next install.
- **The editor says why the add-on refused something.** A name that's taken
  or missing said "The add-on couldn't read that"; it now says, for example,
  "There's already a screen called Kitchen."
- **Add a screen is easier to find.** The screen's name in the toolbar now
  looks like the button it is, with a screen in front, and Settings ›
  Screen has an Add another screen row next to Remove.
- **Adding a screen asks about power before pages.** Always on or Sleeps
  between updates now comes right after the model, so it's never below the
  fold, and the sheet uses the window's height. Sleeps between updates has
  its own menu for how often it updates (2 minutes to a day, as in
  Settings), and so does a TRMNL.
- **The panel fills the editor in Safari.** Fit stopped at the panel's
  actual size, leaving most of a big window empty. It now uses the width it
  has, as it already did in other browsers.
- **Fixed (firmware):** during quiet hours, a panel woken from Home Assistant
  (its Sleep switch, or the editor) went straight back to sleep within
  seconds. Any wake now gets the same two minutes a button press does.
- **Reaching home through Home Assistant's address now finishes setting
  itself up.** After the restart, Home Assistant loaded the integration but
  nobody turned it on, so screens away from home got "not found". The add-on
  now does it within a minute of Home Assistant coming back, without opening
  the editor. Settings › Reaching home says which step it's at: restart
  needed, setting up, running, turned off, or not started.
- **The Restart Home Assistant row goes away after the restart.** It used to
  stay until the add-on itself restarted. Whether a restart is needed now
  comes from the version Home Assistant actually runs, and the pane updates
  by itself once Home Assistant is back.
- **Settings breathes again.** Every pane now keeps the same space between
  its parts, so text no longer runs into the cards below it, and the notes'
  icons match their colour.
- **You can change the password of the panel's own Wi-Fi** (Install or
  update, "Its own Wi-Fi when it's lost"). It needs 8 to 63 characters, and
  a change takes effect when you install the panel again.
- **No more "last render" error in Home Assistant's log at every start.** A
  "Last render" sensor from before 0.8.27 had left a time without a time
  zone in the MQTT broker. The add-on now clears it, which also removes that
  old, unused sensor (today's is sensor.epaper_panel_last_render), and every
  time it publishes carries a time zone.
- **Send to ESPHome.** Install or update has a button that puts the panel's
  file in Home Assistant's ESPHome folder and opens ESPHome in a new tab, so
  you choose Install there. It says when ESPHome's copy is older than the
  editor's. Saving the setup no longer writes the file by itself. As before,
  the file there is kept as `.yaml.previous`, and a file ESPHome would
  refuse is never sent.

## 0.13.0
**Firmware change:** install the panel again from Install or update to get
the fixes below and, for a panel that sleeps between updates, no flash after
a wake. Restart Home Assistant once after updating the add-on. Until you
reinstall, the panel keeps working as before.

- **Update every and Rotate every.** Every screen now has two settings, in
  Settings › Screen under Power, and they replace Low Power Mode, its wake
  interval and the panel's own "Check for new pages every". Update every
  1 minute is always on: buttons and alerts answer at once. 2 minutes or more
  (up to a day) and the screen sleeps in between, for a battery. Rotate every
  is how long each page shows: seconds when always on, and when sleeping, a
  number of updates (each update refreshes the page on screen, and every Nth
  moves on; before, every update moved on). Both apply at once, no Send
  needed. Adding a screen asks plainly: always on or sleeps between updates.
  A TRMNL gets the same two, from 5 minutes. Nothing changes on upgrade: a
  panel with Low Power Mode off is always on, one with it on keeps its
  interval, and its rotation time comes along. An always-on panel now checks
  every minute (the add-on sets its Refresh interval in Home Assistant to
  match); before, it was 5 minutes unless you changed it. Going back to
  0.12.0 finds your old settings as they were.
- **Fixed:** in Low Power Mode, a panel whose refresh interval is one minute
  never went back to sleep after a button press: every download it made while
  awake kept it awake another minute. Only a wake does that now.
- **Fixed:** a panel in Low Power Mode that reaches home through Home
  Assistant's address never slept: the e-Paper Panel integration dropped the
  answer's sleep time on the way. Restart Home Assistant once after updating
  the add-on so it loads the new integration.
- **Fixed:** through Home Assistant's address, a sender could claim a new
  address with every request and so never be slowed down for wrong keys. Only
  the address the integration itself passes on counts now.
- **Fixed:** sending pages with a size from another kind of screen (a TRMNL's
  size on a CrowPanel) was accepted, and that screen then couldn't be drawn at
  all. It's refused now, and a send that leaves the size out keeps the
  screen's own.
- **Fixed:** the editor's API answered a request whose body wasn't JSON with
  an internal error and a stack trace in the log; it now says the request was
  wrong (400).
- **Fixed:** Install or update made files ESPHome refuses. With no Wi-Fi
  network and the panel's own Wi-Fi off, or a Wi-Fi password that isn't 8 to
  63 characters, the editor now says what to fix above the file, and holds
  back Copy, Download and writing it to Home Assistant's ESPHome folder (the
  last good file stays there) until it's fixed. With no first network but
  others, the first of them leads instead of a blank one.
- **Fixed:** on the night the clocks change, a screen asleep until quiet hours
  end woke an hour late (spring) or an hour early (autumn, then slept again).
  It now wakes at the time on the clock.
- **Fixed:** an MQTT broker that accepts the connection and then stops
  answering could slow every render by many seconds. Values now go to Home
  Assistant in the background, so pages are drawn on time whatever the broker
  does.
- **Fixed:** opened through a tunnel or Home Assistant Cloud, Install or
  update told a new panel to fetch its pages from that public name over plain
  HTTP (audit #9). A new panel's address is now Home Assistant's own on your
  network (its internal URL, or its name there), never the browser's. The
  TRMNL pairing address too. An address you've already saved is kept.
- **Going back to 0.11.0 with a TRMNL:** 0.11.0 doesn't know TRMNL screens,
  and one saved by a later version breaks its list of screens. Before going
  back, remove your TRMNL screens (Settings › Screen › Remove), or restore a
  whole backup from before you updated instead. CrowPanels go back fine.
- **Removed:** the previous editor (`?classic=1`). It predates several
  screens; an old bookmark to it now opens the editor.
- **Fixed (firmware):** a panel in Low Power Mode stayed connected for as
  long as the add-on was down (an update, a restart, a stopped add-on),
  because Home Assistant's "isn't answering" counted as an answer. Only the
  add-on's own answer keeps it connected now; anything else makes it sleep and
  try again later, as when the network is down.
- **Fixed (firmware setup):** a screen with no Wi-Fi network filled in made
  firmware ESPHome refused, even with "Its own Wi-Fi when it's lost" on. It
  now gets only its own Wi-Fi, so you choose the network from a phone. A
  blank network among several is left out.
- **Fixed (firmware):** the panel now refuses a frame file whose footer sits
  outside the screen. Only a broken or forged file has one, and drawing it
  could freeze the panel for seconds.
- **Fixed (firmware):** a panel that sleeps between updates no longer
  downloads on its own timer while it's awake: the add-on's answer says when it next
  checks. A 2.9" panel no longer stays awake 6 seconds after a wake that
  didn't redraw anything.
- **Fixed (firmware):** the firmware for the 4.2" and 2.9" CrowPanels
  didn't build. Both build now, with the pins and controllers from Elecrow's
  own demo code, and the 2.9" gets its pages the right way round for its
  upright display. Neither has been tried on a real panel yet.
- **Fixed (firmware):** on a panel that sleeps between updates, pressing a
  button right after a wake, before the new pages had arrived, replaced the picture with a
  "waiting for frames" screen. The picture now stays until the pages arrive.
- **Changed:** the sizes offered for a new CrowPanel are the 5.79", 4.2" and
  2.9". The 7.5" and 10.2" are no longer offered, because Elecrow doesn't
  make them; a screen already set to one keeps working.
- **New (firmware), untried on a real panel:** a screen that sleeps between
  updates no longer has to flash after every wake. The display stays powered while
  the panel sleeps, keeping its picture, so a change is a quick partial
  refresh; every 8th change is a full one that clears ghosting, and so is
  every change when the panel checks only every 30 minutes or more. A panel
  that stays connected clears ghosting exactly as before.

## 0.12.0
**Firmware change** (only needed for Low Power Mode, or if your panel has
"Its own Wi-Fi when it's lost" switched off): install the panel again from
Install or update. Until then it keeps working as before.

- **Low Power Mode.** A switch per screen in Settings › Screen, and when
  adding one: the panel checks for new pages at an interval you choose and
  deep-sleeps in between, for months on a battery. Each check shows the next
  page; a button press shows every page and keeps it awake a minute. Stay
  awake keeps it up ten minutes for an update over Wi-Fi. **Firmware
  change:** install the panel again from Install or update to use it. The
  same firmware stays connected while the switch is off. Not yet tried on a
  real panel.
- TRMNL screens show how long they're awake per wake, next to battery and
  Wi-Fi.
- Screens that sleep get pictures drawn ahead in every render, so a wake is
  answered at once instead of waiting for drawing.
- **TRMNL screens.** Turn on TRMNL screens in the add-on's configuration, then
  add one in the editor (Add a screen, TRMNL). It pairs within ten minutes of
  you asking, gets its own key and shows your pages: one per wake, at an
  interval you choose per screen, with its button going to the next page.
  Quiet hours let it sleep until they end. Battery and Wi-Fi show in the
  editor and as Home Assistant sensors. Works through Reaching home too.
  Built from TRMNL's open-source firmware; not yet tried on a real one.
- **Fixed:** on another screen size, elements placed automatically could run
  into the footer on small panels, or leave a gap above it on others. They now
  stop exactly at the footer, whose height has one source.
- **Fixed:** a panel set up without its own Wi-Fi ("Its own Wi-Fi when it's
  lost" off) couldn't be installed: its firmware didn't compile.
- The Add a screen sheet no longer shows a stray "null" under the pages.
- "Now on the panel" shows the time pages were rendered again, instead of
  "Invalid Date".

## 0.11.0
**Firmware change** (only needed for the new things below): install the panel
again from Install or update when you want it to work away from home or join
more than one Wi-Fi network. Until then it keeps working as before.

- **The footer fits every screen.** The clock, the page and item counts and
  the panel's padlocks no longer run into each other on small or upright
  screens. When room runs out, the page name gives way first, then the
  counts shorten ("2" for "2/5"). The clock always stays. The highlighted
  pill's corners are clean.
- **More than one screen.** Add screens from the name at the top left of the
  editor: set up as new, copy another screen's pages, or show the same pages
  as another screen. A screen of another size keeps its own layout of shared
  pages; anything it hasn't placed yet is fitted automatically and outlined
  until you move it. Each screen has its own quiet hours, key and Refresh
  button in Home Assistant.
- **Away from home.** In Settings › Reaching home, a screen can fetch through
  Home Assistant's own address (the editor installs a small integration and
  asks for one restart) or through a tunnel of yours. Away from home every
  screen needs its key, and wrong keys slow down. Panels fetch over HTTPS, can
  know several Wi-Fi networks, and show the screen's name in Home Assistant.
- **Wi-Fi setup from your phone.** Where a panel knows no network, it opens
  its own Wi-Fi and its screen says how to join it and choose one. On by
  default, per screen, with its own password in Install or update.
- **One style around several elements.** Select two or more, then choose an
  outline, a pill or an inverted area under Together. It follows them when
  they move. Dragging several at once now snaps to the guides too.
- **Your panel becomes the first screen.** The add-on now keeps track of
  screens ("devices") and the pages each one shows ("designs"), so a later
  version can drive several panels of different sizes, each with its own
  pages, quiet hours and key. On the first start your panel becomes the
  first screen with everything it had: the same pages, settings, download
  address and Home Assistant entities. The files it used before stay where
  they were, so going back to 0.10.3 still works (changes made after the
  update won't be in them).

## 0.10.3
Add-on only; no firmware change.

- **Fixed:** "Space evenly" spread the elements' left edges between the outer
  two and ignored their widths, so a small icon between two wide numbers ended
  up inside one of them. Now it spaces them around the panel: the same gap
  between each of them and at both edges (across the whole width, or from the
  top to the footer). It works for two elements too.

## 0.10.2
Add-on only; no firmware change.

- **Fixed:** a value set to step up its unit always wrote the unit after the
  number, so with a label underneath the unit showed twice. Under Units, a
  new switch, **Unit after the number**, leaves it off; adding a label that
  follows the unit turns it off for you.

## 0.10.1
**Firmware change:** after updating, install the panel again from Panel
setup (Install in the ESPHome Device Builder). Until then the old firmware
keeps working as before.

- **Slow or dead services no longer hold anything up.** Your data sources
  (Jellyfin, web addresses, statistics) are fetched in the background, like
  the sports and flight widgets already were. A server that's slow, asleep or
  silent can't delay the panel or Send any more; a statistics query that
  never answers gives up after 15 seconds.
- **A service that stops answering says so.** Each one (ESPN,
  Flightradar24, OpenSky, the racing calendars, each data source) gets a
  problem sensor in Home Assistant, on once it has failed for five minutes,
  with the error and its last success. You can build an automation on it.
  The editor's status (`/api/status`) lists them too.
- **Entities stay put while their source is down.** A source that fails for
  an hour used to have its entity removed from Home Assistant, losing its
  name and area. Now only a value nothing produces any more is removed.
- **Your refresh interval is the contract.** Pages coming and going (a match
  starting, planes overhead) no longer make the add-on wake the panel early.
  It waits for the panel's own interval, which matters on a battery. Alerts,
  quiet hours and what you do yourself (Send, Push, the Refresh button) still
  update it at once.
- **More pages fit, and nothing is left out silently.** The panel now holds
  2 MB of pages (about 77 on the 5.79"), and says how much it holds. If the
  rotation needs more, every page keeps its first item and the extras are
  shared out; within a page, your teams come first, then live games, then
  upcoming, then finished; the closest planes; the newest episodes. What was
  left out shows in `sensor.epaper_panel_pages`. A sports widget can follow
  several teams: "Arsenal, Lakers".
- **Asleep, alerts and Home Assistant.** An alert still shows over sleep, and
  the panel now goes back to sleep afterwards (unless someone pressed a
  button meanwhile). Home Assistant's "show page" and "next page" now wake the
  panel *and* go there, and don't count as someone standing at it.
- **A failed download while asleep is retried** (30 s, then longer), instead
  of leaving the panel asleep all morning when the wake-up download failed.
  A refresh asked for during a download now follows it instead of being
  dropped.
- **Fixed:** errors from Home Assistant, Jellyfin or a web source wrote the
  add-on's Home Assistant token or the source's key into the add-on's log.
  Errors are now described without them.
- **Fixed:** two renders at once could put the previous pages back after a
  Send, until the panel's next refresh.
- **Fixed:** a page with a broken number (an empty "hours", say) stopped every
  render; now only that page is left out.
- **Fixed:** renaming a data source erased its saved key.
- **Fixed:** with both flight services down, the last list of planes was
  shown for hours; now at most five minutes. With no planes overhead, "closest
  aircraft" is cleared instead of keeping the last one.
- **Fixed:** a page listed twice in the rotation shares no identity with its
  first copy, so a lock on it stays there.
- **Fixed:** a very large page step from Home Assistant could freeze the
  panel until it restarted; a non-ASCII token on the LAN port caused an
  error instead of a refusal.

- **A name and a face.** The add-on is now called e-Paper Panel, "e-Paper"
  in the sidebar, and has its own icon and logo: the panel in its frame,
  showing a reading. The editor's tab icon matches.
- **Three Jellyfin screens in New page.** "New to watch" is the page you
  know. "Episode card" shows one new thing at a time: its name, which
  episode (or a film's year and length), and when it arrived. "Up next" puts
  everything new on one screen, a line each. With one Jellyfin source they
  use it straight away; with several, you pick.
- **Jellyfin's details on their own.** A Jellyfin source still has `detail`
  ("2 new episodes · yesterday"), unchanged, and now also each part of it:
  `episode_name`, `episode_number` (S02E04), `new_episodes` (a number),
  `what_is_new` (the episode name, "2 new episodes" or "film"), `kind`
  (episode, series or film), `added_ago` ("yesterday") and `added` (the date
  and time it arrived). Also new: `year`, `runtime` ("1 h 52 min"), `about`
  (the episode card's second line) and `up_next` (the first five, a line
  each). Pick them under "One of its details".
- **Pages that step through what's new** now show each item's own value for
  any of these, not the first item's on every step. Replacements you set on
  `detail` now apply on every step too, not just the first.
- **A page that shows only a whole-list detail** (`up_next`, `count`,
  `titles`) is one screen, instead of the same screen once per new item.
- **A new README**, with screenshots: what it's good for, where it can sit,
  and that it's meant for every CrowPanel.
- **Fixed:** with the page strip down the side, the panel's status and New
  page sat on top of each other. The status line no longer gets cut off,
  Duplicate has its own icon, and the history of a sparkline or bar chart
  can't be set past the week the add-on actually reads.

## 0.10.0
A new editor. Add-on only; no firmware change. The previous editor is still
there for now: add `?classic=1` to the editor's address.

- **One place for each thing.** The canvas gets the width. Your pages sit in a
  strip above it, in rotation order: the strip *is* the rotation, so you drag
  a page to move it. Its head says what's on the panel. With nothing
  selected, the inspector shows the page: when it shows, how often, and its
  name, edited in place.
- **Overlapping items.** A click picks the smallest thing under the pointer,
  so a card no longer blocks what's inside it. Click again without moving to
  reach the next one; the stack is outlined and labelled "2 of 3". Layers
  (front at the top, drag to reorder) and a right-click list of everything
  under the pointer reach the rest.
- **A click no longer nudges.** Moving starts after 4 px, and a plain click
  adds nothing to undo.
- **Copy, paste, and paste and match between pages.** Pasting keeps the same
  place and size, across pages, reloads and windows. Paste and match gives
  the elements already on a page the place, size and text style of what you
  copied, so two pages can share one layout.
- **Saved as you go, sent when you say.** Changes are kept in the add-on as
  you work; Send to panel puts them on the panel. A dot shows what isn't sent
  yet. If another window sent first, the two merge; you're only asked when
  both changed the same page.
- **Dynamic units.** A value can step up through its unit (950 W, then
  1.23 kW) or convert (m/s to km/h, °C to °F), and a label can follow it
  ("kW used"), with no templates.
- **Put the page strip where you like it**: above the canvas, below it, or
  down the side (Settings, Editor). Down the side turns back into a row on
  phones and narrow windows. The panel's status and New page share the
  front of the strip, so New page never scrolls away.
- **Text can wrap** onto more lines instead of running out of its box; the
  note that says it's cut off offers to wrap it.
- **Insert** finds element types and sensors in one search; drag a sensor
  onto the canvas to place it. **Presets** ask for your sensor.
- **Now on the panel**: up to date or not, what's rotating, which pages are
  hidden right now and why, quiet hours, Sleep now, Clear ghosting.
- **Settings in one place**: the panel (model, mounting, how often it checks,
  ghost clearing, sleep), installing it, quiet hours, data sources, and the
  editor itself. Sleep and ghost clearing need firmware 0.9.5 or later.
- Plain words, sentence case, real dark mode, the system font (no more font
  downloads, so it works offline), keyboard shortcuts (press ?), VoiceOver
  labels, and a phone layout for the Home Assistant app.
- **Fixed:** presets saved from the editor disappeared on the next save.
  Opening the full strip no longer saves your changes. The rotation's
  "Manual (buttons only)" choice is gone: it was always saved as 30 s.
- **API:** `GET /api/layouts` has an `ETag`; `PUT` with `If-Match` answers
  409 with the current pages when someone saved in between. Without
  `If-Match` it works as before. New: `/api/draft`, `/api/panel-device`.

## 0.9.7
**Reinstall the panel's firmware to get the last two items.** Save Panel
setup, then Install, as before.

- **Flight widget: type an airport code.** Enter a three-letter code (LHR,
  OTP, JFK…) and the widget goes there; the airport's full name is shown to
  confirm. Codes are looked up offline from a bundled copy of OurAirports
  (public domain, every open airport with a code), so nothing is sent
  anywhere.
- **Your own saved places, up to four.** Save the current place with one
  click; it's kept with your settings in the add-on, and × forgets it. The
  built-in TSR, LHR, JFK and FRA buttons are gone. Home is still one click
  away.
- **Fixed:** a latitude or longitude of exactly 0 was treated as "not set".
  Two flight widgets for different places now get their own sensors (the
  first keeps the original names).
- **Frames are protected by a token,** generated automatically if you
  haven't set `frame_token`. Panel setup puts it in the panel's YAML. Your
  panel keeps getting frames until it's reinstalled with the token, and from
  then on the token is required, so nothing goes blank in between. Panel
  setup shows whether protection is on yet.
- **Firmware updates use your encryption key instead of a separate
  password,** as ESPHome recommends (it drops password-only updates in
  2027.3). Panels built with ESPHome 2026.9 already accept this, so the
  next install just works. The OTA password field is gone from Panel setup.

## 0.9.6
Add-on only; no firmware change.

- **Easier to work on.** The 3,700-line `server.py` is now a dozen focused
  modules (frames, entities, outside-data sources, panel setup, web…), with
  no change in behaviour. New tests cover alerts, quiet hours, saving layouts
  and saving Panel setup.
- **The editor follows your system's light or dark appearance** until you
  pick one with the toggle, and it no longer flashes dark first on a light
  system.
- **Keyboard focus is visible** on every button, and the editor respects
  **Reduce Motion**.
- **Works in a private window.** The editor no longer fails to load when the
  browser won't let it remember preferences.

## 0.9.5
**New panel firmware** for the sleep screen (install as before). The add-on
part works with older firmware too.

- **A sleep screen for quiet hours.** While quiet hours last, the panel shows
  large closed eyes and when it wakes: "back at 07:00", or "back when
  someone’s home" when nobody's home. It switches over with one clean full
  refresh. Your pages are still one turn of the dial away, and after two
  untouched minutes the panel goes back to sleep. A locked page stays on
  screen all night instead. Turn it off under Quiet Hours ("Sleep screen")
  to keep your pages up overnight.
- **Sleep any time.** Hold the dial centre for a second to put the panel to
  sleep ("press any button to wake"), or use the panel's new **Sleep** switch
  in Home Assistant, for example in an automation. While it's asleep, the first
  press only wakes it, back to the page you were on. The dial never lands on
  the sleep screen, and `show_page` numbers are unchanged.
- **Rendering never waits on outside services.** Flights, sports, racing,
  weather and calendars are now fetched in the background, and pages are
  drawn from what's already there. A slow or broken ESPN, Flightradar24 or
  racing site can't hold up an update to the panel or a preview in the editor
  any more. Newly added widgets still fill in within seconds, and a failed
  fetch keeps showing the last good data.

## 0.9.4
**New panel firmware** (install as for 0.9.3).

- **No more flashes while you scroll.** The ghost-clearing full refresh (the
  ~1.8 s black-and-white flash) used to happen on every 10th redraw, even in
  the middle of scrolling. Now nothing you do triggers it. Once ghosting has
  built up, the next change the panel makes on its own (auto-rotation, new
  frames) carries the clear, so it rides on a change that was happening
  anyway. If you browse so long that no such change comes, it clears after a
  minute of stillness. It also clears once when quiet hours start, and for
  alerts.
- **Tune or revert it from Home Assistant, without reflashing.** In the
  panel's device page, under Configuration:
  - **Ghost clear after**: how many quick refreshes build up before a clear
    (default 10). Lower it if ghosting shows sooner.
  - **Ghost clearing**: *On automatic changes* (new), or *Every Nth refresh*
    (the old behaviour, as a one-tap revert).
  - **Clear ghosting**: a button that clears the screen now.
- **A quick press on the dial's centre switches modes again.** You no longer
  need to hold it for a second. A press within 0.4 s of turning the dial is
  ignored, because the dial tilts as it turns.
- **Holding the bottom button refreshes and clears ghosting** in the same
  redraw: one flash, not two.
- **One entry point for every input.** The dial, the buttons, remotes and
  Home Assistant actions all go through `PanelController::dispatch()`, as the
  architecture spec intends, and each input is logged once.

## 0.9.3
**New panel firmware.** Install it from the ESPHome Device Builder once the
add-on is updated. The previous firmware is in `esphome/rollback/` if you need
to go back.

- **Highlights and padlocks land exactly on the pills, in every orientation.**
  The panel no longer guesses which way up it is from what's on screen.
  0.8.37 looked for black pixels on two rows, so a page with a line or chart
  there flipped the highlight to the wrong side. The add-on now sends the pill
  positions and the exact rotation in the frame file. They're the same numbers
  it draws the footer with, so the two can't disagree. Portrait mounting gets a
  correct highlight for the first time.
- **The buttons never wait for the network.** Downloads run in the background;
  a slow or unreachable Home Assistant can no longer freeze the dial or trip the
  watchdog.
- **A bad download never reaches the screen.** Every frame file is checked
  before it's used: checksum, that it's for this panel's size, and that every
  offset stays inside the file. Before, a file for a different panel model
  could write past the end of display memory.
- **Locks survive alerts.** An alert takes over the screen as before, but
  your category or page lock comes back when it's over.
- **Firmware matches the add-on.** The firmware builds its component from this
  release's tag instead of whatever is on `main`, and the display driver is
  pinned to a tested commit.
- **One firmware source.** The YAML now comes from one template, and the
  repository's copy is checked against it. Removed: the PNG fallback (broken
  since 0.8.35), 21 mirrored globals, and the stray copies of `epf_client.h`
  and its download button.
- **Fixed:** saving Panel setup without retyping the Wi-Fi password wrote the
  masked `••••••••` into the ESPHome file. The previous file is now kept as
  `<name>.yaml.previous`.
- **Fixed:** in portrait, the pill widths sent to the panel were measured for
  landscape.
- **Docs:** `show_page` takes `index`, not `page`.

## 0.9.2
Security and privacy. The panel's firmware and frame files are unchanged.

- **The editor answers only Home Assistant.** It now refuses any connection that
  doesn't come through Home Assistant's Ingress (its login). Before, any other
  app on Home Assistant's internal network could open it without logging in, and
  read the panel's API key and OTA password from Panel setup.
- **The LAN port no longer gives away your setup.** Removed `/api/layouts`, which
  exposed every entity, template and custom location with no token check even
  when a token was set, along with `/manifest.json` and `/api/manifest`.
  `/status` is now a plain health check. Frames no longer carry page names or
  the quiet-hours flag in headers. Nothing on the network used any of this.
- **LAN actions need a token.** `POST /api/action/refresh` and `/api/action/page`
  are off unless `frame_token` is set, and they no longer answer GET, so a link
  preview can't trigger them. In Home Assistant, use the panel's actions or the
  Refresh panel button.
- **No built-in home location.** The fallback coordinates and timezone were a
  real place. Location now comes only from Home Assistant. Without one, the
  flight widget shows nothing and the log says where to set it.
- Retired sensors are withdrawn only while Home Assistant still has them, so
  restarts no longer log five "withdrew" lines.

## 0.9.1
- **No missing pages after a restart.** While the add-on is stopped, its
  entities read "unavailable". The first render now waits (up to 20 s) until
  they're back, so pages whose condition reads one, like *watch*, no longer drop
  out for the first minute.
- Uses `bashio::app.version` (the old name logged a deprecation warning).

## 0.9.0
Add-on only. The panel's firmware is unchanged, and so is everything it downloads.

- **Each sensor exists once.** 0.8.x wrote every value twice, so Home Assistant
  had `sensor.epaper_*` and `sensor.epaper_*_2`. Values now become entities only
  through MQTT discovery, with a broker login the Supervisor provides
  automatically. On first start, the add-on removes the old copies and gives
  each entity back its original ID. Entity IDs your pages and automations use
  don't change. It only touches IDs Home Assistant suffixed itself.
- **Real entities.** They sit under one "E-Paper Studio" device, can be renamed,
  survive restarts and show as unavailable while the add-on is stopped. The
  **Refresh panel** button works now; before, nothing listened to it.
- **Pages read the add-on's own values directly**, so data sources and widgets
  render with or without a broker.
- **The add-on finds the panel instead of guessing names.** It looks up the
  panel's actions in Home Assistant and its entities by registry ID, so renaming
  them doesn't break anything. The refresh interval slider now reaches the
  panel; before, it targeted an entity that didn't exist.
- **A refresh is never silently lost.** If the panel is offline, the update
  waits and is retried until Home Assistant confirms it, including the wake-up
  when quiet hours end. The editor says so instead of reporting success.
- **No more flickering flight page.** A live widget page stays 5 minutes after
  its condition last held, so planes at the edge of the radius don't reshape the
  rotation every minute.
- **One refresh timer.** The panel's own interval decides how often it checks.
  The add-on pushes only when something changed.
- **Fixed:** the last-render timestamp now carries a timezone. Home Assistant
  had logged an error for it every minute.
- **Retired:** the `sensor.epaper_category_*` sensors, firmware plumbing that
  nothing reads anymore. They're kept only if a page uses one.

## 0.8.37
- **Dynamic Framebuffer Orientation Auto-Detection:**
  - **Direct Framebuffer Geometry Detection:** `draw_overlays` now analyzes the physical framebuffer layout in real time. Because the footer hairline rule physically spans row 31 in 180° orientation and row 240 in 0° orientation, the engine auto-detects the exact orientation directly from memory.
  - **Dynamic Inversion & Padlock Coordinates:** Resolves coordinates as `rx = is_180 ? px : ((dw - 1) - px); ry = is_180 ? ((dh - 1) - py) : py;`. In 180° mode, the active category pill inverts on the left footer (`x = 96..206, y = 3..27`), sub-item pills on the right (`x = 704..752, y = 3..27`), and padlock badges align adjacent to the pills. In 0° mode, the overlays dynamically track the footer to the top-right buffer mapping.
- **Physical Overlay Geometry Alignment & Seamless Fast Refresh:**
  - **Restored Native DisplayBuffer Overlay Transform:** Restored physical buffer coordinate inversion `rx = (dw - 1) - px; ry = (dh - 1) - py;` in `draw_overlays` matching CrowPanel 5.79" physical hardware memory mapping. The category pill now inverts cleanly on the left footer, sub-mode pills on the right footer, and padlock badges render precisely adjacent to the pills.
  - **Removed Aggressive Waveform Settle Clears:** Removed the 5-second idle settle full refresh trigger that caused unnecessary 1840 ms screen flashes when pausing dial rotation. Dial scrolling remains silky-smooth with 480 ms partial refreshes, letting the native `full_update_every: 10` cycle handle waveform maintenance without disruptive flashes.
- **ESPHome External Component Cache Auto-Refresh & Compiler Hardening:**
  - **Added `refresh: 0s` to `external_components`:** ESPHome by default caches external Git repositories for 24 hours (`refresh: 1d`), which caused ESPHome Dashboard builds to compile against stale cached headers even after new commits were pushed. Adding `refresh: 0s` ensures ESPHome pulls the latest git commit on every build.
  - **Guarded `SYNC_PANEL_FROM_GLOBALS`:** Wrapped `SYNC_PANEL_FROM_GLOBALS()` with `#ifdef SYNC_PANEL_FROM_GLOBALS` in both `crowpanel-epaper.yaml` and the Python YAML generator. This ensures builds will never fail even if compiling against an existing or cached header.

## 0.8.34
- **Precision Overlay Coordinates & Navigation Hierarchy:**
  - **Corrected Horizontal Overlay Inversion:** Fixed ternary orientation mapping in `draw_overlays` (`rx = is_180 ? ((dw - 1) - px) : px`) where unrotated (0°) orientations previously mirrored X coordinates to the opposite side of the screen. The active category pill now highlights strictly on the left over `[ X/Y CATEGORY ]`, and sub-item pills highlight on the right over `[ A/B ]`.
  - **Human-Aligned Serial Navigation Logs:** Updated serial output in `page_step`, `mode_toggle`, and `check_auto_rotate` to log 1-indexed category and page counts (`cat=4/11 sub=1/1 (page=4/14)`), directly matching what is printed on the physical e-paper footer and eliminating confusion between 0-indexed internal variables and 1-indexed screen labels.
  - **Idle Settle Full Waveform Clear:** Added an automatic settle clear trigger to `interval: 5s`. After rapid dial scrolling, the panel waits until the user settles (3–7s idle) before performing a single full refresh pass to clean e-ink ghosting, completely eliminating mid-interaction flashing while actively turning the dial.
  - **Synchronized Web UI YAML Generator:** Fully synchronized `addon/app/server.py` `generate_esphome_yaml()` with `crowpanel-epaper.yaml` to ensure fallback PNG metadata parsing and `SYNC_PANEL_FROM_GLOBALS()` remain identical across both deployment paths.

## 0.8.33
- **E-Ink Footer Polish & Stream Retention:**
  - **Fixed Multi-Page Collapse on Refetch:** Removed conditional override in `refetch` that requested single-page `/frame.epf` when `pinned` was true. The panel now unconditionally fetches full multi-page `/frames.epf` so rotation categories and pages are never collapsed down to a single page in PSRAM, preserving sub-item rotation memory and locks across background updates.
  - **Orientation-Aware Overlay Coordinate Alignment:** Added `FLAG_ORIENTATION_180` (0x0008) to the EPF stream header. `draw_overlays` now maps active pill inversion boxes (`invert_rounded_pill`) and padlock badges (`draw_padlock`) strictly to physical buffer coordinates matching both 180° and 0° display orientations, eliminating inverted X/Y pill offsets and misplaced badges on rotated panels.
  - **High-Contrast Padlock Contrast Correction:** Corrected padlock pixel polarities on inverted SSD1683 displays to render Apple-grade crisp solid black rounded badges with pure white padlocks and black keyholes on the footer bar.

## 0.8.32
- **Compilation & Secrets Self-Healing:**
  - **Fixed undeclared `alert_interrupt`:** Corrected legacy PNG fallback lambda in generated ESPHome YAML.
  - **Fixed `Secret 'api_encryption_key' not defined`:** Added `_inspect_existing_secrets()` to check `/config/esphome/secrets.yaml`. If API or OTA keys are not declared in `secrets.yaml`, the generator automatically embeds literal keys so ESPHome builds cleanly without manual secret creation.

## 0.8.31
- **Frictionless Zero-Copy ESPHome Setup (`components/epf` & Auto-Sync):**
  - **Zero Manual Header Copying:** Packaged the `epf` streaming client as an ESPHome external component (`components/epf`). ESPHome now downloads the C++ engine directly from GitHub automatically alongside display drivers. No curl commands, no SSH, and no manual file dragging into `/config/esphome/`.
  - **Direct ESPHome Dashboard Auto-Sync:** Mapped `/config:rw` in the add-on manifest. Saving settings in E-Paper Studio automatically syncs the generated YAML directly into `/config/esphome/{device_name}.yaml`. Users can simply open ESPHome Dashboard in Home Assistant and click **Install**.

## 0.8.30
- **EPF (E-Paper Frame v3.0) Binary Streaming Protocol (`epf.py` & `epf_client.h`):**
  - **Eliminated 14.1s PNG decode blackout:** Directly streams 1-bit binary frames packed to SSD1683 scanline byte boundaries (12.8 KB for 6 pages vs. 35+ KB PNG).
  - 64-byte aligned binary header, directory tables, CRC-32 integrity validation, and HTTP 304 / ETag caching.
  - Zero-allocation static double-buffered PSRAM streaming (`front_buf_` vs. `back_buf_`) with atomic pointer swap—eliminating in-place buffer destruction, tearing, and decode freezes.
- **Microsecond Display Blit & Overlays:**
  - Page blits reduced from 346 ms to ~80 microseconds.
  - Inverted navigation pill and padlock badge render directly into the display buffer in <50 microseconds without modifying the cached bitmap.
- **Unified `PanelController` C++ Architecture:**
  - Physical buttons/rotary dial and BILRESA remote / Home Assistant API actions share the exact same C++ state machine, auto-rotation timers, and identity locking logic.
- **Waveform & Settle Polish:**
  - Full electrophoretic clears are suppressed during active scrolling (`user_cool_sec < 5s`). Smart settle clear kicks in smoothly only after browsing rests.
- **Studio Setup Upgrade:**
  - Added "Download epf_client.h" companion button in the E-Paper Studio device setup dialog.

## 0.8.29
- **Identity-Based Category & Sub-Item Locking Architecture (Impervious to Dynamic Rotation Shifts):**
  - **The Bug:** When a user pinned a specific sub-item (such as a live sports match or overhead flight) and a background refresh occurred that altered the number of categories (e.g. from 9 to 10), numeric position indices (`cat_idx = 8`) shifted. The category at position 8 became an unrelated single-page category (`sz = 1`), resetting `sub_idx = 0` and drifting the display to another page while the lock icon remained rendered.
  - **Self-Describing Metadata Version 2 (`stripmeta.py`):** Extended strip metadata with 32-bit Blake2s stable identities for every category (`cat_ids`) and every slice (`sub_ids`), an alert interrupt flag (`FLAG_INTERRUPT`), 16-bit slice count, and CRC-8 data integrity validation. Fully backward-compatible with v1 firmware streams. Multi-row packing automatically wraps metadata across rows when needed without altering the page count integer division (`h / page_h`).
  - **Dynamic Sub-Item Discovery & Disambiguation (`subitems.py`):** Automatically discovers sub-items across all composite widgets (`sports_match`, `flight_tracker`, `feed`/Jellyfin/Watch, and generic composite layouts), deriving stable content IDs (ESPN event IDs, flight callsigns, Jellyfin item IDs) with guaranteed collision avoidance.
  - **Hardware & Generator Firmware Parity (`crowpanel-epaper.yaml` & `server.py`):**
    - Firmware tracks `pinned_cat_id`, `pinned_sub_id`, `cur_cat_id`, and `cur_sub_id` rather than fragile numeric indices.
    - Upon download completion (`on_download_finished`), the panel resolves active positions by searching `sub_ids` for the pinned sub-item or `cat_ids` for the pinned category. If categories are inserted or removed, the locked sub-item remains locked and displayed on screen without jumping.
    - Cyclic rotation memory (`cat_sub_pos`) is remapped across category identities so sequential sub-item rotation (`1/N → 2/N → 3/N`) is never scrambled when categories are inserted or deleted.
    - If a locked event finishes and departs the rotation, the lock releases gracefully with diagnostic logging.

## 0.8.28
- **Pixel-Exact Centering & Symmetry for Icons and Lines (`layout.py` & `index.html`):**
  - **Root Cause 1 (`_draw_line` off-center inside its box):** Previously, `_draw_line` called `d.line([(x + w // 2, y), (x + w // 2, y + h)], width=thick)`, which in Pillow draws an even-width stroke at columns `[x + w//2 .. x + w//2 + thick - 1]`. For an `8px`-wide vertical line box (`[x .. x+7]`, center `x + 4.0`) with `thick=2`, Pillow drew at columns `[x+4, x+5]`, leaving **4 blank pixels on the left and 2 blank pixels on the right** (+1.0px right-shift inside its own box). Replaced `d.line` with exact pixel-centered rectangle coordinates (`x0 = round(x + (w - thick) / 2.0)`) so lines have identical left/right (or top/bottom) padding inside their bounding box (`0.0px` shift).
  - **Root Cause 2 (`_draw_icon` metric bearings vs 1-bit ink bbox):** Previously, `_draw_icon` used `d.text(..., anchor="mm")`, which centers by font advance/ascent metrics rather than the thresholded 1-bit ink bounding box. Added `_render_mdi_1bit_crop()` and `_mask_symmetry_error()` in `addon/app/render/layout.py` so icons are cropped to their exact 1-bit ink bounds, auto-sized to match the even/odd parity and horizontal symmetry of their container box, and pasted dead-center (`0.0px` shift).
  - **Root Cause 3 (Canvas `guides()` snapping line box edges before centerline):** Previously, `guides()` checked `[el.x, "l"]` (left box edge) before `[el.x + el.w / 2, "c"]` (center). When dragging a narrow vertical line (`w = 8..12`), `el.x` was within `SNAP (6px)` of the target centerline and snapped the line's **left box edge** to the icon's center instead of the line's **center**. Updated `guides()` so vertical lines only snap horizontally by their centerline, horizontal lines only snap vertically by their centerline, and the closest snap target wins with center priority.
  - **Line Direction (`Horizontal` / `Vertical`) & Length Controls:** Added a **Direction (`Horizontal (―)` / `Vertical (│)`)** selector and **Length (px)** input to the `line` inspector, plus automatic even/odd parity normalization (`normalizeLineParity`) on `Center X`, `Center Y`, and multi-select alignment.

## 0.8.27
- **Self-Contained Active Window Controls for Sports, Racing & Flight Cards (Zero Manual HA Sensor Wiring):**
  - Previously, making `sports_match` only appear on matchdays required manually creating/wiring a `show_if` check against `sensor.sports_premier_league`, which broke when switching leagues (e.g. to Champions League or NBA) and didn't exist at all for `sports_racing` (Formula 1, Formula E, NASCAR, IndyCar).
  - **`sports_match` (All 9 Leagues + Optional Team Filter):** Added an **Only show page during active matchday window** toggle, `show before (hrs)`, and `show after (hrs)` directly in the Studio element inspector. Switching leagues (`Premier League`, `UEFA Champions League`, `La Liga`, `Bundesliga`, `Serie A`, `NBA`, `NFL`, `MLB`, `NHL`) or specifying a `team` filter automatically updates the active window and syncs the page condition — no manual Home Assistant sensor creation or editing required.
  - **`sports_racing` (Formula 1, Formula E, NASCAR & IndyCar):** Added `compute_racing_active_window()` in `server.py` and full inspector controls (**Only show page during active race window**, **Window Mode**: `Around Each Session (FP / Quali / Race)` vs `Entire Race Weekend (FP1 → Checkered Flag)`, `show before (hrs)`, and `show after (hrs)`). Evaluates both the `sportstimes` session schedule (`fp1`, `fp2`, `fp3`, `qualifying`, `sprint`, `gp`/`race`) and live ESPN telemetry.
  - **`flight_tracker`:** Added **Only show page when aircraft overhead (> 0)** toggle directly in the widget inspector.
  - **Direct Python Evaluation in `eligible_pages()`:** Pages with `tier: "when"` containing `sports_match`, `sports_racing`, or `flight_tracker` now evaluate their widget's live active window directly in Python (`_evaluate_widget_gate()`), so active windows work out-of-the-box even before Home Assistant polls any external sensor.
- **Unified `sensor.epaper_*` Namespace, On-Demand Publishing (No Bloat) & MQTT `unique_id` Support:**
  - All add-on-generated sensors now use the `sensor.epaper_*` prefix (`sensor.epaper_sports_<league>`, `sensor.epaper_racing_<series>`, `sensor.epaper_flights_overhead`, `sensor.epaper_closest_aircraft`, `sensor.epaper_quiet_hours`, `sensor.epaper_panel_last_render`, plus user data sources `sensor.epaper_<slug>`) with `attribution: "E-Paper Studio"`.
  - **On-Demand Only (Zero Entity Bloat):** `publish_computed()` scans `layouts.json` and only polls/publishes sports, racing, or flight sensors for leagues, series, or radars actually present on your pages.
  - **Automatic Legacy Sensor Migration:** Existing layouts, `show_if` rules, and exploded widgets referencing legacy names (`sensor.sports_*`, `sensor.f1_status`, `sensor.formula_e_status`, `sensor.overhead_aircraft_count`, `sensor.closest_aircraft`) are automatically migrated to `sensor.epaper_*` in `sanitize_layouts()`.
  - **MQTT Auto-Discovery `unique_id` & Device Grouping:** All active `sensor.epaper_*` sensors are registered via MQTT Auto-Discovery (`publish_mqtt_discovery`) with a deterministic `unique_id` and grouped under the **E-Paper Studio** device in Home Assistant when an MQTT broker is present.
  - **`✦ E-Paper` Filter Chip & `E-PAPER` Badge in Studio Entity Picker:** Added a dedicated **`✦ E-Paper`** filter pill and **`E-PAPER`** badge in the right-rail Entities Explorer so app-native sensors are immediately recognizable.
- **Quiet Hours Modal Time Picker Layout Fix:**
  - Fixed `.row input { flex: 1; min-width: 0 }` squeezing `#qh_start` and `#qh_end` `<input type="time">` fields down to ~35px alongside the inline helper span. Give `input[type="time"]` a fixed `136px` non-shrinking width (`flex: 0 0 136px`), moved the helper note to its own caption line below, and added `color-scheme: dark` / `light` so native browser time pickers render legibly in both themes.

## 0.8.26
- **Manual Scroll Protection & 15-Second Background Fetch Debounce (`user_cool_sec` & `request_refetch`):**
  - Eliminated device freezes when scrolling manually through pages while a 1-minute background update fires.
  - Every physical button press (`key_next`, `key_prev`, `key_ok`, `key_top`, `key_bottom`) and remote action (`page_step`, `mode_toggle`, `lock_toggle`, `category_step`, `sub_step`, `show_page`, `show_category`) now starts a **15-second interaction cooldown (`user_cool_sec`)**.
  - Incoming `refresh_now` pushes from Home Assistant and internal refresh timers now route through `request_refetch`, which checks `user_cool_sec < 15`. If the user is actively scrolling, the network download is **paused/deferred (`pending_refetch = true`)** and automatically executed 15 seconds after manual scrolling stops.
  - Reduced `online_image` `buffer_size` from `32768` to `4096` (and `http_request` `buffer_size_rx` to `4096`) so multi-page PNG decoding yields to the ESPHome main loop between 4 KB chunks rather than blocking in a single 14-second `loop()` call.
- **Decoupled Fast Local PSRAM Page Rotation (`rotate_sec`) vs Background Network Fetch (`panel_refresh_interval`):**
  - Previously, every rotation step on the ESP32 triggered `script.execute: refetch` (making an HTTP request on every page turn) and ignored the Studio UI's `rotate_seconds` (`#rotinterval`) setting.
  - The self-describing metadata row in `frames.png` now encodes `rotate_seconds` (2 bytes MSB/LSB) alongside a 16-bit content hash (`etag_b0`, `etag_b1`).
  - The ESP32 now runs a 5-second interval loop that rotates pages **locally in PSRAM** every `rotate_sec` (`30s` default, ~480 ms blit, zero network activity) while `fetch_idle_sec` independently triggers background data fetches every `panel_refresh_interval` minutes.
- **Sequential Sub-Item Rotation Memory Across Category Passes (`cat_sub_pos`):**
  - Fixed multi-item categories (Watch/Media feeds, Airspace Radar flights, Sports matches) always resetting `sub_idx = 0` on every rotation pass or after a 1-minute data refresh.
  - Added per-category sub-item position memory (`std::vector<int> cat_sub_pos`) on the ESP32. Pass 1 through a multi-item category now displays sub-item `1/N`, Pass 2 displays `2/N`, Pass 3 displays `3/N`, and background 1-minute `frames.png` refreshes preserve both `cat_sub_pos` and the currently displayed `sub_idx` without resetting the rotation timer.
- **HTTP `304 Not Modified` & `Last-Modified` Cleanups:**
  - Added RFC 2822 `Last-Modified` header to `_frame_headers()` in `server.py`, eliminating `[W][http_request:032]: No header with name last-modified found` in ESPHome logs.
  - When `online_image` receives `HTTP 304 (Not Modified)` and the 16-bit strip hash (`last_strip_hash`) and page index are unchanged, `on_download_finished` now skips the redundant physical e-paper `redraw`.

## 0.8.25
- **Configurable Night / Quiet Hours (Zero-Ghosting Deep Idle):**
  - Added an optional, fully configurable **Night / Quiet Hours** schedule (`quiet_hours`) accessible via the top toolbar (`🌙 Quiet`) or **Settings → Night / Quiet Hours…** (`enabled: false` by default).
  - Supports a daily time window (`start` to `end` in `HH:MM`, including overnight windows like `23:30` to `07:00`) and/or an optional Home Assistant presence entity (`zone.home`, `person.*`, `group.*`, `input_boolean.*`) that activates Quiet Hours automatically when everyone is away (`0`, `not_home`, `away`, `off`).
  - **How it works:** While Quiet Hours are active, the server suppresses background `refresh_now` pushes to the panel and encodes a quiet-mode flag (`0xA5`) in the self-describing metadata row of `frames.png`. The ESP32 pauses its 10-second auto-rotation timer so the e-paper screen performs **zero physical flashes** overnight (eliminating e-ink wear and bedroom flashing while retaining the crisp image at zero power), yet **stays 100% awake on Wi-Fi** so physical buttons and IKEA BILRESA scroll remotes still page instantaneously.
  - Optional **Allow Interrupt Alerts (`allow_alerts`)** override lets high-priority `alert` tier pages wake and update the panel even during Quiet Hours.
  - Publishes `sensor.epaper_quiet_hours` (`active` / `inactive`) with schedule and reason attributes to Home Assistant.
- **New E-Ink Native Primitives & Visual Styling:**
  - **`box` (Card / Container / Pill / 50% Screen):** Structural rectangle/rounded card primitive supporting `outline`, `black` (solid fill), `white` (opaque mask), and `screen` (50% checkerboard grey pattern) with configurable corner `radius` and border `thickness`.
  - **Inverted & Pill Badges on `text`, `number`, and `icon`:** Any text, number, or icon element can now toggle `Invert (White on Black)` and/or `Pill / Badge Frame` with configurable corner `radius` for high-contrast headers, status tags, and callout badges.
  - **`bar` (Progress / Gauge Bar):** Horizontal (`solid` or `segmented` battery blocks) or `vertical` tank/column gauge bound to any numeric entity or template, with configurable `min_val`, `max_val`, `title`, `suffix`, and `show_label`.
  - **`bar_chart` (Multi-Bar History Column Chart):** Renders historical Home Assistant sensor data bucketed into `4`–`24` discrete vertical columns over `1`–`72` hours with min/max scale labels and current value readout.
  - **`qr` (Zero-Dependency 1-Bit QR Code Generator):** Pure-Python ISO/IEC 18004 QR code renderer (`addon/app/render/qr.py`) supporting URLs, static text, live Home Assistant entity states, or **Guest Wi-Fi credentials** (`WIFI:T:WPA;S:...;P:...;;`) with crisp module scaling and optional caption header.
- **Per-Element Conditional Visibility (`show_if`):**
  - Every individual element on a page now supports an optional `show_if` condition (structured entity state comparison or raw Jinja expression) in the inspector, allowing badges, warning icons, or secondary metrics to appear or hide dynamically on the same canvas without duplicating whole pages.
- **Studio Multi-Select (`Shift+Click`), Group Alignment & Custom Presets:**
  - **Multi-Select (`Shift+Click`):** Hold `Shift` and click elements on the canvas to select multiple elements at once. Dragging or pressing arrow keys moves the entire selection together.
  - **Multi-Element Alignment & Distribution Toolbar:** Selecting 2+ elements opens a dedicated alignment inspector (`Align Left`, `Center H`, `Align Right`, `Align Top`, `Middle V`, `Align Bottom`, `Distribute H`, `Distribute V`, `Duplicate Selected`, `Delete Selected`).
  - **Save Page as Custom Preset:** Save any designed page into your personal **Custom Presets** library (`💾 Save Page as Preset…`), stored in `layouts.json` (`custom_presets`) and accessible with one click in the **Page Presets** modal alongside two new built-in presets (`Energy & Battery Gauges` and `Guest Wi-Fi QR Card`).
- **Single-Page Slice Endpoint (`/frame.png?page=N`):**
  - `/frame.png` now accepts an optional `?page=N` query parameter to serve any individual rendered slice PNG directly by index.

## 0.8.24
- **Editable & Customizable Composite Widgets (`font_scale`, Layout Density & Break Apart):**
  - **Typography Scale (`font_scale` 0.70×–1.60×) & Density Controls:** All composite widgets (`weather_forecast`, `calendar_month`, `calendar_agenda`, `flight_tracker`, `sports_racing`, `sports_match`, `dynamic_grid`) now expose a **Font Scale (`70%`–`160%`)** slider, **Show Outer Border** toggle, and layout-specific density controls (`Forecast Days` 3–5, `Split Hero + Forecast` vs `Full-Width Forecast Only`, `Max Events` 2–6, `Max Matches` 2–4, `Radar Split` vs `Telemetry Only`).
  - **✂️ Break Apart into Editable Elements:** New one-click inspector action (`POST /api/widget/explode`) that decomposes any composite widget (`weather_forecast`, `flight_tracker`, `sports_racing`, `sports_match`, `calendar_agenda`, `dynamic_grid`) into standard, individually draggable `text`, `number`, `icon`, and `line` elements on the canvas for unlimited pixel-level customization.
- **Weather Forecast Multi-Tier Fallback Engine:**
  - Fixed `weather_forecast` cards getting stuck on `"Forecast loading..."` on modern Home Assistant (`2024.3+`, where `state_attr('weather.x', 'forecast')` was removed).
  - `fetch_weather_forecast()` in `server.py` now tries 4 tiers automatically: (1) HA REST `POST /api/services/weather/get_forecasts?return_response` (`hourly` + `daily`), (2) HA WebSocket `weather/get_forecasts` fallback, (3) legacy `attributes.forecast`, and (4) **automatic Open-Meteo API fallback** using your `zone.home` coordinates and WMO weather codes if the HA weather integration fails or is unavailable.
- **Eliminated Black "Sleep-Like" Screen & Remote Desync Bugs:**
  - **Root Cause 1 (Torn In-Flight Downloads):** ESPHome's `online_image` clears/reallocates its target PSRAM buffer as soon as an HTTP download starts (`GET /frames.png`), taking ~5–6 seconds to decode. Previously, if the 10s timer ticked or a remote action fired mid-download, the display lambda blitted an uninitialized/zeroed PSRAM buffer (`COLOR_ON` with `invert_colors: true` = solid black screen) until the user rotated the dial.
  - **Root Cause 2 (Stale `cat_offsets` / `cat_sizes`):** `ha_cat_offsets` and `ha_cat_sizes` arrived asynchronously over the ESPHome native API out of lockstep with `frames.png`, causing `page_step` from an IKEA BILRESA scroll remote to compute out-of-range slice indices (`y_offset >= strip.height`).
  - **Fix — Self-Describing Strip Metadata & Download Guard:** `server.py` now embeds a self-describing binary header (`0xA5` magic, `cat_count`, `(offset, size, pill_width)` per category, and `quiet_hours_active`) in the bottom-right pixels of `frames.png`. The firmware reads this header atomically inside `on_download_finished` and guards `redraw`, `page_step`, `mode_toggle`, `lock_toggle`, and `show_page` with `downloading_frames` so mid-download triggers defer cleanly until decoding finishes.
- **Studio Canvas Smart Alignment Guides:**
  - Dragging an element on the canvas now snaps to and renders live magenta alignment guides for canvas centerlines (`X = W/2`, `Y = H/2`) and other elements' edges and centers (`±5 px` threshold; hold `Alt` to bypass snapping).

## 0.8.23
- **Custom Flight Tracker Coordinates & Airport Presets:**
  - Added support for custom latitude and longitude on flight tracker cards (allowing traffic monitoring above specific airports such as TSR, LHR, JFK, FRA, or any custom coordinate) with graceful fallback to Home Assistant's `zone.home` coordinates.
  - Multi-location cache: flight tracker cache is now keyed per location and radius, allowing multiple cards or airports without cache collisions.
  - Added Airport Presets (Home, TSR Timisoara, LHR Heathrow, JFK New York, FRA Frankfurt) and custom location label input in the Visual Editor inspector.
  - Added location tags to on-screen distance badges (`1.5 KM E · LHR`) and radar headers.
- **Formula E Motorsport Pit-Wall Tracker:**
  - Added native Formula E support (`series: "fe"`) to `sports_racing`.
  - Integrates with authoritative Formula E season calendar feeds (`sportstimes/f1` and `formulaecal.com`), automatically resolving current/upcoming ePrix rounds, practice sessions, qualifying, and race sessions.
  - Publishes `sensor.formula_e_status` to Home Assistant with state (`PRE`, `IN`, `POST`), event name, circuit, and localized session schedule.
  - Features dedicated electric motorsport iconography (`mdi:car-electric`).
- **Local & Preferred Timezone Conversion for Sports & Motorsport:**
  - Automatically queries Home Assistant's configured timezone (`/api/config` -> `time_zone`, e.g. `Europe/Bucharest`) or accepts card-level custom timezone overrides.
  - All sports kickoff times (Premier League, NBA, NFL, Champions League, etc.) and racing session times (F1, Formula E) are automatically converted from UTC to the user's local timezone (e.g. converting 13:00 UTC to `16:00 EEST` / `15:00 EET`).
  - Added localized time attributes (`first_kickoff_local`, `last_kickoff_local`, `window_start_local`, `window_end_local`) to `sensor.sports_{league_slug}` for easy Jinja automation templates.

## 0.8.22
- **Real-Time ADS-B Flight Tracking:**
  - Replaced deprecated/rate-limited OpenSky Network feed with ultra-fast, rate-limit-free Flightradar24 live feed with OpenSky fallback.
  - Automatically fetches live aircraft within range of Home Assistant home coordinates (`zone.home`), delivering flight routes (`BEY → DUS`), aircraft models (`A320`, `B77W`), speed, altitude, and heading.
  - Dynamically synchronizes `sensor.overhead_aircraft_count` and `sensor.closest_aircraft` to the card's configured radius (clamped to realistic ADS-B line-of-sight: max 250 km).
- **Dynamic Sports Matchday Active Window:**
  - Added smart matchday active window computation engine for all leagues (Premier League, UEFA Champions League, La Liga, Bundesliga, Serie A, NBA, NFL, MLB, NHL).
  - Automatically prioritizes today's games (`?dates=YYYYMMDD`) over previous round results, dynamically showing the card from configurable pre-match buffer (default: 2 hrs before kickoff) until post-match buffer (default: 2 hrs after final whistle).
  - Automatically keeps card active if any game is live / in progress.
  - Publishes `sensor.sports_{league_slug}` (e.g. `sensor.sports_premier_league`, `sensor.sports_nba`) with state `active`/`idle` and rich matchday metadata for 1-click Page Tier conditional display (`show_if: "{{ is_state('sensor.sports_premier_league', 'active') }}"`).
  - Added configurable pre-kickoff and post-whistle buffer controls to the Visual Editor inspector.

## 0.8.20
- **Feed / Watch Sub-Item Cycling:**
  - Resolved issue where secondary episode detail elements in the watch/feed card remained frozen on the first item's episode title.
  - Added multi-tier resolution in `server.py` sub-item slicing to seamlessly cycle both titles and episode details whether configured via structured entity attributes, custom Jinja templates (`{{ state_attr(...) }}`), or template values matching the feed's initial detail.
  - Exposed `/api/layouts` on the panel LAN port for diagnostic inspection.

## 0.8.19
- **Remote & Hierarchical Navigation Actions:**
  - Added native `action: mode_toggle` to switch between Category mode and Sub-category navigation, supporting remote automations (IKEA Bilresa, Matter/Zigbee remotes) with on-screen active pill inversion sync.
  - Upgraded `action: page_step` to be context-aware (steps sub-items when in sub-mode; steps categories when in category mode), eliminating 1D/2D state desync and black overhang boxes.
  - Added `action: lock_toggle` for unified contextual single-click locking (Category lock in category mode, Panel lock in sub-mode).
  - Ensured `show_page` recalculates `cat_idx` and `sub_idx` from category offsets so absolute page jumps never desynchronize.

## 0.8.18
- **Render Loop Fix:**
  - Resolved `TypeError: string indices must be integers, not 'str'` in `build_frames` by using display dictionary `disp["margin"]` instead of string identifier `display["margin"]`.
  - Restored continuous background rendering and real-time category sensor updates (`sensor.epaper_category_pill_widths`).

## 0.8.17
- **Security & Authentication Hardening:**
  - Enforced `_check_frame_auth` token validation across physical refresh and page stepping action endpoints (`/api/action/refresh`, `/api/action/page`), preventing unauthenticated physical e-paper refresh denial-of-service on LAN port 8099.
  - Added full support for `Authorization: Bearer <token>` in addition to `X-Frame-Token` and query parameter tokens.
  - Hardened `/api/panel/setup` GET & POST handlers to mask Wi-Fi credentials in generated YAML and secrets text, preventing plaintext password leaks over the web interface.
  - Removed risky positional index fallback in `feeds.unmask_secrets()`, ensuring secrets are matched strictly by feed slug to prevent credential cross-contamination when feeds are reordered or added.
- **ESP32-S3 Firmware Memory Safety & Live Sync:**
  - Added screen coordinate bounds checking (`rx < dw && ry < dh`) in both Category and Sub-item active pill inversion loops, eliminating out-of-bounds PSRAM writes and ESP32-S3 `LoadProhibited`/`StoreProhibited` panics.
  - Replaced `.empty()` sensor checks with dynamic vector assignment in `ha_cat_offsets` and `ha_cat_sizes`, allowing Home Assistant category and layout changes to sync live without requiring a physical panel power-cycle.
  - Added `ha_cat_pill_widths` text sensor for real-time pill width synchronization from Home Assistant.
  - Added `!std::isnan(x)` check on `ha_cat_count` to prevent undefined behavior during initial sensor discovery.
  - Tuned rotary dial center button (`key_ok`, GPIO 5) to toggle navigation mode on a long hold (1000ms–5000ms), eliminating accidental mode switches caused by rotary dial scroll tilt wobble.
- **Rendering Engine & Backend Stability:**
  - Resolved fatal `UnboundLocalError / NameError: cat_pill_widths` in `server.py` that caused immediate render loop crashes.
  - Corrected runaway render loop timing (`await asyncio.sleep(REFRESH)`), restoring user-configured refresh intervals (e.g. 5m / 10m).
  - Implemented `step_panel_page` to properly forward relative page steps to ESPHome via Home Assistant services.
  - Hardened Jinja template generation for `last_changed` and `last_updated` against missing entities, and validated `replace` configuration types to prevent unhandled `AttributeError`.
  - Added boundary clamping for calendar month/year rendering and dynamic grid calculations to prevent `IndexError` and division-by-zero crashes.
  - Bounded footer category pill width against sub-item pill positions to prevent visual overlapping on narrow displays.

## 0.8.16
- **Self-Describing Image Header & Permanent Anti-Desync Architecture:**
  - `frames.png` now encodes the authoritative category count, slice offsets, and sub-page sizes directly into a dedicated invisible header scanline appended to the image strip.
  - ESPHome parses this metadata directly out of the downloaded image buffer in PSRAM on `on_download_finished`.
  - Solves the asynchronous metadata race condition where Home Assistant entity updates desynced from the image currently held in panel PSRAM, permanently preventing missing categories (such as sports match / scores) or wrong slice navigation when conditional pages dynamically join or leave the rotation.
  - Immediate proactive push (`refresh_now`) is triggered whenever structural category changes are detected by the server.
- **Apple Craftsmanship & Polish Standard Lock Badges:**
  - Redesigned the padlock from a 10×13px dot into a prominent, high-contrast 28×24px rounded status badge (`[ 🔒 ]`) featuring concentric 4px corners, a 3px thick shackle, a bold body, and a clean keyhole cutout.
  - **Category Lock Badge:** Renders immediately following the category pill (`[ 1/9 WATCH ] [ 🔒 ]`).
  - **Panel Lock Badge:** Renders beside the sub-item pill (`[ 🔒 ] [ 1/2 ]`) or in the right status corner.
- **Rocker Switch Hardware Hardening & Anti-Chatter:**
  - Added software crosstalk suppression (`last_ok_press_ms` filter) to ignore mechanical contact bleed when pressing the dial in (preventing inadvertent rotate-left or rotate-right triggers).
  - Center dial push (`key_ok`) now triggers instantly `on_press` with a robust 30ms symmetric debounce filter, eliminating dropped clicks or timeouts from firm presses.
  - Symmetrical 750ms threshold across `key_top` and `key_bottom` eliminated button click "dead zones."
  - When in sub-item mode, categories with a single page automatically fall back to category navigation instead of stalling.
- **Periodic Scheduled Refetching:**
  - Ensured that sensor data refetches on the scheduled interval (`panel_refresh_interval`) whether the panel is actively auto-rotating or pinned on a specific card.

## 0.8.15
- **Structured Footer Navigation & Dynamic Focus Inversion:**
  - Shifted category title and counter closer to the system clock on the left (e.g. `14:40  [ 1/5 LIVING ROOM ]`).
  - Added sub-item counter towards the right of the screen (e.g. `[ 1/4 ]`) for categories with multiple items.
  - Active selection is indicated by Apple-grade solid inversion (solid black pill with crisp white text):
    - **Category Mode (default):** Category pill is inverted, signaling that turning the rotary dial steps through categories.
    - **Sub-Item Mode (when dial is clicked):** Category pill reverts to outline, and Sub-item pill becomes inverted, signaling that turning the dial steps strictly through sub-items inside that category.
    - Clicking the dial again toggles focus back to Category mode.
- **Orientation-Aware Hardware Button Actions:**
  - Dynamic pin mapping based on orientation:
    - **Physical Top Button (GPIO 1 on 180° mounts / GPIO 2 on 0° mounts):** Short click (<600ms) toggles **Category Lock**; Long hold (>1000ms) toggles **Panel Lock**.
    - **Physical Bottom Button (GPIO 2 on 180° mounts / GPIO 1 on 0° mounts):** Short click (<600ms) instantly resets back to **Page 1 (Category 1)**; Long hold (>1000ms) forces an immediate network refetch from Home Assistant.
- **Relocated Status Badges from Canvas to Footer Chrome:**
  - Moved the exact slide lock padlock (`pinned`) and category lock badge (`cat_pinned`) into the uneditable 32px footer bar, liberating the top-right canvas area so cards and headers never get occluded.
  - Category lock renders right beside the category pill; Panel lock renders beside the sub-item pill (or right margin).
- **Activity Watchdog & Anti-Freezing:**
  - Any button press or dial turn resets the panel activity watchdog (`idle_sec = 0`), guaranteeing the user their full refresh interval of uninterrupted viewing without the screen suddenly rotating away.
  - Background network image fetches and display updates are suppressed while the user is actively interacting (`idle_sec <= 30`), completely eliminating dial input lag and screen freezes.
  - Debounced screen redraw to 80ms restart, giving buttery-smooth dial responsiveness without e-paper thrashing.

## 0.8.14
- **Orientation-Aware Pin Badges & Rocker Button Inversion (180° / 270° Mounts):**
  - Padlock indicator (`pinned`) and Category Pin badge (`cat_pinned`) are now dynamically mapped to physical screen coordinates and drawn right-side up in the viewer's visual top-right corner, eliminating inverted or clipped badges on 180° mounts.
  - Rocker dial GPIOs (`4` and `6`) are automatically swapped in the ESPHome configuration for 180° mounts so rotating clockwise/right advances forward regardless of board inversion.
- **Dynamic Jinja Decimal Precision for Number Elements:**
  - `_fmt_number()` now respects custom Jinja template decimal formatting when templates dynamically switch between whole integers and floating point units (e.g. Watts to Kilowatts).

## 0.8.13
- **Universal Clipboard Fix (HTTP, HTTPS, & Ingress iFrames):**
  - Resolved clipboard copying failures where `navigator.clipboard` was undefined in non-secure HTTP contexts (`http://homeassistant.local:8123` or IP access) or blocked by Ingress iframe security policies.
  - Added synchronous `document.execCommand('copy')` fallback with direct DOM element selection and off-screen textarea buffers, guaranteeing that user gesture tokens are never discarded across asynchronous network boundaries.
  - Added tactile feedback to all copy buttons (`Copy key`, `Copy OTA password`, `Copy YAML`, `Copy secrets.yaml`), flashing `✓ Copied!` with subtle emerald highlight and displaying toast confirmations.
  - Added dedicated `Copy` button for the OTA password field.
  - Added automatic change detection across all panel setup inputs (`cfg_dev`, `cfg_host`, `cfg_port`, `cfg_ssid`, `cfg_pw`, `cfg_otapw`) so generated YAML stays perpetually up-to-date.

## 0.8.12
- **2D Hierarchical Navigation (Categories $\times$ Sub-Items):**
  - Expanded multi-item cards (`flight_tracker` with multiple aircraft overhead, `sports_match` with multiple scoreboard games, and `watch` with multiple queued episodes like *Scrubs* and *Brothers*) into consecutive sub-slices in the local PSRAM strip.
  - Implemented intuitive 2D category and sub-item mapping:
    - **Rotary Dial (Rotate Left / Right, GPIO 6 / 4):** Switches **only between Categories** (e.g. Solar $\leftrightarrow$ Weather $\leftrightarrow$ Watch $\leftrightarrow$ Scores $\leftrightarrow$ Flights $\leftrightarrow$ Cat). Users never have to scroll through 20 NBA games or 5 flights just to see the weather or cat!
    - **Dial Center Push (GPIO 5):** Short click (<500ms) steps through **sub-options within that category** (e.g. Knicks v Raptors $\rightarrow$ Bulls v Bucks; or Flight 1 $\rightarrow$ Flight 2 $\rightarrow$ Flight 3; or Scrubs $\rightarrow$ Brothers) with instantaneous partial refreshes (~300ms) directly from local PSRAM.
    - **Dial Long Push (>1000ms):** Toggles **Category Pin** (`cat_pinned`). The panel displays an Apple-polish category badge and locks the automatic interval timer to rotate *only* through sub-items inside that category (e.g. auto-cycling tonight's NBA games).
    - **Menu Button (GPIO 2):** Short click (<500ms) toggles **Item Pin** (`pinned`, lock icon appears, freezing on that exact item). Long hold (>1000ms) forces an immediate network refetch from Home Assistant.
    - **Exit Button (GPIO 1):** Unpins all and resets to Home (Category 0, Page 0).
- **Home Assistant Real-Time Category Sensors & API Actions:**
  - Automatically publishes `sensor.epaper_category_count`, `sensor.epaper_category_offsets`, `sensor.epaper_category_sizes`, and `sensor.epaper_category_names` to Home Assistant.
  - Added ESPHome actions `show_category`, `category_step`, `sub_step`, and `category_pin_toggle`.
  - Added `GET /api/manifest` and `GET /manifest.json` endpoints serving complete 2D category geometry.
- **Dynamic Radar & Scoreboard Pagination:**
  - Radar scope targeting reticle `[ ✈ ]` dynamically tracks the selected aircraft across sub-items.
  - Added concentric pagination pills `[ 1/3 ]`, `[ 2/3 ]` to flight telemetry and sports scoreboards, plus clear footer labels (`WATCH · 1/2`, `SCORES · 2/5`).

## 0.8.11
- **Circular PPI Radar Scope & Multi-Style Flight Tracker:**
  - Added tactical circular Plan Position Indicator (PPI) radar scope with outer boundary ring, intermediate range ring, cardinal tick marks (N, E, S, W), range scale badge, home reticle, and directional aircraft blips with callsign tags and target lock brackets (`[ ✈ ]`).
  - Added `radar style` selector to the Flight Tracker inspector:
    - `card` (default): The full-width 4-column telemetry card (preserved 100%).
    - `split`: Tactical circular PPI radar scope on the left + compact 3-column flight telemetry cards on the right.
    - `radar`: Dedicated circular PPI radar scope.
  - Added `flight_radar` preset ("Overhead PPI Radar & Telemetry") with automatic dynamic activation (`tier: "when"`).
- **Formula 1 & Motorsports Live Pit-Wall Tracker (`sports_racing`):**
  - Live pit-wall leaderboard rendering Top 10 driver positions, driver acronyms (`VER`, `NOR`, `HAM`), constructor names, live gaps (`LEADER`, `+2.1s`), tyre compound badges (`[S]`, `[M]`, `[H]`), and session lap counts (`LAP 42/53`).
  - Integrated off-week & pre-race schedule card featuring racing helmet glyph, circuit full name, city, and session start countdown.
  - Published `sensor.f1_status` (`PRE`, `IN`, `POST`) to Home Assistant with event name, circuit, and detail attributes for 1-click dynamic page tier gating (`tier: "when"`).
- **Live Sports Match Scoreboard (`sports_match`):**
  - Head-to-head live scoreboards for Soccer (Premier League, UEFA Champions League, La Liga, Serie A, Bundesliga), Basketball (NBA), NFL, MLB, and NHL.
  - Prominent typography for team names, huge centered score numbers (`2 — 1`), match clock / period badge (`74' · 2ND HALF`, `FINAL`, `Q3 8:12`), team records, and bottom scorers/events ticker.
- **Dual Engine Architecture (Approach A & Approach B Hybrid):**
  - **Approach A (Home Assistant `ha-teamtracker`):** If an entity is specified (e.g. `sensor.arsenal`, `sensor.boston_celtics`, `sensor.f1`), state, clock, scores, venue, down & distance, and last play are extracted directly from Home Assistant.
  - **Approach B (Public Scoreboard Feeds):** Zero-config fallback to public ESPN and OpenF1 APIs when no Home Assistant entity is configured. Allows users to simply choose a league and optional team name (e.g. `Premier League` + `Arsenal`) to start tracking live scores instantly.

## 0.8.10
- **Weather Forecast API Unwrapping & Precipitation Chance:**
  - Resolved Home Assistant REST API envelope quirk (`{"response": {eid: ...}}`) so `weather.get_forecasts` daily forecast items and High/Low ranges populate instantly.
  - Added precipitation probability (`% rain`) and precipitation volume (`mm`) indicators to both the current conditions chips and multi-day forecast strip.
  - Dynamically scaled chip font hierarchy to preserve breathing room from dividers.
- **Multi-Calendar Family Scheduling & Badges:**
  - `fetch_calendar_events` now supports comma-separated entity IDs (e.g. `calendar.personal, calendar.work, calendar.family`).
  - Fetches from all specified calendars concurrently, tags events with calendar source badges (e.g. `WORK`, `PERS`), deduplicates, and sorts chronologically.
  - Renders subtle outlined calendar origin badges on each agenda item.
- **Multilingual Font Fallback Chains:**
  - Installed Alpine Unicode font packages (`font-noto`, `font-noto-cjk`, `font-noto-arabic`, `font-noto-hebrew`, `font-dejavu`).
  - Added intelligent script detection in `theme.py` that transparently routes Cyrillic, Greek, Hebrew, Arabic, and CJK (Chinese, Japanese, Korean) characters through appropriate native glyph sets without rendering missing glyph tofu boxes (`□`).
- **MQTT Auto-Discovery & REST Control Actions:**
  - Publishes Home Assistant MQTT Auto-Discovery entities: `button.epaper_panel_refresh` (instant refresh and panel push) and `sensor.epaper_panel_last_render` (live render timestamp).
  - Added REST action endpoints `POST /api/action/refresh` and `POST /api/action/page` for easy integration with standard Home Assistant automations and webhooks.
- **Linux & Battery E-Ink Client Daemon:**
  - Added `client/linux/epaper-daemon.sh` with strict conditional `If-None-Match` ETag caching.
  - Automatically aborts screen refresh and redraw on `HTTP 304 Not Modified`, allowing battery e-readers (Kindle, Kobo, Android Termux, Raspberry Pi Zero) to go back to sleep in <100ms.

## 0.8.9
- **Monthly Wall-Calendar View (`calendar_month`):**
  - **Full Month Matrix:** A classic paper wall-calendar view showing days of the month aligned under days of the week, allowing you to easily look up what date falls on a Friday two weeks from now or what day the 26th is.
  - **High-Contrast Today Inversion:** Today's date leaps out instantly with a solid black circle/squircle and bold white text.
  - **Scheduled Event Indicators:** Link any Home Assistant `calendar.*` entity to automatically render neat event indicator dots under dates with scheduled events.
  - **Configurable Preferences:** Toggle headers, weekday names (`MON TUE...` vs `M T...`), first day of the week (Monday or Sunday), and optional card border.
- **Calendar & Upcoming Agenda (`calendar_agenda` & Combo Preset):**
  - **Upcoming Events List:** Displays upcoming events with inverted date pills (`TODAY 19:30`, `TOMORROW`, `TUE 20 OCT`), bold event summaries, and location or time subtitles.
  - **Calendar & Agenda Combo Preset:** A ready-made 1-click preset that places the month grid on the left and the upcoming agenda on the right for a complete command center.
- **Weather Conditions & 4-Day Forecast (`weather_forecast`):**
  - **Hero Current Conditions:** Renders large MDI weather condition icons (`mdi:weather-rainy`, `mdi:weather-sunny`, `mdi:weather-partly-cloudy`, etc.), prominent temperature readout, condition description, and compact pill badges for humidity, wind speed, and today's high/low.
  - **Multi-Day Forecast Strip:** Shows day names, crisp weather glyphs, high/low temperatures, and precipitation amount.
  - **Adaptive Geometry:** Automatically renders in split columns in landscape ($w \ge 480\text{px}$) and seamlessly transitions into stacked rows in portrait orientation ($416\times 792$) or compact widgets.
- **Live Overhead Aircraft Tracker (`flight_tracker`):**
  - **Live Airspace ADS-B Radar:** Tracks commercial and private aircraft flying overhead within a configurable radius (e.g. 35 km) around your home using OpenSky Network data.
  - **Flight Information:** Displays large callsign (e.g. `BAW71LK`, `THY41Y`), airline/country of origin, distance and compass direction (`8.4 KM SW`), altitude (in feet and meters with climb/descent arrows `↑`/`↓`/`→`), ground speed (kts and km/h), heading, and ADS-B ICAO transponder code.
  - **Automatic Airspace Sensors for Home Assistant:** Automatically publishes `sensor.overhead_aircraft_count` and `sensor.closest_aircraft` to Home Assistant.
  - **Automatic Dynamic Screen Surfacing:** Pair with page tier **Show only when active** (`show_if: "{{ states('sensor.overhead_aircraft_count') | int(0) > 0 }}"`) so the flight radar page automatically joins rotation only when an aircraft enters your local airspace, and recedes when the sky is clear.
- **Quick-Add Palette & Preset Library:**
  - Added dedicated one-click buttons for Month View, Agenda, Weather, and Flights in the editor's Add Element palette.
  - Added 4 ready-to-use page presets with custom vector icons in the Presets library.

## 0.8.8
- **Apple-Grade Header & Toolbar Redesign:** Restored a clean, spacious, and uncluttered layout to the top navigation bar.
  - **Grouped Toolbars:** Grouped 17 sprawling individual controls into 4 logical zones: *Brand*, *Page Navigation*, *Canvas Tools*, and *Status & Output Actions*.
  - **Page Actions Menu (`•••`):** Replaced repetitive page buttons with a compact popover menu containing *Duplicate Page*, *Rename Page*, and *Delete Page*.
  - **Settings Menu (`⚙️`):** Secondary administrative options (*Panel Setup & Firmware*, *Data Sources*, and *Dark/Light Theme*) now tuck neatly into an unobtrusive settings popover.
  - **Clear Primary Call to Action:** Replaced ambiguous double-save buttons with a single high-contrast **Push to Panel** action that automatically saves and renders in one click.
- **Hardware Page Rotation Timing (`X-Rotate-Seconds`):**
  - **Cycle Interval Selector:** Added an explicit **`Cycle interval`** dropdown (`15s`, `30s`, `45s`, `1 min`, `2 min`, `5 min`, or `Manual`) right inside the **Active Rotation** strip.
  - **Dynamic HTTP Timing Headers:** The server now emits `X-Next-Refresh-Seconds`, `X-Rotate-Seconds`, and `X-Page-Count` response headers on every `/frames.png` and `/frame.png` fetch, allowing hardware to dynamically adjust its cycle cadence and deep-sleep timers without requiring firmware reflashes.

## 0.8.7
- **Dynamic Multi-Row Grid Scaling (2×2, 2×3, 2×4…):** Dynamic Grid is no longer restricted to 4 spots or squished into a single crowded row when monitoring 5+ devices.
  - **Balanced 2D Matrices:** When monitoring 5 or 6 items, the display automatically arranges into an elegant 2×3 grid in landscape (or 3×2 in portrait). When monitoring 7 or 8 items, it flows into a balanced 2×4 grid.
  - **Dynamic Last-Row Balancing:** When odd numbers of items are active (e.g. 5 active zones), the trailing row automatically stretches and balances its cards evenly across the screen width rather than leaving awkward empty holes.
  - **Single Row/Stack Option:** Users can switch between `Balanced Grid` and `Single Row / Stack` via the new `layout` selector in the inspector.
- **Large Icons & "Icons Only" Mode:**
  - **Clean "Icons Only" View:** Added a `show` mode selector (`Icon + Name + Secondary Tag`, `Icon + Name Only`, or `Icons Only`). In `Icons Only` mode, cards suppress all text and display huge, crisp glyphs centered inside Apple squircle cards with high-contrast active state badges.
  - **Manual Icon Sizing:** Added an `icon size` selector (`Auto`, `Medium (48px)`, `Large (64px)`, `Huge (80px)`) giving users direct control over glyph presence across their layout.
  - **Per-Spot Text Suppression:** Individual spots can now have their text hidden independently via a `Hide text` checkbox, enabling hybrid screens where primary spots have names while secondary spots show minimalist icons.
- **Dynamic State-Based & Off Icons:**
  - **Visual Off / Inactive Icon Picker:** Every spot now provides a dedicated `off icon` field and visual picker alongside the active icon.
  - **Smart Automatic State Fallbacks:** When entities transition to off or idle states, common icons automatically transform (e.g., `mdi:lightbulb` $\to$ `mdi:lightbulb-off`, `mdi:radiator` $\to$ `mdi:radiator-disabled`, `mdi:lock` $\to$ `mdi:lock-open`, `mdi:power` $\to$ `mdi:power-off`).
  - **Multi-State Support:** Supports custom state mappings (e.g., heating, cooling, idle, off) displaying corresponding state badges (`HEAT`, `IDLE`, `OFF`) and matching icons.

## 0.8.6
- **Proactive Server-Side Push for Hardware Refresh Slider:** The editor toolbar's **Panel Refresh** slider (1–60 min) now actively drives physical panel refreshes directly over Home Assistant's native ESPHome API.
  - **Works Immediately Without Reflashing Firmware:** Previously, changing the slider only updated an internal JSON field and attempted to set a Home Assistant number entity that didn't exist on hardware running initial firmware (which had a fixed 5-minute loop hardcoded). The add-on now actively commands the panel (`esphome.<device>_page_step` and `esphome.<device>_refresh_now`) according to your selected interval.
  - **Instant Visual Feedback:** Moving the slider triggers an immediate pre-render and refresh push to the physical panel on the spot, resetting the ticker loop to the new cadence.
  - **Multi-Slug Entity Syncing:** Attempts live updates across both `crowpanel_epaper` and `e_paper_panel` number entity namespaces for seamless compatibility with reflashed nodes.

## 0.8.5
- **Live Reactive "Show Only When Active" Condition Syncing:** The page condition (`show_if`) is now seamlessly and automatically populated with the exact entities configured across your dynamic grid spots.
  - **Zero Manual Jinja Editing:** As you type, paste, or select entities from Home Assistant autocomplete into any spot (Spot 1, Spot 2, Spot 3, Spot 4), the page's condition bar (`{{ is_state('entity_1','on') or is_state('entity_2','on') ... }}`) updates reactively in real time.
  - **Dynamic Entities Preset Tier: "when":** The "Dynamic Entities" preset now defaults to `tier: "when"` ("Show only when active") as intended, but with clean entity bindings rather than broken dummy zones.
  - **Automatic Legacy Dummy Entity Cleanup:** Simply opening or selecting any page containing a dynamic grid instantly updates its `show_if` to match the real configured spots, purging any leftover dummy `switch.zone_X` placeholders.
  - **Safe Spot State Handling:** When spots are initially blank or during page configuration, the page remains visible until monitored entities are configured and evaluated, preventing newly added pages from disappearing before you finish setting them up.

## 0.8.4
- **Visual Icon Picker for All Spots & Elements:** Selecting icons no longer requires memorizing or manually typing `mdi:...` names.
  - Every icon field across the editor—including standard **Icon** elements, **Dynamic Grid Header Icon**, and **Dynamic Grid Spots**—now features an interactive visual preview button rendering the actual glyph, alongside a convenient `Browse…` button.
  - Clicking any icon button opens an Apple-grade visual icon picker dialog.
- **Instant Search Across 7,000+ Material Design Icons:** Added an optimized client-side search engine backed by the full MDI codepoint registry, providing zero-latency 60fps search results with live glyph previews.
- **Quick-Category Chips:** Added curated category chips to the icon picker modal for one-click access: `Popular`, `🐱 Cat & Pets`, `🐾 Paw`, `♨️ Heating`, `🛏️ Bed & Furniture`, `⚡ Power`, `💡 Lights`, `🏠 Home`, `☀️ Weather`, and `🌡️ Climate`.
- **Intelligent Entity-to-Icon Auto-Suggestion:** Binding an entity to a spot in the Dynamic Grid inspector automatically suggests relevant icons based on the entity domain and name (e.g., cat/paw blankets automatically assign `mdi:paw` or `mdi:radiator`; lights assign `mdi:lightbulb`; switches assign sockets/power), while preserving manual overrides.

## 0.8.3
- **Auto-Save on Push & Full Strip Preview:** Clicking **Push to panel** or opening the **Full strip** modal now automatically commits and renders your latest canvas layout changes first, ensuring new pages, element modifications, and spot bindings are immediately included in the generated `/frames.png` strip and pushed to the physical display without having to remember to click "Save Changes" beforehand.
- **Dynamic Entities Preset Rotation Default:** The "Dynamic Entities" preset now defaults to `rotate` tier ("Always in rotation"), preventing newly created pages from being inadvertently hidden from rotation and the strip when monitored entities are initially off.
- **Dynamic Grid Auto-Hide & Real-Time Sync:** Added a dedicated **"Hide page when all spots off"** toggle to the Dynamic Grid inspector. Toggling it automatically manages the page's conditional `show_if` expression in real time, keeping the entity list synchronized whenever spots are added, edited, or removed.
- **Rotation Bar Visual Transparency:** Enhanced rotation pill badges to clearly indicate whether a conditional page is currently `live` (condition active, present in strip) or `idle (skipped)` (condition false, temporarily omitted from the rotation strip until an entity turns on).

## 0.8.2
- **"Dynamic Entities" Adaptive Multi-Spot Grid Element:** Added an intelligent `dynamic_grid` element designed for monitoring multiple related devices or zones (e.g. 1 to 4 heating blankets, radiators, climate zones, or lights) where only entities currently `on` (or matching a chosen state) are displayed:
  - **Dynamic Canvas Scaling (1 to 4 spots):** Automatically redistributes available screen area based on the number of active entities:
    - **1 Active:** Full-width hero card featuring a large icon, bold title, and prominent `ACTIVE` status badge.
    - **2 Active:** Balanced dual-card split (side-by-side columns in landscape, stacked cards in portrait).
    - **3 Active:** Trio card layout with clean icon anchors, bold spot labels, and runtime subtitles.
    - **4 Active:** Toggleable between a **2×2 Quadrant Grid** (balanced, high-legibility cards) and **4 Columns / Stack**.
  - **Customizable Spot Details:** Each monitored spot supports an entity ID, custom display name override (falling back to Home Assistant's friendly name), custom Material Design or custom icon, and a customizable secondary tag (`runtime` for "on for Xm", raw `state`, or `none`).
  - **Optional Header & Live Active Badge:** Optional header title (e.g. "Active Blanket Zones") and icon (e.g. `mdi:cat` or `mdi:lightning-bolt`), featuring a live active badge pill (`[ 2 / 4 ON ]`).
  - **Automatic Rotation Skip (`tier: "when"`):** When configured with `show_if`, the entire page is automatically bypassed during panel rotation when 0 entities are active, popping into view only when at least one entity turns on. If rotated while idle, it displays a calm, centered standby card.
- **"Dynamic Entities" Preset:** Added a ready-to-use "Dynamic Entities" screen template to the preset library (`Add Preset`) with preconfigured 4-zone monitoring and conditional rotation skip.
- **Orientation Reflow & Editor Inspector Integration:** Full support in the visual editor for adding dynamic grids, configuring spots, dragging/resizing, and automatic layout reflow between Landscape and Portrait orientations.

## 0.8.1
- **Apple-Grade Adaptive Layout Reflow:** Completely redesigned the Portrait ↔ Landscape reflow engine. Rather than naively squishing elements into a left-aligned vertical stack at `x = 20`, the new semantic engine detects element roles (Hero Stat, Visual Anchor / Icon, Subtitle, Trend Curve, Dividers) and creates a balanced, publication-grade layout:
  - **Portrait (272×792):** Horizontally centers hero icons (`90×90 px`), centers and sizes primary numbers and status readouts with units, pairs subtitles beneath stats, expands 24h trend curves across the full card width (`w: 240, h: 140-150 px`), converts side-by-side comparisons (e.g. Indoor vs. Outdoor temperature) into vertically stacked cards with horizontal dividers, and vertically balances the layout within the safe area.
  - **Landscape (792×272):** Restores the clean panoramic three-column hierarchy with left-column icons, center-left hero readouts and subtitles, and right-column trend curves and secondary statistics.
- **Zero-Reflash Live Hardware Refresh Slider:** Added an interactive refresh interval slider (1–60 min) directly into the editor stage toolbar and synchronized with Home Assistant's `number.<device>_refresh_interval` template entity. Adjusting the slider updates the physical panel's ticker loop on the fly without reflashing firmware.
- **LAN Host Port Auto-Detection & Custom Port Support:** Added automatic detection of external host-mapped ports via the Supervisor API (resolving LAN port 8099 conflicts with other add-ons such as Diivoo2MQTT) and added a dedicated **Port** field to the `Panel setup` wizard.

## 0.8.0
- **Multi-Model CrowPanel E-Paper Family Support:** Added built-in display profiles for the entire Elecrow CrowPanel E-Paper lineup:
  - `CrowPanel 5.79"` (`DIS08792E`, 792×272 px, 139.1×47.7 mm) — Primary & tested hardware default
  - `CrowPanel 4.2"` (`DIS08042E`, 400×300 px, 84.8×63.6 mm)
  - `CrowPanel 2.9"` (`DIS08029E`, 296×128 px, 66.9×29.1 mm)
  - `CrowPanel 7.5"` (`DIS08075E`, 800×480 px, 163.2×97.9 mm)
  - `CrowPanel 10.2"` (`DIS08102E`, 960×640 px, 215.0×143.4 mm)
- **Dynamic Hardware Model Selector:** Choose your display model in the editor toolbar or inside the `Panel setup` wizard. The editor updates the canvas aspect ratio, hardware bezel branding, safe-zone footer height, and pinned padlock boundaries in real time.
- **Model-Specific ESPHome Firmware Generation:** The `Panel setup` firmware wizard automatically configures drivers, loop dimensions, and component platforms (`crowpanel_epaper` for 5.79" & 4.2"; `waveshare_epaper` for 2.9", 7.5", & 10.2") tailored to the chosen model.
- **Physical DPI-Calibrated Legibility Checking:** Text physical millimeter sizes and viewing distance verdicts (`Desk 0.8m`, `Bedside 1.5m`, `Sofa 3.0m`, `Wall 5.0m`) scale accurately to the active model's millimeter width and pixel density.
- **Adaptive Footer & Orientation Reflow:** Built-in footer rule lines, clock/battery placement, and orientation reflow logic dynamically adapt to each screen model's native resolution and margins.

## 0.7.1
- **Typography & Font Picker:** Added font family selector (`Lato`, `DejaVu Sans`, and `Roboto Mono`) and weight control (`Bold` / `Regular`) for text and numeric elements, rendered via bundled TrueType fonts in PIL and previewed via web `@font-face`.
- **Persistent Advanced Pixel Coordinates:** The `Advanced Pixel Coordinates` inspector panel now remembers its expanded/collapsed state in `localStorage` across element selections and drag operations.
- **Page Duplication & Renaming:** Added `Duplicate` and `Rename` buttons to the page controls bar, allowing instant page cloning and in-place renaming with full rotation sequence updates and Undo/Redo history.
- **Customizable Viewing Distance & Legibility Check:** Replaced static 3m check with a configurable viewing distance selector (`Desk 0.8m`, `Bedside 1.5m`, `Sofa 3.0m`, `Wall 5.0m`, or `Disabled`), dynamically scaling font size thresholds and suppressing noise when disabled.
- **Refined Aesthetics & Emoji Restraint:** Removed decorative emojis from headers, select options, badges, and modals while keeping functional iconography strictly in domain filter chips and the element palette; replaced preset modal icons with crisp SVG vectors.
- **Generic Screen Presets & Entity Safety:** Replaced specific pension presets and arbitrary calendar entity auto-binding with a clean, generalized `Event & Schedule Countdown` preset with safe placeholder entity slots.

## 0.7.0
- **✨ One-Click Ready-Made Page Presets:** New preset library modal (`Add Preset`) featuring one-click screen templates designed for 3-metre sofa viewing: `Next Pension / Event Countdown`, `Room Climate & Comfort`, `Solar Power & Generation`, `Pet & Door Presence`, `Bin Day Waste Reminder`, and `Giant Sofa Clock & Date`. Each preset automatically configures iconography, element sizes, and entity bindings.
- **🎨 Modern Home Assistant Lovelace Dark & Light Theme:** Complete visual redesign with Inter typography, rich dark surfaces, high-contrast borders, tactile button micro-animations, an instant one-click `🌙 / ☀️` theme toggle, and an authentic CrowPanel hardware frame preview with Fit vs 100% zoom controls.
- **🏷️ Intelligent Entity Browser & Filter Chips:** Browse entities by domain category chips (`📅 Dates`, `🌡️ Sensors`, `⚡ Binary`, `❄️ Climate`, `🔒 Security`, `👤 People`), with friendly name prominence, live state pills, and instant one-click `➕ Add to Page` buttons alongside drag-and-drop.
- **Plain-English Countdown & Calendar Bindings:** Added native support for `show: "days_until"` (calculating days remaining until a future date or calendar event start), `show: "date_formatted"`, and `show: "calendar_title"`.
- **Modern Web Accessibility & Interaction Polish:** Applied `overscroll-behavior: contain` to prevent background scroll chaining during modal dialog interactions, added `Escape` key dialog dismissal, and enhanced canvas dragging with primary-button validation and pointer capture safety.

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
