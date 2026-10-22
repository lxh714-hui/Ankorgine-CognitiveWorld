"""Bounded, disposable semantic candidate retrieval over authorized Memory IDs.

An embedding is a ranking hint. This module has no Event-anchor issuer, write
authority, persistent index, or built-in network provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import math
from typing import Protocol

from cognitive_world.cognition.memory_retrieval import (
    MAX_MEMORY_QUERY_RESULTS,
    MemoryQuery,
    MemoryRetriever,
    MemorySnapshot,
    _text_values,
)
from cognitive_world.cognition.memory_store import MemoryStore


MAX_SEMANTIC_SCAN_IDS = 64
MAX_EMBEDDING_DIMENSIONS = 4096
MAX_SEMANTIC_TEXT_CHARS = 4096
MAX_SEMANTIC_QUERY_CHARS = 512
MAX_EMBEDDING_BATCH = 16


class EmbeddingProvider(Protocol):
    """Host-injected text embedding operation; no transport is implied."""

    def embed(self, text: str) -> tuple[float, ...]: ...


def _unit_vector(value: object, *, dimension: int | None = None) -> tuple[float, ...]:
    if not isinstance(value, tuple) or not value or len(value) > MAX_EMBEDDING_DIMENSIONS or (
        dimension is not None and len(value) != dimension
    ):
        raise ValueError("embedding dimension is invalid")
    if any(type(item) not in (float, int) or not math.isfinite(item) for item in value):
        raise ValueError("embedding contains an invalid coordinate")
    magnitude = math.sqrt(sum(float(item) ** 2 for item in value))
    if not math.isfinite(magnitude) or magnitude == 0:
        raise ValueError("embedding has no finite direction")
    return tuple(float(item) / magnitude for item in value)


def _search_text(memory: object) -> str:
    return " ".join(_text_values(memory.content))[:MAX_SEMANTIC_TEXT_CHARS]


@dataclass(frozen=True)
class _IndexedMemory:
    memory_id: str
    source_event: str
    text_sha256: str
    vector: tuple[float, ...]


@dataclass(frozen=True)
class SemanticCandidate:
    """A rechecked canonical snapshot with a similarity ranking signal."""

    memory: MemorySnapshot
    similarity: float


@dataclass(frozen=True)
class MemorySemanticIndex:
    """Query-local index rebuilt from the current Character-linked records."""

    owner_id: str
    entries: tuple[_IndexedMemory, ...]
    dimension: int

    @classmethod
    def rebuild(
        cls,
        *,
        store: MemoryStore,
        owner_id: str,
        allowed_memory_ids: tuple[str, ...],
        provider: EmbeddingProvider,
        scan_limit: int = MAX_SEMANTIC_SCAN_IDS,
    ) -> MemorySemanticIndex:
        if not isinstance(owner_id, str) or not owner_id:
            raise ValueError("owner_id must be non-empty")
        if not isinstance(allowed_memory_ids, tuple) or any(
            not isinstance(item, str) or not item for item in allowed_memory_ids
        ):
            raise TypeError("allowed_memory_ids must contain Memory IDs")
        if type(scan_limit) is not int or not 1 <= scan_limit <= MAX_SEMANTIC_SCAN_IDS:
            raise ValueError("semantic scan limit is invalid")
        if not callable(getattr(provider, "embed", None)):
            raise TypeError("embedding provider must implement embed(text)")

        eligible: list[tuple[object, str]] = []
        for memory_id in tuple(dict.fromkeys(allowed_memory_ids))[:scan_limit]:
            memory = store.get_memory(memory_id)
            if (
                memory is None
                or memory.owner_id != owner_id
                or not MemoryStore.is_semantically_retrievable(memory)
                or not isinstance(memory.source_event, str)
                or not memory.source_event
            ):
                continue
            text = _search_text(memory)
            if text:
                eligible.append((memory, text))

        # Batching is an optional optimization of the existing embed(text)
        # contract. It never receives records beyond the authorized scan.
        batch = getattr(provider, "embed_many", None)
        vectors: list[tuple[float, ...]] = []
        if callable(batch):
            batch_limit = getattr(provider, "batch_size", MAX_EMBEDDING_BATCH)
            if type(batch_limit) is not int or not 1 <= batch_limit <= MAX_EMBEDDING_BATCH:
                raise ValueError("embedding batch size is invalid")
            for start in range(0, len(eligible), batch_limit):
                texts = tuple(text for _, text in eligible[start:start + batch_limit])
                returned = batch(texts)
                if not isinstance(returned, tuple) or len(returned) != len(texts):
                    raise ValueError("embedding batch response count is invalid")
                vectors.extend(returned)
        else:
            vectors = [provider.embed(text) for _, text in eligible]

        entries: list[_IndexedMemory] = []
        dimension: int | None = None
        for (memory, text), raw_vector in zip(eligible, vectors, strict=True):
            if (
                isinstance(raw_vector, tuple)
                and raw_vector
                and all(type(item) in (float, int) and item == 0 for item in raw_vector)
            ):
                if dimension is not None and len(raw_vector) != dimension:
                    raise ValueError("embedding dimension is invalid")
                continue
            vector = _unit_vector(raw_vector, dimension=dimension)
            dimension = len(vector)
            entries.append(_IndexedMemory(
                memory.id,
                memory.source_event,
                sha256(text.encode("utf-8")).hexdigest(),
                vector,
            ))
        return cls(owner_id, tuple(entries), dimension or 0)

    def candidates(
        self,
        query: MemoryQuery,
        *,
        store: MemoryStore,
        allowed_memory_ids: tuple[str, ...],
        provider: EmbeddingProvider,
        limit: int = MAX_MEMORY_QUERY_RESULTS,
        minimum_similarity: float = 0.5,
    ) -> tuple[SemanticCandidate, ...]:
        if query.owner_id != self.owner_id:
            raise PermissionError("semantic index belongs to another owner")
        if type(limit) is not int or not 1 <= limit <= MAX_MEMORY_QUERY_RESULTS:
            raise ValueError("semantic candidate limit is invalid")
        if not isinstance(minimum_similarity, (float, int)) or not 0 <= minimum_similarity <= 1:
            raise ValueError("semantic similarity threshold is invalid")
        if not self.entries:
            return ()
        query_vector = _unit_vector(
            provider.embed(query.query[:MAX_SEMANTIC_QUERY_CHARS]),
            dimension=self.dimension,
        )
        authorized = set(allowed_memory_ids)
        ranked = sorted(
            (
                (sum(a * b for a, b in zip(query_vector, entry.vector, strict=True)), entry)
                for entry in self.entries
                if entry.memory_id in authorized
            ),
            key=lambda item: (-item[0], item[1].memory_id),
        )
        results: list[SemanticCandidate] = []
        for similarity, entry in ranked:
            if similarity < minimum_similarity:
                break
            # Index entries only locate candidates. Re-read current canonical
            # content and authorization before returning a detached snapshot.
            memory = store.get_memory(entry.memory_id)
            if (
                memory is None
                or memory.owner_id != self.owner_id
                or memory.id not in authorized
                or not MemoryStore.is_semantically_retrievable(memory)
                or memory.source_event != entry.source_event
                or sha256(_search_text(memory).encode("utf-8")).hexdigest()
                != entry.text_sha256
            ):
                continue
            results.append(SemanticCandidate(MemorySnapshot.from_memory(memory), similarity))
            if len(results) >= limit:
                break
        return tuple(results)


@dataclass
class HybridMemoryRetriever:
    """Keep lexical order and fill remaining slots with semantic candidates.

    The existing Event association channel in AgentTurn merges after these
    results. A provider failure drops only this optional semantic channel.
    """

    store: MemoryStore
    embedding_provider: EmbeddingProvider
    semantic_scan_limit: int = MAX_SEMANTIC_SCAN_IDS
    semantic_candidate_limit: int = MAX_MEMORY_QUERY_RESULTS
    minimum_similarity: float = 0.5
    runtime_fence: object | None = None
    _runtime_binding: tuple[str, int] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.runtime_fence is not None:
            self._runtime_binding = (
                self.runtime_fence.session_id,
                self.runtime_fence.restore_generation,
            )

    def retrieve(
        self, query: MemoryQuery, *, allowed_memory_ids: tuple[str, ...]
    ) -> tuple[MemorySnapshot, ...]:
        lexical = MemoryRetriever(self.store).retrieve(
            query, allowed_memory_ids=allowed_memory_ids,
        )
        if len(lexical) >= min(query.limit, MAX_MEMORY_QUERY_RESULTS):
            return lexical
        generation = self._runtime_binding
        if self.runtime_fence is not None:
            current = (
                self.runtime_fence.session_id,
                self.runtime_fence.restore_generation,
            )
            if generation != current:
                return lexical
        try:
            index = MemorySemanticIndex.rebuild(
                store=self.store,
                owner_id=query.owner_id,
                allowed_memory_ids=allowed_memory_ids,
                provider=self.embedding_provider,
                scan_limit=self.semantic_scan_limit,
            )
            semantic = index.candidates(
                query,
                store=self.store,
                allowed_memory_ids=allowed_memory_ids,
                provider=self.embedding_provider,
                limit=self.semantic_candidate_limit,
                minimum_similarity=self.minimum_similarity,
            )
            if generation is not None and generation != (
                self.runtime_fence.session_id,
                self.runtime_fence.restore_generation,
            ):
                return lexical
        except Exception:
            # Timeout, model failure, malformed vectors, or a changed Runtime
            # cannot remove already authorized lexical results.
            return lexical
        combined = list(lexical)
        seen = {memory.id for memory in lexical}
        for candidate in semantic:
            if candidate.memory.id not in seen:
                combined.append(candidate.memory)
                seen.add(candidate.memory.id)
            if len(combined) >= min(query.limit, MAX_MEMORY_QUERY_RESULTS):
                break
        return tuple(combined)
