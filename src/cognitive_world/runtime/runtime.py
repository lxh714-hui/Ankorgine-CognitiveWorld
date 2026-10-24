"""Minimal simulation lifecycle controller."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from inspect import Parameter, signature
from typing import Callable, Protocol, TYPE_CHECKING

from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.runtime.scheduler import EventScheduler, ScheduledEvent
from cognitive_world.runtime.snapshot import RuntimeSnapshot
from cognitive_world.safety.governance import SafetyReadiness
from cognitive_world.runtime.write_fence import RuntimeWriteFence
from cognitive_world.decision.behavior_feedback import BehaviorFeedback
from cognitive_world.core.attributed_claim import ClaimPropertyContract

if TYPE_CHECKING:
    from cognitive_world.agent.cognition_context import CognitionContext
    from cognitive_world.agent.runtime_agent import RuntimeAgent
    from cognitive_world.core.event import Event
    from cognitive_world.decision.agent_decision import AgentDecision
    from cognitive_world.agent.action_loop import AgentTurnExecution
    from cognitive_world.decision.event_tree import EventTreeSnapshot
    from cognitive_world.decision.autonomous import ConflictOpportunityCandidate


@dataclass(frozen=True)
class AgentRuntimeTurnRecord:
    """One Agent's bounded, owner-scoped result within a Runtime tick."""

    agent_id: str
    execution: AgentTurnExecution | None = None
    observation_ids: tuple[str, ...] = ()
    newly_consumed_percept_ids: tuple[str, ...] = ()
    event_id: str | None = None
    event_committed: bool = False
    failure_type: str | None = None
    event_tree_snapshot: EventTreeSnapshot | None = None
    event_tree_failure_type: str | None = None
    scheduler_findings: tuple[ConflictOpportunityCandidate, ...] = ()
    scheduler_failure_type: str | None = None


@dataclass(frozen=True)
class ScheduledEventRuntimeRecord:
    event_id: str
    committed: bool
    failure_type: str | None = None


class _AgentActionLoop(Protocol):
    """Agent turn boundary expected by the SimulationRuntime."""

    def run_turn(
        self,
        agent: RuntimeAgent,
        cognition_context: CognitionContext,
        decision: AgentDecision,
    ) -> Event:
        """Run a single Agent turn and return the generated Event."""
        ...


class _EventDispatcher(Protocol):
    """Dispatch boundary expected from an injected EventProcessor."""

    def dispatch(self, event: ScheduledEvent | Event) -> object:
        """Accept a scheduled or Agent-generated Event for dispatch."""
        ...


@dataclass
class SimulationRuntime:
    """Coordinate the runtime context without executing simulation rules."""

    context: RuntimeContext
    write_fence: RuntimeWriteFence = field(default_factory=RuntimeWriteFence, kw_only=True)
    scheduler: EventScheduler | None = None
    event_processor: _EventDispatcher | None = None
    running: bool = False
    agent_action_loop: _AgentActionLoop | None = None
    cognition_context_provider: Callable[[RuntimeAgent], CognitionContext] | None = None
    agent_decision: AgentDecision | None = None
    behavior_feedback: BehaviorFeedback = field(default_factory=BehaviorFeedback, kw_only=True)
    behavior_feedback_status: str = field(default="fresh", kw_only=True)
    memory_revision_lineage: object | None = field(default=None, kw_only=True, repr=False)
    evidence_review_provider: object | None = None
    conflict_opportunity_scheduler: object | None = None
    proactive_content_expansion: object | None = None
    maximum_agent_actions_this_step: int = 64
    maximum_events_this_step: int = 64
    cognitive_review_provider: object | None = None
    self_model_review_provider: object | None = None
    npc_communication_provider: object | None = None
    npc_claim_property_contracts: tuple[ClaimPropertyContract, ...] = field(default=(), kw_only=True)
    npc_dialogue_service: object | None = field(default=None, init=False, repr=False)
    allow_environment_provider_discovery: bool = field(default=True, kw_only=True)
    strict_dependency_binding: bool = field(default=False, kw_only=True)
    last_agent_turn_results: tuple[AgentRuntimeTurnRecord, ...] = field(
        default_factory=tuple, init=False
    )
    last_scheduled_event_results: tuple[ScheduledEventRuntimeRecord, ...] = field(
        default_factory=tuple, init=False
    )
    last_content_expansion_results: tuple[object, ...] = field(
        default_factory=tuple, init=False
    )
    last_cross_agent_goal_projection_failure_type: str | None = field(
        default=None, init=False
    )

    def __post_init__(self) -> None:
        """Resolve compatibility injection into the shared runtime context."""
        if self.memory_revision_lineage is None:
            history = self.context.event_history
            if (getattr(history, "fork_manifest_bytes", None) is None
                    and isinstance(history.timeline_id, str) and history.timeline_id):
                from cognitive_world.cognition.memory_revision import MemoryRevisionLineage
                self.memory_revision_lineage = MemoryRevisionLineage.root(history.timeline_id)
        if (self.memory_revision_lineage is not None
                and self.memory_revision_lineage.timeline_id != self.context.event_history.timeline_id):
            raise PermissionError("Runtime Memory revision view belongs to another Timeline")
        if self.memory_revision_lineage is not None:
            self.memory_revision_lineage.verify_event_history(self.context.event_history)
        if type(self.allow_environment_provider_discovery) is not bool:
            raise TypeError("allow_environment_provider_discovery must be bool")
        if type(self.strict_dependency_binding) is not bool:
            raise TypeError("strict_dependency_binding must be bool")
        if self.cognitive_review_provider is None:
            if self.allow_environment_provider_discovery:
                # A separate explicit selector is required: enabling dialogue
                # generation alone must never transmit cognition data.
                from cognitive_world.cognition.causal_review import OllamaCognitiveReviewProvider

                self.cognitive_review_provider = OllamaCognitiveReviewProvider.from_environment()
        elif not callable(getattr(self.cognitive_review_provider, "review", None)):
            raise TypeError("Runtime cognitive review provider must expose review(request)")
        if self.self_model_review_provider is not None and not callable(
            getattr(self.self_model_review_provider, "review", None)
        ):
            raise TypeError("Runtime SelfModel review provider must expose review(request)")
        if self.npc_communication_provider is not None and not callable(
            getattr(self.npc_communication_provider, "propose", None)
        ):
            raise TypeError("Runtime NPC communication provider must expose propose(situation, ...)")
        if self.conflict_opportunity_scheduler is None and self.strict_dependency_binding:
            raise ValueError("strict Runtime assembly requires an explicit ConflictOpportunityScheduler")
        if self.conflict_opportunity_scheduler is None:
            from cognitive_world.runtime.conflict_opportunity import ConflictOpportunityScheduler

            self.conflict_opportunity_scheduler = ConflictOpportunityScheduler()
        elif not callable(getattr(self.conflict_opportunity_scheduler, "discover", None)):
            raise TypeError("Runtime scheduler must expose discover(situation, candidates, simulation_tick=...)")
        if self.proactive_content_expansion is not None:
            if not callable(getattr(self.proactive_content_expansion, "expand", None)):
                raise TypeError("proactive content expansion must expose expand(findings, simulation_tick=...)")
            if getattr(self.proactive_content_expansion, "scheduler", None) is not self.conflict_opportunity_scheduler:
                raise ValueError("content expansion must use this Runtime's conflict/opportunity scheduler")
            installer = getattr(self.proactive_content_expansion, "installer", None)
            if (getattr(installer, "context", None) is not self.context
                    or getattr(installer, "processor", None) is not self.event_processor):
                raise ValueError("content expansion must use this Runtime's canonical content installer and EventProcessor")
        if self.context.scheduler is None and self.strict_dependency_binding:
            raise ValueError("strict Runtime assembly requires an explicit EventScheduler")
        if self.context.scheduler is None:
            self.context.scheduler = self.scheduler or EventScheduler()
        self.scheduler = self.context.scheduler
        if self.strict_dependency_binding:
            self._validate_processor_dependencies()
        else:
            self._bind_processor_dependencies()
        from cognitive_world.event.processor import EventProcessor
        if type(self.event_processor) is EventProcessor:
            verifier_trust = self.event_processor.persistence_trust
            if verifier_trust is not None:
                self.write_fence._bind_event_history_verifier(
                    history=self.context.event_history,
                    codec=self.event_processor.persistence_codec,
                    trust=verifier_trust,
                )
        from cognitive_world.agent.action_loop import AgentActionLoop
        from cognitive_world.agent.turn import AgentTurn
        from cognitive_world.cognition.l1_consumption_proof import L1ConsumptionIssuer
        if (type(self.agent_action_loop) is AgentActionLoop
                and type(self.agent_action_loop.agent_turn) is AgentTurn):
            turn = self.agent_action_loop.agent_turn
            trust = getattr(self.event_processor, "persistence_trust", None)
            codec = getattr(self.event_processor, "persistence_codec", None)
            if trust is not None and codec is not None:
                turn._bind_memory_event_verifier(
                    history=self.context.event_history,
                    codec=codec,
                    trust=trust,
                    fence=self.write_fence,
                )
            turn.l1_consumption_issuer = (
                None if trust is None else L1ConsumptionIssuer(
                    history=self.context.event_history, clock=self.context.clock,
                    trust=trust, fence=self.write_fence,
                )
            )
        if (type(self.event_processor) is EventProcessor
                and self.event_processor.persistence_trust is not None
                and self.cognition_context_provider is not None
                and type(self.agent_action_loop) is AgentActionLoop):
            from cognitive_world.cognition.action_expectation import ActionExpectationIssuer
            issuer = ActionExpectationIssuer(context=self.context, fence=self.write_fence,
                trust=self.event_processor.persistence_trust, context_provider=self.cognition_context_provider)
            self.event_processor.action_expectations = issuer
            self.agent_action_loop.action_resolution_flow.action_expectations = issuer
            self.agent_action_loop.agent_turn.action_expectation_issuer = issuer
        if self.npc_communication_provider is not None:
            from cognitive_world.event.processor import EventProcessor
            from cognitive_world.dialogue.npc import NpcDialogueService
            from cognitive_world.agent.action_loop import AgentActionLoop
            from cognitive_world.agent.turn import AgentTurn
            if type(self.event_processor) is not EventProcessor:
                raise TypeError("NPC communication requires the canonical EventProcessor")
            if (type(self.agent_action_loop) is not AgentActionLoop
                    or type(self.agent_action_loop.agent_turn) is not AgentTurn):
                raise TypeError("NPC communication requires the canonical AgentActionLoop and AgentTurn")
            self.npc_dialogue_service = NpcDialogueService(
                self.context, self.event_processor, self.write_fence,
                self.agent_action_loop.agent_turn.cognitive_runtime,
                self.npc_claim_property_contracts,
            )
        else:
            self.npc_dialogue_service = None

    def _validate_processor_dependencies(self) -> None:
        """Reject stale dependencies instead of silently rebinding them."""
        if self.event_processor is None:
            raise ValueError("strict Runtime assembly requires an EventProcessor")
        processor = self.event_processor
        expected = {
            "world_state": self.context.world_state,
            "event_history": self.context.event_history,
            "simulation_clock": self.context.clock,
            "agent_registry": self.context.agent_registry,
            "observation_store": self.context.observation_store,
            "write_fence": self.write_fence,
        }
        for name, value in expected.items():
            if hasattr(processor, name) and getattr(processor, name) is not value:
                raise PermissionError(f"strict Runtime EventProcessor has mismatched {name}")
        if self.agent_action_loop is None:
            raise ValueError("strict Runtime assembly requires an AgentActionLoop")
        from cognitive_world.resolution.action_flow import ActionResolutionFlow
        from cognitive_world.agent.action_loop import AgentActionLoop
        if isinstance(self.agent_action_loop, AgentActionLoop):
            loop = self.agent_action_loop
            if loop.write_fence is not self.write_fence:
                raise PermissionError("strict Runtime ActionLoop has a mismatched write fence")
            if loop.safety_governance is not self.context.safety_governance:
                raise PermissionError("strict Runtime ActionLoop has mismatched Safety governance")
            flow = loop.action_resolution_flow
            if isinstance(flow, ActionResolutionFlow) and (
                flow.world_state is not self.context.world_state
                or flow.event_history is not self.context.event_history
                or flow.safety_governance is not self.context.safety_governance
            ):
                raise PermissionError("strict Runtime ActionResolutionFlow has mismatched dependencies")

    def _bind_processor_dependencies(self) -> None:
        """Use the context's world containers when the processor exposes them."""
        if self.agent_action_loop is not None:
            from cognitive_world.resolution.action_flow import ActionResolutionFlow

            action_flow = getattr(self.agent_action_loop, "action_resolution_flow", None)
            if isinstance(action_flow, ActionResolutionFlow):
                action_flow.world_state = self.context.world_state
                action_flow.event_history = self.context.event_history
        if self.agent_action_loop is not None:
            from cognitive_world.agent.action_loop import AgentActionLoop

            if isinstance(self.agent_action_loop, AgentActionLoop):
                self.agent_action_loop.bind_safety_governance(
                    self.context.safety_governance
                )
                self.agent_action_loop.write_fence = self.write_fence
        if self.event_processor is None:
            return
        if hasattr(self.event_processor, "world_state"):
            setattr(self.event_processor, "world_state", self.context.world_state)
        if hasattr(self.event_processor, "event_history"):
            setattr(self.event_processor, "event_history", self.context.event_history)
        if hasattr(self.event_processor, "simulation_clock"):
            setattr(self.event_processor, "simulation_clock", self.context.clock)
        if hasattr(self.event_processor, "agent_registry"):
            setattr(self.event_processor, "agent_registry", self.context.agent_registry)
        if hasattr(self.event_processor, "observation_store"):
            setattr(self.event_processor, "observation_store", self.context.observation_store)
        if hasattr(self.event_processor, "write_fence"):
            setattr(self.event_processor, "write_fence", self.write_fence)

    def _bind_cross_agent_goal_projection(self, simulation_tick: int) -> None:
        """Issue a narrow, current-tick projection from linked canonical Goals."""
        from cognitive_world.cognition.goal import Goal
        from cognitive_world.core.world_state import WorldStateSlot
        from cognitive_world.runtime.conflict_opportunity import (
            CrossAgentGoalProjection,
            MAX_CROSS_AGENT_GOAL_PROJECTIONS,
            goal_resource_revision,
        )

        self.last_cross_agent_goal_projection_failure_type = None
        scheduler = self.conflict_opportunity_scheduler
        bind = getattr(scheduler, "bind_cross_agent_goal_projections", None)
        if not callable(bind):
            self.last_cross_agent_goal_projection_failure_type = "UnsupportedSchedulerBinding"
            return
        registry = self.context.agent_registry
        if registry is None or self.cognition_context_provider is None:
            bind((), world_state=self.context.world_state,
                 event_history=self.context.event_history,
                 simulation_tick=simulation_tick)
            return

        projections = []
        projection_budget_exceeded = False
        for agent in sorted(registry.all_agents(), key=lambda item: item.agent_id):
            try:
                cognition_context = self.cognition_context_provider(agent)
                if getattr(cognition_context, "owner_id", None) != agent.agent_id:
                    raise PermissionError("cognition context owner does not match registered Agent")
                container = getattr(cognition_context, "cognition_container", None)
                goal_store = getattr(container, "goal_store", None)
                get_owned = getattr(goal_store, "get_owned", None)
                if not callable(get_owned):
                    raise TypeError("canonical GoalStore is unavailable")
                for linked_goal in cognition_context.get_goals():
                    if not isinstance(linked_goal, Goal) or linked_goal.owner_id != agent.agent_id:
                        raise PermissionError("linked Goal is not owned by the registered Agent")
                    goal = get_owned(agent.agent_id, linked_goal.goal_id)
                    if goal is None or goal != linked_goal or goal.status != "active":
                        continue
                    for demand in goal.resource_demands:
                        # Strict namespace parsing: no ID/name/type guessing.
                        if not demand.resource_ref.startswith("object:"):
                            continue
                        entity_id = demand.resource_ref.removeprefix("object:")
                        if not entity_id or self.context.world_state.get_entity(entity_id) is None:
                            continue
                        slot_read = self.context.world_state.read_state_slot(
                            WorldStateSlot("entities", entity_id, ("type",)),
                            event_history=self.context.event_history,
                        )
                        if (
                            not slot_read.present
                            or slot_read.origin_kind not in {"initialization", "event"}
                            or not self.context.world_state.verify_state_slot_read(
                                slot_read, event_history=self.context.event_history
                            )
                        ):
                            continue
                        if len(projections) >= MAX_CROSS_AGENT_GOAL_PROJECTIONS:
                            projection_budget_exceeded = True
                            break
                        projections.append(CrossAgentGoalProjection(
                            owner_id=goal.owner_id,
                            goal_id=goal.goal_id,
                            goal_revision=goal_resource_revision(goal),
                            resource_ref=demand.resource_ref,
                            scope_ref=demand.scope_ref,
                            exclusive_use=demand.exclusive_use,
                            simulation_tick=simulation_tick,
                            resource_slot_read=slot_read,
                        ))
                    if projection_budget_exceeded:
                        break
                if projection_budget_exceeded:
                    break
            except Exception as error:
                # Projection failure is closed for cross-owner analysis and
                # isolated from the Agent's normal turn.
                self.last_cross_agent_goal_projection_failure_type = type(error).__name__
        if projection_budget_exceeded:
            projections.clear()
            self.last_cross_agent_goal_projection_failure_type = "ProjectionBudgetExceeded"
        try:
            bind(
                tuple(projections),
                world_state=self.context.world_state,
                event_history=self.context.event_history,
                simulation_tick=simulation_tick,
            )
        except Exception as error:
            self.last_cross_agent_goal_projection_failure_type = type(error).__name__
            bind((), world_state=self.context.world_state,
                 event_history=self.context.event_history,
                 simulation_tick=simulation_tick)

    def start(self) -> None:
        """Mark the runtime as running without advancing or dispatching."""
        if self.context.event_history.requires_recovery() or self.write_fence.recovery_required:
            raise RuntimeError("Runtime requires explicit recovery before starting")
        if self.write_fence.frozen:
            raise PermissionError("runtime is frozen")
        seal = getattr(self.context.world_state, "_seal_initialization", None)
        if callable(seal):
            seal()
        self.running = True

    def stop(self) -> None:
        """Mark the runtime as stopped without changing simulation state."""
        self.running = False

    def freeze_writes(self) -> int:
        """Stop new turns and invalidate every previously captured operation."""
        generation = self.write_fence.freeze_and_advance()
        self.running = False
        return generation

    def unfreeze_writes(self) -> None:
        """Permit new-generation work; old operation contexts remain invalid."""
        self.write_fence.unfreeze()

    def snapshot(self) -> RuntimeSnapshot:
        """Return a copy of runtime-owned time and lifecycle state."""
        return RuntimeSnapshot(
            simulation_time=self.context.clock.current_time,
            running=self.running,
        )

    @property
    def safety_readiness(self) -> SafetyReadiness:
        """Expose safety configuration status without implying model validation."""
        return self.context.safety_governance.readiness

    def step(self) -> tuple[object, ...]:
        """Run one tick under a captured session/generation capability."""
        if self.context.event_history.requires_recovery() or self.write_fence.recovery_required:
            self.stop()
            raise RuntimeError("Runtime requires explicit recovery before another tick")
        with self.write_fence.operation():
            return self._step_in_generation()

    def _step_in_generation(self) -> tuple[object, ...]:
        """Advance one tick and immediately apply each confirmed Agent Event.

        Per-Agent failures are isolated. A processor state requiring recovery
        halts this tick and future ticks; the runtime never replays its write.
        """
        seal = getattr(self.context.world_state, "_seal_initialization", None)
        if callable(seal):
            seal()
        with self.write_fence.commit_scope():
            current_time = self.context.clock.tick()
        scheduler = self.context.scheduler
        if scheduler is None:
            raise RuntimeError("RuntimeContext must provide an EventScheduler")
        due_events = scheduler.get_due_events(current_time)
        if (
            isinstance(self.maximum_agent_actions_this_step, bool)
            or not isinstance(self.maximum_agent_actions_this_step, int)
            or self.maximum_agent_actions_this_step < 0
            or isinstance(self.maximum_events_this_step, bool)
            or not isinstance(self.maximum_events_this_step, int)
            or self.maximum_events_this_step < 0
        ):
            raise ValueError("Runtime per-step budgets must be non-negative integers")
        turn_records: list[AgentRuntimeTurnRecord] = []
        scheduled_records: list[ScheduledEventRuntimeRecord] = []
        content_findings: list[ConflictOpportunityCandidate] = []
        dispatch_results: list[object] = []
        committed_events = 0
        self.last_content_expansion_results = ()
        if self.event_processor is not None:
            self._bind_processor_dependencies()
            for item in due_events:
                if committed_events >= self.maximum_events_this_step:
                    scheduled_records.append(ScheduledEventRuntimeRecord(
                        item.event.id, False, "event_budget_exhausted"
                    ))
                    continue
                try:
                    dispatch_results.append(self._dispatch_event(item))
                    committed_events += 1
                    scheduled_records.append(ScheduledEventRuntimeRecord(item.event.id, True))
                except Exception as error:
                    scheduled_records.append(ScheduledEventRuntimeRecord(
                        item.event.id, False, type(error).__name__
                    ))
                    if self._requires_event_recovery(item.event.id):
                        if self.context.event_history.requires_recovery():
                            self.stop()
                        self.last_scheduled_event_results = tuple(scheduled_records)
                        self.last_agent_turn_results = ()
                        self.last_content_expansion_results = ()
                        return tuple(dispatch_results)
        else:
            dispatch_results.extend(due_events)
            scheduled_records.extend(
                ScheduledEventRuntimeRecord(item.event.id, False, "no_event_processor")
                for item in due_events
            )

        if self.agent_action_loop is not None:
            agent_turn = getattr(self.agent_action_loop, "agent_turn", None)
            if agent_turn is not None and hasattr(agent_turn, "write_fence"):
                agent_turn.write_fence = self.write_fence
            agent_scheduler = self.context.agent_scheduler
            agent_registry = self.context.agent_registry
            if agent_scheduler is None:
                raise RuntimeError("RuntimeContext must provide an AgentScheduler")
            if agent_registry is None:
                raise RuntimeError("RuntimeContext must provide an AgentRegistry")
            if self.cognition_context_provider is None:
                raise RuntimeError(
                    "A cognition_context_provider is required for Agent turns"
                )
            if self.agent_decision is None:
                raise RuntimeError("An agent_decision is required for Agent turns")

            self._bind_cross_agent_goal_projection(current_time)

            due_agent_ids = tuple(sorted(set(agent_scheduler.get_due_agents(current_time))))
            for agent_index, agent_id in enumerate(due_agent_ids):
                if agent_index >= self.maximum_agent_actions_this_step:
                    turn_records.append(AgentRuntimeTurnRecord(
                        agent_id, failure_type="agent_action_budget_exhausted"
                    ))
                    continue
                if committed_events >= self.maximum_events_this_step:
                    turn_records.append(AgentRuntimeTurnRecord(
                        agent_id, failure_type="event_budget_exhausted"
                    ))
                    continue
                agent = agent_registry.get(agent_id)
                if agent is None:
                    turn_records.append(AgentRuntimeTurnRecord(
                        agent_id, failure_type="LookupError"
                    ))
                    continue
                action_flow = getattr(self.agent_action_loop, "action_resolution_flow", None)
                if action_flow is not None and hasattr(action_flow, "world_state"):
                    action_flow.world_state = self.context.world_state
                try:
                    cognition_context = self.cognition_context_provider(agent)
                    observations = tuple(
                        item for item in cognition_context.get_observations()
                        if getattr(item, "observer_id", None) == agent_id
                        and callable(getattr(item, "has_trusted_provenance", None))
                        and item.has_trusted_provenance()
                    )
                    observation_ids = tuple(item.observation_id for item in observations)
                    agent_turn = getattr(self.agent_action_loop, "agent_turn", None)
                    cognitive_runtime = getattr(agent_turn, "cognitive_runtime", None)
                    working_memory_store = getattr(cognitive_runtime, "working_memory_store", None)
                    before = working_memory_store.get(agent_id) if working_memory_store is not None else None
                    before_percepts = set(() if before is None else before.percept_ids)

                    turn_decision = self.agent_decision
                    # Bind evidence access to this owner and tick, never to the
                    # shared AgentDecision retained across different Agents.
                    from cognitive_world.decision.agent_decision import AgentDecision
                    if type(turn_decision) is AgentDecision:
                        from cognitive_world.decision.evidence_review import (
                            DeterministicLocalEvidenceReviewProvider,
                            EvidenceAwareEvaluationPolicy,
                        )
                        from cognitive_world.resolution.evidence import AuthorizedStateQuery
                        prior_policy = turn_decision.evaluation_policy
                        if isinstance(prior_policy, EvidenceAwareEvaluationPolicy):
                            base_policy = prior_policy.base_policy
                            inherited_provider = prior_policy.provider
                        else:
                            base_policy = prior_policy
                            inherited_provider = None
                        provider = self.evidence_review_provider
                        if provider is None:
                            provider = inherited_provider or DeterministicLocalEvidenceReviewProvider()
                        if not callable(getattr(provider, "propose_query", None)) or not callable(getattr(provider, "review_evidence", None)):
                            raise TypeError("Runtime evidence provider must expose local query and review methods")
                        turn_decision = replace(turn_decision, evaluation_policy=EvidenceAwareEvaluationPolicy(
                            AuthorizedStateQuery(self.context, cognition_context=cognition_context),
                            self.context.clock.current_time, provider,
                            base_policy=base_policy,
                        ))
                        turn_decision = replace(
                            turn_decision,
                            conflict_opportunity_scheduler=self.conflict_opportunity_scheduler,
                            simulation_tick=current_time,
                            behavior_feedback=self.behavior_feedback,
                        )
                    if self.npc_communication_provider is not None:
                        if type(turn_decision) is not AgentDecision:
                            raise TypeError("NPC communication requires the canonical AgentDecision")
                        from cognitive_world.dialogue.npc import NpcCommunicationCandidatePolicy
                        sender_location = self.context.world_state.locations.get(agent_id)
                        recipient_ids = tuple(sorted(
                            candidate.agent_id
                            for candidate in agent_registry.all_agents()
                            if candidate.agent_id != agent_id
                            and isinstance(sender_location, str)
                            and bool(sender_location)
                            and self.context.world_state.locations.get(candidate.agent_id) == sender_location
                        ))
                        turn_decision = replace(
                            turn_decision,
                            candidate_policy=NpcCommunicationCandidatePolicy(
                                turn_decision.candidate_policy,
                                self.npc_communication_provider,
                                recipient_ids,
                            ),
                        )
                    run_result = getattr(self.agent_action_loop, "run_turn_with_result", None)
                    if callable(run_result):
                        run_options = {
                            "simulation_tick": self.context.clock.capture(),
                            "legacy_proposal_compatibility": False,
                        }
                        from cognitive_world.agent.action_loop import AgentActionLoop
                        run_parameters = signature(run_result).parameters.values()
                        accepts_cognitive_review = any(
                            parameter.name == "cognitive_review_provider"
                            or parameter.kind is Parameter.VAR_KEYWORD
                            for parameter in run_parameters
                        )
                        accepts_self_model_review = any(
                            parameter.name == "self_model_review_provider"
                            or parameter.kind is Parameter.VAR_KEYWORD
                            for parameter in run_parameters
                        )
                        if (
                            isinstance(self.agent_action_loop, AgentActionLoop)
                            and self.cognitive_review_provider is not None
                            and accepts_cognitive_review
                        ):
                            run_options["cognitive_review_provider"] = self.cognitive_review_provider
                        if (
                            isinstance(self.agent_action_loop, AgentActionLoop)
                            and self.self_model_review_provider is not None
                            and accepts_self_model_review
                        ):
                            run_options["self_model_review_provider"] = self.self_model_review_provider
                        accepts_npc_dialogue = any(
                            parameter.name == "npc_dialogue_service"
                            or parameter.kind is Parameter.VAR_KEYWORD
                            for parameter in run_parameters
                        )
                        if (self.npc_dialogue_service is not None
                                and isinstance(self.agent_action_loop, AgentActionLoop)
                                and accepts_npc_dialogue):
                            run_options["npc_dialogue_service"] = self.npc_dialogue_service
                        execution = run_result(
                            agent, cognition_context, turn_decision, **run_options
                        )
                        event = execution.event
                        communication = execution.communication_result
                    else:
                        parameters = signature(self.agent_action_loop.run_turn).parameters.values()
                        accepts_tick = any(
                            parameter.name == "simulation_tick"
                            or parameter.kind is Parameter.VAR_KEYWORD
                            for parameter in parameters
                        )
                        event = (
                            self.agent_action_loop.run_turn(
                                agent, cognition_context, turn_decision,
                                simulation_tick=self.context.clock.capture(),
                            )
                            if accepts_tick
                            else self.agent_action_loop.run_turn(
                                agent, cognition_context, turn_decision
                            )
                        )
                        execution = None
                        communication = None

                    event_tree_snapshot = None
                    event_tree_failure_type = None
                    scheduler_findings = ()
                    scheduler_failure_type = None
                    if (execution is not None and execution.proposal is not None
                            and communication is None):
                        try:
                            scheduler_findings = self.conflict_opportunity_scheduler.current_for(
                                agent_id, current_time
                            )
                        except (AttributeError, TypeError, ValueError) as error:
                            scheduler_failure_type = type(error).__name__
                    if (execution is not None and execution.proposal is not None
                            and communication is None):
                        try:
                            from cognitive_world.decision.event_tree import (
                                EventTreeExplorer,
                                MAX_EVENT_TREE_BRANCHES,
                            )

                            explorer = EventTreeExplorer.from_proposal(
                                execution.proposal,
                                branch_budget=MAX_EVENT_TREE_BRANCHES,
                                simulation_tick=current_time,
                                scheduler_finding_ids=tuple(
                                    finding.finding_id for finding in scheduler_findings
                                ),
                            )
                            explorer.expand(MAX_EVENT_TREE_BRANCHES)
                            event_tree_snapshot = explorer.snapshot()
                        except (TypeError, ValueError, PermissionError) as error:
                            # Tree diagnostics are non-authoritative and must
                            # not suppress an otherwise valid action/Event path.
                            event_tree_failure_type = type(error).__name__

                    after = working_memory_store.get(agent_id) if working_memory_store is not None else None
                    after_percepts = set(() if after is None else after.percept_ids)
                    new_percepts = tuple(sorted(after_percepts - before_percepts))
                    committed = False
                    failure_type = None
                    event_id = (
                        communication.event_id if communication is not None
                        else (None if event is None else event.id)
                    )
                    if communication is not None:
                        # NpcDialogueService already committed this zero-WorldUpdate
                        # speech Event under the same RuntimeWriteFence.
                        committed_events += 1
                        committed = True
                        committed_event = self.context.event_history.get_event(communication.event_id)
                        if committed_event is None:
                            raise RuntimeError("committed NPC dialogue Event disappeared from EventHistory")
                        dispatch_results.append(committed_event)
                    elif event is not None:
                        if self.event_processor is None:
                            dispatch_results.append(event)
                        else:
                            try:
                                # Keep the authoritative Event append and its
                                # derived transient feedback inside the same
                                # fence lock used by snapshot_scope().
                                with self.write_fence.commit_scope():
                                    try:
                                        dispatch_results.append(self._dispatch_event(event))
                                    except Exception:
                                        # dispatch_with_evidence can fail after
                                        # EventHistory append (for example,
                                        # observation delivery). If the failure
                                        # Event is already authoritative, finish
                                        # its feedback while still fenced.
                                        if self.context.event_history.get_event(event.id) == event:
                                            self._apply_failure_feedback_if_eligible(
                                                agent_id, execution, observations, current_time, event
                                            )
                                        raise
                                    committed_events += 1
                                    committed = True
                                    self._apply_failure_feedback_if_eligible(
                                        agent_id, execution, observations, current_time, event
                                    )
                            except Exception as error:
                                failure_type = type(error).__name__
                                if self._requires_event_recovery(event.id):
                                    turn_records.append(AgentRuntimeTurnRecord(
                                        agent_id, execution, observation_ids, new_percepts,
                                        event_id, False, failure_type,
                                        event_tree_snapshot, event_tree_failure_type,
                                        scheduler_findings, scheduler_failure_type,
                                    ))
                                    if self.context.event_history.requires_recovery():
                                        self.stop()
                                        self.last_agent_turn_results = tuple(turn_records)
                                        self.last_scheduled_event_results = tuple(scheduled_records)
                                        self.last_content_expansion_results = ()
                                        return tuple(dispatch_results)
                                    break
                    if committed and scheduler_findings and communication is None:
                        content_findings.extend(scheduler_findings)
                    turn_records.append(AgentRuntimeTurnRecord(
                        agent_id, execution, observation_ids, new_percepts,
                        event_id, committed, failure_type,
                        event_tree_snapshot, event_tree_failure_type,
                        scheduler_findings, scheduler_failure_type,
                    ))
                except Exception as error:
                    turn_records.append(AgentRuntimeTurnRecord(
                        agent_id, failure_type=type(error).__name__
                    ))
                    if self.context.event_history.requires_recovery() or self.write_fence.recovery_required:
                        self.stop()
                        self.last_agent_turn_results = tuple(turn_records)
                        self.last_scheduled_event_results = tuple(scheduled_records)
                        self.last_content_expansion_results = ()
                        return tuple(dispatch_results)

        self.last_agent_turn_results = tuple(turn_records)
        self.last_scheduled_event_results = tuple(scheduled_records)
        if self.proactive_content_expansion is not None and content_findings:
            self.last_content_expansion_results = self.proactive_content_expansion.expand(
                tuple(content_findings), simulation_tick=current_time
            )
        return tuple(dispatch_results)

    def _record_behavior_failure(self, owner_id, execution, observations, tick, event) -> None:
        """Apply committed failure feedback within the caller's fence commit scope."""
        from cognitive_world.decision.autonomous import SituationFact

        facts = tuple(
            SituationFact(
                f"percept:{item.observation_id}", item.source_event_id,
                item.content.fact_type, item.content.predicate,
                str(item.content.value), item.content.fact_id,
            )
            for item in observations
            if self.context.event_history.get_event(item.source_event_id) is not None
            and all(isinstance(getattr(item.content, name, None), str)
                    for name in ("fact_type", "predicate", "fact_id"))
        )
        proposal = execution.proposal
        if proposal is None:
            raise PermissionError("confirmed failure has no bound proposal")
        selected_id = proposal.metadata.get("selected_candidate_id")
        selected_trace = next((row for row in proposal.metadata.get("decision_trace", ())
                               if isinstance(row, dict) and row.get("candidate_id") == selected_id), None)
        selected_sources = () if selected_trace is None else selected_trace.get("source_refs", ())
        if not isinstance(selected_sources, tuple) or any(not isinstance(ref, str) for ref in selected_sources):
            raise PermissionError("confirmed failure has invalid cited observation references")
        source_record = event.metadata["confirmed_attempt_failure"]
        if tuple(sorted(set(selected_sources))) != tuple(source_record["source_refs"]):
            raise PermissionError("feedback observations differ from the signed Attempt source references")
        try:
            self.behavior_feedback.record_failure(
                owner_id=owner_id, action_type=execution.attempt.action_type,
                target=execution.attempt.target,
                method=execution.attempt.parameters.get("method", ""),
                facts=facts, source_refs=selected_sources,
                event_id=event.id, tick=tick,
            )
        except Exception:
            self.context.event_history.mark_recovery_required(
                event.id, "BehaviorFeedback rejected a committed confirmed failure"
            )
            self.write_fence.mark_recovery_required()
            raise

    def _apply_failure_feedback_if_eligible(self, owner_id, execution, observations, tick, event) -> None:
        if execution is None or self.behavior_feedback is None:
            return
        from cognitive_world.event.attempt_source import verify_confirmed_failure_event

        if (execution.resolution.success is not False
                or not execution.resolution._has_valid_confirmation(execution.attempt)
                or not verify_confirmed_failure_event(event, attempt=execution.attempt)
                or self.context.event_history.get_event(event.id) != event):
            return
        try:
            self._record_behavior_failure(owner_id, execution, observations, tick, event)
        except Exception as feedback_error:
            if not self.context.event_history.requires_recovery():
                self.context.event_history.mark_recovery_required(
                    event.id, f"BehaviorFeedback commit failed: {type(feedback_error).__name__}"
                )
            if not self.write_fence.recovery_required:
                self.write_fence.mark_recovery_required()
            raise

    def _requires_event_recovery(self, event_id: str) -> bool:
        """Stop the tick after a non-replayable EventProcessor failure."""
        history = self.context.event_history
        get_status = getattr(history, "get_processing_status", None)
        if not callable(get_status):
            return False
        status = get_status(event_id)
        return getattr(status, "value", status) in {
            "recovery_required", "observations_pending", "applying_world_update"
        }

    def _dispatch_event(self, event: ScheduledEvent | Event) -> object:
        """Use the additive evidence path when Observation storage is configured."""
        if (
            self.context.observation_store is not None
            and hasattr(self.event_processor, "dispatch_with_evidence")
        ):
            self.event_processor.dispatch_with_evidence(event)
            return None
        return self.event_processor.dispatch(event)

    def run(self, steps: int) -> tuple[tuple[object, ...], ...]:
        """Run the complete configured runtime step flow a fixed number of times."""
        if isinstance(steps, bool) or not isinstance(steps, int):
            raise TypeError("steps must be a non-negative integer")
        if steps < 0:
            raise ValueError("steps must be a non-negative integer")
        if not self.running:
            self.start()
        return tuple(self.step() for _ in range(steps))
