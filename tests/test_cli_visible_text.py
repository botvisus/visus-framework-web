"""`text` imprime o texto VISÍVEL da página como texto (não um dicionário cru), e
`get-text --visible` lê só o que aparece — uma linha filtrada de tabela não entra."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from visus.web.cli.main import app

runner = CliRunner()


@pytest.mark.browser
def test_text_e_texto_visivel_e_simples(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/visible_text.html"])
    out = runner.invoke(app, ["text"]).output
    assert "Selenium with Python" in out
    assert not out.lstrip().startswith("{"), "texto, não um dict"
    assert "Java for Testers" not in out, "linha escondida não é texto visível"
    assert "NAO-E-TEXTO-DA-PAGINA" not in out, "código de <script> não é texto"


@pytest.mark.browser
def test_get_text_visible(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/visible_text.html"])
    visible = runner.invoke(app, ["get-text", "#t", "--visible"]).output
    assert "Selenium with Python" in visible and "Java for Testers" not in visible
    raw = runner.invoke(app, ["get-text", "#t"]).output
    assert "Java for Testers" in raw, "sem --visible continua o text content de antes"
