"""Orchestrate a complete Agent action turn through Event creation."""

from dataclasses import dataclass, field, replace

from cognitive_world.agent.cognition_context import CognitionContext
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.agent.turn import AgentTurn
from cognitive_world.core.event import Event
from cognitive_world.decision.action_pipeline import ActionPipeline
from cognitive_world.decision.agent_decision import AgentDecision
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.decision.attempt import Attempt
from cognitive_world.event import EventFactory
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.result import ResolutionResult
from cognitive_world.runtime.clock import SimulationTime
from cognitive_world.resolution.provider_budget import provider_call_scope
from cognitive_world.safety.governance import (
    UniversalSafetyGovernance,
    safety_input_from_attempt,
    safety_input_from_proposal,
)
from cognitive_world.runtime.write_fence import RuntimeWriteFence


@dataclass(frozen=True)
class AgentTurnExecution:
    """Internal result from the real Agent turn and Resolution chain."""

    proposal: ActionProposal
    attempt: Attempt | None
    resolution: ResolutionResult | None
    event: Event | None
    communication_result: object | None = None


@dataclass
class AgentActionLoop:
    """Connect Agent decision, Attempt creation, and Event creation stages."""

    agent_turn: AgentTurn = field(default_factory=AgentTurn)
    action_pipeline: ActionPipeline = field(default_factory=ActionPipeline)
    action_resolution_flow: ActionResolutionFlow = field(
        default_factory=ActionResolutionFlow
    )
    safety_governance: UniversalSafetyGovernance | None = None
    write_fence: RuntimeWriteFence | None = None

    def __post_init__(self) -> None:
        selected = self.safety_governance
        if selected is None:
            selected = self.action_pipeline.safety_governance
        self.bind_safety_governance(selected)

    def bind_safety_governance(self, governance: UniversalSafetyGovernance) -> None:
        if not isinstance(governance, UniversalSafetyGovernance):
            raise TypeError("AgentActionLoop requires UniversalSafetyGovernance")
        self.safety_governance = governance
        self.action_pipeline.bind_safety_governance(governance)
        self.action_resolution_flow.bind_safety_governance(governance)

    def run_turn(
        self,
        agent: RuntimeAgent,
        cognition_context: CognitionContext,
        decision: AgentDecision,
        *,
        simulation_tick: SimulationTime | None = None,
    ) -> Event:
        """Run one action proposal through Attempt resolution to an Event."""
        result = self.run_turn_with_result(
            agent,
            cognition_context,
            decision,
            simulation_tick=simulation_tick,
            legacy_proposal_compatibility=(
                type(self.agent_turn) is AgentTurn
                and type(decision) is AgentDecision
                and not decision.has_custom_autonomous_policies()
            ),
        )
        if result.event is None:
            raise ValueError(
                "ResolutionEngine did not issue a valid confirmation for this Attempt (unresolved)"
            )
        return result.event

    def run_turn_with_result(
        self,
        agent: RuntimeAgent,
        cognition_context: CognitionContext,
        decision: AgentDecision,
        *,
        simulation_tick: SimulationTime | None = None,
        legacy_proposal_compatibility: bool = False,
        initiator_id: str | None = None,
        cognitive_review_provider: object | None = None,
        self_model_review_provider: object | None = None,
        npc_dialogue_service: object | None = None,
    ) -> AgentTurnExecution:
        """Execute one real decision while preserving unresolved results.

        Autonomous runtimes use this boundary to record an unresolved Attempt
        without converting it into an Event or aborting unrelated Agents.
        """
        if type(self.agent_turn) is AgentTurn:
            turn = self.agent_turn
            if cognitive_review_provider is not None:
                turn = replace(turn, cognitive_review_provider=cognitive_review_provider)
            if self_model_review_provider is not None:
                turn = replace(turn, self_model_review_provider=self_model_review_provider)
            if turn is not self.agent_turn:
                verifier_context = self.agent_turn._memory_event_verification_context
                if verifier_context is not None:
                    history, codec, trust, fence = verifier_context
                    turn._bind_memory_event_verifier(
                        history=history, codec=codec, trust=trust, fence=fence,
                    )
            proposal = turn.execute(
                agent,
                cognition_context,
                decision,
                simulation_tick=simulation_tick,
                legacy_proposal_compatibility=legacy_proposal_compatibility,
            )
        else:
            proposal = self.agent_turn.execute(
                agent, cognition_context, decision, simulation_tick=simulation_tick
            )
        if proposal.metadata.get("candidate_source") == "npc_communication_v1":
            deliver = getattr(npc_dialogue_service, "deliver_selected", None)
            if not callable(deliver):
                raise RuntimeError("selected NPC communication has no Runtime-bound delivery service")
            result = deliver(agent, proposal, cognition_context, simulation_tick)
            return AgentTurnExecution(proposal, None, None, None, result)
        return self.run_proposal_with_result(
            proposal, simulation_tick=simulation_tick,
            initiator_id=(
                agent.agent_id
                if initiator_id is None
                and isinstance(agent, RuntimeAgent)
                and type(self.action_pipeline) is ActionPipeline
                else initiator_id
            ),
        )

    def run_proposal_with_result(
        self,
        proposal: ActionProposal,
        *,
        simulation_tick: SimulationTime | None = None,
        initiator_id: str | None = None,
    ) -> AgentTurnExecution:
        """Submit an already selected Agent proposal through the same guarded path."""
        if not isinstance(proposal, ActionProposal):
            raise TypeError("an AgentDecision-issued ActionProposal is required")
        if self.write_fence is not None:
            self.write_fence.require_candidate_origin(proposal.runtime_write_permit)
        with provider_call_scope(1):
            if not isinstance(self.safety_governance, UniversalSafetyGovernance):
                raise RuntimeError("AgentActionLoop has no valid safety governance")
            # Keep a boundary outside an injectable Pipeline subclass, whose
            # override may not call ActionPipeline.create_attempt().
            self.safety_governance.require_action_allowed(
                safety_input_from_proposal(proposal, source="agent_action_loop")
            )
            attempt = (
                self.action_pipeline.create_attempt(proposal)
                if initiator_id is None
                else self.action_pipeline.create_attempt(
                    proposal, initiator_id=initiator_id
                )
            )
            self.safety_governance.require_action_allowed(
                safety_input_from_attempt(attempt, source="agent_attempt_submission")
            )
            resolution, event = self.action_resolution_flow.execute_with_result(
                attempt,
                action_proposal_id=proposal.proposal_id,
                simulation_tick=simulation_tick,
            )
            return AgentTurnExecution(proposal, attempt, resolution, event)
