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

"""Drives run_local.ps1 through Windows PowerShell with scripted -Answers,
on a copy of the project so option 2 doesn't write node_data/ into the
repo. Skipped where powershell.exe isn't available."""
import glob
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")

pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell not available")


@pytest.fixture
def project_copy(tmp_path):
    for path in glob.glob(os.path.join(ROOT, "*.py")) + [os.path.join(ROOT, "run_local.ps1")]:
        shutil.copy(path, tmp_path)
    return tmp_path


def run_ps1(project, answers, extra_env=None):
    env = dict(os.environ, **(extra_env or {}))
    proc = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(project / "run_local.ps1"), "-Answers", answers, "-NoPause"],
        capture_output=True, text=True, timeout=600, env=env,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_codec_self_test_option(project_copy):
    code, out = run_ps1(project_copy, "4")
    assert code == 0, out
    assert "all checks PASSED" in out and "Done." in out


def test_show_key_option(project_copy):
    code, out = run_ps1(project_copy, "3|7")
    assert code == 0, out
    assert "node-7 public signing key:" in out


def test_run_node_with_blank_answers_uses_defaults(project_copy):
    # id 7, port 19596, everything else blank -> defaults; 1 second run
    code, out = run_ps1(project_copy, "2|7|19596|||||1")
    assert code == 0, out
    assert "REAL NETWORK NODE  id=7  bind=127.0.0.1:19596" in out
    assert "chain intact (OK)" in out


def test_bad_input_is_an_error_not_a_command(project_copy):
    code, out = run_ps1(project_copy, "2|7|||x:1 & echo INJECTED||||1")
    assert code != 0
    assert "has an invalid port" in out
    assert "\nINJECTED" not in out


def test_custom_option_rejects_a_folder_and_invalid_choice_fails(project_copy):
    (project_copy / "somedir").mkdir()
    code, out = run_ps1(project_copy, "6|somedir")
    assert code == 1 and "is not a file" in out
    code, out = run_ps1(project_copy, "9")
    assert code == 1 and "No valid choice" in out


def test_python_failure_exit_code_is_reported(project_copy):
    (project_copy / "fails.py").write_text("raise SystemExit(3)\n")
    code, out = run_ps1(project_copy, "6|fails.py")
    assert code == 3 and "exited with code 3" in out
