"""E2E num site público feito para treinar automação: login e logout pela CLI, do
jeito que um agente faz — abrir, ler a página numerada, agir, conferir o texto.

https://practicetestautomation.com/practice-test-login/ (usuário `student`,
senha `Password123`, publicados na própria página). Depende de internet, então só
roda com VISUS_E2E_INTERNET=1:

    VISUS_E2E_INTERNET=1 uv run pytest tests/test_cli_e2e_practice_login.py -m internet --no-cov -n 0
"""

from __future__ import annotations

import json
import os

import pytest
from typer.testing import CliRunner

from visus.web.cli.main import app

pytestmark = [
    pytest.mark.browser,
    pytest.mark.internet,
    pytest.mark.skipif(os.environ.get("VISUS_E2E_INTERNET") != "1", reason="E2E na internet: VISUS_E2E_INTERNET=1"),
    pytest.mark.timeout(240),
]

LOGIN = "https://practicetestautomation.com/practice-test-login/"
runner = CliRunner()


def _ok(*args: str) -> str:
    r = runner.invoke(app, list(args))
    assert r.exit_code == 0, f"{args}: {r.output}"
    return r.output


def _batch(*actions: list[str]) -> str:
    return _ok("batch", json.dumps(list(actions)))


def _index_of(name: str) -> str:
    fields = json.loads(_ok("list-fields", "--json"))
    return str(next(f["index"] for f in fields if f["name"].strip().lower() == name.lower()))


def _logged_in_then_out(logout_target: str) -> None:
    assert "Logged In Successfully" in _ok("text")
    _ok("click", logout_target)
    page = _ok("list-fields", "--compact")
    assert "practice-test-login" in page, page


def test_login_e_logout_pelo_numero(live_session: list[str]) -> None:
    page = _ok("open", LOGIN)
    assert "Username" in page and "Password" in page and "Submit" in page, page
    _batch(["fill", _index_of("Username"), "student"], ["fill", _index_of("Password"), "Password123"], ["click", _index_of("Submit")])
    _logged_in_then_out(_index_of("Log out"))


def test_login_e_logout_por_id_e_texto(live_session: list[str]) -> None:
    _ok("open", LOGIN)
    _batch(["fill", "#username", "student"], ["fill", "#password", "Password123"], ["click", "#submit"])
    _logged_in_then_out("text=Log out")


def test_login_e_logout_por_xpath(live_session: list[str]) -> None:
    _ok("open", LOGIN)
    _batch(
        ["fill", "//input[@id='username']", "student"],
        ["fill", "xpath=//input[@name='password']", "Password123"],
        ["click", "//button[@id='submit']"],
    )
    _logged_in_then_out("//a[normalize-space()='Log out']")


def test_login_e_logout_por_classe(live_session: list[str]) -> None:
    _ok("open", LOGIN)
    _batch(["fill", "id=username", "student"], ["fill", "id=password", "Password123"], ["click", "button.btn"])
    _logged_in_then_out("class=wp-block-button__link")


def test_dom_dos_campos_traz_ids_e_classes(live_session: list[str]) -> None:
    _ok("open", LOGIN)
    page = _ok("list-fields", "--compact", "--dom")
    assert "#username" in page and "#password" in page and "#submit" in page, page
    assert '<input type="text" name="username" id="username"' in page or 'id="username"' in page, page


def test_senha_errada_mostra_o_erro(live_session: list[str]) -> None:
    _ok("open", LOGIN)
    _batch(["fill", "#username", "student"], ["fill", "#password", "errada"], ["click", "#submit"])
    assert "Your password is invalid!" in _ok("text")
