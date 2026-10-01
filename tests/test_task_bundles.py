"""Every os/tasks bundle is current and follows the kernel's manifest rules."""

import hashlib
import json
import re

import pytest

import build_task_bundles

FILE_NAME = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,14}$")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
BUNDLES = {bundle.name: bundle for bundle in build_task_bundles.BUNDLES}


@pytest.mark.parametrize("name", BUNDLES)
def test_bundle_is_up_to_date(name):
    bundle = BUNDLES[name]
    assert build_task_bundles.stale_files(bundle, build_task_bundles.build(bundle)) == []


@pytest.mark.parametrize("name", BUNDLES)
def test_bundle_manifests_follow_kernel_schemas(name):
    bundle = BUNDLES[name]
    files = build_task_bundles.build(bundle)
    task = json.loads(files[bundle.task_manifest])
    workflow = json.loads(files[bundle.workflow_manifest])

    assert set(task) == {"schemaVersion", "taskId", "runtime", "entrypoint", "files", "capabilities", "limits"}
    assert task["schemaVersion"] == "nosfs.task-bundle.v1" and task["runtime"] == "micropython"
    assert IDENTIFIER.match(task["taskId"])
    assert 16384 <= task["limits"]["memoryBytes"] <= 2097152
    assert 1 <= task["limits"]["runtimeSeconds"] <= 300
    assert task["entrypoint"] in [f["name"] for f in task["files"]]
    assert not any(task["capabilities"]["network"].values())
    for entry in task["files"]:
        data = files[entry["name"]]
        assert FILE_NAME.match(entry["name"])
        assert entry["sizeBytes"] == len(data) <= 65536
        assert entry["sha256"] == hashlib.sha256(data).hexdigest()

    assert workflow["schemaVersion"] == "nosfs.workflow.v1"
    for block in workflow["blocks"]:
        assert block["taskManifest"] in files
        assert all(output.endswith(".OUT") for output in block["outputFiles"])
        for file_name in block["inputFiles"] + block["outputFiles"] + [block["taskManifest"]]:
            assert FILE_NAME.match(file_name)
    assert len(files[bundle.task_manifest]) <= 4096 and len(files[bundle.workflow_manifest]) <= 4096
