# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.2.x   | yes |
| < 0.2   | no  |

## Reporting a vulnerability

Report privately through GitHub Security Advisories:

<https://github.com/botvisus/visus-framework-web/security/advisories/new>

Please **do not open a public issue** for a security problem. Use the
[bug tracker](https://github.com/botvisus/visus-framework-web/issues) only for
non-security defects.

Include: the version, the OS and browser engine, a minimal reproduction, and what an
attacker gains. An acknowledgement is sent within 5 working days.

## Threat model of the session daemon

`visus session start` runs a long-lived daemon that drives a real browser. It is
designed for a single trusted user on one machine:

- The daemon binds **loopback only** (`127.0.0.1`), on an ephemeral port.
- Every request must carry a per-session shared token (`secrets.token_hex(16)`),
  written to `.visus/session.json`.
- `.visus/` is in `.gitignore`, so the token is never committed.

Anything that can read `.visus/session.json` can drive the browser: run JavaScript in
the page via `visus eval`, read cookies, take screenshots to an arbitrary path, and
upload local files into a page. Treat that file as a credential. **Never expose the
daemon's port beyond loopback and never run the daemon on a shared or multi-tenant
host.**

Reports about a directory-local token file being readable by the same user are out of
scope; reports about the port being reachable off-host, the token being guessable, or
the token leaking into logs or artifacts are in scope.
