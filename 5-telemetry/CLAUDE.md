# Rules for this practice: telemetry

Read [CONTRACT.md](CONTRACT.md) and [README.md](README.md) before building. These rules override earlier stage rules for this practice.

## Build boundary

Continue the existing server in `solution/`, keeping its MCP surface and behavior. Implement one task at a time. Task 1 copies the provided `starter/telemetry.py` into `solution/` and wires it in: keep its code as provided. Keep FastMCP 4.0.3 and add the OpenTelemetry Python SDK 1.44.0 with its OTLP/HTTP exporter.

Do not add metrics or log export, a console exporter, HTTP-layer tracing, sampling configuration, a collector, LangSmith's SDK, new tools or flags. Never put a real key or token into a file. Never change the corpus or bake its incidents into source code.

## Editable files

Change `solution/` and its tests. Edit `CHECKLIST.md` only at the student's request. Leave contracts, checks, earlier materials and docs unchanged. Findings are written only through `save_finding`. When the student requests host integration, use the registration commands in `hosts.md` and change only the named exercise registration. Keep real credentials out of configuration files.

## Checkpoints

Run `uv run --project 5-telemetry/checks pytest 5-telemetry/checks` from the repository root. The task's tests and all preceding task tests should pass when it is done. Later tasks may fail. Run the server's own tests after every task. The checks start the server with `uv run --project solution log-triage`, which installs its dependencies first, passes signals on to the server and waits for it to exit, and point it at their own local receiver.

Keep instrumentation context-scoped. A stored scan holds analysis state, never a request context or span. Telemetry must not weaken rooted file access or caller isolation. Look up the pinned library API before using it.
