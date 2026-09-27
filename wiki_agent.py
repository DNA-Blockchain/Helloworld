"""Local code and public-research librarian with guarded file downloads."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import ipaddress
import json
import os
import socket
import ssl
import tempfile
import time
import urllib.parse
from pathlib import Path

import certifi

from research_catalog import DEFAULT_CATALOG, ResearchCatalog, search_public_sources

ALLOWED_DOWNLOAD_HOSTS = frozenset({
    "ftp.ensembl.org",
    "ftp.ncbi.nlm.nih.gov",
    "gnomad.broadinstitute.org",
    "www.ebi.ac.uk",
})
ALLOWED_LICENSE_DECLARATIONS = frozenset({
    "CC0-1.0",
    "CC-BY-4.0",
    "CC-BY-SA-4.0",
    "PDDL-1.0",
})
CODE_SUFFIXES = frozenset({".c", ".cpp", ".go", ".h", ".java", ".js", ".md", ".py", ".rb", ".ts"})
SKIP_DIRECTORIES = frozenset({
    ".git", ".pytest_cache", "__pycache__", "autonomous", "consolidated_run",
    "dna_shell_data", "node_data", "venv", ".venv",
})
DEFAULT_DOWNLOAD_DIR = Path("dna_shell_data") / "wiki_downloads"
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
MAX_CODE_FILE_BYTES = 1024 * 1024
MAX_CODE_RESULTS = 30
MAX_SNIPPET_CHARS = 320


def search_codebase(
    root: str | Path,
    query: str,
    *,
    limit: int = MAX_CODE_RESULTS,
) -> list[dict]:
    if not query.strip():
        raise ValueError("code search query cannot be empty")
    if not 1 <= limit <= MAX_CODE_RESULTS:
        raise ValueError(f"code search limit must be between 1 and {MAX_CODE_RESULTS}")
    root_path = Path(root).resolve(strict=True)
    if not root_path.is_dir():
        raise ValueError("code search root must be a directory")
    terms = [term.casefold() for term in query.split() if term]
    matches = []
    for current, directories, files in os.walk(root_path):
        directories[:] = sorted(
            directory for directory in directories
            if directory not in SKIP_DIRECTORIES and not directory.startswith(".")
        )
        for filename in sorted(files):
            path = Path(current) / filename
            if path.suffix.casefold() not in CODE_SUFFIXES:
                continue
            try:
                if path.stat().st_size > MAX_CODE_FILE_BYTES:
                    continue
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line_number, line in enumerate(content.splitlines(), start=1):
                folded = line.casefold()
                if all(term in folded for term in terms):
                    snippet = line.strip()
                    if len(snippet) > MAX_SNIPPET_CHARS:
                        snippet = snippet[:MAX_SNIPPET_CHARS - 3] + "..."
                    matches.append({
                        "path": path.relative_to(root_path).as_posix(),
                        "line": line_number,
                        "snippet": snippet,
                    })
                    if len(matches) >= limit:
                        return matches
    return matches


def _validate_download_url(url: str) -> tuple[str, str, str]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("downloads require an HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("download URL cannot contain credentials, query parameters, or fragments")
    if parsed.port not in (None, 443):
        raise ValueError("downloads are restricted to HTTPS port 443")
    host = parsed.hostname.casefold()
    if host not in ALLOWED_DOWNLOAD_HOSTS:
        raise ValueError(
            f"download host {host!r} is not allowlisted; permitted hosts: "
            f"{', '.join(sorted(ALLOWED_DOWNLOAD_HOSTS))}"
        )
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        }
    except OSError as error:
        raise RuntimeError(f"could not resolve approved download host {host}") from error
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("download host resolved to a non-public network address")
    request_target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    address = min(addresses, key=lambda item: (item.version, int(item)))
    return host, request_target, str(address)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str, *, timeout: float, context: ssl.SSLContext):
        super().__init__(host, 443, timeout=timeout, context=context)
        self.address = address

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self.address, self.port),
            timeout=self.timeout,
            source_address=self.source_address,
        )
        try:
            if self._context is None:
                raise RuntimeError("TLS context is required for public downloads")
            self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)
        except Exception:
            raw_socket.close()
            raise


def fetch_public_file(
    url: str,
    *,
    license_declaration: str,
    confirm_public_download: bool,
    destination_dir: str | Path = DEFAULT_DOWNLOAD_DIR,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    timeout: float = 30,
) -> dict:
    if confirm_public_download is not True:
        raise PermissionError("explicit confirmation is required before downloading public data")
    if license_declaration not in ALLOWED_LICENSE_DECLARATIONS:
        raise ValueError(
            f"license declaration must be one of {sorted(ALLOWED_LICENSE_DECLARATIONS)}"
        )
    if not 1 <= max_bytes <= MAX_DOWNLOAD_BYTES:
        raise ValueError(f"max_bytes must be between 1 and {MAX_DOWNLOAD_BYTES}")
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    host, request_target, address = _validate_download_url(url)
    destination_root = Path(destination_dir)
    destination_root.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    connection = _PinnedHTTPSConnection(
        host,
        address,
        timeout=timeout,
        context=ssl.create_default_context(cafile=certifi.where()),
    )
    try:
        connection.request(
            "GET",
            request_target,
            headers={"User-Agent": "OpenResearchWikiAgent/1.0"},
        )
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f"approved host returned HTTP {response.status}; file not downloaded")
        declared_length = response.getheader("Content-Length")
        declared_length_bytes = None
        if declared_length is not None:
            try:
                declared_length_bytes = int(declared_length)
            except ValueError as error:
                raise ValueError("download response has an invalid Content-Length") from error
            if declared_length_bytes < 0:
                raise ValueError("download response has an invalid Content-Length")
            if declared_length_bytes > max_bytes:
                raise ValueError(f"download exceeds the {max_bytes}-byte size limit")

        digest = hashlib.sha256()
        byte_count = 0
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".wiki-download-", suffix=".tmp",
            dir=destination_root, delete=False,
        ) as output:
            temporary_path = Path(output.name)
            while chunk := response.read(min(1024 * 1024, max_bytes - byte_count + 1)):
                byte_count += len(chunk)
                if byte_count > max_bytes:
                    raise ValueError(f"download exceeds the {max_bytes}-byte size limit")
                digest.update(chunk)
                output.write(chunk)
            if declared_length_bytes is not None and byte_count != declared_length_bytes:
                raise RuntimeError(
                    "download response ended before the declared Content-Length"
                )
            output.flush()
            os.fsync(output.fileno())
        content_hash = digest.hexdigest()
        data_path = destination_root / f"{content_hash}.data"
        manifest_path = destination_root / f"{content_hash}.json"
        if data_path.exists():
            if _hash_file(data_path) != content_hash:
                raise OSError(f"existing content-addressed file failed integrity check: {data_path}")
            temporary_path.unlink()
            temporary_path = None
        else:
            _install_without_replacing(temporary_path, data_path)
            temporary_path = None

        manifest = {
            "schema_version": 1,
            "classification": "public",
            "source_url": url,
            "source_host": host,
            "license_declaration": license_declaration,
            "rights_status": "user-declared; verify source-specific terms before reuse",
            "retrieved_at": time.time(),
            "content_bytes": byte_count,
            "sha256": content_hash,
            "stored_file": data_path.name,
        }
        _write_manifest(manifest_path, manifest)
        return {
            **manifest,
            "data_path": str(data_path),
            "manifest_path": str(manifest_path),
            "automatic_network_sharing": False,
        }
    finally:
        connection.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _install_without_replacing(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except FileExistsError:
        if _hash_file(destination) != destination.stem:
            raise OSError(f"existing content-addressed file failed integrity check: {destination}")
    finally:
        source.unlink(missing_ok=True)


def _write_manifest(path: Path, manifest: dict) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".wiki-manifest-", suffix=".tmp",
            dir=path.parent, delete=False,
        ) as output:
            temporary_path = Path(output.name)
            json.dump(manifest, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("sha256") != manifest["sha256"]:
                raise OSError(f"existing dataset manifest conflicts with downloaded content: {path}")
        temporary_path.unlink()
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


class WikiAgent:
    def __init__(
        self,
        *,
        repository_root: str | Path,
        catalog_path: str | Path = DEFAULT_CATALOG,
    ):
        self.repository_root = Path(repository_root).resolve()
        self.catalog = ResearchCatalog(catalog_path)

    def search(
        self,
        query: str,
        *,
        sources: tuple[str, ...] = (),
        confirm_public_query: bool = False,
        max_results: int = 10,
        code_limit: int = 10,
    ) -> dict:
        if not query.strip():
            raise ValueError("wiki search query cannot be empty")
        code_results = search_codebase(self.repository_root, query, limit=code_limit)
        records: list[dict] = []
        saved_count = 0
        if sources:
            if not confirm_public_query:
                raise PermissionError(
                    "public source search sends the query to providers; explicit confirmation is required"
                )
            records = search_public_sources(query, sources=sources, max_results=max_results)
            saved_count = self.catalog.add_records(records)
        catalog_results = self.catalog.retrieve(query, classification="public", limit=max_results)
        return {
            "query": query,
            "code_matches": code_results,
            "new_public_records": records,
            "catalog_matches": catalog_results,
            "new_records_saved": saved_count,
            "automatic_download": False,
            "automatic_provider_transfer": False,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local code/wiki search and permission-aware public research librarian."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    search = commands.add_parser("search", help="search local code and optionally public research sources")
    search.add_argument("query")
    search.add_argument("--root", type=Path, default=Path.cwd())
    search.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    search.add_argument("--sources", default="")
    search.add_argument("--max-results", type=int, default=10)
    search.add_argument("--code-limit", type=int, default=10)
    search.add_argument(
        "--confirm-public-query", action="store_true",
        help="confirm the query may be disclosed to the selected public source APIs",
    )

    fetch = commands.add_parser(
        "fetch", help="download a user-selected public file from an allowlisted HTTPS host"
    )
    fetch.add_argument("url")
    fetch.add_argument(
        "--license", required=True, choices=sorted(ALLOWED_LICENSE_DECLARATIONS),
        help="your declared file license; verify it at the source before downloading",
    )
    fetch.add_argument("--destination", type=Path, default=DEFAULT_DOWNLOAD_DIR)
    fetch.add_argument("--max-bytes", type=int, default=MAX_DOWNLOAD_BYTES)
    fetch.add_argument(
        "--confirm-public-download", action="store_true",
        help="confirm the URL and declared public license are approved for local download",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "search":
        sources = tuple(source.strip() for source in args.sources.split(",") if source.strip())
        result = WikiAgent(
            repository_root=args.root,
            catalog_path=args.catalog,
        ).search(
            args.query,
            sources=sources,
            confirm_public_query=args.confirm_public_query,
            max_results=args.max_results,
            code_limit=args.code_limit,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "fetch":
        if not args.confirm_public_download:
            parser.error(
                "download requires --confirm-public-download after reviewing source rights and URL"
            )
        result = fetch_public_file(
            args.url,
            license_declaration=args.license,
            confirm_public_download=True,
            destination_dir=args.destination,
            max_bytes=args.max_bytes,
        )
        print(json.dumps(result, indent=2))
        print("Downloaded as inert local data; no archive was unpacked or executed.")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
