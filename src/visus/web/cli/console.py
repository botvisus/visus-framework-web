"""Interactive REPL attached to a persistent CLI session.

The per-line command parsing/dispatch is a **pure function**
(:func:`dispatch(line, send_callable) -> str`) so it is fully testable with a
fake ``send``. :func:`run_console` wires that to a real session (starting one if
none is running) and the stdin read loop.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from visus.web.cli import session_client

# A send callable: (op, args) -> result (the daemon's `result` payload).
SendFn = Callable[[str, dict[str, Any]], Any]

# An envelope send callable: (op, args) -> the daemon's full reply dict.
SendEnvFn = Callable[[str, dict[str, Any]], dict[str, Any]]

_HELP = """targets: a field index (`3`), a bare selector (`#submit`, `//button[1]`),
         or flags (`--selector #go`, `--role button --name Save`, `--text Save [--exact]`).

commands:
  list [full] [--boxes] enumerate interactive fields (`full` adds CSS/XPATH)
  click TARGET [btn]   click the target (btn: left|middle|right)
  fill TARGET text     fill the target with text
  check TARGET         check the target
  uncheck TARGET       uncheck the target
  select TARGET value  select option `value` on the target
  press [TARGET] key   press a key on the target, or on the page with no target
  type text...         type into the focused element (real key events)
  keydown key          hold a key down (e.g. Shift)
  keyup key            release a held key
  mousemove x y        move the pointer to viewport coordinates
  mousedown [btn]      hold a mouse button down at the pointer
  mouseup [btn]        release a held mouse button
  mousewheel dx dy     scroll by a wheel delta at the pointer
  hover TARGET         hover over the target
  dblclick TARGET [btn] double-click the target (btn: left|middle|right)
  focus TARGET         focus the target
  clear-input TARGET   clear the target's value
  upload TARGET p...   set file(s) on a file input (paths resolved locally)
  drag TARGET TARGET   drag the first target onto the second
  goto url             navigate to url
  back                 navigate back in history
  forward              navigate forward in history
  reload               reload the current page
  title                print the page title
  url                  print the current URL
  resize w h           resize the window so the viewport is w×h
  snapshot [sel] [--boxes] interactive elements (REF/role/name), optionally scoped
  find text            grep the snapshot, with 3 rows of context around each hit
  text TARGET          print the target's text content
  attr name TARGET     print the target's `name` attribute
  count TARGET         count elements matching the target
  wait TARGET [state]  wait until the target is visible/hidden
  expect TARGET text   assert the target contains text (PASSED/FAILED)
  cookies              list cookies for the context
  add-cookies json     add cookies from a JSON list
  clear-cookies        clear every cookie in the context
  state-save [file]    save cookies + web storage (default storage-state.json)
  state-load file      restore a snapshot (navigate to the origin first)
  eval expr            evaluate a JS expression
  eval-on TGT expr     evaluate `(el, arg) => …` on one element
  logs [LEVEL]         browser console messages (SEVERE/WARNING/INFO)
  requests [FILTER]    captured network responses (substring URL filter)
  request N            one captured response, with its body
  dialog [dismiss]     handle the next dialog (accept by default)
  screenshot [path]    save a screenshot (default screenshot.png)
  export-script [path] print (or save) this session as a runnable visus.web script
  read-text TARGET     OCR the target and print the text
  solve-captcha TARGET OCR-solve a text CAPTCHA in the target
  find-image f [T] [c] find template image `f` (optional target, confidence)
  clear                remove the field highlight overlay
  highlight TGT [style] box one element (`highlight hide` removes it)
  highlight-all        redraw the numbered field overlay for every field
  tabs                 list open tabs/windows (active marked *)
  tab N                switch to tab/window N (omit N = newest)
  tab-new [url]        open a new tab (optionally at url)
  tab-close [N]        close tab N (omit N = active)
  tab-activate H       focus the tab with stable handle H (from `tabs`)
  tab-follow on|off    auto-follow new tabs/popups, or stay put
  help                 show this help
  quit                 exit the console (the session stays alive)"""


_TARGET_FLAGS = {
    "--selector": "selector",
    "-s": "selector",
    "--role": "role",
    "--name": "name",
    "--text": "target_text",
}


def _target(tokens: list[str]) -> tuple[dict[str, Any], list[str]]:
    """Split a leading target off *tokens*; return ``(target_args, remaining)``.

    Accepted forms, checked in this order:

    * flags      -- ``--selector #go`` / ``--role button --name Save``
                    / ``--text Save`` / ``-s #go`` / ``--exact``
    * an index   -- ``3`` (a field index from the last ``list``)
    * a selector -- anything else (``#submit``, ``.btn``, ``//button[1]``)

    ``--name`` alone is not a target (it only qualifies ``--role``), matching the
    non-interactive CLI's guard in ``main._target_args``.
    Raises :class:`ValueError` with an actionable message when no target is given.
    """
    if not tokens:
        raise ValueError("provide a field index, a selector, or --selector/--role/--text")
    if tokens[0].startswith("-"):
        args: dict[str, Any] = {}
        i = 0
        while i < len(tokens) and tokens[i].startswith("-"):
            flag = tokens[i]
            if flag == "--exact":
                args["exact"] = True
                i += 1
                continue
            key = _TARGET_FLAGS.get(flag)
            if key is None:
                raise ValueError(f"unknown target flag {flag!r}")
            if i + 1 >= len(tokens):
                raise ValueError(f"{flag} needs a value")
            args[key] = tokens[i + 1]
            i += 2
        if not any(args.get(k) for k in ("selector", "role", "target_text")):
            raise ValueError("--name alone is not a target — add --role")
        return args, tokens[i:]
    token = tokens[0]
    if token.isdigit():
        return {"index": int(token)}, tokens[1:]
    return {"selector": token}, tokens[1:]


def _drag_target(tokens: list[str]) -> dict[str, Any]:
    """Turn a parsed target into drag's *destination* keys."""
    args, _ = _target(tokens)
    if "index" in args:
        return {"target_index": args["index"]}
    if "selector" in args:
        return {"target_selector": args["selector"]}
    raise ValueError("drag's destination must be an index or a selector")


def _is_confidence(token: str) -> bool:
    """True when *token* looks like a 0-1 match threshold (``find-image``'s last arg)."""
    try:
        return 0.0 <= float(token) <= 1.0 and ("." in token or token in ("0", "1"))
    except ValueError:
        return False


def _box_cell(b: Any) -> str:
    """Render a ``{x,y,width,height}`` rect as a compact ``x,y,w,h`` cell."""
    if not isinstance(b, dict):
        return "-"
    return f"{b['x']:.0f},{b['y']:.0f},{b['width']:.0f},{b['height']:.0f}"


_MOUSE_BUTTONS = ("left", "middle", "right")


def _button_arg(tokens: list[str]) -> dict[str, Any]:
    """An optional trailing ``left``/``middle``/``right`` word after a click target.

    The REPL cannot spell this as ``--button`` — ``_target`` consumes leading
    flags and would reject an unknown one — so it is a positional word, the same
    shape as ``press TARGET key``.
    """
    if tokens and tokens[0].lower() in _MOUSE_BUTTONS:
        return {"button": tokens[0].lower()}
    return {}


def format_fields(
    fields: list[dict[str, Any]],
    *,
    width: int | None = None,
    full: bool = False,
    boxes: bool = False,
) -> str:
    """Render fields as a table: #, KIND, NAME, and the ready-to-paste VISUS call.

    The VISUS column is copy-paste-ready and *frame-aware* — for an element inside
    an iframe it is wrapped in ``frame_locator(...)`` so a click/fill actually
    reaches it (a bare css/xpath would not). ``full=True`` adds the CSS and XPATH
    columns; they are off by default because on a large page they triple the
    output an agent has to read for no gain over the VISUS column. ``boxes``
    appends the field's viewport rect as ``x,y,w,h`` (from
    ``visus list-fields --boxes``). An ASCII box is used so the table renders on
    any console encoding.
    """
    if not fields:
        return "(no fields found)"
    from rich import box as rich_box
    from rich.console import Console
    from rich.table import Table

    table = Table(box=rich_box.ASCII, header_style="bold", pad_edge=False)
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("KIND", no_wrap=True)
    table.add_column("NAME", overflow="fold")
    table.add_column("VISUS (copy-paste)", overflow="fold", style="green")
    if full:
        table.add_column("CSS", overflow="fold")
        table.add_column("XPATH", overflow="fold")
    if boxes:
        table.add_column("BOX x,y,w,h", no_wrap=True)
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
        if boxes:
            row.append(_box_cell(f.get("box")))
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
            want_boxes = "--boxes" in rest
            words = [t for t in rest if t != "--boxes"]
            want_full = bool(words and words[0].lower() == "full")
            result = send("list_fields", {"highlight": False, "boxes": want_boxes})
            return format_fields(
                result.get("fields", []), full=want_full, boxes=want_boxes
            )
        if cmd == "click":
            tgt, tail = _target(rest)
            return _act("click", {**tgt, **_button_arg(tail)})
        if cmd == "fill":
            tgt, tail = _target(rest)
            return _act("fill", {**tgt, "text": " ".join(tail)})
        if cmd == "check":
            tgt, _ = _target(rest)
            return _act("check", tgt)
        if cmd == "uncheck":
            tgt, _ = _target(rest)
            return _act("uncheck", tgt)
        if cmd == "select":
            tgt, tail = _target(rest)
            return _act("select", {**tgt, "value": " ".join(tail)})
        if cmd == "press":
            if len(rest) == 1 and not rest[0].isdigit():
                return _act("press", {"key": rest[0]})
            tgt, tail = _target(rest)
            return _act("press", {**tgt, "key": " ".join(tail)})
        if cmd == "type":
            return _act("type", {"text": " ".join(rest)})
        if cmd == "keydown":
            return _act("key_down", {"key": rest[0]})
        if cmd == "keyup":
            return _act("key_up", {"key": rest[0]})
        if cmd == "mousemove":
            return _act("mouse_move", {"x": float(rest[0]), "y": float(rest[1])})
        if cmd == "mousedown":
            return _act("mouse_down", {"button": rest[0] if rest else "left"})
        if cmd == "mouseup":
            return _act("mouse_up", {"button": rest[0] if rest else "left"})
        if cmd == "mousewheel":
            return _act(
                "mouse_wheel", {"delta_x": float(rest[0]), "delta_y": float(rest[1])}
            )
        if cmd == "hover":
            tgt, _ = _target(rest)
            return _act("hover", tgt)
        if cmd == "dblclick":
            tgt, tail = _target(rest)
            return _act("dblclick", {**tgt, **_button_arg(tail)})
        if cmd == "focus":
            tgt, _ = _target(rest)
            return _act("focus", tgt)
        if cmd == "clear-input":
            tgt, _ = _target(rest)
            return _act("clear_input", tgt)
        if cmd == "upload":
            tgt, tail = _target(rest)
            if not tail:
                return "missing file path(s) for `upload` (try `help`)"
            paths = [str(Path(p).resolve()) for p in tail]
            return _act("upload", {**tgt, "paths": paths})
        if cmd == "drag":
            tgt, tail = _target(rest)
            return _act("drag", {**tgt, **_drag_target(tail)})
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
        if cmd == "resize":
            r = send("resize", {"width": int(rest[0]), "height": int(rest[1])})
            return f"viewport is now {r['width']}x{r['height']}"
        if cmd == "snapshot":
            want_boxes = "--boxes" in rest
            # `--boxes` is a flag, not the scope selector PLAN 4 reads from rest[0].
            scope = [t for t in rest if t != "--boxes"]
            snap_args: dict[str, Any] = {
                "selector": scope[0] if scope else None,
                "depth": None,
                "refs": True,
                "boxes": want_boxes,
            }
            elements = send("snapshot", snap_args).get("elements", [])
            if not elements:
                return "(no elements)"
            return "\n".join(
                f"{('-' if e.get('ref') is None else str(e['ref'])):>4}  "
                f"{str(e.get('role', '')):<16} {str(e.get('name', '')):<32} "
                f"{_box_cell(e.get('box'))}".rstrip()
                if want_boxes
                else f"{('-' if e.get('ref') is None else str(e['ref'])):>4}  "
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
            tgt, _ = _target(rest)
            # PLAN 3 Task 12: the op returns {"value", "present"}, so a stored ""
            # and a missing element must not both print an empty line.
            return render_value(send("get_text", tgt))
        if cmd in ("attr", "get-attribute"):
            tgt, _ = _target(rest[1:])
            return render_value(send("get_attribute", {**tgt, "attr_name": rest[0]}))
        if cmd == "count":
            tgt, _ = _target(rest)
            return str(send("count", tgt))
        if cmd == "wait":
            tgt, tail = _target(rest)
            wait_args: dict[str, Any] = dict(tgt)
            if tail:
                wait_args["state"] = tail[0]
            return str(send("wait", wait_args))
        if cmd in ("expect", "expect-text"):
            tgt, tail = _target(rest)
            return str(send("expect_text", {**tgt, "expected_text": " ".join(tail)}))
        if cmd == "cookies":
            items = send("cookies", {}).get("cookies", [])
            if not items:
                return "(no cookies)"
            return "\n".join(
                f"{c.get('name', '')}={c.get('value', '')}  ({c.get('domain', '')})"
                for c in items
            )
        if cmd == "add-cookies":
            try:
                parsed = json.loads(" ".join(rest))
            except json.JSONDecodeError as exc:
                return f"invalid JSON for `add-cookies`: {exc}"
            if not isinstance(parsed, list):
                return "invalid JSON for `add-cookies`: expected a list of cookie objects"
            return _act("add_cookies", {"cookies": parsed})
        if cmd == "clear-cookies":
            return _act("clear_cookies", {})
        if cmd == "state-save":
            path = str(Path(rest[0] if rest else "storage-state.json").resolve())
            r = send("state_save", {"path": path})
            return f"saved {r['path']} ({r['cookies']} cookie(s), {r['origins']} origin(s))"
        if cmd == "state-load":
            return str(send("state_load", {"path": str(Path(rest[0]).resolve())}))
        if cmd == "eval":
            return _act(
                "eval",
                {"expression": " ".join(rest)},
                lambda r: str((r or {}).get("result")),
            )
        if cmd == "eval-on":
            ev_target, ev_tail = _target(rest)
            return str(
                send("eval", {**ev_target, "expression": " ".join(ev_tail)}).get("result")
            )
        if cmd == "logs":
            messages = send("console_messages", {"level": rest[0] if rest else None}).get(
                "messages", []
            )
            if not messages:
                return "(no console messages)"
            return "\n".join(
                f"{str(m.get('level', '')):8} {m.get('text', '')}" for m in messages
            )
        if cmd == "requests":
            rows = send("network_requests", {"url_filter": rest[0] if rest else None}).get(
                "requests", []
            )
            if not rows:
                return "(no requests captured)"
            return "\n".join(
                f"[{r.get('index', i)}] {r.get('status', '')!s:>4} "
                f"{str(r.get('method', '')):6} {r.get('url', '')}"
                for i, r in enumerate(rows)
            )
        if cmd == "request":
            r = send("network_request", {"index": int(rest[0])})
            body = r.get("body")
            return (
                f"{r.get('method', '')} {r.get('url', '')}\n"
                f"status : {r.get('status', '')}\n\n"
                + (body if body is not None else "(body unavailable)")
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
        if cmd == "read-text":
            tgt, _ = _target(rest)
            return str(send("read_text", tgt))
        if cmd == "solve-captcha":
            tgt, _ = _target(rest)
            return str(send("solve_captcha", tgt))
        if cmd == "find-image":
            if not rest:
                return "missing template path for `find-image` (try `help`)"
            img_args: dict[str, Any] = {"template_path": str(Path(rest[0]).resolve())}
            tail = rest[1:]
            if tail and _is_confidence(tail[-1]):
                img_args["confidence"] = float(tail[-1])
                tail = tail[:-1]
            if tail:
                tgt, _ = _target(tail)
                img_args.update(tgt)
            found = send("find_image", img_args)
            if not found.get("found"):
                return "not found"
            return (
                f"found at ({found['x']}, {found['y']}) confidence={found['confidence']:.3f}"
            )
        if cmd == "clear":
            return str(send("clear_highlights", {}))
        if cmd == "highlight":
            if rest and rest[0].lower() in ("hide", "off", "--hide"):
                return str(send("highlight", {"hide": True}))
            hl_target, hl_tail = _target(rest)
            hl_args: dict[str, Any] = dict(hl_target)
            if hl_tail:
                hl_args["style"] = " ".join(hl_tail)
            return str(send("highlight", hl_args))
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
        if cmd == "tab-activate":
            r = send("tab_activate", {"handle": rest[0]})
            return f"activated tab {r['active']} ({r['handle']}): {str(r.get('title', ''))!r}"
        if cmd == "tab-follow":
            on = not (rest and rest[0].lower() in ("off", "false", "no", "manual"))
            r = send("tab_follow", {"enabled": on})
            return f"tab-follow {'enabled (auto)' if r['follow'] else 'disabled (manual)'}"
        return f"unknown command {cmd!r} (try `help`)"
    except IndexError:
        return f"missing argument for `{cmd}` (try `help`)"
    except ValueError as exc:
        # `_target` raises this for a bad/absent target, and int() for a
        # non-numeric tab index — both are user typos, not tracebacks.
        return f"bad argument for `{cmd}`: {exc}"
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
