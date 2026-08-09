"""The op vocabulary shared by the CLI session daemon and the MCP server.

This package sits BELOW both frontends. It imports ``visus.web.api`` and the
standard library and nothing else — never ``typer``, never ``mcp`` — which is
what makes it importable from the CLI when the ``[mcp]`` extra is absent and
from the MCP server when the ``[cli]`` extra is absent. That constraint is the
reason ``make_locator`` used to exist twice (``session_server.py:59-63`` states
it verbatim); this package removes the duplication instead of the constraint.

Anything that needs ``visus.web.cli`` (the daemon transport) imports it lazily
inside a function, so the layering never runs backwards at import time.
"""
