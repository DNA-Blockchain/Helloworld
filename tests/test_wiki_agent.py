import json
import socket

import pytest

import wiki_agent


def test_code_search_excludes_runtime_and_hidden_directories(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "dna_shell_data").mkdir()
    (tmp_path / ".private").mkdir()
    (tmp_path / "src" / "module.py").write_text(
        "def local_research_agent(query):\n    return query\n", encoding="utf-8"
    )
    (tmp_path / "dna_shell_data" / "secret.py").write_text(
        "local_research_agent secret\n", encoding="utf-8"
    )
    (tmp_path / ".private" / "hidden.py").write_text(
        "local_research_agent hidden\n", encoding="utf-8"
    )

    matches = wiki_agent.search_codebase(tmp_path, "local_research_agent")

    assert matches == [{
        "path": "src/module.py",
        "line": 1,
        "snippet": "def local_research_agent(query):",
    }]


def test_wiki_search_keeps_public_api_confirmation_separate(tmp_path, monkeypatch):
    (tmp_path / "agent.py").write_text("public research catalog\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        wiki_agent,
        "search_public_sources",
        lambda query, sources, max_results: calls.append((query, sources, max_results)) or [{
            "source": "pubmed",
            "external_id": "123",
            "title": "Public research record",
            "abstract": "catalog term",
            "source_url": "https://pubmed.example/123",
            "classification": "public",
        }],
    )
    agent = wiki_agent.WikiAgent(
        repository_root=tmp_path,
        catalog_path=tmp_path / "catalog.sqlite3",
    )

    with pytest.raises(PermissionError, match="explicit confirmation"):
        agent.search("catalog", sources=("pubmed",))
    assert calls == []

    result = agent.search(
        "catalog", sources=("pubmed",), confirm_public_query=True
    )
    assert calls == [("catalog", ("pubmed",), 10)]
    assert result["code_matches"][0]["path"] == "agent.py"
    assert result["new_records_saved"] == 1
    assert result["catalog_matches"][0]["citation"]["record_id"] == "123"
    assert result["automatic_download"] is False


def test_download_requires_confirmation_rights_and_allowlisted_public_host(
    tmp_path, monkeypatch
):
    with pytest.raises(PermissionError, match="explicit confirmation"):
        wiki_agent.fetch_public_file(
            "https://ftp.ncbi.nlm.nih.gov/pub/data.bin",
            license_declaration="CC0-1.0",
            confirm_public_download=False,
            destination_dir=tmp_path,
        )
    with pytest.raises(ValueError, match="license declaration"):
        wiki_agent.fetch_public_file(
            "https://ftp.ncbi.nlm.nih.gov/pub/data.bin",
            license_declaration="unknown",
            confirm_public_download=True,
            destination_dir=tmp_path,
        )
    with pytest.raises(ValueError, match="not allowlisted"):
        wiki_agent.fetch_public_file(
            "https://attacker.example/private",
            license_declaration="CC0-1.0",
            confirm_public_download=True,
            destination_dir=tmp_path,
        )


def test_download_rejects_credentials_redirect_and_non_global_dns(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="credentials"):
        wiki_agent._validate_download_url("https://user:pass@ftp.ncbi.nlm.nih.gov/file")

    monkeypatch.setattr(
        wiki_agent.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443))
        ],
    )
    with pytest.raises(ValueError, match="non-public"):
        wiki_agent._validate_download_url("https://ftp.ncbi.nlm.nih.gov/file")


def test_download_writes_content_addressed_file_and_provenance_manifest(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        wiki_agent.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443))
        ],
    )

    class Response:
        status = 200
        payload = b"public synthetic test dataset"
        offset = 0

        def getheader(self, name):
            return str(len(self.payload))

        def read(self, size):
            part = self.payload[self.offset:self.offset + size]
            self.offset += len(part)
            return part

    response = Response()
    requests = []

    class Connection:
        def __init__(self, host, address, timeout, context):
            assert host == "ftp.ncbi.nlm.nih.gov"
            assert address == "8.8.8.8"
            assert timeout == 30
            assert context is not None

        def request(self, method, target, headers):
            requests.append((method, target, headers))

        def getresponse(self):
            return response

        def close(self):
            pass

    monkeypatch.setattr(wiki_agent, "_PinnedHTTPSConnection", Connection)
    result = wiki_agent.fetch_public_file(
        "https://ftp.ncbi.nlm.nih.gov/pub/data.bin",
        license_declaration="CC0-1.0",
        confirm_public_download=True,
        destination_dir=tmp_path / "downloads",
    )

    assert requests[0][0:2] == ("GET", "/pub/data.bin")
    assert result["rights_status"].startswith("user-declared")
    assert result["automatic_network_sharing"] is False
    data_path = tmp_path / "downloads" / result["stored_file"]
    manifest_path = tmp_path / "downloads" / result["manifest_path"].split("\\")[-1]
    assert data_path.read_bytes() == Response.payload
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["license_declaration"] == "CC0-1.0"
    assert manifest["sha256"] == result["sha256"]


def test_download_enforces_size_limit_and_rejects_redirect(tmp_path, monkeypatch):
    monkeypatch.setattr(
        wiki_agent.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443))
        ],
    )

    class Response:
        status = 302

        def getheader(self, name):
            return "https://elsewhere.example/payload"

        def read(self, size):
            return b""

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(wiki_agent, "_PinnedHTTPSConnection", Connection)
    with pytest.raises(RuntimeError, match="HTTP 302"):
        wiki_agent.fetch_public_file(
            "https://ftp.ncbi.nlm.nih.gov/pub/data.bin",
            license_declaration="CC0-1.0",
            confirm_public_download=True,
            destination_dir=tmp_path / "downloads",
        )

    class OversizedResponse(Response):
        status = 200

        def getheader(self, name):
            return "11"

    Connection.getresponse = lambda self: OversizedResponse()
    with pytest.raises(ValueError, match="size limit"):
        wiki_agent.fetch_public_file(
            "https://ftp.ncbi.nlm.nih.gov/pub/data.bin",
            license_declaration="CC0-1.0",
            confirm_public_download=True,
            destination_dir=tmp_path / "downloads",
            max_bytes=10,
        )
    assert not list((tmp_path / "downloads").glob("*.data"))


def test_download_rejects_truncated_response_without_installing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        wiki_agent.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443))
        ],
    )

    class Response:
        status = 200
        offset = 0

        def getheader(self, name):
            return "10"

        def read(self, size):
            if self.offset:
                return b""
            self.offset = 1
            return b"short"

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(wiki_agent, "_PinnedHTTPSConnection", Connection)
    with pytest.raises(RuntimeError, match="ended before"):
        wiki_agent.fetch_public_file(
            "https://ftp.ncbi.nlm.nih.gov/pub/data.bin",
            license_declaration="CC0-1.0",
            confirm_public_download=True,
            destination_dir=tmp_path / "downloads",
        )
    assert not list((tmp_path / "downloads").glob("*.data"))
    assert not list((tmp_path / "downloads").glob("*.json"))
