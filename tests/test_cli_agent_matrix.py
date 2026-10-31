"""A matriz que um agente de IA usa no dia a dia (W5, W6, W9 do spec da aba Agente
do Visus Studio): abas, diálogos, esperas, downloads e uma saída que um processo
pai consegue ler — UTF-8 e código de saída diferente de zero em toda falha.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from visus.web.cli.main import app

runner = CliRunner()


def _ok(*args: str) -> str:
    r = runner.invoke(app, list(args))
    assert r.exit_code == 0, f"{args}: {r.output}"
    return r.output


# --- W5: abas e diálogos -----------------------------------------------------


@pytest.mark.browser
def test_tabs_novo_trocar_fechar(live_session: list[str], base_url: str) -> None:
    _ok("open", f"{base_url}/agent_page.html")
    _ok("tab-new", f"{base_url}/forms.html")
    tabs = json.loads(_ok("tabs", "--json"))
    assert len(tabs["tabs"]) == 2
    _ok("tab", "0")
    assert "Portal do Fornecedor" in _ok("title")
    _ok("tab-close", "1")
    assert len(json.loads(_ok("tabs", "--json"))["tabs"]) == 1


@pytest.mark.browser
def test_dialog_aceita_e_dismiss(live_session: list[str], base_url: str) -> None:
    _ok("open", f"{base_url}/popups.html")
    _ok("click", "#alertbtn")
    assert "hi there" in _ok("dialog")
    _ok("click", "#confirmbtn")
    _ok("dialog", "--dismiss")
    assert _ok("get-text", "#cres").strip() == "no"


@pytest.mark.browser
def test_o_navegador_da_sessao_nao_fecha_dialogos_sozinho(base_url: str) -> None:
    """Com o padrão do driver ("dismiss and notify"), a leitura do estado da página
    que o `click` faz logo depois fechava o confirm que o próprio clique abrira, e o
    `dialog` seguinte esperava em vão (CI: "no dialog appeared within 5000 ms")."""
    from visus.web.cli import session_server

    h = session_server.SessionHandler(engine="chrome", headless=True, url="about:blank")
    try:
        assert h.handle("goto", {"url": f"{base_url}/popups.html"})["ok"]
        caps = h._driver().capabilities  # type: ignore[union-attr]
        assert caps.get("unhandledPromptBehavior") == "ignore", caps
    finally:
        h.close()


@pytest.mark.browser
def test_comando_com_dialogo_aberto_recusa_e_orienta(
    live_session: list[str], base_url: str
) -> None:
    """Qualquer leitura da página com um alert aberto fazia o ChromeDriver fechá-lo
    em silêncio: o agente nunca soube que houve um diálogo. Agora o comando recusa,
    diz o texto do diálogo e como tratá-lo — e o diálogo continua lá."""
    import time

    _ok("open", f"{base_url}/popups.html")
    _ok("click", "#alertbtn")
    time.sleep(0.3)  # o alert abre 50 ms depois do clique
    r = runner.invoke(app, ["text"])
    assert r.exit_code == 1
    assert "hi there" in r.output and "visus dialog" in r.output, r.output
    assert "hi there" in _ok("dialog")
    assert "Portal" not in _ok("title")  # a página volta a responder depois do diálogo


# --- W6: esperar e baixar ----------------------------------------------------


@pytest.mark.browser
def test_wait_text_timeout_sai_com_erro(live_session: list[str], base_url: str) -> None:
    _ok("open", f"{base_url}/agent_page.html")
    r = runner.invoke(app, ["wait", "--text", "Texto que nunca aparece", "--timeout", "800"])
    assert r.exit_code != 0
    assert "error" in r.output.lower()


@pytest.mark.browser
def test_download_imprime_o_caminho_e_copia(
    live_session: list[str], base_url: str, tmp_path: Path
) -> None:
    _ok("open", f"{base_url}/downloads.html")
    _ok("click", "#dl")
    out = _ok("wait-download", "--timeout", "15000")
    path = Path(out.strip().splitlines()[-1])
    assert path.name == "download.txt" and path.is_file(), out

    dest = tmp_path / "entregas"
    saved = Path(_ok("wait-download", "--last", "--save-to", str(dest)).strip().splitlines()[-1])
    assert saved == dest / "download.txt" and saved.is_file()
    listed = json.loads(_ok("downloads", "--json"))
    assert [f["name"] for f in listed["files"]] == ["download.txt"]


@pytest.mark.browser
def test_wait_download_sem_download_sai_com_erro(live_session: list[str], base_url: str) -> None:
    _ok("open", f"{base_url}/agent_page.html")
    r = runner.invoke(app, ["wait-download", "--timeout", "500"])
    assert r.exit_code == 1
    assert "no new download completed within 500 ms" in r.output, r.output


# --- W9: saída que um processo pai lê ----------------------------------------


def test_saida_utf8_mesmo_em_pipe(tmp_path: Path) -> None:
    """O agente lê a CLI por um pipe. No Windows, sem isto, o Python escreve no
    codepage local (cp1252/cp850) e "não" chega como lixo ao processo pai."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "from visus.web.cli._entry import cli_main; import sys; "
            "sys.argv=['visus','batch','[[\"batch\",\"[]\"]]']; cli_main()",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        env=env,
        timeout=120,
    )
    assert proc.returncode == 2
    assert "não" in proc.stderr.decode("utf-8"), proc.stderr
