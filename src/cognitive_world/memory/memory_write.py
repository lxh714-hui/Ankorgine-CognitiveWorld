"""Read-isolated write requests signed from an authorized MemoryDecision."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from cognitive_world.cognition.memory_proposal import MemoryProposal
from cognitive_world.cognition.memory import MemoryDecisionProvenanceV2
from cognitive_world.memory.memory_decision import MemoryDecision
from cognitive_world.runtime.write_fence import RuntimeWritePermit


_FACTORY_AUTHORITY = object()


@dataclass(frozen=True)
class MemoryWriteAuthorizationSnapshot:
    """Deep snapshot of proposal, decision, references, and committed fields."""

    proposal: MemoryProposal
    decision_fields: tuple[Any, ...]
    source_refs: tuple[str, ...]
    memory_fields: tuple[Any, ...]
    runtime_write_permit: RuntimeWritePermit | None
    schema_version: int
    provenance: MemoryDecisionProvenanceV2 | None
    logical_record_id: str | None
    supersedes_record_id: str | None
    decision: MemoryDecision


class MemoryWriteRequest:
    """A factory-issued request whose public values are copy-only properties."""

    __slots__ = (
        "_memory_id",
        "_owner_id",
        "_source_event_id",
        "_content",
        "_memory_type",
        "_importance",
        "_metadata",
        "_authority",
        "_authorization_snapshot",
        "_runtime_write_permit",
        "_schema_version",
        "_provenance",
        "_logical_record_id",
        "_supersedes_record_id",
    )

    def __init__(
        self,
        memory_id: str,
        owner_id: str,
        source_event_id: str,
        content: Any,
        memory_type: str,
        importance: float,
        metadata: dict[str, Any] | None = None,
        schema_version: int = 1,
        provenance: MemoryDecisionProvenanceV2 | None = None,
        logical_record_id: str | None = None,
        supersedes_record_id: str | None = None,
    ) -> None:
        self._memory_id = memory_id
        self._owner_id = owner_id
        self._source_event_id = source_event_id
        self._content = deepcopy(content)
        self._memory_type = memory_type
        self._importance = importance
        self._metadata = deepcopy(metadata if metadata is not None else {})
        self._authority = None
        self._authorization_snapshot = None
        self._runtime_write_permit = None
        self._schema_version = schema_version
        self._provenance = deepcopy(provenance)
        self._logical_record_id = logical_record_id
        self._supersedes_record_id = supersedes_record_id

    @property
    def memory_id(self) -> str:
        return self._memory_id

    @property
    def owner_id(self) -> str:
        return self._owner_id

    @property
    def source_event_id(self) -> str:
        return self._source_event_id

    @property
    def content(self) -> Any:
        return deepcopy(self._content)

    @property
    def memory_type(self) -> str:
        return self._memory_type

    @property
    def importance(self) -> float:
        return self._importance

    @property
    def metadata(self) -> dict[str, Any]:
        return deepcopy(self._metadata)

    @property
    def authorization_snapshot(self) -> MemoryWriteAuthorizationSnapshot | None:
        """Return an isolated view of the retained authorization evidence."""
        return deepcopy(self._authorization_snapshot)

    @property
    def runtime_write_permit(self) -> RuntimeWritePermit | None:
        """Retain the originating proposal's permit without allowing replacement."""
        return self._runtime_write_permit

    @property
    def schema_version(self) -> int:
        return self._schema_version

    @property
    def decision_provenance(self) -> MemoryDecisionProvenanceV2 | None:
        return deepcopy(self._provenance)

    @property
    def logical_record_id(self) -> str | None:
        return self._logical_record_id

    @property
    def supersedes_record_id(self) -> str | None:
        return self._supersedes_record_id

    @classmethod
    def _issue(
        cls,
        *,
        authority: object,
        decision: MemoryDecision,
        proposal: MemoryProposal,
        memory_id: str,
        owner_id: str,
        source_event_id: str,
        content: Any,
        memory_type: str,
        importance: float,
        metadata: dict[str, Any],
        schema_version: int = 1,
        provenance: MemoryDecisionProvenanceV2 | None = None,
        logical_record_id: str | None = None,
        supersedes_record_id: str | None = None,
    ) -> "MemoryWriteRequest":
        if authority is not _FACTORY_AUTHORITY:
            raise PermissionError("MemoryWriteRequest can only be issued by its factory")
        if not decision.is_authorized() or not decision.accepted:
            raise ValueError("MemoryWriteRequest requires an authorized accepted decision")

        request = cls(
            memory_id,
            owner_id,
            source_event_id,
            content,
            memory_type,
            importance,
            metadata,
            schema_version,
            provenance,
            logical_record_id,
            supersedes_record_id,
        )
        proposal_snapshot = deepcopy(proposal)
        decision_fields = deepcopy(
            (
                decision.proposal_id,
                decision.accepted,
                decision.importance,
                decision.memory_type,
                decision.proposal,
                decision.metadata,
            )
        )
        source_refs = _proposal_source_refs(proposal_snapshot)
        request._authority = _FACTORY_AUTHORITY
        request._runtime_write_permit = proposal_snapshot.runtime_write_permit
        request._authorization_snapshot = MemoryWriteAuthorizationSnapshot(
            proposal=proposal_snapshot,
            decision_fields=decision_fields,
            source_refs=source_refs,
            memory_fields=deepcopy(request._fields()),
            runtime_write_permit=request._runtime_write_permit,
            schema_version=schema_version,
            provenance=deepcopy(provenance),
            logical_record_id=logical_record_id,
            supersedes_record_id=supersedes_record_id,
            decision=decision,
        )
        request.validate_authorization()
        return request

    def _fields(self) -> tuple[Any, ...]:
        return (
            self._memory_id,
            self._owner_id,
            self._source_event_id,
            self._content,
            self._memory_type,
            self._importance,
            self._metadata,
            self._schema_version,
            self._provenance,
            self._logical_record_id,
            self._supersedes_record_id,
        )

    def validate_authorization(self) -> MemoryProposal:
        """Verify the request is unchanged and matches its authorized records."""
        snapshot = self._authorization_snapshot
        if self._authority is not _FACTORY_AUTHORITY or snapshot is None:
            raise ValueError("MemoryWriteRequest must be issued by MemoryWriteFactory")
        if self._fields() != snapshot.memory_fields:
            raise ValueError("MemoryWriteRequest was modified after authorization")
        if self._runtime_write_permit is not snapshot.runtime_write_permit:
            raise ValueError("MemoryWriteRequest runtime origin was modified")

        proposal = snapshot.proposal
        (
            proposal_id,
            accepted,
            decision_importance,
            decision_type,
            decision_proposal,
            _decision_metadata,
        ) = snapshot.decision_fields
        decision = snapshot.decision
        if not accepted:
            raise ValueError("MemoryWriteRequest requires an accepted decision")
        if proposal_id != proposal.id or decision_proposal != proposal:
            raise ValueError("authorized Decision does not match its Proposal")
        expected_version = 2 if decision.provenance is not None else 1
        if self._schema_version != expected_version:
            raise ValueError("MemoryWriteRequest schema differs from its Decision")
        if expected_version == 2 and not decision.is_policy_authorized():
            raise PermissionError("Memory/v2 requires an installed-policy decision")
        if snapshot.source_refs != _proposal_source_refs(proposal):
            raise ValueError("MemoryWriteRequest source references do not match Proposal")

        expected_fields = (
            f"memory:{proposal.id}",
            proposal.owner_id,
            proposal.source_event_id,
            proposal.content,
            decision_type,
            decision_importance,
            {
                "proposal_metadata": proposal.metadata,
                "decision_metadata": _decision_metadata,
            },
            expected_version,
            decision.provenance,
            proposal.logical_record_id if expected_version == 2 else None,
            proposal.supersedes_record_id if expected_version == 2 else None,
        )
        if self._fields() != expected_fields:
            raise ValueError("MemoryWriteRequest does not match authorized records")
        return deepcopy(proposal)

    def validate_formal_memory(self, memory: object) -> MemoryProposal:
        """Revalidate the exact formal record at the final Store boundary."""
        from cognitive_world.cognition.memory import Memory

        proposal = self.validate_authorization()
        snapshot = self._authorization_snapshot
        if (snapshot is None or snapshot.schema_version != 2
                or not snapshot.decision.is_policy_authorized()):
            raise PermissionError("formal Memory write lacks policy-call authorization")
        expected = Memory(
            id=self._memory_id, owner_id=self._owner_id, type=self._memory_type,
            content=self._content, importance=self._importance,
            source_event=self._source_event_id, metadata=self._metadata,
            schema_version=2, decision_provenance=self._provenance,
            logical_record_id=self._logical_record_id,
            supersedes_record_id=self._supersedes_record_id,
        )
        if type(memory) is not Memory or memory != expected:
            raise PermissionError("Memory/v2 candidate differs from its authorized request")
        if self._provenance != snapshot.provenance:
            raise PermissionError("Memory/v2 provenance differs from the sealed decision")
        return proposal


def _proposal_source_refs(proposal: MemoryProposal) -> tuple[str, ...]:
    refs = [proposal.source_event_id]
    observation_ref = proposal.metadata.get("source_observation_id")
    if isinstance(observation_ref, str) and observation_ref:
        refs.append(observation_ref)
    return tuple(refs)
