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
Tests for signal_stats_bridge -- the enforced boundary that lets only
abstract statistics (never raw readings) out of EEG/hormone telemetry.

Two things are pinned here:
  1. The statistics themselves (signal_channel_stats).
  2. The boundary guarantees of fold_signal_into_strand: source
     restricted to the telemetry channels, raw readings never passed to
     the consent gate (only a hash of the stats), and the real
     digital_dna.py consent gate still enforced end-to-end.
"""
import hashlib
import json

import pytest

import signal_stats_bridge as ssb
from signal_stats_bridge import signal_channel_stats, fold_signal_into_strand
from digital_dna import DigitalDNA


# -- signal_channel_stats --------------------------------------------------

def test_empty_readings_report_only_a_zero_count():
    assert signal_channel_stats([], label="eeg") == {"eeg_count": 0}


def test_single_reading_has_zero_variance():
    stats = signal_channel_stats([12.0], label="eeg")
    assert stats == {"eeg_count": 1, "eeg_mean": 12.0, "eeg_variance": 0.0}


def test_multiple_readings_compute_mean_and_variance_with_label_prefix():
    stats = signal_channel_stats([2.0, 4.0, 6.0], label="hormone")
    assert stats["hormone_count"] == 3
    assert stats["hormone_mean"] == 4.0
    assert stats["hormone_variance"] == 4.0  # sample variance of [2,4,6]


# -- fold_signal_into_strand: boundary enforcement -------------------------

class _RecordingDNA:
    """Stand-in that records exactly what fold_signal_into_strand hands to
    the consent gate, so tests can assert raw readings never get through."""
    def __init__(self):
        self.calls = []

    def add_live_signal(self, **kwargs):
        self.calls.append(kwargs)
        return "event-sentinel"


def test_rejects_non_telemetry_source():
    dna = _RecordingDNA()
    with pytest.raises(ValueError):
        fold_signal_into_strand(dna, [1.0, 2.0], source="keyboard_cadence", consent_verified=True)
    assert dna.calls == []  # nothing reached the gate


def test_rejects_empty_readings():
    dna = _RecordingDNA()
    with pytest.raises(ValueError):
        fold_signal_into_strand(dna, [], source="eeg_telemetry", consent_verified=True)
    assert dna.calls == []


def test_only_a_hash_of_stats_reaches_the_gate_never_raw_readings():
    dna = _RecordingDNA()
    readings = [12.1, 12.4, 11.9, 12.6]
    event, stats = fold_signal_into_strand(dna, readings, source="eeg_telemetry", consent_verified=True)

    assert event == "event-sentinel"
    assert len(dna.calls) == 1
    call = dna.calls[0]

    # the source and consent flag are forwarded intact
    assert call["source"] == "eeg_telemetry"
    assert call["consent_verified"] is True

    # what was folded is exactly sha256(canonical json of the stats)
    expected = hashlib.sha256(
        json.dumps(stats, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert call["feature_hash_hex"] == expected

    # and crucially: no raw reading value appears anywhere in what was passed
    passed_blob = repr(call)
    for r in readings:
        assert repr(r) not in passed_blob
    assert stats == {"eeg_count": 4, "eeg_mean": 12.25, "eeg_variance": round(
        __import__("statistics").variance(readings), 4)}


def test_label_is_derived_by_stripping_telemetry_suffix():
    dna = _RecordingDNA()
    _, stats = fold_signal_into_strand(dna, [3.2, 3.4], source="hormone_telemetry", consent_verified=True)
    # source "hormone_telemetry" -> label "hormone"
    assert set(stats) == {"hormone_count", "hormone_mean", "hormone_variance"}


# -- end-to-end against the REAL consent gate ------------------------------

def test_real_dna_gate_refuses_without_consent(tmp_path):
    dna = DigitalDNA(seed_label="test-node", dna_path=str(tmp_path / "t.dna.json"))
    with pytest.raises(PermissionError):
        fold_signal_into_strand(dna, [12.0, 12.5], source="eeg_telemetry", consent_verified=False)


def test_real_dna_gate_folds_a_mutation_event_with_consent(tmp_path):
    dna = DigitalDNA(seed_label="test-node", dna_path=str(tmp_path / "t.dna.json"))
    strand_before = dna.strand
    event, stats = fold_signal_into_strand(
        dna, [12.0, 12.5, 12.2], source="eeg_telemetry", consent_verified=True)
    # a real mutation happened: the strand advanced and an event was returned
    assert dna.strand != strand_before
    assert hasattr(event, "strand_hex")
    assert stats["eeg_count"] == 3
