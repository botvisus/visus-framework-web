"""Page-level CLI surface: highlight, boxes, scoped eval, resize, storage,
cookies, generate-locator, session pdf/screenshot."""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import console, session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


class _FakeBrowser:
    def close(self) -> None:
        pass

    @property
    def contexts(self) -> list[Any]:
        return []


def _handler(page: Any) -> session_server.SessionHandler:
    h = session_server.SessionHandler(engine="chrome", headless=True)
    h._browser = _FakeBrowser()  # type: ignore[assignment]
    h._page = page
    return h


class _HighlightLocator:
    def __init__(self, log: list[str], label: str) -> None:
        self._log = log
        self._label = label

    def first(self) -> _HighlightLocator:
        return self

    def count(self) -> int:
        self._log.append(f"count:{self._label}")
        return 1

    def highlight(self, *, style: str | None = None) -> None:
        self._log.append(f"highlight:{self._label}:{style}")


class _HighlightPage:
    url = "http://x/"

    def __init__(self) -> None:
        self.log: list[str] = []

    def locator(self, selector: str, *, deep: bool = False) -> _HighlightLocator:
        return _HighlightLocator(self.log, f"loc({selector})")

    def evaluate(self, expression: str, arg: object = None) -> object:
        self.log.append(f"eval:{expression}")
        return None


def test_op_highlight_targets_one_element() -> None:
    page = _HighlightPage()
    h = _handler(page)
    assert h.handle("highlight", {"selector": "#b"})["result"] == "highlighted"
    assert page.log == ["highlight:loc(#b):None"]
    page.log.clear()
    h.handle("highlight", {"selector": "#b", "style": "2px dashed #0a0"})
    assert page.log == ["highlight:loc(#b):2px dashed #0a0"]


def test_op_highlight_hide_forces_the_bundle_then_unhighlights() -> None:
    page = _HighlightPage()
    h = _handler(page)
    assert h.handle("highlight", {"hide": True})["result"] == "highlight cleared"
    assert page.log[0] == "count:loc(html)"  # forces window.__visus to exist
    assert "unhighlight" in page.log[1]


def test_cli_highlight_and_hide(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client, "send", lambda op, args=None: calls.append((op, args or {})) or "ok"
    )
    assert runner.invoke(app, ["highlight", "3"]).exit_code == 0
    assert runner.invoke(app, ["highlight", "-s", "#b", "--style", "2px solid red"]).exit_code == 0
    assert runner.invoke(app, ["highlight", "--hide"]).exit_code == 0
    assert calls[0] == ("highlight", {"index": 3})
    assert calls[1][1]["selector"] == "#b" and calls[1][1]["style"] == "2px solid red"
    assert calls[2] == ("highlight", {"hide": True})


def test_repl_highlight() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return "ok"

    console.dispatch("highlight 3", send)
    console.dispatch("highlight #b 2px dashed #0a0", send)
    console.dispatch("highlight hide", send)
    assert calls[0] == ("highlight", {"index": 3})
    assert calls[1] == ("highlight", {"selector": "#b", "style": "2px dashed #0a0"})
    assert calls[2] == ("highlight", {"hide": True})
    assert "highlight" in console.dispatch("help", send)


@pytest.mark.browser
def test_highlight_draws_and_hides_a_box_on_a_real_page(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/fields.html"
    )

    def js(expr: str) -> object:
        return h.handle("eval", {"expression": expr})["result"]["result"]

    try:
        assert h.handle("highlight", {"selector": "#btn"})["ok"] is True
        # highlight() appends the box AND a centre dot, both tagged.
        assert js("() => document.querySelectorAll('[data-visus-highlight]').length") == 2

        styled = h.handle("highlight", {"selector": "#btn", "style": "2px dashed rgb(0, 170, 0)"})
        assert styled["ok"] is True, styled
        assert js("() => document.querySelector('[data-visus-highlight]').style.borderStyle") == (
            "dashed"
        )

        assert h.handle("highlight", {"hide": True})["result"] == "highlight cleared"
        assert js("() => document.querySelectorAll('[data-visus-highlight]').length") == 0
    finally:
        h.close()
