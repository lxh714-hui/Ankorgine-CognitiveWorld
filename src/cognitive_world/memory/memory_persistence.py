"""Persist only unchanged requests backed by authorized Memory Decisions."""

from contextlib import nullcontext
from dataclasses import dataclass

from cognitive_world.cognition.memory import Memory
from cognitive_world.cognition.memory_store import (
    MemoryStore, _MEMORY_PERSISTENCE_AUTHORITY,
)
from cognitive_world.event.history import EventHistory
from cognitive_world.memory.memory_write import MemoryWriteRequest
from cognitive_world.runtime.write_fence import RuntimeWriteFence
from cognitive_world.cognition.memory_revision import MemoryRevisionLineage


@dataclass
class MemoryPersistence:
    """Create and store Memory only after request, decision, and source checks."""

    memory_store: MemoryStore
    event_history: EventHistory
    write_fence: RuntimeWriteFence | None = None
    memory_revision_lineage: MemoryRevisionLineage | None = None

    def __post_init__(self) -> None:
        if self.write_fence is not None:
            self.memory_store.bind_write_fence(self.write_fence)
        if self.memory_revision_lineage is None:
            if getattr(self.event_history, "fork_manifest_bytes", None) is not None:
                raise PermissionError("branched Memory persistence requires its verified revision view")
            if isinstance(self.event_history.timeline_id, str) and self.event_history.timeline_id:
                self.memory_revision_lineage = MemoryRevisionLineage.root(self.event_history.timeline_id)
        if self.memory_revision_lineage is not None:
            if self.memory_revision_lineage.timeline_id != self.event_history.timeline_id:
                raise PermissionError("Memory persistence revision view belongs to another Timeline")
            self.memory_revision_lineage.verify_event_history(self.event_history)
            self.memory_store.bind_revision_lineage(self.memory_revision_lineage)

    def bind_write_fence(self, fence: RuntimeWriteFence) -> None:
        if self.write_fence is not None and self.write_fence is not fence:
            raise ValueError("MemoryPersistence is already bound to another runtime fence")
        self.write_fence = fence
        self.memory_store.bind_write_fence(fence)

    def save(self, request: MemoryWriteRequest) -> Memory:
        from cognitive_world.cognition.l1_consumption_proof import (
            PROOF_MEMORY_TYPE, NONVERBAL_PROOF_MEMORY_TYPE,
        )
        fence = self.write_fence or self.memory_store.write_fence
        if not isinstance(request, MemoryWriteRequest):
            raise TypeError("request must be a MemoryWriteRequest")
        if request.schema_version == 2 and fence is None:
            raise PermissionError("formal Memory/v2 persistence requires RuntimeWriteFence")
        scope = nullcontext() if fence is None else fence.commit_scope()
        with scope:
            if fence is not None:
                fence.require_candidate_origin(request.runtime_write_permit)
            if request.schema_version == 2:
                if self.memory_revision_lineage is None:
                    raise PermissionError("formal Memory/v2 requires a bound branch revision view")
                self.memory_revision_lineage.verify_event_history(self.event_history)
                verified_history = fence._verify_complete_event_history(self.event_history)

            proposal = request.validate_authorization()
            if request.memory_type in {PROOF_MEMORY_TYPE, NONVERBAL_PROOF_MEMORY_TYPE}:
                raise PermissionError("ordinary Memory decisions cannot create system L1 proofs")
            if proposal.source_event_id != request.source_event_id:
                raise ValueError("Request source does not match Proposal source")
            if self.event_history.get_event(proposal.source_event_id) is None:
                raise ValueError(
                    f"source Event not found in EventHistory: {proposal.source_event_id}"
                )

            if request.schema_version == 2:
                verified_events, _, _ = verified_history
                if proposal.source_event_id not in {event.id for event in verified_events}:
                    raise PermissionError(
                        "Memory source Event is absent from the verified EventHistory lineage"
                    )
                provenance = request.decision_provenance
                if (provenance is None or self.event_history.timeline_id != provenance.timeline_id
                        or provenance.owner_id != request.owner_id
                        or proposal.source_event_id not in provenance.source_event_ids):
                    raise PermissionError("formal decision context differs from active persistence boundary")
                memory = Memory(
                    id=request.memory_id, owner_id=request.owner_id,
                    type=request.memory_type, content=request.content,
                    importance=request.importance, source_event=proposal.source_event_id,
                    metadata=request.metadata, schema_version=2,
                    decision_provenance=provenance,
                    logical_record_id=request.logical_record_id,
                    supersedes_record_id=request.supersedes_record_id,
                )
                request.validate_formal_memory(memory)
                self.memory_store._commit_memory(
                    memory, authorization=request,
                    persistence_authority=_MEMORY_PERSISTENCE_AUTHORITY,
                )
            else:
                memory = Memory(
                    id=request.memory_id,
                    owner_id=request.owner_id,
                    type=request.memory_type,
                    content=request.content,
                    importance=request.importance,
                    source_event=request.source_event_id,
                    metadata=request.metadata,
                )
                self.memory_store._commit_memory(memory)
            return memory
