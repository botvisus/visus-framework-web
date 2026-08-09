"""Renomear o binário na cópia instalada NÃO é drift.

O aviso existe para pegar uma skill VELHA — conteúdo que não corresponde mais à
ferramenta. Mas num ambiente onde `visus` já é de outro programa (o visus-desktop
declara o mesmo console script), quem instala a skill precisa reescrevê-la para o
nome que de fato funciona: `visus-web`. Sem esta normalização a cópia corrigida
conta como drift PARA SEMPRE — o box aparece em todo comando e manda rodar
`visus install --skills`, que sobrescreveria a correção com um texto que chama o
binário errado. O conselho pioraria a situação que ele diagnostica.

Medido no Visus Studio compilado: era exatamente isso que acontecia.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from visus.web.cli import skill_check


def _install(root: Path, body: str) -> Path:
    skill = root / ".claude" / "skills" / "visus-web"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(body, encoding="utf-8")
    return skill


_BUNDLED = "# visus-web\n\n```bash\nvisus session start https://x/\nvisus click \"#a\"\n```\n"


def test_a_renamed_binary_is_not_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(tmp_path, _BUNDLED.replace("visus ", "visus-web "))
    monkeypatch.setattr(skill_check, "read_skill", _reader(_BUNDLED))

    skill_check.check_installed_skills(tmp_path)

    assert capsys.readouterr().err == "", "avisou de drift por uma simples renomeação"


def test_stale_content_is_still_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A rede de segurança continua valendo: conteúdo diferente ainda avisa."""
    _install(tmp_path, "# visus-web\n\n```bash\nvisus comando-que-nao-existe-mais\n```\n")
    monkeypatch.setattr(skill_check, "read_skill", _reader(_BUNDLED))

    skill_check.check_installed_skills(tmp_path)

    assert "does not match the tool version" in capsys.readouterr().err


def _reader(bundled: str):
    """`read_skill` real para a cópia instalada, fixo para a embarcada."""
    real = skill_check.read_skill

    def reader(path: Path) -> str | None:
        if path.parent.name == "visus-web" and ".claude" not in str(path):
            return bundled
        if "skills" in str(path) and ".claude" not in str(path):
            return bundled
        return real(path)

    return reader


def test_normalisation_only_touches_the_command_token() -> None:
    """`visus-web` no meio de um nome (visus-web-mcp, visus.web) não é o comando."""
    normalised = skill_check.normalise_cli_name(
        "visus-web click x\nvisus-web-mcp roda\nfrom visus.web import launch\n"
    )
    assert normalised.startswith("visus click x")
    assert "visus-web-mcp roda" in normalised, normalised
    assert "from visus.web import launch" in normalised, normalised
