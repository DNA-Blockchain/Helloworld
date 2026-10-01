"""
RabbitSoftware.inc (RabbitSoftware, Inc.): ask this OS about itself in your own words, in a terminal
or a web page.

    python rabbit.py chat                          # terminal conversation
    python rabbit.py web                           # web page at http://127.0.0.1:8792
    python rabbit.py ask "how are the nodes"       # one question, one answer
    python rabbit.py model-server https://...      # answer with your model on a server (asks each time)
    python rabbit.py model-server --off            # answer only with this PC's model
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


def model_server(url: str | None, off: bool, settings_file=None) -> int:
    from hosted_ai import configured_url, save_url
    from rabbitsoft import tools

    settings_file = settings_file or tools.Paths().rabbit / "settings.json"
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
    print(f"Model server: {current}" if current else "No model server: answers use this PC's model.")
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
    m = sub.add_parser("model-server", help="show, set or turn off the model server outside this PC")
    m.add_argument("url", nargs="?", help="the server's https address")
    m.add_argument("--off", action="store_true", help="stop using a model server")
    args = p.parse_args(argv)

    if args.command == "chat":
        return chat()
    if args.command == "web":
        return web(args.port, not args.no_browser)
    if args.command == "model-server":
        return model_server(args.url, args.off)
    if args.command == "account":
        return account(args.action, args.code)
    if args.command == "sync":
        show(Session().sync_now())
        return 0
    if args.command == "update":
        return update()
    if args.command == "publish-code-fingerprint":
        return publish_code_fingerprint(args.tag)
    show(Session().handle(" ".join(args.question)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
