"""
RabbitSoftware.inc (RabbitSoftware, Inc.): ask this OS about itself in your own words, in a terminal
or a web page.

    python rabbit.py chat                          # terminal conversation
    python rabbit.py web                           # web page at http://127.0.0.1:8792
    python rabbit.py ask "how are the nodes"       # one question, one answer
    python rabbit.py model-server https://...      # answer with your model on a server (asks each time)
    python rabbit.py model-server --off            # answer only with this PC's model
    python rabbit.py model-server --always on      # use the server without asking; AI summaries and general answers
    python rabbit.py account create|pair|join CODE|recover|devices   # one account across your devices
    python rabbit.py sync                          # research and encrypted history, with your other devices
    python rabbit.py update                        # install the latest release (asks first)
    python rabbit.py --version

Everything runs on this PC unless you say yes: a public research search, and sending a question to
the model server, each ask first. See rabbitsoft/.
"""
from __future__ import annotations

import argparse
import sys
import webbrowser

from rabbitsoft import GREETING, NAME
from rabbitsoft.assistant import Reply, Session

QUIT = {"quit", "exit", "bye", "goodbye", "q"}


def show(reply: Reply) -> None:
    print(f"\n{NAME}> " + reply.text.replace("\n", "\n    "))
    for i, choice in enumerate(reply.choices, start=1):
        print(f"    {i}. {choice}")
    if reply.confirm:
        print("    (type yes or no)")
    elif reply.choices:
        print("    (type a number, or ask something else)")


def chat() -> int:
    session = Session()
    show(Reply(f"{GREETING} Ask me anything about this OS in your own words, or type help. "
               "Type quit to leave."))
    while True:
        try:
            text = input("\nyou> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if text.strip().lower() in QUIT:
            return 0
        show(session.handle(text))


def web(port: int, open_browser: bool) -> int:
    from rabbitsoft.web import serve

    server = serve(port)
    url = f"http://127.0.0.1:{port}"
    print(f"{NAME} is running at {url} (only this PC can reach it). Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def account(action: str, code: str | None, session: Session | None = None, ask=input, secret_input=None) -> int:
    """The account commands. The recovery phrase is typed hidden here, never into the chat."""
    import getpass

    from rabbitsoft.sync import SyncError

    session = session or Session()
    secret_input = secret_input or getpass.getpass
    if action == "status":
        print(session.account_status())
    elif action == "create":
        reply = session.confirm_create_account()
        show(reply)
        if reply.confirm and ask("you> ").strip().lower() in ("y", "yes"):
            show(session._create_account())
    elif action == "pair":
        show(session.add_device())
    elif action == "join":
        if not code:
            print("Give the code from your other device: rabbit account join ABCD-EFGH-JKLM")
            return 1
        show(session.join_with_code(code))
    elif action == "recover":
        if session.sync_client.has_account():
            print(session.account_status())
            return 0
        phrase = secret_input("Recovery phrase (hidden as you type): ")
        try:
            session.sync_client.join_with_phrase(phrase, session._device_name())
        except (SyncError, ValueError) as error:
            print(f"That didn't work: {error}")
            return 1
        print("This device is back in your account. Run: rabbit sync")
    elif action == "devices":
        show(session.list_devices())
    return 0


def publish_code_fingerprint(tag: str, paths=None, ask=input) -> int:
    """Puts the fingerprint of a release's code manifest on the chain: the public record that this exact
    code is the author's release. Only the fingerprint is published; the manifest is on the GitHub release."""
    import importlib.util
    from pathlib import Path

    from audit_trail import AuditTrail
    from rabbitsoft import tools
    from research_provenance import ResearchProvenanceQueue, create_public_data_hash_event

    spec = importlib.util.spec_from_file_location("code_fingerprint", Path(__file__).resolve().parent /
                                                  "scripts" / "code_fingerprint.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        result = module.manifest(module.ROOT, tag)
    except Exception as error:               # unknown tag, no git
        print(f"Couldn't read release {tag}: {error}")
        return 1
    print(f"RabbitSoftware {result['version']} ({tag}, commit {result['commit'][:12]}), by {result['author']}, "
          f"{result['license']}: {result['file_count']} files, fingerprint {result['fingerprint']}.")
    if ask("Record this fingerprint on the shared chain? It's public and permanent. (yes/no) ").strip().lower() \
            not in ("y", "yes"):
        print("OK, nothing was published.")
        return 0
    paths = paths or tools.Paths()
    event = create_public_data_hash_event(data_sha256=result["fingerprint"], data_kind="code_release",
                                          classification="public", confirm_hash_publication=True)
    ResearchProvenanceQueue(paths.autonomous / "research-outbox").enqueue(event)
    AuditTrail(str(paths.audit)).log("rabbitsoft", "code_fingerprint_queued", "local",
                                     {"tag": tag, "commit": result["commit"], "fingerprint": result["fingerprint"],
                                      "event_id": event["event_id"]})
    print(f"Queued (entry {event['event_id'][:8]}). Node-0 adds it to the chain within a minute or two.")
    return 0


def update(root=None, ask=input, run=None, fetch=None) -> int:
    import subprocess
    from pathlib import Path

    from rabbitsoft import __version__
    from rabbitsoft.update import check, installer_command

    root = Path(root or Path(__file__).resolve().parent)
    result = check(root, __version__, fetch)
    print(result["message"])
    if result["action"] != "install":
        return 0
    if ask("Install it now? (yes/no) ").strip().lower() not in ("y", "yes"):
        print("OK, not now.")
        return 0
    return (run or subprocess.call)(installer_command(root, result["tag"]))


def model_server(url: str | None, off: bool, settings_file=None, always: str | None = None) -> int:
    from hosted_ai import always_use, configured_url, save_url, set_always_use
    from rabbitsoft import tools

    settings_file = settings_file or tools.Paths().rabbit / "settings.json"
    if always:
        if always == "on" and not configured_url(settings_file):
            print("Set a model server first: python rabbit.py model-server <https address>")
            return 1
        set_always_use(settings_file, always == "on")
        print(f"{NAME} now sends AI steps to the model server without asking, writes a technical summary on status "
              "answers, and answers general questions there; if the server doesn't answer, this PC's model does."
              if always == "on" else f"{NAME} asks before each question is sent to the model server again.")
        return 0
    if off:
        save_url(settings_file, None)
        print(f"{NAME} now answers only with this PC's model.")
        return 0
    if url:
        try:
            saved = save_url(settings_file, url)
        except ValueError as error:
            print(f"That address can't be used: {error}.")
            return 1
        print(f"Model server set to {saved}. {NAME} asks before each question is sent there; "
              "say no to answer with this PC's model instead.")
        return 0
    current = configured_url(settings_file)
    if not current:
        print("No model server: answers use this PC's model.")
    else:
        mode = ("used without asking (--always on)" if always_use(settings_file) else
                "asked before each question (python rabbit.py model-server --always on to stop asking)")
        print(f"Model server: {current}, {mode}.")
    return 0


def training(action: str, ids: list[str], daily: str | None = None, session: Session | None = None, ask=input,
             hub=None) -> int:
    """The owner's commands for shared answers (rabbitsoft/training_export.py)."""
    from rabbitsoft import training_export
    from rabbitsoft.sync import SyncError

    session = session or Session()
    client = session.sync_client
    try:
        if action == "stats":
            s = client.admin_stats()
            by_status = ", ".join(f"{t['status']} {t['answers']} ({t.get('exported') or 0} exported)" for t in s["training"]) or "none"
            print(f"Accounts: {s['accounts']}. Shared answers: {by_status}. Corpus: {s['corpus']['records']} records "
                  f"from {s['corpus']['sources']} sources. Exports: {s['exports']['files']} files, "
                  f"{s['exports']['rows']} answers (last {s['exports'].get('last') or 'never'}).")
        elif action == "pending":
            items = client.admin_training("pending")
            for item in items:
                print(f"{item['id']}  {item['shared_at'][:10]}  rating {item['rating']:+d}  Q: {item['question'][:80]}\n"
                      f"    A: {item['answer'][:160]}")
            print(f"{len(items)} answer(s) waiting for review.")
        elif action in ("approve", "reject"):
            if not ids:
                print("Give the answer IDs (from: python rabbit.py training pending).")
                return 1
            updated = client.review_training(ids, "approved" if action == "approve" else "rejected")
            print(f"{updated} answer(s) marked {action}d.")
        elif daily:
            training_export.set_exporting_daily(session.paths, daily == "on")
            session._log("training_export_daily_" + daily, {})
            print("The supervisor will export new shared answers once a day." if daily == "on" else
                  "Daily export is off; export with: python rabbit.py training export")
        else:
            print(training_export.export(client, hub=hub, ask=ask, log=session._log)["message"])
    except SyncError as error:
        print(f"The sync service refused: {error}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):          # the Windows console isn't UTF-8 by default
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    from rabbitsoft import __version__

    p = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    p.add_argument("--version", action="version", version=f"{NAME} {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("chat", help="talk in this terminal")
    w = sub.add_parser("web", help="talk in a web page on this PC")
    w.add_argument("--port", type=int, default=8792)
    w.add_argument("--no-browser", action="store_true", help="don't open the page automatically")
    a = sub.add_parser("ask", help="one question, one answer")
    a.add_argument("question", nargs="+")
    acc = sub.add_parser("account", help="your account across devices: create, pair, join, recover, devices")
    acc.add_argument("action", nargs="?", default="status",
                     choices=["status", "create", "pair", "join", "recover", "devices"])
    acc.add_argument("code", nargs="?", help="the pairing code, for join")
    sub.add_parser("sync", help="sync research and encrypted history with your other devices")
    sub.add_parser("update", help="install the latest RabbitSoftware release (asks first)")
    fp = sub.add_parser("publish-code-fingerprint",
                        help="record a release's code fingerprint (its authorship) on the chain (asks first)")
    fp.add_argument("tag", help="the release tag, e.g. v0.9.0")
    pr = sub.add_parser("pipeline-report", help="the research data pipeline report: sources, corpus, model, "
                                                "chain, nodes, integrity (read-only)")
    pr.add_argument("--hours", type=float, default=24, help="the period for the \"new\" figures (default 24)")
    pr.add_argument("--json", action="store_true", help="the report as JSON")
    tr = sub.add_parser("training", help="shared answers (owner): stats, pending, approve/reject, export to Hugging Face")
    tr.add_argument("action", choices=["stats", "pending", "approve", "reject", "export"])
    tr.add_argument("ids", nargs="*", help="answer IDs, for approve and reject")
    tr.add_argument("--daily", choices=["on", "off"], help="with export: let the supervisor export once a day")
    m = sub.add_parser("model-server", help="show, set or turn off the model server outside this PC")
    m.add_argument("url", nargs="?", help="the server's https address")
    m.add_argument("--off", action="store_true", help="stop using a model server")
    m.add_argument("--always", choices=["on", "off"],
                   help="on: use the model server without asking (status summaries and general answers too)")
    args = p.parse_args(argv)

    if args.command == "chat":
        return chat()
    if args.command == "web":
        return web(args.port, not args.no_browser)
    if args.command == "model-server":
        return model_server(args.url, args.off, always=args.always)
    if args.command == "account":
        return account(args.action, args.code)
    if args.command == "sync":
        show(Session().sync_now())
        return 0
    if args.command == "update":
        return update()
    if args.command == "publish-code-fingerprint":
        return publish_code_fingerprint(args.tag)
    if args.command == "training":
        return training(args.action, args.ids, args.daily)
    if args.command == "pipeline-report":
        from rabbitsoft import pipeline_report

        return pipeline_report.main(["--hours", str(args.hours)] + (["--json"] if args.json else []))
    show(Session().handle(" ".join(args.question)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
