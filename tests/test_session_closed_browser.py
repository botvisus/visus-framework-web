"""A pessoa fechou o navegador da sessão na mão (o X da janela): o daemon continuava de pé
com o objeto do navegador morto, o ``status`` dizia ``running: true`` e TODO comando
seguinte falhava com "invalid session id" -- o ``_ensure()`` só abre outro navegador
quando não há nenhum. Agora o comando seguinte abre um navegador novo (mesmas opções,
mesmo perfil) e avisa; o ``status`` diz a verdade; o Chrome da pessoa só é solto."""

from __future__ import annotations

from typing import Any

import pytest

from visus.web.cli import session_server


class InvalidSessionIdException(Exception):  # o nome que o Selenium usa
    pass


class _Driver:
    def __init__(self) -> None:
        self.closed = False

    @property
    def window_handles(self) -> list[str]:
        if self.closed:
            raise InvalidSessionIdException("Message: invalid session id")
        return ["w1"]


class _Delegate:
    def __init__(self, driver: _Driver) -> None:
        self._driver = driver


class _Page:
    def __init__(self, driver: _Driver) -> None:
        self._delegate = _Delegate(driver)
        self._defaults: Any = None
        self.url = "about:blank"
        self.visited: list[str] = []

    def goto(self, url: str, **_: Any) -> None:
        if self._delegate._driver.closed:
            raise InvalidSessionIdException("Message: invalid session id")
        self.visited.append(url)
        self.url = url

    def title(self) -> str:
        return "t"


class _Browser:
    def __init__(self, log: list[str]) -> None:
        self.driver = _Driver()
        self.log = log
        self.page: _Page | None = None

    def new_page(self) -> _Page:
        self.page = _Page(self.driver)
        return self.page

    def close(self) -> None:
        self.log.append("close")

    def detach(self) -> None:
        self.log.append("detach")


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch) -> list[_Browser]:
    browsers: list[_Browser] = []
    log: list[str] = []

    def fake_launch(engine: Any, **kwargs: Any) -> _Browser:
        browser = _Browser(log)
        browser.kwargs = kwargs  # type: ignore[attr-defined]
        browsers.append(browser)
        return browser

    monkeypatch.setattr(session_server, "launch", fake_launch)
    # a página ativa sem a troca de abas do Selenium: a página do navegador de agora
    monkeypatch.setattr(
        session_server.SessionHandler, "_active_page", lambda self: (self._ensure(), self._page)[1]
    )
    return browsers


def test_the_next_command_reopens_a_browser_the_person_closed(launched: list[_Browser]) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=False, user_data_dir="C:/perfil-do-agente"
    )
    h._ensure()
    assert h.handle("status", {})["result"]["running"] is True

    launched[0].driver.closed = True  # a pessoa fechou a janela
    status = h.handle("status", {})["result"]
    assert status["running"] is False, "o status diz a verdade"
    assert len(launched) == 1, "o status só lê: não abre outro navegador"

    resp = h.handle("goto", {"url": "https://exemplo.com"})
    assert resp["ok"] is True, resp
    assert "had been closed" in resp["note"]
    assert len(launched) == 2, "um navegador novo"
    assert launched[1].kwargs["user_data_dir"] == "C:/perfil-do-agente", "o mesmo perfil"
    assert launched[1].page is not None and launched[1].page.visited == ["https://exemplo.com"]
    assert launched[0].log == ["close"], "o que sobrou do morto (o chromedriver) é fechado"
    assert h.handle("status", {})["result"]["running"] is True


def test_a_live_browser_is_never_reopened(launched: list[_Browser]) -> None:
    h = session_server.SessionHandler(engine="chrome", headless=False)
    h._ensure()
    resp = h.handle("goto", {"url": "https://a.com"})
    assert resp["ok"] is True and "note" not in resp
    assert len(launched) == 1


def test_any_other_error_does_not_reopen(launched: list[_Browser]) -> None:
    h = session_server.SessionHandler(engine="chrome", headless=False)
    h._ensure()

    class _Flaky(_Driver):
        @property
        def window_handles(self) -> list[str]:
            raise RuntimeError("alguma outra coisa")

    page = launched[0].page
    assert page is not None
    page._delegate._driver = _Flaky()
    assert h._browser_gone() is False, "só os sinais de navegador fechado contam"


def test_the_persons_chrome_is_released_never_closed(launched: list[_Browser]) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=False, debugger_address="127.0.0.1:9222"
    )
    h._ensure()
    launched[0].driver.closed = True
    resp = h.handle("goto", {"url": "https://a.com"})
    assert launched[0].log == ["detach"], "nunca fechar o Chrome da pessoa"
    assert len(launched) == 2 and launched[1].kwargs["debugger_address"] == "127.0.0.1:9222"
    assert resp["ok"] is True


def test_a_failure_after_reopening_says_the_browser_was_reopened(
    launched: list[_Browser], monkeypatch: pytest.MonkeyPatch
) -> None:
    h = session_server.SessionHandler(engine="chrome", headless=False)
    h._ensure()
    launched[0].driver.closed = True

    def boom(self: Any, args: dict[str, Any]) -> Any:
        raise ValueError("element not found: text=Aceitar")

    monkeypatch.setattr(session_server.SessionHandler, "_op_click", boom)
    resp = h.handle("click", {"selector": "text=Aceitar"})
    assert resp["ok"] is False
    assert resp["error"].startswith("the browser had been closed")
    assert "element not found" in resp["error"]
