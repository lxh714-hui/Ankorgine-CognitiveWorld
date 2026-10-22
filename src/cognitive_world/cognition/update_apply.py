"""Apply cognition proposals only after validator authorization."""

from copy import deepcopy
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from cognitive_world.cognition.belief import Belief, BeliefStore
from cognitive_world.cognition.belief_update import BeliefUpdateProposal
from cognitive_world.cognition.goal import Goal, GoalStore
from cognitive_world.cognition.goal_update import GoalUpdateProposal
from cognitive_world.cognition.validation import ValidationResult
from cognitive_world.cognition.proposal_origin import original_proposal_permit
from cognitive_world.cognition.self_model import SelfModel, SelfModelStore
from cognitive_world.runtime.write_fence import RuntimeWriteFence


@dataclass
class CognitiveUpdateApplier:
    """Commit validated Belief and Goal proposals to their authoritative stores."""

    belief_store: BeliefStore
    goal_store: GoalStore
    self_model_store: SelfModelStore | None = None
    write_fence: RuntimeWriteFence | None = None

    def __post_init__(self) -> None:
        if self.write_fence is not None:
            self.belief_store.bind_write_fence(self.write_fence)
            self.goal_store.bind_write_fence(self.write_fence)
            if self.self_model_store is not None:
                self.self_model_store.bind_write_fence(self.write_fence)

    def apply(self, proposal: Any, validation_result: ValidationResult) -> Belief | Goal | SelfModel:
        """Apply a validator-approved proposal and return the stored snapshot."""
        scope = (nullcontext() if self.write_fence is None
                 else self.write_fence.commit_scope())
        with scope:
            return self._apply(proposal, validation_result)

    def _apply(self, proposal: Any, validation_result: ValidationResult) -> Belief | Goal | SelfModel:
        if self.write_fence is not None:
            self.write_fence.require_candidate_origin(
                original_proposal_permit(proposal)
            )
        if not isinstance(validation_result, ValidationResult) or not (
            validation_result.authorizes(proposal)
        ):
            raise PermissionError("proposal has no matching accepted validation")

        if isinstance(proposal, BeliefUpdateProposal):
            current = self.belief_store.get_by_id(proposal.belief_id)
            if current is None or current.owner_id != proposal.owner_id:
                raise ValueError("target Belief does not exist for proposal owner")
            if current.content != proposal.change.previous_value:
                raise ValueError("Belief changed since proposal was created")

            metadata = deepcopy(current.metadata)
            metadata.update(deepcopy(proposal.metadata))
            updated = Belief(
                belief_id=current.belief_id,
                owner_id=current.owner_id,
                content=proposal.change.proposed_value,
                source_refs=proposal.source_refs,
                confidence=proposal.confidence,
                metadata=metadata,
            )
            self.belief_store.update(
                updated, proposal=proposal, validation_result=validation_result
            )
            result = self.belief_store.get_by_id(updated.belief_id)
            assert result is not None
            return result

        if isinstance(proposal, GoalUpdateProposal):
            current = self.goal_store.get_owned(proposal.owner_id, proposal.goal_id)
            if current is None:
                raise ValueError("target Goal does not exist for proposal owner")
            if (
                current.status != proposal.change.previous_state
                or current.priority != proposal.change.previous_priority
            ):
                raise ValueError("Goal changed since proposal was created")

            metadata = deepcopy(current.metadata)
            metadata.update(deepcopy(proposal.metadata))
            updated = Goal(
                goal_id=current.goal_id,
                owner_id=current.owner_id,
                description=current.description,
                priority=proposal.change.proposed_priority,
                status=proposal.change.proposed_state,
                source_refs=proposal.source_refs,
                metadata=metadata,
                resource_demands=current.resource_demands,
            )
            self.goal_store.update(
                updated, proposal=proposal, validation_result=validation_result
            )
            result = self.goal_store.get_owned(updated.owner_id, updated.goal_id)
            assert result is not None
            return result

        from cognitive_world.cognition.self_model_evolution import SelfModelUpdateProposal
        if isinstance(proposal, SelfModelUpdateProposal):
            if self.self_model_store is None:
                raise TypeError("SelfModelStore is required for SelfModel updates")
            current = self.self_model_store.get(proposal.owner_id)
            if current is None:
                raise ValueError("SelfModel target does not exist for proposal owner")
            if tuple(current.self_beliefs) != proposal.previous_self_beliefs:
                raise ValueError("SelfModel changed since proposal was created")
            if len(current.self_beliefs) >= 32:
                raise ValueError("SelfModel tentative self-belief capacity reached")
            record = {
                "claim": proposal.claim,
                "status": "tentative",
                "source_refs": list(proposal.source_refs),
                "source_event_ids": list(proposal.source_event_ids),
            }
            updated = SelfModel(
                owner_id=current.owner_id,
                identity=current.identity,
                capabilities=current.capabilities,
                limitations=current.limitations,
                self_beliefs=[*deepcopy(current.self_beliefs), record],
                metadata=current.metadata,
            )
            self.self_model_store.update(
                updated, proposal=proposal, validation_result=validation_result
            )
            result = self.self_model_store.get(proposal.owner_id)
            assert result is not None
            return result

        raise TypeError("unsupported cognition update proposal")
