"""run_node_cli: argument parsing, key display, and refusing a changed
pinned key. The multi-process network path is covered by
test_network_node.py's same-port/different-host test."""
import pytest

import run_node_cli as cli


def test_parse_peers():
    assert cli.parse_peers("") == []
    assert cli.parse_peers("192.168.1.20:9601, 10.0.0.5:9602,") == [("192.168.1.20", 9601), ("10.0.0.5", 9602)]
    assert cli.parse_peers("[::1]:9601") == [("::1", 9601)]
    for bad in ("nonsense", ":9601", "host:0", "host:70000", "host:abc"):
        with pytest.raises(ValueError):
            cli.parse_peers(bad)


def test_parse_trust():
    key = "ab" * 32
    assert cli.parse_trust([f"1={key}", f"2={key.upper()}"]) == {1: key, 2: key}
    assert cli.parse_trust([f"1={key}, 2={key},"]) == {1: key, 2: key}
    for bad in ("1", f"x={key}", "1=abc", "1=" + "zz" * 32):
        with pytest.raises(ValueError):
            cli.parse_trust([bad])


def test_default_identity_text_is_neutral():
    assert cli.build_parser().parse_args(["--id", "0"]).identity_text == cli.DEFAULT_IDENTITY_TEXT


def test_run_all_default_listener_is_local_only():
    import run_all
    assert run_all.HOST == "127.0.0.1"


def test_research_gossip_is_opt_in():
    args = cli.build_parser().parse_args(["--id", "0", "--no-external-info"])
    assert args.allow_research_gossip is False
    assert cli.build_enrichers(args) == []

    args = cli.build_parser().parse_args([
        "--id", "0", "--allow-research-gossip", "--no-external-info"
    ])
    assert cli.build_enrichers(args) == [cli.research_enricher]


def test_external_data_enrichment_is_opt_in():
    default_args = cli.build_parser().parse_args(["--id", "0"])
    assert cli.build_enrichers(default_args) == []

    enabled_args = cli.build_parser().parse_args(["--id", "0", "--allow-external-info"])
    assert cli.build_enrichers(enabled_args) == [cli.external_info_enricher]


def test_provenance_queue_rejects_live_enrichers():
    with pytest.raises(SystemExit) as exc:
        import asyncio
        asyncio.run(cli.main([
            "--id", "0", "--provenance-queue", "outbox", "--allow-external-info"
        ]))
    assert exc.value.code == 2


def test_provenance_queue_allows_work_sharing():
    args = cli.build_parser().parse_args(["--id", "0", "--provenance-queue", "outbox", "--work-sharing"])
    assert args.provenance_queue == "outbox" and args.work_sharing


def test_research_gossip_flags_cannot_conflict():
    with pytest.raises(SystemExit) as exc:
        import asyncio
        asyncio.run(cli.main(["--id", "0", "--allow-research-gossip", "--no-research"]))
    assert exc.value.code == 2


async def test_show_key_is_stable_and_refuses_changed_pin(tmp_path, capsys):
    workdir = str(tmp_path / "n0")
    assert await cli.main(["--id", "0", "--workdir", workdir, "--show-key"]) == 0
    first = capsys.readouterr().out
    assert await cli.main(["--id", "0", "--workdir", workdir, "--show-key"]) == 0
    assert capsys.readouterr().out == first     # same saved key both times

    key = "ab" * 32
    assert await cli.main(["--id", "0", "--workdir", workdir, "--trust", f"1={key}", "--show-key"]) == 0
    capsys.readouterr()
    assert await cli.main(["--id", "0", "--workdir", workdir, "--trust", f"1={'cd' * 32}", "--show-key"]) == 1
    assert "REFUSING TO START" in capsys.readouterr().out


async def test_short_run_with_no_peers(tmp_path, capsys):
    rc = await cli.main(["--id", "3", "--port", "19597", "--workdir", str(tmp_path),
                         "--duration", "0.5", "--no-research", "--no-external-info"])
    out = capsys.readouterr().out
    assert rc == 0 and "chain intact" in out and "mined=1" in out
