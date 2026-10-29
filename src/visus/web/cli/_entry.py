"""Console-script entry points that guard the optional extras.

``pyproject.toml`` declares ``visus`` and ``visus-web-mcp`` unconditionally, but
``typer`` lives in the ``[cli]`` extra and ``mcp`` in ``[mcp]``. Pointing the
scripts straight at ``visus.web.cli.main:app`` / ``visus.web.mcp.server:main``
means a plain ``pip install visus-web`` produces commands that die with a raw
``ModuleNotFoundError`` traceback — while ``README.md:154-158`` tells the user to
run ``visus doctor`` right after that install. These wrappers turn that into one
actionable line on stderr and exit code 2.
"""

from __future__ import annotations

import sys

_MISSING_CLI = (
    'The `visus` CLI needs the [cli] extra:  pip install "visus-web[cli]"\n'
)
_MISSING_MCP = (
    'The visus-web MCP server needs the [mcp] extra:  pip install "visus-web[mcp]"\n'
)


def _utf8_streams() -> None:
    """Saída sempre em UTF-8. Lida por um processo pai (um agente de IA, um script),
    a CLI escreve num pipe — e no Windows o Python usa o codepage local (cp1252/
    cp850) para pipes, então "não" chegava como lixo do outro lado."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # stream já fechado ou não reconfigurável
                pass


def cli_main() -> None:
    """Entry point for the ``visus`` console script."""
    _utf8_streams()
    try:
        import typer  # noqa: F401
    except ImportError as exc:  # ModuleNotFoundError is a subclass
        sys.stderr.write(_MISSING_CLI)
        raise SystemExit(2) from exc

    from visus.web.cli.main import app
    from visus.web.cli.skills import normalize_skills_argv

    app(args=normalize_skills_argv(sys.argv[1:]), prog_name="visus")


def mcp_main() -> None:
    """Entry point for the ``visus-web-mcp`` console script (and ``visus mcp``)."""
    try:
        import mcp  # noqa: F401
    except ImportError as exc:  # ModuleNotFoundError is a subclass
        sys.stderr.write(_MISSING_MCP)
        raise SystemExit(2) from exc

    from visus.web.mcp import server

    server.main()
