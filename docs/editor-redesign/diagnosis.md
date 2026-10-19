# Where the editor's flow breaks

Read with [inventory.md](inventory.md). The clickable mockups of the three
directions are in [mockups.html](mockups.html) (published as a private
artifact for viewing).

## The concepts are scattered

The editor has four things to work on: **the panel**, **the rotation**,
**a page**, **an element**. Today each lives in several places, and the same
control often exists twice.

| Concept | Where it lives today |
|---|---|
| The panel | Top bar (orientation, quiet pill, status pill, gear menu), canvas toolbar (model, refresh slider, legibility), Panel setup (model again, mount again, refresh again), Quiet hours dialog |
| The rotation | Below the canvas (pills, ‹ › one step per press, interval, add slot), the page select's `[when]` tags, Full strip dialog |
| A page | Top bar (select, preset, blank, ••• menu), below the canvas (tier, condition, hold), rotation pills |
| An element | Canvas, inspector (top of the rail), palette (middle), entities (bottom) |

The page list and the rotation are two pictures of one thing. Model,
orientation and refresh interval each have two controls in two places.

## Saving is invisible

Only **Push to panel** is meant to save, but six other actions save the
whole spec as a side effect, including simply opening Full strip. There is no
unsaved-changes mark and no warning when you close the tab. Two tabs save over
each other without a word (frustration C).

## The canvas doesn't do what the hand expects

- **A.** A click goes to the topmost *box*, transparent parts included, so a
  card or a roomy text box blocks what's inside it. Depth moves one step per
  press and the order is never shown.
- **B.** Any movement during a click is a drag: the element moves 1–2 px and
  an undo step is recorded.
- Only one resize handle (bottom-right).

## The inspector has no levels

A widget's inspector is one long column (flights: 15 rows) with no
progressive disclosure. Labels mix lowercase (`show as`, `if error`,
`app sensor`), Title Case and ALL CAPS, and some name the machinery
(`Custom Jinja`, `Hardware Model`, `Zero-Ghosting Deep Idle`).

## Phone

Below 1020 px everything stacks: canvas, three bars, then the inspector far
below, so editing means scrolling away from what you're editing. The top bar
wraps to three rows.

## Five core tasks, walked today

My reading of the daily path, to be corrected by the user. Actions are
clicks, drags and fields; places are distinct areas or windows you have to
look at.

| Task | Today | Actions | Places |
|---|---|---|---|
| 1. New page from a preset, bound to my sensor, on the panel | Preset → read 15 long cards → pick → browser prompt for an id → page arrives **unbound** → find the widget → find the entity field → type the id → Push | 8 + typing two ids | 5 |
| 2. Change something under a card on a busy page | Click (gets the card) → layer down × n with the order hidden, or open exact position and type numbers; each click may nudge it | 3 + n | 3 |
| 3. Add a sensor value to a page | Scroll the rail to Entities → search → drag or + → set unit and decimals → read the chip | 5 | 3 |
| 4. Make page B match page A's layout | No feature. Two tabs, read four numbers per element in one, type them in the other; the last tab to save silently wins | 8 per element | 2 windows |
| 5. Show a page only while the dryer runs, right after the cat page | Page select → tier → entity, operator, value → rotation ‹ › one step per press → Push | 6 + steps | 3 |
