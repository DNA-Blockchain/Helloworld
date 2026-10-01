import hashlib
import json

import pytest
from cryptography.exceptions import InvalidTag

from encrypted_data_vault import EncryptedDataVault


def test_vault_encrypts_restores_and_lists_an_arbitrary_data_file(tmp_path):
    source = tmp_path / "patient-file-name.fasta"
    payload = b">synthetic-sequence\nACGTNNRY\n"
    source.write_bytes(payload)
    vault_dir = tmp_path / "vault"
    vault = EncryptedDataVault(vault_dir)

    stored = vault.store_file(
        source,
        passphrase="long-test-passphrase",
        classification="restricted",
        source_label="authorized-local-source",
    )

    vault_path = vault_dir / f"{stored['vault_id']}.dvault"
    encrypted = vault_path.read_bytes()
    assert payload not in encrypted
    assert b"patient-file-name.fasta" not in encrypted
    assert hashlib.sha256(payload).hexdigest().encode("ascii") not in encrypted
    assert vault.list_ids() == [stored["vault_id"]]

    metadata = vault.inspect(stored["vault_id"], passphrase="long-test-passphrase")
    destination = tmp_path / "restored.fasta"
    restored = vault.restore_file(
        stored["vault_id"], destination, passphrase="long-test-passphrase"
    )
    assert metadata["classification"] == "restricted"
    assert metadata["content_sha256"] == hashlib.sha256(payload).hexdigest()
    assert restored["content_sha256"] == metadata["content_sha256"]
    assert destination.read_bytes() == payload
    with pytest.raises(FileExistsError, match="overwrite"):
        vault.restore_file(
            stored["vault_id"], destination, passphrase="long-test-passphrase"
        )


def test_vault_rejects_weak_passphrases_and_invalid_classes(tmp_path):
    source = tmp_path / "input.bin"
    source.write_bytes(b"data")
    vault = EncryptedDataVault(tmp_path / "vault")

    with pytest.raises(ValueError, match="12 characters"):
        vault.store_file(source, passphrase="too-short")
    with pytest.raises(ValueError, match="classification"):
        vault.store_file(
            source, passphrase="long-test-passphrase", classification="unknown"
        )


def test_vault_wrong_passphrase_does_not_restore_plaintext(tmp_path):
    source = tmp_path / "input.bin"
    source.write_bytes(b"private bytes")
    vault = EncryptedDataVault(tmp_path / "vault")
    stored = vault.store_file(source, passphrase="long-test-passphrase")
    destination = tmp_path / "restored.bin"

    with pytest.raises(InvalidTag):
        vault.restore_file(
            stored["vault_id"], destination, passphrase="different-passphrase"
        )
    assert not destination.exists()
    assert not list(tmp_path.glob(".vault-restore-*.tmp"))


def test_vault_detects_ciphertext_tampering_and_truncation(tmp_path):
    source = tmp_path / "input.bin"
    source.write_bytes(b"private content for integrity test")
    vault = EncryptedDataVault(tmp_path / "vault")
    stored = vault.store_file(source, passphrase="long-test-passphrase")
    path = tmp_path / "vault" / f"{stored['vault_id']}.dvault"
    original = path.read_bytes()

    tampered = bytearray(original)
    tampered[-20] ^= 1
    path.write_bytes(tampered)
    with pytest.raises(InvalidTag):
        vault.inspect(stored["vault_id"], passphrase="long-test-passphrase")

    path.write_bytes(original[:-3])
    with pytest.raises(ValueError, match="truncated"):
        vault.inspect(stored["vault_id"], passphrase="long-test-passphrase")


def test_vault_authenticates_metadata_and_rejects_oversized_frame(tmp_path):
    source = tmp_path / "input.bin"
    source.write_bytes(b"ok")
    vault = EncryptedDataVault(tmp_path / "vault")
    stored = vault.store_file(source, passphrase="long-test-passphrase")
    path = tmp_path / "vault" / f"{stored['vault_id']}.dvault"
    content = bytearray(path.read_bytes())
    content[32:36] = (2**32 - 1).to_bytes(4, "big")
    path.write_bytes(content)

    with pytest.raises(ValueError, match="frame length"):
        vault.inspect(stored["vault_id"], passphrase="long-test-passphrase")


def test_vault_store_cli_prompts_and_keeps_sensitive_content_encrypted(
    tmp_path, monkeypatch, capsys
):
    import dna_shell

    source = tmp_path / "sensitive.json"
    source.write_text(json.dumps({"subject": "synthetic-only"}), encoding="utf-8")
    passphrases = iter(["long-test-passphrase", "long-test-passphrase"])
    monkeypatch.setattr(dna_shell.getpass, "getpass", lambda prompt: next(passphrases))
    vault_dir = tmp_path / "vault"

    assert dna_shell.main([
        "data-vault-store", str(source),
        "--classification", "private",
        "--vault-dir", str(vault_dir),
    ]) == 0

    result = json.loads(capsys.readouterr().out.split("Encrypted locally;")[0])
    assert result["classification"] == "private"
    encrypted = (vault_dir / f"{result['vault_id']}.dvault").read_bytes()
    assert b"synthetic-only" not in encrypted


def test_public_hash_command_requires_confirmation_and_public_classification(
    tmp_path, monkeypatch
):
    import dna_shell

    source = tmp_path / "data.bin"
    source.write_bytes(b"only synthetic test bytes")
    vault = EncryptedDataVault(tmp_path / "vault")
    stored = vault.store_file(
        source,
        passphrase="long-test-passphrase",
        classification="restricted",
    )
    passphrases = iter(["long-test-passphrase"])
    monkeypatch.setattr(dna_shell.getpass, "getpass", lambda prompt: next(passphrases))

    with pytest.raises(SystemExit) as confirmation_error:
        dna_shell.main([
            "data-vault-publish-hash", stored["vault_id"],
            "--vault-dir", str(tmp_path / "vault"),
            "--outbox", str(tmp_path / "outbox"),
        ])
    assert confirmation_error.value.code == 2
    assert not (tmp_path / "outbox").exists()

    with pytest.raises(SystemExit) as classification_error:
        dna_shell.main([
            "data-vault-publish-hash", stored["vault_id"],
            "--confirm-public-hash-publication",
            "--vault-dir", str(tmp_path / "vault"),
            "--outbox", str(tmp_path / "outbox"),
        ])
    assert classification_error.value.code == 2
    assert not (tmp_path / "outbox").exists()
