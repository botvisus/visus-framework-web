"""Page-level CLI surface: highlight, boxes, scoped eval, resize, storage,
cookies, generate-locator, session pdf/screenshot."""

from __future__ import annotations

from pathlib import Path
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
        self,
        *,
        kinds: Any = None,
        include_hidden: bool = False,
        highlight: bool = True,
        clickables: bool = False,
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


# ---------------------------------------------------------------------------
# element-scoped eval (CLI + MCP)
# ---------------------------------------------------------------------------


class _EvalLocator:
    def __init__(self, log: list[str], label: str) -> None:
        self._log = log
        self._label = label

    def first(self) -> _EvalLocator:
        return self

    def evaluate(self, expression: str, arg: object = None) -> object:
        self._log.append(f"loc.evaluate:{self._label}:{expression}:{arg!r}")
        return "element-value"


class _EvalPage:
    url = "http://x/"

    def __init__(self) -> None:
        self.log: list[str] = []

    def locator(self, selector: str, *, deep: bool = False) -> _EvalLocator:
        return _EvalLocator(self.log, f"loc({selector})")

    def evaluate(self, expression: str, arg: object = None) -> object:
        self.log.append(f"page.evaluate:{expression}:{arg!r}")
        return "page-value"


def test_op_eval_without_a_target_stays_on_the_page() -> None:
    page = _EvalPage()
    h = _handler(page)
    out = h.handle("eval", {"expression": "() => document.title", "arg": None})
    assert out["result"] == {"result": "page-value"}
    assert page.log == ["page.evaluate:() => document.title:None"]


def test_op_eval_with_a_target_runs_on_the_element() -> None:
    page = _EvalPage()
    h = _handler(page)
    out = h.handle("eval", {"expression": "(el) => el.id", "selector": "#b", "arg": 7})
    assert out["result"] == {"result": "element-value"}
    assert page.log == ["loc.evaluate:loc(#b):(el) => el.id:7"]


def test_cli_eval_forwards_the_target(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send_envelope",
        lambda op, args=None, **_: calls.append((op, args or {}))
        or {"ok": True, "result": {"result": "v"}, "page": {"url": "http://x/", "title": "T"}},
    )
    assert runner.invoke(app, ["eval", "() => document.title"]).exit_code == 0
    assert runner.invoke(app, ["eval", "(el) => el.id", "--index", "3"]).exit_code == 0
    assert runner.invoke(app, ["eval", "(el) => el.id", "-s", "#b"]).exit_code == 0
    assert calls[0] == ("eval", {"expression": "() => document.title", "arg": None})
    assert calls[1][1]["index"] == 3 and calls[1][1]["expression"] == "(el) => el.id"
    assert calls[2][1]["selector"] == "#b"


def test_repl_eval_and_eval_on() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return {"result": "v"}

    console.dispatch("eval () => document.title", send)
    console.dispatch("eval-on 3 (el) => el.id", send)
    console.dispatch("eval-on #b (el) => el.id", send)
    assert calls[0] == ("eval", {"expression": "() => document.title"})
    assert calls[1] == ("eval", {"index": 3, "expression": "(el) => el.id"})
    assert calls[2] == ("eval", {"selector": "#b", "expression": "(el) => el.id"})
    assert "eval-on" in console.dispatch("help", send)


def test_mcp_browser_evaluate_accepts_a_target() -> None:
    """The MCP tool must gain the same scoping, not just the CLI."""
    import inspect

    from visus.web.mcp import server as mcp_server

    params = inspect.signature(mcp_server.browser_evaluate).parameters
    for want in ("selector", "role", "name", "text", "exact", "frame"):
        assert want in params, f"browser_evaluate is missing {want!r}"


@pytest.mark.browser
def test_scoped_eval_against_a_real_page(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/fields.html"
    )
    try:
        page_level = h.handle("eval", {"expression": "() => document.title"})
        assert page_level["result"]["result"] == "fields fixture"

        scoped = h.handle(
            "eval", {"expression": "(el) => el.textContent", "selector": "#btn"}
        )
        assert scoped["ok"] is True, scoped
        assert scoped["result"]["result"] == "Click me"

        with_arg = h.handle(
            "eval",
            {"expression": "(el, n) => el.id.repeat(n)", "selector": "#btn", "arg": 2},
        )
        assert with_arg["result"]["result"] == "btnbtn"
    finally:
        h.close()


# ---------------------------------------------------------------------------
# resize
# ---------------------------------------------------------------------------


class _ResizePage:
    url = "http://x/"

    def __init__(self) -> None:
        self.sized: tuple[int, int] | None = None

    def set_viewport_size(self, width: int, height: int) -> None:
        self.sized = (width, height)

    def evaluate(self, expression: str, arg: object = None) -> object:
        # The window manager clamped the width -- the op must report what it got.
        return {"w": 900, "h": 720}


def test_op_resize_reports_the_achieved_size() -> None:
    page = _ResizePage()
    h = _handler(page)
    out = h.handle("resize", {"width": 1024, "height": 720})
    assert out["ok"] is True, out
    assert page.sized == (1024, 720)
    assert out["result"] == {"width": 900, "height": 720}


def test_cli_resize(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {}))
        or {"width": 1024, "height": 720},
    )
    r = runner.invoke(app, ["resize", "1024", "720"])
    assert r.exit_code == 0, r.output
    assert calls[0] == ("resize", {"width": 1024, "height": 720})
    assert "1024x720" in r.output


def test_repl_resize() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return {"width": 800, "height": 600}

    out = console.dispatch("resize 800 600", send)
    assert calls[0] == ("resize", {"width": 800, "height": 600})
    assert "800x600" in out
    assert "resize" in console.dispatch("help", send)


@pytest.mark.browser
def test_resize_changes_the_real_viewport(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/fields.html"
    )
    try:
        out = h.handle("resize", {"width": 900, "height": 600})
        assert out["ok"] is True, out
        assert out["result"]["width"] == 900
        assert out["result"]["height"] == 600
        inner = h.handle("eval", {"expression": "() => window.innerWidth"})
        assert inner["result"]["result"] == 900
    finally:
        h.close()


# ---------------------------------------------------------------------------
# web storage
# ---------------------------------------------------------------------------


class _StoragePage:
    """Evaluates the storage helpers against two in-memory dicts."""

    url = "http://x/"

    def __init__(self) -> None:
        self.local: dict[str, str] = {"token": "abc", "empty": ""}
        self.session: dict[str, str] = {"tab": "1"}
        self.seen: list[str] = []

    def evaluate(self, expression: str, arg: object = None) -> object:
        self.seen.append(expression)
        a = arg if isinstance(arg, dict) else {}
        store = self.session if a.get("session") else self.local
        key = str(a.get("key", ""))
        if "st.key(" in expression:
            return [{"name": k, "value": v} for k, v in store.items()]
        if "setItem" in expression:
            store[key] = str(a.get("value", ""))
            return True
        if "removeItem" in expression:
            had = key in store
            store.pop(key, None)
            return had
        if "st.clear()" in expression:
            n = len(store)
            store.clear()
            return n
        v = store.get(key)
        return {"value": v, "present": v is not None}


def test_op_storage_round_trip_on_local_and_session() -> None:
    page = _StoragePage()
    h = _handler(page)

    listed = h.handle("storage_list", {})["result"]
    assert listed["kind"] == "localStorage"
    assert {i["name"] for i in listed["items"]} == {"token", "empty"}

    assert h.handle("storage_get", {"key": "token"})["result"] == {
        "value": "abc",
        "present": True,
    }
    # An empty value and a missing key must be distinguishable.
    assert h.handle("storage_get", {"key": "empty"})["result"] == {"value": "", "present": True}
    assert h.handle("storage_get", {"key": "nope"})["result"] == {
        "value": None,
        "present": False,
    }

    assert h.handle("storage_set", {"key": "k", "value": "v"})["result"] == (
        "localStorage['k'] = 'v'"
    )
    assert page.local["k"] == "v"
    assert h.handle("storage_delete", {"key": "k"})["result"] == {"deleted": True}
    assert h.handle("storage_delete", {"key": "k"})["result"] == {"deleted": False}

    assert h.handle("storage_list", {"session": True})["result"]["kind"] == "sessionStorage"
    assert h.handle("storage_get", {"key": "tab", "session": True})["result"]["value"] == "1"
    assert h.handle("storage_clear", {"session": True})["result"] == {"cleared": 1}
    assert page.session == {}
    assert page.local  # clearing sessionStorage must not touch localStorage


def test_cli_storage_subcommands(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        calls.append((op, args or {}))
        if op == "storage_list":
            return {"kind": "localStorage", "items": [{"name": "token", "value": "abc"}]}
        if op == "storage_get":
            return {"value": "abc", "present": True}
        if op == "storage_delete":
            return {"deleted": True}
        if op == "storage_clear":
            return {"cleared": 3}
        return "localStorage['k'] = 'v'"

    monkeypatch.setattr(session_client, "send", fake_send)
    assert runner.invoke(app, ["storage", "list"]).exit_code == 0
    r_get = runner.invoke(app, ["storage", "get", "token"])
    assert r_get.exit_code == 0 and "abc" in r_get.output
    assert runner.invoke(app, ["storage", "set", "k", "v"]).exit_code == 0
    assert runner.invoke(app, ["storage", "delete", "k"]).exit_code == 0
    assert runner.invoke(app, ["storage", "clear", "--session-storage"]).exit_code == 0
    assert calls[0] == ("storage_list", {"session": False})
    assert calls[1] == ("storage_get", {"key": "token", "session": False})
    assert calls[2] == ("storage_set", {"key": "k", "value": "v", "session": False})
    assert calls[3] == ("storage_delete", {"key": "k", "session": False})
    assert calls[4] == ("storage_clear", {"session": True})


def test_cli_storage_get_missing_key_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_client, "send", lambda op, args=None: {"value": None, "present": False}
    )
    r = runner.invoke(app, ["storage", "get", "nope"])
    assert r.exit_code == 1


def test_repl_storage_branches() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        if op == "storage_list":
            return {"kind": "localStorage", "items": []}
        if op == "storage_get":
            return {"value": "abc", "present": True}
        return {"deleted": True, "cleared": 0}

    console.dispatch("storage list", send)
    console.dispatch("storage get token", send)
    console.dispatch("storage set k some value", send)
    console.dispatch("session-storage delete tab", send)
    assert calls[0] == ("storage_list", {"session": False})
    assert calls[1] == ("storage_get", {"key": "token", "session": False})
    assert calls[2] == ("storage_set", {"key": "k", "value": "some value", "session": False})
    assert calls[3] == ("storage_delete", {"key": "tab", "session": True})
    assert "storage" in console.dispatch("help", send)


@pytest.mark.browser
def test_storage_ops_against_a_real_page(base_url: str) -> None:
    """storage.html seeds token=seed-local and tab=seed-session on every load."""
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/storage.html"
    )
    try:
        assert h.handle("storage_get", {"key": "token"})["result"] == {
            "value": "seed-local",
            "present": True,
        }
        assert h.handle("storage_get", {"key": "tab", "session": True})["result"] == {
            "value": "seed-session",
            "present": True,
        }
        assert h.handle("storage_get", {"key": "absent"})["result"]["present"] is False

        h.handle("storage_set", {"key": "token", "value": "written"})
        assert h.handle("storage_get", {"key": "token"})["result"]["value"] == "written"

        names = {
            i["name"] for i in h.handle("storage_list", {})["result"]["items"]
        }
        assert "token" in names

        assert h.handle("storage_delete", {"key": "token"})["result"] == {"deleted": True}
        assert h.handle("storage_get", {"key": "token"})["result"]["present"] is False

        cleared = h.handle("storage_clear", {"session": True})["result"]["cleared"]
        assert cleared >= 1
        assert h.handle("storage_get", {"key": "tab", "session": True})["result"][
            "present"
        ] is False
    finally:
        h.close()


# ---------------------------------------------------------------------------
# cookie-get / cookie-set / cookie-delete, and cookies --domain/--path
# ---------------------------------------------------------------------------


class _CookieContext:
    def __init__(self) -> None:
        self.store: list[dict[str, Any]] = [
            {"name": "sid", "value": "abc", "domain": "example.com", "path": "/"},
            {"name": "sid", "value": "xyz", "domain": "other.com", "path": "/"},
            {"name": "pref", "value": "", "domain": "example.com", "path": "/app"},
        ]
        self.rejects: set[str] = set()

    def cookies(self) -> list[dict[str, Any]]:
        return [dict(c) for c in self.store]

    def add_cookies(self, cookies: list[dict[str, Any]]) -> None:
        for c in cookies:
            if c.get("domain") in self.rejects:
                raise RuntimeError(f"cannot set a cookie for {c.get('domain')}")
            self.store.append(dict(c))

    def clear_cookies(self) -> None:
        self.store.clear()


class _CookiePage:
    url = "http://example.com/"


def _cookie_handler(ctx: _CookieContext) -> session_server.SessionHandler:
    h = _handler(_CookiePage())
    h.context = lambda: ctx  # type: ignore[assignment,method-assign,return-value]
    return h


def test_cookie_matches_filters_on_name_domain_and_path() -> None:
    c = {"name": "sid", "domain": "example.com", "path": "/app"}
    assert session_server._cookie_matches(c, name="sid", domain=None, path=None) is True
    assert session_server._cookie_matches(c, name="nope", domain=None, path=None) is False
    assert session_server._cookie_matches(c, name=None, domain="example.com", path=None) is True
    # A leading dot on the stored domain must not defeat the filter.
    assert session_server._cookie_matches(
        {"name": "sid", "domain": ".example.com", "path": "/"},
        name=None,
        domain="example.com",
        path=None,
    ) is True
    assert session_server._cookie_matches(c, name=None, domain=None, path="/app") is True
    assert session_server._cookie_matches(c, name=None, domain=None, path="/") is False


def test_op_cookies_filters_by_domain_and_path() -> None:
    h = _cookie_handler(_CookieContext())
    everything = h.handle("cookies", {})["result"]["cookies"]
    assert len(everything) == 3
    by_domain = h.handle("cookies", {"domain": "example.com"})["result"]["cookies"]
    assert {c["name"] for c in by_domain} == {"sid", "pref"}
    by_path = h.handle("cookies", {"path": "/app"})["result"]["cookies"]
    assert [c["name"] for c in by_path] == ["pref"]


def test_op_cookie_get_distinguishes_empty_from_missing() -> None:
    h = _cookie_handler(_CookieContext())
    hit = h.handle("cookie_get", {"name": "sid", "domain": "other.com"})["result"]
    assert hit == {"value": "xyz", "present": True, "cookie": {
        "name": "sid", "value": "xyz", "domain": "other.com", "path": "/"
    }}
    empty = h.handle("cookie_get", {"name": "pref"})["result"]
    assert empty["value"] == "" and empty["present"] is True
    missing = h.handle("cookie_get", {"name": "nope"})["result"]
    assert missing == {"value": None, "present": False, "cookie": None}


def test_op_cookie_set_uses_the_context() -> None:
    ctx = _CookieContext()
    h = _cookie_handler(ctx)
    out = h.handle("cookie_set", {"name": "tok", "value": "1", "path": "/"})["result"]
    assert out == "set cookie 'tok'"
    assert any(c["name"] == "tok" and c["path"] == "/" for c in ctx.store)


def test_op_cookie_delete_readds_the_survivors_and_reports_drops() -> None:
    ctx = _CookieContext()
    ctx.rejects = {"other.com"}  # WebDriver refuses a foreign-domain cookie
    h = _cookie_handler(ctx)
    out = h.handle("cookie_delete", {"name": "pref"})["result"]
    assert out == {"deleted": 1, "restored": 1, "dropped": 1}
    names = {c["name"] for c in ctx.store}
    assert names == {"sid"}  # the example.com sid survived; pref is gone
    assert len(ctx.store) == 1  # the other.com sid could not be restored


def test_cli_cookie_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        calls.append((op, args or {}))
        if op == "cookie_get":
            return {"value": "abc", "present": True, "cookie": {"name": "sid"}}
        if op == "cookie_delete":
            return {"deleted": 1, "restored": 2, "dropped": 0}
        if op == "cookies":
            return {"cookies": [{"name": "sid", "value": "abc", "domain": "example.com"}]}
        return "set cookie 'tok'"

    monkeypatch.setattr(session_client, "send", fake_send)
    r_get = runner.invoke(app, ["cookie-get", "sid", "--domain", "example.com"])
    assert r_get.exit_code == 0 and "abc" in r_get.output
    assert runner.invoke(app, ["cookie-set", "tok", "1", "--path", "/api"]).exit_code == 0
    assert runner.invoke(app, ["cookie-delete", "sid"]).exit_code == 0
    assert runner.invoke(app, ["cookies", "--domain", "example.com"]).exit_code == 0
    assert calls[0] == ("cookie_get", {"name": "sid", "domain": "example.com", "path": None})
    assert calls[1][0] == "cookie_set" and calls[1][1]["path"] == "/api"
    assert calls[2] == ("cookie_delete", {"name": "sid", "domain": None, "path": None})
    assert calls[3] == ("cookies", {"domain": "example.com", "path": None})


def test_cli_cookie_get_missing_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: {"value": None, "present": False, "cookie": None},
    )
    assert runner.invoke(app, ["cookie-get", "nope"]).exit_code == 1


def test_repl_cookie_commands() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        if op == "cookie_get":
            return {"value": "abc", "present": True, "cookie": {}}
        if op == "cookie_delete":
            return {"deleted": 1, "restored": 0, "dropped": 0}
        return "set cookie 'tok'"

    assert console.dispatch("cookie-get sid", send) == "abc"
    console.dispatch("cookie-set tok 1", send)
    console.dispatch("cookie-delete sid", send)
    assert calls[0] == ("cookie_get", {"name": "sid", "domain": None, "path": None})
    assert calls[1] == ("cookie_set", {"name": "tok", "value": "1", "path": "/", "domain": None})
    assert calls[2] == ("cookie_delete", {"name": "sid", "domain": None, "path": None})
    assert "cookie-get" in console.dispatch("help", send)


@pytest.mark.browser
def test_cookie_ops_against_a_real_browser(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/fields.html"
    )
    try:
        assert h.handle("cookie_set", {"name": "tok", "value": "v1", "path": "/"})["ok"] is True
        got = h.handle("cookie_get", {"name": "tok"})["result"]
        assert got["present"] is True and got["value"] == "v1"

        assert h.handle("cookie_set", {"name": "other", "value": "v2", "path": "/"})["ok"] is True
        assert len(h.handle("cookies", {})["result"]["cookies"]) >= 2

        deleted = h.handle("cookie_delete", {"name": "tok"})["result"]
        assert deleted["deleted"] == 1
        assert h.handle("cookie_get", {"name": "tok"})["result"]["present"] is False
        assert h.handle("cookie_get", {"name": "other"})["result"]["present"] is True
    finally:
        h.close()


# ---------------------------------------------------------------------------
# generate-locator
# ---------------------------------------------------------------------------


def test_locator_expr_mirrors_make_locator_branch_order() -> None:
    from visus.web.cli.codegen import locator_expr

    assert locator_expr(role="button", name="Save") == 'page.get_by_role("button", name="Save")'
    assert locator_expr(role="button", name="Save", exact=True) == (
        'page.get_by_role("button", name="Save", exact=True)'
    )
    assert locator_expr(text="Sign in") == 'page.get_by_text("Sign in")'
    assert locator_expr(selector="#u") == 'page.locator("#u")'
    # role wins over text wins over selector -- the same order as make_locator.
    assert locator_expr(selector="#u", role="button") == 'page.get_by_role("button")'
    assert locator_expr(selector="#u", frame="#f1") == 'page.frame_locator("#f1").locator("#u")'
    with pytest.raises(ValueError, match="provide one of"):
        locator_expr()


def test_op_generate_locator_from_the_field_cache() -> None:
    h = _handler(_BoxPage())
    h.handle("list_fields", {})  # populates the cache
    out = h.handle("generate_locator", {"index": 0})["result"]
    assert out == {
        "code": 'page.get_by_role("button", name="Go")',
        "css": "#b",
        "xpath": "//button",
    }
    bad = h.handle("generate_locator", {"index": 5})
    assert bad["ok"] is False and "out of range" in bad["error"]


def test_op_generate_locator_from_a_selector_target() -> None:
    h = _handler(_BoxPage())
    out = h.handle("generate_locator", {"role": "button", "name": "Save"})["result"]
    assert out == {
        "code": 'page.get_by_role("button", name="Save")',
        "css": None,
        "xpath": None,
    }


def test_cli_generate_locator(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {}))
        or {"code": 'page.locator("#u")', "css": "#u", "xpath": "//input"},
    )
    r = runner.invoke(app, ["generate-locator", "3"])
    assert r.exit_code == 0, r.output
    assert calls[0] == ("generate_locator", {"index": 3})
    assert 'page.locator("#u")' in r.output
    assert "//input" in r.output


def test_cli_generate_locator_raw_prints_only_the_expression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--raw` means the expression alone: the emitted value is a `str`, so PLAN 4's
    `emit` drops the css/xpath table under RAW (Prerequisites rule 6)."""
    from visus.web.cli import output

    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: {"code": 'page.locator("#u")', "css": "#u", "xpath": "//input"},
    )
    try:
        r = runner.invoke(app, ["generate-locator", "3", "--raw"])
        assert r.exit_code == 0, r.output
        assert r.output == 'page.locator("#u")\n'
    finally:
        output.set_mode()


def test_repl_generate_locator() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return {"code": 'page.locator("#u")', "css": None, "xpath": None}

    out = console.dispatch("generate-locator #u", send)
    assert calls[0] == ("generate_locator", {"selector": "#u"})
    assert out == 'page.locator("#u")'
    assert "generate-locator" in console.dispatch("help", send)


@pytest.mark.browser
def test_generate_locator_matches_the_list_fields_column(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/fields.html"
    )
    try:
        fields = h.handle("list_fields", {"highlight": False})["result"]["fields"]
        i = next(n for n, f in enumerate(fields) if f["locator"] == "#btn")
        out = h.handle("generate_locator", {"index": i})["result"]
        assert out["code"] == fields[i]["code"]
        assert out["css"] == fields[i]["css"]
    finally:
        h.close()


# ---------------------------------------------------------------------------
# session pdf
# ---------------------------------------------------------------------------


class _PdfPage:
    url = "http://x/"

    def __init__(self) -> None:
        self.written: str | None = None

    def pdf(self, *, path: str | None = None) -> bytes:
        self.written = path
        if path is not None:
            Path(path).write_bytes(b"%PDF-1.4\n")
        return b"%PDF-1.4\n"


def test_op_pdf_writes_and_returns_the_absolute_path(tmp_path: Path) -> None:
    page = _PdfPage()
    h = _handler(page)
    target = tmp_path / "out.pdf"
    out = h.handle("pdf", {"path": str(target)})
    assert out["ok"] is True, out
    assert out["result"] == str(target.resolve())
    assert page.written == str(target)
    assert target.read_bytes().startswith(b"%PDF")


def test_cli_session_pdf_resolves_against_the_client_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {})) or str(tmp_path / "out.pdf"),
    )
    r = runner.invoke(app, ["session-pdf", "-o", str(tmp_path / "out.pdf")])
    assert r.exit_code == 0, r.output
    assert calls[0] == ("pdf", {"path": str((tmp_path / "out.pdf").resolve())})
    assert "out.pdf" in r.output


def test_repl_pdf_resolves_against_the_client_cwd() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return "/abs/page.pdf"

    out = console.dispatch("pdf report.pdf", send)
    assert calls[0] == ("pdf", {"path": str(Path("report.pdf").resolve())})
    assert "saved /abs/page.pdf" == out
    console.dispatch("pdf", send)
    assert calls[1][1]["path"].endswith("page.pdf")
    assert "pdf" in console.dispatch("help", send)


@pytest.mark.browser
def test_session_pdf_against_a_real_page(base_url: str, tmp_path: Path) -> None:
    target = tmp_path / "page.pdf"
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/forms.html"
    )
    try:
        out = h.handle("pdf", {"path": str(target)})
        assert out["ok"] is True, out
        assert out["result"] == str(target.resolve())
    finally:
        h.close()
    assert target.read_bytes().startswith(b"%PDF")


# ---------------------------------------------------------------------------
# --hires
# ---------------------------------------------------------------------------


def _png_size(path: Path) -> tuple[int, int]:
    """Width/height straight out of the PNG IHDR chunk -- no image library needed."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


class _HiresPage:
    url = "http://x/"

    def __init__(self, *, fail: bool = False) -> None:
        self.metrics: list[tuple[int, int, float]] = []
        self.shots = 0
        self._fail = fail

    def evaluate(self, expression: str, arg: object = None) -> object:
        return {"w": 800, "h": 600}

    def set_device_metrics(
        self, width: int, height: int, *, device_scale_factor: float = 1.0, mobile: bool = False
    ) -> None:
        self.metrics.append((width, height, device_scale_factor))

    def screenshot(self, *, path: str | None = None, full_page: bool = False) -> bytes:
        if self._fail:
            raise RuntimeError("capture blew up")
        self.shots += 1
        if path is not None:
            Path(path).write_bytes(b"png")
        return b"png"


def test_op_screenshot_hires_sets_then_restores_the_scale(tmp_path: Path) -> None:
    page = _HiresPage()
    h = _handler(page)
    out = h.handle("screenshot", {"path": str(tmp_path / "s.png"), "hires": True})
    assert out["ok"] is True, out
    assert page.shots == 1
    assert page.metrics == [(800, 600, 2.0), (800, 600, 1.0)]


def test_op_screenshot_without_hires_touches_no_metrics(tmp_path: Path) -> None:
    page = _HiresPage()
    h = _handler(page)
    h.handle("screenshot", {"path": str(tmp_path / "s.png")})
    assert page.metrics == []


def test_op_screenshot_hires_restores_even_when_the_capture_fails(tmp_path: Path) -> None:
    page = _HiresPage(fail=True)
    h = _handler(page)
    bad = h.handle("screenshot", {"path": str(tmp_path / "s.png"), "hires": True})
    assert bad["ok"] is False and "capture blew up" in bad["error"]
    assert page.metrics == [(800, 600, 2.0), (800, 600, 1.0)]


def test_cli_session_screenshot_hires(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {})) or str(tmp_path / "s.png"),
    )
    assert runner.invoke(app, ["session-screenshot", "-o", str(tmp_path / "s.png")]).exit_code == 0
    assert (
        runner.invoke(
            app, ["session-screenshot", "-o", str(tmp_path / "s.png"), "--hires"]
        ).exit_code
        == 0
    )
    assert "hires" not in calls[0][1]  # default payload unchanged
    assert calls[1][1]["hires"] is True


def test_repl_screenshot_hires() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return "/abs/s.png"

    console.dispatch("screenshot s.png", send)
    console.dispatch("screenshot s.png --hires", send)
    assert "hires" not in calls[0][1]
    assert calls[1][1]["hires"] is True
    assert calls[1][1]["path"] == str(Path("s.png").resolve())


@pytest.mark.browser
def test_hires_doubles_the_pixel_dimensions(base_url: str, tmp_path: Path) -> None:
    normal, hires = tmp_path / "n.png", tmp_path / "h.png"
    after = tmp_path / "after.png"
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/fields.html"
    )
    try:
        h.handle("resize", {"width": 800, "height": 600})
        assert h.handle("screenshot", {"path": str(normal)})["ok"] is True
        assert h.handle("screenshot", {"path": str(hires), "hires": True})["ok"] is True
        # And the session is back at 1x afterwards.
        assert h.handle("screenshot", {"path": str(after)})["ok"] is True
    finally:
        h.close()

    nw, nh = _png_size(normal)
    hw, hh = _png_size(hires)
    aw, _ = _png_size(after)
    assert hw >= nw * 2 - 2 and hh >= nh * 2 - 2, (nw, nh, hw, hh)
    assert abs(aw - nw) <= 2, (nw, aw)


# ---------------------------------------------------------------------------
# screenshot / pdf: URL = one-off browser, no URL = the live session
# ---------------------------------------------------------------------------


def _all_output(result: Any) -> str:
    """stdout + stderr, across Click versions.

    Click < 8.2 mixes stderr into ``output`` and raises on ``.stderr``;
    Click >= 8.2 captures them separately.
    """
    try:
        return result.output + result.stderr
    except ValueError:
        return result.output


class _OneShotPage:
    def __init__(self, seen: dict[str, Any]) -> None:
        self._seen = seen

    def goto(self, url: str) -> None:
        self._seen["goto"] = url

    def screenshot(self, *, path: str | None = None, full_page: bool = False) -> bytes:
        self._seen["shot"] = path
        Path(path or "s.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        return b"png"

    def pdf(self, *, path: str | None = None) -> bytes:
        self._seen["pdf"] = path
        Path(path or "p.pdf").write_bytes(b"%PDF-1.4\n")
        return b"pdf"


class _OneShotBrowser:
    def __init__(self, seen: dict[str, Any]) -> None:
        self._seen = seen

    def new_page(self) -> _OneShotPage:
        return _OneShotPage(self._seen)

    def __enter__(self) -> _OneShotBrowser:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def close(self) -> None:
        pass


def _patch_one_shot(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from visus.web.cli import main as cli_main

    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli_main, "launch", lambda engine, **kw: _OneShotBrowser(seen))
    return seen


def test_screenshot_with_a_url_uses_a_one_off_browser(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _patch_one_shot(monkeypatch)
    sent: list[str] = []
    monkeypatch.setattr(session_client, "send", lambda op, args=None: sent.append(op))
    out = tmp_path / "s.png"
    r = runner.invoke(app, ["screenshot", "http://example.com", "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert seen["goto"] == "http://example.com"
    assert seen["shot"] == str(out)
    assert sent == [], "a URL must never touch the daemon"


def test_screenshot_without_a_url_hits_the_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {})) or str(tmp_path / "s.png"),
    )
    out = tmp_path / "s.png"
    r = runner.invoke(app, ["screenshot", "-o", str(out), "--full-page", "--hires"])
    assert r.exit_code == 0, r.output
    assert calls[0][0] == "screenshot"
    assert calls[0][1]["path"] == str(out.resolve())
    assert calls[0][1]["full_page"] is True
    assert calls[0][1]["hires"] is True


def test_screenshot_without_a_url_accepts_a_session_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {})) or "ok",
    )
    r = runner.invoke(app, ["screenshot", "-o", str(tmp_path / "s.png"), "-i", "4"])
    assert r.exit_code == 0, r.output
    assert calls[0][1]["index"] == 4


def test_pdf_with_and_without_a_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _patch_one_shot(monkeypatch)
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {})) or str(tmp_path / "p.pdf"),
    )
    out = tmp_path / "p.pdf"
    assert runner.invoke(app, ["pdf", "http://example.com", "-o", str(out)]).exit_code == 0
    assert seen["pdf"] == str(out)
    assert calls == []

    assert runner.invoke(app, ["pdf", "-o", str(out)]).exit_code == 0
    assert calls[0] == ("pdf", {"path": str(out.resolve())})


def test_deprecated_aliases_still_work_and_warn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {})) or "ok",
    )
    r1 = runner.invoke(app, ["session-screenshot", "-o", str(tmp_path / "s.png"), "2"])
    assert r1.exit_code == 0, r1.output
    text1 = _all_output(r1)
    assert "deprecated" in text1 and "visus screenshot" in text1
    assert calls[0][0] == "screenshot" and calls[0][1]["index"] == 2

    r2 = runner.invoke(app, ["session-pdf", "-o", str(tmp_path / "p.pdf")])
    assert r2.exit_code == 0
    text2 = _all_output(r2)
    assert "deprecated" in text2 and "visus pdf" in text2
    assert calls[1][0] == "pdf"


def test_deprecation_notices_go_to_stderr() -> None:
    """A piped `visus session-screenshot > out` must not get the warning in its stdout."""
    import inspect

    from visus.web.cli import main as cli_main

    for fn in (cli_main.session_screenshot, cli_main.session_pdf):
        assert "err=True" in inspect.getsource(fn), f"{fn.__name__} must warn on stderr"
