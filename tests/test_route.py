"""Route rules: glob semantics, redaction, and (below) real interception."""

from __future__ import annotations

import pytest

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
