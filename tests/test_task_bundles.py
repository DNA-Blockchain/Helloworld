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
