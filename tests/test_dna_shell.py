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

import hashlib
import json

import pytest

import dna_shell


def test_encode_decode_files_and_audit_only_metadata(tmp_path):
    source = tmp_path / "source.bin"
    encoded = tmp_path / "source.dna"
    decoded = tmp_path / "decoded.bin"
    audit = tmp_path / "audit" / "events.jsonl"
    payload = b"private sample\x00\xff"
    source.write_bytes(payload)

    assert dna_shell.main(["encode", str(source), str(encoded), "--audit", str(audit)]) == 0
    assert set(encoded.read_text(encoding="ascii")) <= set("ACGT")
    assert dna_shell.main(["decode", str(encoded), str(decoded), "--audit", str(audit)]) == 0
    assert decoded.read_bytes() == payload

    entries = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert [entry["action"] for entry in entries] == ["file_encoded", "file_decoded"]
    assert all(payload.decode("latin-1") not in json.dumps(entry) for entry in entries)
    assert all("output_sha256" in entry["details"] for entry in entries)
    assert dna_shell.main(["verify", "--audit", str(audit)]) == 0


def test_existing_destination_requires_force(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "output"
    source.write_bytes(b"x")
    destination.write_bytes(b"keep")

    with pytest.raises(SystemExit) as exc:
        dna_shell.main(["encode", str(source), str(destination), "--audit", str(tmp_path / "audit.jsonl")])
    assert exc.value.code == 2
    assert destination.read_bytes() == b"keep"


def test_invalid_dna_does_not_write_output(tmp_path):
    source = tmp_path / "invalid.dna"
    destination = tmp_path / "decoded.bin"
    source.write_text("ACGX", encoding="ascii")

    with pytest.raises(ValueError):
        dna_shell.main(["decode", str(source), str(destination), "--audit", str(tmp_path / "audit.jsonl")])
    assert not destination.exists()


def test_audit_command_verifies_tampering(tmp_path, capsys):
    audit_path = tmp_path / "audit.jsonl"
    dna_shell._audit_at(audit_path).log(
        module="dna_shell", action="file_encoded", node_id="local", details={"input_bytes": 1}
    )
    original = audit_path.read_text(encoding="utf-8")
    audit_path.write_text(original.replace('"input_bytes": 1', '"input_bytes": 2'), encoding="utf-8")

    assert dna_shell.main(["verify", "--audit", str(audit_path)]) == 1
    assert "INVALID" in capsys.readouterr().out


def test_inspect_fasta_reports_iupac_and_rna_without_exposing_names(tmp_path, capsys):
    source = tmp_path / "samples.fasta"
    audit = tmp_path / "audit.jsonl"
    source.write_bytes(b">private-sample-1\nacgt RYSWKMBDHVN-.\n>private-sample-2\nUU\n")

    assert dna_shell.main(["inspect-fasta", str(source), "--audit", str(audit)]) == 0
    output = capsys.readouterr().out
    assert "FASTA: valid; records=2; bases=19" in output
    assert "RNA U=2; gaps=2" in output
    assert "private-sample" not in audit.read_text(encoding="utf-8")
    assert "acgt RYSWKMBDHVN" not in audit.read_text(encoding="utf-8")


def test_validate_fasta_rejects_invalid_symbols_and_records_result(tmp_path, capsys):
    source = tmp_path / "bad.fasta"
    audit = tmp_path / "audit.jsonl"
    source.write_text(">sample\nACGTZ\n", encoding="ascii")

    assert dna_shell.main(["validate-fasta", str(source), "--audit", str(audit)]) == 1
    output = capsys.readouterr().out
    assert "invalid nucleotide symbol 'Z'" in output
    entry = json.loads(audit.read_text(encoding="utf-8").splitlines()[0])
    assert entry["details"]["valid"] is False
    assert entry["details"]["invalid_symbol_count"] == 1
    assert "sample" not in json.dumps(entry)
    assert "ACGTZ" not in json.dumps(entry)


@pytest.mark.parametrize("contents", [
    b"ACGT\n>sample\nACGT\n",
    b">empty\n>second\nACGT\n",
    b">   \nACGT\n",
    b"",
])
def test_validate_fasta_rejects_malformed_records(tmp_path, contents):
    source = tmp_path / "malformed.fasta"
    source.write_bytes(contents)

    assert dna_shell._analyze_fasta(source)["valid"] is False


def test_import_fasta_copies_unchanged_and_writes_local_manifest(tmp_path):
    source = tmp_path / "source.fasta"
    source_bytes = b">synthetic-record\nACGTNNRY\n"
    source.write_bytes(source_bytes)
    data_dir = tmp_path / "datasets"
    audit = tmp_path / "audit.jsonl"

    assert dna_shell.main([
        "import-fasta", str(source), "--data-dir", str(data_dir), "--audit", str(audit)
    ]) == 0

    digest = hashlib.sha256(source_bytes).hexdigest()
    stored = data_dir / f"{digest}.fasta"
    manifest_path = data_dir / f"{digest}.json"
    assert source.read_bytes() == source_bytes
    assert stored.read_bytes() == source_bytes
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["sha256"] == digest
    assert manifest["classification"] == "private"
    assert manifest["sharing_status"] == "local_only"
    assert manifest["sequence_count"] == 1
    assert manifest["total_bases"] == 8
    entry = json.loads(audit.read_text(encoding="utf-8").splitlines()[0])
    assert entry["action"] == "dataset_imported"
    assert entry["details"]["dataset_id"] == manifest["dataset_id"]
    assert entry["details"]["classification"] == "private"
    assert digest not in json.dumps(entry)
    assert "synthetic-record" not in json.dumps(entry)
    assert "ACGTNNRY" not in json.dumps(entry)


def test_import_fasta_rejects_invalid_input_without_storing_dataset(tmp_path):
    source = tmp_path / "invalid.fasta"
    source.write_text(">sample\nACGT?\n", encoding="ascii")
    data_dir = tmp_path / "datasets"
    audit = tmp_path / "audit.jsonl"

    assert dna_shell.main([
        "import-fasta", str(source), "--data-dir", str(data_dir), "--audit", str(audit)
    ]) == 1
    assert not data_dir.exists()
    entry = json.loads(audit.read_text(encoding="utf-8").splitlines()[0])
    assert entry["action"] == "dataset_import_rejected"
