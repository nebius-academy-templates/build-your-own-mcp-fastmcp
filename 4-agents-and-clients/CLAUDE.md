# Rules for this practice: agents and clients

**Related**:

> [README](README.md): The completed stage, setup, checks, and Inspector session
> [CONTRACT](CONTRACT.md): The exact surface to build
> [hosts](hosts.md): How agent hosts connect over HTTP
> [cases](cases.md): The questions asked through a host

These rules take priority over the repository root's `CLAUDE.md` wherever the two differ. `AGENTS.md` in this folder is an identical copy.

## What this practice builds
The fourth and last version of the Log Triage server, in `solution/`, on top of what practices 1 to 3 built, with FastMCP 4.0.3 on Python 3.13:

- `--http HOST:PORT`: stateless streamable HTTP at `/mcp`, set up in `src/logtriage/http.py`, with the HTTP server's own log lines on stderr, never on stdout;
- callers from the bearer tokens in `LOG_TRIAGE_TOKENS`, the 401 answer and the `Origin` check, in `src/logtriage/auth.py`;
- scans owned by the caller, and a read-only caller that doesn't see `save_finding` and gets E13 when it calls it;
- the `triage` prompt in `src/logtriage/prompts.py`, the prompt sentence of the instructions and version `0.4.0`.

Over stdio nothing changes: it stays the default, with the one caller `local`. After the build, the student registers the server in two agent hosts (`hosts.md`), asks the questions of `cases.md` through them and saves the findings in `reports/`.

`CONTRACT.md` in this folder describes the whole server after this practice. Build one coding-agent prompt at a time, only what that prompt asks for. Use the file paths named by the prompt; the README is the project guide, not the task source.

## What not to build
This is the last practice. Don't add, even where it looks useful:

- OAuth, token issuing, or any HTTP route other than `/mcp`;
- callers from anywhere but `LOG_TRIAGE_TOKENS`, or tokens written to a file;
- sessions, or anything kept per connection: a `scan_id` is the only thing that carries from one request to the next;
- any tool, resource, prompt, flag or error text not in `CONTRACT.md`.

## Files you may change
| Path | When |
|---|---|
| `solution/` | always; all server code, its tests, `pyproject.toml`, `uv.lock` and `README.md` |
| `4-agents-and-clients/CHECKLIST.md` | only when the student asks you to |
| `reports/` | only through the server's `save_finding` tool |
| `.mcp.json` at the repository root | only through `claude mcp add --scope project`, when the student asks you to |

Never change this folder's `CONTRACT.md`, `README.md`, `CLAUDE.md`, `AGENTS.md`, `hosts.md`, `cases.md`, `tokens.example.env`, `inspector.json` or anything in `checks/`, and never write into `s3_logs/`, `docs/` or the earlier practice folders. Never write a token into any file; the example tokens stay in `tokens.example.env`. If the contract and the checks seem to disagree, say so instead of changing either.

## How to work
- Look up FastMCP 4.0.3 in its documentation before you rely on it: HTTP deployment (`http_app` with `stateless_http`), token verification, reading the caller's token in a tool (`get_access_token`), middleware and prompts. Don't guess an API.
- There is one scan store for the whole process. Build nothing that holds state per request.
- A tool that FastMCP hides with `auth=require_scopes(...)` disappears from the list, but a call to it then gets FastMCP's unknown-tool refusal, not E13. Hiding `save_finding` from a read-only caller and answering E13 are two separate pieces of code.
- The `Origin` check comes before the token check. FastMCP answers 401 at the `/mcp` route, so an ASGI middleware around the app, or one given to `http_app(middleware=...)`, sees each request first. FastMCP's own host and origin guard is off by default and lets in more origins than the contract does; leave it off.
- uvicorn, the HTTP server under FastMCP, writes its access lines to stdout unless it gets a logging configuration of its own. Send them to stderr, or turn them off.
- Tests of your own for HTTP use FastMCP's in-process HTTP helpers in `fastmcp.utilities.tests`, not a server started as a separate process. The protocol and flow tests of practice 3 keep using the in-process client.
- Keep practices 1 to 3 working, your own tests included: their checks run over stdio after every prompt.
- The `triage` prompt's text is instructions for an agent. Like everything in `solution/`, it names no host, date, address, incident or message from `s3_logs/`.
- Over stdio, stdout belongs to the protocol. With `--http`, stdout stays empty. Print diagnostics to stderr only.
- When the student asks what happened in the logs, answer through the Log Triage tools, not by reading `s3_logs/` directly.

## Commands
Run from the repository root.

| What | Command |
|---|---|
| Install or update the server's environment | `uv sync --project solution` |
| Run the server over stdio | `uv run --project solution log-triage --root s3_logs` |
| Load the example tokens | `set -a; . 4-agents-and-clients/tokens.example.env; set +a` |
| Run the server over HTTP | `uv run --project solution log-triage --root s3_logs --reports reports --http 127.0.0.1:8765` |
| Run the server's own tests | `uv run --project solution pytest solution/tests` |
| Run this practice's checks | `cd 4-agents-and-clients/checks && uv run pytest` |
| Run one task's checks | `cd 4-agents-and-clients/checks && uv run pytest test_t1_http.py` |
| Run the earlier practices' checks | `cd 3-testing-and-debugging/checks && uv run pytest`, and the same in `2-state-safety-errors/checks` and `1-surface-and-contract/checks` |

The checks start the server themselves with `uv run --project solution log-triage`, their own `--http 127.0.0.1:<free port>` and their own `LOG_TRIAGE_TOKENS`. There is one check file per build task: `test_t1_http.py`, `test_t2_principals.py` and `test_t3_prompt.py`. Tasks 4 to 7 happen in agent hosts and the MCP Inspector, and `CHECKLIST.md` records them. After the prompt for task K, the files for the tasks up to K pass, the later ones still fail, and the practice 1 to 3 checks pass.
