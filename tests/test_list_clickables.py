"""`list-fields` também lista o que só um clique torna interativo — o item de menu de um
app React (um ``div`` com o cursor de mão), o dia de um calendário — como ``clickable``.

Sem isso um agente não vê o menu que acabou de abrir e cai em ``text=…`` que casa com
mais de um elemento, ou espera 30 s por um elemento que nunca fica clicável.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from visus.web.cli.main import app

runner = CliRunner()


@pytest.fixture
def page(browser, base_url):  # type: ignore[no-untyped-def]
    p = browser.new_page()
    p.goto(f"{base_url}/clickables.html")
    return p


def _names(fields, kind: str | None = None) -> list[str]:  # type: ignore[no-untyped-def]
    return [f.name for f in fields if kind is None or f.kind == kind]


@pytest.mark.browser
def test_a_api_python_continua_igual_por_padrao(page) -> None:  # type: ignore[no-untyped-def]
    fields = page.list_fields(highlight=False)
    assert not [f for f in fields if f.kind == "clickable"]
    assert "Real Button" in _names(fields)


@pytest.mark.browser
def test_clicaveis_entram_uma_vez_cada(page) -> None:  # type: ignore[no-untyped-def]
    fields = page.list_fields(highlight=False, clickables=True)
    clickable = _names(fields, "clickable")
    assert "Daily Production Plan" in clickable, "o item de menu React (só o cursor)"
    assert "Weekly Plan" in clickable, "o texto inteiro do item, uma entrada só"
    assert "Weekly" not in clickable and "Plan" not in clickable
    assert "Order Status" in clickable, "onclick"
    assert "Tab Stop" in clickable, "tabindex"
    assert "Hidden Item" not in clickable, "invisível não entra"
    assert not any("Real Button" in n for n in clickable), "o card que embrulha o botão não duplica"
    assert _names(fields).count("Real Button") == 1
    assert "Plain text, not clickable" not in _names(fields)
    assert len(clickable) == 4, clickable


@pytest.mark.browser
def test_cli_lista_e_clica_o_item_do_menu(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/clickables.html"])
    fields = json.loads(runner.invoke(app, ["list-fields", "--json"]).output)
    item = next(f for f in fields if f["name"] == "Daily Production Plan")
    assert item["kind"] == "clickable"
    compact = runner.invoke(app, ["list-fields", "--compact"]).output
    assert "clickable" in compact and "Daily Production Plan" in compact
    r = runner.invoke(app, ["click", str(item["index"])])
    assert r.exit_code == 0, r.output
    assert "picked:daily" in runner.invoke(app, ["text"]).output


@pytest.mark.browser
def test_cli_no_clickables_volta_a_lista_antiga(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/clickables.html"])
    fields = json.loads(runner.invoke(app, ["list-fields", "--json", "--no-clickables"]).output)
    assert not [f for f in fields if f["kind"] == "clickable"]
