---
name: blockchain-dna-research
description: Use the project's JSON research interface to collect source IDs, check provenance, and interpret record counts.
---

# Blockchain-DNA research

Use `python blockchain_dna_tool.py` from the project root for structured
research or record checks. This interface complements the
`Blockchain-DNA` agent; it is a local CLI, not a browser/MCP integration or
an always-running service.

## Actions

- `research`: send a non-empty `condition` and optional `biomarker`. The
  tool calls this project's real `GrowingResearchAgent` and its existing
  source fetchers. It updates the existing `research_store.json` in the
  current working directory, returns source IDs/status, and does not write
  to a network node or chain. The project's public API connectors are
  contacted when this action is run. Do not run it unless the user asks for
  a live lookup.
- `interpret`: pass a `records` array with `source` and `id` on every
  record. The deterministic report contains counts by source, duplicate
  source/ID pairs, and records without a `url` or `source_url`. This is
  provenance bookkeeping only; it does not assess scientific validity,
  study quality, efficacy, safety, or causation.
- `execute_python`: do not execute user code unless the user explicitly
  approves the exact code/request. It requires both the CLI
  `--allow-code-execution` flag and `"user_confirmed": true` in the JSON.
  The timeout is at most five seconds and captured output is capped at
  64,000 bytes.

**Python execution is not a security sandbox. It runs with the current
user's filesystem and network permissions.** The timeout and output cap do
not prevent file, network, process, or other side effects. Never use this
action for untrusted code. Ask for approval before enabling it and disclose
the code and consequences.

## CLI examples

Offline provenance check:

```powershell
@'
{"action":"interpret","records":[{"source":"PubMed","id":"PMID:123","url":"https://pubmed.ncbi.nlm.nih.gov/123/"}]}
'@ | python blockchain_dna_tool.py
```

Live research (contacts configured public API endpoints and updates the
local store):

```powershell
'{"action":"research","condition":"breast cancer","biomarker":"BRCA1"}' |
  python blockchain_dna_tool.py
```

Explicitly enabled Python execution (unsafe; only for reviewed code):

```powershell
'{"action":"execute_python","code":"print(1 + 1)","user_confirmed":true}' |
  python blockchain_dna_tool.py --allow-code-execution
```

Input and output shapes are documented in
`schemas/blockchain-dna-tool-input.schema.json` and
`schemas/blockchain-dna-tool-output.schema.json`. Source adapters and
availability are inherited from `growing_research_agent.py`; a status of
`not_reported_by_runtime` means this version of the existing agent does not
expose per-source fetch status, not that a lookup succeeded. The existing
St. Jude adapter is an explicit no-op and is reported as `skipped`.
