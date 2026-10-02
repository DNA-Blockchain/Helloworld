"""TwinOS agent network: identity, signed U-A2A messages, trust, the receiver's policy, approvals,
the TCP transport, the ledger and the command line."""
import asyncio
import json
import struct
import time

import pytest

from rabbitsoft import contracts
from rabbitsoft.tools import Paths
from twinos import protocol
from twinos.__main__ import main
from twinos.identity import AgentIdentity, agent_id_for
from twinos.node import AgentNode, request
from twinos.protocol import ProtocolError, ReplayGuard
from twinos.tasks import MAX_DESCRIPTION, Policy


def make_paths(tmp_path):
    return Paths(root=tmp_path, autonomous=tmp_path / "autonomous", audit=tmp_path / "audit.jsonl",
                 research_store=tmp_path / "rs.json", catalog=tmp_path / "cat.sqlite3")


@pytest.fixture
def pair(tmp_path):
    """Two agents on one PC, each with its own folder; `twin` pins `coder`."""
    paths = make_paths(tmp_path)
    twin = AgentNode(home=tmp_path / "twin", paths=paths)
    coder = AgentNode(home=tmp_path / "coder", paths=paths, name="Coder", agent_type="coding_agent")
    twin.trust.pin(coder.identity.agent_id, coder.identity.public_key, "Coder", "coding_agent")
    return twin, coder


def ask(sender, receiver, message_type, payload, to=None):
    message = protocol.create(sender.identity, message_type, to or receiver.identity.agent_id, payload)
    reply = receiver.handle(message)
    contracts.validate(reply, "agent-message-v1", "message")
    return reply


# -- identity ------------------------------------------------------------------------------------------
def test_identity_persists_and_its_id_comes_from_the_key(tmp_path):
    first = AgentIdentity(tmp_path)
    second = AgentIdentity(tmp_path)
    assert first.agent_id == second.agent_id == agent_id_for(first.public_key)
    assert "PRIVATE" not in (tmp_path / "identity.json").read_text()
    with pytest.raises(ValueError, match="agent types"):
        AgentIdentity(tmp_path / "other", agent_type="overlord")


# -- messages ------------------------------------------------------------------------------------------
def test_a_signed_message_verifies_and_any_change_breaks_it(tmp_path):
    identity = AgentIdentity(tmp_path)
    message = protocol.create(identity, "TASK_REQUEST", "agent-" + "0" * 24,
                              {"task_type": "status", "description": "hi", "parameters": {}})
    contracts.validate(message, "agent-message-v1", "message")
    protocol.verify(message, ReplayGuard())
    for field, value in (("payload", {"task_type": "run_code", "description": "hi"}),
                         ("receiver_agent", "agent-" + "1" * 24), ("timestamp", message["timestamp"] + 1)):
        with pytest.raises(ProtocolError, match="signature"):
            protocol.verify({**message, field: value}, ReplayGuard())


def test_a_claimed_id_without_its_key_is_rejected(tmp_path):
    real, other = AgentIdentity(tmp_path / "a"), AgentIdentity(tmp_path / "b")
    message = protocol.create(real, "IDENTITY_REQUEST", "any", {})
    message["sender_key"] = other.public_key
    with pytest.raises(ProtocolError, match="doesn't match"):
        protocol.verify(message, ReplayGuard())


def test_replays_and_stale_messages_are_rejected(tmp_path):
    identity = AgentIdentity(tmp_path)
    guard = ReplayGuard()
    message = protocol.create(identity, "IDENTITY_REQUEST", "any", {})
    protocol.verify(message, guard)
    with pytest.raises(ProtocolError, match="replay"):
        protocol.verify(message, guard)
    old = protocol.create(identity, "IDENTITY_REQUEST", "any", {}, now=time.time() - 600)
    with pytest.raises(ProtocolError, match="clock"):
        protocol.verify(old, ReplayGuard())


def test_malformed_payloads_fail_the_schema(tmp_path):
    identity = AgentIdentity(tmp_path)
    message = protocol.create(identity, "TASK_REQUEST", "any", {"task_type": "status"})   # no description
    with pytest.raises(ProtocolError, match="doesn't fit"):
        protocol.verify(message, ReplayGuard())


# -- trust and policy ----------------------------------------------------------------------------------
def test_anyone_can_discover_but_only_pinned_peers_can_ask_for_more(pair, tmp_path):
    twin, coder = pair
    stranger = AgentNode(home=tmp_path / "stranger", paths=twin.paths)
    reply = ask(stranger, twin, "IDENTITY_REQUEST", {}, to="any")
    assert reply["message_type"] == "IDENTITY_RESPONSE"
    assert reply["payload"]["agent"]["public_key"] == twin.identity.public_key
    for kind, payload in (("CAPABILITY_REQUEST", {}),
                          ("TASK_REQUEST", {"task_type": "status", "description": "", "parameters": {}})):
        reply = ask(stranger, twin, kind, payload)
        assert reply["message_type"] == "ERROR" and reply["payload"]["reason"] == "not_trusted"
    # A pinned id with a different key is not the pinned peer.
    peers = twin.trust.peers
    peers[stranger.identity.agent_id] = {"public_key": coder.identity.public_key}
    twin.trust._save(peers)
    assert ask(stranger, twin, "CAPABILITY_REQUEST", {})["payload"]["reason"] == "not_trusted"


def test_a_running_node_sees_a_peer_the_owner_pins_later(pair, tmp_path):
    twin, _ = pair
    late = AgentNode(home=tmp_path / "late", paths=twin.paths)
    assert ask(late, twin, "CAPABILITY_REQUEST", {})["payload"]["reason"] == "not_trusted"
    AgentNode(home=twin.home, paths=twin.paths).trust.pin(late.identity.agent_id, late.identity.public_key)
    assert ask(late, twin, "CAPABILITY_REQUEST", {})["message_type"] == "CAPABILITY_RESPONSE"


def test_pinning_checks_the_key_matches_the_id(pair):
    twin, coder = pair
    with pytest.raises(ValueError, match="belongs to"):
        twin.trust.pin(coder.identity.agent_id, twin.identity.public_key)
    with pytest.raises(ValueError, match="hex"):
        twin.trust.pin(coder.identity.agent_id, "not hex")


def test_only_discovery_may_be_sent_to_any(pair):
    twin, coder = pair
    reply = ask(coder, twin, "CAPABILITY_REQUEST", {}, to="any")
    assert reply["payload"]["reason"] == "wrong_receiver"
    assert ask(coder, twin, "CAPABILITY_REQUEST", {}, to="agent-" + "f" * 24)["payload"]["reason"] == "wrong_receiver"


def test_policy_can_never_make_consequential_capabilities_automatic(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"automatic": ["read_context", "run_code", "terminal", "made_up"]}))
    policy = Policy(path)
    assert policy.allows("read_context")
    assert not policy.allows("run_code") and not policy.allows("terminal")
    assert policy.ignored == ["made_up", "run_code", "terminal"]


# -- tasks ---------------------------------------------------------------------------------------------
def test_an_automatic_task_runs_and_returns_its_result(pair):
    twin, coder = pair
    caps = ask(coder, twin, "CAPABILITY_REQUEST", {})["payload"]
    assert caps["automatic"] == ["status"] and "status" in caps["task_types"]
    reply = ask(coder, twin, "TASK_REQUEST", {"task_type": "status", "description": "how are you", "parameters": {}})
    assert reply["message_type"] == "TASK_RESULT"
    assert reply["payload"]["status"] == "completed" and reply["payload"]["result"]["success"] is True


def test_task_types_without_a_handler_are_rejected_not_faked(pair):
    twin, coder = pair
    for task_type in ("run_code", "terminal_command", "made_up", ["list"]):
        reply = ask(coder, twin, "TASK_REQUEST", {"task_type": task_type, "description": "x", "parameters": {}})
        assert reply["message_type"] in ("TASK_REJECTED", "ERROR")
    assert twin.tasks.all() == []


def test_a_sender_cannot_approve_its_own_task(pair):
    twin, coder = pair
    twin.handlers["review_code"] = lambda task: {"success": True, "reviewed": task.parameters.get("path")}
    reply = ask(coder, twin, "TASK_REQUEST", {"task_type": "review_code", "description": "review it",
                                              "parameters": {"path": "x.py"}, "requires_approval": False,
                                              "status": "approved"})
    assert reply["message_type"] == "APPROVAL_REQUIRED"
    task_id = reply["payload"]["task_id"]
    assert [t.task_id for t in twin.tasks.waiting()] == [task_id]
    status = ask(coder, twin, "TASK_STATUS_REQUEST", {"task_id": task_id})
    assert status["payload"]["status"] == "waiting_approval" and "result" not in status["payload"]

    task = twin.decide(task_id, approve=True)
    assert task.status == "completed" and task.result == {"success": True, "reviewed": "x.py"}
    status = ask(coder, twin, "TASK_STATUS_REQUEST", {"task_id": task_id})
    assert status["payload"]["result"]["reviewed"] == "x.py"
    activity = [json.loads(line) for line in twin.paths.audit.read_text().splitlines()]
    assert activity[-1]["action"] == "approve task" and activity[-1]["details"]["task_id"] == task_id
    with pytest.raises(ValueError, match="already completed"):
        twin.decide(task_id, approve=False)


def test_a_denied_task_never_runs_and_only_its_sender_can_see_it(pair, tmp_path):
    twin, coder = pair
    ran = []
    twin.handlers["review_code"] = lambda task: ran.append(task) or {"success": True}
    task_id = ask(coder, twin, "TASK_REQUEST", {"task_type": "review_code", "description": "",
                                                "parameters": {}})["payload"]["task_id"]
    assert twin.decide(task_id, approve=False).status == "denied" and ran == []
    other = AgentNode(home=tmp_path / "other", paths=twin.paths)
    twin.trust.pin(other.identity.agent_id, other.identity.public_key)
    assert ask(other, twin, "TASK_STATUS_REQUEST", {"task_id": task_id})["payload"]["reason"] == "unknown_task"


def test_a_failing_handler_is_a_failed_task(pair):
    twin, coder = pair
    twin.handlers["status"] = lambda task: 1 / 0
    reply = ask(coder, twin, "TASK_REQUEST", {"task_type": "status", "description": "", "parameters": {}})
    assert reply["payload"]["status"] == "failed"
    assert "ZeroDivisionError" in reply["payload"]["result"]["error"]


def test_oversized_or_wrong_inputs_are_rejected(pair):
    twin, coder = pair
    long = ask(coder, twin, "TASK_REQUEST", {"task_type": "status", "description": "x" * (MAX_DESCRIPTION + 1)})
    assert long["message_type"] == "ERROR"                   # the schema caps descriptions too
    for junk in (None, [], "text", {"message_type": "TASK_REQUEST"}):
        assert twin.handle(junk)["payload"]["reason"] == "invalid_message"


def test_a_peer_cannot_flood_the_approval_queue(pair, monkeypatch):
    twin, coder = pair
    monkeypatch.setattr("twinos.tasks.MAX_WAITING_PER_PEER", 2)
    twin.handlers["review_code"] = lambda task: {"success": True}
    replies = [ask(coder, twin, "TASK_REQUEST", {"task_type": "review_code", "description": str(i)})
               for i in range(3)]
    assert [r["message_type"] for r in replies] == ["APPROVAL_REQUIRED", "APPROVAL_REQUIRED", "TASK_REJECTED"]


# -- ledger --------------------------------------------------------------------------------------------
def test_the_ledger_holds_digests_not_content_and_two_processes_extend_one_chain(pair):
    twin, coder = pair
    twin.handlers["review_code"] = lambda task: {"success": True}
    task_id = ask(coder, twin, "TASK_REQUEST", {"task_type": "review_code", "description": "SECRET-DESCRIPTION",
                                                "parameters": {"note": "SECRET-PARAM"}})["payload"]["task_id"]
    owner = AgentNode(home=twin.home, paths=twin.paths)       # the owner's command, a separate process
    owner.decide(task_id, approve=True)
    ask(coder, twin, "TASK_STATUS_REQUEST", {"task_id": task_id})
    text = twin.ledger_path.read_text()
    assert "SECRET" not in text
    ledger = twin.ledger()
    assert ledger.verify() == (True, [])
    assert [e["kind"] for e in ledger.entries] == ["genesis", "message_received", "task_queued", "task_decided",
                                                   "task_result", "message_received"]


def test_untrusted_traffic_is_not_recorded(pair, tmp_path):
    twin, _ = pair
    stranger = AgentNode(home=tmp_path / "stranger", paths=twin.paths)
    for _ in range(3):
        ask(stranger, twin, "CAPABILITY_REQUEST", {})
    twin.handle({"junk": True})
    assert [e["kind"] for e in twin.ledger().entries] == ["genesis"]


# -- network -------------------------------------------------------------------------------------------
def test_round_trip_over_tcp(pair):
    twin, coder = pair

    async def scenario():
        server = await twin.start("127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            hello = await request("127.0.0.1", port, protocol.create(coder.identity, "IDENTITY_REQUEST", "any", {}))
            assert hello["sender_agent"] == twin.identity.agent_id
            pinned = {"agent_id": twin.identity.agent_id, "public_key": twin.identity.public_key}
            task = protocol.create(coder.identity, "TASK_REQUEST", twin.identity.agent_id,
                                   {"task_type": "status", "description": "", "parameters": {}})
            result = await request("127.0.0.1", port, task, expect=pinned)
            assert result["payload"]["status"] == "completed"
            impostor = {"agent_id": twin.identity.agent_id, "public_key": coder.identity.public_key}
            with pytest.raises(ProtocolError, match="pinned"):
                await request("127.0.0.1", port, protocol.create(coder.identity, "IDENTITY_REQUEST", "any", {}),
                              expect=impostor)
            reader, writer = await asyncio.open_connection("127.0.0.1", port)    # an oversized frame
            writer.write(struct.pack(">I", protocol.MAX_MESSAGE + 1))
            await writer.drain()
            reply = await protocol.read_frame(reader)
            assert reply["payload"]["reason"] == "invalid_message"
            writer.close()
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())


def test_listening_beyond_this_pc_needs_allow_remote(pair):
    twin, _ = pair
    with pytest.raises(ValueError, match="allow_remote"):
        asyncio.run(twin.start("0.0.0.0", 0))


# -- command line --------------------------------------------------------------------------------------
def test_command_line_status_trust_tasks_and_remote_guard(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("twinos.node.Paths", lambda: make_paths(tmp_path))
    home = str(tmp_path / "cli")
    assert main(["--home", home, "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["ledger_valid"] and status["automatic"] == ["status"]
    peer = AgentIdentity(tmp_path / "peer")
    assert main(["--home", home, "trust", peer.agent_id, peer.public_key]) == 0
    assert main(["--home", home, "trust", peer.agent_id, "ab" * 32]) == 1
    with pytest.raises(SystemExit, match="allow-remote"):
        main(["--home", home, "send", "192.168.1.20", "8790", peer.agent_id, "status", "hi"])
    with pytest.raises(SystemExit, match="isn't pinned"):
        main(["--home", home, "send", "127.0.0.1", "8790", "agent-" + "0" * 24, "status", "hi"])
    assert main(["--home", home, "approve", "task-0000000000000000"]) == 1
    assert main(["--home", home, "ledger"]) == 0
    assert "Ledger verifies." in capsys.readouterr().out
