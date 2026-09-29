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

from research_art_generator import _build_art_prompt


def test_deterministic_same_input_same_output():
    mos = {"mos": 4.5, "quality": 4.8, "connectivity": 5.0, "agreement": 3.5}
    p1 = _build_art_prompt(mos, topic_count=3, style="abstract, calm blues")
    p2 = _build_art_prompt(mos, topic_count=3, style="abstract, calm blues")
    assert p1 == p2


def test_style_appears_in_prompt():
    mos = {"mos": 3.0, "quality": 3.0, "connectivity": 3.0, "agreement": 3.0}
    prompt = _build_art_prompt(mos, topic_count=1, style="abstract, calm blues")
    assert "abstract, calm blues" in prompt


def test_high_quality_produces_dense_descriptor():
    mos = {"mos": 4.5, "quality": 4.8, "connectivity": 3.0, "agreement": 3.0}
    prompt = _build_art_prompt(mos, topic_count=1)
    assert "dense" in prompt


def test_low_quality_produces_sparse_descriptor():
    mos = {"mos": 1.5, "quality": 1.0, "connectivity": 3.0, "agreement": 3.0}
    prompt = _build_art_prompt(mos, topic_count=1)
    assert "sparse" in prompt


def test_extra_signal_stats_are_included():
    mos = {"mos": 3.0, "quality": 3.0, "connectivity": 3.0, "agreement": 3.0}
    stats = {"conn_reconnect_count": 5}
    prompt = _build_art_prompt(mos, topic_count=1, extra_signal_stats=stats)
    assert "conn_reconnect_count=5" in prompt


def test_none_valued_extra_stats_are_skipped():
    mos = {"mos": 3.0, "quality": 3.0, "connectivity": 3.0, "agreement": 3.0}
    stats = {"conn_avg_seconds_between_reconnects": None}
    prompt = _build_art_prompt(mos, topic_count=1, extra_signal_stats=stats)
    assert "conn_avg_seconds_between_reconnects" not in prompt


def test_missing_mos_keys_fall_back_to_defaults():
    prompt = _build_art_prompt({}, topic_count=0)
    assert "overall_score=3.00" in prompt
