#!/bin/sh
# Starts N Alpine VMs (default 3) as a fully meshed swarm: every node peers
# with every other, shares work, and cross-checks the DNA twin's analyses.
#   swarm.sh [--nodes N] [--round S] [--duration S] [--mem 384M]
# Logs go to $NOS_LINUX_BUILD/logs/node-N.log. Without --duration it runs until
# Ctrl-C, then stops every VM.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
BUILD=${NOS_LINUX_BUILD:-$HOME/.cache/network-os-linux}
NODES=3 ROUND=20 DURATION=0 MEM=384M
while [ $# -gt 0 ]; do
    case $1 in
        --nodes) NODES=$2; shift ;;
        --round) ROUND=$2; shift ;;
        --duration) DURATION=$2; shift ;;
        --mem) MEM=$2; shift ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

mkdir -p "$BUILD/logs"
PIDS=
stop() {
    [ -n "$PIDS" ] && kill $PIDS 2>/dev/null
    wait 2>/dev/null
    return 0
}
trap 'stop; exit 130' INT TERM

for i in $(seq 1 "$NODES"); do
    peers=
    for j in $(seq 1 "$NODES"); do
        [ "$j" = "$i" ] || peers="${peers:+$peers,}localhost:$((9600 + j))"
    done
    sh "$HERE/run.sh" --id "$i" --peers "$peers" --tofu --swarm --round "$ROUND" \
        --duration "$DURATION" --mem "$MEM" > "$BUILD/logs/node-$i.log" 2>&1 &
    PIDS="$PIDS $!"
    echo "node $i: port $((9600 + i)), log $BUILD/logs/node-$i.log"
done

if [ "$DURATION" = 0 ]; then
    echo "swarm running; Ctrl-C stops every VM. Verdicts as they happen:"
    tail -qf "$BUILD"/logs/node-*.log | grep --line-buffered -E "swarm round|took over|!!"
else
    wait
    for i in $(seq 1 "$NODES"); do
        echo "== node $i"
        grep -E "swarm verdicts|  round |chain verify|NOS-NODE-EXIT" "$BUILD/logs/node-$i.log" || true
    done
fi
