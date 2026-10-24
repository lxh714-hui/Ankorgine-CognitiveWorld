"""Read-isolated storage for cognition-layer Memory records."""

from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from cognitive_world.cognition.memory import Memory, SystemOnlyMemoryContent
from cognitive_world.runtime.write_fence import RuntimeWriteFence


_L1_PROOF_WRITE_AUTHORITY = object()
_MEMORY_PERSISTENCE_AUTHORITY = object()


@dataclass
class MemoryStore:
    """Save and query Memory records without forming or interpreting them."""

    _memories: dict[str, Memory] = field(default_factory=dict, repr=False)
    write_fence: RuntimeWriteFence | None = field(default=None, repr=False, compare=False)
    _revision_lineage: object | None = field(default=None, repr=False, compare=False)

    @staticmethod
    def is_semantically_retrievable(memory: Memory) -> bool:
        """Return whether a canonical record may enter an NPC semantic view.

        System-only content carries a typed marker. The existing proof record
        discriminators are also reserved here so malformed records declaring a
        known system type fail closed instead of becoming ordinary memories.
        This classification grants no write or verification authority.
        """
        if not isinstance(memory, Memory):
            return False
        if not isinstance(getattr(memory, "type", None), str) or not memory.type:
            return False
        from cognitive_world.cognition.l1_consumption_proof import (
            PROOF_MEMORY_TYPE, NONVERBAL_PROOF_MEMORY_TYPE,
        )
        if memory.type.startswith(("system_l1_", "system_action_")):
            return False
        return not isinstance(memory.content, SystemOnlyMemoryContent)

    @classmethod
    def from_isolated_snapshot(
        cls, records: tuple[Memory, ...], *, revision_lineage: object | None = None,
    ) -> "MemoryStore":
        """Rebuild an unbound, isolated Store from prevalidated records.

        This is a staging constructor for snapshot validation only. It does
        not establish record provenance or bind the result to a Runtime.
        """
        if not isinstance(records, tuple) or any(type(item) is not Memory for item in records):
            raise TypeError("isolated Memory snapshot must contain a tuple of Memory records")
        store = cls(_revision_lineage=revision_lineage)
        for memory in records:
            if not memory.id or not memory.owner_id or memory.id in store._memories:
                raise ValueError("isolated Memory snapshot has invalid or duplicate identity")
            store._memories[memory.id] = deepcopy(memory)
        return store

    def bind_write_fence(self, fence: RuntimeWriteFence) -> None:
        if self.write_fence is not None and self.write_fence is not fence:
            raise ValueError("MemoryStore is already bound to another runtime fence")
        self.write_fence = fence

    def bind_revision_lineage(self, lineage: object) -> None:
        from cognitive_world.cognition.memory_revision import MemoryRevisionLineage
        if type(lineage) is not MemoryRevisionLineage:
            raise TypeError("MemoryStore requires a verified MemoryRevisionLineage")
        lineage._require_issued()
        if self._revision_lineage is not None:
            if type(self._revision_lineage) is not MemoryRevisionLineage:
                raise PermissionError("MemoryStore has an invalid existing revision view")
            self._revision_lineage._require_issued()
            if self._revision_lineage != lineage:
                raise PermissionError("MemoryStore revision view is immutable once bound")
        self._revision_lineage = lineage

    @property
    def memories(self) -> Mapping[str, Memory]:
        """Return a read-only snapshot of the stored memories."""
        return MappingProxyType(deepcopy(self._memories))

    def _commit_memory(self, memory: Memory, *, authorization: object | None = None,
                       persistence_authority: object | None = None) -> None:
        """Commit a Memory for use by the persistence boundary only."""
        if not self.is_semantically_retrievable(memory):
            raise PermissionError("system-only records require their trusted commit path")
        if type(memory) is not Memory:
            raise TypeError("MemoryStore accepts canonical Memory records only")
        if memory.schema_version == 2:
            if (self.write_fence is None or authorization is None
                    or persistence_authority is not _MEMORY_PERSISTENCE_AUTHORITY):
                raise PermissionError("Memory/v2 requires a fenced formal persistence request")
            validator = getattr(authorization, "validate_formal_memory", None)
            if not callable(validator):
                raise PermissionError("Memory/v2 authorization is not a formal write request")
            validator(memory)
            with self.write_fence.commit_scope() as permit:
                self.write_fence.require_candidate_origin(authorization.runtime_write_permit)
                if authorization.runtime_write_permit is not permit:
                    raise PermissionError("Memory/v2 request belongs to another Runtime operation")
                prior = self._memories.get(memory.id)
                if prior is not None:
                    if prior != memory:
                        raise PermissionError("conflicting immutable Memory revision identity")
                    return
                from cognitive_world.cognition.memory_revision import MemoryRevisionLineage
                lineage = self._revision_lineage
                if type(lineage) is not MemoryRevisionLineage:
                    raise PermissionError("Memory/v2 requires a verified branch-local revision view")
                lineage._require_issued()
                if lineage.timeline_id != memory.decision_provenance.timeline_id:
                    raise PermissionError("Memory/v2 Timeline differs from the bound revision view")
                lineage.validate_records((*self.get_all_memories(), memory))
                if memory.supersedes_record_id is not None:
                    predecessor = self._memories.get(memory.supersedes_record_id)
                    if (predecessor is None or predecessor.owner_id != memory.owner_id
                            or predecessor.logical_record_id != memory.logical_record_id):
                        raise PermissionError("Memory revision predecessor is absent or mismatched")
                    if any(item.supersedes_record_id == memory.supersedes_record_id
                           and item.logical_record_id == memory.logical_record_id
                           for item in self._memories.values()):
                        raise PermissionError("Memory revision predecessor already has a successor")
                elif any(item.logical_record_id == memory.logical_record_id
                         for item in self._memories.values()):
                    raise PermissionError("new Memory logical identity already exists")
                self._memories[memory.id] = deepcopy(memory)
            return
        def commit_legacy_record() -> None:
            prior = self._memories.get(memory.id)
            if prior is not None:
                from cognitive_world.cognition.snapshot import cognitive_snapshot_codec
                if cognitive_snapshot_codec().dumps(prior) != cognitive_snapshot_codec().dumps(memory):
                    raise PermissionError("conflicting immutable Memory identity")
                return
            lineage = self._revision_lineage
            if lineage is not None:
                from cognitive_world.cognition.memory_revision import MemoryRevisionLineage
                if type(lineage) is not MemoryRevisionLineage:
                    raise PermissionError("Memory write has an invalid revision view")
                lineage._require_issued()
                lineage.validate_records((*self.get_all_memories(), memory))
            self._memories[memory.id] = deepcopy(memory)

        if self.write_fence is None:
            commit_legacy_record()
            return
        with self.write_fence.commit_scope():
            commit_legacy_record()

    def _commit_system_proof(self, memory: Memory, *, authority: object,
                             permit: object) -> None:
        """Commit an issuer-built proof under the same lock used by snapshots."""
        from cognitive_world.cognition.l1_consumption_proof import (
            L1ConsumptionProof, NonverbalL1ConsumptionProof,
            PROOF_MEMORY_TYPE, NONVERBAL_PROOF_MEMORY_TYPE,
        )
        if authority is not _L1_PROOF_WRITE_AUTHORITY or self.write_fence is None:
            raise PermissionError("system proof has no trusted Runtime issuer")
        from cognitive_world.cognition.l1_instance import INSTANCE_PROOF_MEMORY_TYPE, InstanceL1ConsumptionProof
        valid_types = {
            INSTANCE_PROOF_MEMORY_TYPE: InstanceL1ConsumptionProof,
            PROOF_MEMORY_TYPE: L1ConsumptionProof,
            NONVERBAL_PROOF_MEMORY_TYPE: NonverbalL1ConsumptionProof,
        }
        if (memory.type not in valid_types or type(memory.content) is not valid_types[memory.type]
                or memory.id != memory.content.proof_id
                or memory.owner_id != memory.content.owner_id
                or memory.source_event != memory.content.source_event_id):
            raise PermissionError("system proof record does not match its signed identity")
        with self.write_fence.commit_scope():
            self.write_fence.require_candidate_origin(permit)
            if memory.type == INSTANCE_PROOF_MEMORY_TYPE:
                from cognitive_world.cognition.l1_instance import validate_instance_proof_structure
                validate_instance_proof_structure(memory.content)
            prior = self._memories.get(memory.id)
            if prior is not None:
                if prior != memory:
                    raise PermissionError("conflicting L1 proof identity")
                return
            self._memories[memory.id] = deepcopy(memory)

    def _commit_action_record(self, memory, *, authority, permit):
        """B3 exact records only; independent from L1 proof authority."""
        from cognitive_world.cognition.action_expectation import (
            _AUTHORITY, ActionExpectationRecord, ActionResultAssociation,
            EXPECTATION_TYPE, ASSOCIATION_TYPE, validate_structure,
        )
        if authority is not _AUTHORITY or self.write_fence is None:
            raise PermissionError("B3 write has no Runtime issuer")
        from cognitive_world.cognition.action_expectation_source import (
            SOURCE_TYPE,ActionExpectationSourceBinding,verify_source_records,
        )
        types = {EXPECTATION_TYPE: ActionExpectationRecord, ASSOCIATION_TYPE: ActionResultAssociation,
                 SOURCE_TYPE:ActionExpectationSourceBinding}
        if (memory.type not in types or type(memory.content) is not types[memory.type]
                or memory.id != memory.content.record_id or memory.owner_id != memory.content.owner_id
                or memory.source_event != (memory.content.event_id if memory.type == ASSOCIATION_TYPE else "")):
            raise PermissionError("B3 record envelope mismatch")
        validate_structure(memory.content)
        with self.write_fence.commit_scope():
            self.write_fence.require_candidate_origin(permit)
            prior = self._memories.get(memory.id)
            if prior is not None and prior != memory:
                raise PermissionError("conflicting immutable B3 record")
            if prior is None:
                context=self.write_fence._event_history_verification_context
                if context is None:
                    raise PermissionError("B3 Store lacks canonical source verification authority")
                verify_source_records((*self.get_all_memories(),memory),context[3])
                self._memories[memory.id] = deepcopy(memory)

    def get_memory(self, memory_id: str) -> Memory | None:
        """Return an isolated copy of a Memory by identifier."""
        memory = self._memories.get(memory_id)
        return deepcopy(memory) if memory is not None else None

    def get_memories_by_owner(self, owner_id: str) -> tuple[Memory, ...]:
        """Return isolated copies of memories belonging to an owner."""
        return tuple(
            deepcopy(memory)
            for memory in self._memories.values()
            if memory.owner_id == owner_id
        )

    def get_all_memories(self) -> tuple[Memory, ...]:
        """Return isolated copies of all stored memories in insertion order."""
        return tuple(deepcopy(list(self._memories.values())))
