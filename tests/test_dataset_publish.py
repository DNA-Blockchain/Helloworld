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

import io
import json
import threading
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer

import pytest

import dataset_publish
import public_variant_sources
import research_viewer
from research_ledger import ResearchLedger, published_dataset_accessions
from research_provenance import (
    ResearchProvenanceQueue,
    create_public_dataset_record_event,
    validate_public_provenance,
)

FASTA = b">NM_007294.4 Homo sapiens BRCA1 DNA repair associated (BRCA1), mRNA\nACGTACGTAC\nGGTTAA\n"


@pytest.fixture
def fake_ncbi(monkeypatch):
    calls = []

    def fetch(accession):
        calls.append(accession)
        return FASTA.replace(b"NM_007294.4", accession.encode())

    monkeypatch.setattr(public_variant_sources, "fetch_nuccore_fasta", fetch)
    return calls


def event_for(accession="NM_007294.4", **overrides):
    fields = dict(dataset_id=str(uuid.uuid4()), accession=accession, title="BRCA1 mRNA", sequence_count=1,
                  total_bases=16, dataset_sha256="a" * 64, confirm_publication=True)
    fields.update(overrides)
    return create_public_dataset_record_event(**fields)


def test_dataset_event_links_public_source_and_rejects_tampering():
    event = event_for()
    assert event["source_url"] == "https://www.ncbi.nlm.nih.gov/nuccore/NM_007294.4"
    validate_public_provenance(event)
    for mutate, message in [
        (lambda e: e.update(accession="../../etc"), "accession"),
        (lambda e: e.update(source_url="https://evil.invalid/NM_007294.4"), "source URL"),
        (lambda e: e.update(source="private_lab"), "public database"),
        (lambda e: e.update(total_bases=True), "total_bases"),
        (lambda e: e.update(sequence="ACGT"), "unsupported fields"),
        (lambda e: e.update(classification="private"), "public FASTA"),
    ]:
        bad = dict(event)
        mutate(bad)
        with pytest.raises(ValueError, match=message):
            validate_public_provenance(bad)
    with pytest.raises(PermissionError):
        create_public_dataset_record_event(dataset_id=str(uuid.uuid4()), accession="NM_007294.4", title="t",
                                           sequence_count=1, total_bases=1, dataset_sha256="a" * 64)


def test_fetch_stores_validated_fasta_and_reuses_it(tmp_path, fake_ncbi):
    first = dataset_publish.fetch_dataset("NM_007294.4", tmp_path)
    assert (tmp_path / "NM_007294.4.fasta").read_bytes() == FASTA
    assert first["total_bases"] == 16 and first["sequence_count"] == 1
    assert first["title"].startswith("NM_007294.4 Homo sapiens BRCA1")
    again = dataset_publish.fetch_dataset("NM_007294.4", tmp_path)
    assert again["dataset_id"] == first["dataset_id"] and fake_ncbi == ["NM_007294.4"]


def test_invalid_fasta_is_not_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(public_variant_sources, "fetch_nuccore_fasta", lambda accession: b">x\n\n>y\nAC\n")
    with pytest.raises(ValueError, match="not valid FASTA"):
        dataset_publish.fetch_dataset("NM_000001.1", tmp_path)
    assert not (tmp_path / "NM_000001.1.fasta").exists()


def test_cli_skips_published_accessions_and_queues_on_confirm(tmp_path, fake_ncbi, capsys):
    (tmp_path / "node-0").mkdir()
    ResearchLedger(str(tmp_path / "node-0" / "research_ledger_node-0.json")).add_block(
        {"origin": 0, "index": 1, "research_provenance": event_for("NM_000059.4")})
    assert published_dataset_accessions(str(tmp_path)) == {"NM_000059.4"}

    outbox = tmp_path / "outbox"
    args = ["NM_007294.4", "NM_000059.4", "--store", str(tmp_path / "ds"), "--ledgers", str(tmp_path),
            "--outbox", str(outbox)]
    assert dataset_publish.main(args) == 0
    out = capsys.readouterr().out
    assert "NM_000059.4: already published" in out and "1 dataset record(s) not queued" in out
    assert dataset_publish.main(args + ["--confirm-publication"]) == 0
    [queued] = list(outbox.glob("*.json"))
    assert json.loads(queued.read_text())["accession"] == "NM_007294.4"


def test_fetch_nuccore_fasta_requests_efetch(monkeypatch):
    seen = {}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake(request, timeout, context):
        seen["url"] = request.full_url
        return Response(FASTA)

    monkeypatch.setattr(public_variant_sources.urllib.request, "urlopen", fake)
    monkeypatch.setattr(public_variant_sources.time, "sleep", lambda _: None)
    assert public_variant_sources.fetch_nuccore_fasta("NM_007294.4") == FASTA
    assert "db=nuccore" in seen["url"] and "rettype=fasta" in seen["url"]
    with pytest.raises(ValueError):
        public_variant_sources.fetch_nuccore_fasta("../etc/passwd")


def test_bad_outbox_entry_is_set_aside(tmp_path):
    queue = ResearchProvenanceQueue(tmp_path)
    good = queue.enqueue(event_for())
    (tmp_path / ("0" * 32 + ".json")).write_text('{"event_type": "unknown"}')
    moved = queue.reject_invalid()
    assert [p.name for p in moved] == ["0" * 32 + ".json"] and (tmp_path / "rejected").is_dir()
    assert queue.peek()[1] == good


def test_viewer_serves_verified_local_fasta_only(tmp_path):
    base = tmp_path / "auto"
    (base / "node-0").mkdir(parents=True)
    (base / "datasets").mkdir()
    import hashlib

    fasta = base / "datasets" / "NM_007294.4.fasta"
    fasta.write_bytes(FASTA)
    event = event_for(dataset_sha256=hashlib.sha256(FASTA).hexdigest())
    ResearchLedger(str(base / "node-0" / "research_ledger_node-0.json")).add_block(
        {"origin": 0, "index": 2, "hash_hex": "ab", "research_provenance": event})

    server = ThreadingHTTPServer(("127.0.0.1", 0), research_viewer.make_handler(str(base)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        [listed] = json.loads(urllib.request.urlopen(url + "/api/datasets", timeout=5).read())
        assert listed["accession"] == "NM_007294.4" and listed["local_copy"] is True
        download = url + f"/api/datasets/{event['dataset_id']}/fasta"
        assert urllib.request.urlopen(download, timeout=5).read() == FASTA

        fasta.write_bytes(FASTA + b"ACGT\n")          # local copy altered
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(download, timeout=5)
        assert error.value.code == 409
        fasta.unlink()
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(download, timeout=5)
        assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
