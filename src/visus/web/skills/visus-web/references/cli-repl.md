# The interactive REPL

```bash
visus console                 # attach to the running session
visus console https://example.com --headless
```

If no session is running, `visus console` **starts one** — headed unless you
pass `--headless`. `quit` exits the REPL and leaves the session alive.

The REPL is a shorter dialect of the CLI, not a different tool. Six names
differ:

| REPL | CLI |
|---|---|
| `list` | `visus list-fields` |
| `text N` | `visus get-text N` |
| `attr href N` | `visus get-attribute href N` |
| `expect N some words` | `visus expect-text N "some words"` |
| `screenshot [path]` | `visus session-screenshot -o path` |
| `highlight-all` | `visus list-fields --highlight` |

The REPL targets **only by integer index** — `click #submit` is not accepted.
Use the CLI when you need `--selector` / `--role` / `--text`.

Every command that changes the page (`click`, `fill`, `goto`, `tab`, …) prints
the same `### Code` / `### Page` footer the non-interactive CLI prints, so you
see the URL and title the action produced without a separate `url` / `title`
round trip.

## Full vocabulary

```
list [full]          enumerate interactive fields (`full` adds CSS/XPATH)
click N              click field N
fill N text          fill field N with text
check N              check field N
uncheck N            uncheck field N
select N value       select option `value` on field N
press N key          press key on field N
hover N              hover over field N
dblclick N           double-click field N
focus N              focus field N
clear-input N        clear field N's value
goto url             navigate to url
back / forward / reload
title / url          print the page title / current URL
snapshot [sel]       list interactive elements (REF/role/name), optionally scoped
find text            grep the snapshot, with 3 rows of context around each hit
text N               print field N's text content
attr name N          print field N's attribute value
count N              count elements matching field N
wait N [state]       wait until field N is visible/hidden
expect N text...     assert field N contains text (PASSED/FAILED)
cookies              list cookies for the context
eval expr            evaluate a JS expression
dialog [dismiss]     handle the next dialog (accept by default)
screenshot [path]    save a screenshot (default screenshot.png)
export-script [path] print (or save) this session as a runnable visus.web script
clear                remove the field highlight overlay
highlight-all        redraw the numbered field overlay for every field
tabs                 list open tabs/windows (active marked *)
tab N                switch to tab/window N (omit N = newest)
tab-new [url]        open a new tab (optionally at url)
tab-close [N]        close tab N (omit N = active)
help                 show this help
quit                 exit the console (the session stays alive)
```

`help` (or `?`) prints this same list inside the running REPL.

## What the REPL does not cover

Nine operations the CLI exposes have **no REPL equivalent** — drop to `visus
<command>` for these:

- `upload` — setting files on a file input
- `drag` — dragging a source element onto a target
- `add-cookies` / `clear-cookies` — the REPL's `cookies` is read-only
- `read-text`, `solve-captcha`, `find-image` — the vision commands
- `browser_tab_activate`-style manual tab follow toggling and `translate` (a
  standalone command, not a session op)

## Errors inside the REPL

A daemon failure prints `error: <message>` and the REPL keeps running (unlike
the CLI, it never exits the process). A missing argument prints a message of
the form:

```
missing argument for `<cmd>` (try `help`)
```

rather than a Python traceback. An unrecognized command prints:

```
unknown command '<cmd>' (try `help`)
```

`Ctrl-D` (EOF) or `Ctrl-C` also exits the REPL cleanly, same as `quit` — the
session is never touched.
