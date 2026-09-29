import json
import re

import pytest

import build_remission_bundle
import remission_core
import remission_workflow
from dna_binary_codec import decode_from_dna


def test_demo_matches_documented_workflow():
    result = remission_core.run(remission_workflow.DEMO_REQUEST)

    assert result["before"]["binary"] == "00 01 10 11 00 01 00 11 00 01 10 11"
    assert result["mutations"] == [{
        "mutation_id": "MUT-000001", "position": 7, "reference": "G", "observed": "A",
        "reference_bits": "10", "observed_bits": "00", "type": "substitution",
    }]
    assert result["modeled_edit"][0]["from"] == "A" and result["modeled_edit"][0]["to"] == "G"
    assert result["after"]["sequence"] == "ACGTACGTACGT"
    assert result["verification"]["matching_positions"] == 12
    assert result["verification"]["different_positions"] == 0
    assert result["verification"]["mutation_positions"][0]["status"] == "match"
    assert result["assessment"]["modeled_status"] == remission_core.MODELED_REFERENCE_MATCH
    assert result["assessment"]["longitudinal_trend"] == "FOLLOW_UP_MATCHES_REFERENCE"
    assert [b["kind"] for b in result["ledger"]["blocks"]] == [
        "REFERENCE", "CANCER_SAMPLE", "MUTATION", "CRISPR_EDIT_MODEL",
        "POST_EDIT", "VERIFICATION", "FOLLOW_UP", "ASSESSMENT",
    ]
    assert result["ledger"]["verified"] is True


def test_binary_encoding_agrees_with_project_codec():
    sequence = "ACGTACATACGT"
    bits = remission_core.to_binary(sequence).replace(" ", "")
    assert bits == "".join(f"{byte:08b}" for byte in decode_from_dna(sequence))


def test_modeled_match_never_implies_clinical_remission():
    result = remission_core.run(remission_workflow.DEMO_REQUEST)
    assert result["assessment"]["modeled_status"] == remission_core.MODELED_REFERENCE_MATCH
    assert result["assessment"]["clinical_status"] == {
        "status": remission_core.NOT_CLINICALLY_CONFIRMED, "source": "none",
    }


def test_clinical_status_only_from_attributed_external_evidence():
    request = dict(remission_workflow.DEMO_REQUEST)
    request["clinical_evidence"] = {"remission_confirmed": True}
    with pytest.raises(ValueError, match="assessed_by"):
        remission_core.run(request)

    request["clinical_evidence"] = {
        "remission_confirmed": True, "assessed_by": "oncology team", "assessed_on": "2026-09-28",
    }
    clinical = remission_core.run(request)["assessment"]["clinical_status"]
    assert clinical["status"] == remission_core.CLINICALLY_CONFIRMED_REMISSION
    assert clinical["source"] == "externally_supplied"


def test_follow_up_detects_returning_mutation():
    request = dict(remission_workflow.DEMO_REQUEST)
    request["follow_ups"] = [
        {"label": "T3", "sequence": "ACGTACGTACGT"},
        {"label": "T4", "sequence": "ACGTACATACGT"},
    ]
    result = remission_core.run(request)
    assert result["follow_ups"][1]["original_mutations_present"] == ["MUT-000001"]
    assert result["follow_ups"][1]["differences_vs_previous_follow_up"] == 1
    assert result["assessment"]["longitudinal_trend"] == "ORIGINAL_MUTATION_DETECTED"


def test_ledger_holds_hashes_not_sequences():
    result = remission_core.run(remission_workflow.DEMO_REQUEST)
    ledger_text = json.dumps(result["ledger"])
    assert "ACGT" not in ledger_text
    for block in result["ledger"]["blocks"]:
        assert set(block) == {"index", "kind", "payload_sha256", "previous_hash", "block_hash"}


def test_ledger_detects_tampering():
    result = remission_core.run(remission_workflow.DEMO_REQUEST)
    blocks, records = result["ledger"]["blocks"], result["records"]

    altered = json.loads(json.dumps(records))
    altered[blocks[4]["payload_sha256"]]["sequence"] = "ACGTACATACGT"
    ok, problems = remission_core.verify_ledger(blocks, altered)
    assert not ok and "block 5: record altered" in problems

    reordered = [dict(b) for b in blocks]
    reordered[2], reordered[3] = reordered[3], reordered[2]
    assert not remission_core.verify_ledger(reordered)[0]


@pytest.mark.parametrize("request_patch, message", [
    ({"sample": "ACGTACATACG"}, "insertions/deletions"),
    ({"sample": "ACGTACNTACGT"}, "non-ACGT"),
    ({"reference": ""}, "empty"),
    ({"reference": "A" * 5000, "sample": "A" * 5000}, "exceeds"),
])
def test_rejects_unsupported_input(request_patch, message):
    request = dict(remission_workflow.DEMO_REQUEST)
    request.update(request_patch)
    with pytest.raises(ValueError, match=message):
        remission_core.run(request)


def test_canonical_json_is_deterministic_and_ascii():
    assert remission_core.canonical_json({"b": [1, True, None], "a": "é\"x"}) == \
        '{"a":"\\u00e9\\"x","b":[1,true,null]}'
    value = {"z": {"y": 1, "x": [2, "s"]}, "k": False}
    assert json.loads(remission_core.canonical_json(value)) == value


def test_task_entrypoint_prints_ledger_only(tmp_path, monkeypatch, capsys):
    (tmp_path / "SAMPLE.JSON").write_text(json.dumps(remission_workflow.DEMO_REQUEST))
    monkeypatch.chdir(tmp_path)
    assert remission_core.main(["REMISSION.PY"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["modeled_status"] == remission_core.MODELED_REFERENCE_MATCH
    assert "records" not in output and "ACGT" not in json.dumps(output)


def test_host_report_and_vault(tmp_path, monkeypatch, capsys):
    pytest.importorskip("cryptography")
    monkeypatch.setenv(remission_workflow.PASSPHRASE_ENV, "test-passphrase")
    out_file = tmp_path / "result.json"
    code = remission_workflow.main(["--vault", "--vault-dir", str(tmp_path / "vault"), "--output", str(out_file)])
    assert code == 0
    report = capsys.readouterr().out
    assert "MUT-000001" in report and "MODELED_REFERENCE_MATCH" in report
    assert "NOT_CLINICALLY_CONFIRMED" in report
    saved = json.loads(out_file.read_text())
    assert set(saved["records"]) == {"vault"}
    assert list((tmp_path / "vault").iterdir())


# --------------------------------------------------- kernel bundle contract

FILE_NAME = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,14}$")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")


def test_bundle_is_up_to_date():
    assert build_remission_bundle.stale_files(build_remission_bundle.build()) == []


def test_bundle_manifests_follow_kernel_schemas():
    files = build_remission_bundle.build()
    task = json.loads(files["RMTASK.JSON"])
    workflow = json.loads(files["RMFLOW.JSON"])

    assert set(task) == {"schemaVersion", "taskId", "runtime", "entrypoint", "files", "capabilities", "limits"}
    assert task["schemaVersion"] == "nosfs.task-bundle.v1" and task["runtime"] == "micropython"
    assert IDENTIFIER.match(task["taskId"])
    assert 16384 <= task["limits"]["memoryBytes"] <= 2097152
    assert 1 <= task["limits"]["runtimeSeconds"] <= 300
    assert task["entrypoint"] in [f["name"] for f in task["files"]]
    for entry in task["files"]:
        data = files[entry["name"]]
        assert FILE_NAME.match(entry["name"])
        assert entry["sizeBytes"] == len(data) <= 262144
        assert entry["sha256"] == build_remission_bundle.hashlib.sha256(data).hexdigest()

    assert workflow["schemaVersion"] == "nosfs.workflow.v1"
    for block in workflow["blocks"]:
        assert block["taskManifest"] in files
        for name in block["inputFiles"] + block["outputFiles"] + [block["taskManifest"]]:
            assert FILE_NAME.match(name)
    for name in files:
        assert len(name) <= 15
    assert len(files["RMTASK.JSON"]) <= 4096 and len(files["RMFLOW.JSON"]) <= 4096
