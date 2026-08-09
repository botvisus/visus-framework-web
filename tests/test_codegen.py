"""Real-browser codegen recorder tests + pure-Python unit tests."""

from __future__ import annotations

import pytest

from visus.web.cli.codegen import (
    _target_expr,
    drain,
    generate_line,
    generate_script,
    inject_recorder,
)

# ---------------------------------------------------------------------------
# Pure-Python unit tests (no browser required)
# ---------------------------------------------------------------------------


def test_target_expr_role() -> None:
    t = {"kind": "role", "role": "button", "name": "Submit"}
    assert _target_expr(t) == "get_by_role('button', name='Submit')"


def test_target_expr_testid() -> None:
    t = {"kind": "testid", "value": "submit-btn"}
    assert _target_expr(t) == "get_by_test_id('submit-btn')"


def test_target_expr_css() -> None:
    t = {"kind": "css", "value": "#myid"}
    assert _target_expr(t) == "locator('#myid')"


def test_generate_line_click() -> None:
    ev = {"action": "click", "target": {"kind": "css", "value": "#btn"}}
    assert generate_line(ev) == "page.locator('#btn').click()"


def test_generate_line_fill() -> None:
    ev = {"action": "fill", "target": {"kind": "css", "value": "#inp"}, "value": "hello"}
    assert generate_line(ev) == "page.locator('#inp').fill('hello')"


def test_generate_line_select_option() -> None:
    ev = {"action": "select_option", "target": {"kind": "css", "value": "select"}, "value": "x"}
    line = generate_line(ev)
    assert ".select_option(value=" in line


def test_generate_line_unsupported() -> None:
    # "hover" became a supported no-arg action in Task 6 (test_generate_line_covers_
    # every_daemon_action pins that); use a genuinely unrecognized action here instead.
    ev = {"action": "scroll_into_view", "target": {"kind": "css", "value": "div"}}
    assert generate_line(ev).startswith("# unsupported:")


def test_generate_script_structure() -> None:
    events = [
        {"action": "click", "target": {"kind": "css", "value": "#btn"}},
    ]
    code = generate_script("https://example.com", events)
    assert "from visus.web import launch" in code
    assert "page.goto('https://example.com')" in code
    assert ".click()" in code


@pytest.mark.browser
def test_recorder_captures_click_and_fill(browser, base_url: str) -> None:  # type: ignore[no-untyped-def]
    page = browser.new_page()
    page.goto(f"{base_url}/forms.html")
    inject_recorder(page)
    # Fill the Username field; change event fires on blur (triggered by next click)
    page.get_by_role("textbox", name="Username").fill("ada")
    # Click another element to blur the textbox and fire the change event
    page.locator("#closebtn").click()
    events = drain(page)
    actions = [e["action"] for e in events]
    assert "fill" in actions and "click" in actions, f"expected fill+click in {actions}"
    # The username fill should generate a get_by_role or locator line
    fill_ev = next(e for e in events if e["action"] == "fill")
    line = generate_line(fill_ev)
    assert ".fill(" in line, f"expected .fill( in generated line: {line!r}"


@pytest.mark.browser
def test_generate_script_shape(browser, base_url: str) -> None:  # type: ignore[no-untyped-def]
    page = browser.new_page()
    page.goto(f"{base_url}/forms.html")
    inject_recorder(page)
    page.locator("#closebtn").click()
    code = generate_script(f"{base_url}/forms.html", drain(page))
    assert "from visus.web import launch" in code
    assert "page.goto(" in code
    assert ".click()" in code


def test_generate_line_prefers_an_explicit_expression() -> None:
    """A cached Field carries a full frame-aware expression; use it verbatim."""
    from visus.web.cli.codegen import generate_line

    event = {
        "action": "fill",
        "target": {"kind": "code", "expr": 'page.frame_locator("#f1").locator("#u")'},
        "value": "ada",
    }
    assert generate_line(event) == "page.frame_locator(\"#f1\").locator(\"#u\").fill('ada')"


def test_generate_line_covers_every_daemon_action() -> None:
    from visus.web.cli.codegen import generate_line

    target = {"kind": "css", "value": "#x"}
    assert generate_line({"action": "click", "target": target}) == "page.locator('#x').click()"
    assert (
        generate_line({"action": "dblclick", "target": target}) == "page.locator('#x').dblclick()"
    )
    assert generate_line({"action": "check", "target": target}) == "page.locator('#x').check()"
    assert generate_line({"action": "uncheck", "target": target}) == "page.locator('#x').uncheck()"
    assert generate_line({"action": "hover", "target": target}) == "page.locator('#x').hover()"
    assert generate_line({"action": "focus", "target": target}) == "page.locator('#x').focus()"
    assert generate_line({"action": "clear", "target": target}) == "page.locator('#x').clear()"
    assert (
        generate_line({"action": "press", "target": target, "value": "Enter"})
        == "page.locator('#x').press('Enter')"
    )
    assert (
        generate_line({"action": "set_input_files", "target": target, "value": ["/a.png"]})
        == "page.locator('#x').set_input_files(['/a.png'])"
    )


def test_target_expr_supports_a_text_target() -> None:
    from visus.web.cli.codegen import _target_expr

    assert _target_expr({"kind": "text", "value": "Save"}) == "get_by_text('Save')"


def test_generate_test_emits_a_runnable_pytest_function() -> None:
    """The generator's output must be a TEST, not a script — the fixture exists."""
    from visus.web.cli.codegen import generate_test

    events = [
        {"action": "fill", "target": {"kind": "role", "role": "textbox", "name": "Username"},
         "value": "student"},
        {"action": "click", "target": {"kind": "role", "role": "button", "name": "Submit"}},
    ]
    code = generate_test("login", "https://x.test/login", events)

    assert "from visus.web import expect" in code
    assert "def test_login(visus_page):" in code
    assert "page = visus_page" in code
    assert "page.goto('https://x.test/login')" in code
    assert "page.get_by_role('textbox', name='Username').fill('student')" in code
    assert "page.get_by_role('button', name='Submit').click()" in code
    # No launch(): the fixture owns the browser lifetime.
    assert "launch(" not in code
    compile(code, "<generated>", "exec")  # it must at least be valid Python


def test_generate_test_embeds_expectations_verbatim() -> None:
    from visus.web.cli.codegen import generate_test

    code = generate_test(
        "login",
        "https://x.test/login",
        [],
        expectations=[
            "expect(page).to_have_url('*dashboard*')",
            "expect(page.get_by_role('heading')).to_contain_text('Welcome')",
        ],
    )
    assert "    expect(page).to_have_url('*dashboard*')" in code
    assert "    expect(page.get_by_role('heading')).to_contain_text('Welcome')" in code
    compile(code, "<generated>", "exec")


def test_generate_test_sanitises_the_name() -> None:
    from visus.web.cli.codegen import generate_test

    code = generate_test("should add a to-do!", "https://x.test/", [])
    assert "def test_should_add_a_to_do(visus_page):" in code
    compile(code, "<generated>", "exec")


def test_generate_test_accepts_another_fixture() -> None:
    from visus.web.cli.codegen import generate_test

    code = generate_test("x", "https://x.test/", [], fixture="page")
    assert "def test_x(page):" in code
    assert "page = page" not in code  # no pointless self-assignment


def test_generate_test_with_no_events_is_still_valid() -> None:
    from visus.web.cli.codegen import generate_test

    code = generate_test("empty", "https://x.test/", [])
    compile(code, "<generated>", "exec")
    assert code.endswith("\n")
