"""`wait`: o agente espera o que vai aparecer em vez de dormir.

Depois de um clique que traz algo mais tarde (uma linha, um resultado), o `wait` volta
assim que aquilo aparece, com a linha de código do script e — num batch — a lista nova
da página, já com o que apareceu (sem um list-fields a mais).
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from visus.web.cli.codegen import generate_line
from visus.web.cli.main import app

runner = CliRunner()


def test_linha_de_codigo_do_wait() -> None:
    target = {"expr": "page.locator('#row2')"}
    assert generate_line({"action": "wait_for", "target": target, "value": "visible"}) == (
        "page.locator('#row2').wait_for(state='visible')"
    )
    assert generate_line({"action": "wait_for", "target": target, "value": "hidden"}) == (
        "page.locator('#row2').wait_for(state='hidden')"
    )


@pytest.mark.browser
def test_wait_pelo_texto_traz_a_lista_nova(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/delayed.html"])
    r = runner.invoke(
        app, ["batch", json.dumps([["click", "#add"], ["wait", "--text", "Row 2 was added"]])]
    )
    assert r.exit_code == 0, r.output
    assert ".wait_for(state='visible')" in r.output, "o script espera o mesmo"
    assert "#row2" in r.output, "a lista do fim já tem o campo que apareceu"


@pytest.mark.browser
def test_wait_espera_o_tempo_de_uma_acao(live_session: list[str], base_url: str) -> None:
    """Sem --timeout, espera o quanto uma ação esperaria — não os 5 s fixos de antes."""
    runner.invoke(app, ["open", f"{base_url}/delayed.html"])
    runner.invoke(app, ["click", "#add"])
    r = runner.invoke(app, ["wait", "#row2"])
    assert r.exit_code == 0, r.output
    assert "page.locator('#row2').wait_for(state='visible')" in r.output
