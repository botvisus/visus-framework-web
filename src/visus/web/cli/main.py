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

# The one positional every element command shares. Defined up here because the
# first of them (`screenshot`) is declared long before the targeting helpers.
_TARGET_ARG = typer.Argument(
    None,
    metavar="[TARGET]",
    help='A `list-fields` index (7) or a selector ("#id", ".cls", "//xpath", "text=Hi").',
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
    session: str = typer.Option(
        None,
        "--session",
        "-S",
        envvar="VISUS_WEB_SESSION",
        help="Session name (default: 'default'). `-s` is --selector, so this is -S.",
    ),
    config: str = typer.Option(
        None,
        "--config",
        envvar="VISUS_WEB_CONFIG",
        help="Config file (default: the nearest .visus/cli.json).",
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
    from visus.web.cli import config as cliconfig
    from visus.web.cli import session_client
    from visus.web.cli.skill_check import check_installed_skills

    # set_mode FIRST (PLAN 1's extension contract, rule 3): a skill-drift warning
    # must never be written before the output mode is decided. Everything below
    # can fail, and every failure leaves through emit_error, which formats itself
    # according to the mode.
    output.set_mode(as_json=as_json, raw=raw)
    output.set_snapshot_sink(snapshot_sink)

    try:
        cfg = cliconfig.resolve(config)
    except cliconfig.ConfigError as exc:
        output.emit_error(str(exc))
    cliconfig.set_active(cfg)

    # An explicit flag always wins over the config file (`is_default` is not needed
    # here: `--session`/`--output-dir` default to None, so `or`/`is not None` is the
    # same test).
    output.set_output_dir(output_dir if output_dir is not None else cfg.output_dir)
    # AFTER set_mode (PLAN 1's rule 3) so an invalid name leaves through
    # emit_error formatted for the active mode, and BEFORE the skill check.
    # The try/except is _root's only error funnel: without it a bad name would
    # be a traceback rather than a clean exit 1 on stderr.
    try:
        session_client.set_session_name(session or cfg.session)
    except session_client.SessionError as exc:
        output.emit_error(f"error: {exc}")
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


@app.command()
def devices() -> None:
    """List the device presets `session start --device` accepts."""
    from visus.web.api.devices import DEVICES
    from visus.web.cli import output

    rows = [
        {
            "name": d.name,
            "width": d.width,
            "height": d.height,
            "device_scale_factor": d.device_scale_factor,
            "mobile": d.mobile,
        }
        for d in DEVICES.values()
    ]
    from rich import box
    from rich.console import Console
    from rich.table import Table

    table = Table(box=box.ASCII, header_style="bold", pad_edge=False)
    for column in ("NAME", "WIDTH", "HEIGHT", "DPR", "MOBILE"):
        table.add_column(column, no_wrap=True)
    for row in rows:
        table.add_row(
            str(row["name"]),
            str(row["width"]),
            str(row["height"]),
            str(row["device_scale_factor"]),
            "yes" if row["mobile"] else "no",
        )
    console_obj = Console()
    with console_obj.capture() as cap:
        console_obj.print(table)
    output.emit(rows, table=cap.get().rstrip("\n"))


def _read_clipboard() -> str | None:
    """Best-effort read of the OS clipboard (so 'Copy element' → translate just works)."""
    import subprocess
    import sys

    cmd = {
        "win32": ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
        "darwin": ["pbpaste"],
    }.get(sys.platform, ["xclip", "-selection", "clipboard", "-o"])
    try:
        # creationflags: powershell/pbpaste are console apps; without this the
        # Windows shell-out flashes a black window (see session_client._NO_WINDOW).
        no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        return (
            subprocess.run(
                cmd, capture_output=True, text=True, timeout=5, creationflags=no_window
            ).stdout
            or None
        )
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
def doctor(
    engine: str = typer.Option("chrome", "--engine", "-e", help="chrome|edge|firefox|edge_ie."),
    remote_url: str = typer.Option(
        None,
        "--remote-url",
        help="Selenium Grid / Remote WebDriver URL, e.g. http://grid:4444/wd/hub.",
    ),
    headless: bool = typer.Option(True, "--headless/--headed"),
) -> None:
    """Check that a browser + driver launch correctly (locally or on a Grid).

    The first command to run when anything is wrong. On failure it exits 1 with a
    message that names the engine, the endpoint and the most likely cause — never
    a raw driver traceback.
    """
    from visus.web.cli import output

    if engine == "edge_ie" and headless:
        output.emit_error(
            "edge_ie is always headed (IE mode has no headless driver) — "
            "run `visus doctor --engine edge_ie --headed`"
        )
    where = remote_url or "a locally launched browser"
    try:
        with launch(Engine.from_str(engine), headless=headless, remote_url=remote_url) as b:
            p = b.new_page()
            p.goto("data:text/html,<title>ok</title>")
            output.emit(f"OK: {engine} via {where} launches and navigates (title: {p.title()!r})")
    except Exception as exc:  # noqa: BLE001 — every failure is reported, none escapes
        detail = f"{type(exc).__name__}: {exc}"
        hints = [f"FAILED: {engine} via {where} — {detail}"]
        if remote_url:
            hints.append(
                f"  - is {remote_url} reachable from this machine? "
                "try `curl <url>/status` (a Grid answers with JSON)"
            )
            hints.append(
                f"  - does the Grid have a free {engine} node? "
                "check the Grid console's browser capacity"
            )
            hints.append("  - drop --remote-url to test the same engine locally")
        elif engine == "edge_ie":
            from visus.web.backends.browsers import _ie_preflight

            if not _ie_preflight.ie_mode_enabled():
                hints.append("  - " + _ie_preflight.admin_hint().replace("\n", "\n    "))
            else:
                hints.append(
                    "  - IE mode is enabled; close ALL Edge windows and retry, and pin "
                    "the driver with VISUS_WEB_IE_DRIVER_VERSION=4.0.0"
                )
        else:
            hints.append("  - run `visus install --engine " + engine + "` to fetch the driver")
        output.emit_error("\n".join(hints))


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
        # The BARE `--skills` is legal because `_entry.cli_main` normalises argv
        # (`skills.normalize_skills_argv`) before Click parses it — Typer has no
        # optional-value option, so the entry point supplies one.
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


def _session_screenshot(
    *,
    output_path: str,
    full_page: bool,
    hires: bool,
    index: int | None,
    selector: str | None,
    role: str | None,
    name: str | None,
    text: str | None,
) -> None:
    """Screenshot the LIVE session's page (or one element) and print the path.

    Shared by `visus screenshot` (no URL) and the deprecated
    `visus session-screenshot`, so the two can never drift apart.
    """
    # Resolve the path against the CLIENT's cwd (not the daemon's) so the PNG
    # lands where the user invoked the command, not under the daemon's base dir.
    args: dict[str, Any] = {"path": output.resolve_out(output_path), "full_page": full_page}
    if hires:
        args["hires"] = True  # only sent when asked, so the payload stays minimal
    if index is not None or selector or role or text:
        args.update(_target_args(index, selector, role, name, text))
    result = _send("screenshot", args)
    output.emit(result, table=f"saved {result}")


def _session_pdf(*, output_path: str) -> None:
    """Print the LIVE session's page to a PDF and print the path."""
    result = _send("pdf", {"path": output.resolve_out(output_path)})
    output.emit(result, table=f"saved {result}")


@app.command()
def screenshot(
    url: str = typer.Argument(
        None, help="URL for a one-off browser. Omit it to shoot the LIVE session."
    ),
    input_path: str = typer.Option("screenshot.png", "-o", "--output"),
    full_page: bool = False,
    headless: bool = True,
    engine: str = "chrome",
    hires: bool = typer.Option(
        False, "--hires", help="Session only: capture at device-pixel-ratio 2."
    ),
    index: int = typer.Option(None, "--index", "-i", help="Session only: field index to shoot."),
    selector: str = typer.Option(None, "--selector", "-s", help="Session only."),
    role: str = typer.Option(None, "--role", help="Session only."),
    name: str = typer.Option(None, "--name", help="Session only."),
    text: str = typer.Option(None, "--text", help="Session only."),
) -> None:
    """Screenshot to a PNG. With a URL: a one-off browser. Without: the live session."""
    if url is None:
        _session_screenshot(
            output_path=input_path,
            full_page=full_page,
            hires=hires,
            index=index,
            selector=selector,
            role=role,
            name=name,
            text=text,
        )
        return
    dest = output.resolve_out(input_path)
    with launch(Engine.from_str(engine), headless=headless) as b:
        p = b.new_page()
        p.goto(url)
        p.screenshot(path=dest, full_page=full_page)
    output.emit(dest, table=f"saved {dest}")


@app.command()
def pdf(
    url: str = typer.Argument(
        None, help="URL for a one-off browser. Omit it to print the LIVE session."
    ),
    input_path: str = typer.Option("page.pdf", "-o", "--output"),
    engine: str = "chrome",
) -> None:
    """Print to a PDF (Chromium). With a URL: a one-off browser. Without: the live session."""
    if url is None:
        _session_pdf(output_path=input_path)
        return
    dest = output.resolve_out(input_path)
    with launch(Engine.from_str(engine), headless=True) as b:
        p = b.new_page()
        p.goto(url)
        p.pdf(path=dest)
    output.emit(dest, table=f"saved {dest}")


@app.command()
def open(  # noqa: A001
    url: str = typer.Argument(..., help="URL to open."),
    engine: str = typer.Option(None, "--engine", "-e", help="chrome | edge | firefox (new session only)."),
    wait: bool = typer.Option(
        False, "--wait", help="Old behaviour: a one-off headed browser, closed when you press Enter."
    ),
) -> None:
    """Open URL in the session (starting it if needed) and print the page, numbered.

    The browser stays open across commands — act on it with `click 4`, `fill 2 …`.
    One command opens the page AND shows what is on it, which is what an agent needs
    next; `--wait` keeps the old press-Enter-to-close browser.
    """
    if wait:
        with launch(Engine.from_str(engine or "chrome"), headless=False) as b:
            b.new_page().goto(url)
            typer.echo("Browser open. Press Enter to close...")
            input()
        return

    from visus.web.cli import config as cliconfig
    from visus.web.cli import session_client

    if session_client.status() is None:
        cfg = cliconfig.active()
        try:
            session_client.start_daemon(engine or cfg.engine or "chrome", bool(cfg.headless), url)
        except session_client.SessionError as exc:
            output.emit_error(f"error: {exc}")
    else:
        _send("goto", {"url": url})
    _emit_page()


@app.command("batch")
def batch(
    actions_json: str = typer.Argument(
        ..., metavar="ACTIONS_JSON", help='JSON list of commands: [["fill","0","ada"],["click","2"]].'
    ),
) -> None:
    """Run several commands in one call, in order, stopping at the first failure.

    Each item is a command's own argv. If any of them can change the page, the page's
    numbered list is printed ONCE at the end — after a failure too, since it is what
    the next attempt is chosen from. One call fills a whole form and shows the result.
    """
    import click

    global _IN_BATCH
    try:
        actions = _json.loads(actions_json)
    except ValueError:
        actions = None
    well_formed = isinstance(actions, list) and all(
        isinstance(a, list) and a and all(isinstance(x, str) for x in a) for a in actions
    )
    if not well_formed:
        output.emit_error(f"error: {_BATCH_USAGE}", code=2)
    if any(a[0] == "batch" for a in actions):
        output.emit_error("error: batch dentro de batch não é permitido", code=2)

    failed: tuple[int, str] | None = None
    changed = False
    _IN_BATCH = True
    try:
        for n, action in enumerate(actions, start=1):
            changed = changed or action[0] in _PAGE_CHANGING
            try:
                # Com standalone_mode=False o click DEVOLVE o código de um Exit em vez de levantar
                rc = app(args=action, prog_name="visus", standalone_mode=False)
                if isinstance(rc, int) and rc != 0:
                    failed = (n, action[0])
            except click.exceptions.Exit as exc:
                if exc.exit_code:
                    failed = (n, action[0])
            except click.ClickException as exc:  # uso errado: opção desconhecida, argumento faltando
                exc.show()
                failed = (n, action[0])
            if failed:
                break
    finally:
        _IN_BATCH = False

    if failed:
        typer.echo(f"falhou na ação {failed[0]} ({failed[1]})", err=True)
    if changed:
        _emit_page()
    if failed:
        raise typer.Exit(1)


@app.command("text")
def page_text(
    max_chars: int = typer.Option(6000, "--max-chars", help="Cut the text after this many characters."),
) -> None:
    """Print the page's visible text (no JavaScript eval)."""
    content = str(_send("get_text", _target_args(None, "body", None, None, None)) or "")
    if len(content) > max_chars:
        content = f"{content[:max_chars]}\n… {len(content) - max_chars} more characters"
    output.emit({"text": content}, table=content)


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
        dest = Path(output.resolve_out(input_path))
        dest.write_text(code, encoding="utf-8")
        output.emit(code, table=f"saved {dest}")
    else:
        output.emit(code, table=code)


# ---------------------------------------------------------------------------
# Tracing & reports
# ---------------------------------------------------------------------------


@app.command("tracing-start")
def tracing_start(
    output_zip: str = typer.Option("run.zip", "-o", "--output", help="Where to write the trace."),
    screenshots: bool = typer.Option(
        True, "--screenshots/--no-screenshots", help="Capture a PNG per action (held in memory)."
    ),
) -> None:
    """Record every session action into a trace (stop with `visus tracing-stop`)."""
    # Resolve against the CLIENT's cwd — the daemon's may differ.
    result = _send(
        "tracing_start",
        {"zip_path": str(Path(output_zip).resolve()), "screenshots": screenshots},
    )
    output.emit(result, table=f"tracing run {result['run_id']} → {result['zip_path']}")


@app.command("tracing-stop")
def tracing_stop(
    output_zip: str = typer.Option(
        None, "-o", "--output", help="Override the path chosen at tracing-start."
    ),
    report_html: str = typer.Option(
        None, "--report", help="Also render a single-file HTML report to this path."
    ),
) -> None:
    """Stop recording, write the trace zip (and optionally the HTML report)."""
    args: dict[str, Any] = {"report": str(Path(report_html).resolve()) if report_html else None}
    if output_zip:
        args["zip_path"] = str(Path(output_zip).resolve())
    result = _send("tracing_stop", args)
    lines = [
        f"tracing run {result['run_id']} stopped: "
        f"{result['actions']} action(s), {result['failures']} failure(s)",
        f"trace  : {result.get('zip', '')}",
    ]
    if result.get("report"):
        lines.append(f"report : {result['report']}")
    output.emit(result, table="\n".join(lines))


@app.command()
def report(
    trace_zip: str = typer.Argument(..., help="A trace written by `visus tracing-stop`."),
    output_html: str = typer.Option("report.html", "-o", "--output"),
) -> None:
    """Render a self-contained HTML report from a trace zip (no session needed)."""
    from visus.web import tracing

    path = tracing.render_report(
        str(Path(trace_zip).resolve()), str(Path(output_html).resolve())
    )
    output.emit(path, table=f"saved {path}")


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


# Inside `batch` the page is printed once, at the end — not after every action
_IN_BATCH = False

# Commands after which the page may be a different one: a batch that ran any of
# them ends with the page's new numbered list
_PAGE_CHANGING = frozenset({
    "click", "dblclick", "hover", "check", "uncheck", "clear-input", "fill", "type",
    "press", "select", "upload", "drag", "goto", "open", "back", "forward", "reload",
    "tab", "tab-new", "tab-close", "tab-activate", "dialog",
})

_BATCH_USAGE = (
    'batch espera uma lista JSON de comandos, cada um uma lista de strings: '
    '[["fill","0","ada@empresa.com"],["fill","1","segredo"],["click","2"]]'
)


def _emit_page(kinds: list[str] | None = None, *, dom: bool = False) -> None:
    """The page as an agent reads it: settled field list, then title and URL."""
    from visus.web.cli.compact import format_compact, settle

    def fetch() -> list[dict[str, Any]]:
        args = {"kinds": kinds, "include_hidden": False, "highlight": False, "boxes": False}
        return list(_send("list_fields", args).get("fields", []))

    # Ler a lista é o que dá números às próximas ações (o daemon guarda a última):
    # dentro de um batch ela é lida assim mesmo, só não é impressa
    fields = settle(fetch)
    if _IN_BATCH:
        return
    page_title, page_url = str(_send("title") or ""), str(_send("url") or "")
    output.emit(
        {"title": page_title, "url": page_url, "fields": fields},
        table=format_compact(fields, title=page_title, url=page_url, dom=dom),
    )


def _format_fields(
    fields: list[dict[str, Any]], *, full: bool = False, boxes: bool = False
) -> str:
    from visus.web.cli.console import format_fields

    return format_fields(fields, full=full, boxes=boxes)


def _format_snapshot(elements: list[dict[str, Any]], *, boxes: bool = False) -> str:
    """Render snapshot rows as a REF/ROLE/NAME table (REF = a list-fields index)."""
    from rich import box as rich_box
    from rich.console import Console
    from rich.table import Table

    from visus.web.cli.console import _box_cell

    table = Table(box=rich_box.ASCII, header_style="bold", pad_edge=False)
    table.add_column("REF", justify="right", no_wrap=True)
    table.add_column("ROLE", no_wrap=True)
    table.add_column("NAME", overflow="fold")
    if boxes:
        table.add_column("BOX x,y,w,h", no_wrap=True)
    for e in elements:
        ref = e.get("ref")
        cells = ["-" if ref is None else str(ref), str(e.get("role", "")),
                 str(e.get("name", ""))]
        if boxes:
            cells.append(_box_cell(e.get("box")))
        table.add_row(*cells)
    console_obj = Console()
    with console_obj.capture() as cap:
        console_obj.print(table)
    return cap.get().rstrip("\n")


def _format_find(result: dict[str, Any]) -> str:
    """Render `find` output grep-style: `>` marks a hit, `--` separates groups."""
    rows = result.get("rows", [])
    if not rows:
        return f"no match for {result.get('query', '')!r} in {result.get('total', 0)} rows"
    lines = [f"{result.get('matched', 0)} of {result.get('total', 0)} rows "
             f"match {result.get('query', '')!r}"]
    prev: int | None = None
    for r in rows:
        if prev is not None and r["line"] != prev + 1:
            lines.append("--")
        prev = r["line"]
        mark = ">" if r.get("match") else " "
        ref = "-" if r.get("ref") is None else str(r["ref"])
        lines.append(f"{mark} {ref:>4}  {str(r.get('role', '')):<12} {r.get('name', '')}")
    return "\n".join(lines)


def _render_value(result: Any) -> str:
    from visus.web.cli.console import render_value

    return render_value(result)


# Module-level singletons (B008: a typer.Option() call cannot be an inline
# default when it is shared across commands; reading it from a module variable
# is the fix — same pattern as _UPLOAD_PATHS_ARG).
_MOBILE_OPT = typer.Option(
    False, "--mobile", help="Shorthand for --device 'iPhone 15' (see `visus devices`)."
)
_EXACT_OPT = typer.Option(False, "--exact", help="Match --role/--text exactly, not by substring.")
_FRAME_OPT = typer.Option(None, "--frame", help="CSS selector of the iframe holding the target.")
_NTH_OPT = typer.Option(
    None,
    "--nth",
    help="Pick one of several matches: 0 is the first, -1 the last. "
    "This is the way out of a 'resolved to N elements' error.",
)
# `--session` is a GROUP-level flag, so Click only accepts it before the
# subcommand. It reads as an option of the session subcommands themselves, which
# is where it gets typed first, so those repeat it locally.
_SESSION_OPT = typer.Option(
    None, "--session", "-S", help="Session name (default: 'default'). `-s` is --selector."
)


def _use_session(name: str | None) -> None:
    """Apply a subcommand-level ``--session`` on top of the group-level one."""
    if name is None:
        return
    from visus.web.cli import session_client

    try:
        session_client.set_session_name(name)
    except session_client.SessionError as exc:
        output.emit_error(f"error: {exc}")
_BUTTON_OPT = typer.Option(
    "left", "--button", "-b", help="Mouse button: left (default), middle or right."
)


def _positional(target: str | None, selector: str | None) -> tuple[int | None, str | None]:
    """Fold a bare positional target into ``(index, selector)``.

    ALL DIGITS is a `list-fields` index; ANYTHING ELSE is a selector, so
    `visus click "#submit"` works — the spelling every other browser CLI uses and
    the one a model reaches for first. The rule cannot be ambiguous because a CSS
    or XPath selector is never all digits.

    Before this, the slot was typed `index: int` and the natural form died in the
    PARSER ("'#submit' is not a valid int") before any code could explain itself.

    An explicit ``--selector`` wins, so a stray positional never silently
    overrides a target the caller spelled out.
    """
    if target is None:
        return None, selector
    if target.isdigit():
        return int(target), selector
    return None, selector or target


def _index_or_value(
    target: str | None, value: str | None, has_option_target: bool
) -> tuple[int | None, str | None, str | None]:
    """Split leading positionals into ``(index, selector, value)``.

    For the commands that take a target AND a value (`fill`, `select`, `press`,
    `expect-text`). Three natural spellings all have to work::

        visus fill 7 hello              # index, value
        visus fill "#user" hello        # selector, value  (the playwright shape)
        visus fill -s "#user" hello     # option target, value

    The last one is why the slot is a string: with a typed `int` it was a parse
    error. When an option target is present a LONE positional is the VALUE —
    otherwise `-s "#u" hello` would read "hello" as a selector.
    """
    if target is None:
        return None, None, value
    if has_option_target:
        if value is None:
            return None, None, target
        if not target.isdigit():
            # `visus fill -s "#u" "#v" hello` names two elements. Dropping one
            # silently is the worst outcome: the command succeeds against an
            # element the caller never asked for.
            output.emit_error(
                f"error: two targets — {target!r} and the --selector/--role/--text option.\n"
                "Use one: `visus <cmd> <TARGET> <value>` or `visus <cmd> -s <sel> <value>`."
            )
        return int(target), None, value
    if value is None:
        # One positional and nothing else. A NUMBER is still a target, so
        # `visus fill 2` reports the missing text rather than a missing target;
        # anything else is the value (`visus press Enter`).
        if target.isdigit():
            return int(target), None, None
        return None, None, target
    index, selector = _positional(target, None)
    return index, selector, value


def _target_args(
    index: int | None,
    selector: str | None,
    role: str | None,
    name: str | None,
    text: str | None,
    *,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> dict[str, Any]:
    """Build the {index|selector|role|name|text} target dict for an action op.

    ``exact``, ``frame`` and ``nth`` are only sent when set: the daemon reads
    them in ``session_server.make_locator`` and the defaults would otherwise pad
    every payload.
    """
    if index is not None:
        args: dict[str, Any] = {"index": index}
    elif not (selector or role or text):
        output.emit_error(
            "error: no target. Use one of:\n"
            '  visus <cmd> "#id"                a CSS, XPath or text= selector\n'
            "  visus <cmd> <INDEX>              a number from `visus list-fields`\n"
            "  visus <cmd> --selector '#id'     the same thing, spelled long\n"
            "  visus <cmd> --role button        an ARIA role (--name refines it)\n"
            "  visus <cmd> --text 'Sign in'     the element's visible text\n"
            "--name alone is NOT a target; it only qualifies --role.\n"
            "QUOTE the selector: an unquoted #id is a COMMENT in PowerShell and in\n"
            "bash alike, so the shell deletes it before visus ever sees it.\n"
            "Run `visus list-fields` to see what is on the page."
        )
    else:
        args = {"selector": selector, "role": role, "name": name, "target_text": text}
    if exact:
        args["exact"] = True
    if frame is not None:
        args["frame"] = frame
    if nth is not None:
        args["nth"] = nth
    return args


@session_app.command("start")
def session_start(
    ctx: typer.Context,
    url: str = typer.Argument(None, help="URL to open once the browser starts."),
    session: str = _SESSION_OPT,
    engine: str = typer.Option(
        "chrome", "--engine", "-e", "--browser", help="chrome | edge | firefox | edge_ie."
    ),
    headless: bool = typer.Option(
        False,
        "--headless/--headed",
        help="Run headless (default: headed). --headed is accepted and is the default.",
    ),
    user_data_dir: str = typer.Option(
        None,
        "--user-data-dir",
        help="Reuse a persistent browser profile — cookies and logins survive runs.",
    ),
    persistent: bool = typer.Option(
        False,
        "--persistent",
        help="Keep the profile in .visus/profiles/<session> so logins survive runs.",
    ),
    profile: str = typer.Option(
        None, "--profile", help="Alias of --user-data-dir: a profile directory you own."
    ),
    device: str = typer.Option(
        None, "--device", help="Emulate a device viewport (see `visus devices`)."
    ),
    mobile: bool = _MOBILE_OPT,
    remote_url: str = typer.Option(
        None,
        "--remote-url",
        help="Drive a Selenium Grid / Remote WebDriver, e.g. http://grid:4444/wd/hub.",
    ),
    slow_mo: int = typer.Option(
        0, "--slow-mo", help="Delay every action by this many milliseconds."
    ),
    allow_run_code: bool = typer.Option(
        False,
        "--allow-run-code",
        help="Allow `visus run-code` to execute Python against this live session.",
    ),
    idle_timeout: float = typer.Option(
        None,
        "--idle-timeout",
        help="Stop the daemon after N seconds with no command (omit = never).",
    ),
) -> None:
    """Start a persistent browser session (detached daemon)."""
    from visus.web.api.devices import DEFAULT_MOBILE, get_device
    from visus.web.cli import config as cliconfig
    from visus.web.cli import session_client

    _use_session(session)

    # The config supplies DEFAULTS only: is_default asks click where each value
    # came from, so anything the user actually typed is left untouched.
    cfg = cliconfig.active()
    if cliconfig.is_default(ctx, "engine") and cfg.engine:
        engine = cfg.engine
    if cliconfig.is_default(ctx, "headless") and cfg.headless is not None:
        headless = cfg.headless
    if cliconfig.is_default(ctx, "url") and cfg.url:
        url = cfg.url
    if cliconfig.is_default(ctx, "device") and cfg.device:
        device = cfg.device
    if cliconfig.is_default(ctx, "persistent") and cfg.persistent is not None:
        persistent = cfg.persistent
    if cliconfig.is_default(ctx, "user_data_dir") and cfg.user_data_dir:
        user_data_dir = cfg.user_data_dir
    if cliconfig.is_default(ctx, "remote_url") and cfg.remote_url:
        remote_url = cfg.remote_url
    if cliconfig.is_default(ctx, "slow_mo") and cfg.slow_mo is not None:
        slow_mo = cfg.slow_mo
    if cliconfig.is_default(ctx, "idle_timeout") and cfg.idle_timeout is not None:
        idle_timeout = cfg.idle_timeout
    if cliconfig.is_default(ctx, "allow_run_code") and cfg.allow_run_code is not None:
        allow_run_code = cfg.allow_run_code

    chosen = [flag for flag, on in (("--persistent", persistent), ("--profile", profile)) if on]
    if user_data_dir and chosen:
        output.emit_error(f"pass --user-data-dir or {chosen[0]}, not both")
    if persistent and profile:
        output.emit_error("pass --persistent or --profile, not both")
    if persistent:
        # The same directory `visus session delete-data` is entitled to remove.
        user_data_dir = str(session_client.profile_dir())
    elif profile:
        user_data_dir = profile

    if mobile and not device:
        device = DEFAULT_MOBILE
    if device:
        try:
            get_device(device)  # fail here, not on the daemon's first action
        except ValueError as exc:
            output.emit_error(str(exc))
        if engine not in ("chrome", "edge"):
            output.emit_error(
                f"device emulation is a CDP feature — it needs chrome or edge, not {engine!r}"
            )

    try:
        info = session_client.start_daemon(
            engine,
            headless,
            url,
            device=device,
            user_data_dir=user_data_dir,
            remote_url=remote_url,
            slow_mo=slow_mo,
            allow_run_code=allow_run_code,
            idle_timeout=idle_timeout,
        )
    except session_client.SessionError as exc:
        output.emit_error(f"error: {exc}")
    output.emit(
        info,
        table=f"session started (pid {info['pid']}, port {info['port']}, engine {engine})",
    )


@session_app.command("stop")
def session_stop(session: str = _SESSION_OPT) -> None:
    """Stop the running session (closes the browser)."""
    from visus.web.cli import session_client

    _use_session(session)
    output.emit(session_client.stop())


def _cdp_address(raw: str) -> str:
    """Normalise ``--cdp`` to ``host:port``.

    A container or `chrome://inspect` prints ``http://localhost:9222``; Selenium's
    ``debuggerAddress`` wants the bare authority, so both forms are accepted.
    """
    value = raw.strip()
    for prefix in ("http://", "https://", "ws://", "wss://"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    return value.rstrip("/")


@session_app.command("attach")
def session_attach(
    cdp: str = typer.Option(
        ..., "--cdp", help="DevTools address, e.g. 127.0.0.1:9222 or http://localhost:9222."
    ),
    url: str = typer.Argument(None, help="Optional URL to navigate the attached tab to."),
    engine: str = typer.Option("chrome", "--engine", "-e", help="chrome | edge."),
) -> None:
    """Attach the session to a browser that is ALREADY running (chrome/edge).

    Start the target browser with remote debugging enabled — in Chrome/Edge,
    visit `chrome://inspect/#remote-debugging` and tick "Allow remote debugging
    for this browser instance", or launch it with `--remote-debugging-port=9222`.

    The session name comes from `--session` / `-S` / `VISUS_WEB_SESSION`, exactly
    as it does for `session start`. End it with `visus session detach` — a plain
    `stop` would close a window that is not yours to close.
    """
    from visus.web.cli import output, session_client

    if engine not in ("chrome", "edge"):
        output.emit_error(
            f"attaching needs chrome or edge, not {engine!r} — no other engine "
            "exposes the Chrome DevTools Protocol"
        )
    try:
        info = session_client.start_daemon(
            engine, False, url, debugger_address=_cdp_address(cdp)
        )
    except session_client.SessionError as exc:
        output.emit_error(str(exc))
    output.emit(
        info,
        table=(
            f"attached to {_cdp_address(cdp)} "
            f"(pid {info['pid']}, port {info['port']}, engine {engine})"
        ),
    )


@session_app.command("detach")
def session_detach() -> None:
    """End an attached session, leaving the browser open (`attach` sessions only)."""
    from visus.web.cli import output

    output.emit(_send("detach", {}))


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
    session: str = _SESSION_OPT,
) -> None:
    """Show the running session's status."""
    from visus.web.cli import session_client

    _use_session(session)
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


@session_app.command("list")
def session_list() -> None:
    """List every session — this project's and any left running in other projects."""
    from visus.web.cli import output, session_client

    rows = session_client.list_sessions()
    if not rows:
        output.emit([], table="no sessions")
        return
    from rich import box
    from rich.console import Console
    from rich.table import Table

    table = Table(box=box.ASCII, header_style="bold", pad_edge=False)
    for column in ("NAME", "SCOPE", "STATE", "PID", "PORT", "ENGINE", "URL", "DIR"):
        table.add_column(column, overflow="fold", no_wrap=column in ("NAME", "STATE"))
    for row in rows:
        table.add_row(
            str(row["name"]),
            str(row["scope"]),
            "live" if row["live"] else "dead",
            str(row["pid"]),
            str(row["port"]),
            str(row.get("engine") or ""),
            str(row.get("url") or ""),
            str(row["cwd"]),
        )
    console_obj = Console()
    with console_obj.capture() as cap:
        console_obj.print(table)
    output.emit(rows, table=cap.get().rstrip("\n"))


@session_app.command("close-all")
def session_close_all() -> None:
    """Shut down every live session, in this project and in any other."""
    from visus.web.cli import output, session_client

    output.emit(session_client.close_all())


@session_app.command("kill-all")
def session_kill_all() -> None:
    """Force-kill every session daemon and delete all session state.

    The escape hatch when `close-all` cannot authenticate: it needs no token and
    also sweeps state left by a visus older than named sessions.
    """
    from visus.web.cli import output, session_client

    output.emit(session_client.kill_all())


@session_app.command("delete-data")
def session_delete_data() -> None:
    """Delete this session's persistent browser profile (`--persistent`)."""
    from visus.web.cli import output, session_client

    try:
        output.emit(session_client.delete_data())
    except session_client.SessionError as exc:
        output.emit_error(str(exc))


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
    highlight: bool = typer.Option(
        False,
        "--highlight/--no-highlight",
        help="Draw the numbered overlay on the page (off by default: it injects "
        "divs that would show up in a later screenshot / OCR / template match).",
    ),
    full: bool = typer.Option(False, "--full", help="Also print the CSS and XPATH columns."),
    boxes: bool = typer.Option(False, "--boxes", help="Include each field's viewport rect."),
    compact: bool = typer.Option(
        False, "--compact", help="One line per field — the form an AI agent reads cheapest."
    ),
    dom: bool = typer.Option(
        False, "--dom", help="With --compact: also each element's opening tag (id, class, name…)."
    ),
) -> None:
    """Enumerate interactive fields on the current page (numbered, highlighted)."""
    kinds = [k.strip() for k in kind.split(",") if k.strip()] if kind else None
    if compact:
        _emit_page(kinds, dom=dom)
        return
    result = _send(
        "list_fields",
        {
            "kinds": kinds,
            "include_hidden": show_all,
            "highlight": highlight,
            "boxes": boxes,
        },
    )
    fields = result.get("fields", [])
    if as_json:
        output.set_mode(as_json=True)
    output.emit(fields, table=_format_fields(fields, full=full, boxes=boxes))


@app.command()
def click(
    target: str = _TARGET_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    image: str = typer.Option(
        None, "--image", help="Click the centre of this template PNG (needs the [vision] extra)."
    ),
    ocr_text: str = typer.Option(
        None,
        "--ocr-text",
        help="Click rendered text found by OCR (needs the [vision] extra).",
    ),
    confidence: float = typer.Option(0.8, "--confidence", "-c", help="Match threshold (0-1)."),
    button: str = _BUTTON_OPT,
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """Click an element: `visus click "#submit"`, `visus click 4`, or --image/--ocr-text."""
    index, sel = _positional(target, selector)
    if ocr_text is not None:
        ocr_args: dict[str, Any] = {"ocr_text": ocr_text, "exact_text": False}
        if index is not None or selector or role or text:
            ocr_args.update(_target_args(index, sel, role, name, text, nth=nth))
        env = _send_env("click_ocr_text", ocr_args)
        r = env["result"]
        message = (
            f"clicked text {r['text']!r} at ({r['x']}, {r['y']}) "
            f"confidence={r['confidence']:.3f}"
        )
        output.emit_envelope({**env, "result": message})
        return
    if image is not None:
        image_args: dict[str, Any] = {
            "template_path": str(Path(image).resolve()),
            "confidence": confidence,
        }
        if index is not None or selector or role or text:
            image_args.update(_target_args(index, sel, role, name, text, nth=nth))
        env = _send_env("click_image", image_args)
        r = env["result"]
        message = f"clicked image at ({r['x']}, {r['y']}) confidence={r['confidence']:.3f}"
        output.emit_envelope({**env, "result": message})
        return
    args = _target_args(index, sel, role, name, text, exact=exact, frame=frame, nth=nth)
    if button != "left":
        # A pixel click always uses the primary button, so this stays in the
        # NON-image branch.
        args["button"] = button  # keep the default payload minimal
    output.emit_envelope(_send_env("click", args))


@app.command()
def fill(
    target: str = typer.Argument(
        None,
        help="Field index from the last list-fields (a plain number), or the value "
        "itself when a --selector/--role/--text target is given.",
    ),
    text: str = typer.Argument(None, help="Text to fill, e.g. `visus fill 7 hello`."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    by_text: str = typer.Option(None, "--text", help="Target a field by its visible text."),
    value: str = typer.Option(
        None, "--value", help="Text to fill when targeting by --selector/--role/--text."
    ),
    submit: bool = typer.Option(
        False, "--submit", help="Press Enter after filling (submits most forms)."
    ),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """Fill a field: `visus fill 7 hello`, `visus fill "#u" hello`, or `-s "#u" hello`."""
    index, pos_selector, positional = _index_or_value(
        target, text, bool(selector or role or by_text)
    )
    args = _target_args(
        index, selector or pos_selector, role, name, by_text, exact=exact, frame=frame, nth=nth
    )
    fill_value = positional if positional is not None else value
    if fill_value is None:
        output.emit_error("error: no text to fill — use `visus fill <index> <text>` or `--value`")
    args["text"] = fill_value
    if submit:
        args["submit"] = True  # only sent when asked, so the payload stays minimal
    output.emit_envelope(_send_env("fill", args))


@app.command()
def check(
    target: str = _TARGET_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """Check a checkbox/radio field."""
    index, sel = _positional(target, selector)
    args = _target_args(index, sel, role, name, None, exact=exact, frame=frame, nth=nth)
    output.emit_envelope(_send_env("check", args))


@app.command()
def uncheck(
    target: str = _TARGET_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """Uncheck a checkbox field."""
    index, sel = _positional(target, selector)
    args = _target_args(index, sel, role, name, None, exact=exact, frame=frame, nth=nth)
    output.emit_envelope(_send_env("uncheck", args))


@app.command()
def select(
    target: str = typer.Argument(
        None,
        help="Field index from the last list-fields (a plain number), or the value "
        "itself when a --selector/--role/--text target is given.",
    ),
    value: str = typer.Argument(None, help="Option value, e.g. `visus select 5 US`."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    by_text: str = typer.Option(None, "--text", help="Target a field by its visible text."),
    option_value: str = typer.Option(
        None, "--value", help="Option value when targeting by --selector/--role/--text."
    ),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """Select an option: `visus select 5 US` or `visus select "#country" US`."""
    index, pos_selector, positional = _index_or_value(
        target, value, bool(selector or role or by_text)
    )
    args = _target_args(
        index, selector or pos_selector, role, name, by_text, exact=exact, frame=frame, nth=nth
    )
    val = positional if positional is not None else option_value
    if val is None:
        output.emit_error(
            "error: no option value — use `visus select <index> <value>` or `--value`"
        )
    args["value"] = val
    output.emit_envelope(_send_env("select", args))


@app.command()
def press(
    target: str = typer.Argument(
        None, help="Field index, OR the key itself for a page-level press."
    ),
    key: str = typer.Argument(None, help="Key to press when the first argument is an index."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    by_text: str = typer.Option(None, "--text", help="Target a field by its visible text."),
    key_value: str = typer.Option(
        None, "--key", help="Key when targeting by --selector/--role/--text."
    ),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """Press a key: `visus press 7 Enter`, `visus press "#q" Enter`, or `visus press Enter`."""
    has_option_target = bool(selector or role or by_text)
    index, pos_selector, k = _index_or_value(target, key, has_option_target)
    if k is None:
        k = key_value
    if k is None:
        output.emit_error(
            "error: no key — use `visus press <index> <key>`, `--key`, or `visus press <key>`"
        )
    if index is None and not (has_option_target or pos_selector):
        output.emit_envelope(_send_env("press", {"key": k}))
        return
    args = _target_args(
        index, selector or pos_selector, role, name, by_text, exact=exact, frame=frame, nth=nth
    )
    args["key"] = k
    output.emit_envelope(_send_env("press", args))


@app.command("type")
def type_text(
    first: str = typer.Argument(
        ..., metavar="[TARGET] TEXT", help="Text to type — or a target, then the text."
    ),
    second: str = typer.Argument(None, hidden=True),
    index: int = typer.Option(None, "--index", "-i", help="Focus this field first."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    by_text: str = typer.Option(None, "--text", help="Target a field by its visible text."),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """Type into the focused element, or into a target: `visus type "#q" hello`.

    A LONE positional is always the text — `visus type 42` types "42" rather than
    focusing field 42, because typing a number (a ZIP, an amount) is ordinary and
    a text argument was this command's only shape before. A target is what the
    SECOND positional makes of the first.
    """
    if second is None:
        text, pos_index, pos_selector = first, None, None
    else:
        text = second
        pos_index, pos_selector = _positional(first, None)
    args: dict[str, Any] = {"text": text}
    if pos_index is not None:
        index = pos_index
    if index is not None or selector or role or by_text or pos_selector:
        args.update(
            _target_args(
                index,
                selector or pos_selector,
                role,
                name,
                by_text,
                exact=exact,
                frame=frame,
                nth=nth,
            )
        )
    output.emit(_send("type", args))


@app.command()
def keydown(key: str = typer.Argument(..., help="Key to hold, e.g. Shift or Control.")) -> None:
    """Hold a key down until `visus keyup` releases it."""
    output.emit(_send("key_down", {"key": key}))


@app.command()
def keyup(key: str = typer.Argument(..., help="Key to release.")) -> None:
    """Release a key held by `visus keydown`."""
    output.emit(_send("key_up", {"key": key}))


# ---------------------------------------------------------------------------
# Mouse device (absolute viewport coordinates)
# ---------------------------------------------------------------------------


@app.command()
def mousemove(
    x: float = typer.Argument(..., help="Viewport X coordinate."),
    y: float = typer.Argument(..., help="Viewport Y coordinate."),
) -> None:
    """Move the pointer to absolute viewport coordinates."""
    output.emit(_send("mouse_move", {"x": x, "y": y}))


@app.command()
def mousedown(button: str = _BUTTON_OPT) -> None:
    """Hold a mouse button down at the current pointer position."""
    output.emit(_send("mouse_down", {"button": button}))


@app.command()
def mouseup(button: str = _BUTTON_OPT) -> None:
    """Release a mouse button held by `visus mousedown`."""
    output.emit(_send("mouse_up", {"button": button}))


@app.command()
def mousewheel(
    delta_x: float = typer.Argument(..., help="Horizontal scroll delta in pixels."),
    delta_y: float = typer.Argument(..., help="Vertical scroll delta in pixels."),
) -> None:
    """Scroll by a wheel delta at the current pointer position."""
    output.emit(_send("mouse_wheel", {"delta_x": delta_x, "delta_y": delta_y}))


@app.command()
def goto(url: str = typer.Argument(..., help="URL to navigate to.")) -> None:
    """Navigate the session's page to a URL."""
    env = _send_env("goto", {"url": url})
    output.emit_envelope(env, table=f"navigated to {env.get('result')}")


@app.command("get-text")
def get_text(
    target: str = _TARGET_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """Print a field's text content."""
    index, sel = _positional(target, selector)
    args = _target_args(index, sel, role, name, text, exact=exact, frame=frame, nth=nth)
    result = _send("get_text", args)
    output.emit(result, table=_render_value(result))


@app.command("session-screenshot")
def session_screenshot(
    input_path: str = typer.Option("screenshot.png", "-o", "--output"),
    full_page: bool = typer.Option(
        False, "--full-page", help="Capture the full scrollable page, not just the viewport."
    ),
    hires: bool = typer.Option(
        False, "--hires", help="Capture at device-pixel-ratio 2 (better for OCR / vision)."
    ),
    target: str = typer.Argument(
        None,
        metavar="[TARGET]",
        help='A `list-fields` index (7) or a selector ("#id", "//xpath") — omit = whole page.',
    ),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text", help="Target an element by its visible text."),
) -> None:
    """DEPRECATED alias for `visus screenshot` with no URL."""
    index, sel = _positional(target, selector)
    typer.echo(
        "warning: `visus session-screenshot` is deprecated — use `visus screenshot` "
        "(with no URL it shoots the live session).",
        err=True,
    )
    _session_screenshot(
        output_path=input_path,
        full_page=full_page,
        hires=hires,
        index=index,
        selector=sel,
        role=role,
        name=name,
        text=text,
    )


@app.command("session-pdf")
def session_pdf(
    output_file: str = typer.Option("page.pdf", "-o", "--output"),
) -> None:
    """DEPRECATED alias for `visus pdf` with no URL."""
    typer.echo(
        "warning: `visus session-pdf` is deprecated — use `visus pdf` "
        "(with no URL it prints the live session).",
        err=True,
    )
    _session_pdf(output_path=output_file)


@app.command("clear")
def clear_highlights() -> None:
    """Remove the numbered field-highlight overlay."""
    output.emit(_send("clear_highlights", {}))


@app.command()
def highlight(
    target: str = _TARGET_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    style: str = typer.Option(None, "--style", help='CSS border, e.g. "2px dashed #0a0".'),
    hide: bool = typer.Option(False, "--hide", help="Remove the box instead of drawing it."),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """Draw a highlight box around ONE element (`--hide` removes it)."""
    index, sel = _positional(target, selector)
    if hide:
        output.emit(_send("highlight", {"hide": True}))
        return
    args = _target_args(index, sel, role, name, text, exact=exact, frame=frame, nth=nth)
    if style:
        args["style"] = style
    output.emit(_send("highlight", args))


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
def resize(
    width: int = typer.Argument(..., help="Viewport width in CSS pixels."),
    height: int = typer.Argument(..., help="Viewport height in CSS pixels."),
) -> None:
    """Resize the session window so the viewport is exactly width × height."""
    result = _send("resize", {"width": width, "height": height})
    output.emit(result, table=f"viewport is now {result['width']}x{result['height']}")


@app.command()
def find(
    query: str = typer.Argument(..., help="Text to look for in the page snapshot."),
    regex: bool = typer.Option(
        False, "--regex", help="Treat QUERY as a Python regular expression."
    ),
    context: int = typer.Option(3, "--context", "-C", help="Rows of context around each hit."),
    selector: str = typer.Option(
        None, "--selector", "-s", help="Scope the search to a CSS selector."
    ),
    depth: int = typer.Option(
        None, "--depth", help="Keep only elements at most N levels below the scope root."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Search the page instead of snapshotting it — matching rows plus context.

    `visus find "Add to cart"` on a 400-element page returns a handful of rows
    with their REFs, so the next command is `visus click <REF>`.
    """
    result = _send(
        "find",
        {
            "query": query,
            "regex": regex,
            "context": context,
            "selector": selector,
            "depth": depth,
        },
    )
    if as_json:
        output.set_mode(as_json=True)
    output.emit(result, table=_format_find(result))


@app.command()
def snapshot(
    scope: str = typer.Argument(
        None, metavar="[SELECTOR]", help='Scope the snapshot to a CSS selector, e.g. "#main".'
    ),
    selector: str = typer.Option(
        None, "--selector", "-s", help="Same as the positional scope; every other command has it."
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
    boxes: bool = typer.Option(False, "--boxes", help="Include each element's viewport rect."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List the page's interactive elements as a REF/ROLE/NAME table.

    A REF is a `visus list-fields` index: `visus snapshot` then `visus click 4`
    works. Scope it (`visus snapshot "#main"`), cap it (`--depth 2`), or save it
    (`--filename after-login.yml`) when the page is large.
    """
    args: dict[str, Any] = {
        "selector": scope or selector,
        "depth": depth,
        "refs": refs,
        "boxes": boxes,
    }
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
    output.emit(elements, table=_format_snapshot(elements, boxes=boxes))


@app.command("get-attribute")
def get_attribute(
    attr_name: str = typer.Argument(..., help="Attribute name, e.g. `href`."),
    target: str = _TARGET_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """Print an element's attribute value."""
    index, sel = _positional(target, selector)
    args = _target_args(index, sel, role, name, text, exact=exact, frame=frame, nth=nth)
    args["attr_name"] = attr_name
    result = _send("get_attribute", args)
    output.emit(result, table=_render_value(result))


@app.command()
def count(
    target: str = _TARGET_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """Print how many elements match the target."""
    index, sel = _positional(target, selector)
    args = _target_args(index, sel, role, name, text, exact=exact, frame=frame, nth=nth)
    output.emit(_send("count", args))


@app.command("generate-locator")
def generate_locator(
    target: str = _TARGET_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    raw: bool = typer.Option(False, "--raw", help="Print only the expression."),
    nth: int = _NTH_OPT,
) -> None:
    """Print the copy-paste `visus.web` expression for one element."""
    index, sel = _positional(target, selector)
    result = _send(
        "generate_locator",
        _target_args(index, sel, role, name, text, exact=exact, frame=frame, nth=nth),
    )
    if raw:
        output.set_mode(raw=True)
    lines = [str(result.get("code", ""))]
    if result.get("css"):
        lines.append(f"css   : {result['css']}")
    if result.get("xpath"):
        lines.append(f"xpath : {result['xpath']}")
    # The value is a str, so `emit` drops the table under --raw all by itself and
    # this prints the expression alone.
    output.emit(result.get("code"), table="\n".join(lines))


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


@app.command()
def hover(
    target: str = _TARGET_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """Hover over a field by TARGET: `4`, `"#id"`, `//xpath`, `text=…`."""
    index, sel = _positional(target, selector)
    args = _target_args(index, sel, role, name, text, exact=exact, frame=frame, nth=nth)
    output.emit_envelope(_send_env("hover", args))


@app.command()
def dblclick(
    target: str = _TARGET_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    button: str = _BUTTON_OPT,
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """Double-click a field by TARGET: `4`, `"#id"`, `//xpath`, `text=…`."""
    index, sel = _positional(target, selector)
    args = _target_args(index, sel, role, name, text, exact=exact, frame=frame, nth=nth)
    if button != "left":
        args["button"] = button
    output.emit_envelope(_send_env("dblclick", args))


@app.command()
def focus(
    target: str = _TARGET_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """Focus a field by TARGET: `4`, `"#id"`, `//xpath`, `text=…`."""
    index, sel = _positional(target, selector)
    args = _target_args(index, sel, role, name, text, exact=exact, frame=frame, nth=nth)
    output.emit_envelope(_send_env("focus", args))


@app.command("clear-input")
def clear_input(
    target: str = _TARGET_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """Clear an input field's value (distinct from `clear`, which removes highlights)."""
    index, sel = _positional(target, selector)
    args = _target_args(index, sel, role, name, text, exact=exact, frame=frame, nth=nth)
    output.emit_envelope(_send_env("clear_input", args))


@app.command()
def drag(
    source: str = typer.Argument(
        None, metavar="[SOURCE]", help="Source: a `list-fields` index or a selector."
    ),
    dest: str = typer.Argument(
        None, metavar="[DEST]", help="Destination: a `list-fields` index or a selector."
    ),
    selector: str = typer.Option(None, "--selector", "-s", help="Source selector."),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    to_selector: str = typer.Option(None, "--to-selector", help="Target CSS/XPath selector."),
    to_index: int = typer.Option(None, "--to-index", help="Target field index."),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """Drag one element onto another: `visus drag 3 7` or `visus drag "#a" "#b"`."""
    index, sel = _positional(source, selector)
    target_index, target_selector = _positional(dest, None)
    args = _target_args(index, sel, role, name, text, exact=exact, frame=frame, nth=nth)
    if to_selector is not None:
        args["target_selector"] = to_selector
    elif to_index is not None:
        args["target_index"] = to_index
    elif target_selector is not None:
        args["target_selector"] = target_selector
    elif target_index is not None:
        args["target_index"] = target_index
    else:
        output.emit_error(
            "error: provide a drag target — `<target_index>`, --to-selector, or --to-index"
        )
    output.emit_envelope(_send_env("drag", args))


@app.command()
def drop(
    target: str = _TARGET_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    path: str = typer.Option(None, "--path", help="File to drop onto the target."),
    data: str = typer.Option(None, "--data", help="Text payload to drop instead of a file."),
    data_type: str = typer.Option(
        "text/plain", "--data-type", help="MIME type for --data (default text/plain)."
    ),
    nth: int = _NTH_OPT,
) -> None:
    """Drop a file or a payload onto an element from outside the page.

    For dropzones with no `<input type=file>`, which `visus upload` cannot reach::

        visus drop --selector "#zone" --path ./report.csv
        visus drop 4 --data '{"id":1}' --data-type application/json
    """
    index, sel = _positional(target, selector)
    import base64
    import mimetypes

    from visus.web.cli import output

    if path is None and data is None:
        output.emit_error("nothing to drop — pass --path <file> or --data <text>")
    if path is not None and data is not None:
        output.emit_error("pass --path or --data, not both")
    args = _target_args(index, sel, role, name, text, nth=nth)
    if path is not None:
        # Read on the CLIENT side so the path resolves against the user's cwd.
        source = Path(path)
        args["file"] = {
            "name": source.name,
            "type": mimetypes.guess_type(source.name)[0] or "application/octet-stream",
            "b64": base64.b64encode(source.read_bytes()).decode("ascii"),
        }
    else:
        args["data"] = data
        args["data_type"] = data_type
    result = _send("drop", args).get("dropped", {})
    output.emit(
        result,
        table=f"dropped {result.get('files', 0)} file(s), types {result.get('types', [])}",
    )


# Module-level singleton default (B008: a function call cannot be a mutable
# list-typed default inline; reading it from a module variable is the fix).
_UPLOAD_PATHS_ARG = typer.Argument(
    None,
    help="One or more file paths. A leading all-digits token is read as a field index.",
)


@app.command()
def upload(
    paths: list[str] = _UPLOAD_PATHS_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """Set file(s) on a file input.

    With no target visus finds the page's single `<input type=file>` — including
    one hidden behind a styled "Choose a file" button, which is the shape a file
    chooser normally hides::

        visus upload ./avatar.png
        visus upload 4 a.png b.png

    The index is not a separate typed argument: `index: int` first would make
    typer reject `visus upload ./a.png` as a bad integer before the body ever
    runs. A leading ALL-DIGITS token is the index instead — the same rule the
    REPL uses. Name a file called `2` with `--selector` or `./2`.
    """
    tokens = list(paths or [])
    index: int | None = None
    if tokens and tokens[0].isdigit():
        index = int(tokens[0])
        tokens = tokens[1:]
    if not tokens:
        output.emit_error("error: provide at least one file path to upload")
    args: dict[str, Any] = {}
    if index is not None or selector or role or text:
        args = _target_args(index, selector, role, name, text, exact=exact, frame=frame, nth=nth)
    # Resolve paths against the CLIENT's cwd so the daemon receives absolute paths.
    args["paths"] = [str(Path(p).resolve()) for p in tokens]
    output.emit_envelope(_send_env("upload", args))


# ---------------------------------------------------------------------------
# Wait / Expect
# ---------------------------------------------------------------------------


@app.command()
def wait(
    target: str = _TARGET_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    state: str = typer.Option("visible", "--state", help="visible|hidden|attached|detached."),
    timeout: int = typer.Option(None, "--timeout", help="Timeout in milliseconds."),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """Wait for an element to reach a state (visible/hidden)."""
    index, sel = _positional(target, selector)
    args = _target_args(index, sel, role, name, text, exact=exact, frame=frame, nth=nth)
    args["state"] = state
    if timeout is not None:
        args["timeout"] = timeout
    output.emit(_send("wait", args))


@app.command("expect-text")
def expect_text(
    target: str = typer.Argument(
        None,
        help="Field index from the last list-fields (a plain number), or the value "
        "itself when a --selector/--role/--text target is given.",
    ),
    expected: str = typer.Argument(None, help="The expected text."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    expected_text: str = typer.Option(
        None, "--expected", help="Expected text when targeting by --selector/--role/--text."
    ),
    timeout: int = typer.Option(None, "--timeout", help="Timeout in milliseconds."),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """Assert an element contains text: `expect-text 0 Hi` or `expect-text "#flash" Hi`."""
    index, pos_selector, positional = _index_or_value(
        target, expected, bool(selector or role or text)
    )
    args = _target_args(
        index, selector or pos_selector, role, name, text, exact=exact, frame=frame, nth=nth
    )
    want = positional if positional is not None else expected_text
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


@app.command("tab-activate")
def tab_activate(
    handle: str = typer.Argument(..., help="Stable window handle from `visus tabs --json`."),
) -> None:
    """Focus a tab by its stable handle (survives reordering, unlike an index)."""
    result = _send("tab_activate", {"handle": handle})
    output.emit(
        result,
        table=(
            f"activated tab {result['active']} "
            f"({result['handle']}): {str(result.get('title', ''))!r}"
        ),
    )


@app.command("tab-follow")
def tab_follow(
    enabled: bool = typer.Option(
        True, "--on/--off", help="Auto-follow new tabs/popups (--on) or stay put (--off)."
    ),
) -> None:
    """Choose whether a newly-opened tab/popup takes over the session context."""
    result = _send("tab_follow", {"enabled": enabled})
    state = "enabled (auto)" if result["follow"] else "disabled (manual)"
    output.emit(result, table=f"tab-follow {state}")


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
def cookies(
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
    domain: str = typer.Option(None, "--domain", help="Only cookies for this domain."),
    path: str = typer.Option(None, "--path", help="Only cookies with this exact path."),
) -> None:
    """List cookies for the session's context, optionally filtered."""
    result = _send("cookies", {"domain": domain, "path": path})
    items = result.get("cookies", [])
    if as_json:
        output.set_mode(as_json=True)
    if not items:
        output.emit(items, table="(no cookies)")
        return
    table = "\n".join(
        f"{c.get('name', '')}={c.get('value', '')}  ({c.get('domain', '')}{c.get('path', '')})"
        for c in items
    )
    output.emit(items, table=table)


@app.command("cookie-get")
def cookie_get(
    name: str = typer.Argument(..., help="Cookie name."),
    domain: str = typer.Option(None, "--domain"),
    path: str = typer.Option(None, "--path"),
) -> None:
    """Print one cookie's value (exits 1 when there is no such cookie)."""
    result = _send("cookie_get", {"name": name, "domain": domain, "path": path})
    if not result.get("present"):
        output.emit_error(f"no such cookie: {name!r}")
    output.emit(result.get("value"))


@app.command("cookie-set")
def cookie_set(
    name: str = typer.Argument(..., help="Cookie name."),
    value: str = typer.Argument(..., help="Cookie value."),
    domain: str = typer.Option(None, "--domain"),
    path: str = typer.Option("/", "--path"),
    url: str = typer.Option(None, "--url", help="Set for this URL instead of a domain/path."),
) -> None:
    """Set one cookie on the session's context (current document's domain)."""
    output.emit(
        _send(
            "cookie_set",
            {"name": name, "value": value, "domain": domain, "path": path, "url": url},
        )
    )


@app.command("cookie-delete")
def cookie_delete(
    name: str = typer.Argument(..., help="Cookie name."),
    domain: str = typer.Option(None, "--domain"),
    path: str = typer.Option(None, "--path"),
) -> None:
    """Delete cookies by name (WebDriver has no per-cookie delete: see the note)."""
    result = _send("cookie_delete", {"name": name, "domain": domain, "path": path})
    table = f"deleted {result['deleted']} cookie(s), restored {result['restored']}"
    if result.get("dropped"):
        table += (
            f" — {result['dropped']} cookie(s) for other domains could not be"
            " restored (WebDriver only accepts cookies for the loaded domain)"
        )
    output.emit(result, table=table)


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
# Web storage (localStorage / sessionStorage)
# ---------------------------------------------------------------------------

storage_app = typer.Typer(help="Read and write localStorage / sessionStorage.")
app.add_typer(storage_app, name="storage")

# `--session` / `-S` is reserved for named sessions, so the switch is spelled out.
_SESSION_STORAGE_OPT = typer.Option(
    False, "--session-storage", help="Use sessionStorage instead of localStorage."
)


@storage_app.command("list")
def storage_list(session: bool = _SESSION_STORAGE_OPT) -> None:
    """List every key/value in the current origin's storage."""
    result = _send("storage_list", {"session": session})
    items = result.get("items", [])
    table = (
        "(empty)"
        if not items
        else "\n".join(f"{i.get('name', '')}={i.get('value', '')}" for i in items)
    )
    output.emit(items, table=table)


@storage_app.command("get")
def storage_get(
    key: str = typer.Argument(..., help="Storage key."),
    session: bool = _SESSION_STORAGE_OPT,
) -> None:
    """Print one storage value (exits 1 when the key is absent)."""
    result = _send("storage_get", {"key": key, "session": session})
    if not result.get("present"):
        output.emit_error(f"no such key: {key!r}")
    output.emit(result.get("value"))


@storage_app.command("set")
def storage_set(
    key: str = typer.Argument(..., help="Storage key."),
    value: str = typer.Argument(..., help="Value to store."),
    session: bool = _SESSION_STORAGE_OPT,
) -> None:
    """Write one storage value."""
    output.emit(_send("storage_set", {"key": key, "value": value, "session": session}))


@storage_app.command("delete")
def storage_delete(
    key: str = typer.Argument(..., help="Storage key."),
    session: bool = _SESSION_STORAGE_OPT,
) -> None:
    """Remove one storage key."""
    result = _send("storage_delete", {"key": key, "session": session})
    output.emit(result, table="deleted" if result.get("deleted") else "no such key")


@storage_app.command("clear")
def storage_clear(session: bool = _SESSION_STORAGE_OPT) -> None:
    """Clear the whole store for the current origin."""
    result = _send("storage_clear", {"session": session})
    output.emit(result, table=f"cleared {result.get('cleared', 0)} key(s)")


# ---------------------------------------------------------------------------
# Storage state (cookies + localStorage/sessionStorage)
# ---------------------------------------------------------------------------


@app.command("state-save")
def state_save(
    file: str = typer.Argument("storage-state.json", help="Where to write the snapshot."),
) -> None:
    """Save cookies + web storage to a JSON file (reuse it to skip a login)."""
    # Resolve against the CLIENT's cwd — the daemon's cwd may differ.
    path = str(Path(file).resolve())
    result = _send("state_save", {"path": path})
    output.emit(
        result,
        table=(
            f"saved {result['path']} "
            f"({result['cookies']} cookie(s), {result['origins']} origin(s))"
        ),
    )


@app.command("state-load")
def state_load(
    file: str = typer.Argument(..., help="A snapshot written by `visus state-save`."),
) -> None:
    """Restore cookies + web storage from a JSON file.

    Navigate to the target origin first (`visus goto <url>`): cookies only apply
    to the loaded domain and web storage is per-origin.
    """
    output.emit(_send("state_load", {"path": str(Path(file).resolve())}))


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------


@app.command("eval")
def eval_js(
    expression: str = typer.Argument(..., help="A JS function, e.g. '() => document.title'."),
    arg: str = typer.Argument(None, help="Optional JSON argument passed to the function."),
    index: int = typer.Option(None, "--index", "-i", help="Run on this field instead of the page."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text", help="Target an element by its visible text."),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    as_json: bool = typer.Option(False, "--json", help="Emit the result as JSON."),
    nth: int = _NTH_OPT,
) -> None:
    """Evaluate JavaScript and print the result.

    On the page: `visus eval '() => document.title'` — the function takes the
    optional argument. On an element: `visus eval '(el) => el.id' -s "#u"` — the
    function takes the ELEMENT first, then the optional argument.
    """
    parsed_arg: Any = None
    if arg is not None:
        try:
            parsed_arg = _json.loads(arg)
        except _json.JSONDecodeError:
            parsed_arg = arg  # treat as a plain string when not valid JSON
    args: dict[str, Any] = {"expression": expression, "arg": parsed_arg}
    if index is not None or selector or role or text:
        args.update(
            _target_args(index, selector, role, name, text, exact=exact, frame=frame, nth=nth)
        )
    env = _send_env("eval", args)
    if as_json:
        output.set_mode(as_json=True)
    value = (env.get("result") or {}).get("result")
    output.emit_envelope(env, table="" if value is None else str(value))


@app.command("run-code")
def run_code(
    code: str = typer.Argument(
        None, help="Python to run, e.g. 'page.title()' or 'result = page.url'."
    ),
    file: str = typer.Option(None, "--file", "-f", help="Read the code from a file instead."),
) -> None:
    """Run Python against the LIVE session (`page`, `context`, `browser`, `expect`).

    Requires `visus session start --allow-run-code`. A single expression is
    returned directly; a longer snippet returns whatever it assigns to `result`::

        visus run-code "page.set_geolocation(51.5074, -0.1278)"
        visus run-code --file ./snippet.py
    """
    from visus.web.cli import output

    if file is not None:
        # Read on the CLIENT side so the path resolves against the user's cwd.
        source = Path(file).read_text(encoding="utf-8")
    elif code is not None:
        source = code
    else:
        output.emit_error("no code — pass it as an argument or use --file <path>")
    output.emit(_send("run_code", {"code": source}).get("result"))


# ---------------------------------------------------------------------------
# Network mocking (Chromium)
# ---------------------------------------------------------------------------

# Module-level singleton defaults (B008: a call cannot be an inline default).
_ROUTE_HEADER_OPT = typer.Option(
    None, "--header", "-H", help="Response header 'K: V' (repeatable)."
)


def _parse_headers(raw: list[str] | None) -> dict[str, str]:
    """Parse repeated ``--header 'K: V'`` values into a dict."""
    from visus.web.cli import output

    headers: dict[str, str] = {}
    for item in raw or []:
        key, sep, value = item.partition(":")
        if not sep or not key.strip():
            output.emit_error(f"bad --header {item!r} — use the form 'K: V'")
        headers[key.strip()] = value.strip()
    return headers


@app.command()
def route(
    pattern: str = typer.Argument(..., help="URL glob, e.g. '**/api/users' or '**/*.png'."),
    status: int = typer.Option(None, "--status", help="Response status for the mock."),
    body: str = typer.Option(None, "--body", help="Response body text."),
    body_file: str = typer.Option(None, "--body-file", help="Read the body from a file."),
    content_type: str = typer.Option(
        None, "--content-type", help="Response Content-Type, e.g. application/json."
    ),
    header: list[str] = _ROUTE_HEADER_OPT,
    abort: bool = typer.Option(False, "--abort", help="Fail the request instead of mocking it."),
) -> None:
    """Mock or block requests matching a URL glob (Chromium only).

    `**` crosses `/`, `*` does not, `{a,b}` is an alternation, and `?` is literal.
    Re-routing the same pattern replaces the rule.
    """
    from visus.web.cli import output

    if abort and (status is not None or body is not None or body_file is not None):
        output.emit_error("--abort fails the request — it cannot also carry a status or body")
    if body is not None and body_file is not None:
        output.emit_error("pass --body or --body-file, not both")
    payload_body = body
    if body_file is not None:
        # Read on the CLIENT side so the path resolves against the user's cwd.
        payload_body = Path(body_file).read_text(encoding="utf-8")
    args: dict[str, Any] = {
        "pattern": pattern,
        "status": status,
        "body": payload_body,
        "content_type": content_type,
        "headers": _parse_headers(header),
        "abort": abort,
    }
    result = _send("route", args)
    rule = result.get("route", {})
    verb = "aborting" if rule.get("abort") else f"mocking with {rule.get('status') or 200}"
    output.emit(rule, table=f"routed {rule.get('pattern', pattern)} — {verb}")


@app.command()
def unroute(
    pattern: str = typer.Argument(None, help="Pattern to remove (omit = remove every rule)."),
) -> None:
    """Remove an interception rule, or all of them."""
    from visus.web.cli import output

    result = _send("unroute", {"pattern": pattern})
    removed = result.get("removed", 0)
    output.emit(removed, table=f"removed {removed} route(s)")


@app.command("route-list")
def route_list() -> None:
    """List the interception rules installed on the session's page."""
    from visus.web.cli import output

    rules = _send("route_list", {}).get("routes", [])
    if not rules:
        output.emit([], table="no routes")
        return
    from rich import box
    from rich.console import Console
    from rich.table import Table

    table = Table(box=box.ASCII, header_style="bold", pad_edge=False)
    for column in ("PATTERN", "ACTION", "STATUS", "CONTENT-TYPE", "BODY"):
        table.add_column(column, overflow="fold", no_wrap=column == "ACTION")
    for rule in rules:
        body_text = str(rule.get("body") or "")
        table.add_row(
            str(rule.get("pattern", "")),
            "abort" if rule.get("abort") else "fulfill",
            str(rule.get("status") or ""),
            str(rule.get("content_type") or ""),
            body_text if len(body_text) <= 120 else body_text[:117] + "...",
        )
    console_obj = Console()
    with console_obj.capture() as cap:
        console_obj.print(table)
    output.emit(rules, table=cap.get().rstrip("\n"))


# ---------------------------------------------------------------------------
# DevTools: console messages
# ---------------------------------------------------------------------------


def _logs_text(messages: list[dict[str, Any]]) -> str:
    """Render console messages one per line: LEVEL then text."""
    if not messages:
        return "(no console messages)"
    return "\n".join(f"{str(m.get('level', '')):8} {m.get('text', '')}" for m in messages)


@app.command()
def logs(
    level: str = typer.Argument(None, help="Filter by level: SEVERE, WARNING or INFO."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Print the browser console messages captured so far (Chromium)."""
    result = _send("console_messages", {"level": level})
    messages = result.get("messages", [])
    if as_json:
        output.set_mode(as_json=True)
    output.emit(messages, table=_logs_text(messages))


def _requests_text(rows: list[dict[str, Any]]) -> str:
    """Render captured responses as `# STATUS METHOD URL` lines."""
    if not rows:
        return "(no requests captured)"
    return "\n".join(
        f"[{r.get('index', i)}] {r.get('status', '')!s:>4} "
        f"{str(r.get('method', '')):6} {r.get('url', '')}"
        for i, r in enumerate(rows)
    )


@app.command()
def requests(
    url_filter: str = typer.Option(
        None, "--filter", "-F", help="Keep only URLs containing this substring."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List the network responses captured so far (Chromium)."""
    rows = _send("network_requests", {"url_filter": url_filter}).get("requests", [])
    if as_json:
        output.set_mode(as_json=True)
    output.emit(rows, table=_requests_text(rows))


@app.command()
def request(
    index: int = typer.Argument(..., help="Index from `visus requests`."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show one captured response in full, including its body."""
    r = _send("network_request", {"index": index})
    if as_json:
        output.set_mode(as_json=True)
    text = "\n".join(
        [
            f"{r.get('method', '')} {r.get('url', '')}",
            f"status : {r.get('status', '')}",
            f"type   : {r.get('resource_type', '')}",
            "",
            r.get("body") if r.get("body") is not None else "(body unavailable)",
        ]
    )
    output.emit(r, table=text)


# ---------------------------------------------------------------------------
# Full traffic capture (request bodies, JSONP, beacons, pixel pings)
# ---------------------------------------------------------------------------

network_app = typer.Typer(
    help="Capture what the page itself sends (complements `visus requests`)."
)
app.add_typer(network_app, name="network")


@network_app.command("start")
def network_start() -> None:
    """Start capturing the page's own traffic (install the hook before you interact)."""
    _send("network_capture_start", {})
    output.emit({"started": True}, table="capture started")


@network_app.command("stop")
def network_stop() -> None:
    """Stop capturing and report how many entries were recorded."""
    result = _send("network_capture_stop", {})
    output.emit(result, table=f"capture stopped ({result['captured']} entr(y|ies))")


@network_app.command("export")
def network_export(
    output_file: str = typer.Option("capture.json", "-o", "--output"),
) -> None:
    """Write the captured traffic to JSON: `{target_url, entries}`, secrets redacted."""
    # Resolve against the CLIENT's cwd — the daemon's may differ.
    result = _send("network_capture_export", {"path": str(Path(output_file).resolve())})
    output.emit(result, table=f"saved {result['path']} ({result['entries']} entries)")


# ---------------------------------------------------------------------------
# Vision (requires the [vision] extra)
# ---------------------------------------------------------------------------


@app.command("read-text")
def read_text(
    target: str = _TARGET_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """OCR the targeted element's screenshot and print the recognized text."""
    index, sel = _positional(target, selector)
    args = _target_args(index, sel, role, name, text, exact=exact, frame=frame, nth=nth)
    output.emit(_send("read_text", args))


@app.command("solve-captcha")
def solve_captcha(
    target: str = _TARGET_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
    nth: int = _NTH_OPT,
) -> None:
    """OCR-solve a text CAPTCHA in the targeted element and print the solution."""
    index, sel = _positional(target, selector)
    args = _target_args(index, sel, role, name, text, exact=exact, frame=frame, nth=nth)
    output.emit(_send("solve_captcha", args))


@app.command("find-image")
def find_image(
    template: str = typer.Argument(..., help="Path to the template PNG to search for."),
    target: str = _TARGET_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    confidence: float = typer.Option(0.8, "--confidence", "-c", help="Match threshold (0-1)."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Find a template image inside the page (or a targeted element)."""
    index, sel = _positional(target, selector)
    args: dict[str, Any] = {
        "template_path": str(Path(template).resolve()),
        "confidence": confidence,
    }
    if index is not None:
        args["index"] = index
    if sel or role or text:
        args["selector"] = sel
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


@app.command("repl")
def repl(
    url: str = typer.Argument(None, help="Optional URL to open."),
    engine: str = typer.Option("chrome", "--engine", "-e"),
    headless: bool = typer.Option(False, "--headless"),
) -> None:
    """Open an interactive REPL attached to the session (starts one if none)."""
    from visus.web.cli.console import run_console

    run_console(url, engine=engine, headless=headless)


@app.command("console")
def console(
    url: str = typer.Argument(None, help="Optional URL to open."),
    engine: str = typer.Option("chrome", "--engine", "-e"),
    headless: bool = typer.Option(False, "--headless"),
) -> None:
    """DEPRECATED alias for `visus repl`. Browser console messages are `visus logs`."""
    typer.echo(
        "warning: `visus console` is deprecated — use `visus repl`. "
        "(Browser console messages are `visus logs`.)",
        err=True,
    )
    from visus.web.cli.console import run_console

    run_console(url, engine=engine, headless=headless)
