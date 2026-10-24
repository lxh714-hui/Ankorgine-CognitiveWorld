"""Narrow durable evidence that an addressed utterance crossed trusted L1."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from cognitive_world.core.persistence import PersistedValueCodec, PersistenceTrust
from cognitive_world.cognition.memory import SystemOnlyMemoryContent
from cognitive_world.observation.observation import Observation
from cognitive_world.event.persistence import EVENT_ATTESTATION_PURPOSE


PROOF_MEMORY_TYPE = "system_l1_consumption_proof_v1"
PROOF_PURPOSE = "cognitive-world/l1-consumption-proof/v1"
VISIBILITY_RULE = "addressed-utterance-delivered/v1"
NONVERBAL_PROOF_MEMORY_TYPE = "system_l1_nonverbal_consumption_proof_v1"
NONVERBAL_PROOF_PURPOSE = "cognitive-world/l1-nonverbal-consumption-proof/v1"
from cognitive_world.observation.historical_rules import (
    HISTORICAL_OBSERVATION_RULES, HistoricalObservationRuleRegistry,
)


@dataclass(frozen=True)
class L1ConsumptionProof(SystemOnlyMemoryContent):
    version: int
    proof_id: str
    owner_id: str
    observation_id: str
    observation_sha256: str
    source_event_id: str
    fact_id: str
    source_timeline_id: str
    consumption_timeline_id: str
    event_tick: int
    consumption_tick: int
    visibility_rule: str
    signature_hex: str

    def body(self) -> bytes:
        value = {
            "version": self.version, "proof_id": self.proof_id,
            "owner_id": self.owner_id, "observation_id": self.observation_id,
            "observation_sha256": self.observation_sha256,
            "source_event_id": self.source_event_id, "fact_id": self.fact_id,
            "source_timeline_id": self.source_timeline_id,
            "consumption_timeline_id": self.consumption_timeline_id,
            "event_tick": self.event_tick, "consumption_tick": self.consumption_tick,
            "visibility_rule": self.visibility_rule,
        }
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class NonverbalL1ConsumptionProof(SystemOnlyMemoryContent):
    """Separate-purpose proof for the currently verified non-verbal rule."""

    version: int
    proof_id: str
    owner_id: str
    observation_id: str
    observation_sha256: str
    source_event_id: str
    fact_id: str
    source_timeline_id: str
    consumption_timeline_id: str
    event_tick: int
    consumption_tick: int
    visibility_rule: str
    signature_hex: str

    def body(self) -> bytes:
        return json.dumps({
            "version": self.version, "proof_id": self.proof_id,
            "owner_id": self.owner_id, "observation_id": self.observation_id,
            "observation_sha256": self.observation_sha256,
            "source_event_id": self.source_event_id, "fact_id": self.fact_id,
            "source_timeline_id": self.source_timeline_id,
            "consumption_timeline_id": self.consumption_timeline_id,
            "event_tick": self.event_tick, "consumption_tick": self.consumption_tick,
            "visibility_rule": self.visibility_rule,
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
           allow_nan=False).encode("utf-8")


def _observation_digest(observation: Observation) -> str:
    codec = PersistedValueCodec()
    return sha256(codec.dumps((
        observation.observation_id, observation.observer_id,
        observation.source_event_id, observation.content,
        observation.metadata,
    ))).hexdigest()


def _issued_utterance_observation(event: object, evidence: object,
                                   owner_id: str, fact_id: str) -> Observation:
    """Frozen v1 addressed-delivery visibility rule over signed event-time facts."""
    if (event.type != "dialogue_input" or not event.has_trusted_source("system")
            or not evidence.has_trusted_source(event)
            or owner_id not in event.participants):
        raise PermissionError("source is not a trusted addressed utterance")
    context = evidence.event_time_context
    position = next((place for identity, place, _ in context.observer_positions
                     if identity == owner_id), None)
    fact = next((item for item in evidence.observable_facts
                 if item.fact_id == fact_id), None)
    if (fact is None or not fact.has_trusted_source(event)
            or fact.fact_type != "social_input"
            or fact.predicate != "utterance_delivered"
            or fact.subject_ref != owner_id
            or not isinstance(fact.value, str)
            or not isinstance(fact.location_id, str)
            or not fact.location_id
            or fact.location_id != context.fact_location_id
            or position != fact.location_id):
        raise PermissionError("utterance was not visible to the addressed owner")
    return Observation(
        f"observation:{event.id}:{owner_id}:{fact.fact_id}",
        owner_id, event.id, fact,
    )


def _source_timeline(history: object, event_id: str, trust: PersistenceTrust) -> str:
    record = history.get_persistence_record(event_id)
    if record is None or not trust.verify(
        EVENT_ATTESTATION_PURPOSE,
        record.attestation_payload, record.signature,
    ):
        raise PermissionError("consumption source lacks a verified Event credential")
    value = json.loads(record.attestation_payload.decode("utf-8"))
    timeline = value.get("timeline_id")
    if not isinstance(timeline, str) or not timeline:
        raise PermissionError("consumption source Timeline is invalid")
    return timeline


def verify_proof(proof: L1ConsumptionProof, *, history: object,
                 trust: PersistenceTrust, checkpoint_timeline_id: str,
                 checkpoint_tick: int) -> None:
    checkpoint_history = history
    while checkpoint_history.timeline_id != checkpoint_timeline_id:
        checkpoint_history = getattr(checkpoint_history, "_parent_history", None)
        if checkpoint_history is None:
            raise PermissionError("L1 proof checkpoint Timeline is outside EventHistory ancestry")
    if type(proof) is not L1ConsumptionProof or proof.version != 1 or proof.visibility_rule != VISIBILITY_RULE:
        raise PermissionError("unsupported L1 consumption proof")
    if any(not isinstance(value, str) or not value for value in (
        proof.proof_id, proof.owner_id, proof.observation_id,
        proof.observation_sha256, proof.source_event_id, proof.fact_id,
        proof.source_timeline_id, proof.consumption_timeline_id,
    )):
        raise PermissionError("L1 consumption proof identity is invalid")
    if (type(proof.event_tick) is not int or type(proof.consumption_tick) is not int
            or proof.event_tick < 0 or proof.event_tick > proof.consumption_tick
            or proof.consumption_tick > checkpoint_tick):
        raise PermissionError("L1 consumption proof time is invalid")
    expected_id = "l1-consumption:" + sha256((
        proof.consumption_timeline_id + "\0" + proof.owner_id + "\0"
        + proof.observation_id + "\0" + proof.observation_sha256
    ).encode("utf-8")).hexdigest()
    if proof.proof_id != expected_id:
        raise PermissionError("L1 consumption proof ID is inconsistent")
    lineage = history
    while proof.consumption_timeline_id != lineage.timeline_id:
        lineage = getattr(lineage, "_parent_history", None)
        if lineage is None:
            raise PermissionError("consumption Timeline is outside checkpoint ancestry")
    try:
        signature = bytes.fromhex(proof.signature_hex)
    except ValueError as error:
        raise PermissionError("invalid L1 proof signature encoding") from error
    if not trust.verify(PROOF_PURPOSE, proof.body(), signature):
        raise PermissionError("L1 proof signature is invalid")
    history.verify_persisted_lineage(codec=PersistedValueCodec(), trust=trust)
    event = history.get_event(proof.source_event_id)
    evidence = history.get_processing_evidence(proof.source_event_id)
    if (event is None or evidence is None or event.type != "dialogue_input"
            or event.simulation_tick != proof.event_tick
            or _source_timeline(history, event.id, trust) != proof.source_timeline_id):
        raise PermissionError("L1 proof source or historical visibility is invalid")
    expected = _issued_utterance_observation(
        event, evidence, proof.owner_id, proof.fact_id,
    )
    if (expected.observation_id != proof.observation_id
            or _observation_digest(expected) != proof.observation_sha256):
        raise PermissionError("L1 proof does not match the issued Observation")


def verify_nonverbal_proof(proof: NonverbalL1ConsumptionProof, *, history: object,
                           trust: PersistenceTrust, checkpoint_timeline_id: str,
                           checkpoint_tick: int,
                           rule_registry: HistoricalObservationRuleRegistry | None = None) -> None:
    if type(proof) is not NonverbalL1ConsumptionProof or proof.version != 1:
        raise PermissionError("unsupported non-verbal L1 proof")
    if rule_registry is None:
        rule_registry = HISTORICAL_OBSERVATION_RULES
    if any(not isinstance(value, str) or not value for value in (
        proof.proof_id, proof.owner_id, proof.observation_id, proof.observation_sha256,
        proof.source_event_id, proof.fact_id, proof.source_timeline_id,
        proof.consumption_timeline_id,
    )):
        raise PermissionError("non-verbal proof identity is invalid")
    if (type(proof.event_tick) is not int or type(proof.consumption_tick) is not int
            or proof.event_tick < 0 or proof.event_tick > proof.consumption_tick
            or proof.consumption_tick > checkpoint_tick):
        raise PermissionError("non-verbal proof time is invalid")
    expected_id = "l1-nonverbal-consumption:" + sha256((
        proof.consumption_timeline_id + "\0" + proof.owner_id + "\0"
        + proof.observation_id + "\0" + proof.observation_sha256
    ).encode("utf-8")).hexdigest()
    if proof.proof_id != expected_id:
        raise PermissionError("non-verbal proof ID is inconsistent")
    lineage = history
    while lineage.timeline_id != checkpoint_timeline_id:
        lineage = getattr(lineage, "_parent_history", None)
        if lineage is None:
            raise PermissionError("checkpoint Timeline is outside EventHistory ancestry")
    lineage = history
    while lineage.timeline_id != proof.consumption_timeline_id:
        lineage = getattr(lineage, "_parent_history", None)
        if lineage is None:
            raise PermissionError("consumption Timeline is outside checkpoint ancestry")
    try:
        signature = bytes.fromhex(proof.signature_hex)
    except ValueError:
        raise PermissionError("invalid non-verbal proof signature encoding") from None
    if not trust.verify(NONVERBAL_PROOF_PURPOSE, proof.body(), signature):
        raise PermissionError("non-verbal proof signature is invalid")
    history.verify_persisted_lineage(codec=PersistedValueCodec(), trust=trust)
    event = history.get_event(proof.source_event_id)
    evidence = history.get_processing_evidence(proof.source_event_id)
    if (event is None or evidence is None or event.simulation_tick != proof.event_tick
            or _source_timeline(history, event.id, trust) != proof.source_timeline_id):
        raise PermissionError("non-verbal proof source or timeline is invalid")
    rule = rule_registry.by_reference(proof.visibility_rule)
    try:
        expected = rule.issue(event, evidence, proof.owner_id, proof.fact_id)
    except Exception as error:
        raise PermissionError("registered historical visibility verification failed") from error
    if (type(expected) is not Observation
            or expected.observer_id != proof.owner_id
            or expected.source_event_id != proof.source_event_id
            or not expected.has_trusted_provenance()
            or expected.observation_id != proof.observation_id
            or _observation_digest(expected) != proof.observation_sha256):
        raise PermissionError("non-verbal proof does not match historical Observation")


class L1ConsumptionIssuer:
    """Trusted Runtime adapter; never accepts a caller-supplied proof body."""

    def __init__(self, *, history: object, clock: object, trust: PersistenceTrust,
                 fence: object,
                 rule_registry: HistoricalObservationRuleRegistry | None = None) -> None:
        self.history, self.clock, self.trust, self.fence = history, clock, trust, fence
        # Restored/pre-existing source Events without a v2 instance are ambiguous.
        self._instance_history_boundary = frozenset(e.id for e in history.get_events())
        self.rule_registry = (
            HISTORICAL_OBSERVATION_RULES if rule_registry is None else rule_registry
        )

    def accept_owner_result(self, **kwargs):
        from cognitive_world.cognition.l1_instance import accept_owner_result
        return accept_owner_result(self, **kwargs)

    def issue_after_l1(self, *, owner_id: str, observation: Observation,
                       cognitive_runtime: object, memory_store: object) -> L1ConsumptionProof | NonverbalL1ConsumptionProof | None:
        from cognitive_world.cognition.memory import Memory
        from cognitive_world.cognition.memory_store import _L1_PROOF_WRITE_AUTHORITY
        from cognitive_world.runtime.write_fence import RuntimeWriteFence

        if not cognitive_runtime.has_consumed_observation(
            owner_id, observation, source_event_id=observation.source_event_id,
        ):
            raise PermissionError("Observation was not consumed by this owner's L1")
        permit = RuntimeWriteFence.bind_current_permit()
        if permit is None:
            raise PermissionError("L1 proof issuance has no original Runtime permit")
        event = self.history.get_event(observation.source_event_id)
        evidence = self.history.get_processing_evidence(observation.source_event_id)
        if event is None or evidence is None:
            return None
        if (getattr(observation.content, "fact_type", None) == "action_result"
                and getattr(observation.content, "predicate", None) == "door_open_attempt_failed"):
            raise PermissionError("B2 requires authoritative instance acceptance, not a legacy receipt")
        rule = self.rule_registry.for_source(event, evidence)
        if rule is not None:
            return self._issue_nonverbal(
                owner_id=owner_id, observation=observation, event=event,
                evidence=evidence, memory_store=memory_store, permit=permit,
                authority=_L1_PROOF_WRITE_AUTHORITY, memory_type=Memory, rule=rule,
                rule_registry=self.rule_registry,
            )
        if event.type != "dialogue_input":
            return None
        expected = _issued_utterance_observation(
            event, evidence, owner_id, observation.content.fact_id,
        )
        if (expected.observation_id != observation.observation_id
                or _observation_digest(expected) != _observation_digest(observation)):
            raise PermissionError("L1 receipt has no matching processor-issued Observation")
        timeline = self.history.timeline_id
        digest = _observation_digest(observation)
        proof_id = "l1-consumption:" + sha256((
            timeline + "\0" + owner_id + "\0" + observation.observation_id + "\0" + digest
        ).encode("utf-8")).hexdigest()
        prior = memory_store.get_memory(proof_id)
        if prior is not None:
            with self.fence.commit_scope():
                self.fence.require_candidate_origin(permit)
                if (prior.type != PROOF_MEMORY_TYPE
                        or type(prior.content) is not L1ConsumptionProof
                        or prior.owner_id != owner_id
                        or prior.content.observation_sha256 != digest):
                    raise PermissionError("conflicting L1 consumption identity")
                verify_proof(prior.content, history=self.history, trust=self.trust,
                             checkpoint_timeline_id=timeline,
                             checkpoint_tick=self.clock.current_time)
                return prior.content
        unsigned = L1ConsumptionProof(
            1, proof_id, owner_id, observation.observation_id, digest,
            event.id, observation.content.fact_id,
            _source_timeline(self.history, event.id, self.trust), timeline,
            event.simulation_tick, self.clock.current_time, VISIBILITY_RULE, "pending",
        )
        signature = self.trust.sign(PROOF_PURPOSE, unsigned.body())
        proof = L1ConsumptionProof(**{**unsigned.__dict__, "signature_hex": signature.hex()})
        with self.fence.commit_scope():
            self.fence.require_candidate_origin(permit)
            verify_proof(proof, history=self.history, trust=self.trust,
                         checkpoint_timeline_id=timeline,
                         checkpoint_tick=self.clock.current_time)
            memory_store._commit_system_proof(
                Memory(proof_id, owner_id, PROOF_MEMORY_TYPE, proof, 0.0, event.id),
                authority=_L1_PROOF_WRITE_AUTHORITY, permit=permit,
            )
        return proof

    def _issue_nonverbal(self, *, owner_id: str, observation: Observation,
                         event: object, evidence: object, memory_store: object,
                         permit: object, authority: object, memory_type: type,
                         rule: object, rule_registry: HistoricalObservationRuleRegistry):
        from cognitive_world.cognition.memory import Memory
        if memory_type is not Memory:
            raise PermissionError("invalid canonical proof record type")
        reference = rule_registry.reference_for(rule)
        expected = rule.issue(event, evidence, owner_id, observation.content.fact_id)
        if (type(expected) is not Observation
                or expected.observer_id != owner_id
                or expected.source_event_id != event.id
                or not expected.has_trusted_provenance()
                or expected.observation_id != observation.observation_id
                or _observation_digest(expected) != _observation_digest(observation)):
            raise PermissionError("L1 receipt has no matching registered historical Observation")
        timeline, digest = self.history.timeline_id, _observation_digest(observation)
        proof_id = "l1-nonverbal-consumption:" + sha256((
            timeline + "\0" + owner_id + "\0" + observation.observation_id + "\0" + digest
        ).encode("utf-8")).hexdigest()
        prior = memory_store.get_memory(proof_id)
        if prior is not None:
            with self.fence.commit_scope():
                self.fence.require_candidate_origin(permit)
                if (prior.type != NONVERBAL_PROOF_MEMORY_TYPE
                        or type(prior.content) is not NonverbalL1ConsumptionProof
                        or prior.owner_id != owner_id or prior.content.observation_sha256 != digest):
                    raise PermissionError("conflicting non-verbal consumption identity")
                verify_nonverbal_proof(
                    prior.content, history=self.history, trust=self.trust,
                    checkpoint_timeline_id=timeline, checkpoint_tick=self.clock.current_time,
                    rule_registry=rule_registry,
                )
                return prior.content
        unsigned = NonverbalL1ConsumptionProof(
            1, proof_id, owner_id, observation.observation_id, digest,
            event.id, observation.content.fact_id,
            _source_timeline(self.history, event.id, self.trust), timeline,
            event.simulation_tick, self.clock.current_time,
            reference, "pending",
        )
        signature = self.trust.sign(NONVERBAL_PROOF_PURPOSE, unsigned.body())
        proof = NonverbalL1ConsumptionProof(
            **{**unsigned.__dict__, "signature_hex": signature.hex()}
        )
        with self.fence.commit_scope():
            self.fence.require_candidate_origin(permit)
            verify_nonverbal_proof(
                proof, history=self.history, trust=self.trust,
                checkpoint_timeline_id=timeline, checkpoint_tick=self.clock.current_time,
                rule_registry=rule_registry,
            )
            memory_store._commit_system_proof(
                Memory(proof_id, owner_id, NONVERBAL_PROOF_MEMORY_TYPE,
                       proof, 0.0, event.id),
                authority=authority, permit=permit,
            )
        return proof
