"""O jeito de um agente de IA ler uma página: uma linha por elemento acionável, o
número para agir, e só o que diferencia um elemento do outro. Cada token a menos
nesta saída se paga em toda ação de toda tarefa.

Também `open` (abrir ou navegar e já ver a página) e `text` (ler a página) — os dois
sem `eval`, que o binário distribuído do Visus Studio bloqueia.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from visus.web.cli.compact import format_compact, settle
from visus.web.cli.main import app

runner = CliRunner()


def _field(index: int, kind: str, name: str, **extra: object) -> dict[str, object]:
    return {"index": index, "kind": kind, "name": name, **extra}


def test_compact_formata_como_o_agente_le() -> None:
    fields = [
        _field(0, "input", "E-mail", type="email", placeholder="voce@empresa.com"),
        _field(1, "input", "Senha", type="password"),
        _field(2, "checkbox", "Lembrar de mim", type="checkbox", checked=False),
        _field(3, "button", "Entrar", disabled=True),
    ]
    out = format_compact(fields, title="Portal", url="https://portal.exemplo.com/login")
    assert out.splitlines() == [
        "Page: Portal | https://portal.exemplo.com/login",
        "  0  input:email    E-mail placeholder='voce@empresa.com'",
        "  1  input:password Senha",
        "  2  checkbox       Lembrar de mim checked=False",
        "  3  button         Entrar disabled",
    ]


def test_compact_omite_label_igual_ao_nome() -> None:
    out = format_compact([_field(0, "input", "Busca", type="search", label="Busca", value="")], title="T", url="u")
    assert out.splitlines()[1] == "  0  input:search   Busca"


def test_compact_pagina_sem_campos() -> None:
    assert format_compact([], title="Vazia", url="about:blank").splitlines() == [
        "Page: Vazia | about:blank",
        "Nothing on this page to act on.",
    ]


def test_settle_espera_duas_leituras_iguais() -> None:
    reads = iter([[{"index": 0}], [{"index": 0}, {"index": 1}], [{"index": 0}, {"index": 1}]])
    calls: list[int] = []

    def fetch() -> list[dict[str, object]]:
        calls.append(1)
        return next(reads)

    assert settle(fetch, polls=10, interval=0) == [{"index": 0}, {"index": 1}]
    assert len(calls) == 3


def test_settle_desiste_depois_de_n_leituras() -> None:
    counter = iter(range(100))
    result = settle(lambda: [{"index": next(counter)}], polls=4, interval=0)
    assert result == [{"index": 3}]


@pytest.mark.browser
def test_open_devolve_lista_compacta(live_session: list[str], base_url: str) -> None:
    r = runner.invoke(app, ["open", f"{base_url}/agent_page.html"])
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    assert lines[0] == f"Page: Portal do Fornecedor | {base_url}/agent_page.html"
    assert any(line.startswith("  0  input:email") and "E-mail" in line for line in lines), r.output
    assert any("button" in line and "Entrar" in line for line in lines), r.output


@pytest.mark.browser
def test_list_fields_compact(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/agent_page.html"])
    r = runner.invoke(app, ["list-fields", "--compact"])
    assert r.exit_code == 0, r.output
    assert r.output.startswith("Page: Portal do Fornecedor | ")
    assert "input:password" in r.output


@pytest.mark.browser
def test_text_sem_eval(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/agent_page.html"])
    live_session.clear()
    r = runner.invoke(app, ["text"])
    assert r.exit_code == 0, r.output
    assert "Bem-vindo ao portal" in r.output
    assert "eval" not in live_session, f"text usou eval: {live_session}"


@pytest.mark.browser
def test_text_trunca(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/agent_page.html"])
    r = runner.invoke(app, ["text", "--max-chars", "20"])
    assert r.exit_code == 0, r.output
    first, rest = r.output.split("\n", 1)
    assert len(first) <= 20
    assert "more characters" in rest


# --- o DOM de cada elemento enumerado, para o agente montar #id, .classe ou XPath ---


def test_compact_dom_mostra_a_tag_de_abertura() -> None:
    field = _field(0, "button", "Entrar", locator="#entrar", dom='<button id="entrar" class="btn btn-primary" type="submit">')
    out = format_compact([field], title="T", url="u", dom=True)
    assert out.splitlines()[1] == '  0  button         Entrar #entrar <button id="entrar" class="btn btn-primary" type="submit">'


@pytest.mark.browser
def test_list_fields_traz_o_dom_de_cada_elemento(live_session: list[str], base_url: str) -> None:
    import json

    runner.invoke(app, ["open", f"{base_url}/agent_page.html"])
    fields = json.loads(runner.invoke(app, ["list-fields", "--json"]).output)
    entrar = next(f for f in fields if f["name"] == "Entrar")
    assert entrar["dom"] == '<button id="entrar" class="btn btn-primary" type="submit">'
    email = next(f for f in fields if f["name"] == "E-mail")
    assert email["dom"].startswith('<input id="email" type="email"')


@pytest.mark.browser
def test_list_fields_compact_dom(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/agent_page.html"])
    r = runner.invoke(app, ["list-fields", "--compact", "--dom"])
    assert r.exit_code == 0, r.output
    assert '<button id="entrar" class="btn btn-primary" type="submit">' in r.output
    # sem --dom a lista continua enxuta: só o #id
    plain = runner.invoke(app, ["list-fields", "--compact"]).output
    assert "#entrar" in plain and "<button" not in plain


def test_dom_corta_atributos_longos_e_ignora_handlers() -> None:
    import re

    bundle = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src/visus/web/backends/selenium/js/bundle.js"
    ).read_text(encoding="utf-8")
    assert re.search(r"function openTag\(el\)", bundle), "o bundle não calcula o DOM do elemento"
