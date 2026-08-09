"""`visus-web` existe porque `visus` é ambíguo.

visus-web e visus-desktop declaram o MESMO console script `visus`: num ambiente
com os dois (o Visus Studio é um), quem instalou por último fica com o arquivo.
Um agente que leu a skill do web e rodou `visus click "#submit"` mandaria um
comando de browser para o CLI de desktop — que responde, e erra, em silêncio.

O alias é o nome que só pode significar web, em qualquer instalação. A skill
publicada continua ensinando `visus`, que é o certo para quem instalou só o
visus-web; quem monta um ambiente misto reescreve para o alias (é o que o
instalador do Studio faz).
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - 3.10
    import tomli as tomllib

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _scripts() -> dict[str, str]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    scripts: dict[str, str] = data["project"]["scripts"]
    return scripts


def test_the_unambiguous_alias_exists() -> None:
    assert "visus-web" in _scripts(), "sem o alias, um ambiente misto não tem como chamar o web"


def test_both_names_run_the_same_entry_point() -> None:
    """Um alias que divergisse do original seria uma segunda CLI, não um apelido."""
    scripts = _scripts()
    assert scripts["visus-web"] == scripts["visus"]


def test_the_alias_target_is_importable_and_callable() -> None:
    """O nome no pyproject tem de existir de fato — um typo só aparece no install."""
    module_name, _, attr = _scripts()["visus-web"].partition(":")
    module = __import__(module_name, fromlist=[attr])
    assert callable(getattr(module, attr))
