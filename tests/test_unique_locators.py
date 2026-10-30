"""O seletor de cada campo da lista identifica SÓ aquele elemento: num grupo de radios
com o mesmo ``name``, com ids repetidos ou com a mesma classe, agir pelo número (e o
código gerado) atinge o elemento listado, não o primeiro que casa."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from visus.web.cli.main import app

runner = CliRunner()


@pytest.fixture
def page(browser, base_url):  # type: ignore[no-untyped-def]
    p = browser.new_page()
    p.goto(f"{base_url}/duplicates.html")
    return p


@pytest.mark.browser
def test_todo_seletor_da_lista_e_unico(page) -> None:  # type: ignore[no-untyped-def]
    for field in page.list_fields(highlight=False):
        assert page.locator(field.locator).count() == 1, (field.name, field.locator)


@pytest.mark.browser
def test_radio_do_grupo_leva_o_value(page) -> None:  # type: ignore[no-untyped-def]
    python = next(
        f for f in page.list_fields(highlight=False) if f.kind == "radio" and "Python" in f.name
    )
    assert '[value="Python"]' in python.locator, python.locator


@pytest.mark.browser
def test_cli_marca_o_radio_certo_pelo_numero(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/duplicates.html"])
    fields = json.loads(runner.invoke(app, ["list-fields", "--json"]).output)
    python = next(f for f in fields if f["kind"] == "radio" and "Python" in f["name"])
    r = runner.invoke(app, ["check", str(python["index"])])
    assert r.exit_code == 0, r.output
    assert "[value=" in r.output, "o código gerado aponta para ESTE radio"
    after = json.loads(runner.invoke(app, ["list-fields", "--json"]).output)
    checked = [f["name"] for f in after if f["kind"] == "radio" and f.get("checked")]
    assert checked and "Python" in checked[0], checked


@pytest.mark.browser
def test_cli_clica_o_segundo_id_repetido(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/duplicates.html"])
    fields = json.loads(runner.invoke(app, ["list-fields", "--json"]).output)
    second = next(f for f in fields if f["name"] == "Edit 2")
    r = runner.invoke(app, ["click", str(second["index"])])
    assert r.exit_code == 0, r.output
    assert "hit:row2" in runner.invoke(app, ["text"]).output
