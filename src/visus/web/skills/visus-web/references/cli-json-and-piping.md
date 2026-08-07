# JSON output, exit codes and piping

## Exit codes are the contract

| Code | Meaning |
|---|---|
| `0` | The command succeeded. |
| `1` | The command ran and failed — no session, daemon error, missing target. |
| `2` | Usage error — bad flag, missing value, unknown skill target. |

Branch on the exit code, never on the message text. `visus expect-text` is the
exception by design: it *prints* `PASSED` or `FAILED: <detail>` and still exits
0, so an assertion never aborts a script.

Every daemon-side failure funnels through the same path: `session_client.send()`
catches `SessionError` and the CLI prints `error: <message>` to stdout, then
exits 1. A bad flag or bad type (e.g. `visus press Enter` — one positional
missing, so `Enter` fails int conversion) is caught by Typer/Click before the
daemon is ever contacted and exits 2 instead.

## `--json`

Eight commands emit machine-readable output:

| Command | Shape |
|---|---|
| `visus list-fields --json` | array of field objects (`index`, `kind`, `name`, `code`, `css`, `xpath`, `frame`, `deep`, …) |
| `visus snapshot --json` | array of `{role, name}` |
| `visus tabs --json` | `{"tabs": [{index, title, url, active}]}` |
| `visus session status --json` | the full status object |
| `visus cookies --json` | array of cookie objects |
| `visus eval "<fn>" --json` | the evaluated value as JSON |
| `visus find-image t.png --json` | `{found, x, y, confidence}` |
| `visus translate '<el>' --json` | selectors + ordered candidates |

Every other command prints a plain human-readable line and has no `--json`
flag — if you need to script against it, prefer one of the eight above, or
parse a stable substring (e.g. `visus tab-new` always prints
`opened tab <idx>: '<title>'`).

## `jq` recipes

```bash
visus list-fields --json | jq '.[] | select(.kind=="button") | {index, name}'
visus snapshot --json | jq -r '.[] | "\(.role): \(.name)"'
visus session status --json | jq -r '.title'
visus cookies --json | jq -r '.[].name'
```

## Capturing a value into a shell variable

```bash
# bash / zsh
title=$(visus title)
port=$(visus session status --json | jq -r '.port')

# PowerShell
$title = visus title
$port = (visus session status --json | ConvertFrom-Json).port
```

## Snapshot-diff around an action

There is no built-in diff command — capture before/after and compare:

```bash
visus snapshot --json > before.json
visus click --role button --name "Add item"
visus snapshot --json > after.json
diff before.json after.json
```

## Why check the exit code, not the message

Message text is for humans and can change between releases; the exit code
(`0`/`1`/`2`) is the only part of the contract this project pins in tests.
`visus expect-text`'s always-`0` behavior exists precisely so a failed
assertion doesn't kill your shell script — check its printed `PASSED`/`FAILED`
prefix instead, or use `visus wait --state visible --timeout <ms>` (which
*does* exit 1 on timeout) when you need a script to actually stop.
