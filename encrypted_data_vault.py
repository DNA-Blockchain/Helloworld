"""Passphrase-encrypted local storage for research and biological data files."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import struct
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

VAULT_MAGIC = b"DNAVLT01"
VAULT_SUFFIX = ".dvault"
VAULT_CHUNK_SIZE = 1024 * 1024
_SALT_BYTES = 16
_NONCE_PREFIX_BYTES = 8
_NONCE_COUNTER_MAX = (1 << 32) - 1
_TAG_BYTES = 16
_MAX_FRAME_BYTES = VAULT_CHUNK_SIZE + 5 + _TAG_BYTES
_VAULT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_CLASSIFICATIONS = frozenset({"public", "restricted", "private"})


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    if not isinstance(passphrase, str) or len(passphrase) < 12:
        raise ValueError("vault passphrase must be at least 12 characters")
    return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(
        passphrase.encode("utf-8")
    )


def _frame_aad(vault_id: str, counter: int) -> bytes:
    return VAULT_MAGIC + bytes.fromhex(vault_id) + counter.to_bytes(4, "big")


def _write_frame(stream, cipher: AESGCM, nonce_prefix: bytes, vault_id: str,
                 counter: int, plaintext: bytes) -> None:
    if counter > _NONCE_COUNTER_MAX:
        raise ValueError("vault file exceeds the supported number of encryption chunks")
    nonce = nonce_prefix + counter.to_bytes(4, "big")
    encrypted = cipher.encrypt(nonce, plaintext, _frame_aad(vault_id, counter))
    stream.write(struct.pack(">I", len(encrypted)))
    stream.write(encrypted)


def _read_exact(stream, length: int) -> bytes:
    data = stream.read(length)
    if len(data) != length:
        raise ValueError("encrypted vault file is truncated")
    return data


def _install_without_replacing(source: Path, destination: Path) -> None:
    os.link(source, destination)
    source.unlink()


class EncryptedDataVault:
    def __init__(
        self, directory: str | Path = Path("dna_shell_data") / "encrypted_vault"
    ):
        self.directory = Path(directory)

    def _vault_path(self, vault_id: str) -> Path:
        if not isinstance(vault_id, str) or not _VAULT_ID_RE.fullmatch(vault_id):
            raise ValueError("vault ID must be a 32-character hexadecimal ID")
        return self.directory / f"{vault_id}{VAULT_SUFFIX}"

    def store_file(
        self,
        source: str | Path,
        *,
        passphrase: str,
        classification: str = "private",
        source_label: str = "local",
    ) -> dict:
        if classification not in _CLASSIFICATIONS:
            raise ValueError(f"classification must be one of {sorted(_CLASSIFICATIONS)}")
        if not isinstance(source_label, str) or not source_label.strip():
            raise ValueError("source label cannot be empty")
        source_path = Path(source)
        digest = hashlib.sha256()
        data_size = 0
        with source_path.open("rb") as stream:
            while chunk := stream.read(VAULT_CHUNK_SIZE):
                digest.update(chunk)
                data_size += len(chunk)

        vault_id = secrets.token_hex(16)
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self._vault_path(vault_id)
        salt = os.urandom(_SALT_BYTES)
        nonce_prefix = os.urandom(_NONCE_PREFIX_BYTES)
        cipher = AESGCM(_derive_key(passphrase, salt))
        metadata = {
            "schema_version": 1,
            "vault_id": vault_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "classification": classification,
            "source_label": source_label.strip(),
            "original_name": source_path.name,
            "content_sha256": digest.hexdigest(),
            "content_bytes": data_size,
        }
        metadata_frame = b"\x00META" + json.dumps(
            metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if len(metadata_frame) > VAULT_CHUNK_SIZE:
            raise ValueError("vault metadata is too large")

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{vault_id}-", suffix=".tmp",
                dir=self.directory, delete=False,
            ) as output:
                temporary_path = Path(output.name)
                output.write(VAULT_MAGIC + salt + nonce_prefix)
                _write_frame(output, cipher, nonce_prefix, vault_id, 0, metadata_frame)
                counter = 1
                copied_digest = hashlib.sha256()
                copied_size = 0
                with source_path.open("rb") as source_stream:
                    while chunk := source_stream.read(VAULT_CHUNK_SIZE):
                        copied_digest.update(chunk)
                        copied_size += len(chunk)
                        _write_frame(
                            output, cipher, nonce_prefix, vault_id, counter, b"\x01" + chunk
                        )
                        counter += 1
                if copied_size != data_size or copied_digest.hexdigest() != digest.hexdigest():
                    raise OSError("source changed during vault encryption; no vault file was stored")
                _write_frame(output, cipher, nonce_prefix, vault_id, counter, b"\x02END")
                output.flush()
                os.fsync(output.fileno())
            _install_without_replacing(temporary_path, destination)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        return {
            "vault_id": vault_id,
            "classification": classification,
            "content_bytes": data_size,
            "content_sha256": digest.hexdigest(),
            "storage": "local-encrypted",
        }

    def _decrypt(
        self,
        vault_id: str,
        *,
        passphrase: str,
        output_path: Path | None,
    ) -> dict:
        path = self._vault_path(vault_id)
        destination_temp: Path | None = None
        output_stream = None
        actual_digest = hashlib.sha256()
        actual_size = 0
        try:
            if output_path is not None:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                if output_path.exists():
                    raise FileExistsError(f"refusing to overwrite existing output: {output_path}")
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=".vault-restore-",
                    suffix=".tmp",
                    dir=output_path.parent,
                )
                destination_temp = Path(temporary_name)
                output_stream = os.fdopen(descriptor, "wb")

            with path.open("rb") as source:
                header = _read_exact(source, len(VAULT_MAGIC) + _SALT_BYTES + _NONCE_PREFIX_BYTES)
                if header[:len(VAULT_MAGIC)] != VAULT_MAGIC:
                    raise ValueError("unsupported encrypted vault format")
                salt_start = len(VAULT_MAGIC)
                salt = header[salt_start:salt_start + _SALT_BYTES]
                nonce_prefix = header[salt_start + _SALT_BYTES:]
                cipher = AESGCM(_derive_key(passphrase, salt))
                counter = 0
                metadata = None
                saw_end = False
                while True:
                    frame_size = struct.unpack(">I", _read_exact(source, 4))[0]
                    if not _TAG_BYTES <= frame_size <= _MAX_FRAME_BYTES:
                        raise ValueError("encrypted vault contains an invalid frame length")
                    encrypted = _read_exact(source, frame_size)
                    plaintext = cipher.decrypt(
                        nonce_prefix + counter.to_bytes(4, "big"),
                        encrypted,
                        _frame_aad(vault_id, counter),
                    )
                    if counter == 0:
                        if not plaintext.startswith(b"\x00META"):
                            raise ValueError("encrypted vault metadata frame is invalid")
                        metadata = json.loads(plaintext[5:])
                        self._validate_metadata(vault_id, metadata)
                    elif plaintext == b"\x02END":
                        saw_end = True
                        if source.read(1):
                            raise ValueError("encrypted vault contains data after its end marker")
                        break
                    elif plaintext.startswith(b"\x01") and metadata is not None:
                        chunk = plaintext[1:]
                        actual_digest.update(chunk)
                        actual_size += len(chunk)
                        if output_stream is not None:
                            output_stream.write(chunk)
                    else:
                        raise ValueError("encrypted vault contains an invalid data frame")
                    counter += 1
                    if counter > _NONCE_COUNTER_MAX:
                        raise ValueError("encrypted vault exceeds its supported frame count")

            if not saw_end or metadata is None:
                raise ValueError("encrypted vault is missing required content")
            if (
                actual_size != metadata["content_bytes"]
                or actual_digest.hexdigest() != metadata["content_sha256"]
            ):
                raise ValueError("encrypted vault content failed its integrity check")
            if output_stream is not None:
                output_stream.flush()
                os.fsync(output_stream.fileno())
                output_stream.close()
                output_stream = None
                _install_without_replacing(destination_temp, output_path)
                destination_temp = None
            return metadata
        finally:
            if output_stream is not None:
                output_stream.close()
            if destination_temp is not None:
                destination_temp.unlink(missing_ok=True)

    @staticmethod
    def _validate_metadata(vault_id: str, metadata: object) -> None:
        required = {
            "schema_version", "vault_id", "created_at", "classification",
            "source_label", "original_name", "content_sha256", "content_bytes",
        }
        if not isinstance(metadata, dict) or set(metadata) != required:
            raise ValueError("encrypted vault metadata has an invalid shape")
        if metadata["schema_version"] != 1 or metadata["vault_id"] != vault_id:
            raise ValueError("encrypted vault metadata does not match its file")
        if metadata["classification"] not in _CLASSIFICATIONS:
            raise ValueError("encrypted vault metadata has an invalid classification")
        if (
            not isinstance(metadata["content_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", metadata["content_sha256"])
        ):
            raise ValueError("encrypted vault metadata has an invalid content hash")
        if type(metadata["content_bytes"]) is not int or metadata["content_bytes"] < 0:
            raise ValueError("encrypted vault metadata has an invalid content size")
        if not isinstance(metadata["original_name"], str) or not metadata["original_name"]:
            raise ValueError("encrypted vault metadata has an invalid original name")
        if not isinstance(metadata["source_label"], str) or not metadata["source_label"]:
            raise ValueError("encrypted vault metadata has an invalid source label")

    def restore_file(
        self,
        vault_id: str,
        destination: str | Path,
        *,
        passphrase: str,
    ) -> dict:
        metadata = self._decrypt(
            vault_id, passphrase=passphrase, output_path=Path(destination)
        )
        return {
            "vault_id": vault_id,
            "destination": str(destination),
            "classification": metadata["classification"],
            "content_bytes": metadata["content_bytes"],
            "content_sha256": metadata["content_sha256"],
            "storage": "restored-local",
        }

    def inspect(self, vault_id: str, *, passphrase: str) -> dict:
        metadata = self._decrypt(vault_id, passphrase=passphrase, output_path=None)
        return {
            "vault_id": vault_id,
            "created_at": metadata["created_at"],
            "classification": metadata["classification"],
            "source_label": metadata["source_label"],
            "original_name": metadata["original_name"],
            "content_sha256": metadata["content_sha256"],
            "content_bytes": metadata["content_bytes"],
            "storage": "local-encrypted",
        }

    def list_ids(self) -> list[str]:
        if not self.directory.exists():
            return []
        return sorted(
            path.stem for path in self.directory.glob(f"*{VAULT_SUFFIX}")
            if _VAULT_ID_RE.fullmatch(path.stem)
        )
