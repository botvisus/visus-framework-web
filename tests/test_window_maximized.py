"""A janela do navegador abre MAXIMIZADA (headless: 1920x1080): o agente vê a página
inteira, e o print dela mostra o calendário que uma janela pequena cortava."""

from __future__ import annotations

import pytest

from visus.web.backends import selenium_backend as sb


class _Driver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[int, ...]]] = []

    def maximize_window(self) -> None:
        self.calls.append(("maximize", ()))

    def set_window_size(self, w: int, h: int) -> None:
        self.calls.append(("size", (w, h)))


def test_com_janela_maximiza(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VISUS_WINDOW_MAXIMIZED", raising=False)
    d = _Driver()
    sb._size_window(d, headless=False)
    assert d.calls == [("maximize", ())]


def test_headless_ganha_1920x1080(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VISUS_WINDOW_MAXIMIZED", raising=False)
    d = _Driver()
    sb._size_window(d, headless=True)
    assert d.calls == [("size", (1920, 1080))]


def test_da_para_desligar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISUS_WINDOW_MAXIMIZED", "0")
    d = _Driver()
    sb._size_window(d, headless=False)
    assert d.calls == []


@pytest.mark.browser
def test_navegador_headless_de_verdade_fica_grande() -> None:
    from visus.web import launch

    with launch(headless=True) as browser:
        page = browser.new_page()
        size = page.evaluate("() => ({w: window.outerWidth, h: window.outerHeight})")
    assert size["w"] >= 1900, size  # type: ignore[index]
