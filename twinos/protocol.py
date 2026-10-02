"""U-A2A 1.0: the message every agent sends, how it is signed and checked, and how it travels.

    {"protocol": "U-A2A", "protocol_version": "1.0", "message_id": <32 hex>, "message_type": ...,
     "sender_agent": "agent-...", "sender_type": "digital_twin", "sender_key": <Ed25519 public key, hex>,
     "receiver_agent": "agent-..." | "any", "timestamp": <unix seconds>, "nonce": <32 hex>,
     "payload": {...}, "signature": <Ed25519 signature, hex>}

The signature covers the canonical JSON (sorted keys, no spaces) of every field except "signature".
A receiver accepts a message only if it fits schemas/rabbitsoftware-agent-message-v1, the sender id
matches the key, the signature verifies, the timestamp is within WINDOW seconds of its own clock, and
the nonce hasn't been seen in that window. Whether the sender is trusted is a separate check (trust.py).

On the wire each message is a 4-byte big-endian length followed by that many bytes of UTF-8 JSON, at
most MAX_MESSAGE bytes; one request and one reply per connection.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import struct
import threading
import time

import crypto_layer
from rabbitsoft import contracts

from .identity import agent_id_for

PROTOCOL, PROTOCOL_VERSION = "U-A2A", "1.0"
API = "agent-message-v1"
MESSAGE_TYPES = ("IDENTITY_REQUEST", "IDENTITY_RESPONSE", "CAPABILITY_REQUEST", "CAPABILITY_RESPONSE",
                 "TASK_REQUEST", "TASK_STATUS_REQUEST", "APPROVAL_REQUIRED", "TASK_RESULT", "TASK_REJECTED", "ERROR")
MAX_MESSAGE = 1024 * 1024
WINDOW = 120.0                       # seconds of clock difference accepted, and how long nonces are kept
READ_TIMEOUT = 10.0


class ProtocolError(ValueError):
    """A message that can't be accepted; the text says why and is safe to send back."""


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def create(identity, message_type: str, receiver: str, payload: dict, now: float | None = None) -> dict:
    if message_type not in MESSAGE_TYPES:
        raise ValueError(f"unknown message type {message_type!r}")
    body = {"protocol": PROTOCOL, "protocol_version": PROTOCOL_VERSION, "message_id": secrets.token_hex(16),
            "message_type": message_type, "sender_agent": identity.agent_id, "sender_type": identity.agent_type,
            "sender_key": identity.public_key, "receiver_agent": receiver,
            "timestamp": time.time() if now is None else now, "nonce": secrets.token_hex(16), "payload": payload}
    body["signature"] = identity.sign(canonical(body))
    return body


class ReplayGuard:
    """Nonces seen in the last WINDOW seconds. A message older than that is rejected by its timestamp, so
    forgetting older nonces is safe."""

    def __init__(self, window: float = WINDOW):
        self.window, self.seen = window, {}
        self._lock = threading.Lock()          # the server answers messages on worker threads

    def check_and_remember(self, nonce: str, now: float) -> None:
        with self._lock:
            self.seen = {n: t for n, t in self.seen.items() if now - t <= self.window}
            if nonce in self.seen:
                raise ProtocolError("this message was already received (replay)")
            self.seen[nonce] = now


def verify(message, replay: ReplayGuard, now: float | None = None) -> dict:
    """Returns the message if it is well formed, signed by the key it carries, and fresh; else raises
    ProtocolError."""
    problems = contracts.errors(message, API, "message")
    if problems:
        raise ProtocolError("message doesn't fit U-A2A 1.0: " + "; ".join(problems[:3]))
    if agent_id_for(message["sender_key"]) != message["sender_agent"]:
        raise ProtocolError("sender_agent doesn't match sender_key")
    body = {k: v for k, v in message.items() if k != "signature"}
    try:
        key = crypto_layer.signing_pub_from_hex(message["sender_key"])
        signature = bytes.fromhex(message["signature"])
    except ValueError as error:
        raise ProtocolError(f"bad key or signature encoding: {error}") from error
    if not crypto_layer.verify(key, canonical(body), signature):
        raise ProtocolError("signature doesn't verify")
    now = time.time() if now is None else now
    if abs(now - message["timestamp"]) > replay.window:
        raise ProtocolError(f"timestamp is more than {replay.window:.0f} s from this agent's clock")
    replay.check_and_remember(message["nonce"], now)
    return message


# -- framing -------------------------------------------------------------------------------------------
def frame(message: dict) -> bytes:
    data = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_MESSAGE:
        raise ValueError(f"message is {len(data)} bytes; the limit is {MAX_MESSAGE}")
    return struct.pack(">I", len(data)) + data


async def read_frame(reader: asyncio.StreamReader, timeout: float = READ_TIMEOUT):
    """Reads one framed message. Raises ProtocolError for an oversized or malformed one, and
    asyncio.IncompleteReadError / TimeoutError when the peer stops sending."""
    header = await asyncio.wait_for(reader.readexactly(4), timeout)
    (length,) = struct.unpack(">I", header)
    if length > MAX_MESSAGE:
        raise ProtocolError(f"message is {length} bytes; the limit is {MAX_MESSAGE}")
    data = await asyncio.wait_for(reader.readexactly(length), timeout)
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ProtocolError("message isn't UTF-8 JSON") from error
