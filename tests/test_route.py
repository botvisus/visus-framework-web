"""Route rules: glob semantics, redaction, and (below) real interception."""

from __future__ import annotations

import pytest

from visus.web import errors, launch
from visus.web.api.route import RouteRule, cdp_url_pattern, compile_pattern


@pytest.mark.parametrize(
    ("pattern", "url", "expected"),
    [
        ("**/api/users", "https://x.test/api/users", True),
        ("**/api/users", "https://x.test/v1/api/users", True),
        ("**/api/users", "https://x.test/api/users/1", False),
        ("**/api/*/details", "https://x.test/api/7/details", True),
        ("**/api/*/details", "https://x.test/api/7/8/details", False),
        ("**/*.{png,jpg}", "https://x.test/a/b/logo.png", True),
        ("**/*.{png,jpg}", "https://x.test/a/b/logo.gif", False),
        ("https://x.test/exact", "https://x.test/exact", True),
        ("https://x.test/exact", "https://y.test/exact", False),
        ("**/search?q=*", "https://x.test/search?q=cats", True),
        ("**/search?q=*", "https://x.test/searchXq=cats", False),
        ("**", "https://anything.test/at/all", True),
    ],
)
def test_glob_matching(pattern: str, url: str, expected: bool) -> None:
    assert RouteRule(pattern, None, None, None, {}, False).matches(url) is expected


def test_question_mark_is_literal_not_a_wildcard() -> None:
    """URLs use `?` for the query string; treating it as a wildcard would be a trap."""
    assert compile_pattern("a?b").match("a?b") is not None
    assert compile_pattern("a?b").match("axb") is None


def test_regex_metacharacters_in_a_pattern_are_literal() -> None:
    rule = RouteRule("**/price(usd).json", None, None, None, {}, False)
    assert rule.matches("https://x.test/price(usd).json") is True
    assert rule.matches("https://x.test/priceXusd.json") is False


def test_round_trip_through_dict() -> None:
    rule = RouteRule(
        pattern="**/api/*",
        status=503,
        body='{"error":"down"}',
        content_type="application/json",
        headers={"X-Mock": "1"},
        abort=False,
    )
    assert RouteRule.from_dict(rule.to_dict()) == rule


def test_from_dict_tolerates_a_minimal_payload() -> None:
    rule = RouteRule.from_dict({"pattern": "**/x"})
    assert rule == RouteRule("**/x", None, None, None, {}, False)


def test_redacted_scrubs_secret_headers_but_keeps_the_rule() -> None:
    rule = RouteRule(
        pattern="**/api/*",
        status=200,
        body="{}",
        content_type="application/json",
        headers={"Authorization": "Bearer abc", "X-Trace": "keep"},
        abort=False,
    )
    safe = rule.redacted()
    assert safe.headers == {"Authorization": "REDACTED", "X-Trace": "keep"}
    assert safe.pattern == rule.pattern and safe.status == 200
    assert rule.headers["Authorization"] == "Bearer abc", "redacted() mutated the original"


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("**/api/users", "*/api/users"),
        ("**/*.{png,jpg}", "*/*.*"),
        ("https://x.test/exact", "*https://x.test/exact"),
        ("**", "*"),
    ],
)
def test_cdp_url_pattern_is_a_superset(pattern: str, expected: str) -> None:
    """CDP only knows `*`; it pre-filters, Python decides. So it must never be narrower."""
    assert cdp_url_pattern(pattern) == expected


@pytest.mark.browser
def test_route_fulfills_a_request_without_hitting_the_network(base_url: str) -> None:
    """The gap with no eval workaround: an answer the page never made a request for."""
    with launch(headless=True) as browser:
        page = browser.new_page()
        page.goto(f"{base_url}/route_fetch.html")
        page.route(
            "**/api/items",
            status=201,
            body='[{"id":1,"name":"Alice"}]',
            content_type="application/json",
            headers={"X-Mock": "yes"},
        )
        page.locator("#go").click()
        from visus.web import expect

        expect(page.locator("#out")).to_contain_text("status=201", timeout=10000)
        text = page.locator("#out").text_content() or ""
        assert '"name":"Alice"' in text, text
        assert "404" not in text, "the request reached the real fixture server"


@pytest.mark.browser
def test_route_abort_fails_a_subresource(base_url: str) -> None:
    with launch(headless=True) as browser:
        page = browser.new_page()
        page.goto(f"{base_url}/route_fetch.html")
        page.route("**/pixel.png*", abort=True)
        page.locator("#img").click()
        from visus.web import expect

        expect(page.locator("#out")).to_have_text("image-blocked", timeout=10000)


@pytest.mark.browser
def test_unmatched_requests_still_reach_the_server(base_url: str) -> None:
    """Fetch.enable pauses traffic — anything unmatched MUST be continued."""
    with launch(headless=True) as browser:
        page = browser.new_page()
        page.goto(f"{base_url}/route_fetch.html")
        page.route("**/never-matches", status=500, body="nope")
        page.locator("#go").click()
        from visus.web import expect

        expect(page.locator("#out")).to_contain_text("status=404", timeout=10000)


@pytest.mark.browser
def test_routes_lists_and_unroute_removes(base_url: str) -> None:
    with launch(headless=True) as browser:
        page = browser.new_page()
        page.goto(f"{base_url}/route_fetch.html")
        page.route("**/api/items", status=201, body="[]", content_type="application/json")
        page.route("**/pixel.png*", abort=True)
        listed = page.routes()
        assert [r.pattern for r in listed] == ["**/api/items", "**/pixel.png*"]
        assert listed[1].abort is True

        assert page.unroute("**/pixel.png*") == 1
        assert [r.pattern for r in page.routes()] == ["**/api/items"]
        assert page.unroute() == 1
        assert page.routes() == []

        # Interception is fully off again: the real 404 comes back.
        page.locator("#go").click()
        from visus.web import expect

        expect(page.locator("#out")).to_contain_text("status=404", timeout=10000)


@pytest.mark.browser
def test_re_routing_the_same_pattern_replaces_it(base_url: str) -> None:
    with launch(headless=True) as browser:
        page = browser.new_page()
        page.goto(f"{base_url}/route_fetch.html")
        page.route("**/api/items", status=200, body="first")
        page.route("**/api/items", status=200, body="second")
        assert len(page.routes()) == 1
        page.locator("#go").click()
        from visus.web import expect

        expect(page.locator("#out")).to_contain_text("body=second", timeout=10000)


def test_route_is_refused_without_a_devtools_endpoint() -> None:
    """A non-Chromium (or grid) session has no debuggerAddress — say what to do.

    Asserted against the resolver directly rather than by launching Firefox: the
    guard is a capability check, and Firefox is not installed on every machine
    that runs this suite.
    """
    from visus.web.backends.selenium.cdp_fetch import devtools_ws_url

    class _NoCdpDriver:
        capabilities: dict[str, object] = {"browserName": "firefox"}

    with pytest.raises(errors.VisusWebError) as excinfo:
        devtools_ws_url(_NoCdpDriver(), "CDwindow-1")  # type: ignore[arg-type]
    message = str(excinfo.value)
    assert "chrome" in message and "edge" in message
    assert "add_init_script" in message


def test_page_route_signature_is_engine_free() -> None:
    """THE HIDDEN-ENGINE RULE: no selenium type in the public route surface."""
    import inspect

    from visus.web.api.page import Page

    for name in ("route", "unroute", "routes"):
        source = inspect.getsource(getattr(Page, name))
        assert "selenium" not in source, f"Page.{name} mentions selenium"
        signature = str(inspect.signature(getattr(Page, name)))
        assert "selenium" not in signature and "WebDriver" not in signature
