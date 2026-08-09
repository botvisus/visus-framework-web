# The MCP server

```bash
pip install "visus-web[mcp]"
visus-web-mcp          # stdio; `visus mcp` is the same thing
```

**47 tools**. By default they drive the server's OWN browser, a *different
process* from the CLI session daemon and with opposite defaults — headless, and
new tabs are **not** followed automatically.

Call `browser_attach_session` to drive the CLI daemon's browser instead. Attached,
every tool crosses to that daemon, so the model and the human share one page, one
session and one field-index vocabulary; the server closes its own browser first,
so there is never a second invisible one. `browser_detach_session` returns to the
server's own browser and leaves the `visus` session running — and `browser_close`
detaches rather than closing a browser that is not the server's to close.

The server also serves this skill: resource `visus://skill/SKILL.md`, resource
template `visus://skill/references/{name}`, and the prompt
`visus_web_quickstart`.

## Client config

```jsonc
// claude_desktop_config.json (or ~/.claude.json / .mcp.json for Claude Code)
{
  "mcpServers": {
    "visus-web": {
      "command": "visus-web-mcp",
      "env": {
        "VISUS_WEB_ENGINE": "chrome",   // chrome | edge | firefox | edge_ie
        "VISUS_WEB_HEADLESS": "1"       // "0" to watch the browser drive
      }
    }
  }
}
```

## The 47 tools, by group

| Group | Tools |
|---|---|
| Navigation | `browser_navigate`, `browser_navigate_back`, `browser_navigate_forward`, `browser_reload` |
| Inspect | `browser_snapshot`, `browser_list_fields`, `browser_clear_highlights`, `browser_translate_element`, `browser_title`, `browser_url`, `browser_get_text`, `browser_get_attribute`, `browser_count` |
| Actions | `browser_click`, `browser_dblclick`, `browser_fill`, `browser_press`, `browser_hover`, `browser_check`, `browser_uncheck`, `browser_select_option`, `browser_drag`, `browser_focus`, `browser_clear`, `browser_set_input_files` |
| Wait / expect | `browser_wait_for`, `browser_expect_text` |
| Tabs | `browser_tab_list`, `browser_tab_new`, `browser_tab_select`, `browser_tab_activate`, `browser_tab_close`, `browser_set_tab_follow` |
| Dialogs | `browser_handle_dialog` |
| Network / console *(Chromium)* | `browser_network_requests`, `browser_console_messages` |
| Cookies | `browser_get_cookies`, `browser_add_cookies`, `browser_clear_cookies` |
| Media / JS | `browser_screenshot`, `browser_evaluate` |
| Vision *(`[vision]`)* | `browser_read_text`, `browser_solve_captcha`, `browser_find_image` |
| Lifecycle | `browser_close` |
| Attach | `browser_attach_session`, `browser_detach_session` |

That is 4 + 9 + 12 + 2 + 6 + 1 + 2 + 3 + 2 + 3 + 1 + 2 = **47**, pinned by
`tests/test_mcp_server.py`.

**Recommended agent flow:** `browser_navigate` → `browser_snapshot` (read the
role/name table) **or** `browser_list_fields` (numbered, with ready-to-use
locators) → act with `browser_click` / `browser_fill` / … targeting by
`role`+`name`, `text`, or `selector` → `browser_wait_for` /
`browser_expect_text` to synchronize.

Every **Actions** tool returns its result followed by a `### Page` block naming
the URL and title the action produced:

```
clicked

### Page
- URL: http://shop.test/cart
- Title: Your cart
```

So you do not need a `browser_url` / `browser_title` call after an action just
to learn where you ended up. Page state is best-effort: if the page cannot be
read the tool returns the bare result rather than failing the action.

## Target parameters

Every action tool accepts the same **target** parameters — provide whichever
you have:

| Param | Meaning |
|---|---|
| `selector` | A CSS selector, `xpath=…`, or a pasted DevTools element (`<…>`). |
| `role` + `name` | ARIA role and accessible name (e.g. `role="button"`, `name="Sign in"`). |
| `text` | Visible text content. |
| `exact` | Match `name`/`text` exactly instead of as a substring. |
| `frame` | CSS/XPath of an `<iframe>` to resolve the target inside. |

Note what is **not** here: MCP tools take no integer `index` parameter — that
targeting mode is CLI-only (`visus click 3`), backed by the CLI daemon's field
cache. From MCP, target by `role`/`name`/`text`/`selector`, or read
`browser_list_fields`'s returned locators and pass those back as `selector`.

## Tab follow — manual by default

New tabs/popups are **manual** by default (`browser_set_tab_follow(False)`): a
click that opens a tab does not change your context — steer explicitly with
`browser_tab_list` / `browser_tab_select`. Set `browser_set_tab_follow(True)`
for auto-follow. This is the opposite default from the CLI session daemon,
which auto-follows new tabs — see [cli-session.md](cli-session.md).

## Tools that exist only in MCP

Four tools have no CLI equivalent:

- `browser_network_requests` / `browser_console_messages` — Chromium network
  and console capture, exposed to agents without a library-level
  `NetworkCapture` object.
- `browser_tab_activate(handle)` — focuses a tab by its **stable handle**
  (from `browser_tab_list`), which survives tab reordering; the CLI's
  `visus tab <idx>` targets by position instead.
- `browser_set_tab_follow(enabled)` — the toggle described above; the CLI has
  no equivalent because it always auto-follows.
