# The session daemon

`visus` is a thin client over a background browser process. The daemon owns the
browser; every command is a one-line JSON request to it.

```bash
visus session start https://example.com   # headed by default
visus session start --headless --engine edge
visus session status                      # pid, port, engine, url, title, fields_cached
visus session stop                        # closes the browser and deletes .visus/
```

## Where the session lives

`session start` writes `.visus/session.json` (pid, port, token, engine, url) in
the directory you ran it from, plus `.visus/session.json.lock` and
`.visus/daemon.log`. Every other command searches **upward** from the current
directory, git-style, for `.visus/session.json`. So a session started at a repo
root serves every subdirectory — and a sibling directory outside that chain gets
its own daemon.

A session is considered live only when its pid is alive **and** its port
accepts a connection. A file that fails either check is deleted automatically.

## Starting

```bash
visus session start [URL] --engine chrome|edge|firefox|edge_ie --headless
```

If a live session is already found at or above the current directory, `start`
fails with `error: a session is already running (pid <p>, port <port>)` rather
than launching a second browser — there is no way to run two named sessions in
one directory tree.

Under the hood, `start` spawns `python -m visus.web.cli.session_server` as a
**detached** background process (on Windows: `DETACHED_PROCESS |
CREATE_NEW_PROCESS_GROUP`; elsewhere: a new session group) so it survives the
parent shell exiting, and blocks for up to 20 seconds polling
`.visus/session.json` until the daemon's socket accepts a connection. If it
never comes up, `start` fails with
`error: daemon did not come up within 20s (see <cwd>/.visus/daemon.log)` — the
log's tail names the real exception (browser missing, driver missing, a stale
lock file).

## Stopping

`visus session stop` sends a `shutdown` op over the socket, waits up to 10
seconds for `.visus/session.json` to disappear, then deletes it itself if the
daemon didn't. It always prints a status message and never raises — with no
session running it prints `no session running` and exits 0.

## Status

`visus session status [--json]` reports:

| Key | Meaning |
|---|---|
| `pid`, `port` | The daemon process and its socket. |
| `engine`, `headless` | What it was started with. |
| `url`, `title` | The active tab's current URL/title (only while a browser is actually running). |
| `windows` | Count of open tabs/windows. |
| `active_tab` | Index of the tab the session is currently driving. |
| `fields_cached` | Size of the `list-fields` index cache — `0` until you run `list-fields`. |

With no session running it prints `no session running` and exits **1** (unlike
`session stop`, which exits 0 either way).

## The index cache

`list-fields` walks the DOM once and caches the numbered result inside the
daemon. Every index-targeted command (`click 3`, `fill 2 …`) resolves against
that cache — it is **not** re-queried per action. The cache is invalidated only
by running `list-fields` again; it is not cleared automatically by `goto`,
`back`, `forward`, `reload`, or a navigating click. Acting on a stale index
after the page changed is the most common CLI mistake — see
[cli-targeting.md](cli-targeting.md).

## Tabs and popups

The session tracks every open tab/window handle. Opening a new tab or popup
(a target-blank link, `window.open`, `visus tab-new`) **auto-follows** it — the
session's active tab switches to the newest handle it hasn't seen before. Use
`visus tabs` to list handles and `visus tab <idx>` to switch back. This is the
opposite of the MCP server's default (manual tab follow) — see
[mcp-tools.md](mcp-tools.md).

Closing the active tab picks another live handle automatically; closing the
**last** tab tears down the browser (`visus tab-close` reports
`closed the last tab — session stopped`), but the daemon process itself stays
up — the next command relaunches a fresh browser at the session's original URL,
which means you are logged out. Prefer `visus session stop` for a clean end.

## Commands with their own browser

Five commands never touch the session daemon — each launches and closes its
**own** throwaway browser, so they work with no session running and never see
session state (cookies, current page, logged-in state):

| Command | What it launches |
|---|---|
| `visus open <URL>` | Opens (or navigates) in the session and prints the page, numbered; the browser stays open. `--wait`: a one-off browser closed with Enter. |
| `visus screenshot <URL> -o <png> --headless --engine <e>` | A one-off browser to capture a PNG. |
| `visus pdf <URL> -o <pdf>` | A one-off Chromium browser to print a PDF. |
| `visus codegen <URL> -o <file> --engine <e>` | A headed browser that records your interactions. |
| `visus run <script.py>` | No browser at all — just runs a Python script with the active interpreter. |

The session's own screenshot command is `visus session-screenshot`, not
`visus screenshot` — see [troubleshooting.md](troubleshooting.md) for that
exact mix-up.
