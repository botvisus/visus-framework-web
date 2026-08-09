"""Pixel targeting: click by template image and by rendered text."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import console, session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


def _crop_template(handler: Any, tmp_path: Path, box_css: tuple[int, int, int, int]) -> Path:
    """Crop a template out of the page's own screenshot (device-pixel aware).

    Self-cropping keeps the test deterministic: the needle is by construction the
    exact pixels the browser painted, so a match failure means the PIPELINE broke,
    not that a hand-drawn template drifted from the rendering.
    """
    from PIL import Image

    shot = handler.handle("screenshot", {"path": str(tmp_path / "page.png")})["result"]
    ratio = float(
        handler.handle("eval", {"expression": "() => window.devicePixelRatio"})["result"]["result"]
    )
    left, top, right, bottom = box_css
    crop = (int(left * ratio), int(top * ratio), int(right * ratio), int(bottom * ratio))
    out = tmp_path / "template.png"
    Image.open(shot).crop(crop).save(out)
    return out


@pytest.mark.browser
def test_click_image_presses_a_canvas_button_with_no_accessibility_tree(
    base_url: str, tmp_path: Path
) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/imagetarget.html"
    )
    try:
        assert h.handle("get_text", {"selector": "#clicked"})["result"]["value"] == "none"
        # Proof the ordinary vocabulary cannot reach it: nothing but a canvas.
        assert h.handle("count", {"role": "button"})["result"] == 0

        template = _crop_template(h, tmp_path, (300, 120, 420, 168))
        resp = h.handle("click_image", {"template_path": str(template), "confidence": 0.9})
        assert resp["ok"] is True, resp
        assert resp["result"]["confidence"] >= 0.9
        assert h.handle("get_text", {"selector": "#clicked"})["result"]["value"] == "image"
    finally:
        h.close()


@pytest.mark.browser
def test_click_image_not_found_is_an_actionable_error(base_url: str, tmp_path: Path) -> None:
    import numpy as np
    from PIL import Image

    needle = np.zeros((24, 24, 3), np.uint8)
    needle[6:18, 6:18, 0] = 200  # patterned, and provably absent from the fixture
    template = tmp_path / "absent.png"
    Image.fromarray(needle).save(template)

    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/imagetarget.html"
    )
    try:
        resp = h.handle("click_image", {"template_path": str(template), "confidence": 0.95})
        assert resp["ok"] is False
        assert "not found on the page" in resp["error"]
        assert "0.95" in resp["error"]
        assert h.handle("get_text", {"selector": "#clicked"})["result"]["value"] == "none"
    finally:
        h.close()


class _RatioPage:
    """Stand-in for the live page: `_device_pixel_ratio` only calls `evaluate`.

    A double is right here because the real behaviour — reading a browser's
    devicePixelRatio and clicking at the scaled point — is covered by the two
    browser tests above; what is NOT reachable through a real browser is the
    HiDPI and the garbage-answer branch, and those are what break the click maths.
    """

    def __init__(self, value: Any) -> None:
        self._value = value

    def evaluate(self, expression: str, arg: Any = None) -> Any:
        return self._value


def test_device_pixel_ratio_falls_back_to_one_when_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dead page, a non-numeric answer or a zero must all degrade to 1:1.

    `_device_pixel_ratio` calls `self.page()`, which would LAUNCH a browser — so
    the page is replaced rather than left to the lazy `_ensure`.
    """
    h = session_server.SessionHandler(engine="chrome", headless=True)

    def _no_page() -> Any:
        raise RuntimeError("session page is not available")

    monkeypatch.setattr(h, "page", _no_page)
    assert h._device_pixel_ratio() == 1.0

    monkeypatch.setattr(h, "page", lambda: _RatioPage("not-a-number"))
    assert h._device_pixel_ratio() == 1.0

    monkeypatch.setattr(h, "page", lambda: _RatioPage(None))
    assert h._device_pixel_ratio() == 1.0

    monkeypatch.setattr(h, "page", lambda: _RatioPage(0))
    assert h._device_pixel_ratio() == 1.0


def test_device_pixel_ratio_passes_a_hidpi_answer_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On a 2x display a match at screenshot (400,200) must be clicked at (200,100)."""
    h = session_server.SessionHandler(engine="chrome", headless=True)
    monkeypatch.setattr(h, "page", lambda: _RatioPage(2.0))
    assert h._device_pixel_ratio() == 2.0


def test_click_image_is_a_mutating_op() -> None:
    assert "click_image" in session_server._MUTATING_OPS


def test_cli_click_image_sends_the_resolved_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template = tmp_path / "t.png"
    template.write_bytes(b"PNG")
    sent: list[tuple[str, Any]] = []

    def fake(op: str, args: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
        sent.append((op, args))
        return {"ok": True, "result": {"x": 12.0, "y": 34.0, "confidence": 0.97}}

    monkeypatch.setattr(session_client, "send_envelope", fake)
    r = runner.invoke(app, ["click", "--image", str(template), "-c", "0.9"])
    assert r.exit_code == 0, r.output
    op, args = sent[0]
    assert op == "click_image"
    assert args["template_path"] == str(template.resolve())
    assert args["confidence"] == 0.9
    assert "clicked image at (12.0, 34.0)" in r.output
    assert "0.970" in r.output


def test_repl_click_image_dispatches(tmp_path: Path) -> None:
    template = tmp_path / "t.png"
    template.write_bytes(b"PNG")
    sent: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        sent.append((op, args))
        return {"x": 5.0, "y": 6.0, "confidence": 0.88}

    out = console.dispatch(f"click-image {template} 0.7", send)
    assert sent[0][0] == "click_image"
    assert sent[0][1]["template_path"] == str(template.resolve())
    assert sent[0][1]["confidence"] == 0.7
    assert "clicked image at (5.0, 6.0)" in out


def test_repl_help_lists_click_image() -> None:
    assert "click-image" in console.dispatch("help", lambda op, args: None)
