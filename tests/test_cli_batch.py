"""`batch`: várias ações numa chamada só, para um agente preencher um formulário
inteiro em UM passo e ver o resultado (a página numerada) uma vez, no fim.

Substitui o `fill 0 … && fill 1 … && click 2` do sandbox do ai-teammates sem
precisar de shell — e sem shell não há onde esconder outro comando.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from visus.web.cli.main import app

runner = CliRunner()


def _batch(*actions: list[str]) -> list[str]:
    return ["batch", json.dumps(list(actions))]


@pytest.mark.browser
def test_batch_executa_em_ordem(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/agent_page.html"])
    r = runner.invoke(app, _batch(["fill", "0", "ada@empresa.com"], ["fill", "1", "segredo"], ["click", "3"]))
    assert r.exit_code == 0, r.output
    assert "Page: Portal do Fornecedor" in r.output
    text = runner.invoke(app, ["text"]).output
    assert "Entrou como ada@empresa.com" in text


@pytest.mark.browser
def test_batch_para_na_primeira_falha(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/agent_page.html"])
    r = runner.invoke(app, _batch(["fill", "0", "a@b.c"], ["click", "99"], ["fill", "1", "nao-deve"]))
    assert r.exit_code == 1, r.output
    assert "falhou na ação 2 (click)" in r.output
    # a lista da página vem mesmo na falha: é dela que o agente tira a próxima tentativa
    assert "Page: Portal do Fornecedor" in r.output
    fields = json.loads(runner.invoke(app, ["list-fields", "--json"]).output)
    senha = next(f for f in fields if f["index"] == 1)
    assert not senha.get("value"), "a 3ª ação rodou depois da falha"


@pytest.mark.browser
def test_batch_lista_a_pagina_uma_vez(live_session: list[str], base_url: str) -> None:
    r = runner.invoke(app, _batch(["open", f"{base_url}/agent_page.html"], ["fill", "0", "x@y.z"], ["check", "2"]))
    assert r.exit_code == 0, r.output
    assert r.output.count("Page: ") == 1, r.output


@pytest.mark.browser
def test_batch_so_de_leitura_nao_lista_a_pagina(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/agent_page.html"])
    r = runner.invoke(app, _batch(["title"], ["url"]))
    assert r.exit_code == 0, r.output
    assert "Page: " not in r.output
    assert "Portal do Fornecedor" in r.output


def test_batch_recusa_batch_aninhado() -> None:
    r = runner.invoke(app, _batch(["batch", "[]"]))
    assert r.exit_code == 2
    assert "batch dentro de batch" in r.output


def test_batch_json_invalido_exit_2() -> None:
    r = runner.invoke(app, ["batch", "isto não é json"])
    assert r.exit_code == 2
    assert "lista JSON" in r.output


def test_batch_formato_errado_exit_2() -> None:
    r = runner.invoke(app, ["batch", json.dumps([["click", 3]])])
    assert r.exit_code == 2
    assert "lista JSON" in r.output
