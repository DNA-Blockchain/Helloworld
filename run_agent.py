# ============================================================================
#  SPDX-License-Identifier: UPL-1.0
#
#  Copyright (c) 2026 Chase Allen Ringquist
#
#  This file is part of an operating system, software, and network Work
#  conceived and authored by Chase Allen Ringquist. The Author retains
#  copyright and authorship. Use of this file is licensed as follows.
#
#  ----------------------------------------------------------------------------
#  The Universal Permissive License (UPL), Version 1.0
#
#  Subject to the condition set forth below, permission is hereby granted to
#  any person obtaining a copy of this software, associated documentation
#  and/or data (collectively the "Software"), free of charge and under any
#  and all copyright rights in the Software, and any and all patent rights
#  owned or freely licensable by each licensor hereunder covering either
#  (i) the unmodified Software as contributed to or provided by such
#  licensor, or (ii) the Larger Works (as defined below), to deal in both
#
#  (a) the Software, and
#
#  (b) any piece of software and/or hardware listed in the lrgrwrks.txt file
#  if one is included with the Software (each a "Larger Work" to which the
#  Software is contributed by such licensors),
#
#  without restriction, including without limitation the rights to copy,
#  create derivative works of, display, perform, and distribute the Software
#  and make, use, sell, offer for sale, import, export, have made, and have
#  sold the Software and the Larger Work(s), and to sublicense the foregoing
#  rights on either these or other terms.
#
#  This license is subject to the following condition:
#
#  The above copyright notice and either this complete permission notice or
#  at a minimum a reference to the UPL must be included in all copies or
#  substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#  DEALINGS IN THE SOFTWARE.
#  ----------------------------------------------------------------------------
#
#  Do not remove or alter this notice or any record of origin.
#  See NOTICE.md in the project root for authorship and ownership terms.
#
#  Contact:  ringquistchase@gmail.com  |  (918) 845-0940
#            Bixby, OK, United States
# ============================================================================

"""
run_agent.py
================
Actual real-time usage of GrowingResearchAgent — a script you run and
leave running, not a one-shot demo. Save this alongside all the other
.py files and run it directly:

    python run_agent.py

WHAT HAPPENS WHEN YOU RUN THIS
----------------------------------
1. Starts a real node listening on the port below.
2. Seeds ONE topic you specify (edit CONDITION / BIOMARKER below) —
   this runs immediately, hits all four real sources, mines a block.
3. Then the background loop takes over: every INTERVAL_SECONDS, it
   either explores one newly-discovered related topic, or re-checks
   your oldest topic for changes — same behavior as the demo, just
   running indefinitely instead of stopping after one step.
4. Everything persists to STORE_PATH, so stopping and restarting this
   script picks up exactly where it left off.

STOP IT WITH CTRL+C — it shuts down cleanly (see the try/finally below).

RATE LIMITS — READ THIS BEFORE SETTING INTERVAL_SECONDS LOW
-----------------------------------------------------------------
Every explore step makes several real HTTP calls (ClinicalTrials.gov,
PubMed, ClinVar, St. Jude searches, plus one HGNC call per candidate
gene it finds). NCBI's E-utilities ask for no more than ~3 requests/
second without a free API key, and will start rejecting requests if
you hammer them. INTERVAL_SECONDS=3600 (hourly) is a safe default.
Don't set this to seconds — you'll get rate-limited and the agent
will just see failed requests, not faster results.
"""

import asyncio
import signal

from digital_dna import DigitalDNA
from network_os import NetworkNode
from growing_research_agent import GrowingResearchAgent

# ---- edit these for your real use ----
SEED_LABEL = "my-research-node"          # your node's identity label
HOST, PORT = "0.0.0.0", 8765             # change PORT if it's already in use
STORE_PATH = "research_store.json"       # grows here, survives restarts
INTERVAL_SECONDS = 3600                  # hourly — see rate-limit note above
CONDITION = "breast cancer"              # <-- set this to what you actually want
BIOMARKER = "BRCA1"                      # <-- or None if you don't have one
# ----------------------------------------


async def main(host: str = HOST, port: int = PORT):
    dna = DigitalDNA(seed_label=SEED_LABEL)
    node = NetworkNode(dna, host=host, port=port)
    await node.start()
    print(f"[node] listening on {host}:{port}, node_id={node.node_id}")

    agent = GrowingResearchAgent(
        node, dna, store_path=STORE_PATH,
        interval_s=INTERVAL_SECONDS, max_topics=50,
    )
    await agent.start()
    print(f"[agent] background loop started, checking every {INTERVAL_SECONDS}s")

    key = await agent.seed_topic(CONDITION, biomarker=BIOMARKER)
    t = agent.topics[key]
    print(f"[agent] seeded topic '{key}': {len(t['new_ids_last_run'])} real results found")
    print(f"[agent] {len(agent.queue)} related topic(s) queued for future exploration")
    print(f"\n[agent] now running in the background. Ctrl+C to stop.")

    # optional: connect to a peer running the same script elsewhere, so
    # you both share discovered topics instead of exploring independently
    # await node.connect_peer("<their real IP>", <their real port>)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass   # Windows doesn't support add_signal_handler for these — Ctrl+C still raises KeyboardInterrupt below

    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        print("\n[shutdown] stopping cleanly...")
        await agent.stop()
        await node.stop()
        print(f"[shutdown] done. Progress saved to {STORE_PATH} — rerun this script anytime to continue.")


if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser(description="Run the growing research agent and its node until stopped.")
    cli.add_argument("--host", default=HOST, help=f"address the node listens on (default {HOST}; "
                                                  "127.0.0.1 keeps it to this PC)")
    cli.add_argument("--port", type=int, default=PORT, help=f"node port (default {PORT})")
    cli_args = cli.parse_args()
    asyncio.run(main(cli_args.host, cli_args.port))
