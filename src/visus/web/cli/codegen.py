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


def _pystr(s: str) -> str:
    """A double-quoted Python string literal.

    Deliberately not ``repr``: this must match how ``Field.code`` is spelled in
    ``driver_delegate.list_fields`` so ``visus generate-locator`` prints the same
    text as the VISUS column of ``visus list-fields`` for the same element.
    ``_target_expr`` above keeps ``repr`` — its output is the golden text
    asserted in ``tests/test_codegen.py``.
    """
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def locator_expr(
    *,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """The copy-paste ``visus.web`` expression for a CLI target.

    Mirrors ``session_server.make_locator``'s branch order exactly — role, then
    text, then selector — so the printed line resolves the element the CLI would
    actually act on, and is frame-aware like ``Field.code``.
    """
    expr = "page" if frame is None else f"page.frame_locator({_pystr(frame)})"
    if role is not None:
        parts = [_pystr(role)]
        if name is not None:
            parts.append(f"name={_pystr(name)}")
        if exact:
            parts.append("exact=True")
        return f"{expr}.get_by_role({', '.join(parts)})"
    if text is not None:
        parts = [_pystr(text)]
        if exact:
            parts.append("exact=True")
        return f"{expr}.get_by_text({', '.join(parts)})"
    if selector is not None:
        return f"{expr}.locator({_pystr(selector)})"
    raise ValueError("provide one of: role, text, selector")


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
    if action == "pick_date":
        dates = [repr(d) for d in event.get("value") or () if d]
        return f"{expr}.pick_date({', '.join(dates)})"
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


def _test_name(name: str) -> str:
    """A valid python identifier for a test function, from a free-text scenario name."""
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in name.strip().lower())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    cleaned = cleaned.strip("_") or "generated"
    if cleaned[0].isdigit():
        cleaned = f"s_{cleaned}"
    return cleaned


def generate_test(
    name: str,
    url: str,
    events: list[dict],  # type: ignore[type-arg]
    *,
    expectations: list[str] | None = None,
    fixture: str = "visus_page",
) -> str:
    """Generate a runnable pytest test from a list of recorded events.

    Emits a test function over the packaged ``visus_page`` fixture rather than a
    ``launch()`` script, so the browser lifetime, the isolated context and the
    on-failure screenshot all come for free. *expectations* are pasted verbatim
    as the assertion block — they are written by whoever knows what the scenario
    is supposed to prove, which the recorder cannot know.
    """
    func = _test_name(name)
    lines = ["from visus.web import expect", "", ""]
    if fixture == "page":
        lines.append(f"def test_{func}(page):")
    else:
        lines.append(f"def test_{func}({fixture}):")
        lines.append(f"    page = {fixture}")
    lines.append(f"    page.goto({url!r})")
    for event in events:
        lines.append("    " + generate_line(event))
    if expectations:
        lines.append("")
        for assertion in expectations:
            lines.append("    " + assertion)
    return "\n".join(lines) + "\n"
