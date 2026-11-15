---
name: visus-web
description: Drive a real browser from the shell with the `visus` CLI — session daemon, list-fields/act-by-index, role/name targeting, expect-text, codegen, vision. Use when automating or testing a web page.
allowed-tools: Bash(visus:*) Bash(visus-web-mcp:*) Bash(pip:*) Bash(uvx:*)
version: "0.3.6"
---

# visus-web

Drive a **real browser** from the shell. `visus` keeps a browser alive in a
background daemon, so every command lands on the same live page — no re-launch,
no lost login.

## Install

```bash
pip install "visus-web[cli]"   # the `visus` CLI
visus install --skills         # (re)install this skill into ./.claude/skills/
visus doctor                   # prove a browser + driver really launch
```

No install rights? `uvx --from "visus-web[cli]" visus doctor`.
Console script not on PATH? `python -m visus.web.cli doctor`.
**`visus` runs something else?** visus-desktop claims the same name; in an
environment with both, `visus-web` is the alias that only ever means this tool —
every command below works under either name.

Extras: `[cli]` the CLI · `[mcp]` the MCP server · `[vision]` OCR + image matching.

## The session loop — start here

```bash
visus session start https://practicetestautomation.com/practice-test-login/
visus fill "#username" student           # a selector, like any other browser CLI
visus fill "#password" Password123
visus click "#submit"
visus expect-text "h1" "Logged In Successfully"             # PASSED / FAILED
visus session stop                       # closes the browser
```

Don't know the selectors? List the page and act by number — the cheapest path in
tokens, and the one to prefer when you are exploring:

```bash
visus list-fields                        # numbered table + numbered overlay on the page
visus fill 1 student                     # act by index
visus fill 2 Password123
visus click --role button --name Submit  # or target by role/name/selector/text
```

## Driving it as an AI agent — fewest tokens, fewest round-trips

One command opens the page **and** shows what is on it; one more fills a whole
form and shows the result. A number always hits the exact element it was listed
as (it is resolved through that element's XPath, not re-searched).

```bash
visus open https://practicetestautomation.com/practice-test-login/
# Page: Test Login | Practice Test Automation | https://practicetestautomation.com/...
#   0  input:text #username label='Username'
#   1  input:password #password label='Password'
#   2  button #submit label='Submit'
visus batch '[["fill","0","student"],["fill","1","Password123"],["click","2"]]'
# in order, stops at the first failure, then prints the NEW page's list once
visus text --max-chars 2000              # the page's visible text (no eval)
```

- `visus list-fields --compact` — that same one-line-per-element list, any time;
  `--dom` adds each element's opening tag (id, class, name…) when you need a
  selector that outlives the numbers.
- Any selector the DOM offers works where a number does: `#id`, `.class`,
  CSS, `//xpath`, `role=button[name="Submit"]`, `id=…`, `class=…`, `text=…`.
- **A dialog never vanishes silently.** While an alert/confirm/prompt is open
  every command refuses with its text; answer it with `visus dialog`
  (`--dismiss`, `--prompt-text`).
- **Downloads:** after a `click` that downloads, `visus wait-download --save-to
  DIR` prints the finished file's path (the session's own folder is temporary);
  `visus downloads` lists them.
- Output is UTF-8 even through a pipe, and a failure exits non-zero with the
  reason on stderr.

## How to name an element

Every command that acts on an element takes the target the same way, and the
FIRST positional argument is it:

```bash
visus click "#submit"                    # CSS
visus click "//button[@id='submit']"     # XPath (also `xpath=...`)
visus click "text=Log out"               # by visible text
visus click 4                            # a `visus list-fields` index — digits only
visus click --role button --name Submit  # ARIA role (+ --name to refine)
visus click --selector "#submit"         # the long form of the first line
```

A plain number is a field index; anything else is a selector. When a command
also takes a value, the target comes first: `visus fill "#user" bob`,
`visus select "#country" US`, `visus press "#q" Enter`, `visus type "#q" hi`.

If a target matches several elements the command refuses rather than guessing —
add `--nth 0` (first), `--nth -1` (last), or narrow the target.

`visus session status` shows pid, port, engine, url, title and `fields_cached`.
Full reference: **[references/cli-session.md](references/cli-session.md)**.

## Rules that will bite you

- **Field indexes belong to the page you listed.** After `goto` / `back` /
  `forward` / `reload` / a form submit, run `list-fields` again before acting by
  index.
- **`--name` alone is not a target.** It only qualifies `--role`. A command with
  no index and no `--selector` / `--role` / `--text` exits 1 with
  `error: provide an index, or --selector / --role / --text`.
- **A loose target that matches several elements is an error, not a guess.**
  `locator resolved to N elements` → re-run with `--nth 0` / `--nth -1`, or use a
  more specific selector.
- **Timeouts are milliseconds.** `--timeout 5000`, not `5`.
- **Never sleep.** Every action auto-waits; `visus wait --state visible` and
  `visus expect-text` are the synchronisation primitives.
- **`visus clear` removes the highlight overlay. `visus clear-input` clears an
  input's value.** They are different commands.
- **The URL decides which browser `screenshot`/`pdf` use.** `visus screenshot
  <URL>` launches a throwaway browser that has none of the session's state;
  `visus screenshot` with **no URL** shoots the live session. (`visus
  session-screenshot` / `session-pdf` still work as deprecated aliases.)

Targeting in depth: **[references/cli-targeting.md](references/cli-targeting.md)**.
When something goes wrong: **[references/troubleshooting.md](references/troubleshooting.md)**.

## Which interface

| You are | Use | Why |
|---|---|---|
| A coding agent with shell access | **the `visus` CLI** | Cheapest tokens: no tool schemas, one line per action, numbered indexes instead of an accessibility dump. This is the default. |
| An MCP client without shell access | **`visus-web-mcp`** | **53 tools** over the same browser surface. Its browser is a *separate* process from the CLI daemon **by default**. Call `browser_attach_session` to drive the daemon's browser instead — then the model and the human share one page, one session and one field-index vocabulary. `browser_detach_session` goes back to the server's own browser. |
| Writing a durable script or a test | **the Python library** | `from visus.web import launch, rpa, expect`. Auto-waiting actions, auto-retrying assertions, HTML run reports. |

The CLI daemon and the MCP server hold **independent** browsers with opposite
defaults (CLI: headed, auto-follows new tabs; MCP: headless, manual tab
follow). Pick one per task.

## Commands

**107 commands** total (88 top-level plus the `session`, `storage`, `network`
and `route` groups), covering the persistent-session daemon, request mocking,
vision targeting, one-off screenshot/pdf/codegen helpers, and `install-skills`.
The complete reference — targeting rules, every flag, grouped by task — is
**[references/cli-commands.md](references/cli-commands.md)**.

The ones you will use most:

```bash
visus goto <URL> | back | forward | reload
visus list-fields [--kind input,button] [--all] [--highlight] [--full] [--json]
visus snapshot ["#main"] [--depth N]     # REF/role/name table; REF is a list-fields index
visus click|dblclick|hover|focus|check|uncheck <target>   # "#css" | //xpath | text=… | idx
visus fill <target> <text>               # also: -s "#user" --value text
visus select <target> <value> | visus press <target> Enter | visus clear-input <target>
visus pick-date <target> 2026-11-02 [2026-11-06]   # any date field or calendar popup
visus get-text|get-attribute <attr>|count <target>
visus <any of the above> --nth 0         # when a target matches several elements
visus title | visus url | visus tabs | visus tab <idx>
visus wait [idx] --state visible|hidden|attached|detached --timeout <ms>
visus expect-text [idx] <text> --timeout <ms>
visus screenshot -o shot.png [--full-page] [--hires] [-i idx]  # no URL = session
visus eval "() => document.title" [--json]
visus cookies [--json] | visus add-cookies '<json>' | visus clear-cookies
```

Beyond the basics — each of these exists, and none of them is reachable by
guessing:

```bash
# Sessions are NAMED. Several can run at once, in one project or across projects.
visus -S auth session start --persistent --allow-run-code <URL>
visus session list [--json]          # every session, this project's and others'
visus session close-all | kill-all | delete-data
visus session attach --cdp 127.0.0.1:9222   # drive a browser visus did not launch

# Request mocking (Chromium): make a flow deterministic without touching the app.
visus route "**/api/*" --status 503 --body '{"e":1}' --content-type application/json
visus route "**/*.{png,jpg}" --abort | visus route-list | visus unroute [PATTERN]

# Network: two complementary layers.
visus requests [--filter /api/] | visus request <N>   # CDP responses, with bodies
visus network start | export -o cap.json | stop       # fetch/XHR/sendBeacon bodies

# Vision targeting — for canvas, embedded PDFs, widgets with NO accessibility tree.
visus click --image button.png [-c 0.9] | visus click --ocr-text "Sign in"

# Emulation and profiles.
visus devices                        # the presets --device accepts
visus session start --device "iPhone 15" | --mobile | --persistent

# Drop a file/payload on a dropzone that has no <input type=file>.
visus drop -s "#zone" --path ./report.csv | --data '{"id":1}'

# Arbitrary Python against the LIVE session (opt-in at session start).
visus run-code "result = page.url"   # needs session start --allow-run-code
```

`--json` is available on `translate`, `session status`, `list-fields`, `tabs`,
`snapshot`, `cookies`, `eval` and `find-image`. Piping, exit codes and shell
capture: **[references/cli-json-and-piping.md](references/cli-json-and-piping.md)**.

On Windows, the shell mangles `<`, `>` and `"` — `visus translate` exists
precisely for that. Read **[references/windows-shell.md](references/windows-shell.md)**
before quoting a selector in PowerShell.

`visus repl` opens a REPL attached to the live session with a shorter
vocabulary: **[references/cli-repl.md](references/cli-repl.md)**. (`visus
console` still works as a deprecated alias; the name now belongs to the
browser's console messages, which are `visus logs`.)

## MCP server

`visus-web-mcp` (or `visus mcp`) exposes **53 tools** — navigation, ARIA
snapshot, `browser_list_fields`, every action, tabs, dialogs, cookies,
network/console capture, screenshot, evaluate, and the vision tools. Configure
with `VISUS_WEB_ENGINE` (chrome | edge | firefox | edge_ie) and
`VISUS_WEB_HEADLESS` (0/1). Tool list and target parameters:
**[references/mcp-tools.md](references/mcp-tools.md)**.

The server also serves this skill: read the resource `visus://skill/SKILL.md`
and `visus://skill/references/<file>.md`, or call the `visus_web_quickstart`
prompt.

## Beyond the CLI

- **Captcha**: `visus solve-captcha` (no target) solves the page's reCAPTCHA,
  Cloudflare Turnstile or hCaptcha with a captcha service — key in
  `VISUS_CAPTCHA_KEY` (CapSolver; `VISUS_CAPTCHA_PROVIDER=2captcha` for 2Captcha) —
  and applies the token; `page.solve_captcha()` in a script. Never click through
  the picture challenges: without a key, ask a human to solve it.
- **Vision** (`[vision]`): `visus read-text`, `visus solve-captcha <target>` (OCR),
  `visus find-image tmpl.png -c 0.8 --json` — OCR and OpenCV template matching.
  **[references/vision.md](references/vision.md)**
- **Tracing & HTML reports**: `rpa("login")` records the run and writes a
  single-file `report.html` **even when a step raises**;
  `tracing.record()` does the same around any block.
  **[references/tracing-reports.md](references/tracing-reports.md)**
- **pytest plugin**: loads automatically via the `pytest11` entry point, gives
  you `visus_page` / `visus_context` / `visus_browser` with screenshot-on-failure
  and automatic `expect.soft()` verification.
  **[references/pytest-plugin.md](references/pytest-plugin.md)**
- **Python API**: `launch()` / `rpa()` / `expect()`, `Field`, `is_active`,
  `save_screenshot`, the 100 %-mirror `visus.web.async_api`, `NetworkCapture`
  for reverse-engineering an API (`page.network_requests()` /
  `page.expect_response()`), `launch(remote_url=...)` for Selenium Grid,
  and the `edge_ie` engine for IE-mode legacy apps (Windows-only).
  **[references/library-api.md](references/library-api.md)**

## Errors

`visus.web.errors`: `VisusWebError` (base), `VisusTimeoutError`,
`NavigationError`, `TargetClosedError`, `StrictModeViolation`,
`ElementNotFoundError`, `UnsupportedEngineError`. A failed `expect()` raises
`AssertionError`. From the shell, a failed command exits **1** and prints
`error: <type>: <message>`; a usage error exits **2**.

## Skills-less operation

If this skill is not installed, point the agent at the CLI and let it read its
own help:

```
Automate <task> on <url> using the `visus` CLI.
Run `visus --help` and `visus <command> --help` for the available commands.
Start with `visus session start <url>`, then `visus list-fields`.
```

## Specific tasks

* **Session daemon lifecycle** [references/cli-session.md](references/cli-session.md)
* **Targeting an element** [references/cli-targeting.md](references/cli-targeting.md)
* **Every command** [references/cli-commands.md](references/cli-commands.md)
* **JSON, exit codes, piping** [references/cli-json-and-piping.md](references/cli-json-and-piping.md)
* **The interactive REPL** [references/cli-repl.md](references/cli-repl.md)
* **Quoting on Windows** [references/windows-shell.md](references/windows-shell.md)
* **The MCP server** [references/mcp-tools.md](references/mcp-tools.md)
* **OCR and image matching** [references/vision.md](references/vision.md)
* **Tracing and HTML reports** [references/tracing-reports.md](references/tracing-reports.md)
* **The pytest plugin** [references/pytest-plugin.md](references/pytest-plugin.md)
* **Troubleshooting** [references/troubleshooting.md](references/troubleshooting.md)
* **The Python API** [references/library-api.md](references/library-api.md)
