"""A página como um agente de IA a lê: uma linha por elemento acionável.

Cada linha leva o número (para agir: ``click 4``), o tipo e o nome, e só o que
diferencia um elemento do outro — rótulo, placeholder e valor quando dizem algo
além do nome, ``checked`` em caixas, ``disabled``. É a mesma forma do comando
``web`` do sandbox do ai-teammates, de onde veio: cada token a menos se paga em
toda ação de toda tarefa.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

EMPTY_PAGE = "Nothing on this page to act on."


def _describe(field: dict[str, Any]) -> str:
    name = field.get("name") or ""
    details = [
        f"{key}={field[key]!r}"
        for key in ("label", "placeholder", "value")
        if field.get(key) and field[key] != name
    ]
    if field.get("type") in ("checkbox", "radio"):
        details.append(f"checked={field.get('checked')}")
    if field.get("disabled"):
        details.append("disabled")
    # O tipo de um input diz o que vai nele: search, email, password, file…
    kind = str(field.get("kind") or "")
    if kind == "input" and field.get("type"):
        kind = f"input:{field['type']}"
    line = f"{field.get('index', '?'):>3}  {kind:<14} {name}"
    return " ".join([line.rstrip(), *details])


def format_compact(fields: list[dict[str, Any]], *, title: str, url: str) -> str:
    """``Page: título | url`` e uma linha por campo (ou o aviso de página vazia)."""
    lines = [f"Page: {title} | {url}"]
    lines += [_describe(f) for f in fields] if fields else [EMPTY_PAGE]
    return "\n".join(lines)


def settle(
    fetch: Callable[[], list[dict[str, Any]]], *, polls: int = 10, interval: float = 0.3
) -> list[dict[str, Any]]:
    """Lê os campos até duas leituras seguidas iguais (a página assentou), no máximo
    ``polls`` vezes. Sem ``eval``: a própria lista é o sinal, e o agente precisa dela
    de qualquer jeito.
    """
    previous = fetch()
    for _ in range(polls - 1):
        if interval:
            time.sleep(interval)
        current = fetch()
        if current == previous:
            return current
        previous = current
    return previous
