"""python -m twinos: run this agent, talk to other agents, and decide on the tasks they send.

    status                                   this agent, its peers, tasks and ledger
    serve [--port 8790] [--host H --allow-remote]
    discover HOST PORT                        ask an agent who it is (prints the trust command to pin it)
    trust AGENT_ID PUBLIC_KEY [--name N]      pin a peer; untrust AGENT_ID removes it; peers lists them
    capabilities HOST PORT AGENT_ID           which task types a pinned peer runs, and which without asking
    send HOST PORT AGENT_ID TASK_TYPE "DESCRIPTION" [--param key=value ...]
    check HOST PORT AGENT_ID TASK_ID          a task's status and result on that peer
    tasks | approve TASK_ID | deny TASK_ID    tasks other agents sent here
    ledger                                    the local ledger, oldest first, and whether it verifies

--home DIR runs a separate agent from DIR (default autonomous/twinos), e.g. a second agent for testing.
Sending to another machine needs --allow-remote and is written to the activity log.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from . import protocol
from .node import DEFAULT_PORT, AgentNode, is_local, request


def _parameters(pairs: list[str]) -> dict:
    params = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise SystemExit(f"--param takes key=value, not {pair!r}")
        params[key] = value
    return params


def _show(value) -> None:
    print(json.dumps(value, indent=2, default=str))


def _ask(node: AgentNode, args, message_type: str, receiver: str, payload: dict, pinned: bool = True) -> dict:
    if not is_local(args.host):
        if not args.allow_remote:
            raise SystemExit(f"{args.host} is another machine; add --allow-remote to send it this message")
        node.log("send to remote agent", {"host": args.host, "port": args.port, "message_type": message_type,
                                          "receiver": receiver})
    expect = None
    if pinned:
        expect = node.trust.peers.get(receiver)
        if expect is None:
            raise SystemExit(f"{receiver} isn't pinned; discover it and run the trust command first")
        expect = {"agent_id": receiver, "public_key": expect["public_key"]}
    message = protocol.create(node.identity, message_type, receiver, payload)
    reply = asyncio.run(request(args.host, args.port, message, expect=expect))
    if pinned:
        node.record("message_sent", message, {"message_type": message_type, "receiver_agent": receiver,
                                              "reply_type": reply["message_type"]})
    return reply


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m twinos", description="TwinOS universal agent network")
    parser.add_argument("--home", type=Path, help="this agent's folder (default autonomous/twinos)")
    parser.add_argument("--name", default="Personal Digital Twin", help="name, when the agent is first created")
    parser.add_argument("--type", default="digital_twin", dest="agent_type", help="agent type, when first created")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--allow-remote", action="store_true")
    for name, extra in (("discover", []), ("capabilities", ["agent_id"]), ("send", ["agent_id", "task_type", "description"]),
                        ("check", ["agent_id", "task_id"])):
        p = sub.add_parser(name)
        p.add_argument("host")
        p.add_argument("port", type=int)
        for field in extra:
            p.add_argument(field)
        p.add_argument("--allow-remote", action="store_true")
        if name == "send":
            p.add_argument("--param", action="append", default=[])
    trust = sub.add_parser("trust")
    trust.add_argument("agent_id")
    trust.add_argument("public_key")
    trust.add_argument("--peer-name", default="")
    trust.add_argument("--peer-type", default="generic_agent")
    sub.add_parser("untrust").add_argument("agent_id")
    sub.add_parser("peers")
    sub.add_parser("tasks")
    sub.add_parser("approve").add_argument("task_id")
    sub.add_parser("deny").add_argument("task_id")
    sub.add_parser("ledger")
    args = parser.parse_args(argv)

    node = AgentNode(home=args.home, name=args.name, agent_type=args.agent_type)
    try:
        if args.command == "status":
            _show(node.status())
        elif args.command == "serve":
            async def serve_forever():
                server = await node.start(args.host, args.port, args.allow_remote)
                print(f"{node.identity.name} ({node.identity.agent_id}) listening on {args.host}:{args.port}, "
                      f"U-A2A {protocol.PROTOCOL_VERSION}. Ctrl+C stops it.")
                async with server:
                    await server.serve_forever()
            asyncio.run(serve_forever())
        elif args.command == "discover":
            reply = _ask(node, args, "IDENTITY_REQUEST", "any", {}, pinned=False)
            agent = reply["payload"].get("agent", {})
            _show(agent)
            print("\nIf this is the agent you expect, pin it with:\n"
                  f"  python -m twinos trust {reply['sender_agent']} {reply['sender_key']} "
                  f"--peer-name \"{agent.get('name', '')}\" --peer-type {reply['sender_type']}")
        elif args.command == "capabilities":
            _show(_ask(node, args, "CAPABILITY_REQUEST", args.agent_id, {})["payload"])
        elif args.command == "send":
            payload = {"task_type": args.task_type, "description": args.description,
                       "parameters": _parameters(args.param)}
            reply = _ask(node, args, "TASK_REQUEST", args.agent_id, payload)
            _show({"reply": reply["message_type"], **reply["payload"]})
        elif args.command == "check":
            reply = _ask(node, args, "TASK_STATUS_REQUEST", args.agent_id, {"task_id": args.task_id})
            _show({"reply": reply["message_type"], **reply["payload"]})
        elif args.command == "trust":
            node.trust.pin(args.agent_id, args.public_key, args.peer_name, args.peer_type)
            node.log("trust agent", {"agent_id": args.agent_id})
            print(f"Pinned {args.agent_id}. It can now send this agent tasks; anything outside the policy still "
                  f"waits for your approval.")
        elif args.command == "untrust":
            removed = node.trust.unpin(args.agent_id)
            if removed:
                node.log("untrust agent", {"agent_id": args.agent_id})
            print("Removed." if removed else f"{args.agent_id} wasn't pinned.")
        elif args.command == "peers":
            _show(node.trust.peers)
        elif args.command == "tasks":
            for task in node.tasks.all():
                print(f"{task.task_id}  {task.status:<16} {task.task_type:<18} from {task.source_agent}: "
                      f"{task.description[:80]}")
        elif args.command in ("approve", "deny"):
            task = node.decide(args.task_id, approve=args.command == "approve")
            _show({"task_id": task.task_id, "status": task.status, "result": task.result})
        elif args.command == "ledger":
            ledger = node.ledger()
            for entry in ledger.entries:
                print(f"#{entry['index']:<4} {entry['kind']:<18} {json.dumps(entry['metrics'], default=str)}")
            ok, problems = ledger.verify()
            print("Ledger verifies." if ok else "Ledger problems:\n  " + "\n  ".join(problems))
    except (protocol.ProtocolError, ValueError, KeyError, OSError, TimeoutError, EOFError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
