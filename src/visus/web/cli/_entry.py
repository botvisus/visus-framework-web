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


def cli_main() -> None:
    """Entry point for the ``visus`` console script."""
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
