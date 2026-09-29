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

"""run_self_tests.py with stand-in components in a temp dir: pass, fail,
missing (not a failure), timeout, non-cp1252 output, the API-key scan,
and the JSON summary the daily report reads."""
import json
import subprocess
import sys

import run_self_tests as rst


def _components(tmp_path):
    (tmp_path / "ok.py").write_text("print('fine')\n", encoding="utf-8")
    (tmp_path / "bad.py").write_text("raise SystemExit(2)\n", encoding="utf-8")
    (tmp_path / "unicode.py").write_text("print('\\u2713 passed \\u2014 ok')\n", encoding="utf-8")
    (tmp_path / "slow.py").write_text("import time; time.sleep(300)\n", encoding="utf-8")
    (tmp_path / "uses_key.py").write_text("import os\nos.environ.get('ANTHROPIC_API_KEY')\n",
                                          encoding="utf-8")
    return [
        ("ok", "ok.py", [], False, False),
        ("bad", "bad.py", [], False, False),
        ("unicode", "unicode.py", [], False, False),
        ("slow", "slow.py", [], False, False),
        ("not here", "missing.py", [], False, False),
        ("net", "ok.py", ["{log_dir}"], True, False),
        ("key user", "uses_key.py", [], False, False),
    ]


def test_statuses_counts_and_key_scan(tmp_path):
    comps = _components(tmp_path)
    out = rst.run_all(str(tmp_path / "logs"), skip_network=True, timeout=30, components=comps,
                      workdir=str(tmp_path), echo=lambda *_: None)
    status = {r["label"]: r["status"] for r in out["results"]}
    assert status == {"ok": "PASS", "bad": "FAIL", "unicode": "PASS", "slow": "FAIL",
                      "not here": "MISSING", "net": "SKIP", "key user": "PASS"}
    assert out["counts"] == {"PASS": 3, "FAIL": 2, "MISSING": 1, "SKIP": 1}
    assert out["ok"] is False
    assert out["components_referencing_api_key"] == ["uses_key.py"]
    assert out["api_key_validator"] == "MISSING"
    log = (tmp_path / "logs" / "unicode.log").read_text(encoding="utf-8")
    assert "\u2713 passed \u2014 ok" in log


def test_utf8_is_what_makes_the_unicode_component_pass(tmp_path):
    """Without PYTHONIOENCODING the same component fails on this machine's
    cp1252 default when its output goes to a file (skip where the default
    is already UTF-8)."""
    import locale
    if locale.getpreferredencoding(False).lower().replace("-", "") == "utf8":
        return
    script = tmp_path / "u.py"
    script.write_text("print('\\u2713')\n", encoding="utf-8")
    with open(tmp_path / "raw.log", "w", encoding="utf-8") as f:
        env = {k: v for k, v in __import__("os").environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
        code = subprocess.run([sys.executable, str(script)], stdout=f, stderr=subprocess.STDOUT, env=env).returncode
    assert code != 0


def test_all_pass_and_missing_is_not_failure(tmp_path):
    (tmp_path / "ok.py").write_text("print('fine')\n", encoding="utf-8")
    comps = [("ok", "ok.py", [], False, False), ("gone", "gone.py", [], False, False)]
    out = rst.run_all(str(tmp_path / "logs"), components=comps, workdir=str(tmp_path), echo=lambda *_: None)
    assert out["ok"] is True and out["counts"]["MISSING"] == 1


def test_real_components_list_matches_the_project():
    # every component either exists or is one of the known not-yet-added files
    import os
    known_missing = {"outbox_queue.py", "region_bounded_pipeline.py", "cancer_panels.py", "vcf_ingestion.py",
                     "cancer_remission_demo.py", "pathologist_agent.py"}
    for _, fname, *_ in rst.COMPONENTS:
        assert os.path.exists(os.path.join(rst.WORKDIR, fname)) or fname in known_missing, fname


def test_report_section_and_attention_rule():
    import datetime as dt
    import node_supervisor as sup
    snaps = {"a": {"node_id": 0, "boot_id": "a", "started_at": 0, "updated_at": 60, "stats": {},
                   "chain_ok": True, "work": {}}}
    fine = {"counts": {"PASS": 7, "FAIL": 0, "MISSING": 6, "SKIP": 0},
            "results": [{"label": "x", "file": "cancer_panels.py", "status": "MISSING"}]}
    md, ok, _ = sup.build_report(dt.date(2026, 9, 26), 0, 60, snaps, [], None, {}, 1, fine)
    assert ok and "7 passed, 0 failed, 6 not in the project yet" in md and "cancer_panels.py" in md

    broken = {"counts": {"PASS": 6, "FAIL": 1, "MISSING": 0, "SKIP": 0},
              "results": [{"label": "codec", "file": "dna_binary_codec.py", "status": "FAIL", "log": "l"}]}
    md, ok, reasons = sup.build_report(dt.date(2026, 9, 26), 0, 60, snaps, [], None, {}, 1, broken)
    assert not ok and any("dna_binary_codec.py" in r for r in reasons)
    md, ok, reasons = sup.build_report(dt.date(2026, 9, 26), 0, 60, snaps, [], None, {}, 1, {"error": "boom"})
    assert not ok and "boom" in md


def test_cli_writes_json(tmp_path, monkeypatch):
    monkeypatch.setattr(rst, "COMPONENTS", [])
    out = tmp_path / "s.json"
    assert rst.main(["--log-dir", str(tmp_path / "logs"), "--json-out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["counts"]["FAIL"] == 0
