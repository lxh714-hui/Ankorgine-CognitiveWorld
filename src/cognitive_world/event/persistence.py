"""Versioned signed persistence records for processed Events.

The signature certifies that the configured EventProcessor authority observed
the Event, applied the handler-produced update, issued its processing evidence,
and recorded the resulting changed-slot fingerprints. It is not a replay log or
a claim about effects outside WorldState's addressable slots.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json

from cognitive_world.core.event import Event
from cognitive_world.core.persistence import PersistedValueCodec, PersistenceTrust, sha256_hex
from cognitive_world.observation.observable import (
    EventProcessingEvidence, ObservableFactDraft, _issue_processing_evidence,
)


EVENT_ATTESTATION_PURPOSE = "cognitive-world/event-processing/v2"
EVENT_RECORD_VERSION = 2


def _b64(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def _unb64(value: object) -> bytes:
    if not isinstance(value, str) or len(value) > 96 * 1024 * 1024:
        raise ValueError("invalid persisted base64 field")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error):
        raise ValueError("invalid persisted base64 field") from None


@dataclass(frozen=True)
class PersistedEventRecord:
    version: int
    event_payload: bytes
    processing_evidence_payload: bytes
    attestation_payload: bytes
    signature: bytes

    def to_json_record(self) -> dict[str, object]:
        return {
            "version": self.version,
            "event": _b64(self.event_payload),
            "processing_evidence": _b64(self.processing_evidence_payload),
            "attestation": _b64(self.attestation_payload),
            "signature": _b64(self.signature),
        }

    @classmethod
    def from_json_record(cls, value: object) -> "PersistedEventRecord":
        if not isinstance(value, dict) or set(value) != {
            "version", "event", "processing_evidence", "attestation", "signature"
        } or value["version"] != EVENT_RECORD_VERSION:
            raise ValueError("unsupported or malformed persisted Event record")
        return cls(
            EVENT_RECORD_VERSION, _unb64(value["event"]),
            _unb64(value["processing_evidence"]), _unb64(value["attestation"]),
            _unb64(value["signature"]),
        )


def make_persisted_event_record(
    event: Event,
    evidence: EventProcessingEvidence,
    *,
    update_digest: str,
    changed_slots: tuple[dict[str, object], ...],
    previous_record_digest: str | None,
    timeline_id: str,
    codec: PersistedValueCodec,
    trust: PersistenceTrust,
) -> PersistedEventRecord:
    if not isinstance(timeline_id, str) or not timeline_id:
        raise ValueError("timeline-aware Event credentials require a Timeline ID")
    event_payload = codec.dumps(event)
    evidence_payload = codec.dumps(evidence)
    attestation = {
        "version": EVENT_RECORD_VERSION,
        "timeline_id": timeline_id,
        "event_id": event.id,
        "event_source": event._source_receipt.source,
        "event_sha256": sha256_hex(event_payload),
        "processing_evidence_sha256": sha256_hex(evidence_payload),
        "update_sha256": update_digest,
        "simulation_tick": event.simulation_tick,
        "changed_slots": changed_slots,
        "previous_record_sha256": previous_record_digest,
        "world_update_applied": True,
    }
    payload = json.dumps(attestation, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    signature = trust.sign(EVENT_ATTESTATION_PURPOSE, payload)
    if not isinstance(signature, bytes) or not signature:
        raise TypeError("persistence trust authority returned an invalid signature")
    return PersistedEventRecord(EVENT_RECORD_VERSION, event_payload, evidence_payload,
                                payload, signature)


def verify_and_restore_event_records(
    records: tuple[PersistedEventRecord, ...], *, codec: PersistedValueCodec,
    trust: PersistenceTrust, expected_timeline_id: str | None = None,
    initial_previous_digest: str | None = None,
) -> tuple[tuple[Event, ...], tuple[EventProcessingEvidence, ...], tuple[dict[str, object], ...]]:
    """Verify chain/signatures before issuing new process-local receipts."""
    events: list[Event] = []
    evidences: list[EventProcessingEvidence] = []
    attestations: list[dict[str, object]] = []
    previous_digest = initial_previous_digest
    seen_ids: set[str] = set()
    for record in records:
        if record.version != EVENT_RECORD_VERSION or not trust.verify(
            EVENT_ATTESTATION_PURPOSE, record.attestation_payload, record.signature
        ):
            raise PermissionError("Event processing attestation is missing or invalid")
        try:
            attestation = json.loads(record.attestation_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("malformed Event processing attestation") from None
        required = {
            "version", "timeline_id", "event_id", "event_source", "event_sha256",
            "processing_evidence_sha256", "update_sha256", "simulation_tick",
            "changed_slots", "previous_record_sha256", "world_update_applied",
        }
        if (not isinstance(attestation, dict) or set(attestation) != required
                or attestation["version"] != EVENT_RECORD_VERSION
                or attestation["previous_record_sha256"] != previous_digest
                or not isinstance(attestation["timeline_id"], str)
                or not attestation["timeline_id"]
                or (expected_timeline_id is not None
                    and attestation["timeline_id"] != expected_timeline_id)
                or attestation["world_update_applied"] is not True
                or attestation["event_source"] not in {"resolution", "system"}
                or not isinstance(attestation["changed_slots"], list)):
            raise ValueError("Event attestation chain or schema is invalid")
        if (sha256_hex(record.event_payload) != attestation["event_sha256"]
                or sha256_hex(record.processing_evidence_payload) != attestation["processing_evidence_sha256"]):
            raise PermissionError("persisted Event or processing evidence was changed")
        event = codec.loads(record.event_payload)
        evidence_untrusted = codec.loads(record.processing_evidence_payload)
        if (not isinstance(event, Event) or not isinstance(evidence_untrusted, EventProcessingEvidence)
                or event.id != attestation["event_id"] or event.id in seen_ids
                or event.simulation_tick != attestation["simulation_tick"]):
            raise ValueError("persisted Event identity/order is invalid")
        # The durable signature authenticates the historical processor result.
        # Only after that verification may the process-local source seal be rebuilt.
        event._issue_source_receipt(attestation["event_source"])
        from cognitive_world.core.physical import PossessionTransition
        if any(isinstance(change, dict) and (
                change.get("effect_type") == "item_take_v1"
                or type(change.get("transition")) is PossessionTransition)
                for change in event.changes):
            # Authenticate first, then check this new closed historical effect.
            # Never re-evaluate old eligibility against the restored world.
            from cognitive_world.items.take import validate_event
            validate_event(event)
        if "take_adjudication_context" in event.metadata:
            from cognitive_world.items.take import validate_adjudication_event
            validate_adjudication_event(event)
        for effect in event.changes[1:]:
            if type(effect) is dict and effect.get("effect_type") in ("life_transition_v1", "life_transition_v2"):
                from cognitive_world.resolution.life import validate_effect
                if len(event.changes) != 2:
                    raise PermissionError("historical life effect has additional effects")
                try:
                    snapshot = effect["authorization"]["body"]["attempt"]
                    validate_effect(effect, snapshot, event.simulation_tick)
                    from cognitive_world.resolution.life import verify_bound_recipients
                    verify_bound_recipients(effect, trust, event_id=event.id)
                    if (snapshot[0] != event.cause
                            or event.changes[0] != {"success": True, "outcome": "life state changed"}):
                        raise PermissionError("historical life result binding mismatch")
                except (KeyError, TypeError, IndexError, ValueError) as exc:
                    raise PermissionError("invalid historical life binding") from exc
        if event.dialogue_payload is not None:
            from cognitive_world.core.attributed_claim import validate_claim_for_event
            validate_claim_for_event(event.dialogue_payload.claim, event=event)
        if "confirmed_attempt_failure" in event.metadata:
            from cognitive_world.event.attempt_source import verify_confirmed_failure_event

            if not event.has_trusted_source("resolution") or not verify_confirmed_failure_event(event):
                raise PermissionError("persisted confirmed-failure Attempt source is inconsistent")
        drafts = tuple(ObservableFactDraft(
            fact_type=f.fact_type, predicate=f.predicate, value=f.value,
            subject_ref=f.subject_ref, location_id=f.location_id,
        ) for f in evidence_untrusted.observable_facts)
        context = evidence_untrusted.event_time_context
        evidence = _issue_processing_evidence(
            event, drafts, simulation_time=context.simulation_time,
            observer_positions=context.observer_positions,
            # Preserve signed historical metadata; never relabel legacy evidence.
            observer_state_phase=context.observer_state_phase,
            environment_conditions=context.environment_conditions,
            environment_snapshot_complete=context.environment_snapshot_complete,
        )
        if codec.dumps(evidence) != record.processing_evidence_payload:
            raise PermissionError("processing evidence could not be reconstructed exactly")
        events.append(event)
        evidences.append(evidence)
        attestations.append(attestation)
        seen_ids.add(event.id)
        previous_digest = sha256_hex(record.attestation_payload)
    return tuple(events), tuple(evidences), tuple(attestations)
