"""Single-turn orchestration boundary for Agent decisions."""

from dataclasses import dataclass, field

from cognitive_world.agent.cognition_context import CognitionContext
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.cognition.runtime import CognitiveRuntime
from cognitive_world.cognition.l1_consumption_proof import L1ConsumptionIssuer
from cognitive_world.cognition.metacognition import (
    BoundedMetacognitionPolicy,
    MetacognitiveFeedback,
    MetacognitionPolicy,
)
from cognitive_world.cognition.memory_retrieval import (
    MAX_MEMORY_QUERY_RESULTS,
    MemoryQuery,
)
from cognitive_world.cognition.memory_event_index import MemoryEventIndex
from cognitive_world.cognition.metacognition import (
    MAX_MEMORY_RETRIEVALS_PER_TURN,
    MAX_METACOGNITIVE_FEEDBACK_ROUNDS,
)
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.decision.agent_decision import AgentDecision
from cognitive_world.decision.context import DecisionContext
from cognitive_world.runtime.clock import SimulationTime
from cognitive_world.cognition.emotion_system import (
    DeterministicDecisionModulationPolicy,
    DeterministicEmotionAppraisalPolicy,
    EmotionUpdateApplier,
    EmotionUpdateContext,
    EmotionUpdateValidator,
    _issue_emotion_update_context,
)
from cognitive_world.cognition.causal_review import (
    CognitiveBeliefReview,
    CognitiveReview,
    build_review_input,
)
from cognitive_world.cognition.evolution import CognitiveEvolutionEngine
from cognitive_world.cognition.self_model_evolution import SelfModelUpdateProposal
from cognitive_world.cognition.validation import CognitiveUpdateValidator
from cognitive_world.cognition.update_apply import CognitiveUpdateApplier
from cognitive_world.runtime.write_fence import RuntimeWriteFence


@dataclass
class AgentTurn:
    """Assemble an isolated DecisionContext from authoritative cognition inputs.

    CognitionContext reads Personality, SelfModel, Belief, and Goal from the
    shared CognitionContainer stores. CognitiveRuntime derives transient
    CognitionState from those snapshots and the Agent's Observations.
    """

    cognitive_runtime: CognitiveRuntime = field(default_factory=CognitiveRuntime)
    metacognition_policy: MetacognitionPolicy = field(
        default_factory=BoundedMetacognitionPolicy
    )
    emotion_appraisal_policy: object = field(default_factory=DeterministicEmotionAppraisalPolicy)
    decision_modulation_policy: object = field(default_factory=DeterministicDecisionModulationPolicy)
    emotion_update_validator: EmotionUpdateValidator = field(default_factory=EmotionUpdateValidator)
    cognitive_review_provider: object | None = None
    cognitive_belief_review: CognitiveBeliefReview = field(default_factory=CognitiveBeliefReview)
    cognitive_evolution_engine: CognitiveEvolutionEngine = field(default_factory=CognitiveEvolutionEngine)
    self_model_review_provider: object | None = None
    cognitive_update_validator: CognitiveUpdateValidator = field(default_factory=CognitiveUpdateValidator)
    write_fence: RuntimeWriteFence | None = None
    l1_consumption_issuer: L1ConsumptionIssuer | None = field(default=None, repr=False)
    _memory_event_verification_context: tuple[object, object, object, object] | None = field(
        default=None, init=False, repr=False,
    )

    def _bind_memory_event_verifier(
        self, *, history: object, codec: object, trust: object, fence: object,
    ) -> None:
        """Bind association retrieval to this Runtime's canonical verifier."""
        from cognitive_world.core.persistence import PersistedValueCodec
        from cognitive_world.event.history import EventHistory
        from cognitive_world.runtime.write_fence import RuntimeWriteFence

        if type(history) is not EventHistory or not isinstance(codec, PersistedValueCodec):
            raise TypeError("Memory event retrieval requires canonical Runtime verification inputs")
        if not callable(getattr(trust, "verify", None)):
            raise TypeError("Memory event retrieval requires persistence trust")
        if type(fence) is not RuntimeWriteFence:
            raise TypeError("Memory event retrieval requires the canonical RuntimeWriteFence")
        context = (history, codec, trust, fence)
        prior = self._memory_event_verification_context
        if prior is not None and any(prior[index] is not context[index] for index in range(4)):
            raise PermissionError("AgentTurn Memory event verifier is immutable once bound")
        self._memory_event_verification_context = context

    def execute(
        self,
        agent: RuntimeAgent,
        cognition_context: CognitionContext,
        decision: AgentDecision,
        *,
        simulation_tick: SimulationTime | None = None,
        legacy_proposal_compatibility: bool = False,
    ) -> ActionProposal:
        """Gather isolated decision inputs and return the proposed action."""
        decision_input, cognition_state = self.prepare_decision_context(
            agent, cognition_context, simulation_tick=simulation_tick
        )
        if not callable(getattr(decision, "propose", None)):
            raise TypeError("decision must provide a callable propose(context) method")
        if legacy_proposal_compatibility and type(decision) is AgentDecision:
            proposal = decision.propose(cognition_state)
        else:
            proposal = decision.propose(decision_input)
        if not isinstance(proposal, ActionProposal):
            raise TypeError("decision.propose(context) must return an ActionProposal")
        if proposal.agent_id != agent.agent_id:
            raise PermissionError("decision proposal belongs to another Agent")
        return proposal

    def prepare_decision_context(
        self,
        agent: RuntimeAgent,
        cognition_context: CognitionContext,
        *,
        simulation_tick: SimulationTime | None = None,
    ) -> tuple[DecisionContext, object]:
        """Assemble the same owner-scoped cognition for action or social choice."""
        if not isinstance(agent, RuntimeAgent):
            raise TypeError("agent must be a RuntimeAgent")
        if not isinstance(cognition_context, CognitionContext):
            raise TypeError("cognition_context must be a CognitionContext")
        agent_context = agent.get_context()
        if agent.agent_id != cognition_context.owner_id:
            raise ValueError(
                "RuntimeAgent agent_id must match CognitionContext owner_id"
            )
        if (
            agent_context.character_id is not None
            and agent_context.character_id != cognition_context.character_id
        ):
            raise ValueError(
                "RuntimeAgent AgentContext character_id must match "
                "CognitionContext character_id"
            )
        if self.write_fence is not None:
            cognition_context.bind_write_fence(self.write_fence)

        observations = cognition_context.get_observations()
        beliefs = cognition_context.get_beliefs()
        goals = cognition_context.get_goals()
        cognition_state = self.cognitive_runtime.process(
            agent.agent_id,
            observations,
            beliefs=beliefs,
            goals=goals,
        )
        if self.l1_consumption_issuer is not None:
            for observation in observations:
                if f"percept:{observation.observation_id}" in cognition_state.percept_ids:
                    self.l1_consumption_issuer.issue_after_l1(
                        owner_id=agent.agent_id, observation=observation,
                        cognitive_runtime=self.cognitive_runtime,
                        memory_store=cognition_context.memory_store,
                    )
        memory_event_index = None
        verified_event_anchors = ()
        memory_event_index_unavailable = False
        verifier_context = self._memory_event_verification_context
        if verifier_context is not None:
            history, codec, trust, fence = verifier_context
            try:
                memory_event_index = MemoryEventIndex.rebuild_for_context(
                    cognition_context, history, codec=codec, trust=trust,
                    runtime_fence=fence,
                )
                verified_event_anchors = memory_event_index.verified_observation_anchors(
                    cognition_context,
                    observations,
                    consumed_percepts=tuple(cognition_state.percepts),
                    cognitive_runtime=self.cognitive_runtime,
                )
                consumed_observation_ids = {
                    item.source_observation_id
                    for item in cognition_state.percepts
                    if getattr(item, "observer_id", None) == agent.agent_id
                    and isinstance(getattr(item, "source_observation_id", None), str)
                }
                if (
                    consumed_observation_ids
                    and not verified_event_anchors
                    and any(
                        observation.observer_id == agent.agent_id
                        and observation.observation_id in consumed_observation_ids
                        for observation in observations
                    )
                ):
                    memory_event_index_unavailable = True
            except Exception:
                # Association failure means this channel is unavailable, not
                # that relevant Memory does not exist. Keep lexical retrieval.
                memory_event_index = None
                verified_event_anchors = ()
                memory_event_index_unavailable = True
        cognitive_review: CognitiveReview | None = None
        cognitive_review_failed = False
        if self.cognitive_review_provider is not None:
            try:
                review_input = build_review_input(
                    agent.agent_id,
                    cognition_state.percept_ids,
                    tuple(cognition_state.percepts),
                    observations,
                    beliefs,
                )
                review_method = getattr(self.cognitive_review_provider, "review", None)
                if review_input is not None and callable(review_method):
                    candidate_review = review_method(review_input)
                    if not isinstance(candidate_review, CognitiveReview):
                        raise TypeError("cognitive review provider returned an invalid result")
                    self.cognitive_belief_review.apply(
                        candidate_review,
                        review_input,
                        cognition_context.cognition_container,
                        write_fence=self.write_fence,
                    )
                    cognitive_review = candidate_review
                    # Subsequent decision assembly in this same turn, and the
                    # next AgentTurn, read the canonical updated owner store.
                    beliefs = cognition_context.get_beliefs()
                elif review_input is not None:
                    raise TypeError("cognitive review provider must expose review(request)")
            except Exception:
                # A failed or invalid semantic suggestion is not a cognition
                # update. Continue with the previous authorized snapshot.
                cognitive_review_failed = True
        # SelfModel evolution is a separate, opt-in semantic review over the
        # same newly consumed L1 evidence. Candidates remain tentative and
        # pass through the shared validator/applier before canonical storage.
        self_model_review_failed = False
        if self.self_model_review_provider is not None:
            try:
                self_model = cognition_context.get_self_model()
                proposal = self.cognitive_evolution_engine.propose_self_model_update(
                    agent.agent_id,
                    cognition_state.percept_ids,
                    tuple(cognition_state.percepts),
                    observations,
                    self_model,
                    self.cognitive_runtime,
                    provider=self.self_model_review_provider,
                )
                if proposal is not None:
                    if not isinstance(proposal, SelfModelUpdateProposal):
                        raise TypeError("SelfModel evolution returned an invalid proposal")
                    authorized_observation_ids = tuple(
                        item.observation_id for item in observations
                        if getattr(item, "observer_id", None) == agent.agent_id
                        and getattr(item, "has_trusted_provenance", lambda: False)()
                        and f"percept:{item.observation_id}" in cognition_state.percept_ids
                        and self.cognitive_runtime.has_consumed_observation(
                            agent.agent_id, item, source_event_id=item.source_event_id
                        )
                    )
                    authorized_event_ids = tuple(
                        item.source_event_id for item in observations
                        if getattr(item, "observation_id", None) in authorized_observation_ids
                    )
                    authorized_source_event_pairs = {
                        item.observation_id: item.source_event_id for item in observations
                        if getattr(item, "observation_id", None) in authorized_observation_ids
                    }
                    validation = self.cognitive_update_validator.validate(proposal, {
                        "agent_id": agent.agent_id,
                        "authorized_source_refs": authorized_observation_ids,
                        "authorized_event_ids": authorized_event_ids,
                        "authorized_source_event_pairs": authorized_source_event_pairs,
                    })
                    if not validation.accepted:
                        raise PermissionError(validation.reason)
                    container = cognition_context.cognition_container
                    CognitiveUpdateApplier(
                        container.belief_store,
                        container.goal_store,
                        container.self_model_store,
                        write_fence=self.write_fence,
                    ).apply(proposal, validation)
            except Exception:
                self_model_review_failed = True
        supplied_feedback = cognition_context.get_metacognitive_feedback()
        if not callable(getattr(self.metacognition_policy, "review", None)):
            raise TypeError("metacognition_policy must provide review(context, ...)")

        memory_snapshots = {}
        prior_queries: list[MemoryQuery] = []
        review_cues: list[str] = (
            [] if supplied_feedback is None else list(supplied_feedback.review_cues)
        )
        if cognitive_review is not None:
            if cognitive_review.assessment:
                review_cues.append(
                    f"Subjective evidence assessment: {cognitive_review.assessment}"
                )
            if cognitive_review.uncertainty:
                review_cues.append(
                    f"Evidence uncertainty: {cognitive_review.uncertainty}"
                )
        if cognitive_review_failed:
            review_cues.append(
                "Cognitive review was unavailable or rejected; retain the previous Beliefs and uncertainty."
            )
        if memory_event_index_unavailable:
            review_cues.append(
                "Verified Event-linked Memory retrieval was unavailable; retain uncertainty."
            )
        if self_model_review_failed:
            review_cues.append(
                "SelfModel review was unavailable or rejected; retain the previous self-understanding."
            )
        feedback_requests = (
            [] if supplied_feedback is None else list(supplied_feedback.memory_queries)
        )
        max_retrievals = getattr(self.metacognition_policy, "maximum_retrievals", None)
        max_rounds = getattr(self.metacognition_policy, "maximum_feedback_rounds", None)
        result_limit = getattr(self.metacognition_policy, "results_per_query", None)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in (max_retrievals, max_rounds)
        ) or not isinstance(result_limit, int) or isinstance(result_limit, bool) or result_limit < 1:
            raise ValueError("metacognition policy budgets are invalid")
        max_retrievals = min(max_retrievals, MAX_MEMORY_RETRIEVALS_PER_TURN)
        max_rounds = min(max_rounds, MAX_METACOGNITIVE_FEEDBACK_ROUNDS)
        result_limit = min(result_limit, MAX_MEMORY_QUERY_RESULTS)

        def make_context(feedback: MetacognitiveFeedback | None) -> DecisionContext:
            current_working_memory = self.cognitive_runtime.working_memory_store.get(
                agent.agent_id
            )
            return DecisionContext(
                cognition_state=cognition_state,
                personality=cognition_context.get_personality(),
                self_model=cognition_context.get_self_model(),
                beliefs=tuple(beliefs),
                goals=tuple(goals),
                metadata={"source": "CognitionContext"},
                percepts=tuple(cognition_state.percepts),
                working_memory=current_working_memory,
                long_term_memories=tuple(memory_snapshots.values()),
                emotion=cognition_context.get_emotion(),
                metacognitive_feedback=feedback,
            )

        query_count = 0
        if max_retrievals == 0:
            review_cues.append("Memory retrieval budget exhausted; retain uncertainty.")

        def run_query(query: MemoryQuery) -> bool:
            nonlocal query_count, memory_event_index_unavailable
            if query.owner_id != agent.agent_id:
                raise PermissionError("metacognitive query belongs to another Agent")
            signature = " ".join(query.query.casefold().split())
            if not signature or any(
                " ".join(old.query.casefold().split()) == signature
                for old in prior_queries
            ):
                return False
            if query_count >= max_retrievals:
                return False
            bounded_query = MemoryQuery(
                owner_id=agent.agent_id,
                query=query.query,
                limit=min(query.limit, result_limit),
                metadata=query.metadata,
            )
            prior_queries.append(bounded_query)
            query_count += 1
            lexical_results = cognition_context.get_relevant_memories(bounded_query)
            results = lexical_results
            if memory_event_index is not None and verified_event_anchors:
                try:
                    event_candidates = memory_event_index.resolve_anchor_candidates(
                        cognition_context,
                        verified_event_anchors,
                        limit=bounded_query.limit,
                    )
                    results = memory_event_index.merge_candidates(
                        cognition_context,
                        lexical_results,
                        event_candidates,
                        limit=bounded_query.limit,
                    )
                except PermissionError:
                    # A stale Runtime/history binding disables only the
                    # association channel. The authorized lexical result is
                    # still valid for this CognitionContext.
                    results = lexical_results
                    if not memory_event_index_unavailable:
                        review_cues.append(
                            "Verified Event-linked Memory retrieval became unavailable; retain uncertainty."
                        )
                    memory_event_index_unavailable = True
            for memory in results:
                memory_snapshots.setdefault(memory.id, memory)
            return bool(results)

        found_relevant = False
        for query in feedback_requests:
            if query_count >= max_retrievals:
                break
            found_relevant = run_query(query) or found_relevant
            if found_relevant:
                break

        for _ in range(max_rounds):
            if found_relevant or query_count >= max_retrievals:
                break
            review_input = make_context(
                MetacognitiveFeedback(
                    owner_id=agent.agent_id,
                    review_cues=tuple(review_cues),
                    memory_queries=tuple(prior_queries),
                )
            )
            feedback = self.metacognition_policy.review(
                review_input,
                prior_queries=tuple(prior_queries),
                remaining_query_budget=max_retrievals - query_count,
            )
            if not isinstance(feedback, MetacognitiveFeedback):
                raise TypeError("metacognition policy must return MetacognitiveFeedback")
            if feedback.owner_id != agent.agent_id:
                raise PermissionError("metacognition policy returned another owner's feedback")
            review_cues.extend(feedback.review_cues)
            if not feedback.memory_queries:
                break
            for query in feedback.memory_queries:
                if query_count >= max_retrievals:
                    break
                if run_query(query):
                    found_relevant = True
                    break
            if found_relevant:
                break

        if not found_relevant:
            if max_retrievals == 0 or query_count >= max_retrievals:
                review_cues.append(
                    "Memory retrieval budget exhausted; retain uncertainty."
                )
            elif query_count > 0:
                review_cues.append(
                    "No matching personal memory was found within the review budget; retain uncertainty."
                )
        metacognitive_feedback = MetacognitiveFeedback(
            owner_id=agent.agent_id,
            review_cues=tuple(dict.fromkeys(review_cues)),
            memory_queries=tuple(prior_queries),
        )
        decision_input = make_context(metacognitive_feedback)
        if simulation_tick is not None:
            if not isinstance(simulation_tick, SimulationTime) or not simulation_tick.is_clock_issued():
                raise PermissionError("emotion updates require SimulationRuntime clock time")
            tick = simulation_tick.tick
            propose_emotion = getattr(self.emotion_appraisal_policy, "propose", None)
            if not callable(propose_emotion):
                raise TypeError("emotion_appraisal_policy must provide propose(context, simulation_tick=)")
            emotion_proposal = propose_emotion(decision_input, simulation_tick=tick)
            if emotion_proposal is not None:
                authorized_percepts = tuple(percept.percept_id for percept in cognition_state.percepts)
                authorized_events = tuple(
                    sorted({
                        getattr(percept.content, "source_event_id", "")
                        for percept in cognition_state.percepts
                        if getattr(percept.content, "source_event_id", None)
                    })
                )
                update_context = _issue_emotion_update_context(
                    agent.agent_id,
                    authorized_percepts,
                    authorized_events,
                    tick,
                    allow_clock_only=not authorized_events,
                    previous_processed_sources=tuple(
                        getattr(decision_input.emotion, "processed_sources", ())
                    ),
                )
                validation = self.emotion_update_validator.validate(emotion_proposal, update_context)
                if validation.accepted:
                    EmotionUpdateApplier(
                        cognition_context.cognition_container,
                        write_fence=self.write_fence,
                    ).apply(
                        emotion_proposal, validation, simulation_tick=tick
                    )
                    decision_input = make_context(metacognitive_feedback)

        assess = getattr(self.decision_modulation_policy, "assess", None)
        if not callable(assess):
            raise TypeError("decision_modulation_policy must provide assess(context)")
        motivation, modulation = assess(decision_input)
        decision_input = DecisionContext(
            cognition_state=decision_input.cognition_state,
            personality=decision_input.personality,
            self_model=decision_input.self_model,
            goals=decision_input.goals,
            beliefs=decision_input.beliefs,
            metadata=decision_input.metadata,
            percepts=decision_input.percepts,
            working_memory=decision_input.working_memory,
            long_term_memories=decision_input.long_term_memories,
            emotion=decision_input.emotion,
            metacognitive_feedback=decision_input.metacognitive_feedback,
            motivation_assessment=motivation,
            decision_modulation=modulation,
        )
        return decision_input, cognition_state
