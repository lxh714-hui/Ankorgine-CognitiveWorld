"""Convert candidate ActionProposals into submitted Attempt records."""

from dataclasses import dataclass, field
from uuid import uuid4

from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.decision.attempt import Attempt
from cognitive_world.safety.governance import (
    UniversalSafetyGovernance,
    safety_input_from_proposal,
)


@dataclass
class ActionPipeline:
    """Create Attempt data from an ActionProposal without executing it."""

    safety_governance: UniversalSafetyGovernance = field(default_factory=UniversalSafetyGovernance)

    def __post_init__(self) -> None:
        if not isinstance(self.safety_governance, UniversalSafetyGovernance):
            raise TypeError("ActionPipeline requires UniversalSafetyGovernance")

    def bind_safety_governance(self, governance: UniversalSafetyGovernance) -> None:
        if not isinstance(governance, UniversalSafetyGovernance):
            raise TypeError("governance must be UniversalSafetyGovernance")
        self.safety_governance = governance

    def create_attempt(
        self, action_proposal: ActionProposal, *, initiator_id: str | None = None
    ) -> Attempt:
        """Convert a proposal to an Attempt while preserving its source reference."""
        if not isinstance(action_proposal, ActionProposal):
            raise TypeError("action_proposal must be an ActionProposal")
        try:
            safety_governance = self.safety_governance
        except AttributeError as exc:
            raise RuntimeError(
                "ActionPipeline subclasses must initialize safety_governance"
            ) from exc
        if not isinstance(safety_governance, UniversalSafetyGovernance):
            raise RuntimeError("ActionPipeline requires valid safety governance")
        safety_governance.require_action_allowed(
            safety_input_from_proposal(action_proposal, source="action_proposal")
        )
        # Import at the conversion boundary to keep Decision package import
        # independent of Resolution package initialization.
        from cognitive_world.resolution.causal import ActionInterpreter

        attempt = ActionInterpreter().interpret(
            action_proposal,
            attempt_id=f"attempt:{uuid4().hex}",
        )
        metadata = attempt.metadata
        metadata["action_proposal_reasoning_refs"] = action_proposal.reasoning_refs
        return Attempt(
            attempt_id=attempt.attempt_id,
            agent_id=attempt.agent_id,
            action_proposal_id=attempt.action_proposal_id,
            action_type=attempt.action_type,
            target_refs=attempt.target_refs,
            parameters=attempt.parameters,
            metadata=metadata,
            initiator_id=initiator_id,
        )
