"""B2: immutable default L1 identity and checkpoint-verifiable owner-result proof.

This is a system evidence payload in the existing MemoryStore, not semantic Memory.
"""
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json

from cognitive_world.cognition.memory import Memory, SystemOnlyMemoryContent
from cognitive_world.core.persistence import PersistedValueCodec
from cognitive_world.observation.observation import Observation

INSTANCE_PROOF_MEMORY_TYPE = "system_l1_instance_consumption_proof_v2"
INSTANCE_PROOF_PURPOSE = "cognitive-world/l1-instance-consumption-proof/v2"
RESULT_RULE = "door-open-failed-owner-result/v1"
_INSTANCE_ACCEPTANCE_AUTHORITY = object()


class AmbiguousL1ConsumptionError(PermissionError):
    """Existing or reused L1 state cannot establish a fresh B2 occurrence."""

    code = "ambiguous_l1_consumption"


def _hash(value):
    return sha256(PersistedValueCodec().dumps(value)).hexdigest()


def default_instance_id(timeline, owner, observation_id):
    # Digest and time are bindings, never alternate identities for one input ID.
    return "l1-instance:" + _hash(("l1-consumption-instance/v1", timeline,
                                  owner, observation_id, "default"))


@dataclass(frozen=True)
class L1ConsumptionInstance(SystemOnlyMemoryContent):
    version: int
    instance_id: str
    owner_id: str
    timeline_id: str
    observation_id: str
    observation_sha256: str
    consumption_tick: int

    def validate(self):
        if (type(self.version) is not int or self.version != 1
                or any(not isinstance(s, str) or not s for s in
                       (self.instance_id, self.owner_id, self.timeline_id, self.observation_id))
                or type(self.consumption_tick) is not int or self.consumption_tick < 0
                or not isinstance(self.observation_sha256, str)
                or len(self.observation_sha256) != 64
                or any(c not in "0123456789abcdef" for c in self.observation_sha256)
                or self.instance_id != default_instance_id(
                    self.timeline_id, self.owner_id, self.observation_id)):
            raise PermissionError("invalid L1 consumption instance")


@dataclass(frozen=True)
class InstanceL1ConsumptionProof(SystemOnlyMemoryContent):
    version: int
    proof_id: str
    instance: L1ConsumptionInstance
    source_event_id: str
    fact_id: str
    source_timeline_id: str
    event_tick: int
    attempt_id: str
    attempt_fingerprint: str
    visibility_rule: str
    signature_hex: str

    @property
    def owner_id(self):
        return self.instance.owner_id

    def body(self):
        value = asdict(self)
        value.pop("signature_hex")
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")


def instance_proof_id(instance):
    return _proof_id_for_instance(instance.instance_id)


def _proof_id_for_instance(instance_id):
    return "l1-instance-proof:" + _hash((2, instance_id, RESULT_RULE))


def validate_instance_proof_structure(proof):
    if (type(proof) is not InstanceL1ConsumptionProof or type(proof.version) is not int
            or proof.version != 2 or type(proof.instance) is not L1ConsumptionInstance
            or proof.visibility_rule != RESULT_RULE):
        raise PermissionError("unsupported instance consumption proof")
    proof.instance.validate()
    if (proof.proof_id != instance_proof_id(proof.instance)
            or any(not isinstance(s, str) or not s for s in (
                proof.source_event_id, proof.fact_id, proof.source_timeline_id, proof.attempt_id))
            or not isinstance(proof.attempt_fingerprint, str)
            or len(proof.attempt_fingerprint) != 64
            or any(c not in "0123456789abcdef" for c in proof.attempt_fingerprint)
            or type(proof.event_tick) is not int
            or not 0 <= proof.event_tick <= proof.instance.consumption_tick):
        raise PermissionError("invalid instance proof bindings")


def verify_instance_proof(proof, *, history, trust, checkpoint_timeline_id,
                          checkpoint_tick, rule_registry=None, memory_revision_lineage=None):
    from cognitive_world.cognition.l1_consumption_proof import _observation_digest, _source_timeline
    from cognitive_world.observation.historical_rules import HISTORICAL_OBSERVATION_RULES
    if (type(proof) is not InstanceL1ConsumptionProof or type(proof.version) is not int
            or proof.version != 2 or type(proof.instance) is not L1ConsumptionInstance
            or proof.visibility_rule != RESULT_RULE):
        raise PermissionError("unsupported instance consumption proof")
    validate_instance_proof_structure(proof)
    instance = proof.instance
    if (type(proof.event_tick) is not int or type(checkpoint_tick) is not int
            or not 0 <= proof.event_tick <= instance.consumption_tick <= checkpoint_tick
            or proof.proof_id != instance_proof_id(instance)):
        raise PermissionError("instance proof identity or time mismatch")
    # Validate against the checkpoint's ancestry, not a descendant's later suffix.
    lineage = history
    while lineage is not None and lineage.timeline_id != checkpoint_timeline_id:
        lineage = getattr(lineage, "_parent_history", None)
    if lineage is None:
        raise PermissionError("checkpoint is outside instance proof ancestry")
    consumption_history = lineage
    while consumption_history is not None and consumption_history.timeline_id != instance.timeline_id:
        consumption_history = getattr(consumption_history, "_parent_history", None)
    if consumption_history is None:
        raise PermissionError("consumption Timeline is outside checkpoint ancestry")
    if consumption_history.fork_manifest_bytes is not None:
        from cognitive_world.core.timeline import TimelineForkManifest
        if instance.consumption_tick < TimelineForkManifest.from_bytes(
                consumption_history.fork_manifest_bytes).simulation_tick:
            raise PermissionError("consumption predates its Timeline")
    if instance.timeline_id != checkpoint_timeline_id:
        # A valid parent signature alone cannot place a post-fork proof into a
        # child's checkpoint, even when both operations have the same tick.
        from cognitive_world.cognition.memory_revision import MemoryRevisionLineage
        from cognitive_world.cognition.snapshot import cognitive_snapshot_codec
        if (type(memory_revision_lineage) is not MemoryRevisionLineage
                or memory_revision_lineage.timeline_id != checkpoint_timeline_id):
            raise PermissionError("ancestor proof requires verified checkpoint Memory lineage")
        memory_revision_lineage.verify_event_history(lineage)
        encoded = dict(memory_revision_lineage.inherited_records).get(proof.proof_id)
        if encoded is None:
            raise PermissionError("proof was not present in the inherited checkpoint")
        record = cognitive_snapshot_codec().loads(encoded)
        if (type(record) is not Memory or record.type != INSTANCE_PROOF_MEMORY_TYPE
                or record.owner_id != instance.owner_id or record.source_event != proof.source_event_id
                or record.content != proof):
            raise PermissionError("ancestor proof differs from its immutable checkpoint record")
    try:
        signature = bytes.fromhex(proof.signature_hex)
    except (TypeError, ValueError):
        raise PermissionError("invalid instance proof signature encoding") from None
    if not trust.verify(INSTANCE_PROOF_PURPOSE, proof.body(), signature):
        raise PermissionError("invalid instance proof signature")
    lineage.verify_persisted_lineage(codec=PersistedValueCodec(), trust=trust)
    event = consumption_history.get_event(proof.source_event_id)
    evidence = consumption_history.get_processing_evidence(proof.source_event_id)
    if (event is None or evidence is None or event.simulation_tick != proof.event_tick
            or _source_timeline(consumption_history, event.id, trust) != proof.source_timeline_id):
        raise PermissionError("instance proof source mismatch")
    source = event.metadata.get("confirmed_attempt_failure", {})
    if (source.get("attempt_id") != proof.attempt_id
            or source.get("attempt_fingerprint") != proof.attempt_fingerprint):
        raise PermissionError("instance proof Attempt mismatch")
    registry = HISTORICAL_OBSERVATION_RULES if rule_registry is None else rule_registry
    expected = registry.by_reference(proof.visibility_rule).issue(
        event, evidence, instance.owner_id, proof.fact_id)
    if (expected.observation_id != instance.observation_id
            or _observation_digest(expected) != instance.observation_sha256):
        raise PermissionError("instance proof Observation mismatch")


def accept_owner_result(issuer, *, owner_id, observation, cognitive_runtime, memory_store):
    """One real L1 acceptance followed by protected proof completion.

    No retry re-consumes. A post-L1 error freezes this Runtime before releasing
    the snapshot/write lock. Recovery uses only a previously published checkpoint.
    """
    from cognitive_world.cognition.runtime import CognitiveRuntime
    from cognitive_world.cognition.l1_history import L1HistoryContext
    from cognitive_world.cognition.memory_store import MemoryStore, _L1_PROOF_WRITE_AUTHORITY
    from cognitive_world.cognition.l1_consumption_proof import _observation_digest, _source_timeline
    from cognitive_world.runtime.write_fence import RuntimeWriteFence
    if type(cognitive_runtime) is not CognitiveRuntime or type(memory_store) is not MemoryStore:
        raise TypeError("instance acceptance requires canonical cognition and MemoryStore")
    permit = RuntimeWriteFence.bind_current_permit()
    with issuer.fence.commit_scope():
        issuer.fence.require_candidate_origin(permit)
        if memory_store.write_fence is not issuer.fence:
            raise PermissionError("instance proof Store belongs to another Runtime")
        # Read the immutable Runtime binding under the existing commit lock.
        # This is a pre-L1 prerequisite, not a consumption result or an upgrade.
        binding = issuer.fence._event_history_verification_context
        context = cognitive_runtime._history_context
        if (binding is None or type(context) is not L1HistoryContext
                or issuer.history is not binding[0] or issuer.trust is not binding[3]
                or context.history is not binding[0] or context.codec is not binding[2]
                or context.trust is not binding[3]):
            raise PermissionError("B2 history binding prerequisite is missing or mismatched")
        if (type(observation) is not Observation or observation.observer_id != owner_id
                or not observation.has_trusted_provenance()
                or observation.trusted_source_runtime_binding() != (
                    issuer.fence.session_id, issuer.fence.restore_generation)):
            raise PermissionError("result Observation is not authorized in this Runtime")
        timeline = issuer.history.timeline_id
        if not isinstance(timeline, str) or not timeline:
            raise PermissionError("instance acceptance requires a persistent Timeline")
        event = issuer.history.get_event(observation.source_event_id)
        evidence = issuer.history.get_processing_evidence(observation.source_event_id)
        if event is None or evidence is None:
            raise PermissionError("result source is not committed")
        # Source signature, exact rule, and Observation semantics are pre-L1 gates.
        issuer.fence._verify_complete_event_history(issuer.history)
        source_timeline = _source_timeline(issuer.history, event.id, issuer.trust)
        rule = issuer.rule_registry.by_reference(RESULT_RULE)
        expected = rule.issue(event, evidence, owner_id, observation.content.fact_id)
        digest = _observation_digest(observation)
        if (expected.observation_id != observation.observation_id
                or _observation_digest(expected) != digest):
            raise PermissionError("result does not match historical authorization")
        identity = default_instance_id(timeline, owner_id, observation.observation_id)
        proof_id = _proof_id_for_instance(identity)
        prior = memory_store.get_memory(proof_id)
        if prior is not None:
            if (prior.type != INSTANCE_PROOF_MEMORY_TYPE
                    or type(prior.content) is not InstanceL1ConsumptionProof
                    or prior.owner_id != owner_id or prior.id != proof_id
                    or prior.source_event != event.id
                    or prior.content.instance.observation_sha256 != digest):
                raise PermissionError("conflicting default consumption identity")
            verify_instance_proof(prior.content, history=issuer.history, trust=issuer.trust,
                checkpoint_timeline_id=timeline, checkpoint_tick=issuer.clock.current_time,
                rule_registry=issuer.rule_registry)
            return prior.content
        receipt = cognitive_runtime._l1_consumption_receipts.get((owner_id, observation.observation_id))
        if receipt is not None and receipt.instance is not None:
            if receipt.instance.observation_sha256 != digest:
                raise PermissionError("conflicting consumed Observation")
            issuer.fence.require_candidate_origin(receipt.original_permit)
            # No normal return from a partial B2 operation is permitted.
            raise PermissionError("consumption is incomplete; explicit recovery required")
        workspace = cognitive_runtime.working_memory_store.get(owner_id)
        percept_id = "percept:" + observation.observation_id
        if (event.id in issuer._instance_history_boundary or receipt is not None
                or (workspace is not None and (
                    workspace.owner_id != owner_id or percept_id in workspace.percept_ids))):
            # A missing qualified receipt is not evidence of non-consumption.
            # Reject before mutation; the legacy workspace remains transient,
            # excluded from checkpoints, and is never rolled back or promoted.
            raise AmbiguousL1ConsumptionError("ambiguous historical or legacy L1 consumption")
        candidate = L1ConsumptionInstance(
            1, identity, owner_id, timeline, observation.observation_id, digest,
            issuer.clock.capture().tick)
        candidate.validate()
        if type(event.simulation_tick) is not int or event.simulation_tick > candidate.consumption_tick:
            raise PermissionError("source Event is later than L1 acceptance")
        try:
            # From the first possible WorkingMemory mutation onward, no rollback
            # or durable atomicity is assumed, even if a callback writes then raises.
            cognitive_runtime._accept_result_instance(
                owner_id, observation, candidate, permit,
                authority=_INSTANCE_ACCEPTANCE_AUTHORITY)
            proof = _construct_instance_proof(candidate, event, observation, source_timeline)
            signature = issuer.trust.sign(INSTANCE_PROOF_PURPOSE, proof.body())
            proof = replace(proof, signature_hex=signature.hex())
            verify_instance_proof(proof, history=issuer.history, trust=issuer.trust,
                checkpoint_timeline_id=timeline, checkpoint_tick=issuer.clock.current_time,
                rule_registry=issuer.rule_registry)
            memory_store._commit_system_proof(
                Memory(proof_id, owner_id, INSTANCE_PROOF_MEMORY_TYPE, proof, 0.0, event.id),
                authority=_L1_PROOF_WRITE_AUTHORITY, permit=permit)
            return proof
        except BaseException:
            issuer.fence.mark_recovery_required()
            raise


def _construct_instance_proof(instance, event, observation, source_timeline):
    source = event.metadata["confirmed_attempt_failure"]
    return InstanceL1ConsumptionProof(
        2, instance_proof_id(instance), instance, event.id, observation.content.fact_id,
        source_timeline, event.simulation_tick, source["attempt_id"],
        source["attempt_fingerprint"], RESULT_RULE, "pending")
