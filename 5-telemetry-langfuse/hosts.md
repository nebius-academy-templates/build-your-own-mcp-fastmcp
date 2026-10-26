# Trace an investigation from a host

Run the server over HTTP with telemetry enabled as [README.md](README.md) describes. Use an unused MCP registration name. These examples use `log-triage-telemetry`, so your normal server registration can remain intact.

## Links

- [Claude Code MCP](https://code.claude.com/docs/en/mcp)
- [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
- [Langfuse OTLP](https://langfuse.com/integrations/native/opentelemetry)

## Claude Code

Load the example tokens into the terminal that starts the host, then register the running HTTP server:

```bash
# Run from the repository root.
# macOS and Linux
set -a
. 4-agents-and-clients/tokens.example.env
set +a
claude mcp add --scope project --transport http log-triage-telemetry http://127.0.0.1:8765/mcp --header 'Authorization: Bearer ${LOG_TRIAGE_TOKEN}'
claude --tools ""

# Windows (PowerShell)
Get-Content 4-agents-and-clients/tokens.example.env | ForEach-Object { if ($_ -match '^(\w+)=(.*)$') { Set-Item -Path "Env:$($Matches[1])" -Value $Matches[2] } }
claude mcp add --scope project --transport http log-triage-telemetry http://127.0.0.1:8765/mcp --header 'Authorization: Bearer ${LOG_TRIAGE_TOKEN}'
claude --tools ""
```

The single quotes store a variable reference, not the token value, in PowerShell too. `--tools ""` removes Claude Code's built-in tools, not other MCP servers you have added. In the fresh session, inspect `/mcp`, enable the server if needed and ask the investigation question from the lesson. Check each tool call belongs to `log-triage-telemetry`. Approve writes only after reviewing their proposed finding.

## Codex

```bash
# Run from the repository root.
# macOS and Linux
set -a
. 4-agents-and-clients/tokens.example.env
set +a
codex mcp add log-triage-telemetry --url http://127.0.0.1:8765/mcp --bearer-token-env-var LOG_TRIAGE_TOKEN
codex --no-daemon

# Windows (PowerShell)
Get-Content 4-agents-and-clients/tokens.example.env | ForEach-Object { if ($_ -match '^(\w+)=(.*)$') { Set-Item -Path "Env:$($Matches[1])" -Value $Matches[2] } }
codex mcp add log-triage-telemetry --url http://127.0.0.1:8765/mcp --bearer-token-env-var LOG_TRIAGE_TOKEN
codex --no-daemon
```

Codex stores this registration in its user configuration, `~/.codex/config.toml` (`$HOME\.codex\config.toml` on Windows). To have Codex ask before it runs `save_finding`, add this line to the file's new `[mcp_servers.log-triage-telemetry]` table:

```toml
default_tools_approval_mode = "writes"
```

It usually connects to its servers through a background server that keeps the environment it started with, not this terminal's, so `--no-daemon` starts the session without it and the token comes from this terminal. Inspect `/mcp` in the fresh session and use the lesson's question. The chat instruction to use only this server's tools is a workflow rule, not an operating-system sandbox. Verify the tool transcript before counting the run as MCP-only evidence.

## Langfuse and the local viewer

The host does not start the HTTP server, so telemetry settings belong in the server terminal. Stop the server normally, then create a Langfuse Cloud account, an organization and a project named `LogTriagePractice`. In the project's settings, under API Keys, create a key pair: a public key `pk-lf-...` and a secret key `sk-lf-...`. Pick an expiration.

The secret key works as a password to your Langfuse project, so keep the pair where passwords live, in your system's credential store: the Keychain on macOS, the desktop keyring on Linux, and on Windows SecretStore, an encrypted vault file for your user that PowerShell manages. A `.env` file would hold the keys in plain text, one `git add` away from a commit. Store the pair once, as one value: the public key, a colon and the secret key (`pk-lf-...:sk-lf-...`):

```bash
# Run once, in any terminal.
# macOS: your login Keychain; asks twice and shows nothing
security add-generic-password -a "$USER" -s langfuse-api-key -w

# Linux: your desktop keyring; asks once and shows nothing
secret-tool store --label=langfuse-api-key service langfuse-api-key account "$USER"

# Windows (PowerShell): install PowerShell 7 once, then in a new pwsh window install Microsoft's secret modules, let the vault open without a password and store the key pair
winget install --id Microsoft.PowerShell --source winget
Install-Module Microsoft.PowerShell.SecretManagement, Microsoft.PowerShell.SecretStore -Scope CurrentUser
Register-SecretVault -Name SecretStore -ModuleName Microsoft.PowerShell.SecretStore -DefaultVault
Set-SecretStoreConfiguration -Authentication None
Set-Secret -Name langfuse-api-key
```

- macOS: if your Keychain already holds a `langfuse-api-key` item, the command stops with `The specified item already exists in the keychain.` Delete the old item with `security delete-generic-password -a "$USER" -s langfuse-api-key`, then store the new pair.
- Linux: `secret-tool` comes in the `libsecret-tools` package on Debian and Ubuntu (`sudo apt install libsecret-tools`) and in `libsecret` on Fedora, and it needs a desktop session running GNOME Keyring or KWallet, unlocked at login.
- Windows: PowerShell 7 (`pwsh`, 7.3 or later) installs next to the Windows PowerShell that ships with Windows, and every Windows line in this practice runs in it. Microsoft now maintains both secret modules for security and critical bug fixes only. If SecretStore already keeps a secret of yours this way, run only the `Set-Secret` line.
- Windows: `Set-SecretStoreConfiguration -Authentication None` asks you to confirm, then creates the encrypted vault file and asks you twice for its new password. After that, no PowerShell session asks for the password again, so a new terminal loads the keys with one line. Microsoft's docs advise against this setting for important secrets, and this key pair is for a free Langfuse project, expires on the date you picked, and goes in the clean-up below. `Set-Secret` then shows only asterisks as you paste.

Check that the pair is stored. The check prints `stored` only when the item exists, and never the keys:

```bash
# Run in any terminal.
# macOS
security find-generic-password -a "$USER" -s langfuse-api-key >/dev/null && echo stored

# Linux
secret-tool lookup service langfuse-api-key account "$USER" >/dev/null && echo stored

# Windows (PowerShell)
if (Get-SecretInfo -Name langfuse-api-key) { 'stored' }
```

```text
stored
```

In the server terminal, load the pair from the store into `LANGFUSE_AUTH_STRING`, encoded for Basic auth. The variable lasts as long as the terminal, so a new terminal needs this line again:

```bash
# Run from the repository root, server terminal.
# macOS
export LANGFUSE_AUTH_STRING="$(printf %s "$(security find-generic-password -a "$USER" -s langfuse-api-key -w)" | base64)"

# Linux
export LANGFUSE_AUTH_STRING="$(printf %s "$(secret-tool lookup service langfuse-api-key account "$USER")" | base64 -w 0)"

# Windows (PowerShell)
$env:LANGFUSE_AUTH_STRING = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((Get-Secret -Name langfuse-api-key -AsPlainText)))
```

Then set the exporter variables and restart:

```bash
# Run from the repository root, server terminal.
# macOS and Linux
unset OTEL_EXPORTER_OTLP_TRACES_ENDPOINT OTEL_EXPORTER_OTLP_TRACES_HEADERS
export OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel
export OTEL_SERVICE_NAME=log-triage
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic $LANGFUSE_AUTH_STRING,x-langfuse-ingestion-version=4"
uv run --project solution log-triage --root s3_logs --reports reports --http 127.0.0.1:8765 --log-level debug

# Windows (PowerShell)
Remove-Item Env:OTEL_EXPORTER_OTLP_TRACES_ENDPOINT, Env:OTEL_EXPORTER_OTLP_TRACES_HEADERS -ErrorAction Ignore
$env:OTEL_EXPORTER_OTLP_ENDPOINT = 'https://cloud.langfuse.com/api/public/otel'
$env:OTEL_SERVICE_NAME = 'log-triage'
$env:OTEL_EXPORTER_OTLP_HEADERS = "Authorization=Basic $env:LANGFUSE_AUTH_STRING,x-langfuse-ingestion-version=4"
uv run --project solution log-triage --root s3_logs --reports reports --http 127.0.0.1:8765 --log-level debug
```

Use the host for your account's region: the EU base URL above, `cloud.langfuse.com`, becomes `us.cloud.langfuse.com` in the US region. It intentionally omits `/v1/traces`. The exporter appends it. The `x-langfuse-ingestion-version=4` header makes the spans show up at once. The keys live in your credential store and are loaded into the server terminal only: keep them out of source, `.env` files, screenshots and transcripts.

After a successful tool call, open `LogTriagePractice` in Langfuse and inspect the `list_logs` observation and the observations under it. Langfuse shows each span as an observation, keeps its duration and IDs and the service name and version, makes the call an observation of type tool, named after the tool, from `gen_ai.operation.name` set to `execute_tool`, and keeps the attributes it doesn't map on the observation's Attributes tab, `error.type` and the `logtriage.*` counters included. A refusal on this server shows there as an error, because Langfuse takes an observation's level from the span's status. Each Inspector command opens its own session, so `server/discover` and `tools/list` appear as observations of their own beside the tool call: filter on type tool.

To read the counters and `error.type` in the local viewer, stop the server normally, start the local receiver from [README.md](README.md), restart the server with its endpoint, and repeat the call: the counters are the same for the same arguments.

If a host supplies a sampled parent that never reaches Langfuse, the server's spans still arrive, but they show cut off from the host's spans. Use the local receiver to inspect missing-parent traces, or configure host export to the same backend with its documented settings. Keep the server's propagation behavior unchanged.

## Correct a registration and clean up

If you used the wrong address or project, exit the host and remove only the entry created for this exercise, then repeat the add command with the intended values:

```bash
# Run from the repository root, Claude Code registration.
claude mcp remove log-triage-telemetry --scope project
```

```bash
# Run from any folder, Codex registration.
codex mcp remove log-triage-telemetry
```

These commands remove a registration, not your project or findings. Preserve unrelated server entries. At the end, stop the HTTP server first so it flushes, then stop the local receiver. Clear the variables in each terminal that used them:

```bash
# Run in each terminal used for the practice.
# macOS and Linux
unset LANGFUSE_AUTH_STRING OTEL_EXPORTER_OTLP_ENDPOINT OTEL_EXPORTER_OTLP_TRACES_ENDPOINT
unset OTEL_EXPORTER_OTLP_HEADERS OTEL_EXPORTER_OTLP_TRACES_HEADERS OTEL_SERVICE_NAME
unset LOG_TRIAGE_TOKENS LOG_TRIAGE_TOKEN LOG_TRIAGE_VIEWER_TOKEN

# Windows (PowerShell)
Remove-Item Env:LANGFUSE_AUTH_STRING, Env:OTEL_EXPORTER_OTLP_ENDPOINT, Env:OTEL_EXPORTER_OTLP_TRACES_ENDPOINT -ErrorAction Ignore
Remove-Item Env:OTEL_EXPORTER_OTLP_HEADERS, Env:OTEL_EXPORTER_OTLP_TRACES_HEADERS, Env:OTEL_SERVICE_NAME -ErrorAction Ignore
Remove-Item Env:LOG_TRIAGE_TOKENS, Env:LOG_TRIAGE_TOKEN, Env:LOG_TRIAGE_VIEWER_TOKEN -ErrorAction Ignore
```

Then delete the practice's key pair in Langfuse, in the project's settings under API Keys, and remove it from your credential store:

```bash
# Run in any terminal.
# macOS
security delete-generic-password -a "$USER" -s langfuse-api-key

# Linux
secret-tool clear service langfuse-api-key account "$USER"

# Windows (PowerShell)
Remove-Secret -Name langfuse-api-key -Vault SecretStore
```
