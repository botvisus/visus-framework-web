"""CDP ``Fetch`` request interception over a dedicated DevTools WebSocket.

Selenium's ``execute_cdp_cmd`` is a command channel: chromedriver returns one
result per call and never delivers events, and its performance log only carries
``Network.*``/``Page.*``. ``Fetch.requestPaused`` therefore cannot be observed
through it. Chrome has supported several concurrent DevTools clients per target
since M63, so this module opens its own connection to the tab's target, enables
``Fetch`` on it, and answers each pause — leaving chromedriver's own session
untouched.

Everything selenium- and protocol-shaped stays here. The public surface
(:class:`visus.web.api.route.RouteRule`, ``Page.route``) never sees it.
"""

from __future__ import annotations

import base64
import json
import threading
import urllib.request
from typing import Any

from selenium.webdriver.remote.webdriver import WebDriver

from visus.web import errors
from visus.web.api.route import RouteRule, cdp_url_pattern

_NO_CDP = (
    "request interception requires a Chromium engine (chrome/edge) driven locally — "
    "this session exposes no DevTools address. Firefox has no CDP Fetch domain: stub "
    "the API from the page instead with page.add_init_script(...), which runs before "
    "the app boots."
)


def devtools_ws_url(driver: WebDriver, handle: str) -> str:
    """The DevTools WebSocket URL for the tab behind *handle*.

    Chromedriver's window handles are ``CDwindow-<targetId>``, and the browser's
    ``/json/list`` endpoint keys page targets by that same id — so the right tab
    is addressed even when several are open.
    """
    capabilities: dict[str, Any] = dict(getattr(driver, "capabilities", None) or {})
    address = ""
    for key in ("goog:chromeOptions", "ms:edgeOptions"):
        options = capabilities.get(key)
        if isinstance(options, dict) and options.get("debuggerAddress"):
            address = str(options["debuggerAddress"])
            break
    if not address:
        raise errors.VisusWebError(_NO_CDP)

    try:
        with urllib.request.urlopen(f"http://{address}/json/list", timeout=10) as resp:
            targets: list[dict[str, Any]] = json.loads(resp.read().decode("utf-8"))
    except OSError as exc:
        raise errors.VisusWebError(
            f"could not reach the DevTools endpoint at {address}: {exc}"
        ) from exc

    target_id = handle.split("CDwindow-", 1)[-1]
    pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    for target in pages:
        if target.get("id") == target_id:
            return str(target["webSocketDebuggerUrl"])
    if pages:
        return str(pages[0]["webSocketDebuggerUrl"])
    raise errors.VisusWebError("no DevTools page target is available for this tab")


class FetchInterceptor:
    """Owns one DevTools connection and answers ``Fetch.requestPaused``.

    ``Fetch.enable`` pauses every matching request until somebody answers it, so
    a dead pump would hang the page. Two guarantees follow: any request that
    matches no rule is immediately continued, and the pump disables ``Fetch``
    on its way out however it exits.
    """

    def __init__(self, ws_url: str, *, timeout: float = 10.0) -> None:
        self._ws_url = ws_url
        self._timeout = timeout
        self._ws: Any = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._send_lock = threading.Lock()
        self._rules_lock = threading.Lock()
        self._rules: list[RouteRule] = []
        self._msg_id = 0

    # --- lifecycle -------------------------------------------------------
    def start(self) -> None:
        """Connect and enable ``Fetch``, then start the pump thread."""
        if self._thread is not None:
            return
        # Imported inside start() rather than at module scope: `websocket-client`
        # is a hard dependency, but nothing else in visus touches it, and every
        # `visus` invocation imports driver_delegate — which imports this module.
        import websocket

        try:
            # suppress_origin is REQUIRED, not a tweak. Since M111 Chrome rejects a
            # DevTools handshake whose Origin header is not allowlisted, and
            # websocket-client derives one from the ws:// URL — so the connection
            # comes back "403 Rejected an incoming WebSocket connection from the
            # http://localhost:<port> origin". Sending no Origin at all is accepted,
            # and it beats launching every browser with --remote-allow-origins=*,
            # which would open the DevTools port to any page the user visits.
            self._ws = websocket.create_connection(
                self._ws_url, timeout=self._timeout, suppress_origin=True
            )
        except Exception as exc:  # noqa: BLE001 — any transport failure is one error
            raise errors.VisusWebError(
                f"could not open a DevTools connection for request interception: {exc}"
            ) from exc
        self._await(self._send("Fetch.enable", {"patterns": self._patterns()}))
        self._ws.settimeout(0.5)
        self._stop.clear()
        self._thread = threading.Thread(target=self._pump, name="visus-route", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Disable ``Fetch``, close the socket, and join the pump."""
        self._stop.set()
        try:
            if self._ws is not None:
                self._send("Fetch.disable", {})
        except Exception:  # noqa: BLE001 — a dead socket is already disabled
            pass
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5.0)
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:  # noqa: BLE001
            pass
        self._ws = None

    def set_rules(self, rules: list[dict[str, object]]) -> None:
        """Replace the rule list and re-arm the CDP pause patterns."""
        with self._rules_lock:
            self._rules = [RouteRule.from_dict(r) for r in rules]
        if self._ws is not None:
            self._send("Fetch.enable", {"patterns": self._patterns()})

    # --- protocol --------------------------------------------------------
    def _patterns(self) -> list[dict[str, str]]:
        with self._rules_lock:
            return [{"urlPattern": cdp_url_pattern(r.pattern)} for r in self._rules]

    def _send(self, method: str, params: dict[str, Any] | None = None) -> int:
        with self._send_lock:
            self._msg_id += 1
            message_id = self._msg_id
            self._ws.send(
                json.dumps({"id": message_id, "method": method, "params": params or {}})
            )
            return message_id

    def _await(self, message_id: int) -> None:
        """Read until the reply to *message_id* arrives (startup only, pre-pump).

        Bounded by the connection's own timeout: a DevTools endpoint that answers
        nothing raises rather than blocking the caller forever.
        """
        while True:
            raw = self._ws.recv()
            if not raw:
                raise errors.VisusWebError("DevTools closed the connection during Fetch.enable")
            try:
                message: dict[str, Any] = json.loads(raw)
            except ValueError:
                continue
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise errors.VisusWebError(f"Fetch.enable failed: {message['error']}")
            return

    def _pump(self) -> None:
        import websocket

        try:
            while not self._stop.is_set():
                try:
                    raw = self._ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                except Exception:  # noqa: BLE001 — socket gone: leave the loop
                    break
                if not raw:
                    continue
                try:
                    message: dict[str, Any] = json.loads(raw)
                except ValueError:
                    continue
                if message.get("method") == "Fetch.requestPaused":
                    self._answer(dict(message.get("params") or {}))
        finally:
            # Never leave requests paused with nobody listening.
            try:
                if self._ws is not None and not self._stop.is_set():
                    self._send("Fetch.disable", {})
            except Exception:  # noqa: BLE001
                pass

    def _match(self, url: str) -> RouteRule | None:
        with self._rules_lock:
            for rule in self._rules:
                if rule.matches(url):
                    return rule
        return None

    def _answer(self, params: dict[str, Any]) -> None:
        request_id = params.get("requestId")
        if not request_id:
            return
        url = str((params.get("request") or {}).get("url", ""))
        rule = self._match(url)
        try:
            if rule is None:
                self._send("Fetch.continueRequest", {"requestId": request_id})
                return
            if rule.abort:
                self._send("Fetch.failRequest", {"requestId": request_id, "errorReason": "Failed"})
                return
            headers = [{"name": k, "value": v} for k, v in rule.headers.items()]
            if rule.content_type:
                headers.append({"name": "Content-Type", "value": rule.content_type})
            body = rule.body or ""
            self._send(
                "Fetch.fulfillRequest",
                {
                    "requestId": request_id,
                    "responseCode": int(rule.status or 200),
                    "responseHeaders": headers,
                    "body": base64.b64encode(body.encode("utf-8")).decode("ascii"),
                },
            )
        except Exception:  # noqa: BLE001 — a send failure means the socket is gone
            self._stop.set()
