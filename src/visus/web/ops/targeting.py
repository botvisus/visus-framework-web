"""One locator resolver for the CLI daemon and the MCP server.

Three helpers used to exist in two copies each, with the reason spelled out in
their own docstrings:

* ``make_locator``       — ``session_server.py:59-63`` / ``mcp/session.py:142-160``
* ``_any_match_visible`` — ``session_server.py:37-46`` / ``mcp/server.py:22-32``
* ``_resolve_field``     — CLI-only, and its absence is exactly why MCP had to
  instruct the model in prose to rebuild an iframe chain by hand
  (``mcp/server.py:96-99``).

They live here now. Both frontends import the same objects, so a fix to
targeting can no longer land on one surface and miss the other.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, cast

from visus.web import errors
from visus.web.api.locator import Locator

if TYPE_CHECKING:
    from visus.web.api.fields import Field
    from visus.web.api.page import Page


class StaleFieldIndexError(RuntimeError):
    """Raised when a cached field index no longer belongs to the current page.

    Index targeting re-resolves a stored selector against whatever page is loaded
    now. Generated selectors intentionally fall back to generic forms
    (``button.btn.primary``, ``input[type="email"]``, a bare tag), each of which
    matches *something* on a different page — so without this guard a stale index
    clicks the wrong element and reports success.
    """


def any_match_visible(loc: Locator) -> bool:
    """True if at least one element the locator matches is visible.

    Tolerant of mid-navigation errors (treated as "not yet visible") and of
    locators that match several elements — so an agent can wait by a loose
    target (e.g. text=) even when a hidden duplicate sorts first in the DOM.
    """
    try:
        return any(loc.nth(i).is_visible() for i in range(loc.count()))
    except errors.VisusWebError:
        return False


def make_locator(
    page: Page,
    *,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> Locator:
    """Resolve a locator from the given target params.

    ``frame`` is applied first, so a role/text/selector target is looked up
    *inside* that iframe rather than in the top document.

    ``nth`` picks one match out of several (0-based; negative counts from the
    end). It is the escape hatch a strict-mode violation points at, and it lives
    HERE so both frontends offer it — an error that advises a way out must be
    followable on whichever surface received it.
    """
    root: Any = page if frame is None else page.frame_locator(frame)
    loc: Locator
    if role is not None:
        loc = cast(Locator, root.get_by_role(role, name=name, exact=exact))
    elif text is not None:
        loc = cast(Locator, root.get_by_text(text, exact=exact))
    elif selector is not None:
        loc = cast(Locator, root.locator(selector))
    else:
        raise ValueError("provide one of: index, role, text, selector")
    return loc.nth(nth) if nth is not None else loc


def resolve_field(
    page: Page,
    fields: Sequence[Field],
    index: int,
    *,
    fields_url: str | None,
) -> Locator:
    """Re-resolve cached field *index* against *page* via the foundation contract.

    Walks the field's iframe chain with ``frame_locator`` and applies its
    ``deep`` flag, so one integer reaches an element three iframes down or inside
    an open shadow root. ``fields_url`` is the page identity stamped when the
    cache was filled; when it disagrees with the live URL the index is refused
    rather than re-resolved against a page it never described.
    """
    if index < 0 or index >= len(fields):
        raise IndexError(
            f"field index {index} out of range (have {len(fields)}; run list_fields first)"
        )
    if fields_url is not None:
        current = page.url
        if current != fields_url:
            raise StaleFieldIndexError(
                f"field indexes were captured on {fields_url}, "
                f"page is now {current} — run list-fields again"
            )
    field = fields[index]
    root: Any = page
    for sel in field.frame:
        root = root.frame_locator(sel)
    # O XPath que o list_fields calculou aponta para ESTE elemento. O localizador
    # "melhor" (papel+nome, classe) pode casar cópias escondidas dele — menus
    # responsivos, modais fechados — e o número clicaria a cópia errada. Em shadow DOM
    # o XPath não alcança: lá o localizador (com deep) continua sendo o caminho.
    if field.xpath and not field.deep:
        return cast(Locator, root.locator(f"xpath={field.xpath}"))
    return cast(Locator, root.locator(field.locator, deep=field.deep))
