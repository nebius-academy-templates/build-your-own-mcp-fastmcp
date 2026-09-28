# Hostile inputs

**Related**:

> [CONTRACT](CONTRACT.md): Paths, Files and Errors say what each input must answer
> [README](README.md): Task 6 builds the screening; the verify step uses this page

Inputs a careless or malicious caller can send, and what your server must answer. The checks for task 6 try each of them on a log root they build themselves. This page lets you try them by hand in the MCP Inspector.

## Links
- [MCP Inspector CLI](https://modelcontextprotocol.io/docs/2026-07-28/tools/inspector/cli)

**Internal**:

- `2-state-safety-errors/CONTRACT.md`
- `2-state-safety-errors/inspector.json`

## Build a hostile log root
`s3_logs/` has no symlinks, no broken archives and no huge files, so build a small log root that has them. The block works in bash and zsh on macOS and Linux, and only writes under `/tmp/log-triage-hostile`:

```bash
H=/tmp/log-triage-hostile
rm -rf "$H"
mkdir -p "$H/outside" "$H/reports" "$H/logs/walk" "$H/logs/broken" "$H/logs/cut" "$H/logs/big" "$H/logs/long"
printf '%s\n' '2026-01-15T09:00:00.000Z INFO vault outside the root, never served' > "$H/outside/secret.log"
printf '%s\n' '2026-01-15T10:00:00.000Z INFO api request served' '2026-01-15T10:00:01.000Z WARN api request slow' '2026-01-15T10:00:02.000Z ERROR api request failed' > "$H/logs/app.log"
ln -s ../outside/secret.log "$H/logs/link-out.log"
ln -s app.log "$H/logs/link-in.log"
ln -s ../outside "$H/logs/linkdir"
printf '%s\n' '2026-01-15T10:05:00.000Z INFO walker step one' '2026-01-15T10:05:01.000Z ERROR walker step two' > "$H/logs/walk/good.log"
ln -s ../app.log "$H/logs/walk/zz-link.log"
ln -s ../../outside "$H/logs/walk/sub-link"
printf 'this is not gzip data\n' > "$H/logs/broken/bad.log.gz"
printf '%s\n' '2026-01-15T10:06:00.000Z INFO mender still readable' > "$H/logs/broken/good.log"
seq 1 5000 | sed 's/.*/2026-01-15T10:07:00.000Z INFO copier chunk & copied/' | gzip -c > "$H/cut.gz"
head -c $(( $(wc -c < "$H/cut.gz") / 2 )) "$H/cut.gz" > "$H/logs/cut/cut.log.gz"
rm "$H/cut.gz"
yes '2026-01-15T10:00:00.000Z INFO filler padding line for the size cap' | head -n 1001625 | gzip -c > "$H/logs/big/huge.log.gz"
seq 1 60 | sed 's/.*/2026-01-15T10:08:00.000Z INFO filler sparse head line &/' > "$H/logs/big/sparse.log"
dd if=/dev/zero of="$H/logs/big/sparse.log" bs=1 count=1 seek=67108864 conv=notrunc 2>/dev/null
printf '%s\n' '2026-01-15T10:09:00.000Z INFO stretcher short line' > "$H/logs/long/long.log"
printf '2026-01-15T10:09:01.000Z INFO stretcher long line %s TAIL\n' "$(printf '%70000s' '' | tr ' ' x)" >> "$H/logs/long/long.log"
```

What it makes, under `/tmp/log-triage-hostile`:

| Path | What it is |
|---|---|
| `outside/secret.log` | A log file outside the log root |
| `logs/` | The log root |
| `logs/app.log` | An ordinary file |
| `logs/link-out.log` | A symlink to the file outside |
| `logs/link-in.log` | A symlink to `app.log`, inside the root |
| `logs/linkdir` | A symlink to the folder outside |
| `logs/walk/` | An ordinary file next to a symlinked file (`zz-link.log`) and a symlinked folder (`sub-link`) |
| `logs/broken/bad.log.gz` | A `.gz` name on a file that isn't gzip, next to a good file |
| `logs/cut/cut.log.gz` | A gzip file cut in half: its first lines decode, the rest doesn't |
| `logs/big/huge.log.gz` | A small gzip file that decompresses to just over 64 MiB |
| `logs/big/sparse.log` | A plain file of just over 64 MiB that takes almost no disk space |
| `logs/long/long.log` | A file whose second line is 70,055 characters long |
| `reports/` | Where findings go, outside the log root |

The `log-triage-hostile` server in `inspector.json` runs your server on this root. On macOS `/tmp` is itself a symlink: the root may sit under one, and your server must still serve it.

## Try the inputs
From this folder, one call per input:

Use the direct Inspector CLI here to select the configured hostile-input server and make an exact `tools/call` request. The `inspector.json` config pins the modern protocol; `fastmcp dev inspector` cannot load it and defaults to the older legacy handshake.

```bash
npx @modelcontextprotocol/inspector --cli --config inspector.json --server log-triage-hostile --method tools/call --tool-name read_lines --tool-args-json '{"path": "link-out.log", "line": 1}' --format json
```

Change `--tool-name` and `--tool-args-json` for each row. A refused call prints its result on stdout, with the text to compare, and exits with code 5; stderr then shows `{"error":{"code":"tool_is_error",...}}`. `\u0000` inside the JSON is a NUL character.

| Input | Tool and arguments | The answer |
|---|---|---|
| A NUL byte | `list_logs` `{"path": "app.log\u0000"}` | E1 |
| An absolute path outside the root | `summarize_logs` `{"path": "/etc"}` | E1 |
| A path that climbs out | `list_logs` `{"path": "../"}` | E1 |
| A path that climbs out halfway | `search_logs` `{"path": "walk/../../outside/secret.log", "pattern": "."}` | E1 |
| A symlink to a file outside | `read_lines` `{"path": "link-out.log", "line": 1}` | E1 |
| A symlink to a file inside | `read_lines` `{"path": "link-in.log", "line": 1}` | E1 |
| A symlinked folder | `list_logs` `{"path": "linkdir"}` | E1 |
| A file through a symlinked folder | `read_lines` `{"path": "linkdir/secret.log", "line": 1}` | E1 |
| A path that isn't there | `list_logs` `{"path": "walk/missing.log"}` | E2 |
| A folder holding symlinks | `summarize_logs` `{"path": "walk", "min_level": "any"}` | `walk/sub-link` and `walk/zz-link.log` in `skipped`, reason `symlink`; one file scanned |
| The same folder, listed | `list_logs` `{"path": "walk"}` | only `walk/good.log` |
| A `.gz` file that isn't gzip | `summarize_logs` `{"path": "broken", "min_level": "any"}` | `broken/bad.log.gz` skipped, reason `unreadable`; the good file scanned |
| The same file, listed | `list_logs` `{"path": "broken"}` | `broken/bad.log.gz` with format `unknown` |
| The same file, read | `read_lines` `{"path": "broken/bad.log.gz", "line": 1}` | a masked error: no file system path, no exception text |
| A gzip file cut in half | `summarize_logs` `{"path": "cut", "min_level": "any"}` | skipped, reason `unreadable`; `lines_scanned` 0 |
| Files over 64 MiB | `summarize_logs` `{"path": "big", "min_level": "any"}` | both skipped, reason `too large` |
| A line over 65,536 characters | `search_logs` `{"path": "long", "pattern": "TAIL"}` | no match: the line was cut before its end |
| The same line, read | `read_lines` `{"path": "long/long.log", "line": 2}` | `text` cut to 500 characters |

Two more on the normal server, `log-triage`:

| Input | Tool and arguments | The answer |
|---|---|---|
| A folder where a file is needed | `read_lines` `{"path": "vms/web-01", "line": 1}` | E10 with `"vms/web-01"` |
| The root where a file is needed | `read_lines` `{"path": "", "line": 1}` | E10 with `"."` |

E1, E2 and E10 are the texts in `CONTRACT.md`, section 5. The error text quotes the path as you sent it (E1, E2) or as the server normalized it (E10), and never shows where the log root is on disk.

When you're done, remove the folder:

```bash
rm -rf /tmp/log-triage-hostile
```
