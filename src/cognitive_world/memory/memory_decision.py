"""Authorized decision records for Memory proposals."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from cognitive_world.cognition.memory import MemoryDecisionProvenanceV2
from cognitive_world.cognition.memory_proposal import MemoryProposal
from cognitive_world.memory.decision_policy import (
    MemoryDecisionInput, MemoryDecisionResult, MemoryPolicyOutput,
)


_DECISION_AUTHORITY = object()
_POLICY_ENGINE_AUTHORITY = object()


@dataclass(frozen=True, init=False)
class MemoryDecision:
    """A decision snapshot; only authority-issued instances can authorize writes."""

    proposal_id: str
    accepted: bool
    importance: float
    memory_type: str
    proposal: MemoryProposal
    metadata: dict[str, Any]
    result: MemoryDecisionResult
    provenance: MemoryDecisionProvenanceV2 | None
    _policy_call: tuple[Any, ...] | None = field(default=None, repr=False, compare=False)
    _seal: object | None = field(default=None, repr=False, compare=False)
    _signed_snapshot: tuple[Any, ...] | None = field(
        default=None, repr=False, compare=False
    )

    def __init__(
        self,
        proposal_id: str,
        accepted: bool,
        importance: float,
        memory_type: str,
        proposal: MemoryProposal,
        metadata: dict[str, Any] | None = None,
        result: MemoryDecisionResult | None = None,
        provenance: MemoryDecisionProvenanceV2 | None = None,
        policy_call: tuple[Any, ...] | None = None,
        *,
        _seal: object | None = None,
    ) -> None:
        copied_proposal = deepcopy(proposal)
        copied_metadata = deepcopy(metadata if metadata is not None else {})
        resolved_result = result or (
            MemoryDecisionResult.ACCEPTED if accepted else MemoryDecisionResult.REJECTED
        )
        if type(resolved_result) is not MemoryDecisionResult:
            raise TypeError("decision result must be a MemoryDecisionResult")
        if bool(accepted) != (resolved_result is MemoryDecisionResult.ACCEPTED):
            raise ValueError("accepted flag must match the decision result")
        if provenance is not None and type(provenance) is not MemoryDecisionProvenanceV2:
            raise TypeError("formal decision provenance has an unsupported type")
        object.__setattr__(self, "proposal_id", proposal_id)
        object.__setattr__(self, "accepted", accepted)
        object.__setattr__(self, "importance", importance)
        object.__setattr__(self, "memory_type", memory_type)
        object.__setattr__(self, "proposal", copied_proposal)
        object.__setattr__(self, "metadata", copied_metadata)
        object.__setattr__(self, "result", resolved_result)
        object.__setattr__(self, "provenance", deepcopy(provenance))
        object.__setattr__(self, "_policy_call", deepcopy(policy_call))
        object.__setattr__(self, "_seal", _seal)
        snapshot = self._state() if _seal is _DECISION_AUTHORITY else None
        object.__setattr__(self, "_signed_snapshot", deepcopy(snapshot))
        if proposal_id != copied_proposal.id:
            raise ValueError("proposal_id must match the referenced proposal")

    def _state(self) -> tuple[Any, ...]:
        return (
            self.proposal_id,
            self.accepted,
            self.importance,
            self.memory_type,
            self.proposal,
            self.metadata,
            self.result,
            self.provenance,
            self._policy_call,
        )

    def is_authorized(self) -> bool:
        """Check the issuing capability and that the decision snapshot is intact."""
        return (
            self._seal is _DECISION_AUTHORITY
            and self._signed_snapshot == self._state()
        )

    def is_policy_authorized(self) -> bool:
        if (not self.is_authorized() or self.provenance is None
                or self._policy_call is None
                or self.result is not MemoryDecisionResult.ACCEPTED):
            return False
        try:
            policy_id, policy_version, call_id, decision_input, output, permit = self._policy_call
            provenance = self.provenance
            return bool(
                provenance.decision_id == call_id
                and provenance.policy_id == policy_id
                and provenance.policy_version == policy_version
                and provenance.proposal_id == decision_input.proposal_id == self.proposal_id
                and provenance.proposal_digest == decision_input.proposal_digest
                and provenance.input_digest == decision_input.input_digest
                and provenance.owner_id == decision_input.owner_id == self.proposal.owner_id
                and provenance.source_event_ids == decision_input.source_event_ids
                and provenance.timeline_id == decision_input.timeline_id
                and provenance.session_id == permit.session_id
                and provenance.restore_generation == permit.restore_generation
                and provenance.outcome == output.result.value == self.result.value
                and output.importance == self.importance
            )
        except (AttributeError, TypeError, ValueError):
            return False


@dataclass(frozen=True)
class MemoryDecisionAuthority:
    """Issue signed decisions supplied by an explicitly trusted decision policy.

    This class does not evaluate proposals. The caller must provide the result
    of its own authorized decision process.
    """

    def issue(
        self,
        proposal: MemoryProposal,
        *,
        accepted: bool,
        importance: float,
        memory_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryDecision:
        if not isinstance(proposal, MemoryProposal):
            raise TypeError("proposal must be a MemoryProposal")
        if type(accepted) is not bool:
            raise TypeError("legacy accepted must be bool")
        return MemoryDecision(
            proposal_id=proposal.id,
            accepted=accepted,
            importance=importance,
            memory_type=memory_type,
            proposal=proposal,
            metadata=metadata,
            _seal=_DECISION_AUTHORITY,
        )

    def _issue_policy_result(
        self, *, issuer: object, proposal: MemoryProposal,
        decision_input: MemoryDecisionInput, output: MemoryPolicyOutput,
        policy_id: str, policy_version: str, permit: object, timeline_id: str,
    ) -> MemoryDecision:
        """Seal only the policy-engine invocation path, never caller booleans."""
        if issuer is not _POLICY_ENGINE_AUTHORITY:
            raise PermissionError("formal decisions require the installed policy engine")
        if type(proposal) is not MemoryProposal or type(decision_input) is not MemoryDecisionInput:
            raise TypeError("formal decision inputs have unsupported types")
        if type(output) is not MemoryPolicyOutput or output.schema_version != 1:
            raise ValueError("formal policy output schema is unsupported")
        from cognitive_world.memory.decision_policy import validate_decision_input
        validate_decision_input(
            decision_input, proposal,
            session_id=getattr(permit, "session_id", ""),
            restore_generation=getattr(permit, "restore_generation", -1),
            timeline_id=timeline_id,
        )
        if not isinstance(policy_id, str) or not policy_id or not isinstance(policy_version, str) or not policy_version:
            raise ValueError("installed policy identity must be explicit")
        result = output.result
        accepted = result is MemoryDecisionResult.ACCEPTED
        provenance = None
        if accepted:
            provenance = MemoryDecisionProvenanceV2(
                schema_version=2,
                decision_id=str(uuid4()),
                policy_id=policy_id,
                policy_version=policy_version,
                proposal_id=decision_input.proposal_id,
                proposal_digest=decision_input.proposal_digest,
                input_digest=decision_input.input_digest,
                reason_code=output.reason_code,
                owner_id=decision_input.owner_id,
                source_event_ids=decision_input.source_event_ids,
                timeline_id=decision_input.timeline_id,
                session_id=decision_input.session_id,
                restore_generation=decision_input.restore_generation,
                supersedes_record_id=decision_input.supersedes_record_id,
                outcome=result.value,
            )
        policy_call = (
            policy_id, policy_version, provenance.decision_id if provenance is not None else None,
            decision_input, output, permit,
        )
        return MemoryDecision(
            proposal_id=proposal.id,
            accepted=accepted,
            importance=float(output.importance),
            memory_type=proposal.memory_type,
            proposal=proposal,
            metadata={"reason_code": output.reason_code},
            result=result,
            provenance=provenance,
            policy_call=policy_call,
            _seal=_DECISION_AUTHORITY,
        )
