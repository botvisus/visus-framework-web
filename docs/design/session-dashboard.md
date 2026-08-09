# Design — the multi-session dashboard

> Status: **designed, spike landed, and the blocker has since been LIFTED.** The
> spike is `visus.web.cli.fleet.render_fleet`, covered by six tests in
> `tests/test_cli_fleet.py`.

## Blocked — and then unblocked

When this design was written the feature could not be built: `start_daemon`
refused a second session outright, and discovery walked upward git-style, so
starting in a subfolder of a project that already had a session silently bound to
the parent's. A fleet view would have been a view over a set of size one, for
ever. The stated go/no-go was PLAN 6's named sessions.

**PLAN 6 has since landed.** Every unblocking symbol now exists:

| Needed | Now shipping |
|---|---|
| `--session` / `-S`, `VISUS_WEB_SESSION` | root callback in `cli/main.py` |
| `.visus/sessions/<name>.json` | `session_server.session_file` |
| Cross-project registry | `~/.visus/sessions/` via `session_server.registry_file`, `VISUS_WEB_HOME` |
| Collection | `session_client.list_sessions` |
| Liveness | memoised `_pid_alive`, uncached `_probe_pid` |
| Teardown | `session close-all` / `kill-all` / `delete-data` |

**So the honest current state is not "blocked" but "already half-built twice".**
PLAN 6 shipped both the collector *and* a first renderer (`visus session list`,
columns `NAME SCOPE STATE PID PORT ENGINE URL DIR`). The remaining work is
**reconciliation**, not construction — see *Rendering* below.

## What the fleet view is for

Three concrete jobs, and each survives the fact that a first renderer exists:

1. **Find the abandoned daemon** holding a headed browser somewhere else on disk.
   This was the strongest motivation and it is exactly what PLAN 6's registry now
   makes possible.
2. **Pick which session to point the next command at**, without remembering what
   is running where.
3. **For an agent: choose a session by the page it is on**, rather than by
   recalling a name. This is the one the shipped `session list` serves *least*
   well — see below.

## Collection

Solved by PLAN 6, and worth recording how, because it is the part that was
genuinely hard:

- Local sessions come from the same upward walk commands use.
- Sessions in *other* project trees come from a registry under `~/.visus/`,
  keyed by a hash of the absolute cwd. Before it, a daemon started in another
  project was invisible **and unkillable** from the CLI.
- The registry entry carries **no token** — the secret stays in the owner-only
  session file — so `close-all` can shut a session down politely when entitled
  and fall back to `kill-all` when not.
- Liveness uses the **memoised** `_pid_alive`, not `_probe_pid`. This matters on
  Windows, where each probe spawns `tasklist` with a 5-second timeout; one per
  row per invocation is the cost ceiling, and the memo is what keeps it there.

## Rendering — what the spike settled

The open question was *what does a fleet row need to show for the view to be
worth building at all*. The spike settled a column set and two rules:

- **A missing field never raises.** These dicts come from files other processes
  wrote, possibly mid-write or from an older version. A fleet view that crashes
  on one bad row is worse than no fleet view.
- **A dead row names its fix** (`visus session kill`). A dashboard that reports a
  problem without the remedy just moves the work.

Two columns differ from the shipped `visus session list` and are the substance of
the reconciliation:

| `render_fleet` | `session list` | Which is right |
|---|---|---|
| `MODE` (headed / headless) | *(absent)* | **`render_fleet`.** "Which of these is the visible one?" is the first question when hunting an abandoned browser. |
| `PAGE` — title, falling back to URL | `URL` only | **`render_fleet`.** A title answers "is this the session I want?" far faster than a URL, and the URL remains the fallback. |
| *(absent)* | `SCOPE` (local / other) | **`session list`.** Knowing a session belongs to another project is what makes the registry useful. |

**Recommendation:** fold `MODE` and the title-preferring `PAGE` column into
`session list`, keep `SCOPE`, and retire `render_fleet` — one renderer, not two.
Until then `fleet.py` is a tested reference for the columns that are missing.

## Command surface

Shipped by PLAN 6: `visus session list [--json]`, `visus session close-all`,
`visus session kill-all`, `visus session delete-data`.

## Why this ranked below `annotate`

`annotate` gives an agent a channel it does not have at all. The dashboard gives
a human a nicer view of state they could already reach one directory at a time.
That ordering was right, and it is why this shipped as a renderer and a document
while `annotate` got the harder primitive.

## Acceptance criteria

- ✅ `visus session list` shows every live session in the current tree plus every
  registered session elsewhere.
- ✅ A killed daemon shows as `dead` and `visus session kill-all` removes it.
- ✅ `visus session list --json` emits one array with the same fields the table
  shows.
- ✅ The view costs at most one liveness probe per session per invocation.
- ⬜ The table shows the browser mode and prefers the page title — the
  reconciliation above.

## Not in scope

- An HTTP dashboard.
- A TUI.
- Remote / Grid sessions: they have no local `.visus/` and no pid to probe.
