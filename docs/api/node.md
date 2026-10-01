# Node API v1

What each node writes for the rest of the OS to read.
Schema: [`rabbitsoftware-node-api-v1`](../../schemas/rabbitsoftware-node-api-v1.schema.json).

| Definition | Where | Contents |
|---|---|---|
| `status` | `autonomous/node-N/status.json`, rewritten every 30 s | node id, boot id, times, counters, `chain_blocks`, `chain_ok`, `chain_msg`, peers, research ledger size and health |
| `chainFile` / `block` | `autonomous/node-N/chain_node-N.json` | `{"blocks": [...]}`; each block has `index`, `previous_hash`, `payload`, `timestamp`, `block_hash` (SHA-256) |
| `researchEvent` | inside blocks on the shared research chain | every event: `schema_version` 1, `event_id` (32 hex), `created_at`, `classification` `"public"`, and an `event_type` |
| `dataHashEvent` | `public_data_hash` | a fingerprint of public data; kinds `dataset`, `biological_sequence`, `research_file`, `integrity_report`, `code_release` (a release's code manifest: the record of its authorship) |
| `noteEvent` | `public_record_note` | a challenge, improvement or reply about an entry, up to 1,000 characters |

Each event type's detailed rules (fields, lengths, required confirmations, refusing personal information)
are enforced by `research_provenance.validate_public_provenance` on every node. This schema fixes the
shape that any reader can rely on.

Nodes also talk to each other over their own encrypted peer protocol (`network_node.py`). That protocol is
internal to the node network, so it isn't part of this API.
