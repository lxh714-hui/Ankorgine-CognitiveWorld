"""Disposable Event-to-Memory candidate locators over verified canonical data.

AgentTurn uses this channel only when Runtime supplies its verified history
context and the current turn contains a matching, L1-consumed Observation.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Literal, Mapping

from cognitive_world.cognition.memory import Memory
from cognitive_world.cognition.memory_retrieval import (
    MAX_MEMORY_QUERY_RESULTS,
    MemorySnapshot,
)
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.core.persistence import PersistedValueCodec, PersistenceTrust
from cognitive_world.event.history import EventHistory
from cognitive_world.observation.observation import Observation
from cognitive_world.observation.observable import ObservableFact


_INDEX_ISSUER = object()


@dataclass(frozen=True, init=False)
class VerifiedEventAnchor:
    """One-turn anchor reconstructed from a consumed trusted Observation.

    Anchors are issued by a particular rebuilt index and cannot be reused by
    another index generation. They locate candidates only; they are not facts.
    """

    owner_id: str
    observation_id: str
    observation_sha256: str
    event_id: str
    timeline_id: str
    source_timeline_id: str
    event_tick: int | None
    _issuer: object

    def __init__(self, *, owner_id: str, observation_id: str,
                 observation_sha256: str, event_id: str, timeline_id: str,
                 source_timeline_id: str, event_tick: int | None,
                 _issuer: object) -> None:
        if _issuer is None:
            raise PermissionError("VerifiedEventAnchor must be issued by a verified index")
        for name, value in (("owner_id", owner_id), ("observation_id", observation_id),
                            ("observation_sha256", observation_sha256),
                            ("event_id", event_id), ("timeline_id", timeline_id),
                            ("source_timeline_id", source_timeline_id)):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty")
            object.__setattr__(self, name, value)
        if event_tick is not None and (type(event_tick) is not int or event_tick < 0):
            raise ValueError("event_tick must be a non-negative integer or None")
        object.__setattr__(self, "event_tick", event_tick)
        object.__setattr__(self, "_issuer", _issuer)


@dataclass(frozen=True)
class MemoryEventLink:
    """A candidate locator retaining its verified Event's source and time."""

    memory_id: str
    source_event_id: str
    event_timestamp: str
    simulation_tick: int | None
    history_position: int
    evidence_status: Literal["verified_persisted_event_history"]


@dataclass(frozen=True)
class MemoryEventCandidate:
    """Canonical Memory snapshot paired with its discovery-only Event link."""

    memory: MemorySnapshot
    link: MemoryEventLink


@dataclass(frozen=True, init=False)
class MemoryEventIndex:
    """Rebuildable reverse locator scoped to one CognitionContext.

    Presence in this structure means the source Event was returned by
    ``verify_persisted_lineage`` during this build. It is not a transferable
    credential, proof of a causal relation, or grant to read the Memory.
    Rebuild after canonical Store or EventHistory changes.
    """

    owner_id: str
    memory_store: MemoryStore
    authorized_memory_ids: frozenset[str]
    verified_event_ids: frozenset[str]
    _event_to_links: Mapping[str, tuple[MemoryEventLink, ...]]
    event_history: EventHistory
    timeline_id: str
    runtime_fence: object | None
    runtime_session_id: str | None
    runtime_generation: int | None
    _event_records: Mapping[str, tuple[object, object, str]]
    _history_fingerprint: str
    _anchor_issuer: object

    def __init__(
        self,
        *,
        owner_id: str,
        memory_store: MemoryStore,
        authorized_memory_ids: frozenset[str],
        verified_event_ids: frozenset[str],
        event_to_links: Mapping[str, tuple[MemoryEventLink, ...]],
        event_history: EventHistory | None = None,
        timeline_id: str = "",
        runtime_fence: object | None = None,
        event_records: Mapping[str, tuple[object, object, str]] | None = None,
        history_fingerprint: str = "",
        _issuer: object = None,
    ) -> None:
        if _issuer is not _INDEX_ISSUER:
            raise PermissionError("MemoryEventIndex must be built from a verified EventHistory")
        if type(event_history) is not EventHistory or not isinstance(timeline_id, str) or not timeline_id:
            raise PermissionError("MemoryEventIndex has no verified EventHistory binding")
        from cognitive_world.runtime.write_fence import RuntimeWriteFence

        if runtime_fence is not None and type(runtime_fence) is not RuntimeWriteFence:
            raise TypeError("runtime_fence must be the canonical RuntimeWriteFence")
        object.__setattr__(self, "owner_id", owner_id)
        object.__setattr__(self, "memory_store", memory_store)
        object.__setattr__(self, "authorized_memory_ids", authorized_memory_ids)
        object.__setattr__(self, "verified_event_ids", verified_event_ids)
        object.__setattr__(self, "event_history", event_history)
        object.__setattr__(self, "timeline_id", timeline_id)
        object.__setattr__(self, "runtime_fence", runtime_fence)
        object.__setattr__(
            self, "runtime_session_id",
            None if runtime_fence is None else runtime_fence.session_id,
        )
        object.__setattr__(
            self, "runtime_generation",
            None if runtime_fence is None else runtime_fence.restore_generation,
        )
        object.__setattr__(self, "_event_records", MappingProxyType(dict(event_records or {})))
        object.__setattr__(self, "_history_fingerprint", history_fingerprint)
        object.__setattr__(self, "_anchor_issuer", object())
        object.__setattr__(
            self,
            "_event_to_links",
            MappingProxyType({key: tuple(value) for key, value in event_to_links.items()}),
        )

    @classmethod
    def rebuild_for_context(
        cls,
        context: CognitionContext,
        event_history: EventHistory,
        *,
        codec: PersistedValueCodec,
        trust: PersistenceTrust,
        runtime_fence: object | None = None,
    ) -> "MemoryEventIndex":
        """Rebuild links only from this Character's canonical Memory IDs.

        The complete EventHistory lineage is verified before any link is made.
        The builder reads no Memory outside ``context``'s frozen Character ID
        set and stores identifiers only, never copied Memory content.
        """
        from cognitive_world.agent.cognition_context import CognitionContext

        if not isinstance(context, CognitionContext):
            raise TypeError("context must be a CognitionContext")
        if type(event_history) is not EventHistory:
            raise TypeError("event_history must be the canonical EventHistory")
        if not isinstance(codec, PersistedValueCodec):
            raise TypeError("codec must be PersistedValueCodec")

        verified_events, verified_evidence, attestations = event_history.verify_persisted_lineage(
            codec=codec, trust=trust,
        )
        event_by_id = {event.id: (position, event) for position, event in enumerate(verified_events)}
        if len(event_by_id) != len(verified_events):
            raise PermissionError("verified EventHistory contains duplicate Event identities")
        if not (len(verified_events) == len(verified_evidence) == len(attestations)):
            raise PermissionError("verified EventHistory result is internally inconsistent")
        event_records = {
            event.id: (event, evidence, attestation["timeline_id"])
            for event, evidence, attestation in zip(
                verified_events, verified_evidence, attestations, strict=True
            )
        }
        history_fingerprint = cls._fingerprint_history(event_history)

        allowed_ids = frozenset(context._memory_ids)
        event_to_links: dict[str, list[MemoryEventLink]] = {}
        for memory_id in dict.fromkeys(context._memory_ids):
            memory = context.memory_store.get_memory(memory_id)
            if (
                type(memory) is not Memory
                or memory.owner_id != context.owner_id
                or not MemoryStore.is_semantically_retrievable(memory)
                or not isinstance(memory.source_event, str)
                or not memory.source_event
            ):
                continue
            verified = event_by_id.get(memory.source_event)
            if verified is None:
                continue
            position, event = verified
            event_to_links.setdefault(event.id, []).append(
                MemoryEventLink(
                    memory.id,
                    event.id,
                    event.timestamp,
                    event.simulation_tick,
                    position,
                    "verified_persisted_event_history",
                )
            )

        return cls(
            owner_id=context.owner_id,
            memory_store=context.memory_store,
            authorized_memory_ids=allowed_ids,
            verified_event_ids=frozenset(event_by_id),
            event_to_links={
                event_id: tuple(sorted(links, key=lambda link: link.memory_id))
                for event_id, links in event_to_links.items()
            },
            event_history=event_history,
            timeline_id=event_history.timeline_id,
            runtime_fence=runtime_fence,
            event_records=event_records,
            history_fingerprint=history_fingerprint,
            _issuer=_INDEX_ISSUER,
        )

    @staticmethod
    def _fingerprint_history(history: EventHistory) -> str:
        records = history.export_persisted_records()
        digest = sha256()
        for record in records:
            components = (
                str(record.version).encode("ascii"), record.event_payload,
                record.processing_evidence_payload, record.attestation_payload,
                record.signature,
            )
            for component in components:
                digest.update(len(component).to_bytes(8, "big"))
                digest.update(component)
        return digest.hexdigest()

    def verified_observation_anchors(
        self,
        context: CognitionContext,
        observations: tuple[Observation, ...],
        *,
        consumed_percepts: tuple[object, ...],
        cognitive_runtime: object,
    ) -> tuple[VerifiedEventAnchor, ...]:
        """Issue ephemeral anchors only for this turn's verified L1 inputs.

        The Event must belong to the completely verified current EventHistory
        ancestry. The Observation must retain its issuer receipt, match the
        verified Event/evidence typed fact, and have crossed this AgentTurn's
        L1 path. Unsupported historical visibility rules produce no anchor.
        """
        self._validate_context(context)
        if not isinstance(observations, tuple) or not isinstance(consumed_percepts, tuple):
            raise TypeError("observations and consumed_percepts must be tuples")
        from cognitive_world.cognition.runtime import CognitiveRuntime

        if type(cognitive_runtime) is not CognitiveRuntime:
            raise TypeError("anchors require the canonical CognitiveRuntime L1 receipt")
        if self.runtime_fence is None:
            return ()
        consumed = {
            (item.observer_id, item.source_observation_id)
            for item in consumed_percepts
            if getattr(item, "observer_id", None) == context.owner_id
            and isinstance(getattr(item, "source_observation_id", None), str)
        }
        anchors: list[VerifiedEventAnchor] = []
        seen: set[str] = set()
        for observation in observations:
            record = (
                self._event_records.get(observation.source_event_id)
                if isinstance(observation, Observation) else None
            )
            if (
                not isinstance(observation, Observation)
                or observation.observer_id != context.owner_id
                or not observation.has_trusted_provenance()
                or record is None
                or observation.trusted_source_timeline_id() != record[2]
                or observation.trusted_source_runtime_binding() != (
                    self.runtime_session_id, self.runtime_generation,
                )
                or (context.owner_id, observation.observation_id) not in consumed
                or not cognitive_runtime.has_consumed_observation(
                    context.owner_id, observation,
                    source_event_id=observation.source_event_id,
                )
                or observation.source_event_id in seen
            ):
                continue
            fact = observation.content
            if type(fact) is not ObservableFact:
                continue
            event, evidence, source_timeline_id = record
            if (
                event.id != observation.source_event_id
                or fact.source_event_id != event.id
                or not event.has_trusted_source()
                or not evidence.has_trusted_source(event)
                or not fact.has_trusted_source(event)
                or not any(
                    item.fact_id == fact.fact_id
                    and item._snapshot() == fact._snapshot()
                    and item.has_trusted_source(event)
                    for item in evidence.observable_facts
                )
            ):
                continue
            if not self._matches_registered_observation(event, evidence, observation):
                continue
            snapshot = observation._snapshot()
            try:
                from cognitive_world.core.persistence import PersistedValueCodec

                digest = sha256(PersistedValueCodec().dumps(snapshot)).hexdigest()
            except (TypeError, ValueError):
                continue
            anchors.append(VerifiedEventAnchor(
                owner_id=context.owner_id,
                observation_id=observation.observation_id,
                observation_sha256=digest,
                event_id=event.id,
                timeline_id=self.timeline_id,
                source_timeline_id=source_timeline_id,
                event_tick=event.simulation_tick,
                _issuer=self._anchor_issuer,
            ))
            seen.add(event.id)
        return tuple(anchors)

    @staticmethod
    def _matches_registered_observation(
        event: object, evidence: object, observation: Observation,
    ) -> bool:
        """Reconstruct supported visibility rules; never trust an Event ID alone."""
        try:
            from cognitive_world.observation.historical_rules import HISTORICAL_OBSERVATION_RULES

            rule = HISTORICAL_OBSERVATION_RULES.for_source(event, evidence)
            if rule is not None:
                expected = rule.issue(
                    event, evidence, observation.observer_id, observation.content.fact_id
                )
            elif event.type == "dialogue_input":
                from cognitive_world.cognition.l1_consumption_proof import (
                    _issued_utterance_observation,
                )

                expected = _issued_utterance_observation(
                    event, evidence, observation.observer_id,
                    observation.content.fact_id,
                )
            else:
                return False
            return (
                type(expected) is Observation
                and expected._snapshot() == observation._snapshot()
            )
        except (PermissionError, TypeError, ValueError, AttributeError):
            return False

    def resolve_anchor_candidates(
        self,
        context: CognitionContext,
        anchors: tuple[VerifiedEventAnchor, ...],
        *,
        limit: int = MAX_MEMORY_QUERY_RESULTS,
    ) -> tuple[MemoryEventCandidate, ...]:
        """Resolve only anchors issued by this exact index generation."""
        self._validate_context(context)
        if not isinstance(anchors, tuple):
            raise TypeError("anchors must be a tuple")
        try:
            current_history_fingerprint = self._fingerprint_history(self.event_history)
        except Exception as error:
            raise PermissionError(
                "EventHistory changed after the retrieval index was verified"
            ) from error
        if (self.event_history.timeline_id != self.timeline_id
                or current_history_fingerprint != self._history_fingerprint):
            raise PermissionError("EventHistory changed after the retrieval index was verified")
        if ((self.runtime_fence is not None
             and (self.runtime_fence.session_id != self.runtime_session_id
                  or self.runtime_fence.restore_generation != self.runtime_generation))
                or (anchors and self.runtime_fence is None)):
            raise PermissionError("Runtime generation changed after the retrieval index was verified")
        results: list[MemoryEventCandidate] = []
        seen: set[str] = set()
        for anchor in anchors:
            if (
                type(anchor) is not VerifiedEventAnchor
                or anchor._issuer is not self._anchor_issuer
                or anchor.owner_id != context.owner_id
                or anchor.timeline_id != self.timeline_id
                or anchor.event_id not in self.verified_event_ids
                or anchor.event_id in seen
            ):
                continue
            seen.add(anchor.event_id)
            for candidate in self.resolve_event_candidates(
                context, anchor.event_id,
                limit=max(1, min(limit, MAX_MEMORY_QUERY_RESULTS) - len(results)),
            ):
                if candidate.memory.id not in {item.memory.id for item in results}:
                    results.append(candidate)
                if len(results) >= min(limit, MAX_MEMORY_QUERY_RESULTS):
                    return tuple(results)
        return tuple(results)

    def candidate_links(
        self,
        context: CognitionContext,
        event_id: str | None,
        *,
        limit: int = MAX_MEMORY_QUERY_RESULTS,
    ) -> tuple[MemoryEventLink, ...]:
        """Return bounded links only for a verified Event and current scope."""
        self._validate_context(context)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")
        if not isinstance(event_id, str) or event_id not in self.verified_event_ids:
            return ()
        current_ids = set(context._memory_ids) & self.authorized_memory_ids
        return tuple(
            link
            for link in self._event_to_links.get(event_id, ())
            if link.memory_id in current_ids
        )[: min(limit, MAX_MEMORY_QUERY_RESULTS)]

    def resolve_event_candidates(
        self,
        context: CognitionContext,
        event_id: str | None,
        *,
        limit: int = MAX_MEMORY_QUERY_RESULTS,
    ) -> tuple[MemoryEventCandidate, ...]:
        """Re-read and revalidate each indexed record through canonical Store."""
        results: list[MemoryEventCandidate] = []
        for link in self.candidate_links(context, event_id, limit=limit):
            memory = self.memory_store.get_memory(link.memory_id)
            if (
                type(memory) is not Memory
                or memory.id not in context._memory_ids
                or memory.id not in self.authorized_memory_ids
                or memory.owner_id != context.owner_id
                or not MemoryStore.is_semantically_retrievable(memory)
                or memory.source_event != link.source_event_id
                or link.source_event_id not in self.verified_event_ids
            ):
                continue
            results.append(MemoryEventCandidate(MemorySnapshot.from_memory(memory), link))
            if len(results) >= min(limit, MAX_MEMORY_QUERY_RESULTS):
                break
        return tuple(results)

    def merge_candidates(
        self,
        context: CognitionContext,
        lexical_results: tuple[MemorySnapshot, ...],
        event_candidates: tuple[MemoryEventCandidate, ...],
        *,
        limit: int = MAX_MEMORY_QUERY_RESULTS,
    ) -> tuple[MemorySnapshot, ...]:
        """Stable direct-first deduplication under current Character scope.

        Direct results may include optional semantic candidates, but must come
        from the existing ``CognitionContext`` canonical-recheck path;
        associated candidates are canonical Store rechecks from this index.
        """
        self._validate_context(context)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")
        if not isinstance(lexical_results, tuple) or not isinstance(event_candidates, tuple):
            raise TypeError("retrieval channel results must be tuples")
        merged: list[MemorySnapshot] = []
        seen: set[str] = set()
        allowed = set(context._memory_ids) & self.authorized_memory_ids
        for snapshot in lexical_results:
            if type(snapshot) is not MemorySnapshot:
                raise TypeError("lexical results must be MemorySnapshot values")
            if snapshot.id not in allowed or snapshot.id in seen:
                continue
            canonical = self.memory_store.get_memory(snapshot.id)
            if (
                type(canonical) is not Memory
                or canonical.owner_id != context.owner_id
                or canonical.source_event != snapshot.source_event
                or not MemoryStore.is_semantically_retrievable(canonical)
            ):
                continue
            merged.append(MemorySnapshot.from_memory(canonical))
            seen.add(snapshot.id)
            if len(merged) >= min(limit, MAX_MEMORY_QUERY_RESULTS):
                break
        if len(merged) >= min(limit, MAX_MEMORY_QUERY_RESULTS):
            return tuple(merged)
        for candidate in event_candidates:
            if type(candidate) is not MemoryEventCandidate:
                raise TypeError("event results must be MemoryEventCandidate values")
            snapshot = candidate.memory
            link = candidate.link
            if (
                type(snapshot) is not MemorySnapshot
                or snapshot.id not in allowed
                or snapshot.id in seen
                or link.source_event_id not in self.verified_event_ids
                or link.memory_id != snapshot.id
                or link not in self._event_to_links.get(link.source_event_id, ())
            ):
                continue
            canonical = self.memory_store.get_memory(snapshot.id)
            if (
                type(canonical) is not Memory
                or canonical.owner_id != context.owner_id
                or canonical.source_event != link.source_event_id
                or snapshot.source_event != link.source_event_id
                or not MemoryStore.is_semantically_retrievable(canonical)
            ):
                continue
            merged.append(MemorySnapshot.from_memory(canonical))
            seen.add(snapshot.id)
            if len(merged) >= min(limit, MAX_MEMORY_QUERY_RESULTS):
                break
        return tuple(merged[: min(limit, MAX_MEMORY_QUERY_RESULTS)])

    def _validate_context(self, context: CognitionContext) -> None:
        from cognitive_world.agent.cognition_context import CognitionContext

        if (
            not isinstance(context, CognitionContext)
            or context.owner_id != self.owner_id
            or context.memory_store is not self.memory_store
        ):
            raise PermissionError("MemoryEventIndex is bound to another cognition context")
