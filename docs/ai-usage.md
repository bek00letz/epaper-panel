# AI usage: the contract

How much of your AI plans you've used, on a page: each provider's limit
windows as calm bars ("Weekly, 41 %, resets Tue 09:00"), and a few extras
when a provider has them. Two halves, joined by one fixed shape:

- **The reporter** (`reporter/`) runs on your own computer, every 5 minutes.
  Each provider is one small reader that turns what that app keeps on your
  computer into the shape below. Your keys and files never leave it; only
  the numbers do.
- **The add-on** takes the numbers on its device port, keeps the newest per
  window, draws the AI usage page and publishes Home Assistant sensors in the
  same shape, so automations can use them too.

Adding a provider is one reader module in the reporter. The add-on, its
page and its sensors never name a provider.

## The report

`POST /api/usage` on the add-on's device port (port 8099 at home; through
Reaching home away from it), with the reporter's key in `X-EPF-Key`, and a
JSON body of at most 64 KB:

```json
{
  "format": 1,
  "sent_at": "2026-10-30T14:05:12+01:00",
  "reporter": {"app": "epaper-usage-reporter", "version": "1.0", "platform": "macos"},
  "providers": [
    {
      "provider": "claude",
      "name": "Claude Code",
      "account": "",
      "windows": [
        {"window": "session", "hours": 5, "used": 0.235,
         "resets_at": "2026-10-30T16:00:00+00:00", "read_at": "2026-10-30T13:58:40+00:00"},
        {"window": "week", "used": 0.412,
         "resets_at": "2026-11-03T08:00:00+00:00", "read_at": "2026-10-30T13:58:40+00:00"},
        {"window": "month", "amount": 314.12, "limit": 500, "unit": "USD",
         "resets_at": "2026-11-01T00:00:00+00:00", "read_at": "2026-10-30T13:58:40+00:00"}
      ],
      "extras": {"day": "2026-10-30", "read_at": "2026-10-30T14:05:10+01:00",
                 "tokens": 1250000, "sessions": 3, "cache": 0.91, "streak_days": 12}
    }
  ],
  "skipped": [{"provider": "codex", "name": "Codex", "reason": "not_found"}]
}
```

### A provider

| Field | | What it is |
|---|---|---|
| `provider` | needed | Its id: lowercase letters, digits and `_`, at most 24 (`claude`, `codex`). Part of its sensors' names, so it never changes |
| `name` | needed | What a person calls it, at most 40 characters (`Claude Code`) |
| `account` | | Which account or plan, at most 40 characters (`Pro`, `Work`). Never an email address: the reporter leaves it empty unless you name it, or the app itself says its plan |
| `windows` | | Its limit windows, at most 8 |
| `extras` | | A few extras, each optional |

### A window: one set of numbers per provider and limit window

| Field | | What it is |
|---|---|---|
| `window` | needed | `session`, `day`, `week` or `month` |
| `hours` | for `session` | How long a session window is (`5`) |
| `scope` | | What the window counts, when it's narrower than everything: a model's name (`Sonnet`), at most 24 characters. A proper name, so never translated |
| `used` | one of these two | A fraction: 0 is none, 1 is all of it, above 1 is over it |
| `amount`, `limit`, `unit` | | An amount used, out of a limit, in a unit: `314.12` of `500` `USD`. `limit` may be left out (no limit), and then there's no bar. A three-letter currency (ISO 4217) makes it spend; anything else is a count (`messages`, `requests`) |
| `resets_at` | | When it resets: ISO 8601 with its offset. Left out when the provider doesn't say |
| `read_at` | needed | When the reader read it: ISO 8601 with its offset. Not when it was sent: a window read from a file Claude Code wrote an hour ago was read an hour ago |

With `used` and `amount` and `limit` all given, `used` is what counts.

### Extras

All optional, all for one day, `day` (`YYYY-MM-DD`, in the reporter's time
zone), read at `read_at`:

| Field | What it is |
|---|---|
| `tokens` | Tokens used that day, everything counted (input, output, cache reads and writes) |
| `sessions` | Sessions with at least one answer that day |
| `cache` | The share of input that came from the cache that day, 0 to 1 |
| `cost` | `{"amount": 1.20, "unit": "USD"}`: spent that day, as the provider itself counts it. A reader never guesses a price |
| `streak_days` | Days in a row, ending that day or the day before, with any use |

### What's skipped

`skipped` says which readers found nothing, so the editor can say so:
`reason` is `not_found` (the app isn't on this computer), `no_limits` (it is,
but hasn't said its limits yet) or `error` (it couldn't be read; the
reporter's own log says why). Never a path, a file's contents or an error's
text.

## What the add-on answers

- `200 {"ok": true, "windows": 3, "dropped": []}`: kept. `dropped` lists
  what was left out and why, in plain words ("codex weekly: used isn't a
  number"). A report with a bad window keeps its good ones.
- `400` with a plain reason: not JSON, or not this shape at all.
- `401`: no key, or a key the add-on doesn't know. Ten wrong keys in ten
  minutes from one sender and it's refused for ten minutes (`429`).
- `413`: more than 64 KB.

Nothing on this port answers without a key, except pairing (below), and that
only inside the editor's ten-minute window.

## Pairing a reporter

The editor (Settings › AI usage, or New page › AI usage) opens a ten-minute
window and shows a six-letter code and the command to run. The reporter
sends it once:

`POST /api/usage/pair` with `{"code": "K7Q4MZ", "platform": "macos"}` →
`{"key": "…", "id": "2", "name": "Mac"}`.

The code works once, only inside its window. A wrong code counts as a wrong
key. The key goes into the computer's own keychain (the macOS Keychain) and
nowhere else; the add-on keeps it in `reporters.json` (0600). It only sends
usage: it can't fetch a frame, wake a device or read anything. Removing the
computer in Settings › AI usage stops its key at once.

## In Home Assistant

Over MQTT, like every value of the add-on's own, under the "E-Paper Studio"
device. Per provider and window:

- `sensor.epaper_ai_<provider>_<window>`: how much is used, in % (the
  amount, in its unit, for a window with no limit). `<window>` is
  `session_5h`, `day`, `week`, `month`, then `_spend` for money
  (`month_spend`) and `_<scope>` (`week_sonnet`). A provider with several accounts adds the account
  (`epaper_ai_claude_work_week`). Attributes: everything in the window
  (`used`, `amount`, `limit`, `unit`, `resets_at`, `read_at`), and
  `provider`, `provider_name`, `account`, `reporter`.

Per provider, for the extras it has (today's, in Home Assistant's time zone):
`sensor.epaper_ai_<provider>_tokens_today`, `_sessions_today`,
`_cache_today` (%), `_cost_today`, `_streak`.

Per reporter: `sensor.epaper_ai_reporter_<id>`, when it last reported
(a timestamp).

A window that has reset since it was read reads 0 %, with `reset: true`,
until a newer one comes. A report older than a week is let go, and its
sensors with it.

## Several computers

Two computers reporting the same provider and account report the same
limits: the newest reading of each window is the one kept. Extras are each
computer's own day, so they add up: tokens, sessions and cost are summed,
the streak is the longest, the cache share is weighted by tokens.

## Readers, and why these

**Claude Code.** Its limit windows (the 5-hour session, the week, and a
spend limit behind a Claude apps gateway) are what `/usage` shows, and
Claude Code hands them, documented, to a status line command on every update
(`rate_limits` in its status line input: `used_percentage` and `resets_at`
in Unix seconds). Nothing else on disk has them. So setup adds a small
status line that saves just `rate_limits` to the reporter's folder and then
runs the status line you already had, if any, showing what it showed. The
extras come from its session files under `~/.claude/projects/` (each
answer's `usage`, counted once per message and request). The TRMNL recipes
run Claude Code in a hidden terminal and read the `/usage` screen instead:
that starts Claude Code every few minutes and breaks when the screen
changes. A weekly limit for one model (Sonnet) isn't in the status line, so
it isn't reported yet.

**Codex** (OpenAI's Codex CLI and app). Its session files under
`~/.codex/sessions/` record, with each answer, the same windows its server
sent (`rate_limits`: `primary` and `secondary`, each `used_percent`,
`window_minutes` and `resets_at`), and the tokens used. Read as they are,
no key, no network. A model's own limit is reported when Codex names it
(`limit_name`).

**Checked and not picked yet: Gemini CLI.** It keeps no record of its
quota on disk: its `/stats` are for the running session only, and its
daily request limit is only known to Google's servers. Its chats under
`~/.gemini/tmp/` could give tokens, but a page of tokens without a limit
isn't what this page is for. A reader for it can be added when it records
its quota.
