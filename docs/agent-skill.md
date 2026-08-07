# The agent skill

`visus-web` ships an agent skill inside the wheel. Any agent that reads
`.claude/skills/` (Claude Code, GitHub Copilot, and others) picks it up once you
install it into the repository you are working in.

```bash
pip install "visus-web[cli]"
visus install --skills            # -> ./.claude/skills/visus-web/
visus install --skills=agents     # -> ./.agents/skills/visus-web/
visus install-skills --target both --force
```

Every later `visus` invocation compares the installed copy against the packaged
one and prints a framed warning **to stderr** if they diverge, naming the
command that fixes it. Line endings are normalised, so a CRLF checkout never
raises a false alarm.

## What the skill teaches

The session loop, which is how an agent should drive the browser:

```bash
visus session start https://example.com/login
visus list-fields
visus fill 1 ada@example.com
visus click --role button --name "Sign in"
visus expect-text --role heading "Welcome"
visus session stop
```

Twelve reference files sit next to it — session lifecycle, targeting, the full
command table, JSON and piping, the REPL, Windows quoting, the MCP tools,
vision, tracing and reports, the pytest plugin, troubleshooting, and the Python
API.

## Without the CLI

An MCP client can read the same content without a shell: the `visus-web-mcp`
server exposes the resource `visus://skill/SKILL.md`, the resource template
`visus://skill/references/{name}`, and the prompt `visus_web_quickstart`.
