"""Captchas de token (reCAPTCHA, Turnstile, hCaptcha) resolvidos por um serviço.

Sem rede: o serviço é um ``post`` falso que responde como o CapSolver/2Captcha, e as
páginas de teste declaram o widget como um site real (a classe, a sitekey, o callback).
O que importa é provado de ponta a ponta: o captcha é achado, o pedido certo vai ao
serviço, o token cai no campo do widget e o callback da página é chamado.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli.main import app
from visus.web.ops import captcha
from visus.web.ops.captcha import CaptchaError, CaptchaInfo

runner = CliRunner()


class _Service:
    """O serviço de captcha de mentira: cria a tarefa, responde "processing" uma vez e
    depois entrega o token. Guarda tudo o que recebeu."""

    def __init__(self, token: str = "SOLVED-TOKEN", *, error: str | None = None) -> None:
        self.token = token
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._polls = 0

    def __call__(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((url, payload))
        if self.error:
            return {"errorId": 1, "errorCode": "ERROR_KEY", "errorDescription": self.error}
        if url.endswith("/createTask"):
            return {"errorId": 0, "taskId": "task-1"}
        if url.endswith("/getBalance"):
            return {"errorId": 0, "balance": 4.5}
        self._polls += 1
        if self._polls == 1:
            return {"errorId": 0, "status": "processing"}
        return {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": self.token}}

    @property
    def task(self) -> dict[str, Any]:
        return self.calls[0][1]["task"]


def _info(kind: str, **over: Any) -> CaptchaInfo:
    return CaptchaInfo(kind=kind, sitekey="KEY", url="https://site.test/login", **over)


# --- o pedido de cada serviço ----------------------------------------------------


@pytest.mark.parametrize(
    ("provider", "info", "expected"),
    [
        (
            "capsolver",
            _info("recaptcha_v2"),
            {"type": "ReCaptchaV2TaskProxyLess", "isInvisible": False},
        ),
        (
            "capsolver",
            _info("recaptcha_v2", enterprise=True),
            {"type": "ReCaptchaV2EnterpriseTaskProxyLess"},
        ),
        (
            "capsolver",
            _info("recaptcha_v3", action="login"),
            {"type": "ReCaptchaV3TaskProxyLess", "pageAction": "login"},
        ),
        (
            "capsolver",
            _info("turnstile", action="login", cdata="x"),
            {"type": "AntiTurnstileTaskProxyLess", "metadata": {"action": "login", "cdata": "x"}},
        ),
        (
            "2captcha",
            _info("recaptcha_v2", invisible=True),
            {"type": "RecaptchaV2TaskProxyless", "isInvisible": True},
        ),
        (
            "2captcha",
            _info("recaptcha_v3", enterprise=True),
            {"type": "RecaptchaV3TaskProxyless", "minScore": 0.7, "isEnterprise": True},
        ),
        (
            "2captcha",
            _info("turnstile", action="login"),
            {"type": "TurnstileTaskProxyless", "action": "login"},
        ),
        ("2captcha", _info("hcaptcha"), {"type": "HCaptchaTaskProxyless"}),
    ],
)
def test_cada_servico_recebe_a_tarefa_no_formato_dele(
    provider: str, info: CaptchaInfo, expected: dict[str, Any]
) -> None:
    task = captcha.task_for(provider, info)
    assert task["websiteURL"] == "https://site.test/login" and task["websiteKey"] == "KEY"
    assert {k: task[k] for k in expected} == expected


def test_capsolver_nao_faz_hcaptcha_e_diz_qual_usar() -> None:
    with pytest.raises(CaptchaError, match="2Captcha"):
        captcha.task_for("capsolver", _info("hcaptcha"))


def test_pede_e_espera_o_token() -> None:
    service = _Service()
    token = captcha.request_token(
        "capsolver", "MY-KEY", _info("recaptcha_v2"), post=service, sleep=lambda s: None
    )
    assert token == "SOLVED-TOKEN"
    urls = [url for url, _ in service.calls]
    assert urls[0] == "https://api.capsolver.com/createTask"
    assert urls[1:] == ["https://api.capsolver.com/getTaskResult"] * 2, "esperou o 'processing'"
    assert all(payload["clientKey"] == "MY-KEY" for _, payload in service.calls)


def test_erro_do_servico_vira_mensagem_clara() -> None:
    service = _Service(error="ERROR_KEY_DENIED_ACCESS")
    with pytest.raises(CaptchaError, match="CapSolver: ERROR_KEY_DENIED_ACCESS"):
        captcha.request_token(
            "capsolver", "bad", _info("recaptcha_v2"), post=service, sleep=lambda s: None
        )


def test_desiste_quando_o_servico_demora() -> None:
    now = [0.0]

    def slow(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        return (
            {"errorId": 0, "taskId": "t"}
            if url.endswith("/createTask")
            else {"status": "processing"}
        )

    def tick(seconds: float) -> None:
        now[0] += seconds

    with pytest.raises(CaptchaError, match="did not solve"):
        captcha.request_token(
            "2captcha",
            "k",
            _info("turnstile"),
            timeout=10,
            post=slow,
            sleep=tick,
            clock=lambda: now[0],
        )


def test_saldo_testa_a_chave() -> None:
    assert captcha.balance("2captcha", "k", post=_Service()) == 4.5


def test_servico_desconhecido(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISUS_CAPTCHA_PROVIDER", "nope")
    with pytest.raises(CaptchaError, match="capsolver or 2captcha"):
        captcha.balance(api_key="k", post=_Service())


# --- na página ------------------------------------------------------------------------


@pytest.fixture
def page(browser, base_url):  # type: ignore[no-untyped-def]
    return browser.new_page()


@pytest.mark.browser
def test_acha_o_recaptcha_v2_e_o_callback(page, base_url) -> None:  # type: ignore[no-untyped-def]
    page.goto(f"{base_url}/captcha.html")
    info = captcha.detect(page)
    assert info is not None
    assert (info.kind, info.sitekey, info.callback) == (
        "recaptcha_v2",
        "6Le-test-v2-sitekey",
        "onCaptcha",
    )
    assert info.url.endswith("/captcha.html")


@pytest.mark.browser
def test_resolve_o_v2_poe_o_token_e_chama_o_callback(page, base_url) -> None:  # type: ignore[no-untyped-def]
    page.goto(f"{base_url}/captcha.html")
    service = _Service("TOKEN-V2")
    done = captcha.solve(page, api_key="MY-KEY", post=service, sleep=lambda s: None)
    assert "solved the reCAPTCHA v2 with CapSolver" in done and "callback" in done
    assert service.task["websiteKey"] == "6Le-test-v2-sitekey"
    assert page.locator("#g-recaptcha-response").input_value() == "TOKEN-V2"
    assert page.locator("#status").text_content() == "verified:TOKEN-V2"


@pytest.mark.browser
def test_resolve_o_turnstile(page, base_url) -> None:  # type: ignore[no-untyped-def]
    page.goto(f"{base_url}/captcha_turnstile.html")
    service = _Service("TOKEN-CF")
    done = captcha.solve(page, provider="2captcha", api_key="k", post=service, sleep=lambda s: None)
    assert "Cloudflare Turnstile with 2Captcha" in done
    assert service.task == {
        "type": "TurnstileTaskProxyless",
        "websiteURL": page.url,
        "websiteKey": "0x4AAAAAAAtestSiteKey",
        "action": "login",
    }
    assert page.locator('[name="cf-turnstile-response"]').input_value() == "TOKEN-CF"
    assert page.locator("#status").text_content() == "turnstile:TOKEN-CF"


@pytest.mark.browser
def test_v3_o_execute_da_pagina_devolve_o_token(page, base_url) -> None:  # type: ignore[no-untyped-def]
    page.goto(f"{base_url}/captcha_v3.html")
    info = captcha.detect(page)
    assert info is not None and (info.kind, info.sitekey) == ("recaptcha_v3", "6Le-test-v3-sitekey")
    captcha.solve(page, api_key="k", post=_Service("TOKEN-V3"), sleep=lambda s: None)
    page.locator("#send").click()
    page.locator("text=sent:TOKEN-V3").wait_for()


@pytest.mark.browser
def test_sem_captcha_so_avisa(page, base_url) -> None:  # type: ignore[no-untyped-def]
    page.goto(f"{base_url}/datepicker.html")
    assert captcha.solve(page, api_key="k", post=_Service()) == "no captcha on this page"


@pytest.mark.browser
def test_sem_chave_explica_o_que_fazer(page, base_url, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("VISUS_CAPTCHA_KEY", raising=False)
    page.goto(f"{base_url}/captcha.html")
    with pytest.raises(CaptchaError, match="VISUS_CAPTCHA_KEY"):
        captcha.solve(page, post=_Service())


@pytest.mark.browser
def test_page_solve_captcha_sem_alvo(page, base_url) -> None:  # type: ignore[no-untyped-def]
    page.goto(f"{base_url}/captcha.html")
    from unittest import mock

    with mock.patch.object(captcha, "_post", _Service("API-TOKEN")):
        done = page.solve_captcha(api_key="k")
    assert "reCAPTCHA v2" in done
    assert page.locator("#status").text_content() == "verified:API-TOKEN"


@pytest.mark.browser
def test_cli_resolve_com_a_chave_do_ambiente_e_gera_a_linha(
    live_session: list[str], base_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VISUS_CAPTCHA_KEY", "SECRET-KEY-123")
    service = _Service("CLI-TOKEN")
    monkeypatch.setattr(captcha, "_post", service)
    runner.invoke(app, ["open", f"{base_url}/captcha.html"])
    r = runner.invoke(app, ["batch", json.dumps([["solve-captcha"]])])
    assert r.exit_code == 0, r.output
    assert "solved the reCAPTCHA v2 with CapSolver" in r.output
    assert "page.solve_captcha()" in r.output
    assert service.calls[0][1]["clientKey"] == "SECRET-KEY-123"
    script = runner.invoke(app, ["session", "export-script"]).output
    assert "page.solve_captcha()" in script
    assert "SECRET-KEY-123" not in r.output + script, "a chave nunca sai na saída nem no script"
