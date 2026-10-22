"""Boundary interface for deciding whether proposals enter long-term Memory."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cognitive_world.cognition.memory_decision import MemoryDecision
    from cognitive_world.cognition.memory_proposal import MemoryProposal
    from cognitive_world.event.history import EventHistory
    from cognitive_world.runtime.write_fence import RuntimeWriteFence


class MemoryDecisionEngine:
    """Evaluate proposals only through an explicitly installed host policy."""

    def __init__(self, *, policy: object | None = None, authority: object | None = None,
                 event_history: object | None = None, write_fence: object | None = None) -> None:
        self._policy = policy
        self._authority = authority
        self._event_history = event_history
        self._write_fence = write_fence

    def decide(self, proposal: "MemoryProposal") -> "MemoryDecision":
        """Return a policy-bound result; missing dependencies fail closed."""
        from cognitive_world.cognition.memory_proposal import MemoryProposal
        from cognitive_world.memory.decision_policy import (
            MemoryPolicyOutput,
            build_decision_input, proposal_digest,
        )
        from cognitive_world.memory.memory_decision import (
            MemoryDecisionAuthority, _POLICY_ENGINE_AUTHORITY,
        )

        if self._policy is None:
            raise NotImplementedError("no Memory decision policy is installed")
        if (self._authority is None or self._event_history is None
                or self._write_fence is None):
            raise PermissionError("formal Memory decisions require an explicitly assembled policy boundary")
        if type(proposal) is not MemoryProposal:
            raise TypeError("formal Memory decisions require the canonical MemoryProposal")
        if not isinstance(self._authority, MemoryDecisionAuthority):
            raise TypeError("formal Memory decisions require MemoryDecisionAuthority")
        if not callable(getattr(self._policy, "evaluate", None)):
            raise TypeError("installed Memory policy must implement evaluate")
        policy_id = getattr(self._policy, "policy_id", None)
        policy_version = getattr(self._policy, "policy_version", None)
        if (not isinstance(policy_id, str) or not policy_id
                or not isinstance(policy_version, str) or not policy_version):
            raise ValueError("installed Memory policy requires explicit ID and version")

        permit = proposal.runtime_write_permit
        self._write_fence.require_candidate_origin(permit)
        timeline_id = getattr(self._event_history, "timeline_id", None)
        if not isinstance(timeline_id, str) or not timeline_id:
            raise PermissionError("formal Memory decision requires a timeline-bound EventHistory")
        if self._event_history.get_event(proposal.source_event_id) is None:
            raise PermissionError("formal Memory decision source Event is absent")
        original_digest = proposal_digest(proposal)
        decision_input = build_decision_input(
            proposal, timeline_id=timeline_id,
            session_id=permit.session_id,
            restore_generation=permit.restore_generation,
        )
        if decision_input.proposal_digest != original_digest:
            raise RuntimeError("Memory proposal changed during input construction")

        output = self._policy.evaluate(decision_input)
        if type(output) is not MemoryPolicyOutput or output.schema_version != 1:
            raise ValueError("installed Memory policy returned an unsupported output")
        if proposal_digest(proposal) != original_digest:
            raise PermissionError("Memory proposal changed during policy evaluation")
        self._write_fence.require_candidate_origin(permit)
        return self._authority._issue_policy_result(
            issuer=_POLICY_ENGINE_AUTHORITY,
            proposal=proposal,
            decision_input=decision_input,
            output=output,
            policy_id=policy_id,
            policy_version=policy_version,
            permit=permit,
            timeline_id=timeline_id,
        )


# Deprecated compatibility alias for the former cognition-layer name.
MemoryConsolidator = MemoryDecisionEngine
