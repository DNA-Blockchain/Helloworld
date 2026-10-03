# Agent toolkit

One launcher for the Universal TwinOS agent and the agents listed in `agents.json`.
It needs only Python 3.7+ and the standard library: no installs, no extra packages.
Auto-approval is on (`RABBIT_AUTO_APPROVE=1`), so nothing waits for a confirmation.

| Where | Run |
|---|---|
| Linux, macOS, WSL, Cloud Shell, CI | `python3 toolkit/run.py --tools` |
| Windows (PowerShell, cmd) | `py toolkit\run.py --tools` or `python toolkit\run.py --tools` |
| Android (Termux) | `pkg install python git`, then `python toolkit/run.py --tools` |

Examples (same on every platform; quote JSON for your shell):

    python3 toolkit/run.py --tool run_command '{"command": "git status"}'
    python3 toolkit/run.py --tool agent_list
    python3 toolkit/run.py --tool agent_run '{"name": "universal-twinos", "args": ["--status"]}'
    python3 toolkit/run.py --ask "hello"

Shells that eat JSON quotes (Windows PowerShell and cmd) are fine: use `key=value` pairs instead, e.g.
`python toolkit\\run.py --tool read_file path=README.md` or `--tool run_command command="git status"`.

Tools: list_dir, read_file, write_file, search_files, git, run_command, chain_head, ask_model,
agent_list, agent_run. File tools stay inside this repository. Any agent task can also carry a
`command` to run in the terminal.

Network use: the server listens on localhost by default. To reach it from another device (a phone,
Cloud Shell web preview), set `RABBIT_TWIN_TOKEN` and bind with `--host 0.0.0.0`; callers send
`Authorization: Bearer <token>`. Peers with the token can run terminal commands and write files;
use `--no-terminal-network` to turn that off. Anchors, model providers and the agent registry are
plain JSON files, so they work the same everywhere.
