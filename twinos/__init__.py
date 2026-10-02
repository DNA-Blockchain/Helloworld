"""TwinOS: a personal digital twin as one agent in a network of agents that talk U-A2A.

    agents (twins, coding, development, terminal, MicroPython, GPU...) <-> U-A2A messages <-> this node
      -> receiver's own policy -> run now | queue for the owner's approval -> result -> local ledger

    python -m twinos status                     this agent: id, key fingerprint, peers, tasks, ledger
    python -m twinos serve                      listen on 127.0.0.1:8790 for U-A2A messages
    python -m twinos discover 127.0.0.1 8791    ask another agent who it is
    python -m twinos trust <agent-id> <key>     pin a peer's Ed25519 key; only pinned peers can send tasks
    python -m twinos send 127.0.0.1 8791 status "how are you"
    python -m twinos tasks | approve <id> | deny <id>

Every message is signed with the sender's Ed25519 key (crypto_layer.py) and checked against the key
pinned for that agent, with a nonce and a time window so a captured message can't be replayed. The
receiver decides what runs: a task's capability is either allowed by its own policy or queued until the
owner approves it, whatever the sender asked for. Approvals are written to the activity log.

Data handling: the node listens on this PC only unless started with --allow-remote. The local ledger
(autonomous/twinos/ledger.jsonl, gitignored) holds keyed digests of messages and task results, never
their content, and nothing is published to the shared research chain. docs/twinos/README.md has the
design, the protocol and its limits.
"""
from .identity import AgentIdentity
from .node import AgentNode
from .protocol import PROTOCOL, PROTOCOL_VERSION

__all__ = ["AgentIdentity", "AgentNode", "PROTOCOL", "PROTOCOL_VERSION"]
