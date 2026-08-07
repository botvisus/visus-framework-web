# Quoting on Windows

`visus` is a Windows-first tool and Windows shells mangle the characters
selectors are made of. `visus translate` exists precisely because of this — it
reads a DevTools "Copy element" blob straight off the clipboard so `<`, `>` and
`"` never touch the command line.

| Value | PowerShell | cmd.exe | bash / zsh |
|---|---|---|---|
| CSS `#user` | `visus click -s '#user'` | `visus click -s "#user"` | `visus click -s '#user'` |
| XPath with quotes | `visus click -s '//button[@id="go"]'` | `visus click -s "//button[@id='go']"` | `visus click -s '//button[@id="go"]'` |
| JS arrow fn | `visus eval '() => document.title'` | `visus eval "() => document.title"` | `visus eval '() => document.title'` |
| JSON cookies | `visus add-cookies '[{"name":"a","value":"b","url":"http://x"}]'` | use a here-file, cmd cannot nest quotes | same as PowerShell |

In PowerShell, **single quotes are literal** — prefer them. Double quotes
interpolate `$`, which will silently eat a jQuery-style selector.

## Why this matters more than usual

`visus` selectors are frequently CSS attribute selectors, XPath, or pasted
HTML — all rich in `<`, `>`, `"`, `'`, `$`, and `[...]`. PowerShell's own
grammar overlaps every one of those characters:

- `$` starts variable interpolation inside double quotes — a selector like
  `"div[data-id=$x]"` silently substitutes an (empty) `$x`.
- `<` and `>` are redirection operators outside quotes.
  cmd.exe interprets `<input>` the same way — always quote HTML fragments.
- Backticks are PowerShell's escape character, not a literal.

## `--%` — the stop-parsing token

For an argument PowerShell's own parser mangles no matter how you quote it
(nested quotes, literal backticks), put `--%` before it — PowerShell passes
everything after `--%` through to the process verbatim, unparsed:

```powershell
visus eval --% "(x) => x.replace(`"a`", `"b`")"
```

## Here-strings for JSON payloads

A `[{"name":"a","value":"b","url":"http://x"}]`-shaped JSON argument is
awkward on one line in cmd.exe (which cannot nest double quotes at all). In
PowerShell, build it with a single-quoted here-string first:

```powershell
$cookieJson = @'
[{"name":"a","value":"b","url":"http://x"}]
'@
visus add-cookies $cookieJson
```

## The clipboard path — avoid quoting entirely

The safest option is to never put the selector on the command line:

```powershell
# Right-click the element in DevTools -> Copy -> Copy element, then:
visus translate               # reads Get-Clipboard -Raw, prints tag/id/css/xpath
visus list-fields             # or just target by index — no quoting at all
```

`visus translate`'s clipboard fallback shells out to
`powershell -NoProfile -Command "Get-Clipboard -Raw"` (or `pbpaste` on macOS,
`xclip` on Linux) — it works from any shell, including a plain cmd.exe
session, because *you* never type the HTML.

See [cli-targeting.md](cli-targeting.md) for the full target grammar and
[cli-commands.md](cli-commands.md) for every flag `translate` accepts.
