# Alpine Linux node image

A small Linux system that boots in QEMU and runs one network node
(`run_node_cli.py`). It sits beside the Rust kernel in `os/` and doesn't
replace it. Rust kernel is the from-scratch OS; this image is the practical
way to run the Python node on real Linux today.

Nothing is compiled. `build.sh` takes Alpine's prebuilt `linux-virt` kernel,
busybox and Python from Alpine's signed repositories, adds only the node
modules `run_node_cli.py` imports, and packs everything into a RAM root
filesystem. A build takes about a minute; a node is up about 3 seconds after
QEMU starts.

Run from WSL or Linux (not Windows PowerShell):

```sh
sudo sh linux/build.sh                    # -> ~/.cache/network-os-linux/{vmlinuz,initramfs.gz}
sh linux/run.sh --id 1                    # node 1 on port 9601, console in this terminal
sh linux/run.sh --id 2 --tofu --peers localhost:9601   # second VM, peered to the first
```

Leave the console with **Ctrl-A then X**, or type `poweroff -f`.

A three-VM swarm, fully meshed, cross-checking the DNA twin's analyses
(`swarm_analysis.py`):

```sh
sh linux/swarm.sh                         # until Ctrl-C, printing verdicts as they happen
sh linux/swarm.sh --round 15 --duration 70   # fixed run, then each node's summary
```

Each round, one VM runs the twin's RNA analyses on a public or synthetic
sequence, and a different VM recomputes them. A result is accepted when two
nodes publish the same SHA-256. On one test run, all three VMs recorded the
same 5 accepted rounds, and the digests matched the ones Ubuntu's Python got
on the host. Each VM uses 384 MB, so three together need about 1.2 GB.

| run.sh option | Meaning |
|---|---|
| `--id N` | node id (default 1) |
| `--port P` | node port, forwarded from the host (default 9600+N) |
| `--peers h:p,...` | other nodes; `localhost` is rewritten to the host (10.0.2.2) |
| `--tofu` | trust new peers on first contact |
| `--duration S` | run S seconds, then power off (used by the test) |
| `--mem 512M` | VM memory |
| `--ram-only` | don't keep node data; new keys every boot |
| `--swarm` | work sharing with swarm-verified twin analyses |
| `--round S` | work-sharing round length with `--swarm` (default 30) |

Node keys and chain live in `~/.cache/network-os-linux/node-data/node-N` on the
host, shared into the VM, so a node keeps its identity across reboots.

The node port speaks the node's encrypted peer protocol, not HTTP, so a browser
pointed at `localhost:9601` is refused. That's expected.

`tests/test_linux_image.py` boots the image and checks a node mines and
verifies its chain. It skips until the image has been built.

Settings: `ALPINE_VERSION` (default 3.24.2), `ALPINE_MIRROR`, `NOS_LINUX_BUILD`.
