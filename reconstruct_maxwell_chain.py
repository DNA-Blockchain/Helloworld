"""
reconstruct_maxwell_chain.py
================
Your file's ARRAY ORDER isn't the real chain order — the real order
lives in the hash <-> previous_hash links themselves. This builds the
actual tree from those links (genesis has multiple children at 46
fork points — likely concurrent mining, same as real blockchains
experience) and finds the longest valid path from genesis, which is
the canonical chain under standard "longest chain wins" consensus.

Blocks on shorter, abandoned branches aren't discarded — they're
returned separately as `orphaned_blocks`, same as a real blockchain
node would keep orphan blocks around rather than deleting them.

    python reconstruct_maxwell_chain.py [path to the exported chain]
"""

from __future__ import annotations
import json
import sys
from collections import defaultdict

DEFAULT_PATH = "autonomous/maxwell/maxwell_blockchain_20260810_190910.json"


def reconstruct_chain(raw_blocks: list[dict]) -> dict:
    hash_to_block = {b["hash"]: b for b in raw_blocks}
    children = defaultdict(list)
    for b in raw_blocks:
        children[b["previous_hash"]].append(b)

    genesis_candidates = [b for b in raw_blocks if b["previous_hash"] not in hash_to_block]
    if len(genesis_candidates) != 1:
        return {"error": f"expected exactly 1 genesis block, found {len(genesis_candidates)}"}
    genesis = genesis_candidates[0]

    # BFS from genesis, tracking the longest path to each reachable block
    depth = {genesis["hash"]: 1}
    parent_in_longest_path = {}
    queue = [genesis]
    reachable = {genesis["hash"]: genesis}

    while queue:
        current = queue.pop(0)
        for child in children[current["hash"]]:
            reachable[child["hash"]] = child
            new_depth = depth[current["hash"]] + 1
            if child["hash"] not in depth or new_depth > depth[child["hash"]]:
                depth[child["hash"]] = new_depth
                parent_in_longest_path[child["hash"]] = current["hash"]
            queue.append(child)

    deepest_hash = max(depth, key=depth.get)
    longest_chain = []
    h = deepest_hash
    while True:
        longest_chain.append(reachable[h])
        if h == genesis["hash"]:
            break
        h = parent_in_longest_path[h]
    longest_chain.reverse()

    longest_chain_hashes = {b["hash"] for b in longest_chain}
    orphaned = [b for b in raw_blocks if b["hash"] not in longest_chain_hashes]

    fork_points = {h: len(kids) for h, kids in children.items() if len(kids) > 1}

    return {
        "genesis": genesis,
        "longest_chain": longest_chain,
        "longest_chain_length": len(longest_chain),
        "orphaned_blocks": orphaned,
        "orphaned_count": len(orphaned),
        "fork_points": fork_points,
        "total_blocks": len(raw_blocks),
        "unreachable_blocks": [b for b in raw_blocks if b["hash"] not in reachable],
    }


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH
    with open(path, encoding="utf-8") as f:
        raw_blocks = json.load(f)

    result = reconstruct_chain(raw_blocks)

    if "error" in result:
        print("ERROR:", result["error"])
    else:
        print(f"Total blocks in file: {result['total_blocks']}")
        print(f"Longest valid chain from genesis: {result['longest_chain_length']} blocks")
        print(f"Orphaned blocks (real forks, not discarded): {result['orphaned_count']}")
        print(f"Blocks completely unreachable from genesis: {len(result['unreachable_blocks'])}")
        print(f"Number of real fork points: {len(result['fork_points'])}")

        print("\n=== Verifying the reconstructed longest chain actually links correctly ===")
        chain = result["longest_chain"]
        broken = sum(
            1 for i in range(1, len(chain))
            if chain[i]["previous_hash"] != chain[i - 1]["hash"]
        )
        print(f"Broken links in the RECONSTRUCTED chain: {broken} / {len(chain) - 1} (should be 0)")
