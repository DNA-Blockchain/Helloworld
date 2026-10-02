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
    sense [--eeg simulated|brainflow|lsl] [--rf pkg.mod:Driver] [--audio pkg.mod:Driver] [--seconds 30]
                                              read the sensors and track the twin's state; a lasting change
                                              becomes a proposed update_context task for you to approve
    context                                   the twin's context entries
    learn [--device auto|cpu|cuda]            train on the recorded neurovisual sessions (your command is the yes)
    datasets [--all]                          public cancer-genomics datasets: licence, access tier, what for
    fetch NAME                                where to get a dataset, and whether this twin may download it
    record NAME --file PATH                   fingerprint a dataset file you downloaded, into the ledger
    compare CANCER.vcf REFERENCE.vcf          variants gained, lost and shifted between two public variant files
    guides SEQUENCE.fa --at OFFSET            candidate Cas9 guides near a position: laboratory hypotheses only

Genomics commands work on public research data and are not a treatment tool: they compute candidates for a
laboratory, and no software can edit DNA in a body (docs/genomics/README.md). Not medical advice.

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
from .sensors import EEGSource, MicroPythonSerial, PluginSource, SensorUnavailable, Unavailable


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


def _sense(node: AgentNode, args) -> int:
    sources = [EEGSource.open(args.eeg, board_id=args.board_id, serial_port=args.serial_port) if args.eeg != "none"
               else Unavailable("eeg", "no EEG source chosen")]
    for name, reference in (("rf", args.rf), ("audio", args.audio)):
        sources.append(PluginSource(name, reference) if reference else Unavailable(name, f"no {name} driver attached"))
    steps = max(1, int(args.seconds * args.hz))

    every = max(1, round(args.hz))
    count = [0]

    def show(state):
        count[0] += 1
        if (count[0] - 1) % every and not state.changes:
            return                   # one line a second, plus every change
        parts = [f"{n} {'%.1f SD' % s.deviation if s.available else 'unavailable'}" for n, s in state.sources.items()]
        flag = f"  CHANGE: {', '.join(state.changes)} (proposed for approval)" if state.changes else ""
        print(f"confidence {state.confidence:.2f}  " + "  ".join(parts) + flag)

    try:
        print(f"Sensing for {args.seconds:.0f} s at {args.hz:.0f} Hz. EEG features are measurements against your "
              f"own baseline, not thoughts. Ctrl+C stops.")
        node.sense(sources, steps, 1.0 / args.hz, on_state=show)
    except KeyboardInterrupt:
        pass
    finally:
        for source in sources:
            source.close()
    waiting = [t for t in node.tasks.waiting() if t.source_agent == node.identity.agent_id]
    if waiting:
        print(f"{len(waiting)} proposed task(s) waiting: python -m twinos tasks")
    return 0


def _genomics(node: AgentNode, args) -> int:
    """The genomics commands. They read public research data and compute candidates for a laboratory;
    they are not a treatment tool and say so in their output."""
    from . import genomics as g

    if args.command == "datasets":
        for d in g.catalogue():
            if not args.all and d["access"] == "controlled":
                continue
            marks = [d["access"]]
            marks += ["before/after"] if d["paired"] else []
            marks += ["personal data: local only"] if d["personal_data"] else []
            print(f"{d['name']:<34} {', '.join(marks)}\n    {d['title']} — {d['subjects']}\n"
                  f"    {d['license']}{'' if d['redistribute'] else ' (no redistribution)'}\n    {d['use']}")
        if not args.all:
            print("(--all also lists controlled-access datasets, which need an institution's approval.)")
        return 0

    if args.command == "fetch":
        entry = g.dataset(args.name)
        allowed, why = g.fetch_plan(entry)
        print(f"{entry['title']}\n  {entry['license']}\n  {why}")
        if not allowed:
            return 1
        print("Download it, then record it here: python -m twinos record "
              f"{entry['name']} --file <the file>")
        return 0

    if args.command == "record":
        entry = g.dataset(args.name)
        if not args.file.is_file():
            print(f"No such file: {args.file}")
            return 1
        from model_versions import file_sha256

        record = g.record_entry(entry, args.file, file_sha256(args.file))
        node.record("dataset_recorded", record, {"dataset": record["dataset"], "sha256": record["sha256"],
                                                 "publishable": record["publishable"]})
        node.log("record dataset", {"dataset": record["dataset"], "sha256": record["sha256"]})
        _show(record)
        print("Recorded in this twin's ledger (keyed digest, local only). "
              + ("Its release fingerprint may be published." if record["publishable"] else
                 "Its licence or personal data means only aggregates may leave this PC."))
        return 0

    if args.command == "compare":
        cancer, reference = g.read_variants(args.cancer), g.read_variants(args.reference)
        result = g.compare(cancer, reference, args.shift)
        print(f"{len(cancer)} variants in {args.cancer.name}, {len(reference)} in {args.reference.name}.")
        _show(result.summary(args.shift))
        for name, items in (("gained (in the cancer file only)", result.gained), ("lost", result.lost)):
            if items:
                print(f"\n{name}:")
                for v in items[:args.limit]:
                    print(f"  {v}" + (f"  AF {v.frequency:.2f}" if v.frequency is not None else ""))
                if len(items) > args.limit:
                    print(f"  ... and {len(items) - args.limit} more")
        if result.shifted:
            print("\nallele-frequency shifts:")
            for before, after in result.shifted[:args.limit]:
                print(f"  {after}  {before.frequency:.2f} -> {after.frequency:.2f}")
        if args.megabases:
            print(f"\nmutations per megabase: {g.mutational_burden(cancer, args.megabases)} (cancer file), "
                  f"{g.mutational_burden(reference, args.megabases)} (reference)")
        print("\nThese are differences between two files. They are not a diagnosis, not a target list, and "
              "not medical advice.")
        return 0

    text = args.sequence.read_text(encoding="utf-8")
    sequence = "".join(l.strip() for l in text.splitlines() if not l.startswith(">")).upper()
    guides = g.candidate_guides(sequence, args.at, args.window)
    print(f"{len(sequence)} bases; position {args.at} is {sequence[args.at] if args.at < len(sequence) else '?'}.")
    if not guides:
        print(f"No SpCas9 (NGG) site within {args.window} bases of that position.")
        return 0
    print(f"\n{len(guides)} candidate guide(s), nearest cut first:")
    for guide in guides:
        print(f"  {guide.protospacer} {guide.pam}  strand {guide.strand}  GC {guide.gc:.0%}  "
              f"{guide.distance_to_target} base(s) from the target")
    print(f"\n{g.HYPOTHESIS}\n{g.edit_outcome_note()}")
    return 0


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
    serve.add_argument("--micropython-port", help="offer micropython_command tasks for the board on this serial port")
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
    sense = sub.add_parser("sense")
    sense.add_argument("--eeg", choices=["simulated", "brainflow", "lsl", "none"], default="simulated")
    sense.add_argument("--board-id", type=int, default=-1, help="BrainFlow board id (-1: BrainFlow's synthetic board)")
    sense.add_argument("--serial-port", default="", help="BrainFlow serial port")
    sense.add_argument("--rf", help="package.module:Driver for an RF/radar source")
    sense.add_argument("--audio", help="package.module:Driver for an audio source")
    sense.add_argument("--seconds", type=float, default=30.0)
    sense.add_argument("--hz", type=float, default=10.0)
    sub.add_parser("context")
    sub.add_parser("learn").add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    ds = sub.add_parser("datasets")
    ds.add_argument("--all", action="store_true", help="include datasets this twin can't download")
    fe = sub.add_parser("fetch")
    fe.add_argument("name")
    rc = sub.add_parser("record")
    rc.add_argument("name")
    rc.add_argument("--file", type=Path, required=True, help="the dataset file you downloaded")
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("cancer", type=Path)
    cmp_.add_argument("reference", type=Path)
    cmp_.add_argument("--shift", type=float, default=0.2, help="allele-frequency change counted as a shift")
    cmp_.add_argument("--megabases", type=float, help="sequenced size, for mutations per megabase")
    cmp_.add_argument("--limit", type=int, default=15)
    gd = sub.add_parser("guides")
    gd.add_argument("sequence", type=Path, help="a FASTA file, or a file of plain A/C/G/T")
    gd.add_argument("--at", type=int, required=True, help="0-based offset of the position of interest")
    gd.add_argument("--window", type=int, default=30)
    args = parser.parse_args(argv)

    node = AgentNode(home=args.home, name=args.name, agent_type=args.agent_type)
    try:
        if args.command == "status":
            _show(node.status())
        elif args.command == "serve":
            if args.micropython_port:
                node.attach_micropython(MicroPythonSerial(args.micropython_port))
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
        elif args.command == "sense":
            return _sense(node, args)
        elif args.command in ("datasets", "fetch", "record", "compare", "guides"):
            return _genomics(node, args)
        elif args.command == "context":
            try:
                for line in node.context_path.read_text(encoding="utf-8").splitlines():
                    entry = json.loads(line)
                    print(f"{entry['category']:<16} {entry['summary']}")
            except FileNotFoundError:
                print("No context entries yet.")
        elif args.command == "learn":
            task = node.run_local("gpu_training", "train on recorded sessions", {"device": args.device})
            _show({"task_id": task.task_id, "status": task.status, "result": task.result})
            return 0 if task.status == "completed" else 1
    except (protocol.ProtocolError, ValueError, KeyError, OSError, TimeoutError, EOFError, ImportError,
            SensorUnavailable) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
