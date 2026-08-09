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
| `visus session start [URL] --engine/--browser <e> --headless --persistent --profile <dir> --user-data-dir <dir> --remote-url <url> --slow-mo <ms> --device <d> --mobile --idle-timeout <seconds> --allow-run-code` | Start the persistent browser daemon (headed by default). `--user-data-dir` reuses a persistent profile, so cookies and logins survive across runs (MFA once, not every run) — the path resolves against your cwd. `--remote-url` drives a Selenium Grid / Remote WebDriver instead of a local browser. `--slow-mo <ms>` delays every action. `--idle-timeout` (omit = never) stops the daemon after that many seconds with no command — an opt-in reaper for an abandoned session. All four are also settable via `VISUS_WEB_USER_DATA_DIR`, `VISUS_WEB_REMOTE_URL`, `VISUS_WEB_SLOW_MO` and `VISUS_WEB_IDLE_TIMEOUT`. `--persistent` is the managed form of the same thing: the profile goes in `.visus/profiles/<session>`, which is the ONLY directory `session delete-data` will remove. `--profile <dir>` is a second spelling of `--user-data-dir` (a directory you own, never deleted), and `--browser` a second spelling of `--engine`. `--device <name>` / `--mobile` emulate the VIEWPORT (size, pixel ratio, mobile flag) via CDP before the first navigation, so the initial load already sees it — chrome or edge only, and the user-agent string is NOT changed. `--allow-run-code` enables `visus run-code` for this session. |
| `visus session stop` | Stop the session (closes the browser). |
| `visus session attach --cdp <host:port> [URL] [--engine chrome\|edge]` | Bind the session to a browser that is ALREADY running — the user's own logged-in window, or a container exposing CDP — instead of launching one. The target must have been started with remote debugging (`--remote-debugging-port=9222`, or `chrome://inspect/#remote-debugging` → "Allow remote debugging for this browser instance"). `--cdp` takes `host:port` or the `http://host:port` form a container prints. The session name still comes from `--session` / `-S`, not from the channel. **An attached session has no performance/console log history** — those are launch-time capabilities, so `visus requests` and `visus logs` stay empty; everything else works. |
| `visus session detach` | End an attached session and leave the browser open. Only for `attach` sessions — `stop` on one would close a window that is not visus's to close, so `detach` refuses on a launched session and points at `stop`. |
| `visus session kill` | Force-clear a wedged session: terminate the daemon and delete `session.json`/`session.json.lock` even if `stop` can't reach it. |
| `visus session status [--json]` | Show the running session's status. |
| `visus session list [--json]` | Every session visus knows about, not just this project's: the local `.visus/sessions/*.json` merged with the cross-project registry under `~/.visus/sessions` (`VISUS_WEB_HOME` moves it). `SCOPE` is `local` when the upward walk found it from here, `other` when only the registry knows it; `STATE` is `live` when the pid is alive AND the port accepts. Use it to find a headed browser abandoned in another project. |
| `visus session close-all` | Politely shut down every live session `list` can see. Shutdown needs the session token, which lives only in the owner-only session file — a session whose file is unreadable is named in the output, not silently skipped, and `kill-all` is the way to end it. |
| `visus session kill-all` | Force-kill every session daemon and delete all state: each project's session file and lock, its registry entry, and any pre-namespace `.visus/session.json` that no other command can reach. Needs no token. |
| `visus session delete-data` | Delete this session's persistent profile — only `.visus/profiles/<name>`, the directory visus itself creates. A profile you pointed at with `--user-data-dir` is reported and left alone. Refuses while the session is still running. |
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
| `visus click [idx] [target] [--button <b>]` / `visus click --image <png> [-c 0.8]` | Click a field. `--button` is `left` (default), `middle` or `right` — a right click opens the page's context menu, a middle click is open-in-new-tab. A non-left click goes through the pointer device at the target's centre, because the auto-waiting click path is left-button only. **`--image`** clicks the CENTRE of a matched template PNG instead of an element — for a canvas app, an embedded PDF viewer or a widget with no accessibility tree, where role/name/text/selector can reach the container and nothing inside it. Scope the search to one element by adding an ordinary target. Needs the `[vision]` extra. |
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
| `visus drop [idx] [target] --path <f>` / `--data <t> [--data-type <ct>]` | The THIRD case, which neither `drag` nor `upload` reaches: a dropzone with no `<input type=file>`, which only reacts to a `DragEvent` carrying a `DataTransfer` from outside the page. `--path` reads the file on the client (so the path is relative to your cwd), base64s it, and rebuilds a real `File` in the page; `--data` drops text under `--data-type` (default `text/plain`). Fires `dragenter`, `dragover`, `drop` in order and reports how many files and which types landed. |
| `visus upload [idx] <paths…>` | Set file(s) on a file input; paths resolve against YOUR cwd. **The target is optional** — with none, visus finds the page's single `<input type=file>`, including one hidden behind a styled "Choose a file" button (the shape an OS file chooser normally hides). No chooser dialog is ever opened. Zero inputs points you at `visus drop --path`; two or more refuses and tells you to pick one with `list-fields` + an index. A leading all-digits token IS that index — for a file literally named `2`, pass `./2` or use `--selector`. |

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
| `visus cookies [--domain <d>] [--path <p>] [--json]` | List cookies, optionally filtered. A stored domain may carry a leading dot (`.example.com`); `--domain example.com` matches both spellings. |
| `visus cookie-get <name> [--domain] [--path]` | Print one cookie's value. Exits 1 when there is no such cookie, and carries a `present` flag so an empty value and a missing cookie stay distinguishable. |
| `visus cookie-set <name> <value> [--domain] [--path] [--url]` | Set one cookie. `--path` defaults to `/`. |
| `visus cookie-delete <name> [--domain] [--path]` | Delete cookies by name. **WebDriver has no per-cookie delete**, so this reads the jar, clears it and re-adds the survivors one at a time. `driver.add_cookie` only accepts a cookie for the *currently loaded* document's domain, so a survivor from another domain cannot be put back — the command reports those as `dropped` rather than losing them silently. |
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
| `visus run-code "<python>"` / `visus run-code --file <f>` | Python executed against the LIVE session, with `page`, `context`, `browser` and `expect` bound to the real objects — the escape hatch for anything the command list does not cover (geolocation, permissions, media emulation, frames, downloads). A single expression is returned; a longer snippet returns whatever it assigns to `result`. Return values are coerced to JSON-safe forms, so a `Page` or `Locator` comes back as its `repr` instead of breaking the reply. **Off unless the session was started with `--allow-run-code`** — it runs arbitrary code inside a browser holding your logins. Three different things: `eval` runs JS *in the page*, `run-code` runs Python *against the session*, `run` runs a script in a *separate process with its own browser*. |
| `visus logs [LEVEL] [--json]` | Browser console messages captured so far. `LEVEL` filters case-insensitively on `SEVERE` / `WARNING` / `INFO`. Chromium engines only. |
| `visus requests [--filter <s>] [-F <s>] [--json]` | Network responses captured so far, numbered. `--filter` is a plain substring test on the URL. Chromium only. |
| `visus request <N> [--json]` | One captured response in full — method, URL, status, resource type and the response **body**, which the MCP surface does not expose. `N` is the index from `visus requests`. A body evicted after a navigation prints `(body unavailable)` rather than failing. |
| `visus network start` / `visus network stop` / `visus network export [-o <json>]` | A **second, complementary** capture. `visus requests` reads the CDP response log: every response, including assets and redirect legs. `network` installs a JS hook and records what the **page itself sent** — `fetch`/`XHR` **request bodies**, JSONP `<script>`, `sendBeacon` and `<img>` pings — none of which a response log can show. `export` writes `{target_url, entries}` with auth headers redacted. The two never starve each other: the hook capture runs with `use_cdp=False`, because `driver.get_log("performance")` is destructive and two drainers would split it. |

### Network mocking (Chromium only)

Make a flow deterministic — a 500, an empty list, a blocked asset — without touching the app.
Patterns are Playwright-style globs: `**` crosses `/`, `*` does not, `{png,jpg}` alternates,
and `?` is **literal** (URLs use it for the query string). Runs on the CDP `Fetch` domain, so
it needs chrome or edge; on Firefox, stub the API from the page with `page.add_init_script(...)`.

| Command | What it does |
|---|---|
| `visus route <PATTERN> [--status N] [--body T] [--body-file F] [--content-type CT] [--header 'K: V'] [--abort]` | Answer matching requests locally instead of letting them reach the network; `--abort` fails them instead (an asset blocked this way behaves like a network error, not a 404). Re-routing the same pattern REPLACES the rule. `--body-file` is read on the client, so its path resolves against your cwd. `--abort` with a status or body is refused rather than silently dropping them. `--header` sets *response* headers on the mock. |
| `visus unroute [PATTERN]` | Remove that rule, or every rule when the pattern is omitted. Removing the last one drops the DevTools connection, leaving the tab exactly as it was. |
| `visus route-list [--json]` | The installed rules in insertion order. Secret headers come back `REDACTED`, so an `Authorization` handed to a mock never leaves through this command. |

### Capture / vision / utilities

| Command | What it does |
|---|---|
| `visus screenshot [URL] -o <png> --full-page [--hires] [target]` | Screenshot to a PNG. **The URL decides which browser.** With one: a *one-off browser* (`--headless`, `--engine`) that has none of the session's state. Without: the **live session** — the whole page, or one element via `-i N` / `-s` / `--role` / `--text`. `--hires` (session only) captures at device-pixel-ratio 2, markedly better for `read-text` OCR and for a vision model reading the numbered overlay; the scale is restored to 1x even if the capture fails. |
| `visus pdf [URL] -o <pdf>` | Print to a PDF (Chromium). Same split as `screenshot`: with a URL a one-off browser, without one the **live session** — so a page you logged into and navigated to can actually be captured. |
| `visus session-screenshot` / `visus session-pdf` | **Deprecated** aliases for the two above with no URL. They still work and print a notice on stderr. After the rename **no session command carries a `session-` prefix**, and the REPL's `screenshot`/`pdf` mean the same thing as the CLI's. |
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
| `visus generate-locator [idx] [target] [--raw]` | The copy-paste `visus.web` expression for **one** element. By index it is `Field.code` verbatim — byte-for-byte the VISUS column of `visus list-fields` — plus that field's css and xpath. By `--selector`/`--role`/`--text` it is built to mirror the CLI's own resolution order (role, then text, then selector), so the printed line reaches the element the CLI would act on. `--raw` prints the expression alone, ready to pipe. |
| `visus tracing-start [-o <zip>] [--no-screenshots]` | Record every session action — per-action screenshot, correlated logs, and an ARIA snapshot at the point of failure. `--no-screenshots` matters on a long run: every shot is held in memory until the zip is written. **`VISUS_WEB_TRACING=1` alone records nothing** — the runtime needs an installed recorder as well, and this is the command that installs one. |
| `visus tracing-stop [-o <zip>] [--report <html>]` | Stop recording and write the trace zip; `--report` also renders the single-file HTML report. Prints the action and failure counts. |
| `visus report <trace.zip> [-o <html>]` | Render the HTML report from a trace zip. *One-off*: needs no running session. |
| `visus doctor --engine <e>` | Check a browser + driver launch correctly. |
| `visus install --engine <e>` | Resolve/download the browser driver via Selenium Manager. |
| `visus install --skills` / `--skills=agents` | Install the bundled agent skill into `./.claude/` or `./.agents/`. |
| `visus install-skills --target <claude\|agents\|both> --force` | Same, with an explicit target. |
| `visus mcp` | Start the MCP server over stdio (same as `visus-web-mcp`). |
| `visus run <script.py>` | Run a Python script with the active interpreter. |
| `visus version` | Print the `visus.web` version. |
| `visus devices [--json]` | The device presets `session start --device` accepts: name, viewport, device-pixel-ratio and the mobile flag. An unknown `--device` is refused AT START with this list, not shrugged off. |

### Not in the CLI (yet)

These exist in the Python library and/or the MCP server but have no shell
command: network request log, browser console log, storage state save/load,
standalone keyboard/mouse, network mocking, tracing start/stop, named
sessions, `attach`/`detach`. Reach them with `visus eval`, the MCP server, or
the library — see [library-api.md](library-api.md) and [mcp-tools.md](mcp-tools.md).
