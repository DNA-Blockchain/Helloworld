"""The agent node: answers U-A2A messages, runs or queues tasks, and serves them over TCP.

    IDENTITY_REQUEST      anyone          -> IDENTITY_RESPONSE (id, name, type, key, OS, architecture)
    CAPABILITY_REQUEST    pinned peers    -> CAPABILITY_RESPONSE (task types it can run, which run without asking)
    TASK_REQUEST          pinned peers    -> TASK_RESULT (allowed by policy) | APPROVAL_REQUIRED | TASK_REJECTED
    TASK_STATUS_REQUEST   the task's sender -> TASK_RESULT (its status, and its result once finished)

A node only offers task types it has a handler for; a request for any other type is rejected rather
than queued and later "completed" with nothing done. The ledger records keyed digests of messages from
pinned peers and of every task decision and result; unsigned or untrusted traffic is answered but not
recorded, so it can't fill the disk.
"""
from __future__ import annotations

import asyncio
import ipaddress
import platform
import secrets
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from neurovisual.provenance import ProvenanceLedger, load_or_create_key
from rabbitsoft.tools import Paths

from . import handlers, protocol
from .identity import AgentIdentity
from .locking import locked
from .protocol import ProtocolError, ReplayGuard
from .tasks import TASKS, Policy, Task, TaskQueue, TaskRejected, build_task
from .trust import TrustStore

DEFAULT_PORT = 8790                  # network_os.NetworkNode uses 8765
MAX_CONNECTIONS = 32
Handler = Callable[[Task], dict]


def is_local(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class AgentNode:
    def __init__(self, home: Path | None = None, paths: Paths | None = None, name: str = "Personal Digital Twin",
                 agent_type: str = "digital_twin"):
        self.paths = paths or Paths()
        self.home = home or self.paths.autonomous / "twinos"
        self.identity = AgentIdentity(self.home, name=name, agent_type=agent_type)
        self.trust = TrustStore(self.home / "peers.json")
        self.policy = Policy(self.home / "policy.json")
        self.tasks = TaskQueue(self.home / "tasks.json")
        self.replay = ReplayGuard()
        self.ledger_path = self.home / "ledger.jsonl"
        self.ledger_key = load_or_create_key(self.home / "ledger.key")
        self.context_path = self.home / "context.jsonl"
        self.handlers: dict[str, Handler] = {
            "status": self._status_task,
            "update_context": handlers.update_context(self.context_path),
            "run_tests": handlers.run_tests(self.paths.root),
            "gpu_training": handlers.gpu_training(self.paths.autonomous / "neurovisual"),
            "research_search": handlers.research_search(self.paths.root),
        }
        self.device = None

    def attach_micropython(self, device) -> None:
        """Offers micropython_command tasks, sent to this board (sensors.MicroPythonSerial)."""
        self.device = device
        self.handlers["micropython_command"] = handlers.micropython_command(device)

    # -- records ------------------------------------------------------------------------------------------
    def ledger(self) -> ProvenanceLedger:
        return ProvenanceLedger(self.ledger_key, self.ledger_path, name="twinos")

    def record(self, kind: str, data, metrics: dict) -> dict:
        """Appends to the ledger under the lock, re-reading it first so two processes extend one chain."""
        with locked(self.ledger_path):
            return self.ledger().append(kind, data=data, model_sha256="", config={}, metrics=metrics)

    def log(self, action: str, details: dict) -> None:
        """The owner's decisions go to the shared activity log, like every other yes in RabbitSoftware."""
        from audit_trail import AuditTrail

        AuditTrail(str(self.paths.audit)).log("twinos", action, self.identity.agent_id, details)

    # -- what this agent is -------------------------------------------------------------------------------
    def describe(self) -> dict:
        return {"agent_id": self.identity.agent_id, "name": self.identity.name,
                "agent_type": self.identity.agent_type, "public_key": self.identity.public_key,
                "operating_system": platform.system(), "architecture": platform.machine(),
                "protocol": protocol.PROTOCOL, "protocol_version": protocol.PROTOCOL_VERSION}

    def capabilities(self) -> dict:
        offered = sorted(self.handlers)
        return {"task_types": offered, "automatic": [t for t in offered if self.policy.allows(TASKS[t])]}

    def status(self) -> dict:
        ok, problems = self.ledger().verify()
        return {**self.describe(), "pinned_peers": len(self.trust.peers),
                "waiting_approval": len(self.tasks.waiting()), "ledger_entries": len(self.ledger().entries),
                "ledger_valid": ok, "ledger_problems": problems[:5], **self.capabilities(),
                "policy_ignored": self.policy.ignored}

    def _status_task(self, task: Task) -> dict:
        s = self.status()
        return {"success": True, "agent_id": s["agent_id"], "agent_type": s["agent_type"],
                "waiting_approval": s["waiting_approval"], "task_types": s["task_types"]}

    # -- messages -----------------------------------------------------------------------------------------
    def reply(self, message_type: str, to: str, payload: dict) -> dict:
        return protocol.create(self.identity, message_type, to, payload)

    def handle(self, message, now: float | None = None) -> dict:
        """Answers one incoming message. Never raises for anything a peer can send."""
        sender = message.get("sender_agent", "unknown") if isinstance(message, dict) else "unknown"
        sender = sender if isinstance(sender, str) and len(sender) < 100 else "unknown"
        try:
            protocol.verify(message, self.replay, now)
        except ProtocolError as error:
            return self.reply("ERROR", sender, {"reason": "invalid_message", "detail": str(error)})
        kind, payload = message["message_type"], message["payload"]
        if message["receiver_agent"] not in (self.identity.agent_id, "any"):
            return self.reply("ERROR", sender, {"reason": "wrong_receiver", "detail": "not addressed to this agent"})
        if kind == "IDENTITY_REQUEST":
            return self.reply("IDENTITY_RESPONSE", sender, {"agent": self.describe()})
        if message["receiver_agent"] != self.identity.agent_id:
            return self.reply("ERROR", sender, {"reason": "wrong_receiver", "detail": "only discovery may be sent to any agent"})
        if not self.trust.is_trusted(sender, message["sender_key"]):
            return self.reply("ERROR", sender, {"reason": "not_trusted",
                                                "detail": "this agent's owner hasn't pinned your key (python -m twinos trust)"})
        self.record("message_received", message, {"message_type": kind, "sender_agent": sender})
        if kind == "CAPABILITY_REQUEST":
            return self.reply("CAPABILITY_RESPONSE", sender, self.capabilities())
        if kind == "TASK_REQUEST":
            return self._task_request(message)
        if kind == "TASK_STATUS_REQUEST":
            task_id = payload.get("task_id")
            task = self.tasks.get(task_id) if isinstance(task_id, str) else None
            if task is None or task.source_agent != sender:
                return self.reply("ERROR", sender, {"reason": "unknown_task", "detail": "no such task from this agent"})
            return self.reply("TASK_RESULT", sender, self._task_view(task))
        return self.reply("ERROR", sender, {"reason": "unexpected_message", "detail": f"{kind} isn't a request"})

    def _task_request(self, message: dict) -> dict:
        sender, payload = message["sender_agent"], message["payload"]
        try:
            task = build_task(payload.get("task_type"), payload.get("description", ""), payload.get("parameters", {}),
                              sender, message["message_id"])
            if task.task_type not in self.handlers:
                raise TaskRejected(f"this agent can't run {task.task_type} tasks")
            automatic = self.policy.allows(task.capability)
            if automatic:
                task.status = "approved"
            self.tasks.add(task)
        except TaskRejected as error:
            return self.reply("TASK_REJECTED", sender, {"reason": str(error)})
        self.record("task_queued", asdict(task), {"task_type": task.task_type, "sender_agent": sender,
                                                  "automatic": automatic})
        if not automatic:
            return self.reply("APPROVAL_REQUIRED", sender, self._task_view(task))
        return self.reply("TASK_RESULT", sender, self._task_view(self.run(task)))

    @staticmethod
    def _task_view(task: Task) -> dict:
        view = {"task_id": task.task_id, "task_type": task.task_type, "capability": task.capability,
                "status": task.status}
        if task.result is not None:
            view["result"] = task.result
        return view

    # -- running tasks ------------------------------------------------------------------------------------
    def run(self, task: Task) -> Task:
        try:
            result = self.handlers[task.task_type](task)
        except Exception as error:   # a handler's failure is the task's result, not the server's
            result = {"success": False, "error": f"{type(error).__name__}: {error}"}
        task = self.tasks.finish(task.task_id, result)
        self.record("task_result", result, {"task_id": task.task_id, "task_type": task.task_type,
                                            "status": task.status})
        return task

    def run_local(self, task_type: str, description: str, parameters: dict) -> Task:
        """The owner's own request on this PC (e.g. python -m twinos learn): their command is the approval."""
        if task_type not in self.handlers:
            raise TaskRejected(f"this agent can't run {task_type} tasks")
        task = build_task(task_type, description, parameters, self.identity.agent_id, secrets.token_hex(16))
        task.status = "approved"
        self.tasks.add(task)
        self.log("run task", {"task_id": task.task_id, "task_type": task_type, "capability": task.capability})
        self.record("task_queued", asdict(task), {"task_type": task_type, "sender_agent": "owner", "automatic": False})
        return self.run(task)

    def propose(self, task_type: str, description: str, parameters: dict) -> Task:
        """A task the twin suggests for itself (a state change): it runs only if the policy allows its
        capability, otherwise it waits for the owner like any other agent's request."""
        task = build_task(task_type, description, parameters, self.identity.agent_id, secrets.token_hex(16))
        automatic = task_type in self.handlers and self.policy.allows(task.capability)
        if automatic:
            task.status = "approved"
        self.tasks.add(task)
        self.record("task_queued", asdict(task), {"task_type": task_type, "sender_agent": "self", "automatic": automatic})
        return self.run(task) if automatic else task

    def sense(self, sources: list, steps: int, interval: float, estimator=None, on_state=None) -> list:
        """Reads every source `steps` times, `interval` seconds apart, and keeps the twin's state. A confirmed
        change against the person's baseline becomes a proposed update_context task, never an action."""
        from .state import StateEstimator

        estimator = estimator or StateEstimator()
        states = []
        for step in range(steps):
            state = estimator.update([source.observe() for source in sources])
            states.append(state)
            for name in state.changes:
                s = state.sources[name]
                summary = (f"{name} signals deviated {s.deviation:.1f} SD from this person's baseline for "
                           f"{estimator.sustain} readings (quality {s.quality:.2f}, confidence {state.confidence:.2f})")
                self.record("state_change", asdict(state), {"source": name, "confidence": state.confidence})
                self.propose("update_context", f"record a {name} state change",
                             {"category": "state_change", "summary": summary})
            if on_state:
                on_state(state)
            if interval and step < steps - 1:
                time.sleep(interval)
        return states

    def decide(self, task_id: str, approve: bool) -> Task:
        """The owner's yes or no. A yes runs the task now; both go to the activity log and the ledger."""
        task = self.tasks.decide(task_id, approve)
        details = {"task_id": task.task_id, "task_type": task.task_type, "capability": task.capability,
                   "from": task.source_agent}
        self.log("approve task" if approve else "deny task", details)
        self.record("task_decided", details, {"task_id": task_id, "approved": approve})
        return self.run(task) if approve else task

    # -- network ------------------------------------------------------------------------------------------
    async def _connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, slots) -> None:
        async with slots:
            try:
                try:
                    message = await protocol.read_frame(reader)
                except ProtocolError as error:
                    answer = self.reply("ERROR", "unknown", {"reason": "invalid_message", "detail": str(error)})
                else:
                    answer = await asyncio.to_thread(self.handle, message)
                writer.write(protocol.frame(answer))
                await writer.drain()
            except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError):
                pass                 # the peer went away; there is no one to answer
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except ConnectionError:
                    pass

    async def start(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT, allow_remote: bool = False):
        if not is_local(host) and not allow_remote:
            raise ValueError(f"listening on {host} lets other machines reach this agent; pass allow_remote=True")
        slots = asyncio.Semaphore(MAX_CONNECTIONS)
        server = await asyncio.start_server(lambda r, w: self._connection(r, w, slots), host, port)
        if not is_local(host):
            self.log("listen for remote agents", {"host": host, "port": port})
        return server


async def request(host: str, port: int, message: dict, expect: dict | None = None,
                  timeout: float = protocol.READ_TIMEOUT) -> dict:
    """Sends one message and returns the verified reply. With expect (a pinned peer: agent_id and
    public_key), the reply must be signed by that key; without it, by whatever key the reply carries,
    which is only good enough for discovery."""
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    try:
        writer.write(protocol.frame(message))
        await writer.drain()
        reply = await protocol.read_frame(reader, timeout)
    finally:
        writer.close()
    protocol.verify(reply, ReplayGuard())
    if expect and (reply["sender_agent"], reply["sender_key"]) != (expect["agent_id"], expect["public_key"]):
        raise ProtocolError(f"the reply came from {reply['sender_agent']}, not the pinned {expect['agent_id']}")
    if reply["receiver_agent"] != message["sender_agent"]:
        raise ProtocolError("the reply is addressed to another agent")
    return reply
