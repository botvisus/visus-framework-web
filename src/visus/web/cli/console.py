"""Interactive REPL attached to a persistent CLI session.

The per-line command parsing/dispatch is a **pure function**
(:func:`dispatch(line, send_callable) -> str`) so it is fully testable with a
fake ``send``. :func:`run_console` wires that to a real session (starting one if
none is running) and the stdin read loop.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from visus.web.cli import session_client

# A send callable: (op, args) -> result (the daemon's `result` payload).
SendFn = Callable[[str, dict[str, Any]], Any]

# An envelope send callable: (op, args) -> the daemon's full reply dict.
SendEnvFn = Callable[[str, dict[str, Any]], dict[str, Any]]

_HELP = """commands:
  list [full]          enumerate interactive fields (`full` adds CSS/XPATH)
  click N              click field N (or a previous list index)
  fill N text          fill field N with text
  check N              check field N
  uncheck N            uncheck field N
  select N value       select option `value` on field N
  press N key          press key on field N
  hover N              hover over field N
  dblclick N           double-click field N
  focus N              focus field N
  clear-input N        clear field N's value
  goto url             navigate to url
  back                 navigate back in history
  forward              navigate forward in history
  reload               reload the current page
  title                print the page title
  url                  print the current URL
  snapshot [sel]       list interactive elements (REF/role/name), optionally scoped
  find text            grep the snapshot, with 3 rows of context around each hit
  text N               print field N's text content
  attr name N          print field N's `name` attribute
  count N              count elements matching field N
  wait N [state]       wait until field N is visible/hidden
  expect N text...     assert field N contains text (PASSED/FAILED)
  cookies              list cookies for the context
  eval expr            evaluate a JS expression
  dialog [dismiss]     handle the next dialog (accept by default)
  screenshot [path]    save a screenshot (default screenshot.png)
  export-script [path] print (or save) this session as a runnable visus.web script
  clear                remove the field highlight overlay
  highlight-all        redraw the numbered field overlay for every field
  tabs                 list open tabs/windows (active marked *)
  tab N                switch to tab/window N (omit N = newest)
  tab-new [url]        open a new tab (optionally at url)
  tab-close [N]        close tab N (omit N = active)
  help                 show this help
  quit                 exit the console (the session stays alive)"""


def format_fields(
    fields: list[dict[str, Any]], *, width: int | None = None, full: bool = False
) -> str:
    """Render fields as a table: #, KIND, NAME, and the ready-to-paste VISUS call.

    The VISUS column is copy-paste-ready and *frame-aware* — for an element inside
    an iframe it is wrapped in ``frame_locator(...)`` so a click/fill actually
    reaches it (a bare css/xpath would not). ``full=True`` adds the CSS and XPATH
    columns; they are off by default because on a large page they triple the
    output an agent has to read for no gain over the VISUS column. An ASCII box is
    used so the table renders on any console encoding.
    """
    if not fields:
        return "(no fields found)"
    from rich import box
    from rich.console import Console
    from rich.table import Table

    table = Table(box=box.ASCII, header_style="bold", pad_edge=False)
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("KIND", no_wrap=True)
    table.add_column("NAME", overflow="fold")
    table.add_column("VISUS (copy-paste)", overflow="fold", style="green")
    if full:
        table.add_column("CSS", overflow="fold")
        table.add_column("XPATH", overflow="fold")
    for f in fields:
        name = str(f.get("name") or f.get("label") or f.get("placeholder") or "")
        row = [
            str(f.get("index", "")),
            str(f.get("kind", "")),
            name,
            str(f.get("code", "")),
        ]
        if full:
            row.extend([str(f.get("css", "")), str(f.get("xpath", ""))])
        table.add_row(*row)
    # Console() auto-detects the real terminal width (wide tables use the full
    # screen) and colour (TTY only); capture() preserves both. On a narrow pipe
    # rich folds long cells. `width` lets tests pin a deterministic size.
    console = Console(width=width) if width else Console()
    with console.capture() as cap:
        console.print(table)
    return cap.get().rstrip("\n")


def render_value(result: Any) -> str:
    """Render a ``{value, present}`` daemon payload, keeping ``None`` distinct from ``""``.

    An agent that reads a blank line cannot tell "this attribute does not exist"
    from "this attribute is the empty string", and the two lead to opposite next
    actions. Anything that is not such a payload passes straight through.
    """
    if not isinstance(result, dict) or "present" not in result:
        return str(result)
    if not result.get("present"):
        return "(null)"
    value = "" if result.get("value") is None else str(result["value"])
    return value if value != "" else "(empty)"


def _footer(env: dict[str, Any]) -> str:
    """The ### Code / ### Page sections for one envelope, ready to append.

    Returns "" when the envelope carries neither, otherwise a string that STARTS
    with a newline so ``result + _footer(env)`` leaves a blank line between the
    value and the first section — the same shape ``output.emit_envelope`` prints.
    """
    parts: list[str] = []
    code = env.get("code")
    if code:
        parts.extend(["", "### Code", str(code)])
    page = env.get("page") or {}
    if page:
        parts.extend(["", "### Page", f"- URL: {page.get('url', '')}",
                      f"- Title: {page.get('title', '')}"])
        snap = env.get("snapshot")
        if snap:
            parts.append(f"- Snapshot: {snap}")
        if page.get("fields_stale"):
            parts.append("- Fields: stale — run `list` again before using an index")
    if not parts:
        return ""
    return "\n" + "\n".join(parts)


def dispatch(line: str, send: SendFn, send_env: SendEnvFn | None = None) -> str:
    """Parse one REPL line, run it via *send*, and return printable output.

    Pure aside from the injected callables — the unit of testing. ``send_env``
    returns the full daemon envelope so a mutating command can print the same
    ``### Code`` / ``### Page`` footer the non-interactive CLI prints; when it is
    omitted the REPL falls back to the bare result.
    """
    line = line.strip()
    if not line:
        return ""
    parts = line.split()
    cmd = parts[0].lower()
    rest = parts[1:]

    def _idx(token: str) -> dict[str, Any]:
        return {"index": int(token)}

    def _act(op: str, args: dict[str, Any], fmt: Callable[[Any], str] = str) -> str:
        """Run a mutating op: render its result with *fmt*, then the ### footer.

        *fmt* keeps each command's existing human sentence ("navigated to …")
        while the footer is added uniformly — exactly how ``emit_envelope(env,
        table=…)`` works on the non-interactive side.
        """
        if send_env is None:
            return fmt(send(op, args))
        env = send_env(op, args)
        return fmt(env.get("result")) + _footer(env)

    def _tab_line(r: Any) -> str:
        return f"switched to tab {r['active']}: {str(r.get('title', ''))!r}"

    def _tab_new_line(r: Any) -> str:
        return f"opened tab {r['index']}: {str(r.get('title', ''))!r}"

    def _tab_close_line(r: Any) -> str:
        # PLAN 3 Task 7 (B4) — two honest branches, not one lie. Reproduced
        # here so this rewrite of `dispatch` cannot silently revert it.
        if r.get("remaining", 0) == 0:
            if r.get("session_stopped"):
                return "closed the last tab — session stopped"
            return "closed the last tab — the browser is closed"
        return f"closed tab {r['closed']} ({r['remaining']} remaining)"

    try:
        if cmd in ("help", "?"):
            return _HELP
        if cmd in ("quit", "exit", "q"):
            return "__QUIT__"
        if cmd in ("list", "ls"):
            want_full = bool(rest and rest[0].lower() == "full")
            result = send("list_fields", {"highlight": False})
            return format_fields(result.get("fields", []), full=want_full)
        if cmd == "click":
            return _act("click", _idx(rest[0]))
        if cmd == "fill":
            return _act("fill", {**_idx(rest[0]), "text": " ".join(rest[1:])})
        if cmd == "check":
            return _act("check", _idx(rest[0]))
        if cmd == "uncheck":
            return _act("uncheck", _idx(rest[0]))
        if cmd == "select":
            return _act("select", {**_idx(rest[0]), "value": " ".join(rest[1:])})
        if cmd == "press":
            return _act("press", {**_idx(rest[0]), "key": " ".join(rest[1:])})
        if cmd == "hover":
            return _act("hover", _idx(rest[0]))
        if cmd == "dblclick":
            return _act("dblclick", _idx(rest[0]))
        if cmd == "focus":
            return _act("focus", _idx(rest[0]))
        if cmd == "clear-input":
            return _act("clear_input", _idx(rest[0]))
        if cmd == "goto":
            return _act("goto", {"url": rest[0]}, lambda r: f"navigated to {r}")
        if cmd == "back":
            return _act("back", {}, lambda r: f"went back to {r}")
        if cmd == "forward":
            return _act("forward", {}, lambda r: f"went forward to {r}")
        if cmd == "reload":
            return _act("reload", {}, lambda r: f"reloaded {r}")
        if cmd == "title":
            return str(send("title", {}))
        if cmd == "url":
            return str(send("url", {}))
        if cmd == "snapshot":
            snap_args: dict[str, Any] = {
                "selector": rest[0] if rest else None,
                "depth": None,
                "refs": True,
            }
            elements = send("snapshot", snap_args).get("elements", [])
            if not elements:
                return "(no elements)"
            return "\n".join(
                f"{('-' if e.get('ref') is None else str(e['ref'])):>4}  "
                f"{str(e.get('role', '')):<16} {e.get('name', '')}"
                for e in elements
            )
        if cmd == "find":
            result = send(
                "find",
                {
                    "query": " ".join(rest),
                    "regex": False,
                    "context": 3,
                    "selector": None,
                    "depth": None,
                },
            )
            rows = result.get("rows", [])
            if not rows:
                return f"no match for {result.get('query', '')!r} in {result.get('total', 0)} rows"
            lines = [
                f"{result.get('matched', 0)} of {result.get('total', 0)} rows "
                f"match {result.get('query', '')!r}"
            ]
            for r in rows:
                ref = "-" if r.get("ref") is None else str(r["ref"])
                lines.append(
                    f"{'>' if r.get('match') else ' '} {ref:>4}  "
                    f"{str(r.get('role', '')):<12} {r.get('name', '')}"
                )
            return "\n".join(lines)
        if cmd in ("text", "get-text"):
            return render_value(send("get_text", _idx(rest[0])))
        if cmd in ("attr", "get-attribute"):
            return render_value(
                send("get_attribute", {**_idx(rest[1]), "attr_name": rest[0]})
            )
        if cmd == "count":
            return str(send("count", _idx(rest[0])))
        if cmd == "wait":
            args: dict[str, Any] = _idx(rest[0])
            if len(rest) > 1:
                args["state"] = rest[1]
            return str(send("wait", args))
        if cmd in ("expect", "expect-text"):
            return str(
                send("expect_text", {**_idx(rest[0]), "expected_text": " ".join(rest[1:])})
            )
        if cmd == "cookies":
            items = send("cookies", {}).get("cookies", [])
            if not items:
                return "(no cookies)"
            return "\n".join(
                f"{c.get('name', '')}={c.get('value', '')}  ({c.get('domain', '')})"
                for c in items
            )
        if cmd == "eval":
            return _act(
                "eval",
                {"expression": " ".join(rest)},
                lambda r: str((r or {}).get("result")),
            )
        if cmd == "dialog":
            accept = not (rest and rest[0].lower() in ("dismiss", "cancel", "no"))
            return _act("dialog", {"accept": accept, "prompt_text": None})
        if cmd == "screenshot":
            # PLAN 3 Task 13 (B9) — resolve against the CLIENT's cwd (not the
            # daemon's) so the PNG lands where the user is, same fix as
            # main.py's session-screenshot. Reproduced here so this rewrite of
            # `dispatch` cannot silently revert it.
            shot_args: dict[str, Any] = {"path": str(Path(rest[0]).resolve())} if rest else {}
            return f"saved {send('screenshot', shot_args)}"
        if cmd == "export-script":
            result = send("export_script", {})
            code = str(result.get("script", ""))
            if rest:
                dest = Path(rest[0]).resolve()
                dest.write_text(code, encoding="utf-8")
                return f"saved {dest} ({result.get('lines', 0)} action(s))"
            return code
        if cmd == "clear":
            return str(send("clear_highlights", {}))
        if cmd == "highlight-all":
            send("list_fields", {"highlight": True})
            return "overlay drawn"
        if cmd == "tabs":
            items = send("tabs", {}).get("tabs", [])
            if not items:
                return "(no tabs)"
            return "\n".join(
                ("* " if t.get("active") else "  ")
                + f"[{t['index']}] {str(t.get('title', ''))!r}  {t.get('url', '')}"
                for t in items
            )
        if cmd == "tab":
            return _act("tab", {"index": int(rest[0]) if rest else None}, _tab_line)
        if cmd == "tab-new":
            return _act("tab_new", {"url": rest[0] if rest else None}, _tab_new_line)
        if cmd == "tab-close":
            return _act("tab_close", {"index": int(rest[0]) if rest else None}, _tab_close_line)
        return f"unknown command {cmd!r} (try `help`)"
    except IndexError:
        return f"missing argument for `{cmd}` (try `help`)"
    except session_client.SessionError as exc:
        return f"error: {exc}"


def run_console(
    url: str | None = None,
    *,
    engine: str = "chrome",
    headless: bool = False,
    start_dir: Any = None,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> None:
    """Attach to a session (start one if none) and run the REPL until `quit`."""
    info = session_client.find_session(start_dir)
    if info is None:
        output_fn("starting a new session...")
        session_client.start_daemon(engine, headless, url, cwd=start_dir)
    elif url:
        session_client.send("goto", {"url": url}, start_dir=start_dir)

    def _send(op: str, args: dict[str, Any]) -> Any:
        return session_client.send(op, args, start_dir=start_dir)

    def _send_env(op: str, args: dict[str, Any]) -> dict[str, Any]:
        return session_client.send_envelope(op, args, start_dir=start_dir)

    output_fn("visus console — type `help` for commands, `quit` to exit.")
    while True:
        try:
            line = input_fn("visus> ")
        except (EOFError, KeyboardInterrupt):
            output_fn("")
            break
        out = dispatch(line, _send, _send_env)
        if out == "__QUIT__":
            break
        if out:
            output_fn(out)
