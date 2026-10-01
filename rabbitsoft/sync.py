"""RabbitSoftware.inc across devices: one account, many devices, through the sync service.

What syncs, and how private it is:

  chat history       encrypted HERE (AES-256-GCM) with a key only this account's devices have; the sync
                     service and Cloudflare only ever store scrambled bytes
  research corpus    public records, shared as they are, so every device's corpus grows
  training answers   only answers someone chose to share, after the personal-information check, with no
                     account or device attached; they train the next model

Keys, all made on the device:
  account secret     32 random bytes. Shown once as a recovery phrase, the only way back if every device
                     is lost. It gives the history key and the account signing key (HKDF).
  device key         an Ed25519 key for this device; it signs every request, so a removed device is cut off.
  pairing code       SLOT-XXXX-XXXX for adding a device: the service holds the account secret sealed with
                     the code's second half (scrypt + AES-GCM) and never sees that half.

Everything lives in autonomous/rabbit/account/ (git never commits autonomous/).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import time
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

SYNC_URL = "https://rabbitsoftware-sync.rabbitsoftware-gateway.workers.dev"
B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
CORPUS_BATCH = 200


class SyncError(RuntimeError):
    pass


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _raw_public(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _id(public_key: bytes) -> str:
    return hashlib.sha256(public_key).hexdigest()[:32]


def _hkdf(secret: bytes, info: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info.encode()).derive(secret)


def account_keys(secret: bytes) -> tuple[bytes, Ed25519PrivateKey]:
    """(history encryption key, account signing key) from the account secret."""
    return _hkdf(secret, "rabbitsoftware history v1"), Ed25519PrivateKey.from_private_bytes(
        _hkdf(secret, "rabbitsoftware account v1"))


def phrase_for(secret: bytes) -> str:
    text = base64.b32encode(secret).decode().rstrip("=")
    return "-".join(text[i:i + 4] for i in range(0, len(text), 4))


def secret_from_phrase(phrase: str) -> bytes:
    text = re.sub(r"[^A-Z2-7]", "", phrase.upper())
    try:
        secret = base64.b32decode(text + "=" * (-len(text) % 8))
    except ValueError:
        secret = b""
    if len(secret) != 32:
        raise ValueError("that recovery phrase isn't complete; it's 13 groups of letters and numbers")
    return secret


def _seal_key(code_secret: str, slot: str) -> bytes:
    return Scrypt(salt=f"rabbitsoftware pairing {slot}".encode(), length=32, n=2 ** 15, r=8, p=1).derive(code_secret.encode())


def seal(secret: bytes, slot: str, code_secret: str) -> str:
    nonce = os.urandom(12)
    return _b64(nonce + AESGCM(_seal_key(code_secret, slot)).encrypt(nonce, secret, slot.encode()))


def unseal(sealed: str, slot: str, code_secret: str) -> bytes:
    raw = base64.b64decode(sealed)
    try:
        return AESGCM(_seal_key(code_secret, slot)).decrypt(raw[:12], raw[12:], slot.encode())
    except Exception:
        raise ValueError("that pairing code doesn't match; check it and try again") from None


def split_code(code: str) -> tuple[str, str]:
    text = re.sub(r"[^A-Z2-7]", "", code.upper())
    if len(text) != 12:
        raise ValueError("a pairing code is 12 letters and numbers, like ABCD-EFGH-JKLM")
    return text[:4], text[4:]


def _urllib_http(method: str, url: str, headers: dict, body: bytes) -> tuple[int, bytes]:
    from hosted_ai import SSL_CONTEXT

    request = urllib.request.Request(url, data=body if method != "GET" else None, method=method,
                                     headers={"User-Agent": "RabbitSoftware.inc", **headers})
    try:
        with urllib.request.urlopen(request, timeout=60, context=SSL_CONTEXT) as response:
            return response.status, response.read(8 * 1024 * 1024)
    except HTTPError as error:
        return error.code, error.read(64 * 1024)
    except (URLError, OSError, TimeoutError) as error:
        raise SyncError(f"the sync service couldn't be reached ({type(error).__name__})") from None


class SyncClient:
    def __init__(self, folder: Path, server: str = SYNC_URL,
                 http: Callable[[str, str, dict, bytes], tuple[int, bytes]] = _urllib_http):
        self.folder = folder
        self.server = server.rstrip("/")
        self.http = http

    # -- local state ------------------------------------------------------------------------------
    @property
    def _info_file(self) -> Path:
        return self.folder / "account.json"

    def info(self) -> dict | None:
        try:
            return json.loads(self._info_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def has_account(self) -> bool:
        return self.info() is not None

    def _save(self, secret: bytes, device: Ed25519PrivateKey, account_id: str, device_id: str, name: str) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "account.secret").write_text(_b64(secret), encoding="utf-8")
        (self.folder / "device.key").write_text(_b64(device.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())), encoding="utf-8")
        self._info_file.write_text(json.dumps({"account": account_id, "device": device_id, "name": name,
                                               "server": self.server}, indent=1), encoding="utf-8")

    def _secret(self) -> bytes:
        return base64.b64decode((self.folder / "account.secret").read_text(encoding="utf-8"))

    def _device_key(self) -> Ed25519PrivateKey:
        return Ed25519PrivateKey.from_private_bytes(base64.b64decode((self.folder / "device.key").read_text(encoding="utf-8")))

    def _state(self) -> dict:
        try:
            return json.loads((self.folder / "sync_state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"pushed": [], "pulled_batches": [], "last_sync": 0}

    def _save_state(self, state: dict) -> None:
        (self.folder / "sync_state.json").write_text(json.dumps(state), encoding="utf-8")

    # -- talking to the service -------------------------------------------------------------------
    def _send(self, method: str, path: str, body: bytes = b"", content_type: str = "", signed: bool = True,
              extra: dict | None = None) -> bytes:
        headers = dict(extra or {})
        if content_type:
            headers["Content-Type"] = content_type
        if signed:
            info = self.info()
            if info is None:
                raise SyncError("there's no account on this device yet")
            now = str(int(time.time() * 1000))
            message = f"{method}\n{path}\n{now}\n{hashlib.sha256(body).hexdigest()}".encode()
            headers.update({"X-Account": info["account"], "X-Device": info["device"], "X-Time": now,
                            "X-Signature": _b64(self._device_key().sign(message))})
        status, raw = self.http(method, self.server + path, headers, body)
        if status >= 400:
            try:
                reason = json.loads(raw).get("error", "")
            except (ValueError, AttributeError):
                reason = ""
            raise SyncError(reason or f"the sync service returned HTTP {status}")
        return raw

    def _json(self, method: str, path: str, data=None, **kwargs):
        body = json.dumps(data).encode() if data is not None else b""
        raw = self._send(method, path, body, "application/json" if data is not None else "", **kwargs)
        return json.loads(raw) if raw else {}

    def _register(self, secret: bytes, name: str, signup_key: str = "") -> None:
        _, account_key = account_keys(secret)
        device = Ed25519PrivateKey.generate()
        account_pub, device_pub = _raw_public(account_key), _raw_public(device)
        account_id, now = _id(account_pub), int(time.time() * 1000)
        message = f"register\n{account_id}\n{_b64(device_pub)}\n{name}\n{now}".encode()
        result = self._json("POST", "/v1/devices", {
            "account_key": _b64(account_pub), "device_key": _b64(device_pub), "name": name, "time": now,
            "signature": _b64(account_key.sign(message))}, signed=False,
            extra={"X-Signup-Key": signup_key} if signup_key else None)
        self._save(secret, device, result["account"], result["device"], name)

    # -- accounts and devices -----------------------------------------------------------------------
    def create_account(self, device_name: str, signup_key: str) -> str:
        """Creates the account with this device as its first; returns the recovery phrase (shown once)."""
        if self.has_account():
            raise SyncError("this device already belongs to an account")
        secret = secrets.token_bytes(32)
        self._register(secret, device_name, signup_key)
        return phrase_for(secret)

    def join_with_phrase(self, phrase: str, device_name: str) -> None:
        self._register(secret_from_phrase(phrase), device_name)

    def make_pairing_code(self) -> str:
        """A code for adding another device, valid for 10 minutes."""
        slot = "".join(secrets.choice(B32) for _ in range(4))
        code_secret = "".join(secrets.choice(B32) for _ in range(8))
        self._json("POST", "/v1/pairing", {"slot": slot, "sealed": seal(self._secret(), slot, code_secret)})
        return f"{slot}-{code_secret[:4]}-{code_secret[4:]}"

    def join_with_code(self, code: str, device_name: str) -> None:
        slot, code_secret = split_code(code)
        sealed = self._json("GET", f"/v1/pairing/{slot}", signed=False)["sealed"]
        self._register(unseal(sealed, slot, code_secret), device_name)

    def devices(self) -> list[dict]:
        return self._json("GET", "/v1/devices")["devices"]

    def remove_device(self, device_id: str) -> None:
        self._json("DELETE", f"/v1/devices/{device_id}")

    # -- chat history (encrypted here) --------------------------------------------------------------
    def _history_key(self) -> bytes:
        return account_keys(self._secret())[0]

    def push_history(self, exchanges: list[dict]) -> None:
        info = self.info()
        plain = json.dumps({"device": info["name"], "exchanges": exchanges}).encode()
        nonce = os.urandom(12)
        sealed = nonce + AESGCM(self._history_key()).encrypt(nonce, plain, info["account"].encode())
        self._send("PUT", f"/v1/history/{info['device']}.bin", sealed, "application/octet-stream")

    def pull_history(self) -> list[dict]:
        """Every device's exchanges, decrypted here, oldest first."""
        account = self.info()["account"].encode()
        exchanges = []
        for item in self._json("GET", "/v1/history")["history"]:
            raw = self._send("GET", f"/v1/history/{item['name']}")
            try:
                data = json.loads(AESGCM(self._history_key()).decrypt(raw[:12], raw[12:], account))
            except Exception:
                continue                     # not ours or damaged: skip, never guess
            exchanges += [{**e, "device": data.get("device", "")} for e in data.get("exchanges", [])]
        return sorted(exchanges, key=lambda e: e.get("time", 0))

    # -- the shared research corpus (public) ---------------------------------------------------------
    @staticmethod
    def _record_key(r: dict) -> str:
        return f"{r['source']}\0{r['external_id']}"

    def push_corpus(self, catalog) -> int:
        state = self._state()
        pushed = set(state["pushed"])
        fresh = [r for r in catalog.all_records() if self._record_key(r) not in pushed
                 and str(r.get("source_url", "")).startswith("https://")]
        for i in range(0, len(fresh), CORPUS_BATCH):
            chunk = fresh[i:i + CORPUS_BATCH]
            self._json("POST", "/v1/corpus", {"records": [{k: str(r.get(k) or "") for k in (
                "source", "external_id", "title", "abstract", "source_url", "published_at")} for r in chunk]})
            pushed.update(self._record_key(r) for r in chunk)
            state["pushed"] = sorted(pushed)
            self._save_state(state)
        return len(fresh)

    def pull_corpus(self, catalog) -> int:
        from research_catalog import SOURCE_TERMS

        state = self._state()
        seen, added = set(state["pulled_batches"]), 0
        pushed = set(state["pushed"])
        for name in self._json("GET", "/v1/corpus/batches", signed=False)["batches"]:
            if name in seen:
                continue
            records = self._json("GET", f"/v1/corpus/batches/{name}", signed=False).get("records", [])
            keep = [{**r, "classification": "public", "rights_status": "unknown; review source and record terms",
                     "terms_url": SOURCE_TERMS.get(r.get("source"), "")} for r in records]
            try:
                added += catalog.add_records(keep) if keep else 0
            except ValueError:
                pass                         # a malformed batch is skipped, not half-applied
            pushed.update(self._record_key(r) for r in records)
            seen.add(name)
            state.update(pulled_batches=sorted(seen), pushed=sorted(pushed))
            self._save_state(state)
        return added

    # -- training answers --------------------------------------------------------------------------
    def share_training(self, question: str, answer: str, sources: list[str], rating: int = 0,
                       model: str = "") -> None:
        self._json("POST", "/v1/training", {"question": question, "answer": answer, "sources": sources[:10],
                                            "rating": rating, "model": model})

    # -- the shared corpus in SQL (public) -------------------------------------------------------------
    def corpus_search(self, query: str, limit: int = 20) -> list[dict]:
        from urllib.parse import urlencode

        return self._json("GET", "/v1/corpus/search?" + urlencode({"q": query, "limit": limit}), signed=False)["records"]

    def corpus_stats(self) -> dict:
        return self._json("GET", "/v1/corpus/stats", signed=False)

    # -- the owner: review and export shared answers (the service allows only ADMIN_ACCOUNT) ----------
    def admin_training(self, status: str = "pending", limit: int = 100) -> list[dict]:
        return self._json("GET", f"/v1/admin/training?status={status}&limit={limit}")["items"]

    def review_training(self, ids: list[str], status: str) -> int:
        return self._json("POST", "/v1/admin/training/review", {"ids": ids, "status": status})["updated"]

    def training_to_export(self, limit: int = 1000) -> list[dict]:
        return self._json("GET", f"/v1/admin/training/export?limit={limit}")["items"]

    def mark_exported(self, file: str, sha256: str, hf_commit: str, ids: list[str]) -> int:
        return self._json("POST", "/v1/admin/training/exported",
                          {"file": file, "sha256": sha256, "hf_commit": hf_commit, "ids": ids})["marked"]

    def admin_stats(self) -> dict:
        return self._json("GET", "/v1/admin/stats")

    def sync(self, catalog, history: list[dict]) -> dict:
        pushed = self.push_corpus(catalog)
        added = self.pull_corpus(catalog)
        self.push_history(history)
        state = self._state()
        state["last_sync"] = time.time()
        self._save_state(state)
        return {"pushed": pushed, "added": added, "history": len(history)}
