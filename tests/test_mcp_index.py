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
