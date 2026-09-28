# Checklist: the surface and the contract

**Related**:

> [README](README.md): The tasks these items close
> [interface](interface.md): Your design, which the Inspector items compare against

Tick each item when it is true, then commit. Where an item asks for a note, write it under the item.

## Links
**Internal**:

- `1-surface-and-contract/README.md`
- `1-surface-and-contract/CONTRACT.md`

## Design
- [ ] Every row of `interface.md` is filled in.
- [ ] `interface.md` names where your design differs from `CONTRACT.md`, or says it doesn't.

## Server
- [ ] `uv run --project 1-surface-and-contract/checks pytest 1-surface-and-contract/checks` passes, run from the repository root.
- [ ] Every checkpoint in the README was true when its prompt finished. Note any that wasn't, and what you did about it.
- [ ] Nothing in `solution/` names a host, a date, an address or a message from `s3_logs/`.
- [ ] `solution/README.md` says how to install and run your server.

## Inspector
- [ ] `tools/list` on `log-triage` shows four tools, each with the title, annotations, input schema and output schema that `CONTRACT.md` gives.
- [ ] `tools/list` on `log-triage-read-only` shows the same tools without `save_finding`.
- [ ] The `summarize_logs` call returns `structuredContent` and one text block with the same object.
- [ ] What the Inspector shows matches your `interface.md`. Note what surprised you.

## Case
- [ ] The agent had no tools except your server's.
- [ ] The finding in `reports/` explains why the customer got an error page, and when.
- [ ] Every piece of evidence names a file and a line, and you checked that at least three of those lines say what the finding claims.
- [ ] Note which tools the agent called, and anything you changed after watching it.

## Wrap-up
- [ ] Time spent on this practice, in minutes:
- [ ] `solution/`, `reports/` and this folder are committed.
