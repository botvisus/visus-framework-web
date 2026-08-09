"""Page-level CLI surface: highlight, boxes, scoped eval, resize, storage,
cookies, generate-locator, session pdf/screenshot."""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.api.fields import Field
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


# ---------------------------------------------------------------------------
# --boxes on list-fields / snapshot
# ---------------------------------------------------------------------------


def _field(index: int, name: str, box: dict[str, float] | None) -> Field:
    return Field(
        index=index,
        kind="button",
        tag="button",
        type=None,
        role="button",
        name=name,
        label=None,
        placeholder=None,
        value=None,
        checked=None,
        disabled=False,
        visible=True,
        frame=[],
        shadow=False,
        locator="#b",
        locator_kind="id",
        css="#b",
        xpath="//button",
        code='page.get_by_role("button", name="Go")',
        deep=False,
        box=box,
    )


class _BoxPage:
    url = "http://x/"

    def title(self) -> str:
        return "box fixture"

    def list_fields(
        self, *, kinds: Any = None, include_hidden: bool = False, highlight: bool = True
    ) -> list[Field]:
        return [_field(0, "Go", {"x": 1.0, "y": 2.0, "width": 30.0, "height": 12.0})]

    # PLAN 4 widened Page.snapshot to (selector, *, depth) -- mirror the real shape.
    def snapshot(
        self, selector: str | None = None, *, depth: int | None = None
    ) -> list[dict[str, Any]]:
        return [
            {"role": "button", "name": "Go", "rect": {"x": 1.0, "y": 2.0, "w": 30.0, "h": 12.0}}
        ]


def test_norm_rect_maps_the_bundle_keys_to_bounding_box_keys() -> None:
    assert session_server._norm_rect({"x": 1, "y": 2, "w": 3, "h": 4}) == {
        "x": 1.0,
        "y": 2.0,
        "width": 3.0,
        "height": 4.0,
    }
    assert session_server._norm_rect(None) is None
    assert session_server._norm_rect("nope") is None


def test_op_list_fields_strips_the_box_unless_asked() -> None:
    h = _handler(_BoxPage())
    plain = h.handle("list_fields", {})["result"]["fields"][0]
    assert "box" not in plain
    boxed = h.handle("list_fields", {"boxes": True})["result"]["fields"][0]
    assert boxed["box"] == {"x": 1.0, "y": 2.0, "width": 30.0, "height": 12.0}


def test_op_snapshot_strips_the_rect_unless_asked() -> None:
    """The raw bundle `rect` never leaks; `boxes` renames it to the box shape.

    PLAN 4 owns the rest of this op's payload (`ref` per row, plus `url`/`title`),
    so this asserts only on the keys THIS task adds and removes.
    """
    h = _handler(_BoxPage())
    plain = h.handle("snapshot", {})["result"]["elements"][0]
    assert plain["role"] == "button" and plain["name"] == "Go"
    assert "rect" not in plain and "box" not in plain
    boxed = h.handle("snapshot", {"boxes": True})["result"]["elements"][0]
    assert boxed["role"] == "button" and boxed["name"] == "Go"
    assert "rect" not in boxed
    assert boxed["box"] == {"x": 1.0, "y": 2.0, "width": 30.0, "height": 12.0}


def test_format_fields_adds_a_box_column() -> None:
    rows = [_field(0, "Go", {"x": 1.4, "y": 2.6, "width": 30.0, "height": 12.0}).to_dict()]
    plain = console.format_fields(rows, width=200)
    assert "BOX" not in plain
    boxed = console.format_fields(rows, width=200, boxes=True)
    assert "BOX" in boxed and "1,3,30,12" in boxed
    # PLAN 4's `full` flag still works, and composes with `boxes`.
    both = console.format_fields(rows, width=200, full=True, boxes=True)
    assert "XPATH" in both and "BOX" in both


def test_cli_list_fields_and_snapshot_boxes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        calls.append((op, args or {}))
        if op == "list_fields":
            return {
                "fields": [
                    _field(0, "Go", {"x": 1.0, "y": 2.0, "width": 30.0, "height": 12.0}).to_dict()
                ]
            }
        return {
            "elements": [
                {
                    "role": "button",
                    "name": "Go",
                    "box": {"x": 1.0, "y": 2.0, "width": 30.0, "height": 12.0},
                }
            ]
        }

    monkeypatch.setattr(session_client, "send", fake_send)
    r1 = runner.invoke(app, ["list-fields", "--boxes", "--no-highlight"])
    assert r1.exit_code == 0, r1.output
    assert calls[0][1]["boxes"] is True
    assert "BOX" in r1.output
    r2 = runner.invoke(app, ["snapshot", "--boxes"])
    assert r2.exit_code == 0
    # PLAN 4's snapshot command also sends selector/depth/refs -- assert the subset.
    assert calls[1][0] == "snapshot" and calls[1][1]["boxes"] is True
    assert "BOX" in r2.output and "1,2,30,12" in r2.output


def test_repl_boxes() -> None:
    """`--boxes` must not be mistaken for a scope selector by `snapshot`."""
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        if op == "list_fields":
            return {"fields": []}
        return {"elements": []}

    console.dispatch("list --boxes", send)
    console.dispatch("snapshot --boxes", send)
    assert calls[0][0] == "list_fields" and calls[0][1]["boxes"] is True
    assert calls[0][1]["highlight"] is False  # PLAN 4: `list` is a read
    assert calls[1][0] == "snapshot" and calls[1][1]["boxes"] is True
    assert calls[1][1]["selector"] is None  # PLAN 4's scope arg, not the flag


@pytest.mark.browser
def test_boxes_come_from_a_real_page(base_url: str) -> None:
    """fields.html's #btn is a laid-out button, so its rect must be non-degenerate."""
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/fields.html"
    )
    try:
        fields = h.handle("list_fields", {"highlight": False, "boxes": True})["result"]["fields"]
        btn = next(f for f in fields if f["locator"] == "#btn")
        box = btn["box"]
        assert box is not None and box["width"] > 0 and box["height"] > 0

        elements = h.handle("snapshot", {"boxes": True})["result"]["elements"]
        go = next(e for e in elements if e["name"] == "Click me")
        assert go["box"]["width"] > 0
    finally:
        h.close()
