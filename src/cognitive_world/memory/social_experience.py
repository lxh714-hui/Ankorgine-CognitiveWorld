"""Evidence-bound social experience, without inferred physical or narrative rules.

The only supported comparison is exact typed equality at one explicit historical
tick. Interval claims, unsupported proof families and missing evidence defer.
The value is subjective experience; it grants no world-write authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json

from cognitive_world.cognition.l1_consumption_proof import (
    L1ConsumptionProof, NonverbalL1ConsumptionProof, verify_proof, verify_nonverbal_proof,
    PROOF_MEMORY_TYPE, NONVERBAL_PROOF_MEMORY_TYPE,
)

SOCIAL_MEMORY_TYPE = "attributed_social_experience_v1"


@dataclass(frozen=True)
class SocialExperience:
    version: int
    experience_id: str
    owner_id: str
    character_id: str
    speaker_id: str
    claim_digest: str
    speech_memory_id: str
    evidence_memory_id: str
    subject_ref: str
    property_ref: str
    value_type: str
    claimed_value: str | int | float | bool
    observed_value: str | int | float | bool
    evidence_event_tick: int
    comparison: str

    def __post_init__(self):
        if type(self.version) is not int or self.version != 1:
            raise ValueError("unsupported social experience version")
        if any(not isinstance(value, str) or not value or len(value) > 1024
               for value in (self.experience_id, self.owner_id, self.character_id,
                             self.speaker_id, self.claim_digest, self.speech_memory_id,
                             self.evidence_memory_id, self.subject_ref, self.property_ref,
                             self.value_type, self.comparison)):
            raise ValueError("invalid social experience identity")
        import math
        expected = {"string": str, "integer": int, "number": float, "boolean": bool}.get(self.value_type)
        if (expected is None or type(self.claimed_value) is not type(self.observed_value)
                or (self.value_type == "number" and type(self.claimed_value) not in (int, float))
                or (self.value_type != "number" and type(self.claimed_value) is not expected)
                or (type(self.claimed_value) is float and not math.isfinite(self.claimed_value))
                or (type(self.observed_value) is float and not math.isfinite(self.observed_value))
                or type(self.evidence_event_tick) is not int or self.evidence_event_tick < 0):
            raise ValueError("social experience has invalid typed evidence")
        if self.comparison not in {"supported", "contradicted"}:
            raise ValueError("unsupported social comparison")

    def policy_value(self):
        return asdict(self)


def _comparison(speech, evidence, *, history, trust, timeline_id, tick):
    if type(speech.content) is not L1ConsumptionProof or type(evidence.content) is not NonverbalL1ConsumptionProof:
        raise PermissionError("social review requires separate speech and nonverbal proofs")
    verify_proof(speech.content, history=history, trust=trust,
                 checkpoint_timeline_id=timeline_id, checkpoint_tick=tick)
    verify_nonverbal_proof(evidence.content, history=history, trust=trust,
                          checkpoint_timeline_id=timeline_id, checkpoint_tick=tick)
    for memory, memory_type in ((speech, PROOF_MEMORY_TYPE), (evidence, NONVERBAL_PROOF_MEMORY_TYPE)):
        if (memory.type != memory_type or memory.id != memory.content.proof_id
                or memory.owner_id != memory.content.owner_id
                or memory.source_event != memory.content.source_event_id):
            raise PermissionError("consumption proof record wrapper mismatch")
    utterance = history.get_event(speech.content.source_event_id)
    payload = getattr(utterance, "dialogue_payload", None)
    claim = getattr(payload, "claim", None)
    if claim is None or claim.recipient_id != speech.owner_id or evidence.owner_id != speech.owner_id:
        raise PermissionError("claim/proof owner mismatch or missing typed claim")
    facts = history.get_processing_evidence(evidence.content.source_event_id).observable_facts
    fact = next((item for item in facts if item.fact_id == evidence.content.fact_id), None)
    # This is intentionally not a claim-to-domain keyword mapping.
    if (fact is None or claim.subject_ref != fact.subject_ref
            or claim.property_ref != fact.predicate
            or claim.valid_from_tick != claim.valid_through_tick
            or claim.valid_from_tick != evidence.content.event_tick
            or claim.scope_ref != "event:" + evidence.content.source_event_id):
        raise PermissionError("unsupported property mapping or temporal comparison")
    if type(claim.value) is not type(fact.value):
        raise PermissionError("claim and evidence types are incomparable")
    return claim, fact, "supported" if claim.value == fact.value else "contradicted"


def build_experience(*, owner_id, character_id, speech, evidence, history, trust, tick):
    if speech.owner_id != owner_id or evidence.owner_id != owner_id:
        raise PermissionError("social evidence belongs to another owner")
    claim, fact, comparison = _comparison(
        speech, evidence, history=history, trust=trust,
        timeline_id=history.timeline_id, tick=tick)
    identity = json.dumps([1, history.timeline_id, owner_id, character_id,
                           claim.content_sha256, speech.id, evidence.id],
                          separators=(",", ":"), ensure_ascii=False)
    return SocialExperience(
        1, "social:" + sha256(identity.encode()).hexdigest(), owner_id,
        character_id, claim.speaker_id, claim.content_sha256,
        speech.id, evidence.id, claim.subject_ref, claim.property_ref, claim.value_type,
        claim.value, fact.value, evidence.content.event_tick, comparison)


def verify_experience(memory, *, records, history, trust, timeline_id, tick):
    value = memory.content
    if (memory.type != SOCIAL_MEMORY_TYPE or type(value) is not SocialExperience
            or memory.schema_version != 2 or memory.owner_id != value.owner_id
            or memory.supersedes_record_id is not None or memory.logical_record_id != memory.id):
        raise PermissionError("unsupported social Memory or owner binding")
    value.__post_init__()
    speech = records.get(value.speech_memory_id)
    evidence = records.get(value.evidence_memory_id)
    if speech is None or evidence is None:
        raise PermissionError("social experience lacks canonical consumption proofs")
    claim, fact, comparison = _comparison(
        speech, evidence, history=history, trust=trust, timeline_id=timeline_id, tick=tick)
    if (claim.speaker_id != value.speaker_id or claim.content_sha256 != value.claim_digest
            or comparison != value.comparison or memory.source_event != claim.source_event_id
            or (value.subject_ref, value.property_ref, value.value_type, value.claimed_value,
                value.observed_value, value.evidence_event_tick) !=
               (claim.subject_ref, claim.property_ref, claim.value_type, claim.value,
                fact.value, evidence.content.event_tick)
            or memory.owner_id != speech.owner_id or memory.owner_id != evidence.owner_id
            or memory.decision_provenance is None):
        raise PermissionError("social experience differs from its verified evidence")
    # The creation Timeline is authenticated by formal Memory/v2 provenance;
    # inherited evidence retains that identity rather than being recreated.
    identity = json.dumps([1, memory.decision_provenance.timeline_id,
                           value.owner_id, value.character_id, value.claim_digest,
                           speech.id, evidence.id], separators=(",", ":"), ensure_ascii=False)
    if value.experience_id != "social:" + sha256(identity.encode()).hexdigest():
        raise PermissionError("social experience identity mismatch")
    if memory.id != "memory:" + value.experience_id:
        raise PermissionError("social Memory identity mismatch")


def authorized_social_memories(character, store, *, history, trust, tick):
    """Derive exact Character grants from verified canonical records, no index Store."""
    records = {item.id: item for item in store.get_all_memories()}
    accepted = []
    for memory in records.values():
        if memory.type != SOCIAL_MEMORY_TYPE or memory.owner_id != character.agent_id:
            continue
        value = memory.content
        if type(value) is not SocialExperience or value.character_id != character.id:
            continue
        verify_experience(memory, records=records, history=history, trust=trust,
                          timeline_id=history.timeline_id, tick=tick)
        accepted.append(memory)
    return tuple(sorted(accepted, key=lambda item: item.id))


def with_social_memory_grants(character, store, *, history, trust, tick):
    memories = authorized_social_memories(character, store, history=history, trust=trust, tick=tick)
    return replace(character, memory_ids=list(dict.fromkeys([
        *character.memory_ids, *(item.id for item in memories)])))


class SocialExperienceService:
    """Opt-in comparison and formal Memory policy, reusing the canonical lifecycle."""

    def __init__(self, *, runtime, cognition, memory_store, policy):
        from cognitive_world.cognition.consolidator import MemoryDecisionEngine
        from cognitive_world.memory.memory_decision import MemoryDecisionAuthority
        from cognitive_world.memory.memory_persistence import MemoryPersistence
        self.runtime, self.cognition, self.store = runtime, cognition, memory_store
        self.policy = policy
        processor = runtime.event_processor
        self.trust = processor.persistence_trust
        if self.trust is None or runtime.memory_revision_lineage is None:
            raise PermissionError("durable social review requires signed canonical history")
        self.engine = MemoryDecisionEngine(
            policy=policy, authority=MemoryDecisionAuthority(),
            event_history=runtime.context.event_history, write_fence=runtime.write_fence)
        self.persistence = MemoryPersistence(
            memory_store, runtime.context.event_history,
            write_fence=runtime.write_fence, memory_revision_lineage=runtime.memory_revision_lineage,
            persistence_trust=self.trust, simulation_clock=runtime.context.clock)

    def create_goal(self, *, character, draft):
        return _create_goal(self, character=character, draft=draft)

    def after_l1(self, context):
        return _after_l1(self, context)

    def review(self, *, character, speech_memory_id, evidence_memory_id):
        from cognitive_world.cognition.memory_proposal import MemoryProposal
        from cognitive_world.memory.memory_write_factory import MemoryWriteFactory
        from cognitive_world.memory.decision_policy import MemoryDecisionResult
        rt = self.runtime
        with rt.write_fence.commit_scope():
            _character_identity(self, character)
            speech = self.store.get_memory(speech_memory_id)
            evidence = self.store.get_memory(evidence_memory_id)
            if speech is None or evidence is None:
                raise PermissionError("required consumed evidence is unavailable")
            # Verified ancestor experience is immutable. Merely reviewing the
            # same proof pair on a child does not create a new experience.
            for prior in self.store.get_memories_by_owner(character.agent_id):
                if (prior.type == SOCIAL_MEMORY_TYPE and type(prior.content) is SocialExperience
                        and prior.content.character_id == character.id
                        and prior.content.speech_memory_id == speech.id
                        and prior.content.evidence_memory_id == evidence.id):
                    verify_experience(prior, records={m.id: m for m in self.store.get_all_memories()},
                        history=rt.context.event_history, trust=self.trust,
                        timeline_id=rt.context.event_history.timeline_id, tick=rt.context.clock.current_time)
                    return prior
            value = build_experience(
                owner_id=character.agent_id, character_id=character.id,
                speech=speech, evidence=evidence, history=rt.context.event_history,
                trust=self.trust, tick=rt.context.clock.current_time)
            prior = self.store.get_memory("memory:" + value.experience_id)
            if prior is not None:
                verify_experience(prior, records={m.id: m for m in self.store.get_all_memories()},
                                  history=rt.context.event_history, trust=self.trust,
                                  timeline_id=rt.context.event_history.timeline_id,
                                  tick=rt.context.clock.current_time)
                if prior.content != value:
                    raise PermissionError("conflicting social experience")
                return prior
            proposal = MemoryProposal(
                value.experience_id, speech.source_event, character.agent_id,
                SOCIAL_MEMORY_TYPE, value, 0.5)
            decision = self.engine.decide(proposal)
            if decision.result is not MemoryDecisionResult.ACCEPTED:
                return None
            request = MemoryWriteFactory().create_request(decision, proposal)
            try:
                return self.persistence.save(request)
            except BaseException:
                rt.write_fence.mark_recovery_required()
                raise


@dataclass(frozen=True)
class EvidenceGoalDraft:
    description: str
    priority: float
    evidence_memory_ids: tuple[str, ...]
    completion_condition: object | None = None

    def __post_init__(self):
        if self.completion_condition is not None:
            from cognitive_world.cognition.goal_completion import GoalCompletionCondition
            if type(self.completion_condition) is not GoalCompletionCondition:
                raise TypeError("Goal completion requires an explicit typed condition")
            self.completion_condition.__post_init__()


def _character_identity(service, character):
    agent = service.runtime.context.agent_registry.get(character.agent_id)
    if agent is None or agent.character_id != character.id:
        raise PermissionError("social Character is not the registered owner identity")
    return agent


def _create_goal(service, *, character, draft):
    from cognitive_world.cognition.goal_creation import GoalCreationProposal
    from cognitive_world.cognition.validation import CognitiveUpdateValidator
    from cognitive_world.cognition.update_apply import CognitiveUpdateApplier
    from cognitive_world.agent.runtime_agent import RuntimeAgent
    rt = service.runtime
    if type(draft) is not EvidenceGoalDraft:
        raise TypeError("goal policy must return EvidenceGoalDraft")
    if (not isinstance(draft.evidence_memory_ids, tuple) or not draft.evidence_memory_ids
            or len(set(draft.evidence_memory_ids)) != len(draft.evidence_memory_ids)):
        raise PermissionError("new Goal requires explicit unique evidence")
    with rt.write_fence.commit_scope(), rt.context.agent_registry.snapshot_scope():
        agent = _character_identity(service, character)
        memories = authorized_social_memories(character, service.store,
            history=rt.context.event_history, trust=service.trust, tick=rt.context.clock.current_time)
        allowed = {m.id for m in memories}
        if not set(draft.evidence_memory_ids).issubset(allowed):
            raise PermissionError("new Goal cites unauthorized social evidence")
        identity = json.dumps([character.id, draft.description, draft.priority,
                               sorted(draft.evidence_memory_ids)], allow_nan=False,
                              ensure_ascii=False, separators=(",", ":"))
        goal_id = "evidence-goal:" + sha256(identity.encode()).hexdigest()
        from cognitive_world.cognition.goal_completion import COMPLETION_KEY
        metadata = ({} if draft.completion_condition is None else {
            COMPLETION_KEY: draft.completion_condition.as_value()})
        proposal = GoalCreationProposal(character.agent_id, goal_id, draft.description,
                                        draft.priority, list(draft.evidence_memory_ids), metadata)
        validation = CognitiveUpdateValidator().validate(proposal, {
            "agent_id": character.agent_id, "authorized_source_refs": tuple(allowed)})
        if not validation.accepted:
            raise PermissionError(validation.reason)
        prior = service.cognition.goal_store.get_owned(character.agent_id, goal_id)
        if prior is not None:
            if goal_id not in agent.goal_ids:
                raise PermissionError("previous Goal has no canonical Agent association")
            return prior
        try:
            goal = CognitiveUpdateApplier(service.cognition.belief_store,
                service.cognition.goal_store, service.cognition.self_model_store,
                write_fence=rt.write_fence).apply(proposal, validation)
            rt.context.agent_registry.register(RuntimeAgent(
                agent.agent_id, agent.character_id, [*agent.goal_ids, goal_id], agent.metadata))
            return goal
        except BaseException:
            rt.write_fence.mark_recovery_required()
            raise


def _after_l1(service, context):
    """Bounded owner-only review; next turn rebuilds grants from canonical records."""
    from cognitive_world.agent.character import Character
    from cognitive_world.cognition.l1_consumption_proof import PROOF_MEMORY_TYPE, NONVERBAL_PROOF_MEMORY_TYPE
    if context.cognition_container is not service.cognition or context.memory_store is not service.store:
        raise PermissionError("social review context is not the canonical owner context")
    character = Character(context.character_id, context.owner_id, "")
    _character_identity(service, character)
    records = service.store.get_memories_by_owner(context.owner_id)
    speech = [m for m in records if m.type == PROOF_MEMORY_TYPE][-16:]
    evidence = [m for m in records if m.type == NONVERBAL_PROOF_MEMORY_TYPE][-16:]
    for spoken in speech:
        for observed in evidence:
            try:
                build_experience(owner_id=context.owner_id, character_id=context.character_id,
                    speech=spoken, evidence=observed, history=service.runtime.context.event_history,
                    trust=service.trust, tick=service.runtime.context.clock.current_time)
            except PermissionError:
                continue
            service.review(character=character, speech_memory_id=spoken.id, evidence_memory_id=observed.id)
    memories = authorized_social_memories(character, service.store,
        history=service.runtime.context.event_history, trust=service.trust,
        tick=service.runtime.context.clock.current_time)
    propose_beliefs = getattr(service.policy, "propose_beliefs", None)
    if callable(propose_beliefs):
        from cognitive_world.cognition.belief_update import BeliefUpdateProposal
        from cognitive_world.cognition.validation import CognitiveUpdateValidator
        from cognitive_world.cognition.update_apply import CognitiveUpdateApplier
        proposals = propose_beliefs(context.get_beliefs(), tuple((m.id, m.content) for m in memories))
        if not isinstance(proposals, tuple) or len(proposals) > 4:
            raise ValueError("belief policy must return at most four proposals")
        for proposal in proposals:
            if type(proposal) is not BeliefUpdateProposal:
                raise TypeError("unsupported belief proposal")
            validation = CognitiveUpdateValidator().validate(proposal, {
                "agent_id": context.owner_id, "authorized_source_refs": tuple(m.id for m in memories)})
            if not validation.accepted:
                raise PermissionError(validation.reason)
            CognitiveUpdateApplier(service.cognition.belief_store, service.cognition.goal_store,
                service.cognition.self_model_store, write_fence=service.runtime.write_fence).apply(proposal, validation)
    propose = getattr(service.policy, "propose_goals", None)
    if callable(propose):
        memories = authorized_social_memories(character, service.store,
            history=service.runtime.context.event_history, trust=service.trust,
            tick=service.runtime.context.clock.current_time)
        drafts = propose(tuple((m.id, m.content) for m in memories))
        if not isinstance(drafts, tuple) or len(drafts) > 4:
            raise ValueError("goal policy must return at most four immutable drafts")
        for draft in drafts:
            service.create_goal(character=character, draft=draft)
