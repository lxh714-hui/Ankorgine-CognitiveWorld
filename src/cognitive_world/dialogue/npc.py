"""Opt-in, owner-scoped NPC speech candidates and trusted delivery.

This is a narrow bridge into the existing dialogue Observation path. It owns
no message store and never treats spoken content as an objective world fact.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from cognitive_world.core.event import Event
from cognitive_world.core.attributed_claim import (
    AttributedClaimDraft, ClaimPropertyContract, DialoguePayload, bind_claim,
    decode_claim_draft, encode_claim_draft,
)
from cognitive_world.core.update import WorldUpdate
from cognitive_world.decision.autonomous import (
    ActionCandidate, CandidateExtension, SituationAssessment, MAX_CANDIDATES,
)
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.observation.observable import ObservableFact
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.runtime.write_fence import RuntimeWriteFence
from cognitive_world.safety.governance import SafetyInput

NPC_COMMUNICATION_STRATEGY = "npc_communication_v1"
NPC_CLAIM_EXTENSION_ID = "cognitive-world/attributed-claim-draft"
MAX_NPC_UTTERANCE_CHARS = 1200


@dataclass(frozen=True)
class NpcCommunicationDraft:
    """Untrusted proposal to share one bounded statement with one recipient."""

    recipient_id: str
    utterance: str
    source_refs: tuple[str, ...]
    claim: AttributedClaimDraft | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.recipient_id, str) or not self.recipient_id:
            raise ValueError("communication recipient is required")
        if (not isinstance(self.utterance, str) or not self.utterance.strip()
                or len(self.utterance) > MAX_NPC_UTTERANCE_CHARS):
            raise ValueError("communication utterance is empty or exceeds its bound")
        if (not isinstance(self.source_refs, tuple) or not self.source_refs
                or len(set(self.source_refs)) != len(self.source_refs)
                or any(not isinstance(ref, str) or not ref for ref in self.source_refs)):
            raise ValueError("communication must cite owner-local source references")
        if self.claim is not None and type(self.claim) is not AttributedClaimDraft:
            raise TypeError("communication claim must use AttributedClaimDraft")


class NpcCommunicationCandidateProvider(Protocol):
    """Explicitly injected source of tentative outbound communication choices."""

    def propose(
        self, situation: SituationAssessment, *, recipient_ids: tuple[str, ...],
        maximum_candidates: int,
    ) -> tuple[NpcCommunicationDraft, ...]: ...


@dataclass(frozen=True)
class NpcCommunicationCandidatePolicy:
    """Add at most one communication option to the normal candidate batch."""

    base_policy: object
    provider: NpcCommunicationCandidateProvider
    recipient_ids: tuple[str, ...]

    def generate(self, situation: SituationAssessment):
        base = self.base_policy.generate(situation)
        generation_mode = "normal"
        if (isinstance(base, tuple) and len(base) == 2
                and isinstance(base[0], tuple) and isinstance(base[1], str)):
            base, generation_mode = base
        if not isinstance(base, tuple) or any(not isinstance(item, ActionCandidate) for item in base):
            raise TypeError("base candidate policy returned an invalid batch")
        if not self.recipient_ids or len(base) >= MAX_CANDIDATES:
            return base, generation_mode
        try:
            drafts = self.provider.propose(
                situation, recipient_ids=self.recipient_ids, maximum_candidates=1,
            )
        except Exception:
            # Provider failure removes only the optional communication choice.
            return base, generation_mode
        if not isinstance(drafts, tuple) or len(drafts) > 1:
            return base, generation_mode
        if not drafts:
            return base, generation_mode
        draft = drafts[0]
        if not isinstance(draft, NpcCommunicationDraft) or draft.recipient_id not in self.recipient_ids:
            return base, generation_mode
        available_refs = {
            ref for fact in situation.observed_facts
            for ref in (fact.percept_id, fact.source_event_id)
        }
        available_refs.update(memory.source_event_id for memory in situation.memories)
        available_refs.update(ref for belief in situation.beliefs for ref in belief.source_refs)
        if not set(draft.source_refs).issubset(available_refs):
            return base, generation_mode
        identity = sha256((situation.owner_id + "\0" + draft.recipient_id + "\0"
                           + draft.utterance + "\0" + "\0".join(draft.source_refs)
                           ).encode("utf-8")).hexdigest()[:24]
        extension = None
        if draft.claim is not None:
            encoded_claim = encode_claim_draft(draft.claim)
            extension = CandidateExtension(
                NPC_CLAIM_EXTENSION_ID, 1, encoded_claim,
                sha256(encoded_claim).hexdigest(),
            )
        communication = ActionCandidate(
            candidate_id=f"npc-communication:{identity}",
            owner_id=situation.owner_id,
            goal_id=None,
            intent="Share a statement with another Agent",
            target=f"agent:{draft.recipient_id}",
            method=draft.utterance,
            tools=(), required_capabilities=(),
            preconditions=("Recipient must remain registered and co-located at delivery time.",),
            steps=("Deliver this statement as testimony; delivery does not establish its truth.",),
            expected_result="The recipient may receive an addressed Observation if delivery is authorized.",
            uncertainties=("The statement is not objective evidence merely because it was delivered.",),
            estimated_risk=0.1, estimated_cost=None, commitment=0.2,
            source_refs=draft.source_refs, strategy=NPC_COMMUNICATION_STRATEGY,
            domain_payload=extension,
        )
        return (*base, communication), f"{generation_mode}+npc_communication"


@dataclass(frozen=True)
class NpcDialogueDelivery:
    proposal_id: str
    sender_id: str
    recipient_id: str
    event_id: str
    observation_id: str
    simulation_tick: int
    status: str = "delivered_pending_recipient_turn"


class NpcDialogueService:
    """Deliver only an AgentDecision-selected communication proposal."""

    def __init__(self, context: RuntimeContext, processor: object,
                 write_fence: RuntimeWriteFence, cognitive_runtime: object,
                 claim_property_contracts: tuple[ClaimPropertyContract, ...] = ()) -> None:
        if (getattr(processor, "world_state", None) is not context.world_state
                or getattr(processor, "event_history", None) is not context.event_history
                or getattr(processor, "simulation_clock", None) is not context.clock
                or getattr(processor, "agent_registry", None) is not context.agent_registry
                or getattr(processor, "observation_store", None) is not context.observation_store):
            raise ValueError("NPC dialogue must use the Runtime's canonical authorities")
        if context.agent_registry is None or context.observation_store is None:
            raise ValueError("NPC dialogue requires AgentRegistry and ObservationStore")
        self.context = context
        self.processor = processor
        self.write_fence = write_fence
        self.cognitive_runtime = cognitive_runtime
        self.factory = SystemEventFactory()
        if (not isinstance(claim_property_contracts, tuple)
                or any(type(item) is not ClaimPropertyContract for item in claim_property_contracts)
                or len({item.property_ref for item in claim_property_contracts}) != len(claim_property_contracts)):
            raise ValueError("claim property contracts must be a unique immutable host registry")
        self.claim_property_contracts = {item.property_ref: item for item in claim_property_contracts}
        self._results: dict[str, NpcDialogueDelivery] = {}
        from cognitive_world.dialogue.runtime import DialogueInputHandler
        handlers = getattr(processor, "_handlers", {})
        existing = handlers.get("dialogue_input")
        if existing is None:
            processor.register_handler("dialogue_input", DialogueInputHandler())
        elif type(existing) is not DialogueInputHandler:
            raise ValueError("Runtime has an incompatible dialogue input handler")

    def deliver_selected(self, agent: object, proposal: ActionProposal,
                         cognition: object, simulation_tick: object) -> NpcDialogueDelivery:
        """Validate the selected proposal again, then commit delivery under the fence."""
        self.write_fence.require_candidate_origin(proposal.runtime_write_permit)
        if proposal.agent_id != getattr(agent, "agent_id", None):
            raise PermissionError("communication proposal owner does not match sender")
        metadata = proposal.metadata
        parameters = proposal.parameters
        if metadata.get("candidate_source") != NPC_COMMUNICATION_STRATEGY:
            raise PermissionError("selected proposal is not an authorized communication candidate")
        selected_id = metadata.get("selected_candidate_id")
        trace = metadata.get("decision_trace")
        selected_trace = next((item for item in trace if isinstance(item, dict)
                               and item.get("candidate_id") == selected_id), None) \
            if isinstance(trace, (tuple, list)) else None
        if (not isinstance(selected_id, str) or not isinstance(selected_trace, dict)
                or selected_trace.get("candidate_source") != NPC_COMMUNICATION_STRATEGY
                or selected_trace.get("intent") != proposal.action_type
                or selected_trace.get("method") != parameters.get("method")
                or selected_trace.get("domain_payload") != parameters.get("domain_payload")
                or selected_trace.get("target") != (proposal.target_refs[0]
                                                       if len(proposal.target_refs) == 1 else None)
                or tuple(selected_trace.get("source_refs", ())) != tuple(proposal.reasoning_refs)):
            raise PermissionError("communication no longer matches the selected AgentDecision candidate")
        target_refs = proposal.target_refs
        if len(target_refs) != 1 or not target_refs[0].startswith("agent:"):
            raise PermissionError("communication must name exactly one Agent recipient")
        recipient_id = target_refs[0][len("agent:"):]
        sender_id = proposal.agent_id
        if not recipient_id or recipient_id == sender_id:
            raise PermissionError("communication recipient is invalid")
        recipient = self.context.agent_registry.get(recipient_id)
        sender = self.context.agent_registry.get(sender_id)
        if recipient is None or sender is None or sender.agent_id != getattr(agent, "agent_id", None):
            raise PermissionError("communication participants must be registered Runtime Agents")
        utterance = parameters.get("method")
        if (not isinstance(utterance, str) or not utterance.strip()
                or len(utterance) > MAX_NPC_UTTERANCE_CHARS):
            raise PermissionError("communication text is invalid")
        refs = tuple(proposal.reasoning_refs)
        if not refs:
            raise PermissionError("communication has no owner-local source references")
        if getattr(cognition, "owner_id", None) != sender_id:
            raise PermissionError("communication cognition belongs to another Agent")
        authorized = set()
        for observation in cognition.get_observations():
            if (getattr(observation, "observer_id", None) == sender_id
                    and callable(getattr(observation, "has_trusted_provenance", None))
                    and observation.has_trusted_provenance()
                    and self.cognitive_runtime.has_consumed_observation(
                        sender_id, observation, source_event_id=observation.source_event_id
                    )):
                authorized.update((
                    observation.observation_id, observation.source_event_id,
                    f"percept:{observation.observation_id}",
                ))
        for belief in cognition.get_beliefs():
            if getattr(belief, "owner_id", None) == sender_id:
                authorized.update(getattr(belief, "source_refs", ()))
        if not set(refs).issubset(authorized):
            raise PermissionError("communication cites sources outside sender's authorized cognition")
        extension = parameters.get("domain_payload")
        claim_draft = None
        if extension is not None:
            if (type(extension) is not CandidateExtension
                    or extension.schema_id != NPC_CLAIM_EXTENSION_ID
                    or extension.schema_version != 1
                    or extension.sha256_hex != sha256(extension.payload).hexdigest()):
                raise PermissionError("selected communication payload has an unsupported schema")
            try:
                claim_draft = decode_claim_draft(extension.payload)
            except (TypeError, ValueError) as error:
                raise PermissionError("selected structured claim is malformed") from error
            contract = self.claim_property_contracts.get(claim_draft.property_ref)
            if contract is None:
                raise PermissionError("structured claim property has no host-registered contract")
            grounded_subjects = set()
            for observation in cognition.get_observations():
                if (observation.observation_id in refs
                        or f"percept:{observation.observation_id}" in refs
                        or observation.source_event_id in refs) and observation.has_trusted_provenance():
                    content = observation.content
                    grounded_subjects.update(value for value in (
                        getattr(content, "subject_ref", None),
                        getattr(content, "location_id", None),
                    ) if isinstance(value, str) and value)
            if claim_draft.subject_ref not in grounded_subjects:
                raise PermissionError("claim subject is not grounded by a cited trusted Observation")
        tick = getattr(simulation_tick, "tick", simulation_tick)
        if isinstance(tick, bool) or not isinstance(tick, int) or tick != self.context.clock.current_time:
            raise PermissionError("communication simulation tick is stale")
        prior = self._results.get(proposal.proposal_id)
        if prior is not None:
            return prior
        locations = self.context.world_state.locations
        location_id = locations.get(sender_id)
        if not isinstance(location_id, str) or not location_id or locations.get(recipient_id) != location_id:
            raise PermissionError("NPC communication requires trusted co-location")
        self.context.safety_governance.require_action_allowed(SafetyInput(
            actor_id=sender_id, source="agent_action_loop", intent=utterance,
            method=utterance, target_refs=(f"agent:{recipient_id}",),
        ))
        event_id = f"npc-dialogue:{proposal.proposal_id}"
        payload = None if claim_draft is None else DialoguePayload(1, bind_claim(
            draft=claim_draft, contract=self.claim_property_contracts[claim_draft.property_ref],
            speaker_id=sender_id, recipient_id=recipient_id, event_id=event_id,
            utterance=utterance,
        ))
        event = self.factory.create(
            event_id=event_id, event_type="dialogue_input", timestamp=str(tick),
            simulation_tick=tick, participants=[sender_id, recipient_id],
            cause=proposal.proposal_id, changes=[{"utterance": utterance}],
            metadata={"sender_id": sender_id, "recipient_id": recipient_id,
                      "location_id": location_id},
            dialogue_payload=payload,
        )
        with self.write_fence.commit_scope():
            evidence = self.processor.dispatch_with_evidence(event)
            if not evidence.has_trusted_source(event):
                raise PermissionError("NPC dialogue Event evidence is invalid")
            observation_id = f"observation:{event.id}:{recipient_id}:observable:{event.id}:0"
            observation = self.context.observation_store.get(observation_id)
            if (observation is None or observation.observer_id != recipient_id
                    or not observation.has_trusted_provenance()
                    or not isinstance(observation.content, ObservableFact)
                    or observation.content.value != utterance
                    or observation.content.subject_ref != recipient_id):
                raise PermissionError("recipient did not receive the exact trusted utterance Observation")
            result = NpcDialogueDelivery(
                proposal.proposal_id, sender_id, recipient_id, event.id,
                observation_id, tick,
            )
            self._results[proposal.proposal_id] = result
            return result
