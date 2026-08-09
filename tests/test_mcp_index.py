"""Index / frame / shadow targeting on the MCP surface (D12)."""

from __future__ import annotations

import os

import pytest

# Force headless before the server module is imported (session reads env at page-open time)
os.environ["VISUS_WEB_HEADLESS"] = "1"


@pytest.fixture()
def srv(base_url: str):  # type: ignore[no-untyped-def]
    """Fresh session + (server_module, base_url) pair for each test."""
    from visus.web.mcp import server

    server._session.close()
    yield server, base_url
    server._session.close()


def test_target_without_a_target_names_every_valid_form() -> None:
    from visus.web.mcp.session import Session

    s = Session()
    with pytest.raises(ValueError, match="provide one of: index, role, text, selector"):
        s.target({})


def test_field_locator_without_a_cache_is_an_actionable_error() -> None:
    from visus.web.mcp.session import Session

    s = Session()
    with pytest.raises(IndexError, match="run list_fields first"):
        s.field_locator(0)


@pytest.mark.browser
def test_index_reaches_a_field_inside_an_iframe(srv):  # type: ignore[no-untyped-def]
    """One integer, three layers: the frame chain is rebuilt by the resolver."""
    server, base_url = srv
    server.browser_navigate(f"{base_url}/fields.html")
    fields = server.browser_list_fields(include_hidden=True)
    by_locator = {f["locator"]: f for f in fields}
    assert by_locator["#iframeinput"]["frame"] == ["#f1"]

    idx = by_locator["#iframeinput"]["index"]
    loc = server._session.field_locator(idx)
    loc.fill("ada")
    # input_value(), not get_attribute("value"): fill types into the element, so
    # the VALUE PROPERTY moves and the HTML attribute (which this input does not
    # even have) does not.
    assert loc.input_value() == "ada"


@pytest.mark.browser
def test_index_reaches_a_field_inside_open_shadow_dom(srv):  # type: ignore[no-untyped-def]
    server, base_url = srv
    server.browser_navigate(f"{base_url}/fields.html")
    fields = server.browser_list_fields(include_hidden=True)
    by_locator = {f["locator"]: f for f in fields}
    assert by_locator["#shadowinput"]["deep"] is True

    loc = server._session.field_locator(by_locator["#shadowinput"]["index"])
    loc.fill("hidden-but-reachable")
    assert loc.input_value() == "hidden-but-reachable"


@pytest.mark.browser
def test_a_navigation_makes_cached_indexes_refuse_to_resolve(srv):  # type: ignore[no-untyped-def]
    """The MCP surface inherits the daemon's staleness contract, not just its cache.

    An EXPLICIT navigation drops the cache outright, exactly as the daemon's
    `_op_goto` does — so the refusal is "there is no cache", not "the cache is
    stale". An empty cache is the stronger guarantee: it cannot mis-resolve.
    """
    server, base_url = srv
    server.browser_navigate(f"{base_url}/fields.html")
    server.browser_list_fields(include_hidden=True)
    server.browser_navigate(f"{base_url}/forms.html")

    with pytest.raises(IndexError, match="run list_fields first"):
        server._session.field_locator(0)


@pytest.mark.browser
def test_a_js_driven_navigation_is_caught_by_the_page_stamp(srv):  # type: ignore[no-untyped-def]
    """The stamp is what catches a navigation visus never initiated.

    Invalidating on goto/back/forward/reload only covers navigations we perform.
    A page that navigates ITSELF leaves the cache populated and pointing at
    elements that no longer exist — which is the case the URL stamp exists for.
    """
    from visus.web.ops.targeting import StaleFieldIndexError

    server, base_url = srv
    server.browser_navigate(f"{base_url}/fields.html")
    server.browser_list_fields(include_hidden=True)
    server.browser_evaluate(f"() => {{ location.href = '{base_url}/forms.html'; }}")
    server._session.page().wait_for_url("**/forms.html")

    assert server._session._fields, "the cache must survive a navigation we did not perform"
    with pytest.raises(StaleFieldIndexError, match="run list-fields again"):
        server._session.field_locator(0)


@pytest.mark.browser
def test_target_falls_back_to_role_and_selector(srv):  # type: ignore[no-untyped-def]
    server, base_url = srv
    server.browser_navigate(f"{base_url}/forms.html")
    assert server._session.target({"role": "textbox", "name": "Username"}).count() == 1
    assert server._session.target({"selector": "#user"}).count() == 1


@pytest.mark.browser
def test_action_tools_accept_an_index(srv):  # type: ignore[no-untyped-def]
    """The whole point: `browser_fill(index=N, ...)` with no hand-built frame chain."""
    server, base_url = srv
    server.browser_navigate(f"{base_url}/fields.html")
    fields = server.browser_list_fields(include_hidden=True)
    by_locator = {f["locator"]: f for f in fields}
    idx = by_locator["#iframeinput"]["index"]

    assert server.browser_fill("student", index=idx).startswith("filled with 'student'")
    assert server._session.field_locator(idx).input_value() == "student"
    assert server.browser_count(index=idx) == 1
    server.browser_clear(index=idx)
    assert server._session.field_locator(idx).input_value() == ""


@pytest.mark.browser
def test_a_stale_index_is_refused_by_an_action_tool(srv):  # type: ignore[no-untyped-def]
    server, base_url = srv
    server.browser_navigate(f"{base_url}/fields.html")
    server.browser_list_fields(include_hidden=True)
    server.browser_navigate(f"{base_url}/forms.html")

    with pytest.raises(IndexError, match="run list_fields first"):
        server.browser_click(index=0)


def test_target_payload_renames_text_to_the_daemon_key() -> None:
    from visus.web.mcp import server

    payload = server._target_payload(
        index=None, selector=None, role="button", name="OK", text="Go"
    )
    assert payload["target_text"] == "Go"
    assert "text" not in payload


def test_run_uses_the_local_callable_while_detached() -> None:
    from visus.web.mcp import server

    assert server._remote is None
    assert server._run("title", {}, lambda: "local title") == {
        "ok": True,
        "result": "local title",
    }


# ---------------------------------------------------------------------------
# The DETACHED local paths. Every tool has two implementations — the daemon op
# and the in-process `_local()` — and only one of them was being exercised.
# ---------------------------------------------------------------------------


@pytest.mark.browser
def test_mcp_click_image_and_ocr_text_drive_this_servers_own_browser(srv, tmp_path):  # type: ignore[no-untyped-def]
    """_click_vision_match is the detached twin of the daemon's vision ops."""
    from PIL import Image

    server, base_url = srv
    server.browser_navigate(f"{base_url}/imagetarget.html")

    shot = tmp_path / "page.png"
    shot.write_bytes(server.browser_screenshot().data)
    ratio = float(server.browser_evaluate("() => window.devicePixelRatio"))
    crop = (int(300 * ratio), int(120 * ratio), int(420 * ratio), int(168 * ratio))
    template = tmp_path / "t.png"
    Image.open(shot).crop(crop).save(template)

    out = server.browser_click_image(str(template), confidence=0.9)
    assert "clicked image at" in out
    assert server.browser_get_text(selector="#clicked") == "image"

    out = server.browser_click_ocr_text("SUBMIT")
    assert "clicked text" in out
    assert server.browser_get_text(selector="#clicked") == "text"


@pytest.mark.browser
def test_mcp_click_image_reports_a_miss(srv, tmp_path):  # type: ignore[no-untyped-def]
    import numpy as np
    from PIL import Image

    server, base_url = srv
    server.browser_navigate(f"{base_url}/imagetarget.html")
    needle = np.zeros((24, 24, 3), np.uint8)
    needle[6:18, 6:18, 0] = 200
    template = tmp_path / "absent.png"
    Image.fromarray(needle).save(template)

    with pytest.raises(LookupError, match="not found on the page"):
        server.browser_click_image(str(template), confidence=0.95)
    with pytest.raises(LookupError, match="no rendered text matching"):
        server.browser_click_ocr_text("Nonexistent Label")


@pytest.mark.browser
def test_mcp_wait_for_and_expect_text_run_locally(srv):  # type: ignore[no-untyped-def]
    server, base_url = srv
    server.browser_navigate(f"{base_url}/forms.html")

    assert server.browser_wait_for(state="visible", role="textbox", name="Username") == (
        "element is visible"
    )
    assert server.browser_wait_for(state="hidden", selector="#no-such-node") == "element is hidden"
    with pytest.raises(AssertionError, match="wait_for"):
        server.browser_wait_for(state="visible", selector="#no-such-node", timeout=300)

    # PASSED is asserted against the element's OWN text, read back first, so the
    # test cannot pass by accident on a fixture edit.
    label = server.browser_get_text(selector="label")
    assert label, "the fixture must have a label to assert on"
    assert server.browser_expect_text(label, selector="label") == "PASSED"
    assert server.browser_expect_text(
        "Definitely Not Here", selector="label", timeout=300
    ).startswith("FAILED")


@pytest.mark.browser
def test_mcp_screenshot_and_find_image_scope_to_an_element(srv, tmp_path):  # type: ignore[no-untyped-def]
    server, base_url = srv
    server.browser_navigate(f"{base_url}/forms.html")
    fields = server.browser_list_fields(include_hidden=True)
    idx = fields[0]["index"]

    element_shot = server.browser_screenshot(index=idx)
    assert element_shot.data[:8] == b"\x89PNG\r\n\x1a\n"

    template = tmp_path / "field.png"
    template.write_bytes(element_shot.data)
    found = server.browser_find_image(str(template), confidence=0.8, index=idx)
    assert found["found"] is True

    absent = server.browser_find_image(str(template), confidence=0.999999, selector="#user")
    assert isinstance(absent["found"], bool)


@pytest.mark.browser
def test_mcp_drag_accepts_both_target_forms(srv):  # type: ignore[no-untyped-def]
    server, base_url = srv
    server.browser_navigate(f"{base_url}/forms.html")
    fields = server.browser_list_fields(include_hidden=True)
    assert len(fields) >= 2

    assert "dragged to" in server.browser_drag(target_selector="#user", index=fields[1]["index"])
    assert "dragged to" in server.browser_drag(
        target_index=fields[0]["index"], index=fields[1]["index"]
    )
    with pytest.raises(ValueError, match="provide a drag target"):
        server.browser_drag(index=fields[0]["index"])
