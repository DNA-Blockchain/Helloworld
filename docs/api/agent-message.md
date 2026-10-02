# Agent message API v1 (U-A2A 1.0)

The messages TwinOS agents send each other (`twinos/`).
Schema: [`rabbitsoftware-agent-message-v1`](../../schemas/rabbitsoftware-agent-message-v1.schema.json).
The design and its limits are in [docs/twinos/README.md](../twinos/README.md).

| Definition | Used for | Contents |
|---|---|---|
| `message` | every message | `protocol` `"U-A2A"`, `protocol_version` `"1.0"`, `message_id` and `nonce` (32 hex), `message_type`, `sender_agent` (`agent-` + 24 hex), `sender_type`, `sender_key` (Ed25519, 64 hex), `receiver_agent`, `timestamp` (unix seconds), `payload`, `signature` (128 hex) |
| `identityPayload` | `IDENTITY_RESPONSE` | `agent`: id, name, type, public key, OS, architecture, protocol and version |
| `capabilityPayload` | `CAPABILITY_RESPONSE` | `task_types` it can run, and the `automatic` ones its policy runs without asking |
| `taskRequestPayload` | `TASK_REQUEST` | `task_type`, `description` (up to 2,000 characters), optional `parameters` |
| `taskStatusRequestPayload` | `TASK_STATUS_REQUEST` | `task_id` |
| `taskView` | `APPROVAL_REQUIRED`, `TASK_RESULT` | `task_id`, `task_type`, `capability`, `status` (`waiting_approval`, `approved`, `denied`, `completed`, `failed`), and `result` (with `success`) once it has run |
| `rejectedPayload` | `TASK_REJECTED` | `reason` |
| `errorPayload` | `ERROR` | `reason` (`invalid_message`, `wrong_receiver`, `not_trusted`, `unknown_task`, `unexpected_message`) and `detail` |

The signature is Ed25519 over the canonical JSON (sorted keys, no spaces) of every field except
`signature`. `sender_agent` must be `agent-` plus the first 24 hex digits of the SHA-256 of the raw
`sender_key`. On the wire each message is a 4-byte big-endian length followed by the UTF-8 JSON, at most
1 MiB, with one request and one reply per connection.
