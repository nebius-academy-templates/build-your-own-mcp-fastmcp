# Rules for this practice: testing and debugging

**Related**:

> [README](README.md): Stage, setup, and verification guide
> [CONTRACT](CONTRACT.md): The exact surface to build
> [tricky-cases](tricky-cases.md): The unit test cases
> [mutations](mutations.md): The planted bugs of task 5
> [probe-expected](probe-expected.md): The probe's steps and output

These rules take priority over the repository root's `CLAUDE.md` wherever the two differ. `AGENTS.md` in this folder is an identical copy.

## What this practice builds
The third version of the Log Triage server, in `solution/`, on top of what practices 1 and 2 built, with FastMCP 4.0.3 on Python 3.13:

- the server's own tests under `solution/tests/`: `unit/`, `protocol/`, `flow/` and `meaning/`, with shared fixtures in `tests/conftest.py`;
- a scripted client in `solution/scripts/probe.py`;
- the `--log-level` flag, logging to stderr in `src/logtriage/log_setup.py`, one line per tool call at `debug`;
- the `timeline` tool with E11 and E12, version `0.3.0` and the longer instructions.

`CONTRACT.md` in this folder describes the whole server after this practice. Build one prompt at a time, only what that prompt asks for. Use the paths named by the practice lesson's prompt and the commands below.

## What not to build yet
Later practices add these. Don't add them now, even where they look useful:

- HTTP, tokens, or a caller other than `local`;
- prompts, including a `triage` prompt;
- any tool, resource, flag or error text not in `CONTRACT.md`;
- tests that start the server as a subprocess from `solution/tests/`: the protocol and flow tests use FastMCP's in-process client, and only the probe starts a process.

## Files you may change
| Path | When |
|---|---|
| `solution/` | always; all server code, tests, the probe, `pyproject.toml`, `uv.lock` and `README.md` |
| `3-testing-and-debugging/CHECKLIST.md` | only when the student asks you to |
| `reports/` | only through the server's `save_finding` tool |

Never change this folder's `CONTRACT.md`, `README.md`, `CLAUDE.md`, `AGENTS.md`, `tricky-cases.md`, `mutations.md`, `facts.json`, `probe-expected.md`, `inspector.json` or anything in `checks/`, and never write into `s3_logs/`, `docs/` or the earlier practice folders. If the contract and the checks seem to disagree, say so instead of changing either.

## How to work
- Look up FastMCP 4.0.3 and pytest behaviour in their documentation before you rely on it; don't guess an API. FastMCP's testing page shows the in-process client (`Client(server)`).
- Tests may name files in `s3_logs/` and compare with `facts.json`, but no test states what went wrong in the logs.
- When a test fails, decide first whether the code or the test is wrong, and say which you changed.
- FastMCP writes its own lines to stderr (a start-up line, and a traceback for a masked error) whatever the server sets. That's fine: only lines containing `tool=` are counted. Nothing may reach stdout except the protocol.
- A mutation from `mutations.md` changes the server code only. Before one, the student commits or stashes; to undo one, put the code back with `git checkout -- solution/src`.
- Keep practices 1 and 2 working: their checks must still pass after every prompt.
- Follow `docs/log-formats.md` rule by rule. Compile its regular expressions with `re.ASCII`.
- The server knows log formats and nothing about what happened in `s3_logs/`: no host, date, address, incident or message from the logs appears in `solution/src/`.
- When the student asks what happened in the logs, answer through the Log Triage tools, not by reading `s3_logs/` directly.

## Commands
Run from the repository root.

| What | Command |
|---|---|
| Install or update the server's environment, dev group included | `uv sync --project solution` |
| Run the server over stdio | `uv run --project solution log-triage --root s3_logs` |
| Run the server's own tests | `uv run --project solution pytest solution/tests` |
| Run one layer of them | `uv run --project solution pytest solution/tests/unit` |
| Run the probe | `uv run --project solution python solution/scripts/probe.py --root s3_logs` |
| Undo a mutation | `git checkout -- solution/src` |
| Run this practice's checks | `uv run --project 3-testing-and-debugging/checks pytest 3-testing-and-debugging/checks` |
| Run one task's checks | `uv run --project 3-testing-and-debugging/checks pytest 3-testing-and-debugging/checks/test_t4_probe.py` |
| Run the earlier practices' checks | `uv run --project 2-state-safety-errors/checks pytest 2-state-safety-errors/checks`, `uv run --project 1-surface-and-contract/checks pytest 1-surface-and-contract/checks` |

The checks start the server themselves with `uv run --project solution log-triage`, run your own tests with `uv run --project solution pytest`, and run the probe as above. There is one check file per build task: `test_t1_unit.py`, `test_t2_protocol.py`, `test_t3_meaning.py`, `test_t4_probe.py`, `test_t6_logging.py` and `test_t7_timeline.py`. Task 5, the mutations, has none. After the prompt for task K, the files for the tasks up to K pass, the later ones still fail, and the practice 1 and 2 checks pass.
