# Rules for this practice: the surface and the contract

**Related**:

> [README](README.md): The tasks and their prompts
> [CONTRACT](CONTRACT.md): The exact surface to build
> [log-formats](../docs/log-formats.md): How to read every log line

These rules take priority over the repository root's `CLAUDE.md` wherever the two differ. `AGENTS.md` in this folder is an identical copy.

## What this practice builds
The first version of the Log Triage server, in `solution/`, with FastMCP 4.0.3 on Python 3.13:

- the server object, its name, version and instructions, its three command-line flags, stdio;
- a log reader that follows `docs/log-formats.md`;
- four tools: `list_logs`, `summarize_logs`, `search_logs` and `save_finding`, exactly as `CONTRACT.md` describes them.

Build one prompt at a time, only what that prompt asks for. The project structure in this folder's `README.md` names the files; use those names.

## What not to build yet
Later practices add these. Don't add them now, even where they look useful:

- a `scan_id` or any other handle, or a cache of scan results; every call reads the files again;
- tools other than the four above;
- resources, resource templates and prompts;
- error texts beyond refusing a path outside the log root; the refusal's wording is yours;
- checks behind the schema (evidence files and lines, existing finding names), masking of unexpected errors, size or line caps, symlink handling;
- HTTP, tokens, a `--log-level` flag or any other flag;
- tests of your own under `solution/`.

## Files you may change
| Path | When |
|---|---|
| `solution/` | always; all server code and its `pyproject.toml`, `uv.lock` and `README.md` |
| `1-surface-and-contract/interface.md`, `1-surface-and-contract/CHECKLIST.md` | only when the student asks you to |
| `reports/` | only through the server's `save_finding` tool |

Never change this folder's `CONTRACT.md`, `README.md`, `CLAUDE.md`, `AGENTS.md`, `inspector.json` or anything in `checks/`, and never write into `s3_logs/` or `docs/`. If the contract and the checks seem to disagree, say so instead of changing either.

## How to work
- Look up FastMCP 4.0.3 behaviour in its documentation before you rely on it; don't guess an API.
- Follow `docs/log-formats.md` rule by rule. Compile its regular expressions with `re.ASCII`.
- The server knows log formats and nothing about what happened in `s3_logs/`: no host, date, address, incident or message from the logs appears in `solution/`.
- Over stdio, stdout belongs to the protocol. Print diagnostics to stderr only.
- When the student asks what happened in the logs, answer through the Log Triage tools, not by reading `s3_logs/` directly.

## Commands
Run from the repository root.

| What | Command |
|---|---|
| Install or update the server's environment | `uv sync --project solution` |
| Run the server over stdio | `uv run --project solution log-triage --root s3_logs` |
| Run this practice's checks | `uv run --project 1-surface-and-contract/checks pytest 1-surface-and-contract/checks` |
| Run one task's checks | `uv run --project 1-surface-and-contract/checks pytest 1-surface-and-contract/checks/test_t4_list_logs.py` |

The checks start the server themselves with `uv run --project solution log-triage` and their own `--root` and `--reports`. There is one check file per task, `test_t2_server.py` to `test_t7_save_finding.py`; after the prompt for task K, the files for tasks 2 to K pass and the later ones still fail.
