"""Reach a running `visus` session daemon from any frontend, in-process.

:class:`RemoteDispatcher` has the same signature and returns the same envelope as
``SessionHandler.handle`` — the only difference is which process owns the
browser. That is what lets the MCP server stop being a second, invisible browser
(``mcp/session.py`` launches headless with manual tab-follow while
``session_server.py`` launches headed with auto-follow, and nothing tells the
model they are different windows) and become a frontend over the very session the
shell is driving.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import ModuleType


class NoSessionError(RuntimeError):
    """Raised when no live `visus` session daemon can be found."""


class RemoteDispatcher:
    """The daemon's op vocabulary as a plain object.

    *start_dir* is where the search for ``.visus/sessions/<name>.json`` begins;
    the search walks upward, git-style. ``None`` means the process's current
    working directory.
    """

    def __init__(self, *, start_dir: str | Path | None = None) -> None:
        self._start_dir = start_dir

    @staticmethod
    def _client() -> ModuleType:
        """The daemon transport, imported lazily.

        ``visus.web.ops`` must not depend on ``visus.web.cli`` at import time —
        the layering runs the other way. ``session_client`` imports nothing but
        the standard library, so this pulls in no optional dependency and works
        with neither the ``[cli]`` nor the ``[mcp]`` extra installed.
        """
        from visus.web.cli import session_client

        return session_client

    def session(self) -> dict[str, Any] | None:
        """The live session dict, or ``None``. Cleans up a stale session file."""
        info: dict[str, Any] | None = self._client().find_session(self._start_dir)
        return info

    def is_live(self) -> bool:
        """True when a daemon is running and its socket accepts."""
        return self.session() is not None

    def handle(self, op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Dispatch one op. Returns ``{ok:True,result:...}`` or ``{ok:False,error:str}``.

        Mirrors ``SessionHandler.handle`` exactly, including the rule that it
        never raises for a daemon-side failure: a frontend that switches between
        local and remote must not also switch error styles.
        """
        client = self._client()
        try:
            env: dict[str, Any] = client.send_envelope(op, args or {}, start_dir=self._start_dir)
        except client.SessionError as exc:
            return {"ok": False, "error": str(exc)}
        return env

    def result(self, op: str, args: dict[str, Any] | None = None) -> Any:
        """The op's ``result`` payload, raising on failure.

        Use this where a caller wants an exception (an MCP tool body); use
        :meth:`handle` where it wants the whole envelope (page state, generated
        code).
        """
        if self.session() is None:
            raise NoSessionError(
                "no live visus session — run `visus session start` in the project directory"
            )
        env = self.handle(op, args)
        if not env.get("ok"):
            raise RuntimeError(str(env.get("error", "unknown error")))
        return env.get("result")
