"""Agir pelo número da última lista tem que acertar EXATAMENTE o elemento listado.

É o caminho principal de um agente (`click 4`, `fill 2 …`). Dois defeitos medidos no
backend Selenium: o número virava um localizador `role=button[name=…]`, que o
`querySelectorAll` recusa — todo botão falhava por número —, e um localizador por
papel+nome casa também cópias escondidas do mesmo elemento. O XPath que o próprio
`list-fields` calculou aponta para o elemento certo.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from visus.web.cli.main import app

runner = CliRunner()


def _index_of(name: str) -> int:
    fields = json.loads(runner.invoke(app, ["list-fields", "--json"]).output)
    return next(f["index"] for f in fields if f["name"] == name)


@pytest.mark.browser
def test_click_por_indice_em_botao(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/agent_page.html"])
    assert runner.invoke(app, ["fill", "0", "ada@empresa.com"]).exit_code == 0
    r = runner.invoke(app, ["click", str(_index_of("Entrar"))])
    assert r.exit_code == 0, r.output
    assert "Entrou como ada@empresa.com" in runner.invoke(app, ["text"]).output


@pytest.mark.browser
def test_click_por_indice_ignora_copia_escondida(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/hidden_duplicates.html"])
    r = runner.invoke(app, ["click", str(_index_of("Salvar"))])
    assert r.exit_code == 0, r.output
    assert "salvo pelo visível" in runner.invoke(app, ["text"]).output


@pytest.mark.browser
def test_click_por_indice_dentro_de_iframe(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/frames.html"])
    r = runner.invoke(app, ["click", str(_index_of("Inner Button"))])
    assert r.exit_code == 0, r.output
    res = runner.invoke(app, ["get-text", "--selector", "#res", "--frame", "#f1"])
    assert "clicked" in res.output, res.output


@pytest.mark.browser
def test_click_por_indice_em_shadow_dom(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/shadow_click.html"])
    r = runner.invoke(app, ["click", str(_index_of("Shadow Button"))])
    assert r.exit_code == 0, r.output
    assert "shadow clicked" in runner.invoke(app, ["text"]).output


@pytest.mark.browser
def test_indice_desconhecido_mensagem_clara(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/agent_page.html"])
    r = runner.invoke(app, ["click", "99"])
    assert r.exit_code == 1
    assert "run list_fields first" in r.output


# --- todo alvo que o elemento oferecer: número, #id, .classe, CSS, XPath, papel ---

_SELECTORS = [
    "#entrar",
    ".btn-primary",
    "button.btn",
    "form#login button[type=submit]",
    "css=#entrar",
    "xpath=//button[@id='entrar']",
    "//button[@id='entrar']",
    "/html/body/form/button",
    "(//button)[1]",
    'role=button[name="Entrar"]',
    "id=entrar",
    "class=btn btn-primary",
    "text=Entrar",
]


@pytest.mark.browser
@pytest.mark.parametrize("selector", _SELECTORS)
def test_click_por_qualquer_seletor(live_session: list[str], base_url: str, selector: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/agent_page.html"])
    assert runner.invoke(app, ["fill", "#email", "ada@empresa.com"]).exit_code == 0
    r = runner.invoke(app, ["click", selector])
    assert r.exit_code == 0, f"{selector}: {r.output}"
    assert "Entrou como ada@empresa.com" in runner.invoke(app, ["text"]).output, selector


def test_compact_mostra_o_id_quando_o_elemento_tem() -> None:
    from visus.web.cli.compact import format_compact

    out = format_compact(
        [{"index": 0, "kind": "button", "name": "Entrar", "locator": "#entrar", "xpath": "/html/body/form/button"}],
        title="T",
        url="u",
    )
    assert out.splitlines()[1] == "  0  button         Entrar #entrar"
