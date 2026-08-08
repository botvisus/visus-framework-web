"""visus CLI — web automation commands."""

from __future__ import annotations

import datetime as _dt
import json as _json
import runpy
from pathlib import Path
from typing import Any

import typer

from visus.web import Engine, launch
from visus.web.cli import output

#: Shown at the bottom of `visus --help`. The skill is packaged in the wheel but
#: inert until a repo installs a copy, and nothing else in the help output would
#: tell a user that it exists — so the discovery hint lives here.
_EPILOG = (
    "Installing skills\n"
    "Claude Code, GitHub Copilot and others will use the locally installed skills.\n"
    "\n"
    "visus install --skills\n"
)

app = typer.Typer(
    help="visus.web — Playwright-style web automation on Selenium.",
    epilog=_EPILOG,
    no_args_is_help=True,
)

#: Subcommands that install the skill — they must never be nagged about it.
#: May grow, must never shrink.
_SKILL_INSTALL_COMMANDS: tuple[str, ...] = ("install", "install-skills")


@app.callback()
def _root(
    ctx: typer.Context,
    as_json: bool = typer.Option(
        False, "--json", help="Emit exactly one JSON document per command."
    ),
    raw: bool = typer.Option(
        False, "--raw", help="Print only the value — no table, no ### Code, no ### Page."
    ),
    snapshot_sink: bool = typer.Option(
        False,
        "--snapshot",
        help="After every action, write .visus/snapshots/page-<ts>.yml and link it.",
    ),
    output_dir: str = typer.Option(
        None,
        "--output-dir",
        envvar="VISUS_WEB_OUTPUT_DIR",
        help="Directory for screenshots/snapshots/scripts (default: the current directory).",
    ),
) -> None:
    """Global entry point for every `visus` subcommand.

    This is the project's only group-level callback and therefore the single hook
    for global flags (PLAN 6's `--session` / `--config` are reserved to attach
    here too). Click's eager `--help` exits before a group callback runs, so this
    body does not execute for `visus --help` or bare `visus` — the flags still
    appear in the help text because they are declared here.
    """
    # Local import: PLAN 1 keeps it inside the function so `visus` still starts
    # when the skill package is unreadable.
    from visus.web.cli.skill_check import check_installed_skills

    # set_mode FIRST (PLAN 1's extension contract, rule 3): a skill-drift warning
    # must never be written before the output mode is decided.
    output.set_mode(as_json=as_json, raw=raw)
    output.set_output_dir(output_dir)
    output.set_snapshot_sink(snapshot_sink)
    # The guard tuple is PLAN 1's constant — never re-inline the literal, and never
    # shrink it: warning a user while they run the command that fixes the warning
    # is the bug it exists to prevent.
    if ctx.invoked_subcommand not in _SKILL_INSTALL_COMMANDS:
        check_installed_skills()


@app.command()
def version() -> None:
    """Print the visus.web version."""
    from visus.web import __version__

    output.emit(__version__)


def _read_clipboard() -> str | None:
    """Best-effort read of the OS clipboard (so 'Copy element' → translate just works)."""
    import subprocess
    import sys

    cmd = {
        "win32": ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
        "darwin": ["pbpaste"],
    }.get(sys.platform, ["xclip", "-selection", "clipboard", "-o"])
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout or None
    except Exception:
        return None


@app.command()
def translate(
    html: str | None = typer.Argument(
        None, help="Element outerHTML. Omit to read the clipboard; or use --file / pipe via stdin."
    ),
    file: str | None = typer.Option(
        None, "--file", "-f", help="Read the element HTML from a file."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON (handy for scripts / AI)."),
) -> None:
    """Translate a pasted DevTools element into css/xpath/id/class selectors.

    Easiest on Windows (the shell mangles <, >, "): copy the element in DevTools
    (Copy element), then run ``visus translate`` with no argument — it reads your
    clipboard. You can also pass --file <path> or pipe the HTML via stdin.
    """
    import sys

    from visus.web.api._htmlsel import translate as _translate

    src = html
    if file:
        src = Path(file).read_text(encoding="utf-8")
    elif src is None:
        src = (None if sys.stdin.isatty() else sys.stdin.read()) or _read_clipboard()
    if not src or "<" not in src:
        output.emit_error(
            "No element HTML found. Pass it as an argument, use --file <path>, pipe it via "
            "stdin, or copy the element to your clipboard first.",
            code=2,
        )

    r = _translate(src)
    if as_json:
        output.set_mode(as_json=True)
    if output.mode() is output.Mode.JSON:
        output.emit(r)
        return
    lines = [f"tag    : {r['tag']}"]
    for key, label in (
        ("id", "id     "),
        ("name", "name   "),
        ("css", "css    "),
        ("xpath", "xpath  "),
        ("class", "class  "),
    ):
        if r[key]:
            lines.append(f"{label}: {r[key]}")
    lines.append("candidates (the smart locator tries these in order):")
    for c in [*r["candidates_css"], *r["candidates_xpath"]]:  # type: ignore[misc]
        lines.append(f"  - {c}")
    output.emit(r, table="\n".join(lines))


@app.command()
def doctor(engine: str = "chrome") -> None:
    """Check that a browser + driver launch correctly."""
    try:
        with launch(Engine.from_str(engine), headless=True) as b:
            p = b.new_page()
            p.goto("data:text/html,<title>ok</title>")
            output.emit(f"OK: {engine} launches and navigates (title: {p.title()!r})")
    except Exception as exc:  # noqa: BLE001
        output.emit_error(f"FAILED: {exc}")


def _install_skills(flavor: str, *, force: bool) -> None:
    """Copy the bundled agent skill into the current repo and report the paths."""
    from visus.web.cli.skills import install_skills

    if flavor not in ("claude", "agents", "both"):
        typer.echo(f"error: unknown skill target {flavor!r} — use claude, agents, or both")
        raise typer.Exit(2)
    written = install_skills(Path.cwd(), flavor=flavor, force=force)
    for path in written:
        typer.echo(f"wrote {path}")
    typer.echo(f"installed the visus-web skill ({len(written)} files)")


@app.command()
def install(
    engine: str = typer.Option("chrome", "--engine", help="Engine to resolve a driver for."),
    skills: str = typer.Option(
        None,
        "--skills",
        help="Install the agent skill instead of a driver: --skills or --skills=agents.",
    ),
    force: bool = typer.Option(
        False, "--force", help="With --skills: wipe the target directory before copying."
    ),
) -> None:
    """Resolve/download the driver via Selenium Manager, or install the agent skill."""
    if skills is not None:
        _install_skills(skills, force=force)
        return
    with launch(Engine.from_str(engine), headless=True):
        output.emit(f"{engine} driver is ready (Selenium Manager).")


@app.command("install-skills")
def install_skills_cmd(
    target: str = typer.Option("claude", "--target", help="claude | agents | both"),
    force: bool = typer.Option(
        False, "--force", help="Wipe the target directory before copying."
    ),
) -> None:
    """Install the bundled `visus-web` agent skill into this repository."""
    _install_skills(target, force=force)


@app.command()
def screenshot(
    url: str,
    input_path: str = typer.Option("screenshot.png", "-o", "--output"),
    full_page: bool = False,
    headless: bool = True,
    engine: str = "chrome",
) -> None:
    """Screenshot a URL to a PNG file."""
    with launch(Engine.from_str(engine), headless=headless) as b:
        p = b.new_page()
        p.goto(url)
        p.screenshot(path=input_path, full_page=full_page)
    output.emit(input_path, table=f"saved {input_path}")


@app.command()
def pdf(
    url: str,
    input_path: str = typer.Option("page.pdf", "-o", "--output"),
    engine: str = "chrome",
) -> None:
    """Print a URL to a PDF (Chromium)."""
    with launch(Engine.from_str(engine), headless=True) as b:
        p = b.new_page()
        p.goto(url)
        p.pdf(path=input_path)
    output.emit(input_path, table=f"saved {input_path}")


@app.command()
def open(url: str, engine: str = "chrome") -> None:  # noqa: A001
    """Open a headed browser at URL and wait until you press Enter."""
    with launch(Engine.from_str(engine), headless=False) as b:
        b.new_page().goto(url)
        typer.echo("Browser open. Press Enter to close...")
        input()


@app.command()
def run(script: str) -> None:
    """Run a Python script (convenience)."""
    runpy.run_path(script, run_name="__main__")


@app.command()
def mcp() -> None:
    """Start the visus.web MCP server (stdio)."""
    from visus.web.cli._entry import mcp_main

    mcp_main()


@app.command()
def codegen(
    url: str,
    input_path: str | None = typer.Option(None, "-o", "--output"),
    engine: str = "chrome",
) -> None:
    """Record interactions in a headed browser and generate visus.web code."""
    from visus.web.cli.codegen import drain, generate_script, inject_recorder

    events: list[dict] = []  # type: ignore[type-arg]
    with launch(Engine.from_str(engine), headless=False) as b:
        p = b.new_page()
        p.goto(url)
        inject_recorder(p)
        typer.echo("Recording... interact with the page, then press Enter to finish.")
        try:
            input()
        finally:
            events = drain(p)
    code = generate_script(url, events)
    if input_path:
        Path(input_path).write_text(code, encoding="utf-8")
        output.emit(input_path, table=f"saved {input_path}")
    else:
        output.emit(code)


# ---------------------------------------------------------------------------
# Persistent session: daemon + thin client commands + REPL
# ---------------------------------------------------------------------------

session_app = typer.Typer(help="Manage the persistent browser session (daemon).")
app.add_typer(session_app, name="session")


def _send(op: str, args: dict[str, Any] | None = None) -> Any:
    """Send an op to the running daemon, mapping failures to a clean Exit(1).

    ``socket.timeout`` is an ``OSError`` and a truncated reply raises
    ``JSONDecodeError`` — neither is a ``SessionError``, and both used to reach
    the user as a raw traceback.
    """
    from visus.web.cli import session_client

    try:
        return session_client.send(op, args or {})
    except session_client.SessionError as exc:
        output.emit_error(f"error: {exc}")
    except _json.JSONDecodeError as exc:
        output.emit_error(f"error: daemon sent a malformed response — {exc}")
    except OSError as exc:
        output.emit_error(f"error: daemon communication failed — {type(exc).__name__}: {exc}")


def _send_env(op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send an op and return the daemon's full envelope, mapping failures to Exit(1).

    Commands that change the page use this so they can print ``### Code`` and
    ``### Page``; plain reads keep using :func:`_send`, whose bare value pipes
    cleanly.

    Mirrors ALL THREE of ``_send``'s exception handlers (not just
    ``SessionError``) — a mutating command hitting a socket timeout or a
    corrupt reply must exit(1) cleanly too, not leak a raw traceback.
    """
    from visus.web.cli import session_client

    payload = dict(args or {})
    if output.snapshot_sink():
        payload["snapshot"] = True
    try:
        return session_client.send_envelope(op, payload)
    except session_client.SessionError as exc:
        output.emit_error(f"error: {exc}")
    except _json.JSONDecodeError as exc:
        output.emit_error(f"error: daemon sent a malformed response — {exc}")
    except OSError as exc:
        output.emit_error(f"error: daemon communication failed — {type(exc).__name__}: {exc}")


def _format_fields(fields: list[dict[str, Any]]) -> str:
    from visus.web.cli.console import format_fields

    return format_fields(fields)


def _format_snapshot(elements: list[dict[str, Any]]) -> str:
    """Render snapshot rows as a REF/ROLE/NAME table (REF = a list-fields index)."""
    from rich import box
    from rich.console import Console
    from rich.table import Table

    table = Table(box=box.ASCII, header_style="bold", pad_edge=False)
    table.add_column("REF", justify="right", no_wrap=True)
    table.add_column("ROLE", no_wrap=True)
    table.add_column("NAME", overflow="fold")
    for e in elements:
        ref = e.get("ref")
        table.add_row("-" if ref is None else str(ref), str(e.get("role", "")),
                      str(e.get("name", "")))
    console_obj = Console()
    with console_obj.capture() as cap:
        console_obj.print(table)
    return cap.get().rstrip("\n")


def _render_value(result: Any) -> str:
    from visus.web.cli.console import render_value

    return render_value(result)


def _target_args(
    index: int | None,
    selector: str | None,
    role: str | None,
    name: str | None,
    text: str | None,
) -> dict[str, Any]:
    """Build the {index|selector|role|name|text} target dict for an action op."""
    if index is not None:
        return {"index": index}
    if not (selector or role or text):
        typer.echo("error: provide an index, or --selector / --role / --text")
        raise typer.Exit(1)
    return {"selector": selector, "role": role, "name": name, "target_text": text}


@session_app.command("start")
def session_start(
    url: str = typer.Argument(None, help="URL to open once the browser starts."),
    engine: str = typer.Option("chrome", "--engine", "-e"),
    headless: bool = typer.Option(False, "--headless", help="Run headless (default: headed)."),
    idle_timeout: float = typer.Option(
        None,
        "--idle-timeout",
        help="Stop the daemon after N seconds with no command (omit = never).",
    ),
) -> None:
    """Start a persistent browser session (detached daemon)."""
    from visus.web.cli import session_client

    try:
        info = session_client.start_daemon(engine, headless, url, idle_timeout=idle_timeout)
    except session_client.SessionError as exc:
        output.emit_error(f"error: {exc}")
    output.emit(
        info,
        table=f"session started (pid {info['pid']}, port {info['port']}, engine {engine})",
    )


@session_app.command("stop")
def session_stop() -> None:
    """Stop the running session (closes the browser)."""
    from visus.web.cli import session_client

    output.emit(session_client.stop())


@session_app.command("kill")
def session_kill() -> None:
    """Force-clear a wedged session: terminate the daemon and delete its state.

    Use when `visus session start` reports a timeout or `visus session stop`
    cannot reach the daemon — those paths cannot recover a process that was
    killed mid-flight and left `.visus/session.json.lock` behind.
    """
    from visus.web.cli import session_client

    output.emit(session_client.kill())


@session_app.command("status")
def session_status(
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show the running session's status."""
    from visus.web.cli import session_client

    if as_json:
        output.set_mode(as_json=True)
    info = session_client.status()
    if info is None:
        output.emit_error("no session running")
    keys = ("pid", "port", "engine", "headless", "url", "title", "windows", "active_tab",
            "fields_cached")
    output.emit(
        info,
        table="\n".join(f"{k:14}: {info[k]}" for k in keys if k in info),
    )


@session_app.command("export-script")
def session_export_script(
    output_path: str = typer.Option(
        None, "-o", "--output", help="Write the script here (default: print it)."
    ),
) -> None:
    """Emit a runnable visus.web script from everything this session did."""
    result = _send("export_script", {})
    code = str(result.get("script", ""))
    if output_path:
        dest = Path(output.resolve_out(output_path))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(code, encoding="utf-8")
        output.emit(code, table=f"saved {dest} ({result.get('lines', 0)} action(s))")
        return
    output.emit(code, table=code)


@app.command("list-fields")
def list_fields(
    kind: str = typer.Option(None, "--kind", help="Comma-separated kinds (e.g. input,button)."),
    show_all: bool = typer.Option(False, "--all", help="Include hidden/disabled fields."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
    no_highlight: bool = typer.Option(False, "--no-highlight", help="Skip the numbered overlay."),
) -> None:
    """Enumerate interactive fields on the current page (numbered, highlighted)."""
    kinds = [k.strip() for k in kind.split(",") if k.strip()] if kind else None
    result = _send(
        "list_fields",
        {"kinds": kinds, "include_hidden": show_all, "highlight": not no_highlight},
    )
    fields = result.get("fields", [])
    if as_json:
        output.set_mode(as_json=True)
    output.emit(fields, table=_format_fields(fields))


@app.command()
def click(
    index: int = typer.Argument(None, help="Field index from the last list-fields."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
) -> None:
    """Click a field by index or by --selector/--role/--text."""
    output.emit_envelope(_send_env("click", _target_args(index, selector, role, name, text)))


@app.command()
def fill(
    index: int = typer.Argument(None, help="Field index from the last list-fields."),
    text: str = typer.Argument(None, help="Text to fill, e.g. `visus fill 7 hello`."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    by_text: str = typer.Option(None, "--text", help="Target a field by its visible text."),
    value: str = typer.Option(
        None, "--value", help="Text to fill when targeting by --selector/--role/--text."
    ),
) -> None:
    """Fill a field. By index: `visus fill 7 hello`. By selector: `-s "#u" --value hello`."""
    args = _target_args(index, selector, role, name, by_text)
    fill_value = text if text is not None else value
    if fill_value is None:
        output.emit_error("error: no text to fill — use `visus fill <index> <text>` or `--value`")
    args["text"] = fill_value
    output.emit_envelope(_send_env("fill", args))


@app.command()
def check(
    index: int = typer.Argument(None),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
) -> None:
    """Check a checkbox/radio field."""
    output.emit_envelope(_send_env("check", _target_args(index, selector, role, name, None)))


@app.command()
def uncheck(
    index: int = typer.Argument(None),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
) -> None:
    """Uncheck a checkbox field."""
    output.emit_envelope(_send_env("uncheck", _target_args(index, selector, role, name, None)))


@app.command()
def select(
    index: int = typer.Argument(None, help="Field index from the last list-fields."),
    value: str = typer.Argument(None, help="Option value, e.g. `visus select 5 US`."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    by_text: str = typer.Option(None, "--text", help="Target a field by its visible text."),
    option_value: str = typer.Option(
        None, "--value", help="Option value when targeting by --selector/--role/--text."
    ),
) -> None:
    """Select an option on a <select> field. By index: `visus select 5 US`."""
    args = _target_args(index, selector, role, name, by_text)
    val = value if value is not None else option_value
    if val is None:
        output.emit_error(
            "error: no option value — use `visus select <index> <value>` or `--value`"
        )
    args["value"] = val
    output.emit_envelope(_send_env("select", args))


@app.command()
def press(
    index: int = typer.Argument(None, help="Field index from the last list-fields."),
    key: str = typer.Argument(None, help="Key to press, e.g. `visus press 7 Enter`."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    by_text: str = typer.Option(None, "--text", help="Target a field by its visible text."),
    key_value: str = typer.Option(
        None, "--key", help="Key when targeting by --selector/--role/--text."
    ),
) -> None:
    """Press a key on a field (e.g. Enter, Tab, Control+a). By index: `visus press 7 Enter`."""
    args = _target_args(index, selector, role, name, by_text)
    k = key if key is not None else key_value
    if k is None:
        output.emit_error("error: no key — use `visus press <index> <key>` or `--key`")
    args["key"] = k
    output.emit_envelope(_send_env("press", args))


@app.command()
def goto(url: str = typer.Argument(..., help="URL to navigate to.")) -> None:
    """Navigate the session's page to a URL."""
    env = _send_env("goto", {"url": url})
    output.emit_envelope(env, table=f"navigated to {env.get('result')}")


@app.command("get-text")
def get_text(
    index: int = typer.Argument(None),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
) -> None:
    """Print a field's text content."""
    result = _send("get_text", _target_args(index, selector, role, name, text))
    output.emit(result, table=_render_value(result))


@app.command("session-screenshot")
def session_screenshot(
    input_path: str = typer.Option("screenshot.png", "-o", "--output"),
    full_page: bool = typer.Option(
        False, "--full-page", help="Capture the full scrollable page, not just the viewport."
    ),
    index: int = typer.Argument(None, help="Field index to screenshot (omit = whole page)."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text", help="Target an element by its visible text."),
) -> None:
    """Screenshot the session's page (or a single element) to a PNG file.

    With no target it captures the page (``--full-page`` for the whole scroll
    height). Give an index or ``--selector``/``--role``/``--text`` to screenshot
    just that element (mirrors the MCP ``browser_screenshot`` tool).
    """
    # Resolve the path against the CLIENT's cwd (not the daemon's) so the PNG
    # lands where the user invoked the command, not under the daemon's base dir.
    abs_output = output.resolve_out(input_path)
    args: dict[str, Any] = {"path": abs_output, "full_page": full_page}
    if index is not None or selector or role or text:
        args.update(_target_args(index, selector, role, name, text))
    saved = _send("screenshot", args)
    output.emit(saved, table=f"saved {saved}")


@app.command("clear")
def clear_highlights() -> None:
    """Remove the numbered field-highlight overlay."""
    output.emit(_send("clear_highlights", {}))


@app.command()
def tabs(as_json: bool = typer.Option(False, "--json", help="Emit JSON.")) -> None:
    """List open tabs/windows (the active one is marked with *)."""
    result = _send("tabs", {})
    if as_json:
        output.set_mode(as_json=True)
    items = result.get("tabs", [])
    if not items:
        output.emit(result, table="(no tabs)")
        return
    table = "\n".join(
        f"{'*' if t.get('active') else ' '} [{t['index']}] "
        f"{str(t.get('title', ''))!r}  {t.get('url', '')}"
        for t in items
    )
    output.emit(result, table=table)


@app.command()
def tab(
    index: int = typer.Argument(None, help="Tab/window index from `visus tabs` (omit = newest)."),
) -> None:
    """Switch the session to a tab/window by index (or the newest if omitted)."""
    env = _send_env("tab", {"index": index})
    result = env.get("result") or {}
    output.emit_envelope(
        env, table=f"switched to tab {result['active']}: {str(result.get('title', ''))!r}"
    )


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


@app.command()
def back() -> None:
    """Navigate back in the session's history."""
    env = _send_env("back", {})
    output.emit_envelope(env, table=f"went back to {env.get('result')}")


@app.command()
def forward() -> None:
    """Navigate forward in the session's history."""
    env = _send_env("forward", {})
    output.emit_envelope(env, table=f"went forward to {env.get('result')}")


@app.command()
def reload() -> None:
    """Reload the session's current page."""
    env = _send_env("reload", {})
    output.emit_envelope(env, table=f"reloaded {env.get('result')}")


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------


@app.command()
def title() -> None:
    """Print the session page's title."""
    output.emit(_send("title", {}))


@app.command()
def url() -> None:
    """Print the session page's current URL."""
    output.emit(_send("url", {}))


@app.command()
def snapshot(
    selector: str = typer.Argument(
        None, help='Scope the snapshot to a CSS selector, e.g. "#main".'
    ),
    depth: int = typer.Option(
        None, "--depth", help="Keep only elements at most N levels below the scope root."
    ),
    filename: str = typer.Option(
        None, "--filename", help="Write the snapshot as YAML here instead of printing it."
    ),
    refs: bool = typer.Option(
        True,
        "--refs/--no-refs",
        help="Number rows with list-fields indexes (re-enumerates the page).",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List the page's interactive elements as a REF/ROLE/NAME table.

    A REF is a `visus list-fields` index: `visus snapshot` then `visus click 4`
    works. Scope it (`visus snapshot "#main"`), cap it (`--depth 2`), or save it
    (`--filename after-login.yml`) when the page is large.
    """
    args: dict[str, Any] = {"selector": selector, "depth": depth, "refs": refs}
    result = _send("snapshot", args)
    elements = result.get("elements", [])
    if as_json:
        output.set_mode(as_json=True)

    if filename or output.snapshot_sink():
        from visus.web.cli.session_server import render_snapshot_yaml

        target = filename or f"page-{_dt.datetime.now():%Y-%m-%dT%H-%M-%S}.yml"
        dest = Path(output.resolve_out(target))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            render_snapshot_yaml(
                elements, url=str(result.get("url", "")), title=str(result.get("title", ""))
            ),
            encoding="utf-8",
        )
        output.emit(elements, table=f"Snapshot: {dest}")
        return

    if not elements:
        output.emit(elements, table="(no elements)")
        return
    output.emit(elements, table=_format_snapshot(elements))


@app.command("get-attribute")
def get_attribute(
    attr_name: str = typer.Argument(..., help="Attribute name, e.g. `href`."),
    index: int = typer.Argument(None, help="Field index from the last list-fields."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
) -> None:
    """Print an element's attribute value."""
    args = _target_args(index, selector, role, name, text)
    args["attr_name"] = attr_name
    result = _send("get_attribute", args)
    output.emit(result, table=_render_value(result))


@app.command()
def count(
    index: int = typer.Argument(None, help="Field index from the last list-fields."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
) -> None:
    """Print how many elements match the target."""
    output.emit(_send("count", _target_args(index, selector, role, name, text)))


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


@app.command()
def hover(
    index: int = typer.Argument(None),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
) -> None:
    """Hover over a field by index or by --selector/--role/--text."""
    output.emit_envelope(_send_env("hover", _target_args(index, selector, role, name, text)))


@app.command()
def dblclick(
    index: int = typer.Argument(None),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
) -> None:
    """Double-click a field by index or by --selector/--role/--text."""
    output.emit_envelope(_send_env("dblclick", _target_args(index, selector, role, name, text)))


@app.command()
def focus(
    index: int = typer.Argument(None),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
) -> None:
    """Focus a field by index or by --selector/--role/--text."""
    output.emit_envelope(_send_env("focus", _target_args(index, selector, role, name, text)))


@app.command("clear-input")
def clear_input(
    index: int = typer.Argument(None),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
) -> None:
    """Clear an input field's value (distinct from `clear`, which removes highlights)."""
    output.emit_envelope(_send_env("clear_input", _target_args(index, selector, role, name, text)))


@app.command()
def drag(
    index: int = typer.Argument(None, help="Source field index from the last list-fields."),
    target_index: int = typer.Argument(None, help="Target field index."),
    selector: str = typer.Option(None, "--selector", "-s", help="Source selector."),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    to_selector: str = typer.Option(None, "--to-selector", help="Target CSS/XPath selector."),
    to_index: int = typer.Option(None, "--to-index", help="Target field index."),
) -> None:
    """Drag a source element onto a target. By index: `visus drag 3 7`."""
    args = _target_args(index, selector, role, name, text)
    if to_selector is not None:
        args["target_selector"] = to_selector
    elif to_index is not None:
        args["target_index"] = to_index
    elif target_index is not None:
        args["target_index"] = target_index
    else:
        output.emit_error(
            "error: provide a drag target — `<target_index>`, --to-selector, or --to-index"
        )
    output.emit_envelope(_send_env("drag", args))


# Module-level singleton default (B008: a function call cannot be a mutable
# list-typed default inline; reading it from a module variable is the fix).
_UPLOAD_PATHS_ARG = typer.Argument(None, help="One or more file paths to upload.")


@app.command()
def upload(
    index: int = typer.Argument(None, help="File-input field index from the last list-fields."),
    paths: list[str] = _UPLOAD_PATHS_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
) -> None:
    """Set file(s) on a file input. By index: `visus upload 4 a.png b.png`."""
    if not paths:
        output.emit_error("error: provide at least one file path to upload")
    args = _target_args(index, selector, role, name, text)
    # Resolve paths against the CLIENT's cwd so the daemon receives absolute paths.
    args["paths"] = [str(Path(p).resolve()) for p in paths]
    output.emit_envelope(_send_env("upload", args))


# ---------------------------------------------------------------------------
# Wait / Expect
# ---------------------------------------------------------------------------


@app.command()
def wait(
    index: int = typer.Argument(None),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    state: str = typer.Option("visible", "--state", help="visible|hidden|attached|detached."),
    timeout: int = typer.Option(None, "--timeout", help="Timeout in milliseconds."),
) -> None:
    """Wait for an element to reach a state (visible/hidden)."""
    args = _target_args(index, selector, role, name, text)
    args["state"] = state
    if timeout is not None:
        args["timeout"] = timeout
    output.emit(_send("wait", args))


@app.command("expect-text")
def expect_text(
    index: int = typer.Argument(None, help="Field index from the last list-fields."),
    expected: str = typer.Argument(None, help="The expected text."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    expected_text: str = typer.Option(
        None, "--expected", help="Expected text when targeting by --selector/--role/--text."
    ),
    timeout: int = typer.Option(None, "--timeout", help="Timeout in milliseconds."),
) -> None:
    """Assert an element contains text (prints PASSED/FAILED). By index: `expect-text 0 Hi`."""
    args = _target_args(index, selector, role, name, text)
    want = expected if expected is not None else expected_text
    if want is None:
        output.emit_error(
            "error: no expected text — use `visus expect-text <index> <text>` or --expected"
        )
    args["expected_text"] = want
    if timeout is not None:
        args["timeout"] = timeout
    output.emit(_send("expect_text", args))


# ---------------------------------------------------------------------------
# Tabs (new / close)
# ---------------------------------------------------------------------------


@app.command("tab-new")
def tab_new(
    url: str = typer.Argument(None, help="Optional URL to open in the new tab."),
) -> None:
    """Open a new tab/window (optionally at URL) and switch the session to it."""
    env = _send_env("tab_new", {"url": url})
    result = env.get("result") or {}
    output.emit_envelope(
        env, table=f"opened tab {result['index']}: {str(result.get('title', ''))!r}"
    )


@app.command("tab-close")
def tab_close(
    index: int = typer.Argument(None, help="Tab index to close (omit = the active tab)."),
) -> None:
    """Close a tab/window by index (or the active one if omitted)."""
    env = _send_env("tab_close", {"index": index})
    result = env.get("result") or {}
    if result.get("remaining", 0) == 0:
        # Both branches are PLAN 3 Task 7's honest message — do NOT collapse them
        # back to the unconditional "session stopped", which was the lie B4 fixed.
        if result.get("session_stopped"):
            output.emit_envelope(env, table="closed the last tab — session stopped")
        else:
            output.emit_envelope(env, table="closed the last tab — the browser is closed")
        return
    output.emit_envelope(
        env, table=f"closed tab {result['closed']} ({result['remaining']} remaining)"
    )


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------


@app.command()
def dialog(
    accept: bool = typer.Option(
        True, "--accept/--dismiss", help="Accept (default) or dismiss the dialog."
    ),
    prompt_text: str = typer.Option(None, "--prompt-text", help="Text for a prompt() dialog."),
) -> None:
    """Handle the next pending dialog (alert/confirm/prompt)."""
    output.emit_envelope(_send_env("dialog", {"accept": accept, "prompt_text": prompt_text}))


# ---------------------------------------------------------------------------
# Cookies
# ---------------------------------------------------------------------------


@app.command()
def cookies(as_json: bool = typer.Option(False, "--json", help="Emit JSON.")) -> None:
    """List all cookies for the session's context."""
    result = _send("cookies", {})
    items = result.get("cookies", [])
    if as_json:
        output.set_mode(as_json=True)
    if not items:
        output.emit(items, table="(no cookies)")
        return
    table = "\n".join(
        f"{c.get('name', '')}={c.get('value', '')}  ({c.get('domain', '')})" for c in items
    )
    output.emit(items, table=table)


@app.command("add-cookies")
def add_cookies(
    cookies_json: str = typer.Argument(..., help='JSON list, e.g. \'[{"name":"a","value":"b","url":"http://x"}]\'.'),
) -> None:
    """Add cookies from a JSON list to the session's context."""
    try:
        parsed = _json.loads(cookies_json)
    except _json.JSONDecodeError as exc:
        output.emit_error(f"error: invalid JSON — {exc}")
    if not isinstance(parsed, list):
        output.emit_error("error: expected a JSON list of cookie objects")
    output.emit_envelope(_send_env("add_cookies", {"cookies": parsed}))


@app.command("clear-cookies")
def clear_cookies() -> None:
    """Clear all cookies in the session's context."""
    output.emit_envelope(_send_env("clear_cookies", {}))


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------


@app.command("eval")
def eval_js(
    expression: str = typer.Argument(..., help="A JS function, e.g. '() => document.title'."),
    arg: str = typer.Argument(None, help="Optional JSON argument passed to the function."),
    as_json: bool = typer.Option(False, "--json", help="Emit the result as JSON."),
) -> None:
    """Evaluate a JavaScript expression in the page and print the result."""
    parsed_arg: Any = None
    if arg is not None:
        try:
            parsed_arg = _json.loads(arg)
        except _json.JSONDecodeError:
            parsed_arg = arg  # treat as a plain string when not valid JSON
    env = _send_env("eval", {"expression": expression, "arg": parsed_arg})
    if as_json:
        output.set_mode(as_json=True)
    value = (env.get("result") or {}).get("result")
    output.emit_envelope(env, table="" if value is None else str(value))


# ---------------------------------------------------------------------------
# Vision (requires the [vision] extra)
# ---------------------------------------------------------------------------


@app.command("read-text")
def read_text(
    index: int = typer.Argument(None),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
) -> None:
    """OCR the targeted element's screenshot and print the recognized text."""
    output.emit(_send("read_text", _target_args(index, selector, role, name, text)))


@app.command("solve-captcha")
def solve_captcha(
    index: int = typer.Argument(None),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
) -> None:
    """OCR-solve a text CAPTCHA in the targeted element and print the solution."""
    output.emit(_send("solve_captcha", _target_args(index, selector, role, name, text)))


@app.command("find-image")
def find_image(
    template: str = typer.Argument(..., help="Path to the template PNG to search for."),
    index: int = typer.Argument(None, help="Optional field index to scope the search."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    confidence: float = typer.Option(0.8, "--confidence", "-c", help="Match threshold (0-1)."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Find a template image inside the page (or a targeted element)."""
    args: dict[str, Any] = {
        "template_path": str(Path(template).resolve()),
        "confidence": confidence,
    }
    if index is not None:
        args["index"] = index
    if selector or role or text:
        args["selector"] = selector
        args["role"] = role
        args["name"] = name
        args["target_text"] = text
    result = _send("find_image", args)
    if as_json:
        output.set_mode(as_json=True)
    if result.get("found"):
        table = f"found at ({result['x']}, {result['y']}) confidence={result['confidence']:.3f}"
    else:
        table = "not found"
    output.emit(result, table=table)


@app.command()
def console(
    url: str = typer.Argument(None, help="Optional URL to open."),
    engine: str = typer.Option("chrome", "--engine", "-e"),
    headless: bool = typer.Option(False, "--headless"),
) -> None:
    """Open an interactive REPL attached to the session (starts one if none)."""
    from visus.web.cli.console import run_console

    run_console(url, engine=engine, headless=headless)
