# Targeting an element from the shell

Every action, read, wait and assertion command takes the **same** target
grammar. There are exactly two ways to name an element.

## 1. By index (preferred)

```bash
visus list-fields          # prints a numbered table AND draws numbered boxes on the page
visus fill 2 ada@example.com
visus click 7
```

`list-fields` emits six columns: `#`, `KIND`, `NAME`, `VISUS (copy-paste)`,
`CSS`, `XPATH`. The `VISUS` column is a ready Python expression, generated
**frame-aware** — if the element sits inside an iframe it is already wrapped in
`frame_locator(...)`, so pasting it into a script works.

Index targeting is the only form that transparently reaches **through iframes
and open shadow roots**: the daemon stores the frame chain with the field and
re-walks it on every action, then re-resolves with `deep=` for shadow DOM. There
is no extra syntax — `visus click 3` reaches an element three iframes deep.

**Indexes belong to the page you listed them on.** They are a cache, refreshed
only by `list-fields`. After `goto`, `back`, `forward`, `reload`, a form submit,
or a click that navigates, run `list-fields` again. Acting on a stale index is
the single most common way to click the wrong element.

Out-of-range indexes are rejected loudly:

```
error: IndexError: field index 9 out of range (have 4; run list_fields first)
```

Filter a long page instead of paging through it:

```bash
visus list-fields --kind input,button        # kinds: input textarea editable button
visus list-fields --kind link,checkbox       #        link checkbox radio select dropdown
visus list-fields --all                      # include hidden/disabled fields
visus list-fields --highlight                # opt in to the numbered overlay
visus clear                                  # remove the overlay afterwards
```

The overlay injects marker elements into the page, so it is **off by default** —
a plain `visus list-fields` leaves the DOM untouched and later screenshots, OCR
and `find-image` stay clean. Turn it on with `--highlight` when a human is
watching a headed browser or a vision model has to read the numbers, and run
`visus clear` when you are done.

## 2. By selector / role / text

```bash
visus click --role button --name "Sign in"
visus click --text "Add to cart"
visus click -s "#submit"
visus click -s "//button[@type='submit']"          # xpath is auto-detected
visus fill  -s "#username" --value student         # note: --value, not a positional
```

| Flag | Meaning |
|---|---|
| `--selector` / `-s` | CSS, XPath, or a pasted DevTools element (`<input …>`) |
| `--role` | ARIA role: `button`, `link`, `heading`, `textbox`, `checkbox`, … |
| `--name` | Accessible name — **a qualifier for `--role`, not a target on its own** |
| `--text` | Visible text (substring, case-insensitive) |
| `--exact` | Match `--role`/`--text` exactly instead of by substring |
| `--frame` | CSS selector of the iframe holding the target |

`--exact` and `--frame` are modifiers, not targets — they refine whichever of
the four forms above you used, and they work with an index target too
(`visus get-text 2 --frame "#checkout"`). Both are accepted by every targeted
command: `click`, `fill`, `check`, `uncheck`, `select`, `press`, `get-text`,
`get-attribute`, `count`, `hover`, `dblclick`, `focus`, `clear-input`, `drag`,
`upload`, `wait`, `expect-text`, `read-text`, `solve-captcha` and
`session-screenshot`.

**`--name` alone is not a target.** The guard in `_target_args`
(`src/visus/web/cli/main.py`) only accepts an index, `--selector`, `--role` or
`--text` — `--name` is not in that check, so a command carrying just `--name`
exits 1 (on **stderr**) with:

```
error: no target. Use one of:
  visus <cmd> <INDEX>              a number from `visus list-fields`
  visus <cmd> --selector '#id'     a CSS or XPath selector
  visus <cmd> --role button        an ARIA role (--name refines it)
  visus <cmd> --text 'Sign in'     the element's visible text
--name alone is NOT a target; it only qualifies --role.
Run `visus list-fields` to see what is on the page.
```

So `visus click --name Submit` fails, while `visus click --role button --name Submit`
works. This is the most common CLI mistake.

## Precedence and the `--text` collision

- A positional index **wins** over every flag. `visus click 3 --role button`
  clicks field 3.
- Order of resolution among the flags: `--role` (with `--name`), then `--text`,
  then `--selector`.
- On `fill`, `select`, `press` and `expect-text` the **positional** second
  argument is the *value*, and `--text` is the *target*. When you target by
  role/selector/text you must pass the value through its own flag:

```bash
visus fill 2 hunter2                          # index + positional value
visus fill -s "#pwd" --value hunter2          # selector + --value
visus select 5 US                             # index + positional value
visus select --role combobox --name Country --value US
visus press 2 Enter                           # index + positional key
visus press -s "#pwd" --key Enter
visus expect-text 0 "Welcome"                 # index + positional expectation
visus expect-text --role heading --expected "Welcome"
```

Passing no value at all exits 1, e.g.:

```
error: no text to fill — use `visus fill <index> <text>` or `--value`
```

## Strict matching and iframes

The daemon supports `exact` matching and an explicit `frame` selector, but **no
CLI flag sets them today** — from the shell, reach an element inside an iframe
by its `list-fields` index, or use the MCP server's `exact` / `frame`
parameters. `--role` name matching and `--text` are substring, case-insensitive.

If a selector matches more than one element, single-element operations raise
`StrictModeViolation`. Narrow with `--role` + `--name`, or list the fields and
use an index.

## Getting a selector out of DevTools

Right-click the element → *Copy* → *Copy element*, then:

```bash
visus translate                # reads the clipboard, prints tag/id/name/css/xpath
visus translate --file el.html
visus translate '<input name="email" class="…">' --json
```

`visus translate` is the only command that needs no running browser. It also
prints the ordered candidate list the smart locator will try, so you can see
which selector will actually win.
