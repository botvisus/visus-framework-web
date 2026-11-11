"""`pick-date`: escolher uma data (ou um intervalo) em qualquer campo de data.

Três caminhos, nesta ordem: o ``<input type=date>`` nativo, o campo que aceita
digitação (no formato que ele já mostra) e o calendário que só abre e clica — que um
agente não alcança por ``fill``/``click`` numerados: os dias não são "campos", há dois
meses lado a lado, setas ◂ ▸ e dias cinzas de outro mês que escolheriam a data errada.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from typer.testing import CliRunner

from visus.web.cli.main import app
from visus.web.ops import dates

runner = CliRunner()


# --- o formato do campo (sem navegador) --------------------------------------------


def test_formato_mes_dia_quando_o_dia_passa_de_12() -> None:
    fmt = dates.detect_format("10/23/2026")
    assert fmt is not None
    assert fmt.render(date(2026, 11, 2)) == "11/2/2026", "sem zero à esquerda, como o campo"


def test_formato_dia_mes_com_zero_e_lingua_pt() -> None:
    fmt = dates.detect_format("05/10/2026", lang="pt-BR")
    assert fmt is not None
    assert fmt.render(date(2026, 11, 2)) == "02/11/2026"


def test_formato_iso_e_pontos() -> None:
    iso = dates.detect_format("2026-10-23")
    assert iso is not None and iso.render(date(2026, 11, 2)) == "2026-11-02"
    dots = dates.detect_format("23.10.2026")
    assert dots is not None and dots.render(date(2026, 11, 2)) == "02.11.2026"


def test_intervalo_guarda_o_separador() -> None:
    fmt = dates.detect_format("10/23/2026 ~ 11/6/2026")
    assert fmt is not None and fmt.range_sep == " ~ "
    assert fmt.render(date(2026, 11, 2), date(2026, 11, 6)) == "11/2/2026 ~ 11/6/2026"


def test_le_as_datas_de_volta() -> None:
    fmt = dates.detect_format("10/23/2026 ~ 11/6/2026")
    assert fmt is not None
    assert fmt.parse_all("11/2/2026 ~ 11/6/2026") == [date(2026, 11, 2), date(2026, 11, 6)]


def test_data_iso_invalida_e_um_erro_claro() -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        dates.parse_iso("2/11/2026")


# --- no navegador -----------------------------------------------------------------


@pytest.fixture
def page(browser, base_url):  # type: ignore[no-untyped-def]
    p = browser.new_page()
    p.goto(f"{base_url}/datepicker.html")
    return p


@pytest.mark.browser
def test_input_date_nativo(page) -> None:  # type: ignore[no-untyped-def]
    msg = dates.pick_date(page, page.locator("#native"), date(2026, 11, 2))
    assert page.locator("#native").input_value() == "2026-11-02"
    assert "2026-11-02" in msg


@pytest.mark.browser
def test_campo_que_aceita_digitacao(page) -> None:  # type: ignore[no-untyped-def]
    dates.pick_date(page, page.locator("#typed"), date(2026, 11, 2))
    assert page.locator("#typed").input_value() == "11/2/2026"


@pytest.mark.browser
def test_calendario_de_intervalo_dois_meses(page) -> None:  # type: ignore[no-untyped-def]
    msg = dates.pick_date(page, page.locator("#range"), date(2026, 11, 2), date(2026, 11, 6))
    assert page.locator("#range").input_value() == "11/2/2026 ~ 11/6/2026"
    assert "11/2/2026 ~ 11/6/2026" in msg


@pytest.mark.browser
def test_calendario_navega_pelas_setas(page) -> None:  # type: ignore[no-untyped-def]
    # abre em outubro/novembro de 2026: janeiro de 2027 exige avançar dois meses
    dates.pick_date(page, page.locator("#range"), date(2027, 1, 4), date(2027, 1, 8))
    assert page.locator("#range").input_value() == "1/4/2027 ~ 1/8/2027"


@pytest.mark.browser
def test_calendario_volta_pelas_setas(page) -> None:  # type: ignore[no-untyped-def]
    dates.pick_date(page, page.locator("#range"), date(2026, 8, 3), date(2026, 8, 7))
    assert page.locator("#range").input_value() == "8/3/2026 ~ 8/7/2026"


@pytest.mark.browser
def test_nunca_clica_dia_cinza_de_outro_mes(page) -> None:  # type: ignore[no-untyped-def]
    # o "1" de novembro também aparece em cinza no fim de outubro: tem de ser o de novembro
    dates.pick_date(page, page.locator("#range"), date(2026, 11, 1), date(2026, 11, 2))
    assert page.locator("#range").input_value() == "11/1/2026 ~ 11/2/2026"


@pytest.mark.browser
def test_calendario_em_portugues_com_setas_sem_texto(page) -> None:  # type: ignore[no-untyped-def]
    dates.pick_date(page, page.locator("#pt"), date(2026, 11, 2))
    assert page.locator("#pt").input_value() == "02/11/2026"


@pytest.mark.browser
def test_intervalo_num_input_date_e_um_erro_claro(page) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(dates.DatePickError, match="two"):
        dates.pick_date(page, page.locator("#native"), date(2026, 11, 2), date(2026, 11, 6))


# --- pela CLI, como o agente usa ----------------------------------------------------


@pytest.mark.browser
def test_cli_pick_date_no_batch(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/datepicker.html"])
    r = runner.invoke(
        app,
        ["batch", json.dumps([["pick-date", "#range", "2026-11-02", "2026-11-06"]])],
    )
    assert r.exit_code == 0, r.output
    assert "11/2/2026 ~ 11/6/2026" in r.output
    assert "pick_date" in live_session
    value = runner.invoke(app, ["text"]).output
    assert "range:11/2/2026 ~ 11/6/2026" in value


@pytest.mark.browser
def test_cli_pick_date_por_numero(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/datepicker.html"])
    fields = json.loads(runner.invoke(app, ["list-fields", "--json"]).output)
    index = next(f["index"] for f in fields if f.get("locator") == "#pt")
    r = runner.invoke(app, ["pick-date", str(index), "2026-11-02"])
    assert r.exit_code == 0, r.output
    assert "02/11/2026" in r.output


@pytest.mark.browser
def test_pick_date_gera_a_linha_visus_web(live_session: list[str], base_url: str) -> None:
    runner.invoke(app, ["open", f"{base_url}/datepicker.html"])
    r = runner.invoke(app, ["pick-date", "#range", "2026-11-02", "2026-11-06"])
    assert r.exit_code == 0, r.output
    assert "page.locator('#range').pick_date('2026-11-02', '2026-11-06')" in r.output
    script = runner.invoke(app, ["session", "export-script"]).output
    assert ".pick_date('2026-11-02', '2026-11-06')" in script, "o script roda como está"


def test_pick_date_aceita_texto_iso() -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        dates.pick_date(None, None, "2/11/2026")


@pytest.mark.browser
def test_dois_calendarios_independentes_como_o_gmes(page) -> None:  # type: ignore[no-untyped-def]
    # esquerda = início (em outubro), direita = fim (em novembro), cada um com as suas
    # setas: o 2 vai no da esquerda (que avança SOZINHO para novembro), o 6 no da direita
    msg = dates.pick_date(page, page.locator("#gmes"), "2026-11-02", "2026-11-06")
    assert page.locator("#gmes").input_value() == "11/2/2026 ~ 11/6/2026"
    assert "(calendar)" in msg


@pytest.mark.browser
def test_inicio_depois_do_fim_move_o_fim_primeiro(page) -> None:  # type: ignore[no-untyped-def]
    # o fim atual é 6/11: no calendário do início o 10/11 está desligado (só pela cor)
    dates.pick_date(page, page.locator("#gmes"), "2026-11-10", "2026-11-20")
    assert page.locator("#gmes").input_value() == "11/10/2026 ~ 11/20/2026"


@pytest.mark.browser
def test_campo_que_aceita_digitar_nao_abre_o_calendario(page) -> None:  # type: ignore[no-untyped-def]
    assert "(typed)" in dates.pick_date(page, page.locator("#typed"), "2026-11-02")


@pytest.mark.browser
def test_locator_pick_date_na_api(page) -> None:  # type: ignore[no-untyped-def]
    page.locator("#gmes").pick_date("2026-11-02", "2026-11-06")
    assert page.locator("#gmes").input_value() == "11/2/2026 ~ 11/6/2026"


@pytest.mark.browser
def test_campo_bloqueado_que_so_abre_pelo_botao(page) -> None:  # type: ignore[no-untyped-def]
    """InputDate do Wijmo: o campo é readonly e clicar nele não abre o calendário — só o
    botão ▾ do componente. O pick_date tem de achar esse botão, navegar e clicar o dia."""
    msg = dates.pick_date(page, page.locator("#wijmo"), date(2026, 12, 9))
    assert page.locator("#wijmo").input_value() == "2026/12/09"
    assert "2026/12/09" in msg
