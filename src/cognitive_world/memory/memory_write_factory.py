"""Issue MemoryWriteRequests from authorized decisions and matching proposals."""

from copy import deepcopy

from cognitive_world.cognition.memory_proposal import MemoryProposal
from cognitive_world.memory.memory_decision import MemoryDecision
from cognitive_world.memory.memory_write import (
    _FACTORY_AUTHORITY,
    MemoryWriteRequest,
)


class MemoryWriteFactory:
    """Convert an intact, authorized accepted decision into a sealed request."""

    def create_request(
        self, decision: MemoryDecision, proposal: MemoryProposal
    ) -> MemoryWriteRequest:
        if not isinstance(decision, MemoryDecision):
            raise TypeError("decision must be a MemoryDecision")
        if not isinstance(proposal, MemoryProposal):
            raise TypeError("proposal must be a MemoryProposal")
        if decision.proposal_id != proposal.id or decision.proposal != proposal:
            raise ValueError("decision does not reference the supplied proposal")
        if not decision.accepted:
            raise ValueError("MemoryWriteRequest requires an accepted decision")
        if not decision.is_authorized():
            raise PermissionError("MemoryDecision was not issued by an authority")
        formal = decision.provenance is not None
        if formal and not decision.is_policy_authorized():
            raise PermissionError("formal Memory/v2 requires an installed-policy decision")

        return MemoryWriteRequest._issue(
            authority=_FACTORY_AUTHORITY,
            decision=decision,
            proposal=proposal,
            memory_id=f"memory:{proposal.id}",
            owner_id=proposal.owner_id,
            source_event_id=proposal.source_event_id,
            content=deepcopy(proposal.content),
            memory_type=decision.memory_type,
            importance=decision.importance,
            metadata={
                "proposal_metadata": deepcopy(proposal.metadata),
                "decision_metadata": deepcopy(decision.metadata),
            },
            schema_version=2 if formal else 1,
            provenance=decision.provenance,
            logical_record_id=proposal.logical_record_id if formal else None,
            supersedes_record_id=proposal.supersedes_record_id if formal else None,
        )


MemoryWriteRequestFactory = MemoryWriteFactory
