"""The shared targeting vocabulary — one implementation, both frontends."""

from __future__ import annotations

from typing import Any

import pytest

from visus.web.cli import session_server
from visus.web.mcp import session as mcp_session
from visus.web.ops import targeting


class _Loc:
    def __init__(self, label: str) -> None:
        self.label = label

    def frame_locator(self, sel: str) -> _Loc:
        return _Loc(f"{self.label}>frame({sel})")

    def locator(self, selector: str, *, deep: bool = False) -> _Loc:
        return _Loc(f"{self.label}>loc({selector},deep={deep})")

    def get_by_role(self, role: str, *, name: str | None = None, exact: bool = False) -> _Loc:
        return _Loc(f"role({role},{name},exact={exact})")

    def get_by_text(self, text: str, *, exact: bool = False) -> _Loc:
        return _Loc(f"text({text},exact={exact})")


class _Page(_Loc):
    def __init__(self) -> None:
        super().__init__("page")
        self.url = "http://a.test/one"


class _Field:
    def __init__(self, locator: str, frame: list[str], deep: bool) -> None:
        self.locator = locator
        self.frame = frame
        self.deep = deep


def test_both_frontends_import_the_same_make_locator() -> None:
    """The duplication is gone, not just re-synced: same function object."""
    assert session_server.make_locator is targeting.make_locator
    assert mcp_session.make_locator is targeting.make_locator


def test_both_frontends_import_the_same_visibility_helper() -> None:
    from visus.web.mcp import server as mcp_server

    assert session_server._any_match_visible is targeting.any_match_visible
    assert mcp_server._any_match_visible is targeting.any_match_visible


def test_stale_field_index_error_is_re_exported_by_the_daemon() -> None:
    """PLAN 3 named it `session_server.StaleFieldIndexError`; that stays true."""
    assert session_server.StaleFieldIndexError is targeting.StaleFieldIndexError
    assert issubclass(targeting.StaleFieldIndexError, RuntimeError)


def test_make_locator_prefers_role_then_text_then_selector() -> None:
    page = _Page()
    assert (
        targeting.make_locator(page, role="button", name="OK").label
        == "role(button,OK,exact=False)"
    )
    assert targeting.make_locator(page, text="Hi", exact=True).label == "text(Hi,exact=True)"
    assert targeting.make_locator(page, selector="#x").label == "page>loc(#x,deep=False)"


def test_make_locator_wraps_the_frame_first() -> None:
    page = _Page()
    loc = targeting.make_locator(page, selector="#x", frame="#f1")
    assert loc.label == "page>frame(#f1)>loc(#x,deep=False)"


def test_make_locator_without_a_target_names_every_valid_form() -> None:
    with pytest.raises(ValueError, match="provide one of: index, role, text, selector"):
        targeting.make_locator(_Page())


def test_resolve_field_rebuilds_the_frame_chain_and_deep_flag() -> None:
    page = _Page()
    fields = [_Field("#a", [], False), _Field("#b", ["#f1", "#f2"], True)]
    loc = targeting.resolve_field(page, fields, 1, fields_url=page.url)
    assert loc.label == "page>frame(#f1)>frame(#f2)>loc(#b,deep=True)"


def test_resolve_field_out_of_range_message_is_actionable() -> None:
    page = _Page()
    with pytest.raises(IndexError, match=r"out of range \(have 1; run list_fields first\)"):
        targeting.resolve_field(page, [_Field("#a", [], False)], 9, fields_url=page.url)


def test_resolve_field_refuses_a_stamp_from_another_page() -> None:
    page = _Page()
    with pytest.raises(targeting.StaleFieldIndexError) as excinfo:
        targeting.resolve_field(
            page, [_Field("#a", [], False)], 0, fields_url="http://a.test/other"
        )
    message = str(excinfo.value)
    assert "field indexes were captured on http://a.test/other" in message
    assert "page is now http://a.test/one" in message
    assert "run list-fields again" in message


def test_resolve_field_with_no_stamp_does_not_check_the_page() -> None:
    """An unstamped cache (a frontend that never stamps) still resolves."""
    page = _Page()
    loc = targeting.resolve_field(page, [_Field("#a", [], False)], 0, fields_url=None)
    assert loc.label == "page>loc(#a,deep=False)"


@pytest.mark.browser
def test_shared_resolver_reaches_an_iframe_field_from_the_daemon(base_url: str) -> None:
    """Integration proof: the extracted resolver still drives a real browser."""
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/fields.html"
    )
    try:
        fields: list[dict[str, Any]] = h.handle("list_fields", {"highlight": False})["result"][
            "fields"
        ]
        by_locator = {f["locator"]: f for f in fields}
        assert by_locator["#iframeinput"]["frame"] == ["#f1"]
        idx = by_locator["#iframeinput"]["index"]
        assert h.handle("fill", {"index": idx, "text": "ada"})["ok"] is True
        # Read back through the SAME index, so both directions go through the
        # extracted resolver. Not `get_attribute("value")`: locator_get_attribute
        # calls getAttribute() on purpose, and this input has no `value=`
        # attribute — filling it moves the property, never the attribute.
        read_back = h.handle("eval", {"index": idx, "expression": "(el) => el.value"})
        assert read_back["result"]["result"] == "ada", read_back
    finally:
        h.close()
