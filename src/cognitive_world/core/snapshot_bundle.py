"""Signed association between independently persisted world and cognition snapshots.

This contract prevents valid files from different ticks or timelines being
assembled into one apparent save. It stages isolated state only; it does not
publish an active Runtime or provide timeline isolation by itself.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json

from cognitive_world.core.persistence import PersistenceTrust, PersistedValueCodec, sha256_hex
from cognitive_world.core.issued_credentials import (
    _issue_object_credential, _require_object_credential,
)


_SCHEMA = "cognitive-world/snapshot-bundle-manifest"
_VERSION = 2
_LEGACY_VERSION = 1
_PURPOSE = "cognitive-world/snapshot-bundle-manifest/v2"
_LEGACY_PURPOSE = "cognitive-world/snapshot-bundle-manifest/v1"
_VERIFIED_BUNDLE_SEAL = object()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class SnapshotBundleManifest:
    version: int
    timeline_id: str
    simulation_tick: int
    world_checkpoint_sha256: str
    cognitive_snapshot_sha256: str
    event_chain_head_sha256: str | None
    cognitive_agent_manifest_sha256: str
    signature: bytes
    behavior_feedback_sha256: str | None = None

    def __post_init__(self) -> None:
        if (self.version not in {_LEGACY_VERSION, _VERSION} or not isinstance(self.timeline_id, str)
                or not self.timeline_id or isinstance(self.simulation_tick, bool)
                or not isinstance(self.simulation_tick, int) or self.simulation_tick < 0
                or not self.signature):
            raise ValueError("invalid snapshot bundle manifest")
        if ((self.version == _LEGACY_VERSION and self.behavior_feedback_sha256 is not None)
                or (self.version == _VERSION and (
                    not isinstance(self.behavior_feedback_sha256, str)
                    or len(self.behavior_feedback_sha256) != 64
                ))):
            raise ValueError("SnapshotBundle has invalid BehaviorFeedback component binding")
        for digest in (self.world_checkpoint_sha256, self.cognitive_snapshot_sha256,
                       self.cognitive_agent_manifest_sha256):
            if not isinstance(digest, str) or len(digest) != 64:
                raise ValueError("snapshot bundle requires SHA-256 component digests")
        if self.event_chain_head_sha256 is not None and len(self.event_chain_head_sha256) != 64:
            raise ValueError("invalid Event chain head digest")

    def _body(self) -> dict[str, object]:
        result = {
            "schema": _SCHEMA,
            "version": self.version,
            "timeline_id": self.timeline_id,
            "simulation_tick": self.simulation_tick,
            "world_checkpoint_sha256": self.world_checkpoint_sha256,
            "cognitive_snapshot_sha256": self.cognitive_snapshot_sha256,
            "event_chain_head_sha256": self.event_chain_head_sha256,
            "cognitive_agent_manifest_sha256": self.cognitive_agent_manifest_sha256,
        }
        if self.version >= _VERSION:
            result["behavior_feedback_sha256"] = self.behavior_feedback_sha256
        return result

    def to_bytes(self) -> bytes:
        return _canonical({**self._body(), "signature": base64.b64encode(self.signature).decode("ascii")})

    def verify_signature(self, trust: PersistenceTrust) -> bool:
        """Verify this version with its fixed schema-specific purpose."""
        purpose = _PURPOSE if self.version >= _VERSION else _LEGACY_PURPOSE
        return trust.verify(purpose, _canonical(self._body()), self.signature)

    @classmethod
    def create(
        cls, *, world_checkpoint: bytes, cognitive_snapshot: object,
        expected_agents: tuple[object, ...], trust: PersistenceTrust,
        event_history_resolver: object | None = None,
        behavior_feedback_snapshot: bytes | None = None,
        memory_revision_lineage: object | None = None,
        codec: PersistedValueCodec | None = None,
    ) -> "SnapshotBundleManifest":
        from cognitive_world.cognition.snapshot import (
            CognitiveAgentManifestEntry, CognitiveStateSnapshot, reconstruct_isolated,
        )
        from cognitive_world.core.world_state import WorldState

        if codec is not None and type(codec) is not PersistedValueCodec:
            raise TypeError("bundle persistence codec must use the canonical explicit allow-list")

        if not isinstance(world_checkpoint, bytes):
            raise TypeError("world checkpoint must be serialized bytes")
        if type(cognitive_snapshot) is CognitiveStateSnapshot:
            cognitive_bytes = cognitive_snapshot.to_bytes()
        elif isinstance(cognitive_snapshot, bytes):
            cognitive_bytes = cognitive_snapshot
        else:
            raise TypeError("cognitive snapshot must be a canonical snapshot or serialized bytes")
        if (not isinstance(expected_agents, tuple)
                or any(type(item) is not CognitiveAgentManifestEntry for item in expected_agents)):
            raise TypeError("bundle creation requires the independently trusted Agent manifest")

        world, history, tick = WorldState.restore_persisted_snapshot(
            world_checkpoint, trust=trust, codec=codec,
            event_history_resolver=event_history_resolver,
        )
        del world  # only isolated validation is required to issue the bundle manifest
        world_envelope = json.loads(world_checkpoint.decode("utf-8"))
        cognitive = CognitiveStateSnapshot.from_bytes(cognitive_bytes, trust=trust)
        isolated = reconstruct_isolated(
            cognitive, trust=trust, expected_agents=expected_agents, event_history=history,
            memory_revision_lineage=memory_revision_lineage,
        )
        if cognitive.body.timeline_id != world_envelope["timeline_id"]:
            raise ValueError("snapshot components belong to different timelines")
        if cognitive.body.simulation_tick != tick:
            raise ValueError("snapshot components belong to different simulation ticks")
        if behavior_feedback_snapshot is None:
            version = _LEGACY_VERSION
            behavior_digest = None
        else:
            if not isinstance(behavior_feedback_snapshot, bytes):
                raise TypeError("BehaviorFeedback snapshot must be serialized bytes")
            from cognitive_world.decision.behavior_feedback_snapshot import BehaviorFeedbackSnapshot
            BehaviorFeedbackSnapshot.verify_and_restore(
                payload=behavior_feedback_snapshot, event_history=history,
                timeline_id=world_envelope["timeline_id"], simulation_tick=tick,
                session_id=cognitive.body.session_id,
                restore_generation=cognitive.body.restore_generation,
                agent_ids=tuple(sorted(cognitive.body.agent_ids)),
                memory_store=isolated.memory_store, trust=trust,
            )
            version = _VERSION
            behavior_digest = sha256_hex(behavior_feedback_snapshot)
        roster_codec = PersistedValueCodec()
        for value_type in (CognitiveAgentManifestEntry,):
            roster_codec.register_type(value_type)
        event_head = history.last_persistence_record_digest()
        body_without_signature = {
            "schema": _SCHEMA, "version": version,
            "timeline_id": world_envelope["timeline_id"], "simulation_tick": tick,
            "world_checkpoint_sha256": sha256_hex(world_checkpoint),
            "cognitive_snapshot_sha256": sha256_hex(cognitive_bytes),
            "event_chain_head_sha256": event_head,
            "cognitive_agent_manifest_sha256": sha256_hex(roster_codec.dumps(isolated.expected_agents)),
        }
        if version >= _VERSION:
            body_without_signature["behavior_feedback_sha256"] = behavior_digest
        purpose = _PURPOSE if version >= _VERSION else _LEGACY_PURPOSE
        signature = trust.sign(purpose, _canonical(body_without_signature))
        if not isinstance(signature, bytes) or not signature:
            raise TypeError("persistence trust authority returned an invalid bundle signature")
        return cls(version, world_envelope["timeline_id"], tick,
                   body_without_signature["world_checkpoint_sha256"],
                   body_without_signature["cognitive_snapshot_sha256"], event_head,
                   body_without_signature["cognitive_agent_manifest_sha256"], signature,
                   behavior_digest)

    @classmethod
    def from_bytes(cls, payload: bytes) -> "SnapshotBundleManifest":
        try:
            value = json.loads(payload.decode("utf-8"))
            expected = {"schema", "version", "timeline_id", "simulation_tick",
                        "world_checkpoint_sha256", "cognitive_snapshot_sha256",
                        "event_chain_head_sha256", "cognitive_agent_manifest_sha256", "signature"}
            version = value.get("version") if isinstance(value, dict) else None
            if version == _VERSION:
                expected.add("behavior_feedback_sha256")
            if not isinstance(value, dict) or set(value) != expected or value["schema"] != _SCHEMA:
                raise ValueError("malformed snapshot bundle manifest")
            signature = base64.b64decode(value["signature"], validate=True)
            return cls(value["version"], value["timeline_id"], value["simulation_tick"],
                       value["world_checkpoint_sha256"], value["cognitive_snapshot_sha256"],
                       value["event_chain_head_sha256"], value["cognitive_agent_manifest_sha256"],
                       signature, value.get("behavior_feedback_sha256"))
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError,
                base64.binascii.Error) as error:
            raise ValueError("malformed snapshot bundle manifest") from error

    def verify_and_stage(
        self, *, world_checkpoint: bytes, cognitive_snapshot: bytes,
        expected_agents: tuple[object, ...], trust: PersistenceTrust,
        event_history_resolver: object | None = None,
        behavior_feedback_snapshot: bytes | None = None,
        memory_revision_lineage: object | None = None,
        codec: PersistedValueCodec | None = None,
    ) -> "VerifiedSnapshotBundle":
        from cognitive_world.cognition.snapshot import (
            CognitiveAgentManifestEntry, CognitiveStateSnapshot, reconstruct_isolated,
        )
        from cognitive_world.core.world_state import WorldState

        if codec is not None and type(codec) is not PersistedValueCodec:
            raise TypeError("bundle persistence codec must use the canonical explicit allow-list")

        if not self.verify_signature(trust):
            raise PermissionError("snapshot bundle signer is not trusted or signature is invalid")
        if (sha256_hex(world_checkpoint) != self.world_checkpoint_sha256
                or sha256_hex(cognitive_snapshot) != self.cognitive_snapshot_sha256):
            raise PermissionError("snapshot bundle component digest mismatch")
        world, history, tick = WorldState.restore_persisted_snapshot(
            world_checkpoint, trust=trust, codec=codec,
            event_history_resolver=event_history_resolver,
        )
        envelope = json.loads(world_checkpoint.decode("utf-8"))
        cognition_snapshot = CognitiveStateSnapshot.from_bytes(cognitive_snapshot, trust=trust)
        isolated = reconstruct_isolated(
            cognition_snapshot, trust=trust, expected_agents=expected_agents,
            event_history=history, memory_revision_lineage=memory_revision_lineage,
        )
        if self.version >= _VERSION:
            if not isinstance(behavior_feedback_snapshot, bytes):
                raise PermissionError("signed SnapshotBundle requires its BehaviorFeedback component")
            if sha256_hex(behavior_feedback_snapshot) != self.behavior_feedback_sha256:
                raise PermissionError("BehaviorFeedback component digest mismatch")
            from cognitive_world.decision.behavior_feedback_snapshot import BehaviorFeedbackSnapshot
            feedback_result = BehaviorFeedbackSnapshot.verify_and_restore(
                payload=behavior_feedback_snapshot, event_history=history,
                timeline_id=self.timeline_id, simulation_tick=self.simulation_tick,
                session_id=cognition_snapshot.body.session_id,
                restore_generation=cognition_snapshot.body.restore_generation,
                agent_ids=tuple(sorted(cognition_snapshot.body.agent_ids)),
                memory_store=isolated.memory_store, trust=trust,
            )
        else:
            if behavior_feedback_snapshot is not None:
                raise PermissionError("legacy SnapshotBundle cannot accept an unsigned feedback component")
            from cognitive_world.decision.behavior_feedback import BehaviorFeedback
            from cognitive_world.decision.behavior_feedback_snapshot import VerifiedBehaviorFeedback
            feedback_result = VerifiedBehaviorFeedback(
                BehaviorFeedback(), "legacy_not_captured", self.timeline_id,
                self.simulation_tick, cognition_snapshot.body.session_id,
                cognition_snapshot.body.restore_generation,
                tuple(sorted(cognition_snapshot.body.agent_ids)),
            )
        roster_codec = PersistedValueCodec()
        roster_codec.register_type(CognitiveAgentManifestEntry)
        roster_digest = sha256_hex(roster_codec.dumps(isolated.expected_agents))
        if (tick != self.simulation_tick or envelope["timeline_id"] != self.timeline_id
                or cognition_snapshot.body.simulation_tick != self.simulation_tick
                or cognition_snapshot.body.timeline_id != self.timeline_id
                or history.last_persistence_record_digest() != self.event_chain_head_sha256
                or roster_digest != self.cognitive_agent_manifest_sha256):
            raise PermissionError("snapshot bundle components have inconsistent timeline, tick, or lineage")
        verified = VerifiedSnapshotBundle(
            world, history, isolated, self.timeline_id, self.simulation_tick,
            feedback_result.feedback, feedback_result.status, behavior_feedback_snapshot,
            isolated.memory_store._revision_lineage, _VERIFIED_BUNDLE_SEAL,
            _verified_manifest_sha256=sha256_hex(self.to_bytes()),
            _codec=codec or PersistedValueCodec(),
        )
        _issue_object_credential("VerifiedSnapshotBundle", verified,
                                 _verified_bundle_fingerprint(verified))
        return verified


@dataclass(frozen=True)
class VerifiedSnapshotBundle:
    world_state: object
    event_history: object
    cognition: object
    timeline_id: str
    simulation_tick: int
    behavior_feedback: object
    behavior_feedback_status: str
    behavior_feedback_snapshot: bytes | None
    memory_revision_lineage: object | None = None
    _verification_seal: object = None
    _verified_manifest_sha256: str | None = field(default=None, repr=False, compare=False)
    _codec: object | None = field(default=None, repr=False, compare=False)

    def _require_issued(self) -> None:
        _require_object_credential("VerifiedSnapshotBundle", self,
                                   _verified_bundle_fingerprint(self))

    def verify_manifest_binding(self, manifest: SnapshotBundleManifest) -> None:
        """Require this isolated result to match the exact verified manifest."""
        if type(manifest) is not SnapshotBundleManifest:
            raise TypeError("verified Bundle binding requires a canonical manifest")
        self._require_issued()
        if (self._verification_seal is not _VERIFIED_BUNDLE_SEAL
                or not isinstance(self._verified_manifest_sha256, str)
                or self._verified_manifest_sha256 != sha256_hex(manifest.to_bytes())):
            raise PermissionError("verified Bundle is not bound to this exact manifest")


def _require_verified_snapshot_bundle(bundle: object) -> VerifiedSnapshotBundle:
    """Require a verifier-issued, intact Bundle before trusting its contents."""
    if type(bundle) is not VerifiedSnapshotBundle:
        raise TypeError("expected a canonical verified SnapshotBundle")
    bundle._require_issued()
    return bundle


def _verified_bundle_fingerprint(bundle: VerifiedSnapshotBundle) -> tuple[object, ...]:
    """Fingerprint the complete issued projection, not just component identities.

    These are process-local misuse guards. The persistent resources must still
    be re-read and verified before restoration or activation.
    """
    from cognitive_world.core.persistence import PersistedValueCodec

    from cognitive_world.core.world_state import WorldState
    if type(bundle.world_state) is not WorldState:
        raise PermissionError("verified Bundle has an unsupported WorldState component")
    world = bundle.world_state
    if set(vars(world)) != {
            "_entities", "_locations", "_relationships", "_facts", "_environment",
            "_environment_snapshot_complete", "_initialization_sealed", "_world_norms",
            "_slot_origins",
        }:
        raise PermissionError("verified Bundle WorldState has unsupported state")
    codec = bundle._codec
    if type(codec) is not PersistedValueCodec:
        raise PermissionError("verified Bundle has no supported persistence codec")
    slot_origins = [
        (slot.to_record(), origin.kind, origin.present,
         origin.value_fingerprint, origin.event_id)
        for slot, origin in world._slot_origins.items()
    ]
    slot_origins.sort(key=lambda item: _canonical(item[0]))
    world_content = codec.dumps({
        "entities": world._entities,
        "locations": world._locations,
        "relationships": world._relationships,
        "facts": world._facts,
        "environment": world._environment,
        "world_norms": world._world_norms,
        "environment_snapshot_complete": world._environment_snapshot_complete,
        "initialization_sealed": world._initialization_sealed,
        "slot_origins": slot_origins,
    })

    history_content = _event_history_content(bundle.event_history, set())
    from cognitive_world.core.persistence import sha256_hex
    history_digest = sha256_hex(codec.dumps(history_content))

    from cognitive_world.cognition.belief import BeliefStore
    from cognitive_world.cognition.container import CognitionContainer
    from cognitive_world.cognition.goal import GoalStore
    from cognitive_world.cognition.memory_store import MemoryStore
    from cognitive_world.cognition.personality import PersonalityStore
    from cognitive_world.cognition.self_model import SelfModelStore
    from cognitive_world.cognition.snapshot import IsolatedCognitiveRestore, cognitive_snapshot_codec
    if type(bundle.cognition) is not IsolatedCognitiveRestore:
        raise PermissionError("verified Bundle has an unsupported cognition component")
    isolated = bundle.cognition
    container = isolated.cognition
    if (type(container) is not CognitionContainer
            or type(container.belief_store) is not BeliefStore
            or type(container.goal_store) is not GoalStore
            or type(container.self_model_store) is not SelfModelStore
            or type(container.personality_store) is not PersonalityStore
            or type(isolated.memory_store) is not MemoryStore):
        raise PermissionError("verified Bundle has unsupported canonical cognition Stores")
    if (set(vars(container)) != {
            "personality_store", "belief_store", "goal_store", "self_model_store",
            "_emotions", "write_fence",
        }
            or set(vars(isolated.memory_store)) != {
                "_memories", "write_fence", "_revision_lineage",
            }
            or set(vars(container.belief_store)) != {"_beliefs", "write_fence"}
            or set(vars(container.goal_store)) != {"_goals", "write_fence"}
            or set(vars(container.self_model_store)) != {"_self_models", "write_fence"}
            or set(vars(container.personality_store)) != {"_personalities", "write_fence"}):
        raise PermissionError("verified Bundle cognition Store has unsupported state")
    cognition_codec = cognitive_snapshot_codec()
    cognition_records = (
        tuple(container.belief_store.get_all()),
        tuple(container.goal_store.get_all()),
        tuple(container.self_model_store.get_all()),
        tuple(isolated.memory_store.get_all_memories()),
        tuple(container.emotions.values()),
        tuple(container.personality_store.get_all()),
    )
    cognition_bindings = tuple(
        id(component) for component in (
            container.belief_store, container.goal_store, container.self_model_store,
            container.personality_store, isolated.memory_store,
        )
    ) + tuple(
        None if fence is None else id(fence)
        for fence in (
            container.write_fence, container.belief_store.write_fence,
            container.goal_store.write_fence, container.self_model_store.write_fence,
            container.personality_store.write_fence, isolated.memory_store.write_fence,
        )
    )
    cognition_metadata = (
        isolated.agent_ids, isolated.expected_agents, isolated.agent_registry_revision,
        isolated.agent_links, isolated.timeline_id, isolated.simulation_tick,
        isolated.session_id, isolated.captured_restore_generation,
        isolated.completeness, isolated.authenticity,
    )
    lineage = bundle.memory_revision_lineage
    if lineage is not None:
        from cognitive_world.cognition.memory_revision import (
            MemoryRevisionLineage, _lineage_fingerprint,
        )
        if type(lineage) is not MemoryRevisionLineage:
            raise PermissionError("verified Bundle has an unsupported Memory revision view")
        lineage._require_issued()
        lineage_fingerprint = _lineage_fingerprint(lineage)
        lineage_content = (
            lineage.timeline_id,
            tuple((record_id, encoded.hex())
                  for record_id, encoded in lineage.inherited_records),
            lineage.fork_checkpoint_id, lineage.parent_timeline_id,
            lineage.fork_manifest_sha256,
            lineage._seal is not None,
        )
    else:
        lineage_fingerprint = None
        lineage_content = None
    if isolated.memory_store._revision_lineage is not lineage:
        raise PermissionError("verified Bundle cognition has a different Memory revision view")
    cognition_digest = sha256_hex(cognition_codec.dumps((
        cognition_records, cognition_metadata, cognition_bindings, lineage_content,
    )))

    from cognitive_world.decision.behavior_feedback import BehaviorFeedback
    if type(bundle.behavior_feedback) is not BehaviorFeedback:
        raise PermissionError("verified Bundle has an unsupported BehaviorFeedback component")
    from cognitive_world.decision.behavior_feedback_snapshot import BehaviorFeedbackSnapshot, _canonical as feedback_canonical
    feedback = bundle.behavior_feedback
    from cognitive_world.decision.behavior_feedback import BehaviorFailure
    if (type(feedback.history) is not list
            or type(feedback._seen_events) is not set
            or any(type(item) is not BehaviorFailure for item in feedback.history)
            or any(not isinstance(item, str) for item in feedback._seen_events)):
        raise PermissionError("verified Bundle BehaviorFeedback has unsupported state")
    feedback_body = BehaviorFeedbackSnapshot._body(
        feedback, bundle.timeline_id, bundle.simulation_tick,
        isolated.session_id, isolated.captured_restore_generation, isolated.agent_ids,
    )
    feedback_body["seen_events"] = sorted(feedback._seen_events)
    feedback_digest = sha256_hex(feedback_canonical(feedback_body))

    if bundle._verification_seal is not _VERIFIED_BUNDLE_SEAL:
        raise PermissionError("verified Bundle seal is invalid")

    return (
        id(bundle.world_state), id(bundle.event_history), id(bundle.cognition),
        sha256_hex(world_content), history_digest, cognition_digest,
        bundle.timeline_id, bundle.simulation_tick, id(bundle.behavior_feedback),
        feedback_digest,
        bundle.behavior_feedback_status, bundle.behavior_feedback_snapshot,
        id(bundle.memory_revision_lineage), lineage_fingerprint,
        id(bundle._verification_seal), bundle._verified_manifest_sha256,
    )


def _event_history_content(history: object, ancestors: set[int]) -> object:
    """Build a stable projection of local and inherited EventHistory state."""
    from cognitive_world.event.history import EventHistory

    if type(history) is not EventHistory:
        raise PermissionError("verified Bundle has an unsupported EventHistory component")
    if set(vars(history)) != {
            "_events", "_processing_evidence", "_processing_records",
            "_persistence_records", "timeline_id", "fork_manifest_bytes",
            "fork_checkpoint_manifest_bytes", "_inherited_events", "_inherited_evidence",
            "_inherited_persistence_records", "_parent_history", "_lock",
        }:
        raise PermissionError("verified Bundle EventHistory has unsupported state")
    identity = id(history)
    if identity in ancestors:
        raise PermissionError("verified Bundle EventHistory contains a parent cycle")
    ancestors.add(identity)
    try:
        events = history.get_events()
        evidence = tuple(
            (event.id, history.get_processing_evidence(event.id))
            for event in events
        )
        persisted = tuple(
            record.to_json_record() for record in history.export_local_persisted_records()
        )
        inherited_persisted = tuple(
            record.to_json_record() for record in history._inherited_persistence_records
        )
        processing = tuple(sorted(
            (event_id, record.event_snapshot, record.status.value, record.failure)
            for event_id, record in history._processing_records.items()
        ))
        parent = (None if history._parent_history is None else
                  _event_history_content(history._parent_history, ancestors))
        return {
            "timeline_id": history.timeline_id,
            "fork_manifest_bytes": (None if history.fork_manifest_bytes is None
                                     else history.fork_manifest_bytes.hex()),
            "fork_checkpoint_manifest_bytes": (
                None if history.fork_checkpoint_manifest_bytes is None
                else history.fork_checkpoint_manifest_bytes.hex()
            ),
            "events": events,
            "evidence": evidence,
            "persisted_records": persisted,
            "inherited_persisted_records": inherited_persisted,
            "processing": processing,
            "parent": parent,
            "lock_identity": id(history._lock),
        }
    finally:
        ancestors.remove(identity)
