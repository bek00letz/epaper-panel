# The AI usage reporter

A small program for your own computer, Mac, Linux or Windows. Every 5 minutes it reads how much of
your AI plans you've used, from what the apps already keep on your computer, and sends just those
numbers to your e-Paper Panel add-on. An AI usage page shows them as calm bars, and each number is a
sensor in Home Assistant too.

It reads:

- **Claude Code**: the 5-hour session and the weekly limit (what `/usage` shows), and, behind a
  Claude apps gateway, your spend limit; plus today's tokens, sessions, cache share and your streak.
- **Codex** (OpenAI's Codex CLI and app): its 5-hour and weekly limits, and a model's own when
  Codex names it; plus today's tokens and sessions.

Only the numbers leave your computer: no file, folder name, prompt or key. They go to your add-on
and nowhere else; there's no account and nothing is tracked. The contract it sends in is
[docs/ai-usage.md](../docs/ai-usage.md).

## Setting it up

In the add-on's editor, open **Settings › AI usage** (or **New page › AI usage**) and choose
**Connect a computer**. Pick Mac, Linux or Windows, copy the command, and paste it into Terminal
(PowerShell on Windows). That's all: it connects with a code that works once for ten minutes, keeps
its key in your computer's own key store, and starts reporting.

It needs Python 3.9 or later and nothing else. On a Mac that's the one that comes with the Command
Line Tools (`xcode-select --install` if your Mac asks); on Windows, python.org's.

From a checkout of this repository, `./setup.sh --address <address> --code <code>` does the same
without downloading anything.

### What setup changes on your computer

| | Mac | Linux | Windows |
|---|---|---|---|
| Its folder | `~/Library/Application Support/e-Paper Usage Reporter` | `~/.local/share/epaper-usage-reporter` | `%LOCALAPPDATA%\e-Paper Usage Reporter` |
| Its key | the Keychain | your desktop's key store (`secret-tool`), or a file only you can read where there's none | a file Windows encrypts for your account (DPAPI) |
| What runs it | a LaunchAgent, `local.epaper-panel.usage-reporter` | a systemd user timer, `epaper-usage-reporter.timer` | a Task Scheduler task, "e-Paper Usage Reporter" |
| Its log | `~/Library/Logs/e-Paper Usage Reporter.log` | `reporter.log` in its folder | `reporter.log` in its folder |

**Claude Code's status line.** Claude Code shares its limits only with a status line command, so
setup puts the reporter's in `~/.claude/settings.json` (`statusLine`). If you had one, it still runs
and shows what it showed: the reporter's only saves the limits on the way. If you had none, you get
a short one: the model and your limits. A backup of the file is kept beside it
(`settings.json.before-epaper-usage`), and a settings file that isn't valid JSON is never rewritten:
setup says what to add instead. `--no-status-line` leaves it alone, and then only the extras are
read. Limits update whenever Claude Code does, so a Mac that's been asleep reports the last ones,
with when they were read.

## Using it

```bash
python3 "<its folder>/app/run.py" show       # what it would send, in plain words; sends nothing
python3 "<its folder>/app/run.py" status     # connected, scheduled, and how the last report went
python3 "<its folder>/app/run.py" report     # send now
python3 "<its folder>/app/run.py" uninstall  # stop, forget the key, give Claude Code its status line back
```

To stop reading one app, add `"readers": {"codex": {"off": true}}` to `config.json` in its folder.
To name its account on the page, `"readers": {"claude": {"account": "Work"}}`.

Removing it in the editor's Settings › AI usage stops its key at once; `uninstall` removes it from
the computer.

## Adding a provider

One module in `epaper_usage/readers/`, with `ID`, `NAME` and `read(ctx)` returning a
`shape.Provider` (or `shape.Skipped` when the app isn't there). Nothing else in the reporter, and
nothing in the add-on, names a provider. Give it saved sample files in `tests/samples/` (never
anyone's real ones) and a test in `tests/test_readers.py`. What was checked and why these two:
[docs/ai-usage.md › Readers](../docs/ai-usage.md#readers-and-why-these).

## Tests

```bash
python3 -m unittest discover -s reporter/tests
```

They use only the samples in `tests/samples/` and a throwaway home folder: never your own files,
key store or schedule.
