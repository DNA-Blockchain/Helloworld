"""A live latent stream for game engines and other local apps: one JSON datagram per step over UDP.

    {"t": ..., "mode": "memory", "event_id": ..., "confidence": 0.86, "weights": [e, i, g],
     "camera": [8], "motion": [8], "depth": [8], "lighting": [8], "continuity": [8], "scene": [64],
     "model_version": "1.1.0"}

UDP on 127.0.0.1 by default: Unity (UdpClient), Unreal (FUdpSocketReceiver), Godot (PacketPeerUDP),
TouchDesigner and Python can all read it with a few lines (docs/neurovisual/SDK.md). Datagrams stay on
this machine unless you name another host and pass allow_remote=True.
"""
from __future__ import annotations

import json
import socket

from .generators import LOCAL_HOSTS


class LatentStream:
    def __init__(self, host: str = "127.0.0.1", port: int = 9555, allow_remote: bool = False):
        if host not in LOCAL_HOSTS and not allow_remote:
            raise ValueError(f"streaming to {host} would send live state off this machine; pass allow_remote=True")
        self.address = (host, port)
        self.sock = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_DGRAM)
        self.sent = 0

    @staticmethod
    def message(state) -> dict:
        r = lambda values: [round(float(x), 4) for x in values]
        return {"t": state.timestamp, "mode": state.mode, "event_id": state.event_id,
                "confidence": round(state.confidence, 4),
                "weights": [state.evidence_weight, state.inference_weight, state.generative_weight],
                "camera": r(state.camera), "motion": r(state.motion), "depth": r(state.depth),
                "lighting": r(state.lighting), "continuity": r(state.continuity), "scene": r(state.scene),
                "model_version": state.model_version}

    def send(self, state) -> None:
        self.sock.sendto(json.dumps(self.message(state), separators=(",", ":")).encode("utf-8"), self.address)
        self.sent += 1

    def close(self) -> None:
        self.sock.close()
