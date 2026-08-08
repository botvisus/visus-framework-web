import pytest


@pytest.fixture
def page(browser, base_url):
    p = browser.new_page()
    p.goto(f"{base_url}/interactions.html")
    return p


@pytest.mark.browser
def test_check_uncheck(page):
    cb = page.locator("#cb")
    cb.check()
    assert cb.is_checked() is True
    assert page.locator("#cbstate").text_content() == "on"
    cb.uncheck()
    assert cb.is_checked() is False
    assert page.locator("#cbstate").text_content() == "off"


@pytest.mark.browser
def test_check_is_idempotent(page):
    cb = page.locator("#cb")
    cb.check()
    cb.check()  # already checked -> no toggle
    assert cb.is_checked() is True


@pytest.mark.browser
def test_select_option(page):
    page.locator("#sel").select_option(value="y")
    assert page.locator("#sel").input_value() == "y"
    page.locator("#sel").select_option(label="Z")
    assert page.locator("#sel").input_value() == "z"
    page.locator("#sel").select_option(index=0)
    assert page.locator("#sel").input_value() == "x"


@pytest.mark.browser
def test_press_enter(page):
    page.locator("#txt").press("Enter")
    assert page.locator("#pressres").text_content() == "enter"


@pytest.mark.browser
def test_clear(page):
    txt = page.locator("#txt")
    assert txt.input_value() == "hello"
    txt.clear()
    assert txt.input_value() == ""


@pytest.mark.browser
def test_hover(page):
    page.locator("#hovertarget").hover()
    assert page.locator("#hoverres").text_content() == "hovered"


@pytest.mark.browser
def test_dblclick(page):
    page.locator("#dbl").dblclick()
    assert page.locator("#dblres").text_content() == "double"


@pytest.mark.browser
def test_focus_and_blur(page):
    f = page.locator("#focusable")
    f.focus()
    assert page.locator("#focusres").text_content() == "focused"
    f.blur()
    assert page.locator("#blurres").text_content() == "blurred"


@pytest.mark.browser
def test_focus_needs_a_clickable_point_and_says_so(page):
    """Documents a real limitation of `focus`, so a future change is a decision.

    `focus` dispatches a mouse click (the only way to make headless Chrome fire
    the page's onfocus handler — with document.hasFocus() False a JS
    HTMLElement.focus() moves activeElement silently). The cost: an element with
    no clickable point is reported focused without focus moving. Swapping the
    dispatch to JS trades this for a worse bug; the real fix is CDP focus
    emulation (Emulation.setFocusEmulationEnabled), which is Chromium-only.
    """
    page.evaluate(
        "() => { const d = document.createElement('div');"
        " d.id = 'flatfocus'; d.tabIndex = 0; d.style.height = '0px';"
        " document.body.appendChild(d); }"
    )
    page.locator("#flatfocus").focus()
    assert page.evaluate("() => document.activeElement.id") != "flatfocus"
    # …while a JS focus() would move it — proving the element itself is focusable
    # and the limitation is in the dispatch, not the page.
    page.evaluate("() => document.getElementById('flatfocus').focus()")
    assert page.evaluate("() => document.activeElement.id") == "flatfocus"


@pytest.mark.browser
def test_drag_to(page):
    page.locator("#src").drag_to(page.locator("#dst"))
    assert page.locator("#dragres").text_content() == "dropped"
