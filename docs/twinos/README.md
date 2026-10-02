# TwinOS: the universal agent network

TwinOS lets a personal digital twin work as one agent among many: other twins, coding and development
agents, terminal and automation agents, MicroPython edge devices and GPU workers. Every agent states
what it can do and speaks the same message format, **U-A2A 1.0**. Each agent decides for itself what it
will run. The code is in [`twinos/`](../../twinos/), and the message contract is
[`rabbitsoftware-agent-message-v1`](../../schemas/rabbitsoftware-agent-message-v1.schema.json)
([API page](../api/agent-message.md)).

```
other agent ──U-A2A──▶ this agent: verify signature, freshness, nonce ─▶ pinned sender? ─▶ task type offered?
                                                                                │
                              policy allows its capability? ──yes──▶ run ──▶ TASK_RESULT
                                         │no
                                         ▼
                        queue ─▶ owner: python -m twinos approve|deny ─▶ run (on approve) ─▶ result kept for the sender
```

The first part (this page) covers identity, messages, trust, approvals and the network. The next part
adds the sensors (EEG through BrainFlow or LSL; RF, audio and MicroPython adapters), the handlers that do
real work, and learning runs.

## Using it

```powershell
python -m twinos status                                   # id, key, peers, waiting tasks, ledger check
python -m twinos serve                                    # listen on 127.0.0.1:8790

# A second agent on this PC, in its own folder:
python -m twinos --home autonomous/twinos-coder --name Coder --type coding_agent discover 127.0.0.1 8790
#   prints the agent's id and key, and the exact trust command to pin it
python -m twinos --home autonomous/twinos-coder trust agent-... <key>   # the coder trusts the twin's replies
python -m twinos trust agent-... <coder key>                            # the twin accepts the coder's tasks
python -m twinos --home autonomous/twinos-coder capabilities 127.0.0.1 8790 agent-...
python -m twinos --home autonomous/twinos-coder send 127.0.0.1 8790 agent-... status "how are you"

python -m twinos tasks                                    # tasks other agents sent here
python -m twinos approve task-...                         # runs it; written to the activity log
python -m twinos ledger                                   # the local ledger and whether it verifies
```

## How it works

| Part | File | What it does |
|---|---|---|
| Identity | `twinos/identity.py` | A persistent Ed25519 key in `autonomous/twinos/identity.pem` (PKCS#8, from `crypto_layer.py`). The agent id is `agent-` plus the first 24 hex digits of the key's SHA-256, so nobody can claim an id without its key. |
| Messages | `twinos/protocol.py` | Each message is signed with Ed25519 over its canonical JSON. A receiver checks the schema, that the id matches the key, the signature, a ±120 s clock window and a nonce not seen in that window. On the wire: a 4-byte length, then UTF-8 JSON, up to 1 MiB, with a 10 s read timeout. |
| Trust | `twinos/trust.py` | Peer keys pinned by the owner in `peers.json`. Anyone may ask who an agent is (`IDENTITY_REQUEST`); everything else needs a pinned sender signing with the pinned key. Nothing is ever pinned automatically. |
| Policy | `twinos/tasks.py` | Each task type needs one capability. `policy.json` lists those that run without asking (default: `read_context` only). Running code, terminal commands, writing files, network operations, MicroPython and GPU jobs always wait for approval, whatever the file says. |
| Tasks | `twinos/tasks.py` | The receiver builds each task from only its type, description (up to 2,000 characters) and parameters (up to 16 KiB), so a sender can't mark its own task approved. At most 100 tasks per peer may wait; one message makes at most one task. |
| Node | `twinos/node.py` | Answers messages, runs or queues tasks, and serves TCP on `127.0.0.1:8790` (the node network uses 8765). It offers only task types it has a handler for; in this part that is `status`. |
| Ledger | `autonomous/twinos/ledger.jsonl` | The hash-chained ledger from `neurovisual/provenance.py`, with keyed digests (HMAC-SHA-256) of messages from pinned peers and of every task decision and result. It never holds their content, and it isn't published. |

The server and the owner's commands are separate processes, so `tasks.json`, `peers.json` and the ledger
are re-read under a lock file for every change. A peer pinned while the server runs is trusted at once.
Changes to `policy.json` take effect when the server restarts.

## Limits

- **Signed, not encrypted.** Messages are authenticated and replay-protected, but anyone on the path can
  read them. Keep the default `127.0.0.1`, or use `--allow-remote` only on a network you trust, until
  encrypted sessions are added (the node network's X25519 + AES-GCM handshake is the model).
- **Replays across a restart.** Nonces are kept in memory for 120 s. A task request replayed right
  after a restart is still refused, because its message id already made a task; other request types are
  read-only.
- **No rate limit.** Unsigned and untrusted messages are answered but not stored. A pinned peer can
  queue at most 100 tasks. There's no per-connection rate limit yet (32 connections at a time).
- **Trust is manual.** Check the key that `discover` prints through another channel before pinning,
  because whoever answers on that address could be an impostor.
- **Clocks.** Both agents' clocks must be within 120 s of each other.
