# Troubleshooting

Errors are keyed to the literal strings the CLI and daemon print. A failed
command exits **1**; a usage error (bad flags/types) exits **2**.

## Session lifecycle

| Message | Cause | Fix |
|---|---|---|
| `` `error: no live session — run `visus session start` first` `` | No `.visus/session.json` was found walking up from the current directory, or the recorded pid/port failed the liveness probe (the stale file is deleted for you). | `visus session start [URL]`. If you started the session in a *sibling* directory, `cd` into it or into a shared parent — discovery only walks **upward**. |
| `error: a session is already running (pid 1234, port 51234)` | A live daemon was found at or above the current directory. | Reuse it (just run commands), or `visus session stop` first. There are no named sessions — one daemon per directory tree. |
| `error: daemon did not come up within 20s (see <cwd>/.visus/daemon.log)` — the path is printed absolute | The daemon process started but never bound its socket within the 20s default timeout: the browser failed to launch, the driver is missing, or a stale `.visus/session.json.lock` blocked it. | Read the tail of `.visus/daemon.log` — the real exception is there (logged as `daemon crashed: <TypeName>: <message>`). Then `visus doctor` to prove the browser launches. If the log says `daemon aborting: another daemon already holds …`, delete `.visus/session.json.lock` by hand and retry. |
| `error: daemon closed the connection without responding` | The daemon died mid-request (browser crash, machine sleep, OOM) — the client read an empty line instead of a JSON response. | `visus session stop` (it cleans up), then `visus session start` again. |
| `error: unauthorized: bad token` | The `.visus/session.json` you are reading belongs to a different daemon than the one listening on that port — usually a half-cleaned crash. | Delete `.visus/` and start a fresh session. |
| `visus session stop` prints `no session running` but a browser window is still open | The daemon died without cleaning up, or the window belongs to a `visus open` / `visus codegen` / `visus screenshot` / `visus pdf` one-off browser. | Close the window manually; those commands launch their own browser and are not part of the session. |
| `closed the last tab — session stopped` but later commands still work | Closing the last tab tears down the browser (`tab-close` sees 0 remaining handles), but the daemon process itself stays up; the next command's `_ensure()` relaunches a **fresh** browser at the session's original URL. | Treat it as a restart: you are logged out. Prefer `visus session stop`. |

## Targeting

| Message | Cause | Fix |
|---|---|---|
| `error: provide an index, or --selector / --role / --text` | No target given, or only `--name`. `--name` qualifies `--role`; it is not a target on its own (see [cli-targeting.md](cli-targeting.md)). | `visus click --role button --name Submit`, or use an index. |
| `error: IndexError: field index 9 out of range (have 4; run list_fields first)` | The index cache is empty or shorter than you think. | `visus list-fields` first, every time the page changes. |
| A command reports success but the wrong element reacted | The index cache was captured on a **previous** page. Nothing re-validates it. | Re-run `visus list-fields` after every navigation and after every click that submits a form. |
| `error: ValueError: provide one of: index, role, text, selector` | The daemon received an empty target dict — usually a hand-built op, not the CLI (the CLI's own guard catches this first). | Send one of `index`, `role`, `text`, `selector`. |
| `error: StrictModeViolation: …` | The selector matched more than one element. | Add `--name` to `--role`, use a more specific selector, or switch to an index. |
| `error: ElementNotFoundError: …` / `error: VisusTimeoutError: …` | The element never became actionable within the timeout. | `visus wait --state visible -s "…" --timeout 15000` first; check you are on the right tab with `visus tabs`. |
| `Invalid value for 'index': 'Enter' is not a valid int.` (from `visus press Enter`) | `press` takes two positionals, `<index> <key>`; with only one word given it is parsed as `index`, and `Enter` is not an int. This is a Typer usage error, not a targeting error — it exits **2**. | `visus press <idx> Enter`, or `visus press -s "#pwd" --key Enter`. |

## Command confusion

| Symptom | Cause | Fix |
|---|---|---|
| `visus screenshot` opened a new browser instead of capturing the session | `visus screenshot <URL>` is a one-off browser command (like `open`, `pdf`, `codegen`). | Use `visus session-screenshot -o shot.png [--full-page]`. |
| `visus clear` did not clear the input | `clear` removes the numbered overlay. | Use `visus clear-input <idx>`. |
| `visus console` launched a browser | With no session running, the REPL starts one itself, **headed** by default. | `visus session start --headless` first if you need headless, then `visus console`. |
| `error: ValueError: unknown op 'xyz'` | The daemon does not implement that op — usually a CLI/daemon version mismatch after an upgrade (the running daemon is stale). | Reinstall: `pip install -U "visus-web[cli]"`, then `visus session stop && visus session start`. |

## Environment

| Symptom | Cause | Fix |
|---|---|---|
| `visus: command not found` | The console script is not on PATH. | `python -m visus.web.cli <command>`, or `uvx --from "visus-web[cli]" visus <command>`. |
| `` The `visus` CLI needs the [cli] extra `` | Installed without the extra. | `pip install "visus-web[cli]"` |
| `The visus-web MCP server needs the [mcp] extra` | Same, for MCP. | `pip install "visus-web[mcp]"` |
| `ModuleNotFoundError: No module named 'rapidocr_onnxruntime'` from `read-text` / `solve-captcha`; `No module named 'cv2'` from `find-image` | Vision runs **inside the daemon** process; the extra is missing there, not on the client. | `pip install "visus-web[vision]"`, then `visus session stop && visus session start` so the daemon picks it up. |
| A framed box says `does not match the tool version` | Your repo's installed copy of the skill differs from the bundled one (compared with line endings normalized, so CRLF alone never triggers it). | Run the command the box names: `visus install --skills` (or `--skills=agents`). |
| `visus doctor` prints `FAILED: …` | The browser or driver cannot launch. | Install the browser; Selenium Manager resolves the driver. `visus install --engine edge` forces a one-time resolve. |

## Quoting

Selector quoting is the top source of "it works in bash, not in PowerShell"
failures. See [windows-shell.md](windows-shell.md).
