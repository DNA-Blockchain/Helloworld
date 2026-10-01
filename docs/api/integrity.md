# Integrity v1

What the integrity team writes.
Schema: [`rabbitsoftware-integrity-v1`](../../schemas/rabbitsoftware-integrity-v1.schema.json).

## `report`: an integrity report (`rabbitsoft/integrity.py`)

The report is saved as `autonomous/integrity/integrity-<time>.json`, with a readable `.md` beside it.

```json
{"schema": "rabbitsoft-integrity.v1", "created_at": "...", "ok": true,
 "checks": [{"role": "records and data", "name": "Node chains", "status": "ok", "lines": ["node-0: ..."]}]}
```

- **`role`** is `records and data` or `code enforcement`.
- **`status`** is `ok`, `problem` or `skipped`.
- **`ok`** is true when no check found a problem.
- **Fingerprint:** the report file's SHA-256 is its fingerprint. Only that fingerprint can go on the chain, as a `public_data_hash` of kind `integrity_report` (see [node.md](node.md)).

## `toolSurvey`: the tools the OS needs (`rabbitsoft/toolchain.py`, `survey_json`)

```json
{"schema": "rabbitsoft-tools.v1",
 "tools": [{"key": "qemu", "name": "QEMU", "needed_for": "...", "here": false, "wsl": true}]}
```

`wsl` is `null` when there's no WSL to look in.
