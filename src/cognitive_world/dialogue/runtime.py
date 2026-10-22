"""Direct, event-backed player speech delivery to a recipient Agent.

The input Event records that the host delivered an utterance; its text is not
interpreted as objective world content. Recipient action remains owned by the
existing AgentTurn and ActionResolutionFlow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Protocol
from uuid import uuid4

from cognitive_world.agent.action_loop import AgentActionLoop, AgentTurnExecution
from cognitive_world.agent.cognition_context import CognitionContext
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.cognition.causal_review import (
    BeliefSnapshot, CognitiveBeliefReview, CognitiveEvidence,
    CognitiveReview, CognitiveReviewInput, MAX_COGNITIVE_REVIEW_ITEMS,
)
from cognitive_world.core.event import Event
from cognitive_world.core.update import WorldUpdate
from cognitive_world.decision.agent_decision import AgentDecision
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.decision.autonomous import ActionCandidate, SituationAssessment
from cognitive_world.decision.autonomous import DEFAULT_SITUATION_ASSESSMENT_POLICY
from cognitive_world.presentation.pipeline import PresentationPipeline
from cognitive_world.presentation.perspective import PerspectiveResolver
from cognitive_world.event.handler import EventHandler
from cognitive_world.event.history import EventHistory, EventProcessingStatus
from cognitive_world.event.processor import EventProcessor
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.observation.observable import ObservableFact, ObservableFactDraft
from cognitive_world.runtime.context import PlayerMode, RuntimeContext
from cognitive_world.safety.governance import SafetyInput

MAX_DIALOGUE_CHARS = 4000


@dataclass(frozen=True)
class DialogueRequest:
    request_id: str
    recipient_id: str
    utterance: str
    in_reply_to: str | None = None

    def __post_init__(self) -> None:
        if not self.request_id or len(self.request_id) > 128:
            raise ValueError("request_id must be bounded non-empty text")
        if not self.recipient_id or len(self.recipient_id) > 256:
            raise ValueError("recipient_id must be bounded non-empty text")
        if not isinstance(self.utterance, str) or not self.utterance.strip() or len(self.utterance) > MAX_DIALOGUE_CHARS:
            raise ValueError("utterance must be bounded non-empty text")
        if self.in_reply_to is not None and (
            not isinstance(self.in_reply_to, str)
            or not self.in_reply_to
            or len(self.in_reply_to) > 128
            or self.in_reply_to == self.request_id
        ):
            raise ValueError("in_reply_to must name a distinct bounded request")


@dataclass(frozen=True)
class DialogueInterpretationRequest:
    sender_id: str
    recipient_id: str
    source_event_id: str
    utterance: str


@dataclass(frozen=True)
class DialogueInterpretation:
    """Untrusted semantic assessment; it is only a turn-local decision cue."""
    meaning: str
    possible_action_request: str | None
    uncertainty: str

    def __post_init__(self) -> None:
        for name in ("meaning", "uncertainty"):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) > 1000:
                raise ValueError(f"{name} must be bounded text")
        if self.possible_action_request is not None and (
            not isinstance(self.possible_action_request, str)
            or len(self.possible_action_request) > 1000
        ):
            raise ValueError("possible_action_request must be bounded text or None")


class DialogueInterpretationProvider(Protocol):
    """Explicitly injected semantic interpreter; no provider is selected here."""
    def interpret(self, request: DialogueInterpretationRequest) -> DialogueInterpretation: ...


@dataclass(frozen=True)
class DialogueResponseCandidate:
    """A proposed NPC choice; the interpreter cannot select or authorize it."""

    action: ActionCandidate
    request_outcome: str
    semantic_content: str
    inbound_event_id: str

    def __post_init__(self) -> None:
        if self.request_outcome not in {"accept", "reject", "clarify", "undecided", "not_applicable"}:
            raise ValueError("invalid delegated-request lifecycle outcome")
        if not isinstance(self.semantic_content, str) or len(self.semantic_content) > MAX_DIALOGUE_CHARS:
            raise ValueError("response semantics must be bounded text")
        if not isinstance(self.inbound_event_id, str) or not self.inbound_event_id:
            raise ValueError("inbound Event reference is required")
        if self.request_outcome == "accept" and not self.semantic_content.strip():
            raise ValueError("an acceptance must express its decision")


class DialogueResponseCandidateProvider(Protocol):
    """Explicitly selected candidate source; the default is no model provider."""

    def propose(
        self,
        situation: SituationAssessment,
        interpretation: DialogueInterpretation | None,
        inbound_event_id: str,
    ) -> tuple[DialogueResponseCandidate, ...]: ...


class DialogueExpressionProvider(Protocol):
    """Optional wording adapter; it may not change the selected semantics."""

    def express(self, semantic_content: str) -> str: ...


class DialogueInputHandler(EventHandler):
    """Issue a typed fact that one utterance was delivered to one recipient."""
    def handle(self, event: Event) -> WorldUpdate:
        return WorldUpdate("facts", "update", {})

    def handle_with_world_state(self, event: Event, world_state: object) -> WorldUpdate:
        if not event.has_trusted_source("system") or event.type != "dialogue_input":
            raise PermissionError("dialogue input requires a trusted host event")
        if set(event.metadata) != {"sender_id", "recipient_id", "location_id"}:
            raise PermissionError("dialogue input metadata has an invalid schema")
        if len(event.changes) != 1 or not isinstance(event.changes[0], dict):
            raise ValueError("dialogue input must contain exactly one utterance record")
        change = event.changes[0]
        if set(change) != {"utterance"} or not isinstance(change["utterance"], str):
            raise PermissionError("dialogue input contains unsupported fields")
        if event.dialogue_payload is not None:
            from cognitive_world.core.attributed_claim import DialoguePayload, validate_claim_for_event
            if type(event.dialogue_payload) is not DialoguePayload:
                raise PermissionError("dialogue payload has an unsupported schema")
            if event.dialogue_payload.claim is not None:
                validate_claim_for_event(event.dialogue_payload.claim, event=event)
        sender, recipient = event.metadata["sender_id"], event.metadata["recipient_id"]
        if (sender, recipient) != tuple(event.participants) or sender == recipient:
            raise PermissionError("dialogue input participants do not match its delivery")
        location_id = event.metadata["location_id"]
        locations = getattr(world_state, "locations", {})
        if (
            not isinstance(location_id, str)
            or not location_id
            or locations.get(sender) != location_id
            or locations.get(recipient) != location_id
        ):
            raise PermissionError("dialogue participants do not share the trusted event-time location")
        return WorldUpdate("facts", "update", {})

    def observable_facts(self, event: Event, update: WorldUpdate) -> tuple[ObservableFactDraft, ...]:
        if not event.has_trusted_source("system") or event.type != "dialogue_input":
            raise PermissionError("dialogue facts require a trusted host event")
        change = event.changes[0]
        return (ObservableFactDraft(
            fact_type="social_input",
            predicate="utterance_delivered",
            value=change["utterance"],
            subject_ref=event.metadata["recipient_id"],
            location_id=event.metadata["location_id"],
        ),)


@dataclass
class DialogueReplyHandler(EventHandler):
    """Record only the occurrence of NPC speech, not the truth of its claims."""

    history: EventHistory
    _selected_replies: dict[str, tuple[object, ...]] = field(default_factory=dict, repr=False)
    _request_results: dict[str, tuple[str, DialogueResult]] = field(default_factory=dict, repr=False)

    def bind_selected_reply(self, event: Event, proposal: ActionProposal) -> None:
        """Bind a host-selected NPC decision to the exact reply Event snapshot."""
        if (
            not isinstance(event, Event)
            or not event.has_trusted_source("system")
            or not isinstance(proposal, ActionProposal)
            or proposal.agent_id != event.metadata.get("sender_id")
            or proposal.metadata.get("selected_candidate_id") != event.metadata.get("decision_candidate_id")
            or proposal.proposal_id != event.metadata.get("decision_proposal_id")
            or event.metadata.get("inbound_event_id") not in proposal.reasoning_refs
        ):
            raise PermissionError("reply is not bound to the selected NPC decision")
        self._selected_replies[event.id] = event._source_snapshot()

    def handle(self, event: Event) -> WorldUpdate:
        return WorldUpdate("facts", "update", {})

    def handle_with_world_state(self, event: Event, world_state: object) -> WorldUpdate:
        if not event.has_trusted_source("system") or event.type != "dialogue_reply":
            raise PermissionError("reply requires a controlled system Event")
        if set(event.metadata) != {"sender_id", "recipient_id", "location_id", "inbound_event_id", "decision_candidate_id", "decision_proposal_id"}:
            raise PermissionError("reply metadata schema is invalid")
        if not isinstance(event.metadata["decision_candidate_id"], str) or not event.metadata["decision_candidate_id"]:
            raise PermissionError("reply lacks its selected decision candidate reference")
        if self._selected_replies.get(event.id) != event._source_snapshot():
            raise PermissionError("reply Event lacks an intact selected-decision binding")
        if len(event.changes) != 1 or not isinstance(event.changes[0], dict) or set(event.changes[0]) != {"utterance"}:
            raise PermissionError("reply must contain one bounded utterance")
        utterance = event.changes[0]["utterance"]
        if not isinstance(utterance, str) or not utterance.strip() or len(utterance) > MAX_DIALOGUE_CHARS:
            raise ValueError("reply utterance is invalid")
        sender, recipient = event.metadata["sender_id"], event.metadata["recipient_id"]
        location = event.metadata["location_id"]
        inbound_id = event.metadata["inbound_event_id"]
        inbound = self.history.get_event(inbound_id) if isinstance(inbound_id, str) else None
        inbound_evidence = (
            self.history.get_processing_evidence(inbound_id)
            if inbound is not None else None
        )
        if (
            (sender, recipient) != tuple(event.participants)
            or sender == recipient
            or not isinstance(location, str)
            or not location
            or getattr(world_state, "locations", {}).get(sender) != location
            or getattr(world_state, "locations", {}).get(recipient) != location
            or event.cause != inbound_id
            or inbound is None
            or inbound.type != "dialogue_input"
            or not inbound.has_trusted_source("system")
            or inbound_evidence is None
            or not inbound_evidence.has_trusted_source(inbound)
            or tuple(inbound.participants) != (recipient, sender)
            or inbound.metadata.get("sender_id") != recipient
            or inbound.metadata.get("recipient_id") != sender
            or inbound.simulation_tick is None
            or event.simulation_tick is None
            or event.simulation_tick < inbound.simulation_tick
        ):
            raise PermissionError("reply lacks a matching trusted inbound utterance")
        return WorldUpdate("facts", "update", {})

    def observable_facts(self, event: Event, update: WorldUpdate) -> tuple[ObservableFactDraft, ...]:
        return (ObservableFactDraft(
            fact_type="social_output",
            predicate="utterance_delivered",
            value=event.changes[0]["utterance"],
            subject_ref=event.metadata["recipient_id"],
            location_id=event.metadata["location_id"],
        ),)


@dataclass(frozen=True)
class DialogueResult:
    request_id: str
    status: str
    delivery_event_id: str
    observation_id: str
    agent_execution: AgentTurnExecution | None = None
    interpretation: DialogueInterpretation | None = None
    request_outcome: str = "undecided"
    reply_event_id: str | None = None
    reply_delivered: bool = False
    decision_candidate_id: str | None = None
    decision_source_refs: tuple[str, ...] = ()


class PlayerDialogueService:
    """Deliver speech to an observed, co-located Agent and run its own turn."""
    def __init__(
        self,
        context: RuntimeContext,
        processor: EventProcessor,
        action_loop: AgentActionLoop,
        cognition_context_provider: object,
        decision: AgentDecision,
        *,
        interpretation_provider: DialogueInterpretationProvider | None = None,
        response_candidate_provider: DialogueResponseCandidateProvider | None = None,
        persuasion_review_provider: object | None = None,
        expression_provider: DialogueExpressionProvider | None = None,
        presentation: PresentationPipeline | None = None,
    ) -> None:
        if (
            processor.world_state is not context.world_state
            or processor.event_history is not context.event_history
            or processor.simulation_clock is not context.clock
            or processor.agent_registry is not context.agent_registry
            or processor.observation_store is not context.observation_store
        ):
            raise ValueError("dialogue service requires the RuntimeContext authorities")
        if not callable(cognition_context_provider) or not callable(getattr(decision, "propose", None)):
            raise TypeError("recipient cognition provider and AgentDecision are required")
        if not callable(getattr(action_loop, "run_turn_with_result", None)):
            raise TypeError("existing AgentActionLoop is required")
        self.context = context
        self.processor = processor
        self.action_loop = action_loop
        self.cognition_context_provider = cognition_context_provider
        self.decision = decision
        self.interpretation_provider = interpretation_provider
        if response_candidate_provider is None:
            # Environment selection is explicit and construction-only; no model
            # request occurs until a recipient dialogue turn is processed.
            from cognitive_world.dialogue.ollama import OllamaDialogueResponseCandidateProvider
            response_candidate_provider = OllamaDialogueResponseCandidateProvider.from_environment()
        self.response_candidate_provider = response_candidate_provider
        if persuasion_review_provider is not None and not callable(getattr(persuasion_review_provider, "review", None)):
            raise TypeError("persuasion reviewer must expose review(request)")
        self.persuasion_review_provider = persuasion_review_provider
        self.persuasion_belief_review = CognitiveBeliefReview()
        self.expression_provider = expression_provider
        self.presentation = presentation
        if presentation is not None and presentation.runtime_context is not context:
            raise ValueError("dialogue Presentation must share the RuntimeContext")
        action_loop.bind_safety_governance(context.safety_governance)
        action_loop.action_resolution_flow.world_state = context.world_state
        self.factory = SystemEventFactory()
        self.processor.register_handler("dialogue_input", DialogueInputHandler())
        existing_reply_handler = self.processor._handlers.get("dialogue_reply")
        if existing_reply_handler is None:
            self.reply_handler = DialogueReplyHandler(context.event_history)
            self.processor.register_handler("dialogue_reply", self.reply_handler)
        elif (
            isinstance(existing_reply_handler, DialogueReplyHandler)
            and existing_reply_handler.history is context.event_history
        ):
            self.reply_handler = existing_reply_handler
        else:
            raise ValueError("Runtime already has an incompatible dialogue reply handler")
        self._results = self.reply_handler._request_results

    def _sender(self) -> str:
        session = self.context.player_session
        if session is None or session.mode is not PlayerMode.ROLEPLAY or not session.controlled_agent_id:
            raise PermissionError("dialogue requires a host-bound roleplay identity")
        return session.controlled_agent_id

    def submit(self, request: DialogueRequest) -> DialogueResult:
        # Capture before delivery, L1 processing, and any blocking Provider
        # call. A late response after generation advance keeps this permit.
        fence = getattr(self.processor, "write_fence", None)
        if fence is None:
            return self._submit_in_generation(request, None)
        with fence.operation():
            return self._submit_in_generation(request, fence)

    def _submit_in_generation(self, request: DialogueRequest, write_fence: object | None) -> DialogueResult:
        if not isinstance(request, DialogueRequest):
            raise TypeError("DialogueRequest required")
        sender = self._sender()
        session = self.context.player_session
        fingerprint = json.dumps((
            session.session_id, session.player_id, sender,
            request.recipient_id, request.utterance, request.in_reply_to,
        ), ensure_ascii=False)
        prior = self._results.get(request.request_id)
        if prior is not None:
            if prior[0] != fingerprint:
                raise PermissionError("dialogue request ID was reused with changed content")
            return prior[1]
        prior_reply_event_id = None
        if request.in_reply_to is not None:
            previous = self._results.get(request.in_reply_to)
            if previous is None or previous[1].request_outcome != "clarify" or not previous[1].reply_delivered:
                raise PermissionError("follow-up lacks a delivered clarification request")
            prior_session, prior_player, prior_sender, prior_recipient, _, _ = json.loads(previous[0])
            if (prior_session, prior_player, prior_sender, prior_recipient) != (
                session.session_id, session.player_id, sender, request.recipient_id
            ):
                raise PermissionError("follow-up participants do not match the prior dialogue")
            prior_reply_event_id = previous[1].reply_event_id
        registry = self.context.agent_registry
        observations = self.context.observation_store
        receiver = registry.get(request.recipient_id) if registry is not None else None
        if receiver is None or request.recipient_id == sender or observations is None:
            raise PermissionError("dialogue recipient is unavailable")
        locations = self.context.world_state.locations
        sender_location = locations.get(sender)
        if not isinstance(sender_location, str) or not sender_location or locations.get(receiver.agent_id) != sender_location:
            raise PermissionError("in-person dialogue requires a known shared location")
        if not callable(getattr(self.context.safety_governance, "require_action_allowed", None)):
            raise RuntimeError("runtime safety governance is unavailable")
        self.context.safety_governance.require_action_allowed(SafetyInput(
            actor_id=sender, source="player_dialogue", intent=request.utterance,
            method=request.utterance, target_refs=(f"agent:{receiver.agent_id}",),
        ))
        tick = self.context.clock.capture()
        event = self.factory.create(
            event_id=f"dialogue:{request.request_id}:{uuid4().hex}",
            event_type="dialogue_input",
            timestamp=str(tick.tick),
            simulation_tick=tick.tick,
            participants=[sender, receiver.agent_id],
            cause=prior_reply_event_id or request.request_id,
            changes=[{"utterance": request.utterance}],
            metadata={
                "sender_id": sender,
                "recipient_id": receiver.agent_id,
                "location_id": sender_location,
            },
        )
        evidence = self.processor.dispatch_with_evidence(event)
        observation_id = f"observation:{event.id}:{receiver.agent_id}:observable:{event.id}:0"
        observation = next((item for item in observations.get_by_observer(receiver.agent_id)
                            if item.observation_id == observation_id and item.source_event_id == event.id), None)
        if observation is None or not observation.has_trusted_provenance():
            raise RuntimeError("recipient did not receive the trusted dialogue Observation")
        if not evidence.has_trusted_source(event):
            raise PermissionError("dialogue Event evidence is invalid")

        interpretation = None
        if self.interpretation_provider is not None:
            try:
                interpretation = self.interpretation_provider.interpret(
                    DialogueInterpretationRequest(sender, receiver.agent_id, event.id, request.utterance)
                )
                if not isinstance(interpretation, DialogueInterpretation):
                    raise TypeError("interpretation provider returned an invalid result")
            except Exception:
                # The recipient still receives the original utterance; a failed
                # semantic suggestion cannot grant permissions or create action.
                interpretation = None

        execution = None
        try:
            cognition = self.cognition_context_provider(receiver)
            if not isinstance(cognition, CognitionContext) or cognition.owner_id != receiver.agent_id:
                raise PermissionError("recipient CognitionContext has the wrong owner")
            if write_fence is not None:
                cognition.bind_write_fence(write_fence)
            # Every delivered utterance is consumed by the recipient's own L1.
            # A conversation is not automatically converted to a physical action.
            runtime = self.action_loop.agent_turn.cognitive_runtime
            cognition_state = runtime.process(
                receiver.agent_id,
                cognition.get_observations(),
                beliefs=cognition.get_beliefs(),
                goals=cognition.get_goals(),
            )
            if self.persuasion_review_provider is not None:
                try:
                    self._review_persuasion(
                        cognition, runtime, cognition_state.percept_ids,
                        observation, event, tick.tick, write_fence,
                    )
                except Exception:
                    # The delivered utterance remains true, but a failed
                    # assessment cannot change the recipient's Belief.
                    pass
            if self.response_candidate_provider is not None:
                result = self._respond(
                    request, sender, receiver, cognition, tick, event.id,
                    observation_id, interpretation, session.session_id, session.player_id,
                )
                self._results[request.request_id] = (fingerprint, result)
                return result
            if interpretation is None or interpretation.possible_action_request is None:
                result = DialogueResult(
                    request.request_id, "delivered_no_action", event.id,
                    observation_id, None, interpretation,
                )
                self._results[request.request_id] = (fingerprint, result)
                return result
            original_feedback = cognition.metacognitive_feedback
            from cognitive_world.cognition.metacognition import MetacognitiveFeedback
            cues = () if original_feedback is None else original_feedback.review_cues
            if original_feedback is not None and original_feedback.owner_id != receiver.agent_id:
                raise PermissionError("recipient feedback belongs to another Agent")
            cognition.metacognitive_feedback = MetacognitiveFeedback(
                owner_id=receiver.agent_id,
                review_cues=tuple(cues) + (
                    "Untrusted dialogue interpretation candidate: " + interpretation.meaning,
                    "Possible request candidate: " + interpretation.possible_action_request,
                    "Interpretation uncertainty: " + interpretation.uncertainty,
                ),
            )
            try:
                execution = self.action_loop.run_turn_with_result(
                    receiver, cognition, self.decision,
                    simulation_tick=tick, initiator_id=sender,
                )
            finally:
                cognition.metacognitive_feedback = original_feedback
            if execution.attempt.agent_id != receiver.agent_id or execution.attempt.initiator_id != sender:
                raise PermissionError("delegated Attempt actor/initiator binding failed")
            if execution.event is not None:
                self.processor.dispatch_with_evidence(execution.event)
                status = "action_resolved" if execution.resolution.confirmed else "unresolved"
            else:
                status = "unresolved"
        except Exception:
            # Delivery is already a recorded fact. Do not replay it or invent a
            # refusal/response; report that receiver processing failed.
            status = "delivered_receiver_turn_failed"
            execution = None
        result = DialogueResult(request.request_id, status, event.id, observation_id, execution, interpretation)
        self._results[request.request_id] = (fingerprint, result)
        return result

    def _review_persuasion(
        self, cognition: CognitionContext, runtime: object,
        new_percept_ids: list[str], speech: object, event: Event, tick: int,
        write_fence: object | None = None,
    ) -> None:
        """Review one newly consumed addressed utterance against recipient evidence."""
        owner = cognition.owner_id
        if f"percept:{speech.observation_id}" not in new_percept_ids:
            return
        if not isinstance(speech.content, ObservableFact) or (
            speech.content.fact_type, speech.content.predicate
        ) != ("social_input", "utterance_delivered"):
            return
        if speech.content.source_event_id != event.id or speech.content.subject_ref != owner:
            return
        beliefs = cognition.get_beliefs()
        if not beliefs:
            return

        def verified(item: object) -> bool:
            if not isinstance(item.content, ObservableFact):
                return False
            source = self.context.event_history.get_event(item.source_event_id)
            evidence = self.context.event_history.get_processing_evidence(item.source_event_id)
            return (
                item.observer_id == owner and item.has_trusted_provenance()
                and item.content.source_event_id == item.source_event_id
                and source is not None and evidence is not None
                and isinstance(source.simulation_tick, int)
                and source.simulation_tick <= tick
                and item.content.has_trusted_source(source)
                and evidence.has_trusted_source(source)
                and runtime.has_consumed_observation(owner, item, source_event_id=item.source_event_id)
            )

        if not verified(speech):
            return
        inputs = [speech]
        for item in cognition.get_observations():
            if len(inputs) >= MAX_COGNITIVE_REVIEW_ITEMS:
                break
            if item.observation_id == speech.observation_id or not verified(item):
                continue
            if item.content.fact_type == "social_input":
                continue  # Other testimony is not independent objective support.
            inputs.append(item)
        evidence_items = tuple(CognitiveEvidence(
            item.observation_id, item.source_event_id,
            {"fact_type": item.content.fact_type, "predicate": item.content.predicate,
             "value": item.content.value, "subject_ref": item.content.subject_ref,
             "location_id": item.content.location_id},
        ) for item in inputs)
        request = CognitiveReviewInput(
            owner, evidence_items,
            tuple(BeliefSnapshot(item.belief_id, item.content, item.confidence,
                                 tuple(item.source_refs)) for item in beliefs[:MAX_COGNITIVE_REVIEW_ITEMS]),
            speech.observation_id,
        )
        review = self.persuasion_review_provider.review(request)
        if not isinstance(review, CognitiveReview):
            raise TypeError("persuasion reviewer returned an invalid result")
        if self.context.clock.current_time != tick or not all(
            verified(item)
            and (current := self.context.observation_store.get(item.observation_id)) is not None
            and current._snapshot() == item._snapshot()
            for item in inputs
        ):
            raise PermissionError("persuasion evidence changed during assessment")
        current_beliefs = {item.belief_id: item for item in cognition.get_beliefs()}
        if any(
            (current := current_beliefs.get(item.belief_id)) is None
            or current.content != item.content
            or current.confidence != item.confidence
            or tuple(current.source_refs) != item.source_refs
            for item in request.beliefs
        ):
            raise PermissionError("recipient Belief changed during persuasion assessment")
        self.persuasion_belief_review.apply(
            review, request, cognition.cognition_container,
            write_fence=write_fence,
        )

    def _respond(
        self, request: DialogueRequest, sender: str, receiver: RuntimeAgent,
        cognition: CognitionContext, tick: object, inbound_event_id: str,
        observation_id: str, interpretation: DialogueInterpretation | None,
        session_id: str, player_id: str,
    ) -> DialogueResult:
        """Run the recipient's existing assessment, scoring and guarded output."""
        try:
            decision_context, _ = self.action_loop.agent_turn.prepare_decision_context(
                receiver, cognition, simulation_tick=tick
            )
            situation_policy = getattr(
                self.decision, "situation_policy", DEFAULT_SITUATION_ASSESSMENT_POLICY
            )
            situation = situation_policy.assess(decision_context)
            if situation.owner_id != receiver.agent_id:
                raise PermissionError("social assessment belongs to another Agent")
        except Exception:
            return DialogueResult(
                request.request_id, "response_decision_failed", inbound_event_id,
                observation_id, interpretation=interpretation,
            )
        try:
            from cognitive_world.dialogue.ollama import OllamaDialogueResponseCandidateProvider
            if isinstance(self.response_candidate_provider, OllamaDialogueResponseCandidateProvider):
                offered = self.response_candidate_provider.propose(
                    situation, interpretation, inbound_event_id, sender_id=sender
                )
            else:
                offered = self.response_candidate_provider.propose(
                    situation, interpretation, inbound_event_id
                )
        except Exception:
            # No response/event is synthesized when the local model is
            # unavailable, times out, or returns malformed structured output.
            return DialogueResult(
                request.request_id, "response_generation_failed", inbound_event_id,
                observation_id, interpretation=interpretation,
            )
        try:
            if not isinstance(offered, tuple) or not offered or len(offered) > 6:
                raise ValueError("response candidates are empty or over budget")
            if any(not isinstance(item, DialogueResponseCandidate) for item in offered):
                raise TypeError("response provider returned an invalid candidate")
            ids = set()
            allowed_targets = {f"agent:{sender}"}
            allowed_targets.update(item.target_ref for item in situation.affordances)
            for item in offered:
                candidate = item.action
                if (
                    item.inbound_event_id != inbound_event_id
                    or candidate.owner_id != receiver.agent_id
                    or inbound_event_id not in candidate.source_refs
                    or candidate.candidate_id in ids
                ):
                    raise PermissionError("response candidate has an invalid owner or source")
                if candidate.target not in allowed_targets:
                    raise PermissionError("response candidate target is outside authorized scope")
                ids.add(candidate.candidate_id)
                if item.request_outcome == "accept" and (
                    interpretation is None or interpretation.possible_action_request is None
                ):
                    raise PermissionError("acceptance requires an interpreted request candidate")
            proposal = self.decision.propose_from_candidates(
                decision_context, tuple(item.action for item in offered)
            )
            selected = next(
                item for item in offered
                if item.action.candidate_id == proposal.metadata["selected_candidate_id"]
            )
        except Exception:
            return DialogueResult(
                request.request_id, "response_decision_failed", inbound_event_id,
                observation_id, interpretation=interpretation,
            )

        outcome = selected.request_outcome
        decision_trace = {
            "decision_candidate_id": selected.action.candidate_id,
            "decision_source_refs": selected.action.source_refs,
        }
        execution = None
        if outcome == "accept":
            try:
                execution = self.action_loop.run_proposal_with_result(
                    proposal, simulation_tick=tick, initiator_id=sender
                )
                if execution.attempt.agent_id != receiver.agent_id or execution.attempt.initiator_id != sender:
                    raise PermissionError("delegated Attempt has a mismatched actor/initiator")
                if execution.event is not None:
                    self.processor.dispatch_with_evidence(execution.event)
            except Exception:
                event_status = (
                    None if execution is None or execution.event is None
                    else self.context.event_history.get_processing_status(execution.event.id)
                )
                return DialogueResult(
                    request.request_id,
                    "action_event_recovery_required"
                    if event_status is EventProcessingStatus.RECOVERY_REQUIRED
                    else "action_submission_failed",
                    inbound_event_id, observation_id, execution, interpretation,
                    "accept", **decision_trace,
                )
        if outcome == "undecided" or not selected.semantic_content.strip():
            return DialogueResult(
                request.request_id, "response_undecided", inbound_event_id,
                observation_id, execution, interpretation, outcome,
                **decision_trace,
            )

        # A wording provider may decline/fail, but cannot introduce new claims.
        # Exact semantic content is the current verifiable narrow boundary.
        try:
            speech = selected.semantic_content
            if self.expression_provider is not None:
                speech = self.expression_provider.express(selected.semantic_content)
            if speech != selected.semantic_content:
                raise PermissionError("expression altered approved response semantics")
        except Exception:
            return DialogueResult(
                request.request_id, "response_expression_failed", inbound_event_id,
                observation_id, execution, interpretation, outcome,
                **decision_trace,
            )
        try:
            self.context.safety_governance.require_presentation_allowed(SafetyInput(
                actor_id=receiver.agent_id,
                source="npc_dialogue",
                intent=speech,
                target_refs=(f"agent:{sender}",),
            ))
        except Exception:
            return DialogueResult(
                request.request_id, "response_safety_blocked", inbound_event_id,
                observation_id, execution, interpretation, outcome,
                **decision_trace,
            )
        reply = None
        try:
            perspective = PerspectiveResolver(self.context).resolve()
            if (
                perspective.observer_id != sender
                or perspective.session_id != session_id
                or perspective.recipient_id != player_id
            ):
                raise PermissionError("reply target is no longer the original player")
            location = self.context.world_state.locations.get(sender)
            if not location or self.context.world_state.locations.get(receiver.agent_id) != location:
                raise PermissionError("reply participants no longer share a location")
            reply = self.factory.create(
                event_id=f"dialogue-reply:{request.request_id}:{uuid4().hex}",
                event_type="dialogue_reply", timestamp=str(tick.tick),
                simulation_tick=tick.tick,
                participants=[receiver.agent_id, sender], cause=inbound_event_id,
                changes=[{"utterance": speech}],
                metadata={
                    "sender_id": receiver.agent_id, "recipient_id": sender,
                    "location_id": location, "inbound_event_id": inbound_event_id,
                    "decision_candidate_id": selected.action.candidate_id,
                    "decision_proposal_id": proposal.proposal_id,
                },
            )
            self.reply_handler.bind_selected_reply(reply, proposal)
            self.processor.dispatch_with_evidence(reply)
        except Exception:
            processing_status = (
                None if reply is None else self.context.event_history.get_processing_status(reply.id)
            )
            if processing_status is EventProcessingStatus.RECOVERY_REQUIRED:
                failure_status = "reply_event_recovery_required"
            elif processing_status is EventProcessingStatus.OBSERVATIONS_PENDING:
                failure_status = "reply_observation_pending"
            else:
                failure_status = "reply_event_failed"
            return DialogueResult(
                request.request_id, failure_status, inbound_event_id,
                observation_id, execution, interpretation, outcome,
                None if reply is None else reply.id,
                decision_candidate_id=selected.action.candidate_id,
                decision_source_refs=selected.action.source_refs,
            )
        try:
            if self.presentation is None:
                raise RuntimeError("a trusted player PresentationPipeline is required")
            batch = self.presentation.publish_event(reply.id)
            if len(batch.messages) != 1 or batch.messages[0].source_event_ids != (reply.id,):
                raise RuntimeError("the addressed player received no verified reply message")
        except Exception:
            return DialogueResult(
                request.request_id, "reply_delivery_failed", inbound_event_id,
                observation_id, execution, interpretation, outcome, reply.id,
                decision_candidate_id=selected.action.candidate_id,
                decision_source_refs=selected.action.source_refs,
            )
        return DialogueResult(
            request.request_id, "reply_delivered", inbound_event_id,
            observation_id, execution, interpretation, outcome, reply.id, True,
            **decision_trace,
        )

    def retry_delivery(self, request_id: str) -> DialogueResult:
        """Retry only presentation; never replay either committed Event."""
        prior = self._results.get(request_id)
        if prior is None or prior[1].status != "reply_delivery_failed" or not prior[1].reply_event_id:
            raise ValueError("only a recorded delivery failure can be retried")
        result = prior[1]
        if self.presentation is None:
            raise RuntimeError("a trusted player PresentationPipeline is required")
        session_id, player_id, sender, _, _, _ = json.loads(prior[0])
        perspective = PerspectiveResolver(self.context).resolve()
        if (
            perspective.session_id != session_id
            or perspective.recipient_id != player_id
            or perspective.observer_id != sender
        ):
            raise PermissionError("reply retry targets a different player session")
        batch = self.presentation.publish_event(result.reply_event_id)
        if len(batch.messages) != 1 or batch.messages[0].source_event_ids != (result.reply_event_id,):
            raise RuntimeError("the addressed player received no verified reply message")
        from dataclasses import replace
        delivered = replace(result, status="reply_delivered", reply_delivered=True)
        self._results[request_id] = (prior[0], delivered)
        return delivered
