# Rules for this practice: state, safety and errors

**Related**:

> [README](README.md): The stage, its MCP surface, setup and verification
> [CONTRACT](CONTRACT.md): The exact surface to build
> [hostile-inputs](hostile-inputs.md): Inputs the server must refuse
> [log-formats](../docs/log-formats.md): How to read every log line

These rules take priority over the repository root's `CLAUDE.md` wherever the two differ. `AGENTS.md` in this folder is an identical copy.

## What this practice builds
The second version of the Log Triage server, in `solution/`, on top of what practice 1 built, with FastMCP 4.0.3 on Python 3.13:

- version `0.2.0`, the longer instructions and the `--scan-ttl` flag;
- a scan store: `summarize_logs` returns a `scan_id`, and the store keeps each scan's groups for later calls;
- two tools: `group_lines` and `read_lines`;
- two resources and two templates: `triage://formats`, `triage://reports`, `triage://reports/{name}`, `triage://scans/{scan_id}`, with the freshness pair;
- path screening, symlink handling, the size and line caps, unreadable archives;
- the contract's error texts, the checks behind `save_finding`'s schema, and masking of unexpected errors.

`CONTRACT.md` in this folder describes the whole server after this practice, practice 1 included. Build one prompt at a time, only what that prompt asks for.

## What not to build yet
Later practices add these. Don't add them now, even where they look useful:

- a caller other than `local`: tokens, principals from requests, per-caller tool lists;
- tests of your own under `solution/`, and scripts that call the server;
- a `timeline` tool, prompts, or any tool, resource or template not in `CONTRACT.md`;
- HTTP, a `--log-level` flag, or any flag not in `CONTRACT.md`;
- a cache of anything other than scans, or a scan store that outlives the process.

## Files you may change
| Path | When |
|---|---|
| `solution/` | always; all server code and its `pyproject.toml`, `uv.lock` and `README.md` |
| `2-state-safety-errors/interface.md`, `2-state-safety-errors/CHECKLIST.md` | only when the student asks you to |
| `reports/` | only through the server's `save_finding` tool |

Never change this folder's `CONTRACT.md`, `README.md`, `CLAUDE.md`, `AGENTS.md`, `hostile-inputs.md`, `inspector.json` or anything in `checks/`, and never write into `s3_logs/`, `docs/` or `1-surface-and-contract/`. If the contract and the checks seem to disagree, say so instead of changing either.

## How to work
- Look up FastMCP 4.0.3 behaviour in its documentation before you rely on it; don't guess an API. The freshness pair, masking and resource templates are all server options or decorators there.
- A resource handler that can't find what was asked returns the resource-not-found error from `CONTRACT.md`, section 4. In FastMCP 4.0.3, `NotFoundError` maps to `-32602` with the requested URI in `data`; an explicit `MCPError` with the same code is also valid.
- The error texts in `CONTRACT.md`, section 5, are exact. Build each one in one place and quote values with plain `"` characters, not with `repr()`.
- Screen path arguments where they are built, walk folders without following symlinks, and revalidate cached file paths before reopening them. A reopened file must stay inside the original root even if the file or a parent directory was replaced after the scan. The log root is resolved once at startup; only what lies below it is screened.
- Keep practice 1 working: its checks in `1-surface-and-contract/checks/` must still pass after every prompt.
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
| Run this practice's checks | `uv run --project 2-state-safety-errors/checks pytest 2-state-safety-errors/checks` |
| Run one task's checks | `uv run --project 2-state-safety-errors/checks pytest 2-state-safety-errors/checks/test_t3_group_lines.py` |
| Run practice 1's checks | `uv run --project 1-surface-and-contract/checks pytest 1-surface-and-contract/checks` |

The checks start the server themselves with `uv run --project solution log-triage` and their own `--root`, `--reports` and `--scan-ttl`. There is one check file per task, `test_t2_scans.py` to `test_t7_checks.py`; after the prompt for task K, the files for tasks 2 to K pass, the later ones still fail, and practice 1's checks pass.
