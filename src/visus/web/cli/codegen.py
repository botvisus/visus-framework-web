"""Records browser interactions and emits visus.web Python code."""

from __future__ import annotations

from typing import cast

from visus.web.api.page import Page

_RECORDER_JS = r"""
(function () {
  if (window.__visusRec) return;
  window.__visusRec = [];
  function sel(el) {
    var role = window.__visus.role(el);
    var name = window.__visus.accessibleName(el);
    if (role && name) return {kind:'role', role:role, name:name};
    if (el.id) return {kind:'css', value:'#' + el.id};
    if (el.getAttribute && el.getAttribute('data-testid'))
      return {kind:'testid', value: el.getAttribute('data-testid')};
    var tag = el.tagName.toLowerCase();
    if (el.name) return {kind:'css', value: tag + '[name="' + el.name + '"]'};
    return {kind:'css', value: tag};
  }
  document.addEventListener('click', function (e) {
    window.__visusRec.push({action:'click', target: sel(e.target)});
  }, true);
  document.addEventListener('change', function (e) {
    var t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA'))
      window.__visusRec.push({action:'fill', target: sel(t), value: t.value});
    else if (t && t.tagName === 'SELECT')
      window.__visusRec.push({action:'select_option', target: sel(t), value: t.value});
  }, true);
})();
"""


def inject_recorder(page: Page) -> None:
    """Inject the visus bundle (if needed) and then the recorder JS."""
    # Force _ensure_bundle by resolving an element — this guarantees window.__visus exists
    page.locator("html").count()
    # Now inject the recorder (which calls window.__visus.role / accessibleName)
    page.evaluate("() => { " + _RECORDER_JS + " }")


def drain(page: Page) -> list[dict]:  # type: ignore[type-arg]
    """Drain and return all recorded events, resetting the buffer."""
    script = "() => { var r = window.__visusRec || []; window.__visusRec = []; return r; }"
    result = page.evaluate(script)
    if result is None:
        return []
    return cast(list, result)  # type: ignore[type-arg]


def _target_expr(t: dict) -> str:  # type: ignore[type-arg]
    """The locator expression (without the leading ``page.``) for one target."""
    if t["kind"] == "role":
        return f"get_by_role({t['role']!r}, name={t['name']!r})"
    if t["kind"] == "text":
        return f"get_by_text({t['value']!r})"
    if t["kind"] == "testid":
        return f"get_by_test_id({t['value']!r})"
    return f"locator({t['value']!r})"


# Actions whose generated call takes no argument.
_NO_ARG_ACTIONS: dict[str, str] = {
    "click": "click",
    "dblclick": "dblclick",
    "check": "check",
    "uncheck": "uncheck",
    "hover": "hover",
    "focus": "focus",
    "clear": "clear",
}


def generate_line(event: dict) -> str:  # type: ignore[type-arg]
    """Generate a single visus.web Python statement for one recorded event.

    ``event["target"]["expr"]`` short-circuits selector synthesis: the daemon's
    cached ``Field.code`` is already a complete, frame-aware expression and is
    strictly better than anything reconstructible from a bare selector.
    """
    target = event["target"]
    expr = target.get("expr") or ("page." + _target_expr(target))
    action = event["action"]
    if action in _NO_ARG_ACTIONS:
        return f"{expr}.{_NO_ARG_ACTIONS[action]}()"
    if action == "fill":
        return f"{expr}.fill({event.get('value', '')!r})"
    if action == "press":
        return f"{expr}.press({event.get('value', '')!r})"
    if action == "select_option":
        return f"{expr}.select_option(value={event.get('value', '')!r})"
    if action == "set_input_files":
        return f"{expr}.set_input_files({event.get('value', [])!r})"
    return f"# unsupported: {action}"


def generate_script(url: str, events: list[dict]) -> str:  # type: ignore[type-arg]
    """Generate a complete visus.web Python script from a list of recorded events."""
    lines = [
        "from visus.web import launch",
        "",
        "with launch(headless=False) as browser:",
        "    page = browser.new_page()",
        f"    page.goto({url!r})",
    ]
    for ev in events:
        lines.append("    " + generate_line(ev))
    return "\n".join(lines) + "\n"
