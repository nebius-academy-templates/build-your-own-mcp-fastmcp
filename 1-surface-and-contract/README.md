# Practice 1: Build the surface and the contract (Python, FastMCP)
**Practice files**:

> [Contract](CONTRACT.md): Exact server behavior and tool contracts
> [Interface worksheet](interface.md): Your design before you compare it with the supplied contract
> [Checklist](CHECKLIST.md): Manual completion checks
> [Coding-agent instructions](CLAUDE.md): Scope and constraints for AI-assisted work

Build the first working stage of Log Triage, an MCP server that helps an AI investigate a directory of mixed infrastructure logs. You will design its public interface, implement four tools, and verify the behavior through the MCP protocol.

The contract defines observable behavior. It does not prescribe your package names or internal file layout. Choose an implementation structure that keeps protocol code, log reading, and report writing understandable without copying the completed solution.

## Links
- [FastMCP documentation](https://gofastmcp.com/)
- [MCP specification used by this practice](https://modelcontextprotocol.io/specification/2026-07-28)
- [MCP Inspector](https://github.com/modelcontextprotocol/inspector)

**Project references**:

- [Log format rules](../docs/log-formats.md)
- [Log bundle guide](../docs/s3-logs.md)

## What you will build
Your server will:

- identify itself as `log-triage` version `0.1.0`;
- communicate over standard input and standard output;
- read plain-text and gzip-compressed logs under a configured root;
- expose four MCP tools with complete input and output schemas;
- return bounded structured results with an equivalent JSON text block;
- reject paths outside the configured log root;
- remove the write tool when started in read-only mode.

The checks start your program as a separate process and talk to it through MCP. They do not import your Python package, so your internal design remains your choice.

## How the pieces fit
```mermaid
flowchart TD
    Host[AI host or Inspector] -->|tools/list and tools/call| Server[Log Triage MCP server]
    Server -->|read only| Logs[s3_logs]
    Server -->|save_finding| Reports[reports]
```

The server receives tool calls from an AI host. Read tools inspect the supplied log corpus. The write tool stores an investigation report in a separate reports directory. Protocol messages use standard output, so diagnostics belong on standard error.

## Design reminders
Begin with the questions the AI must answer. Each distinct decision should have one clear operation.

| Contract part | What it tells the AI or client |
|---------------|--------------------------------|
| Name | Which operation is available |
| Description | When to call it and what it returns |
| Input schema | Which arguments are accepted, including defaults and limits |
| Output schema | Which result fields the client can rely on |
| Annotations | Whether the operation reads data, writes data, or may replace existing data |
| Tool result | The structured answer, its text copy, or an actionable error |

The model reads names, descriptions, and annotations when choosing a tool. FastMCP builds the input schema from the function signature and the output schema from the return model. Both layers are part of the public contract.

In Python, type hints, constrained parameters, and Pydantic models make the contract inspectable. The tool decorator supplies metadata such as the title and annotations. A raised `ToolError` returns a tool-level failure the model can act on. Exact values and defaults are listed in [CONTRACT.md](CONTRACT.md).

## MCP surface in this stage
MCP offers three server primitives:

- Tools are operations an AI model can choose and call.
- Resources are addressable context that an application can read.
- Prompts are reusable workflows that a user selects.

This stage publishes tools only. It intentionally has no MCP resources and no MCP prompts. Coding-agent prompts in the practice lesson help you implement the project, but they are not MCP prompts exposed by your server.

### `list_logs`
Use this discovery tool when the AI needs to learn which files exist below a path and which format each file uses. It returns file metadata without including log contents. Pagination keeps large directories manageable.

Example input:

```json
{
  "path": "vms/web-01",
  "limit": 20,
  "offset": 0
}
```

The result identifies each file's relative path, size, compression state, and detected format. It also reports the total and shown counts so the caller knows whether more entries remain.

### `summarize_logs`
Use this analysis tool for questions such as "What went wrong in this folder during this time window?" It parses known log formats, counts severity levels, and groups repeated messages into a bounded answer.

Example input:

```json
{
  "path": "vms/web-01",
  "since": "2026-08-31T03:00:00Z",
  "until": "2026-08-31T03:30:00Z",
  "min_level": "warning",
  "limit": 20
}
```

The result includes the observed time range, counts by level, and the most relevant message groups. Unknown file formats may be listed by `list_logs`, but this tool skips them because it cannot parse their records safely.

### `search_logs`
Use this evidence tool when the AI has a concrete regular expression and needs matching raw lines with file names and line numbers. Pagination lets the caller continue a search without requesting every match at once.

Example input:

```json
{
  "path": "vms/web-01",
  "pattern": "(?i)upstream|timeout",
  "limit": 20,
  "offset": 0
}
```

The result preserves the raw matching line and adds its source location. Time and severity filters are available when the search should cover only part of the corpus.

### `save_finding`
Use this write tool after the investigation has enough evidence to record a conclusion. It creates a Markdown report from a title, severity, summary, and source references.

Example input:

```json
{
  "title": "Investigation title",
  "severity": "medium",
  "summary": "Short conclusion supported by the evidence below.",
  "evidence": [
    {
      "file": "path/from-a-tool-result.log",
      "line": 123,
      "note": "What this line proves."
    }
  ]
}
```

Saving the same slug again replaces the existing report. The tool must therefore advertise that it writes data and can be destructive. It is absent when the server runs with `--read-only`.

## Contract expectations
Use [CONTRACT.md](CONTRACT.md) as the source of truth for exact fields, defaults, bounds, annotations, server instructions, and error text.

While implementing it, check these properties:

- Tool descriptions explain both the purpose and the result within the required length.
- Inputs reject invalid enum values, limits, timestamps, and regular expressions.
- Defaults work when optional arguments are omitted.
- Output schemas match the structured content returned at runtime.
- Every successful tool result contains `structuredContent` and one text block with the same JSON value.
- Bounded lists report `total`, `shown`, and a note when the result is incomplete.
- Expected failures raise `ToolError` with text that helps the AI correct its next call.
- Unregistered tool names remain protocol-level errors.

## Log-reading domain
The corpus contains nine supported formats: application logs, Nginx access logs, Nginx error logs, PHP-FPM logs, PostgreSQL logs, Redis logs, syslog, pytest output, and Go test output.

Your reader must also account for:

- plain and `.gz` files;
- recursive byte-order path traversal;
- hidden names that must be skipped;
- content-based format detection;
- multi-line message grouping;
- UTF-8 replacement for invalid bytes;
- one-based line numbers;
- half-open time windows where `since <= time < until`.

Implement the definitions in [docs/log-formats.md](../docs/log-formats.md) instead of inferring rules from the sample data.

## Repository map
Only the student-facing folders are shown here. Your implementation stays under `solution/`, but its internal folders are up to you.

```text
build-your-own-mcp-fastmcp/
├── 1-surface-and-contract/  # Contract, worksheet, checks, and Inspector config
├── docs/                    # Log formats and corpus notes
├── reports/                 # Findings written by save_finding
├── s3_logs/                 # Read-only input corpus
└── solution/                # Your Python implementation
```

Keep `s3_logs/` read-only. The server may write only inside the configured reports directory.

## Set up the project
You need Python 3.13, uv 0.11 or newer, Node.js 22.19 or newer, Git, and a coding agent or editor.

From the repository root, install the check dependencies and confirm that the starter state fails because no server exists yet:

```bash
# Run from the repository root.
uv sync --project 1-surface-and-contract/checks
uv run --project 1-surface-and-contract/checks pytest 1-surface-and-contract/checks
```

That initial failure is expected. Once your server starts correctly, the same command becomes the main verification command.

## Suggested build order
1. Complete [interface.md](interface.md) before reading the supplied contract closely. Record the questions the server should answer and the operations you would expose.
2. Compare your design with [CONTRACT.md](CONTRACT.md). Preserve your original worksheet and explain meaningful differences. Leave the original design unchanged.
3. Create the stdio server and register the four declared tools with their schemas and annotations.
4. Implement the shared log reader from the format specification.
5. Add the three read tools, then the report-writing tool.
6. Run the matching check file after each increment.
7. Inspect the published surface before using the server to solve the investigation case from the practice lesson.

The coding-agent prompts and the investigation question remain in the practice lesson. This README describes the project contract and how to verify it.

## Verify each capability
Run the full suite from the repository root:

```bash
# Run from the repository root.
uv run --project 1-surface-and-contract/checks pytest 1-surface-and-contract/checks
```

You can also run one check file at a time:

| Check file | Capability |
|------------|------------|
| `test_t2_server.py` | Server identity, startup, instructions, and tool registration |
| `test_t3_reading.py` | Log formats, gzip handling, grouping, paths, and time windows |
| `test_t4_list_logs.py` | Discovery, pagination, metadata, and bounds |
| `test_t5_summarize_logs.py` | Counts, severity filters, groups, and bounded results |
| `test_t6_search_logs.py` | Regex matches, source locations, filters, and errors |
| `test_t7_save_finding.py` | Report writing, replacement behavior, and read-only mode |

For example:

```bash
# Run from the repository root.
uv run --project 1-surface-and-contract/checks pytest 1-surface-and-contract/checks/test_t2_server.py
```

## Inspect the MCP surface
The Inspector config starts your server with the fixture root and a reports directory. From `1-surface-and-contract/`, list the normal tool surface:

Use the direct `npx` commands below, not `fastmcp dev inspector`. In FastMCP 4.0.3, that wrapper passes the Inspector only a `fastmcp run ... --no-banner` command. It cannot load `inspector.json` or select the protocol era, so the Inspector defaults to legacy `2025-11-25`. That handshake returns only tools in `tools/list`, so the Protocol tab omits newer metadata. This folder's config sets `protocolEra` to `modern`, selects the normal or read-only server, and uses `2026-07-28`.

```bash
# Run from 1-surface-and-contract/.
npx @modelcontextprotocol/inspector --cli \
  --config inspector.json \
  --server log-triage \
  --method tools/list \
  --format json
```

Check read-only mode separately:

```bash
# Run from 1-surface-and-contract/.
npx @modelcontextprotocol/inspector --cli \
  --config inspector.json \
  --server log-triage-read-only \
  --method tools/list \
  --format json
```

The first response should contain four tools. The read-only response should contain three and omit `save_finding`.

Call a read tool through the protocol:

```bash
# Run from 1-surface-and-contract/.
npx @modelcontextprotocol/inspector --cli \
  --config inspector.json \
  --server log-triage \
  --method tools/call \
  --tool-name summarize_logs \
  --tool-args-json '{"path":"vms/cache-01/syslog.log","min_level":"any"}'
```

FastMCP logs its stdio startup message to stderr. npm and uv may also print diagnostics there. Judge the command by the JSON protocol response on stdout.

## Completion check
Before submitting your work:

- compare `tools/list` with the contract;
- call every tool at least once through MCP;
- verify that read-only mode omits `save_finding`;
- confirm that `interface.md` preserves your original design and explains its differences from the implemented contract;
- run the full test suite;
- complete [CHECKLIST.md](CHECKLIST.md).

When these checks pass, commit `solution/`, `reports/`, and `1-surface-and-contract/` together. Continue to Practice 2 on that commit.
