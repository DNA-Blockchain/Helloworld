from reconstruct_maxwell_chain import reconstruct_chain


def _block(name, parent):
    return {"hash": name, "previous_hash": parent}


def test_the_longest_branch_is_the_chain_and_forks_are_kept():
    blocks = [_block("g", "0x0"), _block("a", "g"), _block("b", "a"), _block("fork", "g"), _block("c", "b")]
    result = reconstruct_chain(blocks)
    assert [b["hash"] for b in result["longest_chain"]] == ["g", "a", "b", "c"]
    assert [b["hash"] for b in result["orphaned_blocks"]] == ["fork"]
    assert result["fork_points"] == {"g": 2} and result["unreachable_blocks"] == []


def test_more_than_one_genesis_is_an_error():
    assert "error" in reconstruct_chain([_block("g1", "x"), _block("g2", "y")])
