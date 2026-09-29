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

import crypto_layer as ck


def test_ed25519_sign_verify_roundtrip():
    priv, pub = ck.generate_signing_keypair()
    msg = b"real message"
    sig = ck.sign(priv, msg)
    assert ck.verify(pub, msg, sig) is True


def test_ed25519_rejects_tampered_message():
    priv, pub = ck.generate_signing_keypair()
    sig = ck.sign(priv, b"original")
    assert ck.verify(pub, b"tampered", sig) is False


def test_ed25519_rejects_wrong_key():
    priv_a, pub_a = ck.generate_signing_keypair()
    priv_b, pub_b = ck.generate_signing_keypair()
    sig = ck.sign(priv_a, b"message")
    assert ck.verify(pub_b, b"message", sig) is False


def test_x25519_both_sides_derive_same_key():
    priv_a, pub_a = ck.generate_exchange_keypair()
    priv_b, pub_b = ck.generate_exchange_keypair()
    key_a = ck.derive_shared_key(priv_a, pub_b)
    key_b = ck.derive_shared_key(priv_b, pub_a)
    assert key_a == key_b
    assert len(key_a) == 32


def test_hex_roundtrip_produces_same_key():
    priv_a, pub_a = ck.generate_exchange_keypair()
    priv_b, pub_b = ck.generate_exchange_keypair()
    hex_pub_a = ck.exchange_pub_to_hex(pub_a)
    restored = ck.exchange_pub_from_hex(hex_pub_a)
    assert ck.derive_shared_key(priv_b, restored) == ck.derive_shared_key(priv_b, pub_a)


def test_aead_encrypt_decrypt_roundtrip():
    key = b"0" * 32
    plaintext = b"a real secret"
    payload = ck.aead_encrypt(key, plaintext, aad=b"context")
    assert ck.aead_decrypt(key, payload, aad=b"context") == plaintext


def test_aead_detects_tampered_ciphertext():
    import pytest
    from cryptography.exceptions import InvalidTag

    key = b"0" * 32
    payload = bytearray(ck.aead_encrypt(key, b"secret", aad=b"ctx"))
    payload[-1] ^= 0xFF
    with pytest.raises(InvalidTag):
        ck.aead_decrypt(key, bytes(payload), aad=b"ctx")


def test_aead_rejects_wrong_key():
    import pytest
    from cryptography.exceptions import InvalidTag

    key_a, key_b = b"0" * 32, b"1" * 32
    payload = ck.aead_encrypt(key_a, b"secret", aad=b"ctx")
    with pytest.raises(InvalidTag):
        ck.aead_decrypt(key_b, payload, aad=b"ctx")


# -- additive: raw-bytes keypair + context-scoped derivation ----------------

def test_generate_exchange_keypair_raw_returns_32_public_bytes():
    priv, pub_bytes = ck.generate_exchange_keypair_raw()
    assert isinstance(pub_bytes, bytes) and len(pub_bytes) == 32


def test_derive_accepts_raw_bytes_equivalently_to_object():
    # default context must match the old fixed behavior exactly, whether the
    # peer key is passed as an object or as raw bytes (interop unchanged)
    a_priv, a_pub = ck.generate_exchange_keypair()
    b_priv, b_pub_bytes = ck.generate_exchange_keypair_raw()
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    a_pub_bytes = a_pub.public_bytes(Encoding.Raw, PublicFormat.Raw)

    # object-arg path and bytes-arg path on the same peer key agree
    key_obj = ck.derive_shared_key(b_priv, a_pub)
    key_bytes = ck.derive_shared_key(b_priv, a_pub_bytes)
    assert key_obj == key_bytes

    # both sides still derive the same key with the default context
    a_side = ck.derive_shared_key(a_priv, b_pub_bytes)
    assert a_side == key_obj


def test_context_scopes_the_key():
    a_priv, a_pub = ck.generate_exchange_keypair()
    b_priv, b_pub = ck.generate_exchange_keypair()
    ctx1, ctx2 = b"session/purpose-1", b"session/purpose-2"

    # same context on both sides -> same key
    assert ck.derive_shared_key(a_priv, b_pub, ctx1) == ck.derive_shared_key(b_priv, a_pub, ctx1)
    # different context -> different key from the same ECDH secret
    assert ck.derive_shared_key(a_priv, b_pub, ctx1) != ck.derive_shared_key(a_priv, b_pub, ctx2)


def test_signing_key_persists_across_loads(tmp_path):
    path = str(tmp_path / "keys" / "node.ed25519.pem")
    _, pub1 = ck.load_or_create_signing_keypair(path)
    priv2, pub2 = ck.load_or_create_signing_keypair(path)
    assert ck.signing_pub_to_hex(pub1) == ck.signing_pub_to_hex(pub2)
    assert ck.verify(pub1, b"msg", ck.sign(priv2, b"msg"))


def test_encrypted_signing_key_needs_the_passphrase(tmp_path):
    import pytest
    path = str(tmp_path / "node.ed25519.pem")
    _, pub = ck.load_or_create_signing_keypair(path, passphrase=b"correct horse")
    assert b"ENCRYPTED" in open(path, "rb").read()
    _, pub_again = ck.load_or_create_signing_keypair(path, passphrase=b"correct horse")
    assert ck.signing_pub_to_hex(pub) == ck.signing_pub_to_hex(pub_again)
    with pytest.raises(ValueError):
        ck.load_or_create_signing_keypair(path, passphrase=b"wrong")
    with pytest.raises(ValueError):
        ck.load_or_create_signing_keypair(path)


def test_corrupt_signing_key_file_is_not_overwritten(tmp_path):
    import pytest
    path = tmp_path / "node.ed25519.pem"
    path.write_bytes(b"not a key")
    with pytest.raises(ValueError):
        ck.load_or_create_signing_keypair(str(path))
    assert path.read_bytes() == b"not a key"
