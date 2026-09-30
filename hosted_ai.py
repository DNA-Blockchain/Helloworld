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

"""Your model on a server outside this PC, reached like any other LLM.

The server speaks the OpenAI-compatible chat API (POST <url>/v1/chat/completions) that Hugging Face
Inference Endpoints, llama.cpp's server, vLLM and the RabbitSoftware gateway all serve, so the same
client works whichever of them hosts the model.

Where the server is comes from the RABBIT_MODEL_URL environment variable or, more usually, from
`rabbit model-server <url>` (saved in autonomous/rabbit/settings.json). An access key, if the server
needs one, only ever comes from RABBIT_MODEL_KEY: it's never written to a file by this project.

RabbitSoftware.inc asks before each question is sent here (see rabbitsoft/assistant.py); this module
only does the sending.
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.error import HTTPError, URLError

import certifi

DEFAULT_MODEL = "rabbitsoftware"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
MAX_REPLY_BYTES = 1024 * 1024


def check_url(url: str) -> str:
    """The server's base URL, cleaned up. Anything leaving this PC must use https."""
    url = url.strip().rstrip("/")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ValueError("the model server must be a web address like https://example.org")
    if parts.scheme == "http" and parts.hostname not in LOCAL_HOSTS:
        raise ValueError("a model server outside this PC must use https, so questions are encrypted on the way")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise ValueError("the model server address can't include a query, fragment or login")
    return url


class HostedAI:
    def __init__(self, url: str, key: str = "", model: str = DEFAULT_MODEL, timeout: float = 180):
        self.url = check_url(url)
        self.key = key
        self.model = model
        self.timeout = timeout

    @property
    def host(self) -> str:
        return urllib.parse.urlsplit(self.url).hostname or self.url

    def _endpoint(self) -> str:
        return f"{self.url}/chat/completions" if self.url.endswith("/v1") else f"{self.url}/v1/chat/completions"

    def generate(self, prompt: str, num_predict: int = 220) -> str:
        body = json.dumps({"model": self.model, "messages": [{"role": "user", "content": prompt}],
                           "max_tokens": num_predict, "temperature": 0.2, "stream": False}).encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "User-Agent": "RabbitSoftware.inc"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        request = urllib.request.Request(self._endpoint(), data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=SSL_CONTEXT) as response:
                data = json.loads(response.read(MAX_REPLY_BYTES))
        except HTTPError as error:
            hint = {401: " (it needs an access key: set RABBIT_MODEL_KEY)", 429: " (too many questions; wait a bit)",
                    503: " (it's starting up; try again in a minute)"}.get(error.code, "")
            raise RuntimeError(f"the model server {self.host} returned HTTP {error.code}{hint}") from None
        except (URLError, OSError, TimeoutError) as error:
            raise RuntimeError(f"the model server {self.host} couldn't be reached ({type(error).__name__})") from None
        except ValueError:
            raise RuntimeError(f"the model server {self.host} sent a reply that isn't JSON") from None
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError(f"the model server {self.host} sent a reply without an answer") from None
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError(f"the model server {self.host} returned no text")
        return text.strip()


def configured_url(settings_file: Path) -> str:
    """The model server to use, or "" for none: the environment variable wins over the saved setting."""
    url = os.environ.get("RABBIT_MODEL_URL", "").strip()
    if not url:
        try:
            url = str(json.loads(settings_file.read_text(encoding="utf-8")).get("model_server", "")).strip()
        except (OSError, ValueError, AttributeError):
            url = ""
    return url


def from_settings(settings_file: Path) -> HostedAI | None:
    url = configured_url(settings_file)
    if not url:
        return None
    try:
        return HostedAI(url, key=os.environ.get("RABBIT_MODEL_KEY", ""),
                        model=os.environ.get("RABBIT_MODEL_NAME", DEFAULT_MODEL))
    except ValueError:
        return None       # a bad saved address means no server, not a crash; `rabbit model-server` says why


def save_url(settings_file: Path, url: str | None) -> str:
    """Saves the model server (checked first), or removes it when url is None. Returns what was saved."""
    try:
        settings = json.loads(settings_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    if url is None:
        settings.pop("model_server", None)
        saved = ""
    else:
        saved = settings["model_server"] = check_url(url)
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(settings, indent=1), encoding="utf-8")
    return saved
