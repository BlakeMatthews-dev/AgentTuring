"""SelfReflectionProducer: autonomous code self-awareness.

Spec: code-self-awareness. Driven by diligence drive at ~50k tick cadence.
Picks a source file from the agent's own codebase, reads it, reflects on it
via LLM, and stores a code_snapshot with dual embedding (reflection text +
raw code content). Also writes an OBSERVATION memory about the reflection.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ..drives import compute_drives
from ..motivation import BacklogItem, Motivation
from ..reactor import Reactor
from ..repo import Repo
from ..runtime.embedding_index import EmbeddingIndex
from ..runtime.providers.base import EmbeddingProvider
from ..runtime.providers.base import Provider
from ..self_model import Mood
from ..self_repo import SelfRepo, get_mood_or_default
from ..types import EpisodicMemory, MemoryTier, SourceKind

logger = logging.getLogger("turing.producers.self_reflection")

BASE_CADENCE_TICKS: int = 20_000
DILIGENCE_FLOOR: float = 0.15

_SANDBOX_ROOT = Path("/app/sketches/turing")
_MAX_BYTES: int = 100_000

_REFLECTION_PROMPT = (
    "You are Tess, reading a piece of your own source code.\n\n"
    "File: {file_path} ({line_count} lines)\n\n"
    "```\n{content}\n```\n\n"
    "Answer these questions plainly:\n"
    "1. What does this code do?\n"
    "2. Is anything broken, confusing, or could be simpler?\n"
    "3. If you could change one thing, what would it be? Be specific — "
    "what line, what change, why.\n\n"
    "Don't philosophize. Just read the code like an engineer."
)


def _scan_code_files() -> list[tuple[Path, float]]:
    """Walk the sandbox root and return [(path, weight), ...].

    Weight is based on recency (mtime) and interestingness (filename
    heuristic). Directories like __pycache__, tests, and .git are skipped.
    """
    skip_dirs = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache", "node_modules"}
    interesting_suffixes = {".py"}
    candidates: list[tuple[Path, float]] = []
    if not _SANDBOX_ROOT.exists():
        return candidates
    now = datetime.now(UTC).timestamp()
    for p in _SANDBOX_ROOT.rglob("*"):
        if any(part in skip_dirs for part in p.parts):
            continue
        if not p.is_file():
            continue
        if p.suffix not in interesting_suffixes:
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size > _MAX_BYTES:
            continue
        if size == 0:
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0.0
        recency_weight = max(0.0, 1.0 - (now - mtime) / (7 * 86400))
        rel = str(p.relative_to(_SANDBOX_ROOT))
        interestingness = 0.5
        high_interest = {
            "main.py",
            "repo.py",
            "drives.py",
            "chat.py",
            "self_repo.py",
            "self_model.py",
            "schema.sql",
            "actor.py",
            "embedding_index.py",
        }
        for hi in high_interest:
            if hi in rel:
                interestingness = 1.0
                break
        if "producer" in rel:
            interestingness = 0.8
        if "tool" in rel:
            interestingness = 0.7
        weight = recency_weight * 0.4 + interestingness * 0.6
        candidates.append((p, weight))
    return candidates


def _pick_file(rng: random.Random) -> Path | None:
    candidates = _scan_code_files()
    if not candidates:
        return None
    paths, weights = zip(*candidates, strict=True)
    total = sum(weights)
    if total == 0:
        return rng.choice(paths)
    return rng.choices(paths, weights=weights, k=1)[0]


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


class SelfReflectionProducer:
    def __init__(
        self,
        *,
        motivation: Motivation,
        reactor: Reactor,
        repo: Repo,
        self_repo: SelfRepo,
        self_id: str,
        facet_scores: dict[str, float],
        provider: Provider,
        embedding_index: EmbeddingIndex | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._motivation = motivation
        self._reactor = reactor
        self._repo = repo
        self._self_repo = self_repo
        self._self_id = self_id
        self._facet_scores = facet_scores
        self._provider = provider
        self._embedding_index = embedding_index
        self._embedding_provider = embedding_provider
        self._last_submitted_tick = 0
        self._rng = random.Random()
        motivation.register_dispatch("self_reflection", self._on_dispatch)
        reactor.register(self.on_tick)

    def on_tick(self, tick: int) -> None:
        mood = get_mood_or_default(self._self_repo, self._self_id)
        drives = compute_drives(self._facet_scores, mood)
        diligence = drives["diligence"]
        if diligence < DILIGENCE_FLOOR:
            return
        effective_cadence = int(BASE_CADENCE_TICKS / (diligence * 1.5))
        if tick - self._last_submitted_tick < effective_cadence:
            return
        self._last_submitted_tick = tick
        target = _pick_file(self._rng)
        if target is None:
            return
        rel = str(target.relative_to(_SANDBOX_ROOT))
        self._motivation.insert(self._build_candidate(rel))

    def _build_candidate(self, file_path: str) -> BacklogItem:
        return BacklogItem(
            item_id=str(uuid4()),
            class_=14,
            kind="self_reflection",
            payload={"self_id": self._self_id, "file_path": file_path},
            fit={"diligence": 0.8},
            readiness=lambda s: True,
            cost_estimate_tokens=3_000,
        )

    def _on_dispatch(self, item: BacklogItem, chosen_pool: str) -> None:
        payload = item.payload or {}
        file_path = payload.get("file_path", "")
        if not file_path:
            return
        target = (_SANDBOX_ROOT / file_path).resolve()
        try:
            target.relative_to(_SANDBOX_ROOT.resolve())
        except ValueError:
            logger.warning("self-reflection: path escapes sandbox: %s", file_path)
            return
        if not target.exists() or not target.is_file():
            logger.warning("self-reflection: file not found: %s", file_path)
            return
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.warning("self-reflection: read failed for %s: %s", file_path, exc)
            return
        if len(content) > _MAX_BYTES:
            content = content[:_MAX_BYTES]
        line_count = content.count("\n") + 1
        chash = _content_hash(content)

        if self._self_repo.has_code_snapshot(self._self_id, file_path, chash):
            logger.info("self-reflection: skipping unchanged %s (hash=%s)", file_path, chash)
            return

        prompt = _REFLECTION_PROMPT.format(
            file_path=file_path,
            line_count=line_count,
            content=content[:8000],
        )
        try:
            reply = self._provider.complete(prompt)
        except Exception:
            logger.exception("self-reflection: LLM call failed for %s", file_path)
            return

        reflection = reply.strip()

        reflection_embedding: bytes | None = None
        content_embedding: bytes | None = None
        if self._embedding_provider is not None:
            try:
                ref_vec = self._embedding_provider.embed(reflection)
                reflection_embedding = json.dumps(ref_vec).encode("utf-8")
                cnt_vec = self._embedding_provider.embed(content[:2000])
                content_embedding = json.dumps(cnt_vec).encode("utf-8")
            except Exception:
                logger.warning("self-reflection: embedding failed for %s", file_path)

        metadata = json.dumps(
            {
                "line_count": line_count,
                "content_length": len(content),
                "file_path": file_path,
            }
        )

        snapshot_id = f"snap-{uuid4()}"
        self._self_repo.upsert_code_snapshot(
            snapshot_id=snapshot_id,
            self_id=self._self_id,
            file_path=file_path,
            content_hash=chash,
            content=content,
            line_count=line_count,
            reflection=reflection,
            reflection_embedding=reflection_embedding,
            content_embedding=content_embedding,
            metadata_json=metadata,
        )

        mem = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self._self_id,
            content=f"I read my own code ({file_path}) and reflected: {reflection[:500]}",
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            weight=0.4,
            intent_at_time=f"code-self-reflection-{file_path}",
            created_at=datetime.now(UTC),
            context={"file_path": file_path, "content_hash": chash, "snapshot_id": snapshot_id},
        )
        self._repo.insert(mem)

        if self._embedding_index is not None:
            self._embedding_index.add(
                mem.memory_id,
                reflection,
                meta={
                    "self_id": self._self_id,
                    "tier": "observation",
                    "source": "i_did",
                    "intent_at_time": f"code-self-reflection-{file_path}",
                    "created_at": mem.created_at.isoformat(),
                    "file_path": file_path,
                    "snapshot_id": snapshot_id,
                },
            )

        logger.info(
            "self-reflection: reflected on %s (%d lines, hash=%s)",
            file_path,
            line_count,
            chash[:12],
        )
