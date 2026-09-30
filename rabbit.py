"""
RabbitSoftware.inc (RabbitSoftware, Inc.): ask this OS about itself in your own words, in a terminal
or a web page.

    python rabbit.py chat                          # terminal conversation
    python rabbit.py web                           # web page at http://127.0.0.1:8792
    python rabbit.py ask "how are the nodes"       # one question, one answer
    python rabbit.py model-server https://...      # answer with your model on a server (asks each time)
    python rabbit.py model-server --off            # answer only with this PC's model

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
    p = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("chat", help="talk in this terminal")
    w = sub.add_parser("web", help="talk in a web page on this PC")
    w.add_argument("--port", type=int, default=8792)
    w.add_argument("--no-browser", action="store_true", help="don't open the page automatically")
    a = sub.add_parser("ask", help="one question, one answer")
    a.add_argument("question", nargs="+")
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
    show(Session().handle(" ".join(args.question)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
