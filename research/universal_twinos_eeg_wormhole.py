#!/usr/bin/env python3
"""
Universal TwinOS + EEG/Hormone Wormhole
=======================================

A research/prototype architecture for:

    Historical personal data
        -> Digital Twin
        -> EEG / physiology context
        -> EEG-Hormone Wormhole
        -> historical event matching
        -> temporal transformer
        -> scene reconstruction
        -> image/video generation
        -> human feedback
        -> iterative refinement

Also provides an OS/network-neutral agent protocol allowing:

    Digital Twin agents
    Coding agents
    Terminal agents
    Development agents
    GPU agents
    MicroPython agents
    Generic agents

to communicate using the same task/event representation.

IMPORTANT:
This is a research architecture.

EEG and physiological signals are treated as probabilistic
state/context information. The system does NOT assume that EEG
directly reveals an exact private thought or memory.

The historical event matcher provides candidate matches and
confidence values. Human guidance/feedback remains part of the
reconstruction loop.

Sensitive raw EEG, physiology, memories, media, and personal
data should remain off-chain. Provenance records contain hashes,
metadata, model versions, auto-approval records, and event IDs.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import platform
import shlex
import subprocess
import sys
import urllib.request
import uuid

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


# ============================================================
# UTILITIES
# ============================================================

def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def sha256_object(value: Any) -> str:
    return sha256_text(stable_json(value))


def new_id(prefix: str = "id") -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


# ============================================================
# CONFIGURATION
# ============================================================

@dataclass
class Config:
    twin_name: str = "UniversalTwin"
    twin_id: str = field(default_factory=lambda: new_id("twin"))

    # Loopback by default. Binding elsewhere requires auth_token.
    host: str = "127.0.0.1"
    port: int = 8765

    history_limit: int = 10000
    event_match_limit: int = 20

    # Every task is auto-approved. Network peers are still authenticated.
    auto_approve: bool = True

    allow_autonomous_safe_tasks: bool = True

    # Keep dangerous actions disabled by default.
    # Terminal access is on for local tasks. Tasks arriving over the
    # network additionally need allow_terminal_network plus an auth_token.
    allow_terminal: bool = True
    allow_terminal_network: bool = False
    terminal_timeout: float = 30.0
    terminal_cwd: Optional[str] = None
    terminal_allowlist: Optional[List[str]] = None
    allow_system_files: bool = False
    allow_external_messages: bool = False
    allow_code_execution: bool = False
    allow_software_install: bool = False

    eeg_enabled: bool = False
    physiology_enabled: bool = False
    rf_enabled: bool = False
    audio_enabled: bool = False

    image_api_url: Optional[str] = None
    video_api_url: Optional[str] = None

    provenance_file: str = "twin_provenance.jsonl"

    # Shared secret for network peers. Read from the environment only.
    auth_token: Optional[str] = field(
        default_factory=lambda: os.environ.get("RABBIT_TWIN_TOKEN") or None
    )

    # Universal model adapter: any coding model / AI agent by name.
    # API keys are never stored here, only the env var name (api_key_env).
    default_model_provider: str = "local-echo"
    # External chains to anchor provenance to (read-only, opt-in).
    # Each: {"name","kind": evm|esplora|json, "url", ...}. Empty = offline.
    chain_anchors: List[Dict[str, Any]] = field(default_factory=list)

    model_providers: Dict[str, Dict[str, Any]] = field(
        default_factory=lambda: {"local-echo": {"kind": "echo"}}
    )


# ============================================================
# AGENT IDENTITY
# ============================================================

@dataclass
class AgentIdentity:
    agent_id: str
    name: str
    agent_type: str
    owner_twin_id: Optional[str] = None
    public_key_hash: Optional[str] = None

    def fingerprint(self) -> str:
        return sha256_object(asdict(self))


class AgentType:
    TWIN = "digital_twin"
    CODING = "coding"
    TERMINAL = "terminal"
    DEVELOPMENT = "development"
    GPU = "gpu"
    MICROPYTHON = "micropython"
    GENERIC = "generic"
    OS = "os"


@dataclass
class Capability:
    name: str
    description: str
    enabled: bool = True


@dataclass
class AgentDescription:
    identity: AgentIdentity
    capabilities: List[Capability] = field(default_factory=list)

    def capability_names(self) -> List[str]:
        return [
            capability.name
            for capability in self.capabilities
            if capability.enabled
        ]


# ============================================================
# AGENT TASK
# ============================================================

@dataclass
class AgentTask:
    task_id: str
    task_type: str
    requester: str
    target: str
    payload: Dict[str, Any]

    auto_approved: bool = True

    created_at: str = field(default_factory=now)

    status: str = "pending"

    result: Optional[Dict[str, Any]] = None

    def digest(self) -> str:
        return sha256_object(asdict(self))


# ============================================================
# PERMISSION SYSTEM
# ============================================================

@dataclass
class AutonomyPolicy:
    read_sensors: bool = True
    update_context: bool = True
    retrieve_memory: bool = True

    generate_code: bool = True
    review_code: bool = True

    run_preapproved_tasks: bool = True

    execute_unapproved_code: bool = False
    modify_system_files: bool = False
    install_software: bool = False
    send_external_messages: bool = False
    spend_money: bool = False
    access_sensitive_data: bool = False

    access_wormhole_results: bool = True
    access_historical_events: bool = False


# ============================================================
# HISTORICAL MEMORY
# ============================================================

@dataclass
class HistoricalEvent:
    event_id: str
    timestamp: str

    title: str = ""

    description: str = ""

    # These are representations, not raw biometric data.
    visual_embedding: List[float] = field(default_factory=list)
    audio_embedding: List[float] = field(default_factory=list)
    text_embedding: List[float] = field(default_factory=list)

    eeg_embedding: List[float] = field(default_factory=list)
    physiology_embedding: List[float] = field(default_factory=list)

    tags: List[str] = field(default_factory=list)

    metadata: Dict[str, Any] = field(default_factory=dict)


class HistoricalMemory:

    def __init__(self, limit: int = 10000):
        self.limit = limit
        self.events: Dict[str, HistoricalEvent] = {}

    def add(self, event: HistoricalEvent) -> None:

        if len(self.events) >= self.limit:

            oldest = sorted(
                self.events.values(),
                key=lambda x: x.timestamp
            )[0]

            self.events.pop(oldest.event_id, None)

        self.events[event.event_id] = event

    def get(self, event_id: str) -> Optional[HistoricalEvent]:
        return self.events.get(event_id)

    def all(self) -> List[HistoricalEvent]:
        return list(self.events.values())

    def search(
        self,
        query: str,
        limit: int = 20,
    ) -> List[HistoricalEvent]:

        query_tokens = set(
            query.lower().split()
        )

        scored = []

        for event in self.events.values():

            text = " ".join([
                event.title,
                event.description,
                " ".join(event.tags),
            ]).lower()

            tokens = set(text.split())

            overlap = len(
                query_tokens.intersection(tokens)
            )

            scored.append(
                (overlap, event)
            )

        scored.sort(
            key=lambda x: x[0],
            reverse=True
        )

        return [
            event
            for _, event in scored[:limit]
        ]


# ============================================================
# PERSONAL DATASET
# ============================================================

class PersonalDataset:

    def __init__(self):
        self.records: List[Dict[str, Any]] = []

    def add(self, record: Dict[str, Any]) -> str:

        record_copy = dict(record)

        record_copy.setdefault(
            "record_id",
            new_id("record")
        )

        record_copy.setdefault(
            "timestamp",
            now()
        )

        self.records.append(record_copy)

        return record_copy["record_id"]

    def digest(self) -> str:
        return sha256_object(self.records)


# ============================================================
# EEG ADAPTER
# ============================================================

class EEGAdapter:

    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def read(self) -> Dict[str, Any]:

        if not self.enabled:
            return {
                "available": False,
                "reason": "EEG disabled"
            }

        # Hardware-specific BrainFlow/device implementation
        # can be connected here.

        return {
            "available": True,
            "timestamp": now(),
            "features": [],
            "source": "EEG"
        }


# ============================================================
# PHYSIOLOGY / HORMONE ADAPTER
# ============================================================

class PhysiologyAdapter:

    """
    Slow contextual channel.

    A real implementation could consume validated physiological
    measurements from supported hardware or laboratory datasets.

    Hormone measurements should not be treated as instantaneous
    commands to the AI.
    """

    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def read(self) -> Dict[str, Any]:

        if not self.enabled:
            return {
                "available": False,
                "reason": "physiology disabled"
            }

        return {
            "available": True,
            "timestamp": now(),
            "features": [],
            "source": "PHYSIOLOGY"
        }


# ============================================================
# RF ADAPTER
# ============================================================

class RFAdapter:

    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def read(self) -> Dict[str, Any]:

        if not self.enabled:
            return {
                "available": False,
                "reason": "RF disabled"
            }

        return {
            "available": True,
            "timestamp": now(),
            "features": [],
            "source": "RF"
        }


# ============================================================
# AUDIO ADAPTER
# ============================================================

class AudioAdapter:

    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def read(self) -> Dict[str, Any]:

        if not self.enabled:
            return {
                "available": False,
                "reason": "audio disabled"
            }

        return {
            "available": True,
            "timestamp": now(),
            "features": [],
            "source": "AUDIO"
        }


# ============================================================
# STATE ESTIMATOR
# ============================================================

@dataclass
class StateEstimate:

    state_id: str

    timestamp: str

    eeg: Dict[str, Any]

    physiology: Dict[str, Any]

    rf: Dict[str, Any]

    audio: Dict[str, Any]

    user_guidance: str

    context: Dict[str, Any] = field(default_factory=dict)

    confidence: float = 0.0


class StateEstimator:

    def estimate(
        self,
        eeg: Dict[str, Any],
        physiology: Dict[str, Any],
        rf: Dict[str, Any],
        audio: Dict[str, Any],
        user_guidance: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> StateEstimate:

        available = 0

        for source in [
            eeg,
            physiology,
            rf,
            audio,
        ]:
            if source.get("available"):
                available += 1

        confidence = min(
            1.0,
            0.20 * available +
            (0.20 if user_guidance else 0.0)
        )

        return StateEstimate(
            state_id=new_id("state"),
            timestamp=now(),
            eeg=eeg,
            physiology=physiology,
            rf=rf,
            audio=audio,
            user_guidance=user_guidance,
            context=context or {},
            confidence=confidence,
        )


# ============================================================
# DIGITAL TWIN
# ============================================================

class DigitalTwin:

    def __init__(
        self,
        identity: AgentIdentity,
        dataset: PersonalDataset,
        memory: HistoricalMemory,
    ):
        self.identity = identity
        self.dataset = dataset
        self.memory = memory

        self.current_state: Optional[StateEstimate] = None

        self.context: Dict[str, Any] = {}

    def update_state(
        self,
        state: StateEstimate,
    ) -> None:

        self.current_state = state

    def add_context(
        self,
        key: str,
        value: Any,
    ) -> None:

        self.context[key] = value

    def context_digest(self) -> str:
        return sha256_object(self.context)


# ============================================================
# WORMHOLE EVENT MATCH
# ============================================================

@dataclass
class EventMatch:

    event_id: str

    score: float

    confidence: float

    evidence: Dict[str, float]

    explanation: str


@dataclass
class WormholeResult:

    wormhole_id: str

    timestamp: str

    state_id: str

    user_guidance: str

    matches: List[EventMatch]

    selected_event_id: Optional[str]

    scene_state: Dict[str, Any]

    confidence: float


# ============================================================
# EEG-HORMONE WORMHOLE
# ============================================================

class EEGHormoneWormhole:

    """
    Synchronization and retrieval layer connecting:

        current signals
             +
        historical personal events
             +
        user guidance
             +
        Twin context

    It does NOT claim to directly decode an exact memory.
    It generates ranked candidate historical events.
    """

    def __init__(
        self,
        twin: DigitalTwin,
        memory: HistoricalMemory,
        limit: int = 20,
    ):

        self.twin = twin
        self.memory = memory
        self.limit = limit

        self.last_result: Optional[
            WormholeResult
        ] = None

    # --------------------------------------------------------
    # Text/context similarity
    # --------------------------------------------------------

    def _text_score(
        self,
        guidance: str,
        event: HistoricalEvent,
    ) -> float:

        if not guidance:
            return 0.0

        query = set(
            guidance.lower().split()
        )

        text = set(
            (
                event.title +
                " " +
                event.description +
                " " +
                " ".join(event.tags)
            ).lower().split()
        )

        if not query:
            return 0.0

        return len(
            query.intersection(text)
        ) / len(query)

    # --------------------------------------------------------
    # Vector similarity
    # --------------------------------------------------------

    def _vector_similarity(
        self,
        a: List[float],
        b: List[float],
    ) -> float:

        if not a or not b:
            return 0.0

        length = min(len(a), len(b))

        if length == 0:
            return 0.0

        aa = a[:length]
        bb = b[:length]

        dot = sum(
            x * y
            for x, y in zip(aa, bb)
        )

        norm_a = sum(
            x * x for x in aa
        ) ** 0.5

        norm_b = sum(
            x * x for x in bb
        ) ** 0.5

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return max(
            0.0,
            min(
                1.0,
                dot / (norm_a * norm_b)
            )
        )

    # --------------------------------------------------------
    # Match current state to event
    # --------------------------------------------------------

    def _score_event(
        self,
        state: StateEstimate,
        event: HistoricalEvent,
    ) -> EventMatch:

        guidance_score = self._text_score(
            state.user_guidance,
            event,
        )

        eeg_score = 0.0

        physiology_score = 0.0

        # Real systems should pass learned embeddings
        # here rather than raw EEG values.

        if state.eeg.get("embedding"):
            eeg_score = self._vector_similarity(
                state.eeg["embedding"],
                event.eeg_embedding,
            )

        if state.physiology.get("embedding"):
            physiology_score = self._vector_similarity(
                state.physiology["embedding"],
                event.physiology_embedding,
            )

        contextual_score = 0.0

        if event.metadata:

            context_terms = set()

            for key, value in event.metadata.items():
                context_terms.add(
                    str(key).lower()
                )
                context_terms.add(
                    str(value).lower()
                )

            if state.context:

                current_terms = set(
                    str(value).lower()
                    for value in state.context.values()
                )

                if context_terms and current_terms:

                    overlap = (
                        context_terms
                        .intersection(current_terms)
                    )

                    contextual_score = min(
                        1.0,
                        len(overlap) /
                        max(1, len(current_terms))
                    )

        # Guidance receives the strongest semantic role.
        score = (
            0.45 * guidance_score +
            0.25 * eeg_score +
            0.15 * physiology_score +
            0.15 * contextual_score
        )

        confidence = min(
            1.0,
            score +
            (0.15 if state.user_guidance else 0.0)
        )

        evidence = {
            "user_guidance": guidance_score,
            "eeg": eeg_score,
            "physiology": physiology_score,
            "context": contextual_score,
        }

        explanation = (
            "Candidate generated from multimodal "
            "state/context similarity."
        )

        return EventMatch(
            event_id=event.event_id,
            score=score,
            confidence=confidence,
            evidence=evidence,
            explanation=explanation,
        )

    # --------------------------------------------------------
    # Run wormhole
    # --------------------------------------------------------

    def run(
        self,
        state: StateEstimate,
    ) -> WormholeResult:

        events = self.memory.all()

        matches = [
            self._score_event(
                state,
                event
            )
            for event in events
        ]

        matches.sort(
            key=lambda x: x.score,
            reverse=True
        )

        matches = matches[:self.limit]

        selected = (
            matches[0].event_id
            if matches
            else None
        )

        top_event = (
            self.memory.get(selected)
            if selected
            else None
        )

        scene_state = self.build_scene_state(
            state,
            top_event,
            matches,
        )

        result = WormholeResult(
            wormhole_id=new_id("wormhole"),
            timestamp=now(),
            state_id=state.state_id,
            user_guidance=state.user_guidance,
            matches=matches,
            selected_event_id=selected,
            scene_state=scene_state,
            confidence=(
                matches[0].confidence
                if matches
                else 0.0
            ),
        )

        self.last_result = result

        return result

    # --------------------------------------------------------
    # Scene construction
    # --------------------------------------------------------

    def build_scene_state(
        self,
        state: StateEstimate,
        selected_event: Optional[HistoricalEvent],
        matches: List[EventMatch],
    ) -> Dict[str, Any]:

        if selected_event:

            return {
                "mode": "historical_reconstruction",
                "event_id": selected_event.event_id,
                "event_title": selected_event.title,
                "event_description":
                    selected_event.description,
                "event_timestamp":
                    selected_event.timestamp,
                "tags": selected_event.tags,
                "confidence":
                    matches[0].confidence
                    if matches else 0.0,
                "user_guidance":
                    state.user_guidance,
            }

        return {
            "mode": "guided_generation",
            "user_guidance":
                state.user_guidance,
            "confidence": 0.0,
        }


# ============================================================
# GENERATIVE AI ADAPTER
# ============================================================

class ImageGenerator:

    def __init__(
        self,
        endpoint: Optional[str] = None,
    ):
        self.endpoint = endpoint

    def generate(
        self,
        scene_state: Dict[str, Any],
    ) -> Dict[str, Any]:

        return {
            "generator": "image",
            "endpoint": self.endpoint,
            "scene_hash":
                sha256_object(scene_state),
            "scene": scene_state,
            "status": "generation_request_created",
        }


class VideoGenerator:

    def __init__(
        self,
        endpoint: Optional[str] = None,
    ):
        self.endpoint = endpoint

    def generate(
        self,
        scene_state: Dict[str, Any],
    ) -> Dict[str, Any]:

        return {
            "generator": "video",
            "endpoint": self.endpoint,
            "scene_hash":
                sha256_object(scene_state),
            "scene": scene_state,
            "status": "generation_request_created",
        }


# ============================================================
# RECONSTRUCTION SESSION
# ============================================================

@dataclass
class ReconstructionSession:

    session_id: str

    twin_id: str

    started_at: str

    iterations: int = 0

    wormhole_ids: List[str] = field(
        default_factory=list
    )

    selected_events: List[str] = field(
        default_factory=list
    )

    feedback: List[Dict[str, Any]] = field(
        default_factory=list
    )


class ReconstructionEngine:

    def __init__(
        self,
        wormhole: EEGHormoneWormhole,
        image_generator: ImageGenerator,
        video_generator: VideoGenerator,
    ):

        self.wormhole = wormhole
        self.image_generator = image_generator
        self.video_generator = video_generator

        self.session: Optional[
            ReconstructionSession
        ] = None

    def start(
        self,
        twin_id: str,
    ) -> str:

        self.session = ReconstructionSession(
            session_id=new_id("recon"),
            twin_id=twin_id,
            started_at=now(),
        )

        return self.session.session_id

    def reconstruct(
        self,
        state: StateEstimate,
    ) -> Dict[str, Any]:

        if self.session is None:

            self.start(
                self.wormhole.twin.identity.agent_id
            )

        result = self.wormhole.run(state)

        image = self.image_generator.generate(
            result.scene_state
        )

        video = self.video_generator.generate(
            result.scene_state
        )

        self.session.iterations += 1

        self.session.wormhole_ids.append(
            result.wormhole_id
        )

        if result.selected_event_id:
            self.session.selected_events.append(
                result.selected_event_id
            )

        return {
            "wormhole": result,
            "image": image,
            "video": video,
        }

    def add_feedback(
        self,
        feedback: str,
        rating: Optional[float] = None,
    ) -> None:

        if self.session is None:
            return

        self.session.feedback.append({
            "timestamp": now(),
            "feedback": feedback,
            "rating": rating,
        })


# ============================================================
# SPECIALIZED AGENTS
# ============================================================

def require_http_url(url: str) -> str:
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("Only http(s) URLs are allowed.")
    return url


def is_loopback_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1")


class UniversalModelClient:
    """
    Provider-neutral chat client for any coding model or AI agent.

    kind = "echo"       offline stub, no network
    kind = "openai"     any OpenAI-compatible /chat/completions API
                        (OpenAI, Azure-style gateways, OpenRouter, vLLM,
                        LM Studio, llama.cpp server, Ollama /v1, ...)
    kind = "anthropic"  Anthropic Messages API
    kind = "ollama"     native Ollama /api/chat
    """

    DEFAULT_URLS = {
        "openai": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com",
        "ollama": "http://127.0.0.1:11434",
    }

    def __init__(self, name: str, spec: Dict[str, Any]):
        self.name = name
        self.kind = spec.get("kind", "echo")
        self.model = spec.get("model", "")
        self.base_url = (
            spec.get("base_url")
            or self.DEFAULT_URLS.get(self.kind, "")
        ).rstrip("/")
        self.api_key_env = spec.get("api_key_env")
        self.timeout = float(spec.get("timeout", 60))
        self.max_tokens = int(spec.get("max_tokens", 1024))

    @property
    def is_local(self) -> bool:
        return self.kind == "echo" or is_loopback_url(self.base_url)

    def _post(self, url, body, headers):
        request = urllib.request.Request(
            require_http_url(url),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def complete(self, prompt: str, system: str = "") -> str:
        if self.kind == "echo":
            return f"[echo] {prompt}"

        key = os.environ.get(self.api_key_env, "") if self.api_key_env else ""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        if self.kind == "openai":
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            data = self._post(
                self.base_url + "/chat/completions",
                {"model": self.model, "messages": messages},
                headers,
            )
            return data["choices"][0]["message"]["content"]

        if self.kind == "anthropic":
            body = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                body["system"] = system
            data = self._post(
                self.base_url + "/v1/messages",
                body,
                {"x-api-key": key, "anthropic-version": "2023-06-01"},
            )
            return "".join(b.get("text", "") for b in data.get("content", []))

        if self.kind == "ollama":
            data = self._post(
                self.base_url + "/api/chat",
                {"model": self.model, "messages": messages, "stream": False},
                {},
            )
            return data["message"]["content"]

        raise ValueError(f"Unknown model provider kind: {self.kind}")


class CodingAgent:
    """
    Routes a prompt to any configured model provider.

    The wormhole context and personal data are never sent to a model.
    Non-loopback providers are blocked unless allow_external_messages
    is enabled. Model output is returned as text and is never executed.
    """

    def __init__(self, config: "Config"):
        self.config = config

    def handle(
        self,
        task: AgentTask,
    ) -> Dict[str, Any]:

        payload = task.payload or {}
        name = payload.get("provider") or self.config.default_model_provider
        base = {
            "agent": "coding",
            "task_id": task.task_id,
            "provider": name,
        }

        prompt = payload.get("prompt") or payload.get("message") or ""
        if not prompt:
            return {**base, "status": "invalid_task",
                    "reason": "payload.prompt is required."}

        spec = self.config.model_providers.get(name)
        if spec is None:
            return {**base, "status": "unknown_provider"}

        client = UniversalModelClient(name, spec)

        if not client.is_local and not self.config.allow_external_messages:
            return {**base, "status": "blocked",
                    "reason": "External model providers are disabled "
                              "(allow_external_messages)."}

        try:
            output = client.complete(prompt, payload.get("system", ""))
        except Exception as exc:
            return {**base, "status": "error",
                    "reason": f"{type(exc).__name__}: {exc}"}

        return {**base, "status": "completed", "output": output}


class TerminalAgent:
    """
    Runs one command without a shell (no pipes, redirects or expansion).

    Enforces a timeout and an output cap. If terminal_allowlist is set,
    only those executable names run. Commands arriving over the network
    are blocked unless allow_terminal_network and auth_token are set.
    """

    MAX_OUTPUT = 20000

    def __init__(self, config: "Config"):
        self.config = config

    def handle(
        self,
        task: AgentTask,
        origin: str = "local",
    ) -> Dict[str, Any]:

        base = {"agent": "terminal", "task_id": task.task_id}

        if not self.config.allow_terminal:
            return {**base, "status": "blocked",
                    "reason": "Terminal execution disabled."}

        if origin == "network" and not (
            self.config.allow_terminal_network and self.config.auth_token
        ):
            return {**base, "status": "blocked",
                    "reason": "Network terminal tasks need "
                              "allow_terminal_network and RABBIT_TWIN_TOKEN."}

        command = (task.payload or {}).get("command", "")
        try:
            argv = (
                list(command) if isinstance(command, list)
                else shlex.split(command, posix=(os.name != "nt"))
            )
        except ValueError as exc:
            return {**base, "status": "invalid_task", "reason": str(exc)}

        if not argv:
            return {**base, "status": "invalid_task",
                    "reason": "payload.command is required."}

        allow = self.config.terminal_allowlist
        if allow is not None and os.path.basename(argv[0]) not in allow:
            return {**base, "status": "blocked",
                    "reason": f"{argv[0]} is not in terminal_allowlist."}

        try:
            done = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self.config.terminal_timeout,
                cwd=self.config.terminal_cwd,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return {**base, "status": "timeout"}
        except Exception as exc:
            return {**base, "status": "error",
                    "reason": f"{type(exc).__name__}: {exc}"}

        return {
            **base,
            "status": "completed",
            "returncode": done.returncode,
            "stdout": done.stdout[: self.MAX_OUTPUT],
            "stderr": done.stderr[: self.MAX_OUTPUT],
        }


class DevelopmentAgent:

    def handle(
        self,
        task: AgentTask,
    ) -> Dict[str, Any]:

        return {
            "agent": "development",
            "task_id": task.task_id,
            "status": "completed",
            "output":
                "Development task accepted.",
        }


class GPUAgent:

    def handle(
        self,
        task: AgentTask,
    ) -> Dict[str, Any]:

        return {
            "agent": "gpu",
            "task_id": task.task_id,
            "status": "completed",
            "output":
                "GPU learning task registered.",
        }


class MicroPythonAgent:

    def handle(
        self,
        task: AgentTask,
    ) -> Dict[str, Any]:

        return {
            "agent": "micropython",
            "task_id": task.task_id,
            "status": "completed",
            "output":
                "MicroPython task registered.",
        }


# ============================================================
# PROVENANCE
# ============================================================

@dataclass
class ProvenanceBlock:

    block_index: int

    timestamp: str

    event_type: str

    data_hash: str

    previous_hash: str

    block_hash: str = ""

    # References to blocks on other chains observed when this was sealed.
    anchors: List[Dict[str, Any]] = field(default_factory=list)

    def compute_hash(self) -> str:

        return sha256_object({
            "block_index":
                self.block_index,
            "timestamp":
                self.timestamp,
            "event_type":
                self.event_type,
            "data_hash":
                self.data_hash,
            "previous_hash":
                self.previous_hash,
            "anchors":
                self.anchors,
        })

    def seal(self) -> None:

        self.block_hash = self.compute_hash()


class ChainReader:
    """
    Read-only adapter that fetches the current head of ANY chain.

    kind = "evm"      JSON-RPC (Ethereum, Polygon, Base, BSC, Avalanche C,
                      Arbitrum, Optimism, ... any EVM chain)
    kind = "esplora"  Esplora REST (Bitcoin, Liquid, via blockstream.info,
                      mempool.space or your own node)
    kind = "json"     Any HTTP JSON endpoint: set "height_path" and/or
                      "hash_path" as dotted paths (e.g. "result.hash")
    No keys are held and nothing is ever written to these chains.
    """

    def __init__(self, spec: Dict[str, Any]):
        self.spec = spec
        self.name = spec.get("name", spec.get("kind", "chain"))
        self.kind = spec.get("kind", "json")
        self.url = spec.get("url", "").rstrip("/")
        self.timeout = float(spec.get("timeout", 10))

    UA = {"User-Agent": "UniversalTwinOS/1.0"}

    def _get(self, url):
        req = urllib.request.Request(require_http_url(url), headers=self.UA)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read().decode("utf-8")

    def _rpc(self, method, params):
        request = urllib.request.Request(
            require_http_url(self.url),
            data=json.dumps({
                "jsonrpc": "2.0", "id": 1,
                "method": method, "params": params,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json", **self.UA},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))["result"]

    @staticmethod
    def _dig(value, path):
        for part in path.split("."):
            value = value[int(part)] if isinstance(value, list) \
                else value[part]
        return value

    def head(self) -> Dict[str, Any]:

        if self.kind == "evm":
            block = self._rpc("eth_getBlockByNumber", ["latest", False])
            height = int(block["number"], 16)
            digest = block["hash"]

        elif self.kind == "esplora":
            digest = self._get(self.url + "/blocks/tip/hash").strip()
            height = int(self._get(self.url + "/blocks/tip/height"))

        else:
            data = json.loads(self._get(self.url))
            hp, dp = self.spec.get("height_path"), self.spec.get("hash_path")
            height = self._dig(data, hp) if hp else None
            digest = self._dig(data, dp) if dp else sha256_object(data)

        return {
            "chain": self.name,
            "kind": self.kind,
            "height": height,
            "hash": str(digest),
            "observed_at": now(),
        }


class ProvenanceBlockchain:

    """
    Append-only hash chain that CONTINUES an existing chain.

    On start it resumes from the saved file; it never replaces it with a
    new genesis block. Only when there is no history does it write a
    first "ANCHOR" block, which references the current head of every
    configured external chain (Bitcoin, any EVM chain, any JSON API).
    Blocks keep "anchors" so history is tied to real, public chains.

    This is NOT a distributed consensus blockchain. It reads from other
    chains; it does not write to them.
    """

    def __init__(
        self,
        filename: str = "twin_provenance.jsonl",
        anchors: Optional[List[Dict[str, Any]]] = None,
    ):

        self.filename = filename

        self.readers = [ChainReader(spec) for spec in (anchors or [])]

        self.chain: List[
            ProvenanceBlock
        ] = []

        self._load()

        if not self.chain:
            self._start()

    def _load(self) -> None:

        try:
            with open(self.filename, encoding="utf-8") as file:
                for line in file:
                    if line.strip():
                        self.chain.append(
                            ProvenanceBlock(**json.loads(line))
                        )
        except FileNotFoundError:
            pass
        except Exception:
            self.chain = []

        if self.chain and not self.verify():
            raise SystemExit(
                f"{self.filename} failed verification; refusing to extend it."
            )

    def observe_anchors(self) -> List[Dict[str, Any]]:

        observed = []
        for reader in self.readers:
            try:
                observed.append(reader.head())
            except Exception as exc:
                observed.append({
                    "chain": reader.name,
                    "error": f"{type(exc).__name__}",
                })
        return observed

    def _persist(self, block: ProvenanceBlock) -> None:

        try:
            with open(self.filename, "a", encoding="utf-8") as file:
                file.write(json.dumps(asdict(block)) + "\n")
        except Exception:
            pass

    def _start(self) -> None:

        anchors = self.observe_anchors()

        block = ProvenanceBlock(
            block_index=0,
            timestamp=now(),
            event_type="ANCHOR" if anchors else "LOCAL_ROOT",
            data_hash=sha256_text("UniversalTwinOS"),
            previous_hash=(
                anchors[0].get("hash", "0") if anchors else "0"
            ),
            anchors=anchors,
        )

        block.seal()

        self.chain.append(block)

        self._persist(block)

    def add(
        self,
        event_type: str,
        data: Dict[str, Any],
        anchor: bool = False,
    ) -> ProvenanceBlock:

        previous = self.chain[-1]

        block = ProvenanceBlock(
            block_index=len(self.chain),
            timestamp=now(),
            event_type=event_type,
            data_hash=sha256_object(data),
            previous_hash=previous.block_hash,
            anchors=self.observe_anchors() if anchor else [],
        )

        block.seal()

        self.chain.append(block)

        self._persist(block)

        return block

    def verify(self) -> bool:

        for index, current in enumerate(self.chain):

            if current.block_hash != current.compute_hash():
                return False

            if index and (
                current.previous_hash
                != self.chain[index - 1].block_hash
            ):
                return False

        return True


# ============================================================
# UNIVERSAL A2A PROTOCOL
# ============================================================

class UniversalA2A:

    VERSION = "1.0"

    @staticmethod
    def message(
        sender: AgentIdentity,
        receiver: str,
        message_type: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:

        body = {
            "protocol": "UniversalA2A",
            "version": UniversalA2A.VERSION,
            "message_id": new_id("msg"),
            "timestamp": now(),

            "sender": asdict(sender),
            "receiver": receiver,

            "message_type": message_type,

            "payload": payload,
        }

        body["message_hash"] = sha256_object(
            body
        )

        return body


# ============================================================
# UNIVERSAL AGENT NODE
# ============================================================

class UniversalAgentNode:

    def __init__(
        self,
        config: Config,
    ):

        self.config = config

        identity = AgentIdentity(
            agent_id=config.twin_id,
            name=config.twin_name,
            agent_type=AgentType.TWIN,
            owner_twin_id=config.twin_id,
            public_key_hash=sha256_text(
                config.twin_id
            ),
        )

        self.identity = identity

        self.dataset = PersonalDataset()

        self.memory = HistoricalMemory(
            config.history_limit
        )

        self.twin = DigitalTwin(
            identity,
            self.dataset,
            self.memory,
        )

        self.policy = AutonomyPolicy()

        self.state_estimator = StateEstimator()

        # ----------------------------------------------------
        # SENSOR LAYERS
        # ----------------------------------------------------

        self.eeg = EEGAdapter(
            config.eeg_enabled
        )

        self.physiology = PhysiologyAdapter(
            config.physiology_enabled
        )

        self.rf = RFAdapter(
            config.rf_enabled
        )

        self.audio = AudioAdapter(
            config.audio_enabled
        )

        # ----------------------------------------------------
        # WORMHOLE
        # ----------------------------------------------------

        self.wormhole = EEGHormoneWormhole(
            self.twin,
            self.memory,
            config.event_match_limit,
        )

        # ----------------------------------------------------
        # GENERATION
        # ----------------------------------------------------

        self.image_generator = ImageGenerator(
            config.image_api_url
        )

        self.video_generator = VideoGenerator(
            config.video_api_url
        )

        self.reconstruction = ReconstructionEngine(
            self.wormhole,
            self.image_generator,
            self.video_generator,
        )

        # ----------------------------------------------------
        # AGENTS
        # ----------------------------------------------------

        self.coding_agent = CodingAgent(config)

        self.terminal_agent = TerminalAgent(config)

        self.development_agent = DevelopmentAgent()

        self.gpu_agent = GPUAgent()

        self.micropython_agent = MicroPythonAgent()

        # ----------------------------------------------------
        # PROVENANCE
        # ----------------------------------------------------

        self.provenance = ProvenanceBlockchain(
            config.provenance_file,
            config.chain_anchors,
        )

        # ----------------------------------------------------
        # NETWORK
        # ----------------------------------------------------

        self.running = True

    # ========================================================
    # CAPABILITIES
    # ========================================================

    def capabilities(self) -> AgentDescription:

        capabilities = [

            Capability(
                "historical_memory",
                "Retrieve historical personal event representations."
            ),

            Capability(
                "state_estimation",
                "Fuse current contextual signal sources."
            ),

            Capability(
                "eeg_hormone_wormhole",
                "Match current multimodal state against historical events."
            ),

            Capability(
                "image_generation",
                "Create scene-generation requests."
            ),

            Capability(
                "video_generation",
                "Create video-generation requests."
            ),

            Capability(
                "coding",
                "Route prompts to any coding model or AI agent (OpenAI-compatible, Anthropic, Ollama, local)."
            ),

            Capability(
                "development",
                "Communicate with development agents."
            ),

            Capability(
                "terminal",
                "Communicate with terminal agents."
            ),

            Capability(
                "gpu",
                "Communicate with GPU learning agents."
            ),

            Capability(
                "micropython",
                "Communicate with MicroPython agents."
            ),
        ]

        return AgentDescription(
            identity=self.identity,
            capabilities=capabilities,
        )

    # ========================================================
    # HISTORICAL DATA
    # ========================================================

    def add_history(
        self,
        title: str,
        description: str,
        timestamp: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        eeg_embedding: Optional[List[float]] = None,
        physiology_embedding:
            Optional[List[float]] = None,
    ) -> str:

        event = HistoricalEvent(
            event_id=new_id("event"),

            timestamp=timestamp or now(),

            title=title,

            description=description,

            tags=tags or [],

            metadata=metadata or {},

            eeg_embedding=
                eeg_embedding or [],

            physiology_embedding=
                physiology_embedding or [],
        )

        self.memory.add(event)

        self.dataset.add({
            "event_id": event.event_id,
            "timestamp": event.timestamp,
            "title": title,
        })

        self.provenance.add(
            "HISTORICAL_EVENT_REGISTERED",
            {
                "event_id":
                    event.event_id,
                "event_hash":
                    sha256_object(
                        asdict(event)
                    ),
            },
        )

        return event.event_id

    # ========================================================
    # SIGNAL COLLECTION
    # ========================================================

    def collect_signals(self) -> Dict[str, Any]:

        return {
            "eeg":
                self.eeg.read(),

            "physiology":
                self.physiology.read(),

            "rf":
                self.rf.read(),

            "audio":
                self.audio.read(),
        }

    # ========================================================
    # CAPTURE STATE
    # ========================================================

    def capture_state(
        self,
        user_guidance: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> StateEstimate:

        signals = self.collect_signals()

        state = self.state_estimator.estimate(
            eeg=signals["eeg"],
            physiology=signals["physiology"],
            rf=signals["rf"],
            audio=signals["audio"],
            user_guidance=user_guidance,
            context=context or self.twin.context,
        )

        self.twin.update_state(state)

        self.provenance.add(
            "STATE_ESTIMATE",
            {
                "state_id":
                    state.state_id,

                "confidence":
                    state.confidence,

                "sources": [
                    key
                    for key, value
                    in signals.items()
                    if value.get("available")
                ],
            },
        )

        return state

    # ========================================================
    # WORMHOLE RECONSTRUCTION
    # ========================================================

    def reconstruct_event(
        self,
        user_guidance: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        state = self.capture_state(
            user_guidance,
            context,
        )

        result = self.reconstruction.reconstruct(
            state
        )

        wormhole = result["wormhole"]

        self.provenance.add(
            "WORMHOLE_EVENT_MATCH",
            {
                "wormhole_id":
                    wormhole.wormhole_id,

                "state_id":
                    wormhole.state_id,

                "selected_event":
                    wormhole.selected_event_id,

                "confidence":
                    wormhole.confidence,

                "candidate_count":
                    len(wormhole.matches),
            },
        )

        self.provenance.add(
            "GENERATION_REQUEST",
            {
                "wormhole_id":
                    wormhole.wormhole_id,

                "image_hash":
                    sha256_object(
                        result["image"]
                    ),

                "video_hash":
                    sha256_object(
                        result["video"]
                    ),
            },
        )

        return result

    # ========================================================
    # HUMAN FEEDBACK
    # ========================================================

    def provide_feedback(
        self,
        feedback: str,
        rating: Optional[float] = None,
    ) -> None:

        self.reconstruction.add_feedback(
            feedback,
            rating,
        )

        self.provenance.add(
            "HUMAN_RECONSTRUCTION_FEEDBACK",
            {
                "feedback_hash":
                    sha256_text(feedback),

                "rating":
                    rating,
            },
        )

    # ========================================================
    # TASK CREATION
    # ========================================================

    def create_task(
        self,
        target: str,
        task_type: str,
        payload: Dict[str, Any],
        auto_approve: bool = True,
    ) -> AgentTask:

        return AgentTask(
            task_id=new_id("task"),

            task_type=task_type,

            requester=self.identity.agent_id,

            target=target,

            payload=payload,

            auto_approved=auto_approve,
        )

    # ========================================================
    # WORMHOLE ACCESS POLICY
    # ========================================================

    def wormhole_context_for_agent(
        self,
        agent_type: str,
    ) -> Dict[str, Any]:

        if not self.policy.access_wormhole_results:

            return {
                "allowed": False
            }

        result = self.wormhole.last_result

        if result is None:

            return {
                "allowed": True,
                "available": False,
            }

        # Do not expose raw historical sensitive data.
        response = {
            "allowed": True,
            "available": True,

            "wormhole_id":
                result.wormhole_id,

            "selected_event_id":
                result.selected_event_id,

            "confidence":
                result.confidence,

            "scene_state":
                result.scene_state,

            "candidate_events": [
                {
                    "event_id":
                        match.event_id,

                    "score":
                        match.score,

                    "confidence":
                        match.confidence,

                    "evidence":
                        match.evidence,
                }

                for match in result.matches
            ],
        }

        # Historical content is more restricted.
        if not self.policy.access_historical_events:

            response.pop(
                "candidate_events",
                None
            )

            # scene_state can carry event text, tags and user guidance.
            response.pop(
                "scene_state",
                None
            )

        return response

    # ========================================================
    # EXECUTE TASK
    # ========================================================

    def execute_task(
        self,
        task: AgentTask,
        origin: str = "local",
    ) -> Dict[str, Any]:

        self.provenance.add(
            "TASK_RECEIVED",
            asdict(task),
        )

        # ----------------------------------------------------
        # Permission check
        # ----------------------------------------------------

        task.auto_approved = True

        self.provenance.add(
            "TASK_AUTO_APPROVED",
            {
                "task_id":
                    task.task_id,
            },
        )

        # ----------------------------------------------------
        # Wormhole context can be provided to agents.
        # ----------------------------------------------------

        wormhole_context = (
            self.wormhole_context_for_agent(
                task.target
            )
        )

        payload = dict(
            task.payload
        )

        payload["wormhole_context"] = (
            wormhole_context
        )

        # ----------------------------------------------------
        # Route task
        # ----------------------------------------------------

        if task.task_type in ("coding", "model"):

            result = self.coding_agent.handle(
                task
            )

        elif task.task_type == "development":

            result = self.development_agent.handle(
                task
            )

        elif task.task_type == "terminal":

            result = self.terminal_agent.handle(
                task,
                origin,
            )

        elif task.task_type == "gpu":

            result = self.gpu_agent.handle(
                task
            )

        elif task.task_type == "micropython":

            result = self.micropython_agent.handle(
                task
            )

        elif task.task_type == "wormhole_query":

            result = {
                "status":
                    "completed",

                "wormhole":
                    wormhole_context,
            }

        elif task.task_type == "reconstruct":

            guidance = payload.get(
                "user_guidance",
                ""
            )

            result = self.reconstruct_event(
                guidance,
                payload.get(
                    "context",
                    {}
                ),
            )

        else:

            result = {
                "status":
                    "unknown_task",

                "task_type":
                    task.task_type,
            }

        self.provenance.add(
            "TASK_RESULT",
            {
                "task_id":
                    task.task_id,

                "result_hash":
                    sha256_object(result),
            },
        )

        task.status = "completed"

        task.result = result

        return result

    # ========================================================
    # A2A MESSAGE
    # ========================================================

    def build_a2a_task_message(
        self,
        task: AgentTask,
    ) -> Dict[str, Any]:

        return UniversalA2A.message(
            self.identity,

            task.target,

            "TASK_REQUEST",

            {
                "task":
                    asdict(task),
            },
        )

    # ========================================================
    # NETWORK MESSAGE HANDLER
    # ========================================================

    async def handle_message(
        self,
        message: Dict[str, Any],
    ) -> Dict[str, Any]:

        message_type = message.get(
            "message_type"
        )

        sender = message.get(
            "sender",
            {}
        )

        sender_id = sender.get(
            "agent_id",
            "unknown"
        )

        # ----------------------------------------------------
        # Identity
        # ----------------------------------------------------

        if message_type == "IDENTITY_REQUEST":

            return UniversalA2A.message(
                self.identity,

                sender_id,

                "IDENTITY_RESPONSE",

                {
                    "identity":
                        asdict(
                            self.identity
                        )
                },
            )

        # ----------------------------------------------------
        # Capabilities
        # ----------------------------------------------------

        if message_type == "CAPABILITY_REQUEST":

            description = self.capabilities()

            return UniversalA2A.message(
                self.identity,

                sender_id,

                "CAPABILITY_RESPONSE",

                {
                    "description":
                        asdict(description)
                },
            )

        # ----------------------------------------------------
        # Task
        # ----------------------------------------------------

        if message_type == "TASK_REQUEST":

            task_data = (
                message
                .get("payload", {})
                .get("task")
            )

            if not task_data:

                return UniversalA2A.message(
                    self.identity,
                    sender_id,
                    "TASK_RESULT",
                    {
                        "status":
                            "invalid_task"
                    },
                )

            known = AgentTask.__dataclass_fields__
            task = AgentTask(
                **{
                    key: value
                    for key, value in task_data.items()
                    if key in known
                }
            )

            result = self.execute_task(
                task,
                origin="network",
            )

            return UniversalA2A.message(
                self.identity,

                sender_id,

                "TASK_RESULT",

                {
                    "task_id":
                        task.task_id,

                    "result":
                        result,
                },
            )

        # ----------------------------------------------------
        # Result
        # ----------------------------------------------------

        if message_type == "TASK_RESULT":

            return {
                "status":
                    "received",

                "message_type":
                    "TASK_RESULT",

                "payload":
                    message.get(
                        "payload",
                        {}
                    ),
            }

        return {
            "status":
                "unknown_message",

            "message_type":
                message_type,
        }

    # ========================================================
    # UNIVERSAL TOOL SCHEMAS AND HTTP GATEWAY
    # ========================================================

    TASK_TYPES = {
        "terminal": "Run one command (no shell) with timeout.",
        "coding": "Send a prompt to any configured coding model.",
        "model": "Alias of coding for any AI model.",
        "development": "Development task.",
        "gpu": "GPU learning task.",
        "micropython": "MicroPython task.",
        "wormhole_query": "Read the redacted wormhole context.",
        "reconstruct": "Reconstruct a scene from user guidance.",
    }

    def tool_schemas(self) -> List[Dict[str, Any]]:
        """Framework-neutral tool list (name/description/input_schema).

        Maps directly to MCP and Anthropic tools; wrap as
        {"type": "function", "function": {...parameters...}} for OpenAI."""

        return [
            {
                "name": f"twinos_{name}",
                "description": description,
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string"},
                        "provider": {"type": "string"},
                        "user_guidance": {"type": "string"},
                    },
                },
                "task_type": name,
            }
            for name, description in self.TASK_TYPES.items()
        ]

    def authorized(self, supplied: str) -> bool:
        token = self.config.auth_token
        if not token:
            return True
        return hmac.compare_digest(str(supplied), token)

    async def http_handler(self, first_line, reader, writer):
        try:
            method, path, _ = first_line.decode("latin-1").split(" ", 2)
        except ValueError:
            return

        headers = {}
        while True:
            line = await asyncio.wait_for(reader.readline(), 15)
            if len(headers) > 100:
                break
            if line in (b"\r\n", b"\n", b""):
                break
            key, _, value = line.decode("latin-1").partition(":")
            headers[key.strip().lower()] = value.strip()

        async def reply(code, body):
            text = json.dumps(body, default=str).encode("utf-8")
            writer.write(
                f"HTTP/1.1 {code}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(text)}\r\nConnection: close\r\n\r\n"
                .encode("latin-1") + text
            )
            await writer.drain()

        if not self.config.auth_token and not is_loopback_url(
            "//" + headers.get("host", "")
        ):
            await reply("403 Forbidden", {"error": "host not allowed"})
            return

        bearer = headers.get("authorization", "")
        if bearer.lower().startswith("bearer "):
            bearer = bearer[7:]
        if not self.authorized(bearer):
            await reply("401 Unauthorized", {"error": "unauthorized"})
            return

        path = path.split("?", 1)[0]

        if method == "GET" and path == "/health":
            await reply("200 OK", {"status": "ok"})
        elif method == "GET" and path == "/.well-known/agent.json":
            await reply("200 OK", {
                "protocol": "UniversalA2A",
                "version": UniversalA2A.VERSION,
                "description": asdict(self.capabilities()),
                "tools": self.tool_schemas(),
            })
        elif method == "POST" and path == "/a2a":
            try:
                length = int(headers.get("content-length", "0") or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > 1_000_000:
                await reply("413 Payload Too Large", {"error": "bad length"})
                return
            body = await asyncio.wait_for(reader.readexactly(length), 15)
            response = await self.handle_message(json.loads(body))
            await reply("200 OK", response)
        else:
            await reply("404 Not Found", {"error": "not found"})

    # ========================================================
    # NETWORK SERVER
    # ========================================================

    async def network_handler(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):

        try:

            data = await asyncio.wait_for(reader.readline(), 15)

            if not data:
                return

            if data.split(b" ", 1)[0] in (b"GET", b"POST"):
                await self.http_handler(data, reader, writer)
                return

            message = json.loads(
                data.decode("utf-8")
            )

            if not self.authorized(message.get("auth", "")):
                raise PermissionError("unauthorized")

            response = await self.handle_message(
                message
            )

            writer.write(
                (
                    json.dumps(response)
                    + "\n"
                ).encode("utf-8")
            )

            await writer.drain()

        except Exception as exc:

            error = {
                "status":
                    "error",

                "error":
                    str(exc),
            }

            writer.write(
                (
                    json.dumps(error)
                    + "\n"
                ).encode("utf-8")
            )

            await writer.drain()

        finally:

            writer.close()

            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def start_server(
        self,
    ):

        if not is_loopback_url(f"//{self.config.host}") \
                and not self.config.auth_token:
            raise SystemExit(
                "Refusing to listen on a non-loopback address without "
                "RABBIT_TWIN_TOKEN set."
            )

        server = await asyncio.start_server(
            self.network_handler,

            self.config.host,

            self.config.port,
        )

        addresses = ", ".join(
            str(sock.getsockname())
            for sock in server.sockets
        )

        print(
            f"Universal TwinOS A2A server: "
            f"{addresses}"
        )

        async with server:
            await server.serve_forever()

    # ========================================================
    # SEND A2A MESSAGE
    # ========================================================

    async def send_message(
        self,
        host: str,
        port: int,
        message: Dict[str, Any],
    ) -> Dict[str, Any]:

        if self.config.auth_token:
            message = {**message, "auth": self.config.auth_token}

        reader, writer = await asyncio.open_connection(
            host,
            port,
        )

        writer.write(
            (
                json.dumps(message)
                + "\n"
            ).encode("utf-8")
        )

        await writer.drain()

        data = await reader.readline()

        writer.close()

        try:
            await writer.wait_closed()
        except Exception:
            pass

        if not data:
            return {
                "status":
                    "no_response"
            }

        return json.loads(
            data.decode("utf-8")
        )

    # ========================================================
    # SEND TASK TO OTHER AGENT
    # ========================================================

    async def send_task(
        self,
        host: str,
        port: int,
        target_agent: str,
        task_type: str,
        payload: Dict[str, Any],
        auto_approve: bool = True,
    ) -> Dict[str, Any]:

        task = self.create_task(
            target=target_agent,
            task_type=task_type,
            payload=payload,
            auto_approved=auto_approve,
        )

        message = (
            self.build_a2a_task_message(
                task
            )
        )

        return await self.send_message(
            host,
            port,
            message,
        )

    # ========================================================
    # STATUS
    # ========================================================

    def status(self) -> Dict[str, Any]:

        wormhole = self.wormhole.last_result

        return {

            "system":
                "Universal TwinOS",

            "platform":
                platform.platform(),

            "python":
                sys.version,

            "twin":
                asdict(
                    self.identity
                ),

            "historical_events":
                len(
                    self.memory.events
                ),

            "dataset_records":
                len(
                    self.dataset.records
                ),

            "wormhole_active":
                wormhole is not None,

            "wormhole_confidence":
                (
                    wormhole.confidence
                    if wormhole
                    else 0.0
                ),

            "selected_event":
                (
                    wormhole.selected_event_id
                    if wormhole
                    else None
                ),

            "provenance_blocks":
                len(
                    self.provenance.chain
                ),

            "provenance_valid":
                self.provenance.verify(),

            "capabilities":
                self.capabilities()
                .capability_names(),
        }


# ============================================================
# DEMO DATA
# ============================================================

def load_demo_history(
    node: UniversalAgentNode,
):

    node.add_history(
        title="Summer evening",
        description=(
            "Outdoor evening with warm light, "
            "trees, people, conversation and music."
        ),
        tags=[
            "summer",
            "evening",
            "outdoors",
            "music",
        ],
        metadata={
            "environment":
                "outdoors",

            "time":
                "evening",
        },
    )

    node.add_history(
        title="Computer development session",
        description=(
            "Working on software architecture, "
            "code and AI development at a computer."
        ),
        tags=[
            "computer",
            "coding",
            "AI",
            "development",
        ],
        metadata={
            "environment":
                "computer",

            "activity":
                "development",
        },
    )

    node.add_history(
        title="Travel memory",
        description=(
            "Travel event involving roads, "
            "buildings, changing scenery and audio."
        ),
        tags=[
            "travel",
            "road",
            "audio",
        ],
        metadata={
            "activity":
                "travel",
        },
    )


# ============================================================
# CLI
# ============================================================

async def main():

    parser = argparse.ArgumentParser(
        description=
        "Universal TwinOS with EEG-Hormone Wormhole"
    )

    parser.add_argument(
        "--server",
        action="store_true",
        help="Start A2A network server",
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8765,
    )

    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run wormhole reconstruction demo",
    )

    parser.add_argument(
        "--status",
        action="store_true",
    )

    parser.add_argument(
        "--reconstruct",
        type=str,
        default=None,
        help="User guidance for reconstruction",
    )

    parser.add_argument(
        "--feedback",
        type=str,
        default=None,
    )

    parser.add_argument(
        "--discover",
        nargs=2,
        metavar=("HOST", "PORT"),
    )

    parser.add_argument(
        "--send",
        nargs=4,
        metavar=(
            "HOST",
            "PORT",
            "AGENT",
            "TASK",
        ),
    )

    parser.add_argument(
        "--ask",
        type=str,
        default=None,
        help="Send a prompt to a model provider via the coding agent",
    )

    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="Model provider name (see --providers)",
    )

    parser.add_argument(
        "--run",
        type=str,
        default=None,
        help="Run one local command through the terminal agent",
    )

    parser.add_argument(
        "--allow-terminal-network",
        action="store_true",
        help="Let authenticated network peers run terminal tasks",
    )

    parser.add_argument(
        "--anchors",
        type=str,
        default=None,
        help="JSON file: list of chains to anchor to "
             '[{"name","kind":"evm|esplora|json","url"}]',
    )

    parser.add_argument(
        "--providers",
        type=str,
        default=None,
        help="JSON file: {name: {kind, model, base_url, api_key_env}}",
    )

    args = parser.parse_args()

    config = Config(
        host=args.host,
        port=args.port,
    )

    config.allow_terminal_network = args.allow_terminal_network

    if args.anchors:
        with open(args.anchors, encoding="utf-8") as handle:
            config.chain_anchors = json.load(handle)

    if args.providers:
        with open(args.providers, encoding="utf-8") as handle:
            config.model_providers.update(json.load(handle))

    node = UniversalAgentNode(
        config
    )

    # --------------------------------------------------------
    # DEMO HISTORY
    # --------------------------------------------------------

    load_demo_history(node)

    # --------------------------------------------------------
    # STATUS
    # --------------------------------------------------------

    if args.status:

        print(
            json.dumps(
                node.status(),
                indent=2,
                default=str,
            )
        )

    # --------------------------------------------------------
    # RECONSTRUCTION
    # --------------------------------------------------------

    if args.reconstruct:

        result = node.reconstruct_event(
            args.reconstruct
        )

        output = {

            "wormhole_id":
                result[
                    "wormhole"
                ].wormhole_id,

            "confidence":
                result[
                    "wormhole"
                ].confidence,

            "selected_event":
                result[
                    "wormhole"
                ].selected_event_id,

            "matches": [

                {
                    "event_id":
                        match.event_id,

                    "score":
                        match.score,

                    "confidence":
                        match.confidence,

                    "evidence":
                        match.evidence,
                }

                for match
                in result[
                    "wormhole"
                ].matches
            ],

            "scene":
                result[
                    "wormhole"
                ].scene_state,

            "image":
                result["image"],

            "video":
                result["video"],
        }

        print(
            json.dumps(
                output,
                indent=2,
                default=str,
            )
        )

    # --------------------------------------------------------
    # FEEDBACK
    # --------------------------------------------------------

    if args.feedback:

        node.provide_feedback(
            args.feedback
        )

        print(
            "Feedback recorded."
        )

    # --------------------------------------------------------
    # DEMO
    # --------------------------------------------------------

    if args.demo:

        print(
            "\n=== EEG-HORMONE WORMHOLE DEMO ===\n"
        )

        result = node.reconstruct_event(
            user_guidance=(
                "I am thinking about "
                "an evening outdoors with "
                "music and trees."
            )
        )

        wormhole = result[
            "wormhole"
        ]

        print(
            "Wormhole:",
            wormhole.wormhole_id,
        )

        print(
            "Selected event:",
            wormhole.selected_event_id,
        )

        print(
            "Confidence:",
            wormhole.confidence,
        )

        print(
            "\nCandidate events:"
        )

        for match in wormhole.matches:

            print(
                " ",
                match.event_id,
                "score=",
                round(
                    match.score,
                    4,
                ),
                "confidence=",
                round(
                    match.confidence,
                    4,
                ),
            )

        print(
            "\nScene:"
        )

        print(
            json.dumps(
                wormhole.scene_state,
                indent=2,
            )
        )

        print(
            "\nGenerated image request:"
        )

        print(
            json.dumps(
                result["image"],
                indent=2,
            )
        )

        print(
            "\nGenerated video request:"
        )

        print(
            json.dumps(
                result["video"],
                indent=2,
            )
        )

    if args.run:

        task = node.create_task(
            "terminal",
            "terminal",
            {"command": args.run},
        )

        print(
            json.dumps(
                node.execute_task(task),
                indent=2,
                default=str,
            )
        )

    # --------------------------------------------------------
    # ASK ANY MODEL
    # --------------------------------------------------------

    if args.ask:

        task = node.create_task(
            "coding",
            "coding",
            {"prompt": args.ask, "provider": args.provider},
        )

        print(
            json.dumps(
                node.execute_task(task),
                indent=2,
                default=str,
            )
        )

    # --------------------------------------------------------
    # DISCOVER REMOTE AGENT
    # --------------------------------------------------------

    if args.discover:

        host = args.discover[0]
        port = int(
            args.discover[1]
        )

        message = UniversalA2A.message(
            node.identity,

            "remote",

            "IDENTITY_REQUEST",

            {},
        )

        response = await node.send_message(
            host,
            port,
            message,
        )

        print(
            json.dumps(
                response,
                indent=2,
                default=str,
            )
        )

    # --------------------------------------------------------
    # SEND TASK
    # --------------------------------------------------------

    if args.send:

        host = args.send[0]
        port = int(
            args.send[1]
        )

        agent = args.send[2]

        task_type = args.send[3]

        response = await node.send_task(
            host,
            port,
            agent,
            task_type,
            {
                "message":
                    "Task generated by Universal TwinOS",

                "wormhole_context":
                    node.wormhole_context_for_agent(
                        agent
                    ),
            },
        )

        print(
            json.dumps(
                response,
                indent=2,
                default=str,
            )
        )

    # --------------------------------------------------------
    # SERVER
    # --------------------------------------------------------

    if args.server:

        await node.start_server()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "\nUniversal TwinOS stopped."
        )