"""EmbeddingIndex: in-memory cosine-similarity search over memory vectors.

Pure Python, no numpy. Fine for O(10k) memories; revisit if the branch ever
goes beyond that.

Storage: {memory_id: vector}. Rebuilt on startup by re-embedding every
I_DID memory (cheap for a research box, and keeps the store self-contained
— no separate vector database to sync).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from typing import Any


logger = logging.getLogger("turing.embedding_index")


EmbedFn = Callable[[str], list[float]]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class EmbeddingIndex:
    """Mutable, thread-safe, in-memory vector index."""

    def __init__(self, *, embed_fn: EmbedFn) -> None:
        self._embed_fn = embed_fn
        self._by_id: dict[str, list[float]] = {}
        self._meta: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def size(self) -> int:
        with self._lock:
            return len(self._by_id)

    def add(self, memory_id: str, text: str, *, meta: dict[str, Any] | None = None) -> None:
        vec = self._embed_with_retry(text, memory_id)
        if vec is None:
            return
        with self._lock:
            self._by_id[memory_id] = vec
            if meta is not None:
                self._meta[memory_id] = dict(meta)

    def _embed_with_retry(
        self, text: str, label: str, *, max_retries: int = 2
    ) -> list[float] | None:
        delays = [1.0, 4.0]
        for attempt in range(max_retries + 1):
            try:
                return self._embed_fn(text)
            except Exception:
                if attempt < max_retries:
                    wait = delays[attempt]
                    logger.warning(
                        "embed failed for %s; retrying in %.0fs (attempt %d/%d)",
                        label,
                        wait,
                        attempt + 1,
                        max_retries,
                    )
                    time.sleep(wait)
                else:
                    logger.exception(
                        "embed failed for %s after %d retries; skipping", label, max_retries
                    )
                    return None

    def remove(self, memory_id: str) -> None:
        with self._lock:
            self._by_id.pop(memory_id, None)
            self._meta.pop(memory_id, None)

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        filter_fn: Callable[[dict[str, Any]], bool] | None = None,
    ) -> list[tuple[str, float, dict[str, Any]]]:
        """Return `[(memory_id, similarity, meta), ...]` top-K by cosine."""
        try:
            q = self._embed_fn(query)
        except Exception:
            logger.exception("embed failed for query; returning empty")
            return []
        with self._lock:
            items = list(self._by_id.items())
            meta = dict(self._meta)
        scored: list[tuple[str, float, dict[str, Any]]] = []
        for mid, vec in items:
            m = meta.get(mid, {})
            if filter_fn is not None and not filter_fn(m):
                continue
            scored.append((mid, _cosine(q, vec), m))
        scored.sort(key=lambda t: -t[1])
        return scored[:top_k]
