# The interactive REPL

```bash
visus repl                    # attach to the running session
visus repl https://example.com --headless
```

`visus console` is a deprecated alias that still opens the REPL (it prints a
notice on stderr). The plain name now belongs to the browser's console
messages: those are `visus logs`.

If no session is running, `visus repl` **starts one** — headed unless you
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

The REPL takes the **same targets as the CLI**: a field index (`click 3`), a bare
selector (`click #submit`, `click //button[1]`), or flags
(`click --selector #go`, `click --role button --name Save`,
`click --text Save --exact`). As in the CLI, `--name` alone is not a target.

Every command that changes the page (`click`, `fill`, `goto`, `tab`, …) prints
the same `### Code` / `### Page` footer the non-interactive CLI prints, so you
see the URL and title the action produced without a separate `url` / `title`
round trip.

## Full vocabulary

```
targets: a field index (`3`), a bare selector (`#submit`, `//button[1]`),
         or flags (`--selector #go`, `--role button --name Save`, `--text Save [--exact]`).

list [full]          enumerate interactive fields (`full` adds CSS/XPATH)
click TARGET         click the target
fill TARGET text     fill the target with text
check TARGET         check the target
uncheck TARGET       uncheck the target
select TARGET value  select option `value` on the target
press [TARGET] key   press a key on the target, or on the page with no target
hover TARGET         hover over the target
dblclick TARGET      double-click the target
focus TARGET         focus the target
clear-input TARGET   clear the target's value
upload TARGET p...   set file(s) on a file input (paths resolved locally)
drag TARGET TARGET   drag the first target onto the second
goto url             navigate to url
back / forward / reload
title / url          print the page title / current URL
snapshot [sel]       list interactive elements (REF/role/name), optionally scoped
find text            grep the snapshot, with 3 rows of context around each hit
text TARGET          print the target's text content
attr name TARGET     print the target's attribute value
count TARGET         count elements matching the target
wait TARGET [state]  wait until the target is visible/hidden
expect TARGET text   assert the target contains text (PASSED/FAILED)
cookies              list cookies for the context
add-cookies json     add cookies from a JSON list
clear-cookies        clear every cookie in the context
eval expr            evaluate a JS expression
dialog [dismiss]     handle the next dialog (accept by default)
screenshot [path]    save a screenshot (default screenshot.png)
export-script [path] print (or save) this session as a runnable visus.web script
read-text TARGET     OCR the target and print the text
solve-captcha TARGET OCR-solve a text CAPTCHA in the target
find-image f [T] [c] find template image `f` (optional target, confidence)
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

Only `translate` — a standalone command that parses pasted HTML rather than a
session op. Everything else the CLI reaches, the REPL reaches.

## Errors inside the REPL

A daemon failure prints `error: <message>` and the REPL keeps running (unlike
the CLI, it never exits the process). A missing argument prints a message of
the form:

```
missing argument for `<cmd>` (try `help`)
```

and a target that is absent or malformed prints:

```
bad argument for `click`: provide a field index, a selector, or --selector/--role/--text
```

rather than a Python traceback. An unrecognized command prints:

```
unknown command '<cmd>' (try `help`)
```

`Ctrl-D` (EOF) or `Ctrl-C` also exits the REPL cleanly, same as `quit` — the
session is never touched.
