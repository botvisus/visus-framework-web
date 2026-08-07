# `visus` command reference

Every command below drives the **live session daemon** unless it is marked
*one-off browser*. Start the daemon first: `visus session start [URL]`.

Targeting: most commands accept a positional **field index** (from the last
`list-fields`) **or** `--selector` / `-s`, `--role`, `--name`, `--text`.
`--name` on its own is not a target — see
[cli-targeting.md](cli-targeting.md). Exactly eight commands accept their own
`--json`: `translate`, `session status`, `list-fields`, `tabs`, `snapshot`,
`cookies`, `eval` and `find-image` — see
[cli-json-and-piping.md](cli-json-and-piping.md).

Global flags, on every command: `visus --json|--raw|--snapshot|--output-dir <dir>
<command> ...` — see [cli-json-and-piping.md](cli-json-and-piping.md#global-flags).

Timeouts are milliseconds. Exit code 1 = the command failed; 2 = usage error.

### Session & lifecycle

| Command | What it does |
|---|---|
| `visus session start [URL] --engine <e> --headless --idle-timeout <seconds>` | Start the persistent browser daemon (headed by default). `--idle-timeout` (omit = never) stops the daemon after that many seconds with no command — an opt-in reaper for an abandoned session; also settable via `VISUS_WEB_IDLE_TIMEOUT`. |
| `visus session stop` | Stop the session (closes the browser). |
| `visus session kill` | Force-clear a wedged session: terminate the daemon and delete `session.json`/`session.json.lock` even if `stop` can't reach it. |
| `visus session status [--json]` | Show the running session's status. |
| `visus console [URL] --engine <e> --headless` | Open an interactive REPL attached to the session. |

### Navigation

| Command | What it does |
|---|---|
| `visus goto <URL>` | Navigate the session's page to a URL. |
| `visus back` / `visus forward` / `visus reload` | History navigation / reload. |

### Inspect / search the DOM

| Command | What it does |
|---|---|
| `visus snapshot [--json]` | List interactive elements as a role/name table. |
| `visus list-fields --kind <k> --all --no-highlight [--json]` | Enumerate interactive fields, numbered + highlighted. |
| `visus get-text [idx] [target]` | Print an element's text content. |
| `visus get-attribute <attr> [idx] [target]` | Print an element's attribute value. |
| `visus count [idx] [target]` | Count elements matching the target. |
| `visus title` / `visus url` | Print the page title / URL. |
| `visus translate [html] --file <f> [--json]` | Convert a pasted DevTools element into css/xpath/id/class selectors (reads the clipboard if omitted). |

### Actions

| Command | What it does |
|---|---|
| `visus click [idx] [target]` | Click a field. |
| `visus dblclick [idx] [target]` | Double-click a field. |
| `visus fill [idx] <text>` / `… -s <sel> --value <v>` | Fill an input. |
| `visus clear-input [idx] [target]` | Clear an input's value. |
| `visus check` / `visus uncheck [idx] [target]` | Check / uncheck a checkbox or radio. |
| `visus select [idx] <value>` | Select an option on a `<select>`. |
| `visus press [idx] <key>` | Press a key/chord (e.g. `Enter`, `Control+a`). |
| `visus hover` / `visus focus [idx] [target]` | Hover / focus a field. |
| `visus drag <src> <dst>` / `… --to-selector` | Drag a source element onto a target. |
| `visus upload [idx] <paths…>` | Set file(s) on a file input. |

### Wait / assert

| Command | What it does |
|---|---|
| `visus wait [idx] [target] --state <s> --timeout <ms>` | Wait for `visible`/`hidden`/`attached`/`detached`. |
| `visus expect-text [idx] <text> --timeout <ms>` | Assert an element contains text (PASSED/FAILED). |

### Tabs / windows

| Command | What it does |
|---|---|
| `visus tabs [--json]` | List open tabs/windows (active marked `*`). |
| `visus tab [idx]` | Switch to a tab by index (newest if omitted). |
| `visus tab-new [URL]` | Open a new tab and switch to it. |
| `visus tab-close [idx]` | Close a tab (active if omitted). |

### Dialogs / cookies / JS

| Command | What it does |
|---|---|
| `visus dialog --accept/--dismiss --prompt-text <t>` | Handle the next alert/confirm/prompt. |
| `visus cookies [--json]` | List cookies. |
| `visus add-cookies '<json>'` / `visus clear-cookies` | Add / clear cookies. |
| `visus eval "<fn>" [arg] [--json]` | Evaluate JS in the page (e.g. `'() => document.title'`). |

### Capture / vision / utilities

| Command | What it does |
|---|---|
| `visus screenshot <URL> -o <png> --full-page --headless --engine <e>` | Screenshot a URL to a PNG (one-off browser). |
| `visus session-screenshot [idx] -o <png> --full-page` | Screenshot the session's page or a single element. |
| `visus pdf <URL> -o <pdf>` | Print a URL to a PDF (Chromium). |
| `visus open <URL> --engine <e>` | Open a headed browser at URL until you press Enter. |
| `visus clear` | Remove the numbered field-highlight overlay. |
| `visus read-text [idx] [target]` *(`[vision]`)* | OCR an element's screenshot → recognized text. |
| `visus solve-captcha [idx] [target]` *(`[vision]`)* | OCR-solve a text CAPTCHA. |
| `visus find-image <template.png> [idx] [target] -c <conf> [--json]` *(`[vision]`)* | Find a template image inside the page/element. |

### Tooling

| Command | What it does |
|---|---|
| `visus codegen <URL> -o <file> --engine <e>` | Record interactions in a headed browser and generate `visus.web` code. |
| `visus doctor --engine <e>` | Check a browser + driver launch correctly. |
| `visus install --engine <e>` | Resolve/download the browser driver via Selenium Manager. |
| `visus install --skills` / `--skills=agents` | Install the bundled agent skill into `./.claude/` or `./.agents/`. |
| `visus install-skills --target <claude\|agents\|both> --force` | Same, with an explicit target. |
| `visus mcp` | Start the MCP server over stdio (same as `visus-web-mcp`). |
| `visus run <script.py>` | Run a Python script with the active interpreter. |
| `visus version` | Print the `visus.web` version. |

### Not in the CLI (yet)

These exist in the Python library and/or the MCP server but have no shell
command: network request log, browser console log, storage state save/load,
standalone keyboard/mouse, network mocking, tracing start/stop, named
sessions, `attach`/`detach`. Reach them with `visus eval`, the MCP server, or
the library — see [library-api.md](library-api.md) and [mcp-tools.md](mcp-tools.md).
