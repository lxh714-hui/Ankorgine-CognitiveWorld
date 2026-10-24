"""Versioned, fence-consistent snapshots of canonical cognition stores.

The snapshot is a validated staging contract, not an active Runtime restore.
Its content digest detects changes; authenticity requires an injected
PersistenceTrust that is stable and managed by the host.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from cognitive_world.agent.cognition_context import CognitionContext
    from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.cognition.belief import Belief
from cognitive_world.cognition.container import CognitionContainer
from cognitive_world.cognition.emotion import (
    Emotion, EmotionDimensionProfile, EmotionProfile, EmotionReaction,
)
from cognitive_world.cognition.goal import Goal, GoalResourceDemand
from cognitive_world.cognition.memory import (
    Memory, MemoryDecisionProvenance, MemoryDecisionProvenanceV2,
    SystemOnlyMemoryContent,
)
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.cognition.memory_revision import MemoryRevisionLineage
from cognitive_world.cognition.l1_consumption_proof import (
    L1ConsumptionProof, NonverbalL1ConsumptionProof,
    PROOF_MEMORY_TYPE, NONVERBAL_PROOF_MEMORY_TYPE, verify_proof,
    verify_nonverbal_proof,
)
from cognitive_world.cognition.l1_instance import (L1ConsumptionInstance, InstanceL1ConsumptionProof,
    INSTANCE_PROOF_MEMORY_TYPE, verify_instance_proof)
from cognitive_world.cognition.personality import Personality
from cognitive_world.cognition.self_model import SelfModel
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.core.persistence import (
    PersistedValueCodec, PersistenceTrust, sha256_hex,
)
from cognitive_world.event.history import EventHistory
from cognitive_world.runtime.write_fence import RuntimeWriteFence


COGNITIVE_SNAPSHOT_SCHEMA_VERSION = 3
_COGNITIVE_SNAPSHOT_PURPOSE_V2 = "cognitive-world/cognitive-state-snapshot/v2"
_COGNITIVE_SNAPSHOT_PURPOSE_V3 = "cognitive-world/cognitive-state-snapshot/v3"
# Compatibility name for callers that sign newly captured snapshots.
_COGNITIVE_SNAPSHOT_PURPOSE = _COGNITIVE_SNAPSHOT_PURPOSE_V3
_STORE_NAMES = ("beliefs", "goals", "self_models", "memories", "emotions", "personalities")
_EXCLUSIONS = (
    "WorkingMemory and turn-local buffers",
    "Observation and Percept input records",
    "DecisionContext and derived cognition projections",
    "Proposal, validation trace, ActionProposal trace, Event Tree and scheduler diagnostics",
    "CognitiveRuntime consumption cursors and provider/task state",
    "AgentRegistry and mutable Agent scheduling metadata",
    "relationship state: no canonical relationship store is currently present",
)


def cognitive_snapshot_codec() -> PersistedValueCodec:
    """Build the existing allow-list codec with supported cognition records."""
    codec = PersistedValueCodec()
    for value_type in (
        Belief, Goal, GoalResourceDemand, SelfModel, Memory,
        MemoryDecisionProvenance, MemoryDecisionProvenanceV2, Emotion,
        EmotionReaction, EmotionDimensionProfile, EmotionProfile, Personality,
        CognitiveSourceReference, CognitiveRecordSnapshot, CognitiveStoreSnapshot,
        CognitiveAgentManifestEntry,
        CognitiveAgentLinks, CognitiveSnapshotBody, CognitiveStateSnapshot,
        L1ConsumptionProof,
        NonverbalL1ConsumptionProof, L1ConsumptionInstance, InstanceL1ConsumptionProof,
    ):
        codec.register_type(value_type)
    return codec


@dataclass(frozen=True)
class CognitiveSourceReference:
    reference: str
    verification: str

    def __post_init__(self) -> None:
        if not isinstance(self.reference, str) or not self.reference:
            raise ValueError("cognitive source reference must be non-empty")
        if self.verification not in {
            "event_history_reference_present", "unverified_reference", "no_source_recorded"
        }:
            raise ValueError("unsupported cognitive source verification status")


@dataclass(frozen=True)
class CognitiveRecordSnapshot:
    owner_id: str
    record_id: str
    value: object
    sources: tuple[CognitiveSourceReference, ...]

    def __post_init__(self) -> None:
        if not self.owner_id or not self.record_id:
            raise ValueError("cognitive snapshot record requires owner and identity")
        if not isinstance(self.sources, tuple) or any(
            type(item) is not CognitiveSourceReference for item in self.sources
        ):
            raise TypeError("cognitive snapshot sources must be typed immutable records")


@dataclass(frozen=True)
class CognitiveStoreSnapshot:
    store_name: str
    records: tuple[CognitiveRecordSnapshot, ...]
    owner_ids: tuple[str, ...]
    state_version: str
    revision_semantics: str = "canonical-content-digest"
    coverage: str = "complete-for-bound-store"

    def __post_init__(self) -> None:
        if self.store_name not in _STORE_NAMES:
            raise ValueError("unknown cognitive store in snapshot")
        if not isinstance(self.records, tuple) or any(
            type(item) is not CognitiveRecordSnapshot for item in self.records
        ) or not isinstance(self.owner_ids, tuple):
            raise TypeError("store snapshots require immutable typed records and owner IDs")
        if not self.state_version.startswith("sha256:"):
            raise ValueError("store state version must be a content digest")
        if self.revision_semantics != "canonical-content-digest":
            raise ValueError("unsupported store revision semantics")
        if self.coverage != "complete-for-bound-store":
            raise ValueError("unsupported store coverage claim")
        if len(set(self.owner_ids)) != len(self.owner_ids):
            raise ValueError("duplicate owners in store coverage")


@dataclass(frozen=True)
class CognitiveAgentLinks:
    """Stable Agent/Character identity and canonical cognition record links."""

    agent_id: str
    character_id: str
    belief_ids: tuple[str, ...]
    goal_ids: tuple[str, ...]
    memory_ids: tuple[str, ...]
    personality_id: str | None
    emotion_id: str | None
    has_self_model: bool

    def __post_init__(self) -> None:
        if (not isinstance(self.agent_id, str) or not self.agent_id
                or not isinstance(self.character_id, str) or not self.character_id):
            raise ValueError("Agent cognition links require Agent and Character identities")
        for name in ("belief_ids", "goal_ids", "memory_ids"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(item, str) or not item for item in values):
                raise TypeError(f"{name} must be a tuple of non-empty IDs")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} cannot contain duplicate IDs")
        for name in ("personality_id", "emotion_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{name} must be a non-empty ID or None")
        if type(self.has_self_model) is not bool:
            raise TypeError("has_self_model must be bool")


@dataclass(frozen=True)
class CognitiveAgentManifestEntry:
    """Agent/Character identity copied from the authoritative Runtime registry."""

    agent_id: str
    character_id: str

    def __post_init__(self) -> None:
        if (not isinstance(self.agent_id, str) or not self.agent_id
                or not isinstance(self.character_id, str) or not self.character_id):
            raise ValueError("registered Agent manifest requires both identities")


@dataclass(frozen=True)
class CognitiveSnapshotBody:
    schema_version: int
    simulation_tick: int
    timeline_id: str
    session_id: str
    restore_generation: int
    agent_ids: tuple[str, ...]
    expected_agents: tuple[CognitiveAgentManifestEntry, ...]
    agent_registry_revision: int
    agent_links: tuple[CognitiveAgentLinks, ...]
    stores: tuple[CognitiveStoreSnapshot, ...]
    exclusions: tuple[str, ...] = _EXCLUSIONS

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version not in {2, 3}:
            raise ValueError("unsupported CognitiveStateSnapshot schema version")
        if isinstance(self.simulation_tick, bool) or not isinstance(self.simulation_tick, int) or self.simulation_tick < 0:
            raise ValueError("snapshot simulation tick must be non-negative")
        if not isinstance(self.timeline_id, str) or not self.timeline_id:
            raise ValueError("snapshot requires an explicit timeline identity")
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("snapshot requires runtime session identity")
        if isinstance(self.restore_generation, bool) or not isinstance(self.restore_generation, int) or self.restore_generation < 0:
            raise ValueError("snapshot restore generation must be non-negative")
        if isinstance(self.agent_registry_revision, bool) or not isinstance(self.agent_registry_revision, int) or self.agent_registry_revision < 0:
            raise ValueError("snapshot AgentRegistry revision must be non-negative")
        if (not isinstance(self.agent_ids, tuple) or any(not isinstance(x, str) or not x for x in self.agent_ids)
                or not isinstance(self.expected_agents, tuple)
                or any(type(item) is not CognitiveAgentManifestEntry for item in self.expected_agents)
                or not isinstance(self.stores, tuple)):
            raise TypeError("snapshot Agent roster must be a tuple of non-empty IDs")
        if len(set(self.agent_ids)) != len(self.agent_ids):
            raise ValueError("duplicate Agent identity in cognitive snapshot")
        expected_ids = tuple(item.agent_id for item in self.expected_agents)
        if len(set(expected_ids)) != len(expected_ids):
            raise ValueError("duplicate Agent identity in authoritative snapshot manifest")
        if tuple(sorted(self.agent_ids)) != tuple(sorted(expected_ids)):
            raise ValueError("captured Agent set does not match authoritative manifest")
        if (not isinstance(self.agent_links, tuple)
                or any(type(item) is not CognitiveAgentLinks for item in self.agent_links)
                or tuple(sorted(item.agent_id for item in self.agent_links)) != tuple(sorted(self.agent_ids))):
            raise ValueError("snapshot Agent links must cover the exact Agent roster")
        expected_pairs = tuple(sorted((item.agent_id, item.character_id) for item in self.expected_agents))
        actual_pairs = tuple(sorted((item.agent_id, item.character_id) for item in self.agent_links))
        if expected_pairs != actual_pairs:
            raise ValueError("captured Agent/Character links do not match authoritative manifest")
        names = tuple(item.store_name for item in self.stores)
        if len(names) != len(set(names)) or set(names) != set(_STORE_NAMES):
            raise ValueError("snapshot must contain each supported canonical store exactly once")


@dataclass(frozen=True)
class CognitiveStateSnapshot:
    body: CognitiveSnapshotBody
    content_digest: str
    signature_hex: str | None = None

    @property
    def authenticity(self) -> str:
        return "signed-pending-verification" if self.signature_hex else "content-digest-only"

    def to_bytes(self, *, codec: PersistedValueCodec | None = None) -> bytes:
        codec = codec or cognitive_snapshot_codec()
        body_bytes = codec.dumps(self.body)
        if "sha256:" + sha256_hex(body_bytes) != self.content_digest:
            raise ValueError("cognitive snapshot body changed after capture")
        return codec.dumps(self)

    @classmethod
    def from_bytes(
        cls, payload: bytes, *, trust: PersistenceTrust | None = None,
        codec: PersistedValueCodec | None = None,
    ) -> "CognitiveStateSnapshot":
        codec = codec or cognitive_snapshot_codec()
        value = codec.loads(payload)
        if type(value) is not cls:
            raise TypeError("payload is not a CognitiveStateSnapshot")
        value.validate(trust=trust, codec=codec, defer_event_sources=True,
                       defer_memory_lineage=True)
        return value

    def validate(
        self, *, trust: PersistenceTrust | None = None,
        codec: PersistedValueCodec | None = None,
        event_history: EventHistory | None = None,
        defer_event_sources: bool = False,
        historical_rule_registry: object | None = None,
        memory_revision_lineage: MemoryRevisionLineage | None = None,
        defer_memory_lineage: bool = False,
    ) -> str:
        codec = codec or cognitive_snapshot_codec()
        if type(self.body) is not CognitiveSnapshotBody:
            raise TypeError("invalid cognitive snapshot body")
        body_bytes = codec.dumps(self.body)
        if "sha256:" + sha256_hex(body_bytes) != self.content_digest:
            raise ValueError("cognitive snapshot content digest mismatch")
        if self.signature_hex is not None:
            if trust is None:
                raise PermissionError("signed cognitive snapshot requires its external trust verifier")
            try:
                signature = bytes.fromhex(self.signature_hex)
            except ValueError as error:
                raise ValueError("invalid cognitive snapshot signature encoding") from error
            purpose = (_COGNITIVE_SNAPSHOT_PURPOSE_V2 if self.body.schema_version == 2
                       else _COGNITIVE_SNAPSHOT_PURPOSE_V3)
            if not trust.verify(purpose, body_bytes, signature):
                raise PermissionError("cognitive snapshot signature verification failed")
            authenticity = "signature-verified"
        else:
            authenticity = "content-digest-only"
        _validate_body(self.body, codec=codec, event_history=event_history, trust=trust,
                       defer_event_sources=defer_event_sources,
                       historical_rule_registry=historical_rule_registry,
                       memory_revision_lineage=memory_revision_lineage,
                       defer_memory_lineage=defer_memory_lineage)
        return authenticity

    @classmethod
    def capture(
        cls, *, cognition: CognitionContainer, memory_store: MemoryStore,
        runtime: SimulationRuntime, agent_contexts: tuple[CognitionContext, ...],
        timeline_id: str,
        trust: PersistenceTrust | None = None,
        codec: PersistedValueCodec | None = None,
        historical_rule_registry: object | None = None,
        memory_revision_lineage: MemoryRevisionLineage | None = None,
    ) -> "CognitiveStateSnapshot":
        """Capture all supported canonical Stores under the shared fence lock."""
        from cognitive_world.agent.cognition_context import CognitionContext
        from cognitive_world.runtime.runtime import SimulationRuntime
        codec = codec or cognitive_snapshot_codec()
        if type(runtime) is not SimulationRuntime:
            raise TypeError("capture requires the canonical SimulationRuntime")
        write_fence = runtime.write_fence
        simulation_clock = runtime.context.clock
        event_history = runtime.context.event_history
        lineage = memory_revision_lineage or runtime.memory_revision_lineage
        if lineage is None and getattr(event_history, "fork_manifest_bytes", None) is None:
            lineage = MemoryRevisionLineage.root(timeline_id)
        if type(lineage) is not MemoryRevisionLineage or lineage.timeline_id != timeline_id:
            raise PermissionError("snapshot capture requires the Runtime's Timeline revision view")
        lineage.verify_event_history(event_history)
        _require_shared_fence(cognition, memory_store, write_fence)
        if memory_store._revision_lineage is None:
            if getattr(event_history, "fork_manifest_bytes", None) is not None:
                raise PermissionError("MemoryStore lacks its required verified revision view")
            memory_store.bind_revision_lineage(lineage)
        elif type(memory_store._revision_lineage) is not MemoryRevisionLineage:
            raise PermissionError("MemoryStore has an invalid revision view")
        else:
            memory_store._revision_lineage._require_issued()
        if memory_store._revision_lineage is None:
            memory_store.bind_revision_lineage(lineage)
        if memory_store._revision_lineage != lineage:
            raise PermissionError("MemoryStore is not bound to the Runtime's revision view")
        registry = runtime.context.agent_registry
        if type(registry) is not AgentRegistry:
            raise PermissionError("complete cognition snapshot requires the Runtime's authoritative AgentRegistry")
        if not isinstance(agent_contexts, tuple) or any(type(item) is not CognitionContext for item in agent_contexts):
            raise TypeError("capture requires the Agents' canonical CognitionContexts")
        with write_fence.snapshot_scope() as permit:
            with registry.snapshot_scope() as (registry_revision, registered_agents):
                expected_agents = _registered_manifest(registered_agents)
                expected_by_id = {item.agent_id: item.character_id for item in expected_agents}
                links = tuple(sorted(
                    (_agent_links(item, cognition) for item in agent_contexts),
                    key=lambda item: item.agent_id,
                ))
                agent_ids = tuple(item.agent_id for item in links)
                if len(agent_ids) != len(set(agent_ids)):
                    raise ValueError("capture has duplicate CognitionContext owners")
                if set(agent_ids) != set(expected_by_id):
                    missing = set(expected_by_id) - set(agent_ids)
                    extra = set(agent_ids) - set(expected_by_id)
                    raise ValueError(
                        f"CognitionContext coverage differs from Runtime AgentRegistry; "
                        f"missing={sorted(missing)}, unregistered={sorted(extra)}"
                    )
                for link in links:
                    if expected_by_id[link.agent_id] != link.character_id:
                        raise ValueError("CognitionContext Character does not match registered RuntimeAgent")
                simulation_tick = simulation_clock.capture().tick
                store_records = _collect_store_records(cognition, memory_store, event_history)
                stores: list[CognitiveStoreSnapshot] = []
                for name in _STORE_NAMES:
                    records = tuple(sorted(store_records[name], key=lambda r: (r.owner_id, r.record_id)))
                    if any(record.owner_id not in expected_by_id for record in records):
                        raise ValueError(f"{name} contains a record whose owner is absent from Runtime AgentRegistry")
                    owners = tuple(sorted({record.owner_id for record in records}))
                    unsigned = CognitiveStoreSnapshot(name, records, owners, "sha256:pending")
                    digest = "sha256:" + sha256_hex(codec.dumps(unsigned))
                    stores.append(CognitiveStoreSnapshot(name, records, owners, digest))
                body = CognitiveSnapshotBody(
                    COGNITIVE_SNAPSHOT_SCHEMA_VERSION, simulation_tick, timeline_id,
                    permit.session_id, permit.restore_generation,
                    tuple(sorted(agent_ids)), expected_agents, registry_revision,
                    links, tuple(stores),
                )
                body_bytes = codec.dumps(body)
                signature = None if trust is None else trust.sign(_COGNITIVE_SNAPSHOT_PURPOSE_V3, body_bytes).hex()
                result = cls(body, "sha256:" + sha256_hex(body_bytes), signature)
                result.validate(trust=trust, codec=codec, event_history=event_history,
                                historical_rule_registry=historical_rule_registry,
                                memory_revision_lineage=lineage)
                return result


@dataclass(frozen=True)
class IsolatedCognitiveRestore:
    cognition: CognitionContainer
    memory_store: MemoryStore
    agent_ids: tuple[str, ...]
    expected_agents: tuple[CognitiveAgentManifestEntry, ...]
    agent_registry_revision: int
    agent_links: tuple[CognitiveAgentLinks, ...]
    timeline_id: str
    simulation_tick: int
    session_id: str
    captured_restore_generation: int
    completeness: str
    authenticity: str
    memory_revision_lineage: MemoryRevisionLineage

    def __post_init__(self) -> None:
        if self.completeness != "complete-for-verified-Agent-manifest-and-supported-stores":
            raise ValueError("isolated restore must be complete for supported stores")
        if self.authenticity not in {"content-digest-only", "signature-verified"}:
            raise ValueError("invalid isolated restore authenticity level")


def reconstruct_isolated(
    snapshot: CognitiveStateSnapshot, *, trust: PersistenceTrust | None = None,
    expected_agents: tuple[CognitiveAgentManifestEntry, ...] | None = None,
    event_history: EventHistory | None = None,
    codec: PersistedValueCodec | None = None,
    historical_rule_registry: object | None = None,
    memory_revision_lineage: MemoryRevisionLineage | None = None,
    defer_memory_lineage: bool = False,
) -> IsolatedCognitiveRestore:
    """Validate the snapshot against an independent host roster, then stage it.

    A roster carried only inside an unsigned snapshot is not independent
    evidence of its own completeness. Callers must provide the expected Agent
    manifest obtained from their trusted host/save metadata.
    """
    if (not isinstance(expected_agents, tuple)
            or any(type(item) is not CognitiveAgentManifestEntry for item in expected_agents)):
        raise PermissionError("isolated reconstruction requires an independent expected Agent manifest")
    expected_pairs = tuple(sorted((item.agent_id, item.character_id) for item in expected_agents))
    if len({item.agent_id for item in expected_agents}) != len(expected_agents):
        raise ValueError("independent expected Agent manifest contains duplicate identities")
    snapshot_pairs = tuple(sorted(
        (item.agent_id, item.character_id) for item in snapshot.body.expected_agents
    ))
    if expected_pairs != snapshot_pairs:
        raise ValueError("snapshot Agent coverage does not match independent expected manifest")
    authenticity = snapshot.validate(
        trust=trust, codec=codec, event_history=event_history,
        historical_rule_registry=historical_rule_registry,
        memory_revision_lineage=memory_revision_lineage,
        defer_memory_lineage=defer_memory_lineage,
    )
    records = {store.store_name: store.records for store in snapshot.body.stores}
    cognition = CognitionContainer()
    memory_records: tuple[Memory, ...] = ()
    constructors: dict[str, tuple[type, Any]] = {
        "beliefs": (Belief, cognition.add_belief),
        "goals": (Goal, cognition.add_goal),
        "self_models": (SelfModel, cognition.add_self_model),
        "personalities": (Personality, cognition.add_personality),
        "emotions": (Emotion, cognition.add_emotion),
        "memories": (Memory, None),
    }
    # Validate and build only local staging values. No active Store is passed
    # here; any exception prevents an IsolatedCognitiveRestore being returned.
    for name in _STORE_NAMES:
        expected_type, add = constructors[name]
        values = []
        for record in records[name]:
            if type(record.value) is not expected_type:
                raise TypeError(f"{name} snapshot contains an unsupported record type")
            if getattr(record.value, "owner_id", None) != record.owner_id:
                raise ValueError(f"{name} owner does not match its record")
            values.append(record.value)
        if name == "memories":
            memory_records = tuple(values)
        else:
            for value in values:
                add(deepcopy(value))
    if memory_revision_lineage is None:
        memory_revision_lineage = MemoryRevisionLineage.root(snapshot.body.timeline_id)
    memory_store = MemoryStore.from_isolated_snapshot(
        memory_records, revision_lineage=memory_revision_lineage,
    )
    return IsolatedCognitiveRestore(
        cognition, memory_store, snapshot.body.agent_ids, snapshot.body.expected_agents,
        snapshot.body.agent_registry_revision, snapshot.body.agent_links,
        snapshot.body.timeline_id, snapshot.body.simulation_tick, snapshot.body.session_id,
        snapshot.body.restore_generation,
        "complete-for-verified-Agent-manifest-and-supported-stores", authenticity,
        memory_revision_lineage,
    )


def verify_restored_stores_match_snapshot(
    snapshot: CognitiveStateSnapshot, *, cognition: CognitionContainer,
    memory_store: MemoryStore, event_history: EventHistory,
    write_fence: RuntimeWriteFence, codec: PersistedValueCodec | None = None,
    trust: PersistenceTrust | None = None,
    memory_revision_lineage: MemoryRevisionLineage | None = None,
    snapshot_event_history: EventHistory | None = None,
) -> None:
    """Recheck canonical isolated Store content against a verified snapshot.

    Intended for a frozen, unpublished reconstruction. It performs no writes
    and does not mint or apply cognition updates.
    """
    if type(snapshot) is not CognitiveStateSnapshot:
        raise TypeError("store verification requires a canonical CognitiveStateSnapshot")
    codec = codec or cognitive_snapshot_codec()
    lineage = memory_revision_lineage or memory_store._revision_lineage
    snapshot.validate(trust=trust, codec=codec,
                      event_history=snapshot_event_history or event_history,
                      memory_revision_lineage=lineage)
    _require_shared_fence(cognition, memory_store, write_fence)
    records = _collect_store_records(cognition, memory_store, event_history)
    actual: list[CognitiveStoreSnapshot] = []
    for name in _STORE_NAMES:
        owned = tuple(sorted(records[name], key=lambda item: (item.owner_id, item.record_id)))
        owners = tuple(sorted({item.owner_id for item in owned}))
        unsigned = CognitiveStoreSnapshot(name, owned, owners, "sha256:pending")
        digest = "sha256:" + sha256_hex(codec.dumps(unsigned))
        actual.append(CognitiveStoreSnapshot(name, owned, owners, digest))
    if tuple(actual) != snapshot.body.stores:
        raise PermissionError("staged canonical Store contents differ from the verified cognitive snapshot")


def _require_shared_fence(
    cognition: CognitionContainer, memory_store: MemoryStore,
    fence: RuntimeWriteFence,
) -> None:
    if type(cognition) is not CognitionContainer or type(memory_store) is not MemoryStore:
        raise TypeError("snapshot requires canonical cognition and Memory stores")
    if set(vars(cognition)) != {
        "personality_store", "belief_store", "goal_store", "self_model_store",
        "_emotions", "write_fence",
    }:
        raise TypeError("CognitionContainer has unsupported state outside the snapshot contract")
    if set(vars(memory_store)) != {"_memories", "write_fence", "_revision_lineage"}:
        raise TypeError("MemoryStore has unsupported state outside the snapshot contract")
    if cognition.write_fence is not fence or memory_store.write_fence is not fence:
        raise PermissionError("all canonical cognition stores must share the capture RuntimeWriteFence")
    if any(getattr(cognition, name).write_fence is not fence for name in (
        "belief_store", "goal_store", "self_model_store", "personality_store"
    )):
        raise PermissionError("a canonical cognition Store is not bound to the capture fence")


def _collect_store_records(
    cognition: CognitionContainer, memory_store: MemoryStore,
    event_history: EventHistory | None,
) -> dict[str, list[CognitiveRecordSnapshot]]:
    values: dict[str, tuple[object, ...]] = {
        "beliefs": cognition.belief_store.get_all(),
        "goals": cognition.goal_store.get_all(),
        "self_models": cognition.self_model_store.get_all(),
        "memories": memory_store.get_all_memories(),
        "emotions": tuple(cognition.emotions.values()),
        "personalities": cognition.personality_store.get_all(),
    }
    result: dict[str, list[CognitiveRecordSnapshot]] = {name: [] for name in _STORE_NAMES}
    for store_name, items in values.items():
        seen: set[str] = set()
        for item in items:
            owner_id = getattr(item, "owner_id", None)
            record_id = _record_id(store_name, item)
            if not isinstance(owner_id, str) or not owner_id or not record_id:
                raise ValueError(f"{store_name} has invalid canonical owner or identity")
            if record_id in seen:
                raise ValueError(f"{store_name} contains duplicate canonical identity")
            seen.add(record_id)
            refs = _source_refs(store_name, item)
            sources = tuple(CognitiveSourceReference(
                ref,
                "event_history_reference_present" if event_history is not None and event_history.get_event(ref) is not None
                else "unverified_reference",
            ) for ref in refs)
            if not refs:
                sources = (CognitiveSourceReference("<none>", "no_source_recorded"),)
            result[store_name].append(CognitiveRecordSnapshot(
                owner_id, record_id, deepcopy(item), sources
            ))
    return result


def _record_id(store: str, value: object) -> str:
    if store == "beliefs":
        return getattr(value, "belief_id", "")
    if store == "goals":
        return f"{getattr(value, 'owner_id', '')}:{getattr(value, 'goal_id', '')}"
    if store == "self_models" or store == "personalities":
        return getattr(value, "owner_id", "")
    if store == "emotions":
        return f"{getattr(value, 'owner_id', '')}:{getattr(value, 'id', '')}"
    if store == "memories":
        return getattr(value, "id", "")
    raise ValueError("unknown cognition store")


def _agent_links(context: CognitionContext, cognition: CognitionContainer) -> CognitiveAgentLinks:
    if (not context.owner_id or not context.character_id
            or context.cognition_container is not cognition):
        raise ValueError("CognitionContext must belong to the captured canonical container")
    return CognitiveAgentLinks(
        context.owner_id, context.character_id, tuple(context._belief_ids),
        tuple(context._goal_ids), tuple(context._memory_ids),
        context._personality_id, context._emotion_id,
        cognition.get_self_model(context.owner_id) is not None,
    )


def _registered_manifest(
    registered_agents: tuple[RuntimeAgent, ...],
) -> tuple[CognitiveAgentManifestEntry, ...]:
    if any(type(item) is not RuntimeAgent for item in registered_agents):
        raise TypeError("Runtime AgentRegistry contains an unsupported Agent implementation")
    result = []
    for agent in registered_agents:
        identity = agent.get_identity()
        agent_id = identity.get("agent_id")
        character_id = identity.get("character_id")
        if not isinstance(agent_id, str) or not agent_id:
            raise ValueError("registered RuntimeAgent has invalid identity")
        if not isinstance(character_id, str) or not character_id:
            raise ValueError("registered RuntimeAgent has no verifiable Character identity")
        result.append(CognitiveAgentManifestEntry(agent_id, character_id))
    return tuple(sorted(result, key=lambda item: item.agent_id))


def _source_refs(store: str, value: object) -> tuple[str, ...]:
    if store in {"beliefs", "goals"}:
        refs = getattr(value, "source_refs", ())
    elif store == "memories":
        provenance = getattr(value, "decision_provenance", None)
        provenance_refs = (
            provenance.source_event_ids
            if type(provenance) in {
                MemoryDecisionProvenance, MemoryDecisionProvenanceV2,
            } else ()
        )
        refs = (getattr(value, "source_event", ""), *provenance_refs)
    elif store == "emotions":
        refs = getattr(value, "processed_sources", ())
    elif store == "self_models":
        refs = tuple(
            ref for item in getattr(value, "self_beliefs", ()) if isinstance(item, dict)
            for field_name in ("source_refs", "source_event_ids")
            for ref in item.get(field_name, ())
        )
    else:
        refs = ()
    if isinstance(refs, str):
        refs = (refs,)
    return tuple(dict.fromkeys(ref for ref in refs if isinstance(ref, str) and ref))


def _validate_body(
    body: CognitiveSnapshotBody, *, codec: PersistedValueCodec,
    event_history: EventHistory | None, trust: PersistenceTrust | None,
    defer_event_sources: bool = False,
    historical_rule_registry: object | None = None,
    memory_revision_lineage: MemoryRevisionLineage | None = None,
    defer_memory_lineage: bool = False,
) -> None:
    if len(body.stores) != len(_STORE_NAMES):
        raise ValueError("incomplete canonical cognition Store coverage")
    indexed: dict[str, dict[tuple[str, str], CognitiveRecordSnapshot]] = {}
    for store in body.stores:
        identities: set[object] = set()
        actual_owners: set[str] = set()
        for record in store.records:
            key = ((record.owner_id, record.record_id) if store.store_name == "goals"
                   else record.record_id)
            if key in identities:
                raise ValueError("duplicate cognitive record identity")
            identities.add(key)
            actual_owners.add(record.owner_id)
            if record.owner_id not in body.agent_ids:
                raise ValueError("cognitive record owner is absent from snapshot Agent roster")
            expected_type = {
                "beliefs": Belief, "goals": Goal, "self_models": SelfModel,
                "memories": Memory, "emotions": Emotion, "personalities": Personality,
            }[store.store_name]
            if type(record.value) is not expected_type:
                raise TypeError(f"{store.store_name} contains an unsupported record type")
            if getattr(record.value, "owner_id", None) != record.owner_id:
                raise ValueError(f"{store.store_name} record owner mismatch")
            if store.store_name == "memories":
                memory = record.value
                if body.schema_version == 2 and memory.schema_version != 1:
                    raise PermissionError("CognitiveStateSnapshot/v2 cannot contain Memory/v2 records")
                if memory.type == PROOF_MEMORY_TYPE:
                    if (type(memory.content) is not L1ConsumptionProof
                            or memory.id != memory.content.proof_id
                            or memory.source_event != memory.content.source_event_id):
                        raise PermissionError("system L1 proof record is malformed")
                    if event_history is not None:
                        if trust is None:
                            raise PermissionError("system L1 proof requires a trusted verifier")
                        verify_proof(
                            memory.content, history=event_history, trust=trust,
                            checkpoint_timeline_id=body.timeline_id,
                            checkpoint_tick=body.simulation_tick,
                        )
                elif memory.type == NONVERBAL_PROOF_MEMORY_TYPE:
                    if (type(memory.content) is not NonverbalL1ConsumptionProof
                            or memory.id != memory.content.proof_id
                            or memory.source_event != memory.content.source_event_id):
                        raise PermissionError("non-verbal system proof record is malformed")
                    if event_history is not None:
                        if trust is None:
                            raise PermissionError("non-verbal system proof requires a trusted verifier")
                        verify_nonverbal_proof(
                            memory.content, history=event_history, trust=trust,
                            checkpoint_timeline_id=body.timeline_id,
                            checkpoint_tick=body.simulation_tick,
                            rule_registry=historical_rule_registry,
                        )
                elif memory.type == INSTANCE_PROOF_MEMORY_TYPE:
                    if (body.schema_version < 3 or type(memory.content) is not InstanceL1ConsumptionProof
                            or memory.id != memory.content.proof_id
                            or memory.owner_id != memory.content.owner_id
                            or memory.source_event != memory.content.source_event_id):
                        raise PermissionError("instance proof record is malformed or unsupported")
                    from cognitive_world.cognition.l1_instance import validate_instance_proof_structure
                    validate_instance_proof_structure(memory.content)
                    if event_history is not None:
                        if trust is None:
                            raise PermissionError("instance proof requires trusted verification")
                        verify_instance_proof(memory.content, history=event_history, trust=trust,
                            checkpoint_timeline_id=body.timeline_id, checkpoint_tick=body.simulation_tick,
                            rule_registry=historical_rule_registry, memory_revision_lineage=memory_revision_lineage)
                elif memory.type.startswith("system_l1_"):
                    raise PermissionError("unknown L1 system record type")
                elif isinstance(memory.content, SystemOnlyMemoryContent):
                    raise PermissionError("system-only content cannot be hidden in ordinary Memory")
            if _record_id(store.store_name, record.value) != record.record_id:
                raise ValueError(f"{store.store_name} record identity mismatch")
            expected_refs = _source_refs(store.store_name, record.value)
            actual_refs = tuple(item.reference for item in record.sources)
            if actual_refs != (expected_refs or ("<none>",)):
                raise ValueError(f"{store.store_name} source references do not match record")
            if not record.sources:
                raise ValueError("cognitive record omits source validation status")
            for source in record.sources:
                if source.verification == "event_history_reference_present":
                    if (event_history is None and not defer_event_sources) or (
                        event_history is not None and event_history.get_event(source.reference) is None
                    ):
                        raise PermissionError("snapshot Event source is absent from supplied EventHistory")
        if tuple(sorted(actual_owners)) != tuple(sorted(store.owner_ids)):
            raise ValueError("store owner coverage does not match its records")
        if store.store_name == "memories":
            memories_by_id = {item.record_id: item.value for item in store.records}
            for record in store.records:
                memory = record.value
                if memory.schema_version != 2:
                    continue
                visited = {memory.id}
                predecessor_id = memory.supersedes_record_id
                while predecessor_id is not None:
                    predecessor = memories_by_id.get(predecessor_id)
                    if (predecessor is None or predecessor.schema_version != 2
                            or predecessor.owner_id != memory.owner_id
                            or predecessor.logical_record_id != memory.logical_record_id):
                        raise ValueError("Memory/v2 predecessor is absent or crosses owner/logical identity")
                    if predecessor.id in visited:
                        raise ValueError("Memory/v2 revision references contain a cycle")
                    visited.add(predecessor.id)
                    predecessor_id = predecessor.supersedes_record_id
        expected = "sha256:" + sha256_hex(codec.dumps(CognitiveStoreSnapshot(
            store.store_name, store.records, store.owner_ids, "sha256:pending"
        )))
        if expected != store.state_version:
            raise ValueError(f"{store.store_name} content version mismatch")
        # Ensure payload values can actually be serialized by the allow-list.
        codec.dumps(store)
        indexed[store.store_name] = {(item.owner_id, item.record_id): item for item in store.records}
    for link in body.agent_links:
        if link.agent_id not in body.agent_ids or not link.character_id:
            raise ValueError("invalid Agent identity link")
        refs = {
            "beliefs": tuple((link.agent_id, item) for item in link.belief_ids),
            "goals": tuple((link.agent_id, f"{link.agent_id}:{item}") for item in link.goal_ids),
            "memories": tuple((link.agent_id, item) for item in link.memory_ids),
            "personalities": (() if link.personality_id is None else ((link.agent_id, link.personality_id),)),
            "emotions": (() if link.emotion_id is None else ((link.agent_id, f"{link.agent_id}:{link.emotion_id}"),)),
        }
        for store_name, keys in refs.items():
            for key in keys:
                if key not in indexed[store_name]:
                    raise ValueError(f"Agent link references missing {store_name} state")
        if link.has_self_model != ((link.agent_id, link.agent_id) in indexed["self_models"]):
            raise ValueError("Agent SelfModel coverage does not match canonical store")
    if defer_memory_lineage:
        return
    if memory_revision_lineage is None:
        memory_revision_lineage = MemoryRevisionLineage.root(body.timeline_id)
    if (type(memory_revision_lineage) is not MemoryRevisionLineage
            or memory_revision_lineage.timeline_id != body.timeline_id):
        raise PermissionError("snapshot Memory revision view does not match its Timeline")
    if event_history is not None:
        memory_revision_lineage.verify_event_history(event_history)
    memory_revision_lineage.validate_records(tuple(
        item.value for item in next(store for store in body.stores
                                    if store.store_name == "memories").records
    ))
