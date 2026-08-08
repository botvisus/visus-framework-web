"""Request-interception rules.

A :class:`RouteRule` is a pure value: a URL glob plus what to answer with. The
engine (``backends/selenium/cdp_fetch.py``) turns it into CDP ``Fetch`` commands,
the CLI turns it into a ``visus route`` invocation, and neither leaks into this
module — nothing here touches a browser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from visus.web.network import scrub_headers


def compile_pattern(pattern: str) -> re.Pattern[str]:
    """Compile a Playwright-style URL glob into a full-match regex.

    ``**`` matches anything including ``/``; ``*`` matches anything except ``/``;
    ``{a,b}`` is an alternation. ``?`` is **literal** — URLs use it to start the
    query string, so treating it as a wildcard would silently widen every pattern
    that names a query parameter. Everything else is escaped.
    """
    out: list[str] = ["^"]
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if pattern.startswith("**", i):
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 1
            continue
        if ch == "{":
            end = pattern.find("}", i)
            if end != -1:
                alts = pattern[i + 1 : end].split(",")
                out.append("(?:" + "|".join(re.escape(a) for a in alts) + ")")
                i = end + 1
                continue
        out.append(re.escape(ch))
        i += 1
    out.append("$")
    return re.compile("".join(out))


def cdp_url_pattern(pattern: str) -> str:
    """A permissive CDP ``urlPattern`` for *pattern*.

    CDP's ``Fetch.enable`` only understands ``*``, and it merely decides which
    requests get PAUSED — :meth:`RouteRule.matches` still makes the real decision
    in Python. So this only has to be a SUPERSET: every construct CDP cannot
    express collapses to ``*``, and a pattern that does not already start with a
    wildcard gets one so it can match a full absolute URL.
    """
    collapsed = re.sub(r"\{[^}]*\}", "*", pattern)
    while "**" in collapsed:
        collapsed = collapsed.replace("**", "*")
    if not collapsed.startswith("*"):
        collapsed = "*" + collapsed
    return collapsed


@dataclass(frozen=True)
class RouteRule:
    """One interception rule: what to match, and what to answer with.

    ``abort=True`` fails the request outright (the network-error path). Otherwise
    the request is fulfilled locally with *status* / *body* / *content_type* /
    *headers* and never reaches the network.
    """

    pattern: str
    status: int | None
    body: str | None
    content_type: str | None
    headers: dict[str, str]
    abort: bool

    def to_dict(self) -> dict[str, object]:
        """The transport shape: what crosses the delegate boundary and the socket."""
        return {
            "pattern": self.pattern,
            "status": self.status,
            "body": self.body,
            "content_type": self.content_type,
            "headers": dict(self.headers),
            "abort": self.abort,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> RouteRule:
        """Rebuild a rule from :meth:`to_dict` (or from a partial CLI payload).

        Every field is narrowed with ``isinstance`` rather than cast: this is fed
        straight from a JSON socket payload, so a wrong-typed value must become a
        clean default instead of a ``TypeError`` inside the daemon.
        """
        raw_status = data.get("status")
        raw_body = data.get("body")
        raw_type = data.get("content_type")
        raw_headers = data.get("headers")
        headers: dict[str, str] = {}
        if isinstance(raw_headers, dict):
            headers = {str(k): str(v) for k, v in raw_headers.items()}
        return cls(
            pattern=str(data.get("pattern", "")),
            status=int(raw_status) if isinstance(raw_status, (int, str)) else None,
            body=None if raw_body is None else str(raw_body),
            content_type=None if raw_type is None else str(raw_type),
            headers=headers,
            abort=bool(data.get("abort", False)),
        )

    def matches(self, url: str) -> bool:
        """Whether *url* is covered by this rule's glob."""
        return compile_pattern(self.pattern).match(url) is not None

    def redacted(self) -> RouteRule:
        """A copy whose secret headers are ``"REDACTED"`` — safe to print or log.

        Reuses the network capture's redaction list so `visus route-list` cannot
        become the one command that prints an ``Authorization`` header back out.
        """
        scrubbed = scrub_headers(self.headers)
        return replace(self, headers={str(k): str(v) for k, v in scrubbed.items()})
