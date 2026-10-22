"""Owner-scoped, explainable retrieval over the canonical MemoryStore."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import groupby
import math
import re
from types import MappingProxyType
from typing import Any

from cognitive_world.cognition.memory import Memory
from cognitive_world.cognition.memory_store import MemoryStore


MAX_MEMORY_QUERY_RESULTS = 5


def _freeze(value: Any) -> Any:
    """Copy the JSON-like Memory payload into recursively immutable values."""
    if value is None or isinstance(value, (str, bytes, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({_freeze(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, dict):
        return MappingProxyType(
            {name: _freeze(item) for name, item in attributes.items() if not name.startswith("_")}
        )
    raise TypeError(f"unsupported Memory payload value: {type(value).__name__}")


def _frozen_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return _freeze(value)


@dataclass(frozen=True)
class MemoryQuery:
    """Describe an owner-scoped request for relevant Memory records.

    ``query`` is derived from current Percepts, Goals, Beliefs, or an explicit
    turn-local MetacognitiveFeedback request. Metadata is retained for
    compatibility and diagnostics but is never interpreted as authority.
    """

    owner_id: str
    query: str
    limit: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.owner_id, str) or not self.owner_id:
            raise ValueError("owner_id must be non-empty")
        if not isinstance(self.query, str):
            raise TypeError("query must be a string")
        if not isinstance(self.limit, int) or isinstance(self.limit, bool) or self.limit < 1:
            raise ValueError("limit must be a positive integer")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        object.__setattr__(self, "metadata", _frozen_mapping(self.metadata))

    def __deepcopy__(self, memo: dict[int, Any]) -> "MemoryQuery":
        return self


@dataclass(frozen=True)
class MemorySnapshot:
    """Detached read-only Memory result retaining its complete source Event ID."""

    id: str
    owner_id: str
    type: str
    content: Any
    importance: Any
    source_event: str
    metadata: Mapping[str, Any]

    def __deepcopy__(self, memo: dict[int, Any]) -> "MemorySnapshot":
        return self

    @classmethod
    def from_memory(cls, memory: Memory) -> "MemorySnapshot":
        if not MemoryStore.is_semantically_retrievable(memory):
            raise PermissionError("system-only Memory cannot become a semantic snapshot")
        return cls(
            id=memory.id,
            owner_id=memory.owner_id,
            type=memory.type,
            content=_freeze(memory.content),
            importance=memory.importance,
            source_event=memory.source_event,
            metadata=_frozen_mapping(memory.metadata),
        )


def _text_values(value: Any) -> list[str]:
    """Extract only explicit textual values/keys; never use object repr text."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        parts: list[str] = []
        for key, item in value.items():
            parts.extend(_text_values(key))
            parts.extend(_text_values(item))
        return parts
    if isinstance(value, (tuple, list, set, frozenset)):
        return [part for item in value for part in _text_values(item)]
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, dict):
        return [
            part
            for name, item in attributes.items()
            if not name.startswith("_")
            for part in _text_values(item)
        ]
    return []


def _tokens(text: str) -> frozenset[str]:
    """Use deterministic word and CJK bigram tokens for simple lexical match."""
    tokens: set[str] = set()
    for word in re.findall(r"[\w]+", text.casefold(), flags=re.UNICODE):
        tokens.add(word)
        if any("\u3400" <= char <= "\u9fff" for char in word):
            tokens.update(word[index : index + 2] for index in range(len(word) - 1))
    return frozenset(token for token in tokens if token)


def _importance_tiebreak(memory: Memory) -> float | None:
    """Return the existing importance only when it is a valid finite number."""
    value = getattr(memory, "importance", None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


@dataclass
class MemoryRetriever:
    """Retrieve character-authorized owner memories without mutating storage.

    The caller must pass IDs taken from the current Character reference list.
    CognitionContext supplies and rechecks those IDs and the Agent owner. The
    retriever ranks by lexical overlap, then valid stored importance only when
    every candidate in that relevance-tie group has it, then stable ID;
    importance is a tie-break only and never a truth/confidence estimate.
    """

    memory_store: MemoryStore

    def retrieve(
        self, query: MemoryQuery, *, allowed_memory_ids: tuple[str, ...]
    ) -> tuple[MemorySnapshot, ...]:
        if not isinstance(query, MemoryQuery):
            raise TypeError("query must be a MemoryQuery")
        if not isinstance(allowed_memory_ids, tuple) or any(
            not isinstance(memory_id, str) or not memory_id
            for memory_id in allowed_memory_ids
        ):
            raise TypeError("allowed_memory_ids must be a tuple of Memory IDs")

        query_tokens = _tokens(query.query)
        ranked: list[tuple[int, float | None, str, Memory]] = []
        for memory_id in dict.fromkeys(allowed_memory_ids):
            memory = self.memory_store.get_memory(memory_id)
            if (
                memory is None
                or memory.owner_id != query.owner_id
                or not MemoryStore.is_semantically_retrievable(memory)
                or not isinstance(memory.source_event, str)
                or not memory.source_event
            ):
                continue
            content_tokens = _tokens(" ".join(_text_values(memory.content)))
            overlap = len(query_tokens & content_tokens)
            if overlap == 0:
                continue
            ranked.append((overlap, _importance_tiebreak(memory), memory.id, memory))

        ranked.sort(key=lambda item: (-item[0], item[2]))
        ordered: list[tuple[int, float | None, str, Memory]] = []
        for _, tied in groupby(ranked, key=lambda item: item[0]):
            relevance_tie = list(tied)
            if all(item[1] is not None for item in relevance_tie):
                relevance_tie.sort(key=lambda item: (-item[1], item[2]))
            # If any tied item lacks a valid importance value, fall back for
            # the whole tie group to ID order instead of inventing a score.
            ordered.extend(relevance_tie)
        return tuple(
            MemorySnapshot.from_memory(memory)
            for _, _, _, memory in ordered[: min(query.limit, MAX_MEMORY_QUERY_RESULTS)]
        )
