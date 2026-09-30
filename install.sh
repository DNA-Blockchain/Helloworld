#!/usr/bin/env bash
# RabbitSoftware.inc installer for Linux, including WSL (Ubuntu and others).
#
# One line (no sudo needed):
#
#     curl -fsSL https://raw.githubusercontent.com/DNA-Blockchain/Helloworld/master/install.sh | bash
#
# It downloads the project from GitHub into ~/.local/share/rabbitsoftware, gives it its own Python
# environment, and adds a `rabbit` command:  rabbit chat | rabbit web | rabbit ask "..."
# Running it again updates the code and keeps your data (chains, notes, research, settings).
#
# It never installs anything else on its own: if Python or Ollama is missing it says so and gives the
# command to run. Options, as environment variables:
#   RABBIT_HOME       where to install (default ~/.local/share/rabbitsoftware)
#   RABBIT_SOURCE     a .zip of the project to install from instead of GitHub
#   RABBIT_MODEL_URL  a model server to use (https); RabbitSoftware.inc asks before each question sent there
set -euo pipefail

REPO_ZIP="https://github.com/DNA-Blockchain/Helloworld/archive/refs/heads/master.zip"
RABBIT_HOME="${RABBIT_HOME:-$HOME/.local/share/rabbitsoftware}"
BIN_DIR="$HOME/.local/bin"

echo "RabbitSoftware.inc installer"

# 1. Python 3.11 or newer, able to make environments
PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        PYTHON="$(command -v "$candidate")"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    echo "Python 3.11 or newer is needed and wasn't found. On Ubuntu/WSL install it with:"
    echo "    sudo apt update && sudo apt install -y python3 python3-venv"
    echo "then run this installer again."
    exit 1
fi
if ! "$PYTHON" -c 'import ensurepip, venv' 2>/dev/null; then
    echo "Python can't make environments yet. On Ubuntu/WSL fix that with:"
    echo "    sudo apt install -y python3-venv"
    echo "then run this installer again."
    exit 1
fi
echo "Using $("$PYTHON" --version)."

# 2. The project code (downloaded, or the zip given in RABBIT_SOURCE), unpacked with Python so
#    nothing else (unzip, git) is needed
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
if [ -n "${RABBIT_SOURCE:-}" ]; then
    cp "$RABBIT_SOURCE" "$WORK/project.zip"
else
    echo "Downloading the project from GitHub..."
    curl -fsSL "$REPO_ZIP" -o "$WORK/project.zip"
fi
mkdir -p "$RABBIT_HOME"
"$PYTHON" - "$WORK/project.zip" "$RABBIT_HOME" <<'EOF'
import shutil, sys, zipfile
from pathlib import Path

archive, home = Path(sys.argv[1]), Path(sys.argv[2])
with zipfile.ZipFile(archive) as z:
    names = z.namelist()
    top = names[0].split("/")[0] + "/"
    if top + "rabbit.py" not in names:
        sys.exit("Install stopped: the download doesn't look like the RabbitSoftware project (no rabbit.py)")
    # Copying over an existing install updates the code; data folders aren't in the download, so they stay.
    for info in z.infolist():
        rel = info.filename[len(top):]
        if not rel or info.is_dir():
            continue
        target = home / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with z.open(info) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        if rel.endswith(".sh"):
            target.chmod(0o755)
EOF
echo "Installed the code in $RABBIT_HOME"

# 3. Its own Python environment, so nothing else on this computer is changed
if [ ! -x "$RABBIT_HOME/.venv/bin/python" ]; then
    echo "Creating a Python environment..."
    "$PYTHON" -m venv "$RABBIT_HOME/.venv"
fi
echo "Installing the Python packages (a few minutes the first time)..."
"$RABBIT_HOME/.venv/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip
"$RABBIT_HOME/.venv/bin/python" -m pip install --quiet --disable-pip-version-check -r "$RABBIT_HOME/requirements.txt"

# 4. The `rabbit` command
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/rabbit" <<EOF
#!/bin/sh
exec "$RABBIT_HOME/.venv/bin/python" "$RABBIT_HOME/rabbit.py" "\$@"
EOF
chmod +x "$BIN_DIR/rabbit"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        if ! grep -qs 'RabbitSoftware.inc: rabbit command' "$HOME/.bashrc"; then
            printf '\n# RabbitSoftware.inc: rabbit command\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$HOME/.bashrc"
            echo "Added ~/.local/bin to PATH in ~/.bashrc."
        fi
        ;;
esac

# 5. The model server, if one was given
if [ -n "${RABBIT_MODEL_URL:-}" ]; then
    "$BIN_DIR/rabbit" model-server "$RABBIT_MODEL_URL"
fi

# 6. Tell (never install) what's optional
if ! command -v ollama >/dev/null 2>&1; then
    echo
    echo "Optional: to answer with a model on this computer (and search by meaning), install Ollama:"
    echo "    curl -fsSL https://ollama.com/install.sh | sh"
fi

echo
echo "Done. Open a new terminal (or run: source ~/.bashrc) and type:"
echo "    rabbit chat     talk in this terminal"
echo "    rabbit web      talk in a web page on this computer"
