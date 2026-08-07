# The Python API

```python
from visus.web import launch, rpa, expect, Engine, Field, errors, tracing

with launch(headless=True) as browser:      # engine defaults to chrome
    page = browser.new_page()
    page.goto("https://example.com")
    page.get_by_role("button", name="Sign in").click()   # auto-waits
    page.get_by_label("Email").fill("ada@example.com")
    expect(page.get_by_text("Welcome")).to_be_visible()  # auto-retries
```

Four rules carry most of the reliability:

- **Auto-wait** — every action waits for visible / stable / enabled / editable /
  hit-testable before acting. **Never add `sleep`.**
- **Web-first assertions** — `expect(loc).to_*()` re-checks until it passes or the
  timeout elapses (5 s by default).
- **Lazy locators** — a `Locator` is a recipe, re-resolved on every use. No stale
  element errors.
- **Strict mode** — a single-element op on a locator matching >1 element raises
  `StrictModeViolation`. Disambiguate with `.first()` / `.last()` / `.nth(i)`.

Timeouts are **milliseconds** (action/navigation 30 000, `expect` 5 000).

## What `visus.web` exports

`src/visus/web/__init__.py` re-exports: `launch`, `rpa`, `expect`, `Engine`,
`Browser`, `Context`, `Page`, `Field`, `errors`, `tracing`, `is_active`,
`save_screenshot`.

```python
launch(engine="chrome", *, headless=False, slow_mo=0, user_data_dir=None, remote_url=None) -> Browser
```

- `slow_mo=300` — delay every action/navigation by that many milliseconds, to
  watch a script drive the page in real time (debug/demo).
- `user_data_dir="~/profiles/erp"` — reuse (or create) a persistent browser
  profile instead of a throwaway temp one: cookies, localStorage and logins
  survive across runs. `visus` never deletes this directory.
- `remote_url="http://grid:4444/wd/hub"` — drive a **Selenium Grid** /
  Remote WebDriver session instead of a local browser.

## Locators

```python
page.get_by_role("button", name="Sign in")     # ARIA role + accessible name
page.get_by_role("link", name="Docs", exact=True)
page.get_by_text("Welcome back")                # visible text (substring)
page.get_by_label("Email")                      # form control by its <label>
page.get_by_placeholder("Search…")
page.get_by_test_id("submit")                   # data-testid
page.get_by_alt_text("Company logo")
page.get_by_title("Close")
page.locator("#username")                       # CSS
page.locator("xpath=//button[@type='submit']")  # XPath
page.locator(".row").locator("css=button")      # chain

# Regex — every text matcher takes a compiled re.Pattern
import re
page.get_by_text(re.compile(r"order #\d+", re.I))

# Refinement
page.get_by_role("listitem").filter(has_text="In stock").first()
page.get_by_role("row").nth(2)
page.locator(".card").last()
page.locator("#shadow-host").locator("button", deep=True)   # pierce open Shadow DOM

# Composition — disambiguate without XPath
page.locator("tr").filter(has=page.get_by_role("button", name="Edit"))
page.locator("tr").filter(has_not_text="archived")
page.locator("#save").or_(page.locator("#submit")).click()   # whichever exists
page.locator("input").and_(page.locator(".touched"))         # intersection
```

Paste-an-element locator — copy an element's `outerHTML` from DevTools straight
into a locator; Visus derives an ordered candidate list (id → `data-*` → name →
aria → class → xpath) and tries each:

```python
page.locator('<input name="email" class="form-control w-full" type="email">').fill("ada@x.com")
```

## Auto-waited actions

```python
loc.click(); loc.dblclick(); loc.hover(); loc.focus(); loc.blur()
loc.fill("hello"); loc.clear(); loc.press("Enter"); loc.press("Control+a")
loc.check(); loc.uncheck(); loc.set_checked(True)
loc.select_option(value="US")            # or label="United States" / index=0
loc.set_input_files("invoice.pdf")       # or ["a.png", "b.png"]
src.drag_to(target)
```

All accept `timeout=<ms>`, most accept `force=True` (skip actionability
checks) and `backtrack` (`True`, or an integer count — replays the previous
step(s) before retrying; see [tracing-reports.md](tracing-reports.md)).

## Reads

```python
loc.count(); loc.is_visible(); loc.is_enabled(); loc.is_checked()
loc.text_content(); loc.inner_text(); loc.inner_html(); loc.input_value()
loc.get_attribute("href"); loc.bounding_box()   # {x, y, width, height} | None
loc.all_text_contents(); loc.all_inner_texts()
```

## `expect()` — web-first assertions

```python
from visus.web import expect

expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
expect(page.get_by_label("Email")).to_have_value("ada@example.com")
expect(page.get_by_role("listitem")).to_have_count(3)
expect(page.get_by_text("Error")).not_.to_be_visible()          # .not_ negates

# Page-level assertions
expect(page).to_have_url("*checkout*")
expect(page).to_have_title(re.compile("Dashboard"))

# Custom failure message — prefixed onto the AssertionError
expect(page.locator("#cart"), "cart should appear after adding an item").to_be_visible()

# Soft assertions — collect failures, fail once at the end
expect.soft(page.locator("#price")).to_have_text("$10")
expect.soft(page.locator("#qty")).to_have_value("2")
expect.verify_soft()   # raises ONE combined error if anything failed
# (the pytest plugin calls verify_soft() automatically at the end of each test)
```

Full matcher set: `to_be_visible / to_be_hidden / to_be_enabled / to_be_disabled
/ to_be_checked / to_be_editable / to_be_attached / to_be_focused / to_be_empty
/ to_be_in_viewport / to_have_text(exact=True) / to_contain_text / to_have_value
/ to_have_values / to_have_count / to_have_attribute(name, value) / to_have_class
/ to_contain_class / to_have_role / to_have_css(name, value) / to_have_id`. Text,
value, attribute and CSS matchers all accept a compiled `re.Pattern`.

## Field enumeration — the library twin of the CLI's index model

```python
fields = page.list_fields(kinds=["input", "button"], include_hidden=False, highlight=True)
for f in fields:
    print(f.index, f.kind, f.name, f.locator)

page.field(0).fill("student")             # act by number (from the latest list_fields)
page.field_locator(fields[1]).fill("…")   # or by the Field object (resolves frame/shadow chain)
page.clear_highlights()
```

Each `Field` carries `index, kind, tag, type, role, name, label, placeholder,
value, checked, disabled, visible, frame, shadow, locator, locator_kind, css,
xpath, code, deep` and a `.to_dict()`. This is exactly what `visus list-fields`
and `browser_list_fields` are backed by — `page.field(n)` is `visus click n` at
the library level. For durable automation prefer a stable selector over the
positional index.

## Frames, tabs, dialogs, downloads, cookies

```python
frame = page.frame_locator("#checkout-iframe")
frame.get_by_label("Card number").fill("4242 4242 4242 4242")

with page.expect_popup() as popup:
    page.get_by_role("link", name="Open in new tab").click()
new_page = popup.value

with page.expect_dialog(accept=True, prompt_text="yes") as dlg:
    page.get_by_role("button", name="Delete").click()

with page.expect_download() as dl:
    page.get_by_role("button", name="Export CSV").click()
dl.value.save_as("./reports/export.csv")

ctx = browser.new_context()                 # isolated cookies/cache
ctx.add_cookies([{"name": "session", "value": "abc", "url": "https://example.com"}])
ctx.clear_cookies()
```

## Engines

| String | `Engine` member | Notes |
|---|---|---|
| `"chrome"` | `Engine.CHROME` | Default. Full feature set (PDF, CDP network controls). |
| `"edge"` | `Engine.EDGE` | Chromium-based; same features as Chrome. |
| `"firefox"` | `Engine.FIREFOX` | No CDP-only features (PDF / network controls). |
| `"edge_ie"` | `Engine.EDGE_IE` | Edge in **IE mode** (Trident), Windows-only — for legacy corporate apps. |

## `NetworkCapture` — reverse-engineering the API behind a page

Two layers feed one scrubbed request list: a **JS hook** (patches `fetch`,
`XMLHttpRequest`, `navigator.sendBeacon`, and dynamically-inserted
`<script>`/`<img>` `src` — catching JSONP and pixel pings, not just fetch/XHR)
and, on Chromium, the **CDP Network domain** (fills in status, resource type
and request headers, and catches everything the JS hook alone would miss,
including top-level navigations). The two are merged and de-duplicated;
**both request and response bodies are kept**, and every header dict is passed
through `scrub_headers()`, which redacts `authorization`, `cookie`,
`set-cookie`, `proxy-authorization`, `x-api-key`, `x-auth-token`,
`x-session-id`, and anything matching `x-*-(token|key|auth|session|secret)` to
the literal string `"REDACTED"` before you ever see it.

```python
from visus.web.network import NetworkCapture

cap = NetworkCapture(page)
cap.start()                      # install the hook BEFORE interactions
page.goto("https://example.com")
page.get_by_role("button", name="Load more").click()
for r in cap.get_requests(filter_type=["xhr", "fetch"]):
    print(r["method"], r["url"], r["status"])
cap.export_enriched("capture.json")   # {target_url, entries} — scrubbed
```

The higher-level, page-scoped equivalents cover the common case without
building a `NetworkCapture` yourself:

```python
with page.expect_response("*api/login*") as info:
    page.get_by_role("button", name="Sign in").click()
assert info.value.ok
print(info.value.body())

for r in page.network_requests():
    print(r.status, r.url)
for m in page.console_messages():
    print(m.level, m.text)
```

## `visus.web.async_api` — a 100% mirror

`visus.web.async_api` mirrors the sync surface with the same names and the
same parameter names, wrapped in `asyncio.to_thread` — porting sync code is a
mechanical `await` insertion. Builders (`get_by_*` / `locator` / `first` /
`last` / `nth` / `filter` / `frame_locator`) and zero-I/O accessors stay sync;
everything that reaches the live browser is `await`-able.

```python
import asyncio
from visus.web.async_api import launch, expect

async def main():
    async with await launch(headless=True) as browser:
        page = await browser.new_page()
        await page.goto("https://example.com/login")
        await page.get_by_label("Email").fill("ada@example.com")   # builder sync, fill async
        await expect(page.get_by_text("Welcome")).to_be_visible()

asyncio.run(main())
```

## Errors

All exceptions live in `visus.web.errors` and subclass `VisusWebError`:
`UnsupportedEngineError`, `VisusTimeoutError`, `NavigationError`,
`TargetClosedError`, `StrictModeViolation`, `ElementNotFoundError`. No
`selenium.*` type ever crosses this boundary — see [troubleshooting.md](troubleshooting.md)
for the shell-facing form of the same errors.
