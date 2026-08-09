# `visus` command reference

Every command below drives the **live session daemon** unless it is marked
*one-off browser*. Start the daemon first: `visus session start [URL]`.

Targeting: most commands accept a positional **field index** (from the last
`list-fields`) **or** `--selector` / `-s`, `--role`, `--name`, `--text`, plus the
two modifiers `--exact` (match `--role`/`--text` exactly, not by substring) and
`--frame <css>` (the iframe holding the target). `--name` on its own is not a
target — see [cli-targeting.md](cli-targeting.md). Exactly eight commands accept their own
`--json`: `translate`, `session status`, `list-fields`, `tabs`, `snapshot`,
`cookies`, `eval` and `find-image` — see
[cli-json-and-piping.md](cli-json-and-piping.md).

Global flags, on every command: `visus --json|--raw|--snapshot|--output-dir <dir>
<command> ...` — see [cli-json-and-piping.md](cli-json-and-piping.md#global-flags).

Timeouts are milliseconds. Exit code 1 = the command failed; 2 = usage error.

### Session & lifecycle

| Command | What it does |
|---|---|
| `visus session start [URL] --engine <e> --headless --user-data-dir <dir> --remote-url <url> --slow-mo <ms> --idle-timeout <seconds>` | Start the persistent browser daemon (headed by default). `--user-data-dir` reuses a persistent profile, so cookies and logins survive across runs (MFA once, not every run) — the path resolves against your cwd. `--remote-url` drives a Selenium Grid / Remote WebDriver instead of a local browser. `--slow-mo <ms>` delays every action. `--idle-timeout` (omit = never) stops the daemon after that many seconds with no command — an opt-in reaper for an abandoned session. All four are also settable via `VISUS_WEB_USER_DATA_DIR`, `VISUS_WEB_REMOTE_URL`, `VISUS_WEB_SLOW_MO` and `VISUS_WEB_IDLE_TIMEOUT`. |
| `visus session stop` | Stop the session (closes the browser). |
| `visus session kill` | Force-clear a wedged session: terminate the daemon and delete `session.json`/`session.json.lock` even if `stop` can't reach it. |
| `visus session status [--json]` | Show the running session's status. |
| `visus session export-script [-o FILE]` | Emit everything the session did as a runnable `visus.web` script. Prints it by default; `-o` writes it to a file (relative paths honour `--output-dir`). |
| `visus repl [URL] --engine <e> --headless` | Open an interactive REPL attached to the session. |
| `visus console [URL] --engine <e> --headless` | **Deprecated** alias for `visus repl`; prints a notice on stderr and still opens the REPL. The name is reserved for the browser's console messages, which are `visus logs`. |

### Navigation

| Command | What it does |
|---|---|
| `visus goto <URL>` | Navigate the session's page to a URL. |
| `visus back` / `visus forward` / `visus reload` | History navigation / reload. |

### Inspect / search the DOM

| Command | What it does |
|---|---|
| `visus snapshot [SELECTOR] [--depth N] [--filename F] [--no-refs] [--json]` | List interactive elements as a REF/ROLE/NAME table. A REF **is** a `list-fields` index, so `visus snapshot` then `visus click 4` works. `SELECTOR` scopes the walk to one subtree, `--depth N` keeps only elements at most N levels below that root, `--filename` writes YAML instead of printing, `--no-refs` skips the re-enumeration (leaves the field cache untouched, every REF then `-`), `--boxes` adds each element's viewport rect as `x,y,w,h`. |
| `visus find <QUERY> [--regex] [-C N] [-s SEL] [--depth N] [--json]` | Grep the snapshot instead of printing it: matching rows plus `-C` rows of context (default 3), `>` marking each hit. Matches `"<role> <name>"`, case-insensitively unless `--regex`. Every row carries its REF, so the next command is `visus click <REF>`. |
| `visus list-fields --kind <k> --all [--highlight] [--full] [--json]` | Enumerate interactive fields, numbered. The table carries `#`, `KIND`, `NAME` and the copy-paste `VISUS` call; `--full` adds the `CSS` and `XPATH` columns. The numbered overlay is **off by default** — it injects real DOM nodes that a later `session-screenshot` / `read-text` / `find-image` would read as page content. `--highlight` turns it on (useful with a headed browser or a vision model); `--no-highlight` still parses and names the default. `--boxes` adds each field's viewport rect as `x,y,w,h` — the geometry the overlay was drawn from, so `find-image`/`read-text` can be pointed at one element instead of the whole screenshot. |
| `visus get-text [idx] [target]` | Print an element's text content. |
| `visus get-attribute <attr> [idx] [target]` | Print an element's attribute value. |
| `visus count [idx] [target]` | Count elements matching the target. |
| `visus title` / `visus url` | Print the page title / URL. |
| `visus translate [html] --file <f> [--json]` | Convert a pasted DevTools element into css/xpath/id/class selectors (reads the clipboard if omitted). |

### Actions

| Command | What it does |
|---|---|
| `visus click [idx] [target] [--button <b>] [-b <b>]` | Click a field. `--button` is `left` (default), `middle` or `right` — a right click opens the page's context menu, a middle click is open-in-new-tab. A non-left click goes through the pointer device at the target's centre, because the auto-waiting click path is left-button only. |
| `visus dblclick [idx] [target] [--button <b>]` | Double-click a field. |
| `visus mousemove <x> <y>` | Move the pointer to absolute **viewport** coordinates. |
| `visus mousedown [--button <b>]` / `visus mouseup [--button <b>]` | Press / release a mouse button at the current pointer position — a drag is `mousemove`, `mousedown`, `mousemove`, `mouseup`. |
| `visus mousewheel <dx> <dy>` | Scroll by a wheel delta at the pointer: the way to drive lazy-loading lists and canvases. Note Chrome enters autoscroll after a **middle** click and swallows the next wheel until the pointer moves again. |
| `visus fill [idx] <text> [--submit]` / `… -s <sel> --value <v>` | Fill an input. `--submit` presses Enter on the same element afterwards, which submits most forms in one command instead of two. |
| `visus clear-input [idx] [target]` | Clear an input's value. |
| `visus check` / `visus uncheck [idx] [target]` | Check / uncheck a checkbox or radio. |
| `visus select [idx] <value>` | Select an option on a `<select>`. |
| `visus press [idx] <key>` / `visus press <key>` | Press a key/chord (e.g. `Enter`, `Control+a`). With **no** target the key goes to the page's keyboard — `visus press Enter` works on whatever is focused. A bare first argument that is not a number is read as the key. |
| `visus type <text> [--index N] [-s <sel>] [--role r] [--text t]` | Type with real key events (unlike `fill`, which sets the value in one step — use `type` when the page listens for keystrokes). With a target it focuses it first; without one it types into whatever is focused. |
| `visus keydown <key>` / `visus keyup <key>` | Hold a modifier down across several commands and release it — e.g. `keydown Shift`, some clicks, `keyup Shift`. |
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
| `visus tab-activate <handle>` | Focus a tab by its **stable window handle** (the `handle` field of `visus tabs --json`). Handles survive a reorder or a close; the positional index `visus tab N` uses does not. |
| `visus tab-follow --on/--off` | `--on` (the default) makes every later op target the most recently opened tab/popup. `--off` pins the context where it is, so a click that spawns a popup cannot silently steal it — steer manually with `tabs` + `tab`/`tab-activate`. The current mode shows up as `follow` in `visus session status --json`. |

### Dialogs / cookies / JS

| Command | What it does |
|---|---|
| `visus dialog --accept/--dismiss --prompt-text <t>` | Handle the next alert/confirm/prompt. |
| `visus cookies [--json]` | List cookies. |
| `visus add-cookies '<json>'` / `visus clear-cookies` | Add / clear cookies. |
| `visus state-save [FILE]` | Snapshot cookies **and** localStorage/sessionStorage to JSON (default `storage-state.json`). Paths resolve against the client's cwd. |
| `visus state-load <FILE>` | Restore a `state-save` snapshot — the login-reuse flow. **Navigate to the target origin first** (`visus goto <url>`): cookies only apply to the loaded domain and web storage is per-origin. |
| `visus storage list [--session-storage]` | Every key/value in the origin's storage. |
| `visus storage get <key> [--session-storage]` | One value. Exits 1 when the key is absent, and carries a `present` flag — so a stored empty string and a missing key never print the same blank line. |
| `visus storage set <key> <value> [--session-storage]` | Write one value. |
| `visus storage delete <key> [--session-storage]` | Remove one key. |
| `visus storage clear [--session-storage]` | Empty **one** store — clearing sessionStorage never touches localStorage. |

`--session-storage` (on all five) switches from localStorage to sessionStorage;
the switch is spelled out because `--session` / `-S` is reserved for named
sessions. Reaching web storage any other way means a hand-written JS closure
through `visus eval`, whose quotes PowerShell mangles.
| `visus eval "<fn>" [arg] [target] [--json]` | Evaluate JS and print the result. With **no** target it runs on the page and is called as `(fn)(arg)`. With a target (`-i N`, `-s`, `--role`, `--text`) it runs on that ELEMENT and is called as `(fn)(element, arg)` — how you read `id`/`class`/`dataset` or any property `list-fields` does not return. The MCP `browser_evaluate` tool takes the same target parameters. |
| `visus logs [LEVEL] [--json]` | Browser console messages captured so far. `LEVEL` filters case-insensitively on `SEVERE` / `WARNING` / `INFO`. Chromium engines only. |
| `visus requests [--filter <s>] [-F <s>] [--json]` | Network responses captured so far, numbered. `--filter` is a plain substring test on the URL. Chromium only. |
| `visus request <N> [--json]` | One captured response in full — method, URL, status, resource type and the response **body**, which the MCP surface does not expose. `N` is the index from `visus requests`. A body evicted after a navigation prints `(body unavailable)` rather than failing. |

### Capture / vision / utilities

| Command | What it does |
|---|---|
| `visus screenshot <URL> -o <png> --full-page --headless --engine <e>` | Screenshot a URL to a PNG (one-off browser). |
| `visus session-screenshot [idx] -o <png> --full-page` | Screenshot the session's page or a single element. |
| `visus pdf <URL> -o <pdf>` | Print a URL to a PDF (Chromium). |
| `visus open <URL> --engine <e>` | Open a headed browser at URL until you press Enter. |
| `visus clear` | Remove the numbered field-highlight overlay drawn by `list-fields --highlight`. |
| `visus highlight [idx] [target] [--style <css>] [--hide]` | Box **one** element on the live page — what a human needs to see which element the agent chose. `--style` replaces the default border (e.g. `"2px dashed #0a0"`), `--hide` removes the box. Distinct from `visus clear`, which erases the numbered overlay. |
| `visus resize <w> <h>` | Resize the window so the **viewport** is exactly w x h CSS pixels. Prints the size actually achieved, not the one requested: a window manager can clamp it (minimum widths, screen size), and echoing the request back would hide that. Use it to reproduce a width-specific layout bug, or to make screenshots deterministic across machines. |
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
