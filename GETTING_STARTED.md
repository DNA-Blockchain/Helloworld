# Getting started: install and run, step by step

A checklist for setting up this project on a Windows PC, from nothing to the
full system: the network nodes, the DNA twin, the swarm, the local AI, the
two operating-system builds, and EEG and radio hardware. Tick the boxes as
you go. Each part names what you need first and how to know it worked.

Parts 1–4 are the core; parts 5–8 are independent and can be done in any
order. You don't need any hardware for parts 1–7.

| Part | You get | Time |
|---|---|---|
| [1. Operating system](#1-operating-system-windows--wsl) | Windows with Ubuntu (WSL) | 20 min |
| [2. Software](#2-software) | Python, Git, VS Code, Claude Code | 20 min |
| [3. Code](#3-code-get-it-install-it-test-it) | The project, installed and tested | 15 min |
| [4. Run the network](#4-run-the-network) | Nodes mining and gossiping | 5 min |
| [5. DNA twin and swarm](#5-dna-twin-and-swarm) | The twin page; nodes cross-checking | 10 min |
| [6. Local AI](#6-local-ai-ollama) | Plain-language summaries on your PC | 15 min |
| [7. The OS builds](#7-the-os-builds-alpine-linux-image-and-the-rust-kernel) | Linux VMs running nodes; the Rust kernel | 20 min |
| [8. Hardware](#8-hardware-eeg-and-radio) | Real EEG and radio signals | when you have it |

---

## 1. Operating system: Windows + WSL

What you need: Windows 10/11, 8 GB RAM or more, about 20 GB free disk.

- [ ] **Turn on virtualization** in your PC's BIOS/UEFI (often "Intel VT-x",
      "AMD-V" or "SVM"). Check in Task Manager → Performance → CPU:
      "Virtualization: Enabled".
- [ ] **Install WSL with Ubuntu.** In PowerShell as administrator:
      ```powershell
      wsl --install -d Ubuntu-24.04
      ```
      Restart when asked, then open "Ubuntu" from the Start menu and choose a
      username and password.
- [ ] **Give WSL enough memory.** Create `C:\Users\<you>\.wslconfig`:
      ```ini
      [wsl2]
      memory=5GB
      processors=6
      swap=8GB
      ```
      On an 8 GB PC keep `memory` at 5 GB or less so Windows has room. Then
      run `wsl --shutdown` in PowerShell and reopen Ubuntu.
- [ ] **Check it worked.** In Ubuntu: `free -h` shows about 5 GB total, and
      `ls -l /dev/kvm` exists (VMs will run at full speed).

## 2. Software

- [ ] **Python 3.12 or newer for Windows** from
      [python.org](https://www.python.org/downloads/). Tick "Add python.exe to
      PATH" in the installer. Check: `python --version` in PowerShell.
- [ ] **Git for Windows** from [git-scm.com](https://git-scm.com/). Check:
      `git --version`.
- [ ] **VS Code** from [code.visualstudio.com](https://code.visualstudio.com/),
      with the **WSL** extension (to open the project from Ubuntu) and the
      **Claude Code** extension.
- [ ] **Ubuntu packages.** In Ubuntu:
      ```bash
      sudo apt update
      sudo apt install -y python3-venv python3-pip build-essential curl qemu-system-x86 qemu-utils
      ```
- [ ] **Rust** (only for the Rust kernel in part 7). In Ubuntu:
      ```bash
      curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
      ```
      The project pins its own nightly version; `cargo` fetches it on first use.

## 3. Code: get it, install it, test it

- [ ] **Get the code.** In PowerShell:
      ```powershell
      cd $env:USERPROFILE
      git clone <your repository URL> network-os-project
      cd network-os-project
      ```
- [ ] **Make Git agree on line endings** between Windows and WSL (otherwise
      Ubuntu shows every file as changed):
      ```powershell
      git config core.autocrlf true
      ```
- [ ] **Install the Python packages on Windows:**
      ```powershell
      python -m pip install -r requirements.txt
      ```
- [ ] **And in Ubuntu**, in a virtual environment on the Linux disk (faster
      than `/mnt/c`):
      ```bash
      python3 -m venv ~/venvs/network-os
      ~/venvs/network-os/bin/pip install -r /mnt/c/Users/<you>/network-os-project/requirements.txt
      ```
- [ ] **Run the tests.** Either side should end with "passed" and 0 failed:
      ```powershell
      python -m pytest -q                              # Windows, about 4 minutes
      ```
      ```bash
      cd /mnt/c/Users/<you>/network-os-project
      ~/venvs/network-os/bin/python -m pytest -q      # Ubuntu
      ```
      Some tests skip on one side on purpose (PowerShell tests need Windows;
      the Linux image test needs the image from part 7).

## 4. Run the network

- [ ] **One command, everything local:**
      ```powershell
      python run_all.py
      ```
      You'll see a node start on `127.0.0.1:8765` and a research topic seeded.
      Ctrl+C stops it; state is saved beside the code.
- [ ] **A menu for single nodes** (Windows): double-click `run_local.bat`, or
      `.\run_local.ps1`. Option 4 runs the codec self-test ("all checks
      PASSED").
- [ ] **Three nodes talking to each other**, one per terminal:
      ```powershell
      python run_node_cli.py --id 1 --port 9601 --peers 127.0.0.1:9602,127.0.0.1:9603 --tofu
      python run_node_cli.py --id 2 --port 9602 --peers 127.0.0.1:9601,127.0.0.1:9603 --tofu
      python run_node_cli.py --id 3 --port 9603 --peers 127.0.0.1:9601,127.0.0.1:9602 --tofu
      ```
      Worked if: each shows `<- block ... VERIFIED` from the others, and on
      Ctrl+C `chain intact (OK)`.
- [ ] **Keep 3 nodes running in the background** at every Windows logon:
      ```powershell
      python node_supervisor.py --install
      python node_supervisor.py --status
      ```

## 5. DNA twin and swarm

- [ ] **Make a synthetic run and open its twin page:**
      ```powershell
      python remission_workflow.py --output run.json
      python dna_twin_viewer.py run.json --output twin.html --open
      ```
      The page shows the double helix, the binary code, each difference, its
      protein change with tRNA anticodons and side-chain chemistry, and siRNA
      candidates. The default synthetic run is only 12 bases, too short for a
      19-base siRNA window. Use `--baseline <file>` or a longer run to see
      them. Everything on the page is a computational model, not a treatment.
- [ ] **Add ClinVar's classifications for a gene** (needs internet):
      ```powershell
      python dna_twin_viewer.py run.json --gene BRCA1 --clinvar --open
      ```
- [ ] **Run the swarm:** add `--work-sharing --swarm` to each of the three
      node commands in part 4 (add `--round-seconds 30` to see results
      sooner). Worked if: the logs show
      `swarm round N: ACCEPTED synthetic:K (nodes 1, 2 agree ...)`.

## 6. Local AI (Ollama)

Everything here runs on your PC; nothing is sent to an AI service.

- [ ] **Install Ollama** from [ollama.com](https://ollama.com/download) (on
      Windows it runs as a tray app).
- [ ] **Download a small model** (about 2 GB):
      ```powershell
      ollama pull llama3.2:3b
      ```
      Check: `ollama list` shows it.
- [ ] **Plain-language summaries of published research:**
      ```powershell
      python research_summaries.py run --limit 5
      python research_summaries.py status
      ```
- [ ] **Ask questions of the research catalog:**
      ```powershell
      python dna_shell.py catalog-ask "What does the catalog say about BRCA1?" --model llama3.2
      ```
      AI answers can be wrong. The project labels them "may be wrong, not
      evidence" and never treats them as findings.
- [ ] **Explain the swarm's accepted results** (after part 5; add
      `--status-file node1_status.json` to node 1's command so it saves its
      verdicts):
      ```powershell
      python swarm_explain.py --status-file node1_status.json
      ```
      Each result is re-verified on your PC first. The facts print, then the
      AI's plain-language explanation. A larger model is more accurate if your
      PC can run it: `ollama pull llama3.1:8b`, then add `--model llama3.1:8b`.

## 7. The OS builds: Alpine Linux image and the Rust kernel

These are two different things. The **Alpine image** is real Linux that runs
the Python node in a VM. The **Rust kernel** (`os/`) is the from-scratch
operating system prototype. Both run only inside QEMU and never touch your
real disk.

- [ ] **Build the Alpine image** (Ubuntu, about a minute, needs internet):
      ```bash
      cd /mnt/c/Users/<you>/network-os-project
      sudo sh linux/build.sh
      ```
      Worked if it ends with `==> done: Alpine 3.24.2` and lists `vmlinuz` and
      `initramfs.gz`.
- [ ] **Boot one node in Linux:**
      ```bash
      sh linux/run.sh --id 1
      ```
      Leave with Ctrl-A then X.
- [ ] **Three Linux VMs as a swarm:**
      ```bash
      sh linux/swarm.sh --round 15 --duration 70
      ```
      Worked if each node lists `ACCEPTED` rounds and `chain intact (OK)`.
      If the output looks like an older version, rebuild first.
- [ ] **Build and check the Rust kernel** (Ubuntu):
      ```bash
      export CARGO_TARGET_DIR="$HOME/.cache/network-os-target"
      cd /mnt/c/Users/<you>/network-os-project/os
      cargo run --locked -- check
      ```
      The first build downloads crates; afterwards it works offline. On
      Windows, see `os/README.md` for the PowerShell steps.

## 8. Hardware: EEG and radio

Everything in the signal lab works now on simulated input. Hardware only
changes the `--source` or `--sink` text. See the "Signal lab" section of
`README.md` for all options.

**Try it without hardware first:**

- [ ] ```powershell
      python signal_lab.py devices
      python signal_lab.py bridge --source eeg:synthetic --sink stats --seconds 5
      python signal_lab.py send-twin --twin run.json --sink file:twin.cs8
      python signal_lab.py receive-twin --source "rf:file:twin.cs8?rate=250e3" --twin run.json
      ```
      Worked if the last line says `matches the twin's sample strand`.

**EEG: OpenBCI** (Cyton 8-channel or Ganglion 4-channel)

- [ ] Plug in the OpenBCI USB dongle. In Device Manager → Ports, note its
      COM port (for example `COM3`).
- [ ] Run from **Windows** Python (simplest for EEG; no WSL USB setup):
      ```powershell
      python signal_lab.py bridge --source "eeg:cyton?serial_port=COM3" --sink stats --seconds 10
      python signal_lab.py eeg-control --source "eeg:cyton?serial_port=COM3" --twin run.json
      ```
      Use `eeg:ganglion?serial_port=COM3` for a Ganglion. For
      `eeg-control`, sit still with eyes open while it calibrates, then close
      your eyes to `select` and open them for `next`.
- [ ] EEG is personal data. Keep it on your PC; `udp:` sinks stay local
      unless you add `--allow-remote`.

**Radio: SDR**

- [ ] **Start with an RTL-SDR** (about $30, receive only, legal to use
      anywhere). A **HackRF One** can also transmit, which needs a licence.
- [ ] **Install SoapySDR in Ubuntu**, and make a venv that can see it:
      ```bash
      sudo apt install -y python3-soapysdr soapysdr-module-all
      python3 -m venv --system-site-packages ~/venvs/network-os-sdr
      ~/venvs/network-os-sdr/bin/pip install -r requirements.txt
      ```
- [ ] **Connect the USB radio to WSL.** In PowerShell as administrator:
      ```powershell
      winget install usbipd
      usbipd list                           # find the radio's BUSID, e.g. 2-3
      usbipd bind --busid 2-3
      usbipd attach --wsl --busid 2-3       # repeat after each replug or reboot
      ```
- [ ] **Check it's seen, then receive** (FM broadcast band as a test):
      ```bash
      ~/venvs/network-os-sdr/bin/python signal_lab.py devices
      ~/venvs/network-os-sdr/bin/python signal_lab.py bridge \
          --source "rf:soapy:driver=rtlsdr?freq=100e6&rate=2.4e6&gain=30" --sink stats --seconds 5
      ```
- [ ] **Transmitting: only with a licence.** In the US that means an amateur
      radio licence (the Technician exam covers the 2 m and 70 cm bands). Then
      copy `signal_tx_policy.example.json` to `signal_tx_policy.json`, fill in
      your callsign as `operator`, keep only bands you're licensed for, and
      add `--transmit`:
      ```bash
      python signal_lab.py send-twin --twin run.json --transmit \
          --sink "rf:soapy:driver=hackrf?freq=144.39e6&rate=250e3"
      ```
      The lab refuses to transmit without both the flag and the policy file,
      outside a listed band, or past the band's airtime limit.

**Sending signals between machines**

- [ ] Pick a shared secret and set it on **both** machines before starting:
      ```powershell
      $env:SIGNAL_LINK_KEY = "a long random secret"
      ```
      Then use `udp:<other machine's IP>:9700` with `--allow-remote`, and allow
      that UDP port through the firewall only for the other machine.

---

## Daily checklist

- [ ] `git pull` for the latest code (or let Claude Code do it).
- [ ] `python -m pytest -q` still passes.
- [ ] `python node_supervisor.py --status` shows 3 nodes running.
- [ ] Ollama is running if you want AI summaries.
- [ ] After changing Python code, rebuild the Alpine image (`sudo sh linux/build.sh`)
      before testing in VMs.

## When something goes wrong

| Symptom | Fix |
|---|---|
| Ubuntu shows every file as modified | `git config core.autocrlf true` in the project |
| `No module named pytest` in Ubuntu | Use the venv's Python: `~/venvs/network-os/bin/python -m pytest` |
| `ensurepip is not available` | `sudo apt install python3-venv` |
| VMs are very slow | `/dev/kvm` is missing: turn on virtualization (part 1) |
| Out of memory with 3 VMs | Raise `memory` in `.wslconfig`, or use `swarm.sh --mem 320M` |
| `localhost:9601` refused in a browser | Expected: node ports speak the node protocol, not web pages |
| `SoapySDR isn't installed` | Part 8, radio steps 2–3 |
| `refused: transmitting needs --transmit` | Working as designed; see the licence step |
| Radio not listed by `devices` | Re-run `usbipd attach --wsl --busid ...` after replugging |
| Ollama errors | Check it's running (tray icon) and `ollama list` shows the model |
