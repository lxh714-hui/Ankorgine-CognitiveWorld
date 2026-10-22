"""Append-only container for confirmed events."""

from copy import deepcopy
import base64
from dataclasses import dataclass, field
from enum import Enum
import json
from threading import RLock

from cognitive_world.core.event import Event
from cognitive_world.observation.observable import EventProcessingEvidence
from cognitive_world.event.persistence import PersistedEventRecord, verify_and_restore_event_records
from cognitive_world.core.persistence import PersistedValueCodec, PersistenceTrust, sha256_hex


class EventProcessingStatus(str, Enum):
    """In-process progress marker for the existing Event processing path."""

    PREPARING = "preparing"
    APPLYING_WORLD_UPDATE = "applying_world_update"
    RECOVERY_REQUIRED = "recovery_required"
    RECORDED = "recorded"
    OBSERVATIONS_PENDING = "observations_pending"
    COMPLETE = "complete"


@dataclass(frozen=True)
class _ProcessingRecord:
    event_snapshot: tuple
    status: EventProcessingStatus
    failure: str | None = None


@dataclass
class EventHistory:
    """Store and retrieve event records without changing the events."""

    _events: list[Event] = field(default_factory=list, repr=False)
    _processing_evidence: dict[str, EventProcessingEvidence] = field(
        default_factory=dict, repr=False
    )
    _processing_records: dict[str, _ProcessingRecord] = field(
        default_factory=dict, repr=False
    )
    _persistence_records: dict[str, PersistedEventRecord] = field(
        default_factory=dict, repr=False
    )
    timeline_id: str | None = None
    fork_manifest_bytes: bytes | None = field(default=None, repr=False)
    fork_checkpoint_manifest_bytes: bytes | None = field(default=None, repr=False)
    _inherited_events: tuple[Event, ...] = field(default=(), repr=False)
    _inherited_evidence: dict[str, EventProcessingEvidence] = field(
        default_factory=dict, repr=False
    )
    _inherited_persistence_records: tuple[PersistedEventRecord, ...] = field(
        default=(), repr=False
    )
    _parent_history: "EventHistory | None" = field(default=None, repr=False, compare=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False, compare=False)

    def begin_processing(self, event: Event) -> bool:
        """Reserve an Event ID before handler/world work; return False if recorded.

        This is an in-memory recovery marker, not a durable transaction log.
        """
        if not isinstance(event, Event):
            raise TypeError("event must be an Event")
        with self._lock:
            if self._requires_recovery_locked():
                raise RuntimeError("EventHistory is inconsistent; explicit recovery is required")
            existing = self._processing_records.get(event.id)
            if existing is not None:
                if existing.event_snapshot != event._source_snapshot():
                    raise ValueError("Event ID already belongs to different content")
                if existing.status in {
                    EventProcessingStatus.RECORDED,
                    EventProcessingStatus.OBSERVATIONS_PENDING,
                    EventProcessingStatus.COMPLETE,
                }:
                    return False
                raise RuntimeError(
                    f"Event {event.id} is {existing.status.value}; explicit recovery is required"
                )
            if any(record.id == event.id for record in self._inherited_events) or any(
                record.id == event.id for record in self._events
            ):
                raise RuntimeError(
                    f"Event {event.id} is already in EventHistory without a processing receipt"
                )
            self._processing_records[event.id] = _ProcessingRecord(
                event._source_snapshot(), EventProcessingStatus.PREPARING
            )
            return True

    def requires_recovery(self) -> bool:
        """Whether a non-replayable Event failure blocks this history's timeline."""
        with self._lock:
            return self._requires_recovery_locked()

    def _requires_recovery_locked(self) -> bool:
        return any(
            record.status is EventProcessingStatus.RECOVERY_REQUIRED
            for record in self._processing_records.values()
        )

    def mark_applying_world_update(self, event_id: str) -> None:
        self._set_processing_status(
            event_id, EventProcessingStatus.APPLYING_WORLD_UPDATE
        )

    def mark_recovery_required(self, event_id: str, failure: str) -> None:
        self._set_processing_status(
            event_id, EventProcessingStatus.RECOVERY_REQUIRED, failure=failure
        )

    def abandon_prepared_processing(self, event_id: str) -> None:
        """Release only a reservation known to precede WorldState mutation."""
        with self._lock:
            record = self._processing_records.get(event_id)
            if record is not None and record.status is EventProcessingStatus.PREPARING:
                del self._processing_records[event_id]

    def mark_observations_pending(self, event_id: str) -> None:
        self._set_processing_status(
            event_id, EventProcessingStatus.OBSERVATIONS_PENDING
        )

    def mark_observations_complete(self, event_id: str) -> None:
        self._set_processing_status(event_id, EventProcessingStatus.COMPLETE)

    def get_processing_status(self, event_id: str) -> EventProcessingStatus | None:
        with self._lock:
            record = self._processing_records.get(event_id)
            return None if record is None else record.status

    def _set_processing_status(
        self,
        event_id: str,
        status: EventProcessingStatus,
        *,
        failure: str | None = None,
    ) -> None:
        with self._lock:
            record = self._processing_records.get(event_id)
            if record is None:
                raise KeyError(f"no processing reservation for Event {event_id}")
            self._processing_records[event_id] = _ProcessingRecord(
                record.event_snapshot, status, failure
            )

    def append(
        self,
        event: Event,
        *,
        processing_evidence: EventProcessingEvidence | None = None,
        persistence_record: PersistedEventRecord | None = None,
    ) -> None:
        """Append an event and optionally retain its isolated processor evidence.

        This remains a storage operation; consumers must validate evidence
        provenance independently of EventHistory membership.
        """
        if not isinstance(event, Event):
            raise TypeError("event must be an Event")
        if processing_evidence is not None:
            if not isinstance(processing_evidence, EventProcessingEvidence):
                raise TypeError("processing_evidence must be EventProcessingEvidence")
            if processing_evidence.source_event_id != event.id:
                raise ValueError(
                    "processing evidence must reference the appended Event"
                )
        if persistence_record is not None and (
            not isinstance(persistence_record, PersistedEventRecord)
            or persistence_record.version != 2
        ):
            raise TypeError("persistence_record must be a versioned PersistedEventRecord")
        if persistence_record is not None:
            if not isinstance(self.timeline_id, str) or not self.timeline_id:
                raise PermissionError("persisted Event append requires a Timeline-bound history")
            try:
                attestation = json.loads(persistence_record.attestation_payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ValueError("malformed Event processing attestation") from None
            if attestation.get("timeline_id") != self.timeline_id:
                raise PermissionError("Event credential belongs to a different Timeline")
        with self._lock:
            record = self._processing_records.get(event.id)
            if (
                record is not None
                and record.status is not EventProcessingStatus.APPLYING_WORLD_UPDATE
            ):
                raise RuntimeError(
                    "Event is not at the WorldState-applied History boundary"
                )
            if any(item.id == event.id for item in self._inherited_events) or any(
                item.id == event.id for item in self._events
            ):
                raise ValueError("Event ID is already present in this timeline ancestry")
            self._events.append(deepcopy(event))
            if processing_evidence is not None:
                self._processing_evidence[event.id] = deepcopy(processing_evidence)
                if record is not None:
                    self._processing_records[event.id] = _ProcessingRecord(
                        record.event_snapshot, EventProcessingStatus.RECORDED
                    )
            if persistence_record is not None:
                self._persistence_records[event.id] = deepcopy(persistence_record)

    def get_processing_evidence(self, event_id: str) -> EventProcessingEvidence | None:
        """Return an isolated processor-evidence record, if stored."""
        with self._lock:
            evidence = self._processing_evidence.get(event_id)
            if evidence is None:
                evidence = self._inherited_evidence.get(event_id)
            return deepcopy(evidence) if evidence is not None else None

    def get_events(self) -> tuple[Event, ...]:
        """Return isolated copies of all recorded events in order."""
        with self._lock:
            return tuple(deepcopy(self._inherited_events + tuple(self._events)))

    def get_event(self, event_id: str) -> Event | None:
        """Return an isolated copy of a recorded event by identifier."""
        with self._lock:
            for event in self._events:
                if event.id == event_id:
                    return deepcopy(event)
            for event in self._inherited_events:
                if event.id == event_id:
                    return deepcopy(event)
        return None


    def get_persistence_record(self, event_id: str) -> PersistedEventRecord | None:
        with self._lock:
            value = self._persistence_records.get(event_id)
            if value is None:
                value = next((record for event, record in zip(
                    self._inherited_events, self._inherited_persistence_records, strict=True
                ) if event.id == event_id), None)
            return deepcopy(value) if value is not None else None

    def last_persistence_record_digest(self) -> str | None:
        with self._lock:
            if self._events:
                record = self._persistence_records.get(self._events[-1].id)
            elif self._inherited_persistence_records:
                record = self._inherited_persistence_records[-1]
            else:
                return None
            return None if record is None else sha256_hex(record.attestation_payload)

    def export_persisted_records(self) -> tuple[PersistedEventRecord, ...]:
        """Return a complete ordered signed history or fail closed for legacy Events."""
        with self._lock:
            records = [deepcopy(record) for record in self._inherited_persistence_records]
            for event in self._events:
                record = self._persistence_records.get(event.id)
                evidence = self._processing_evidence.get(event.id)
                processing = self._processing_records.get(event.id)
                if (record is None or evidence is None or processing is None
                        or processing.status not in {
                            EventProcessingStatus.RECORDED,
                            EventProcessingStatus.OBSERVATIONS_PENDING,
                            EventProcessingStatus.COMPLETE,
                        }):
                    raise PermissionError(
                        f"EventHistory is not durably attestable at Event {event.id}"
                    )
                records.append(deepcopy(record))
            if set(self._processing_records) - {event.id for event in self._events}:
                raise PermissionError("EventHistory contains an incomplete processing operation")
            return tuple(records)

    def export_local_persisted_records(self) -> tuple[PersistedEventRecord, ...]:
        """Export the local suffix only; immutable ancestor records are referenced."""
        with self._lock:
            records = []
            for event in self._events:
                record = self._persistence_records.get(event.id)
                evidence = self._processing_evidence.get(event.id)
                processing = self._processing_records.get(event.id)
                if (record is None or evidence is None or processing is None
                        or processing.status not in {
                            EventProcessingStatus.RECORDED,
                            EventProcessingStatus.OBSERVATIONS_PENDING,
                            EventProcessingStatus.COMPLETE,
                        }):
                    raise PermissionError(
                        f"EventHistory local suffix is not durably attestable at Event {event.id}"
                    )
                records.append(deepcopy(record))
            if set(self._processing_records) - {event.id for event in self._events}:
                raise PermissionError("EventHistory contains an incomplete processing operation")
            return tuple(records)

    @classmethod
    def fork_from_checkpoint(
        cls, parent: "EventHistory", *, fork_manifest: object,
        checkpoint_manifest: object, verified_bundle: object,
        trust: PersistenceTrust, codec: PersistedValueCodec | None = None,
    ) -> "EventHistory":
        """Create a child that retains an immutable view of the verified parent prefix."""
        from cognitive_world.core.snapshot_bundle import SnapshotBundleManifest
        from cognitive_world.core.timeline import TimelineForkManifest

        if type(parent) is not cls or not isinstance(parent.timeline_id, str) or not parent.timeline_id:
            raise TypeError("fork parent must have an explicit Timeline ID")
        if type(fork_manifest) is not TimelineForkManifest or type(
            checkpoint_manifest
        ) is not SnapshotBundleManifest:
            raise TypeError("fork requires timeline and checkpoint manifests")
        fork_manifest.verify_against_checkpoint(
            checkpoint_manifest, verified_bundle=verified_bundle, trust=trust,
        )
        if fork_manifest.parent_timeline_id != parent.timeline_id:
            raise PermissionError("fork parent Timeline does not match EventHistory")
        records = parent.export_persisted_records()
        parent.verify_persisted_lineage(codec=codec or PersistedValueCodec(), trust=trust)
        if parent.last_persistence_record_digest() != fork_manifest.inherited_event_chain_head_sha256:
            raise PermissionError("fork checkpoint does not match the parent EventHistory head")
        result = cls(timeline_id=fork_manifest.timeline_id)
        result.fork_manifest_bytes = fork_manifest.to_bytes()
        result.fork_checkpoint_manifest_bytes = checkpoint_manifest.to_bytes()
        # Snapshot immutable, authenticated records and isolated Events at fork
        # time. Later parent appends update only the parent's local lists.
        result._inherited_events = parent.get_events()
        result._inherited_evidence = {
            event.id: evidence
            for event in result._inherited_events
            if (evidence := parent.get_processing_evidence(event.id)) is not None
        }
        result._inherited_persistence_records = tuple(deepcopy(records))
        result._parent_history = parent._immutable_snapshot_copy()
        return result

    def _immutable_snapshot_copy(self) -> "EventHistory":
        """Copy this prefix and its ancestry as it existed at a fork boundary."""
        with self._lock:
            result = EventHistory(
                timeline_id=self.timeline_id,
                fork_manifest_bytes=self.fork_manifest_bytes,
                fork_checkpoint_manifest_bytes=self.fork_checkpoint_manifest_bytes,
                _inherited_events=deepcopy(self._inherited_events),
                _inherited_evidence=deepcopy(self._inherited_evidence),
                _inherited_persistence_records=deepcopy(self._inherited_persistence_records),
            )
            result._events = deepcopy(self._events)
            result._processing_evidence = deepcopy(self._processing_evidence)
            result._processing_records = deepcopy(self._processing_records)
            result._persistence_records = deepcopy(self._persistence_records)
            if self._parent_history is not None:
                result._parent_history = self._parent_history._immutable_snapshot_copy()
            return result

    def verify_persisted_lineage(
        self, *, codec: PersistedValueCodec, trust: PersistenceTrust,
        parent_history_resolver: object | None = None,
    ) -> tuple[tuple[Event, ...], tuple[EventProcessingEvidence, ...], tuple[dict[str, object], ...]]:
        """Verify each timeline-local chain and its signed immutable fork boundary."""
        local_records = self.export_local_persisted_records()
        if self.fork_manifest_bytes is None:
            if self.fork_checkpoint_manifest_bytes is not None:
                raise PermissionError("root EventHistory cannot name a fork checkpoint")
            return verify_and_restore_event_records(
                local_records, codec=codec, trust=trust,
                expected_timeline_id=self.timeline_id,
            )
        from cognitive_world.core.snapshot_bundle import SnapshotBundleManifest
        from cognitive_world.core.timeline import TimelineForkManifest

        if self.fork_checkpoint_manifest_bytes is None:
            raise PermissionError("branch EventHistory is missing its checkpoint manifest")
        fork = TimelineForkManifest.from_bytes(self.fork_manifest_bytes)
        checkpoint = SnapshotBundleManifest.from_bytes(self.fork_checkpoint_manifest_bytes)
        parent = self._parent_history
        if parent is None and callable(parent_history_resolver):
            parent = parent_history_resolver(fork.fork_checkpoint_id)
        if type(parent) is not type(self) or parent.timeline_id != fork.parent_timeline_id:
            raise PermissionError("branch EventHistory requires its verified parent history")
        parent_events, parent_evidence, parent_attestations = parent.verify_persisted_lineage(
            codec=codec, trust=trust, parent_history_resolver=parent_history_resolver,
        )
        parent_head = parent.last_persistence_record_digest()
        fork.verify_event_history_parent(
            checkpoint, parent_timeline_id=parent.timeline_id,
            parent_chain_head_sha256=parent_head, trust=trust,
        )
        local_events, local_evidence, local_attestations = verify_and_restore_event_records(
            local_records, codec=codec, trust=trust,
            expected_timeline_id=self.timeline_id,
            initial_previous_digest=parent_head,
        )
        inherited_ids = {event.id for event in parent_events}
        if inherited_ids.intersection(event.id for event in local_events):
            raise ValueError("branch suffix repeats an inherited Event ID")
        return (parent_events + local_events, parent_evidence + local_evidence,
                parent_attestations + local_attestations)

    def export_persisted_state(self, *, timeline_id: str | None = None) -> dict[str, object]:
        """Export a versioned lineage descriptor and this Timeline's local suffix."""
        records = self.export_local_persisted_records()
        resolved_timeline = self.timeline_id
        if resolved_timeline is None and not self._events and not self._inherited_events:
            resolved_timeline = timeline_id
        if (not isinstance(resolved_timeline, str) or not resolved_timeline
                or (timeline_id is not None and resolved_timeline != timeline_id)):
            raise PermissionError("persistent EventHistory requires a Timeline ID")
        return {
            "version": 1,
            "timeline_id": resolved_timeline,
            "fork_manifest": (None if self.fork_manifest_bytes is None else
                              base64.b64encode(self.fork_manifest_bytes).decode("ascii")),
            "fork_checkpoint_manifest": (
                None if self.fork_checkpoint_manifest_bytes is None else
                base64.b64encode(self.fork_checkpoint_manifest_bytes).decode("ascii")
            ),
            "local_records": [record.to_json_record() for record in records],
        }

    @classmethod
    def from_persisted_state(
        cls, state: object, *, codec: PersistedValueCodec, trust: PersistenceTrust,
        parent_history_resolver: object | None = None,
    ) -> "EventHistory":
        """Restore a root or branch suffix; branches require a verified parent resolver."""
        from cognitive_world.core.snapshot_bundle import SnapshotBundleManifest
        from cognitive_world.core.timeline import TimelineForkManifest
        from cognitive_world.event.persistence import PersistedEventRecord

        required = {"version", "timeline_id", "fork_manifest",
                    "fork_checkpoint_manifest", "local_records"}
        if (not isinstance(state, dict) or set(state) != required or state["version"] != 1
                or not isinstance(state["timeline_id"], str) or not state["timeline_id"]
                or not isinstance(state["local_records"], list)):
            raise ValueError("malformed persisted EventHistory state")
        records = tuple(PersistedEventRecord.from_json_record(item)
                        for item in state["local_records"])
        if state["fork_manifest"] is None:
            if state["fork_checkpoint_manifest"] is not None:
                raise ValueError("root EventHistory cannot name a fork checkpoint")
            return cls.from_persisted_records(
                records, codec=codec, trust=trust, timeline_id=state["timeline_id"],
            )
        if (not isinstance(state["fork_manifest"], str)
                or not isinstance(state["fork_checkpoint_manifest"], str)
                or not callable(parent_history_resolver)):
            raise PermissionError("branch EventHistory requires its checkpoint and parent resolver")
        fork_bytes = base64.b64decode(state["fork_manifest"], validate=True)
        checkpoint_bytes = base64.b64decode(state["fork_checkpoint_manifest"], validate=True)
        fork = TimelineForkManifest.from_bytes(fork_bytes)
        checkpoint = SnapshotBundleManifest.from_bytes(checkpoint_bytes)
        if fork.timeline_id != state["timeline_id"]:
            raise PermissionError("branch Timeline ID does not match its signed fork manifest")
        parent = parent_history_resolver(fork.fork_checkpoint_id)
        if type(parent) is not cls or parent.timeline_id != fork.parent_timeline_id:
            raise PermissionError("fork parent EventHistory is missing or belongs to another Timeline")
        parent_records = parent.export_persisted_records()
        parent.verify_persisted_lineage(
            codec=codec, trust=trust, parent_history_resolver=parent_history_resolver,
        )
        parent_head = parent.last_persistence_record_digest()
        fork.verify_event_history_parent(
            checkpoint, parent_timeline_id=parent.timeline_id,
            parent_chain_head_sha256=parent_head, trust=trust,
        )
        events, evidences, _ = verify_and_restore_event_records(
            records, codec=codec, trust=trust,
            expected_timeline_id=state["timeline_id"],
            initial_previous_digest=parent_head,
        )
        if {event.id for event in events} & {event.id for event in parent.get_events()}:
            raise ValueError("branch suffix repeats an inherited Event ID")
        result = cls.fork_from_checkpoint_metadata(
            parent, timeline_id=state["timeline_id"], fork_bytes=fork_bytes,
            checkpoint_bytes=checkpoint_bytes, parent_records=parent_records,
        )
        result._events = [deepcopy(event) for event in events]
        result._processing_evidence.update({
            event.id: deepcopy(evidence)
            for event, evidence in zip(events, evidences, strict=True)
        })
        result._processing_records = {
            event.id: _ProcessingRecord(event._source_snapshot(), EventProcessingStatus.RECORDED)
            for event in events
        }
        result._persistence_records = {
            event.id: deepcopy(record) for event, record in zip(events, records, strict=True)
        }
        return result

    @classmethod
    def fork_from_checkpoint_metadata(
        cls, parent: "EventHistory", *, timeline_id: str, fork_bytes: bytes,
        checkpoint_bytes: bytes, parent_records: tuple[PersistedEventRecord, ...],
    ) -> "EventHistory":
        result = cls(timeline_id=timeline_id)
        result.fork_manifest_bytes = fork_bytes
        result.fork_checkpoint_manifest_bytes = checkpoint_bytes
        result._inherited_events = parent.get_events()
        result._inherited_evidence = {
            event.id: evidence for event in result._inherited_events
            if (evidence := parent.get_processing_evidence(event.id)) is not None
        }
        result._inherited_persistence_records = tuple(deepcopy(parent_records))
        result._parent_history = parent._immutable_snapshot_copy()
        return result

    @classmethod
    def from_persisted_records(
        cls,
        records: tuple[PersistedEventRecord, ...],
        *,
        codec: PersistedValueCodec,
        trust: PersistenceTrust,
        timeline_id: str | None = None,
    ) -> "EventHistory":
        """Build an isolated history only after every signed record validates."""
        events, evidences, attestations = verify_and_restore_event_records(
            records, codec=codec, trust=trust, expected_timeline_id=timeline_id,
        )
        resolved_timeline = timeline_id
        if records:
            timeline_ids = {item["timeline_id"] for item in attestations}
            if len(timeline_ids) != 1:
                raise ValueError("root EventHistory cannot contain multiple Timeline owners")
            inferred = next(iter(timeline_ids))
            if resolved_timeline is not None and inferred != resolved_timeline:
                raise PermissionError("Event credential Timeline does not match restored history")
            resolved_timeline = inferred
        result = cls(timeline_id=resolved_timeline)
        result._events = [deepcopy(event) for event in events]
        result._processing_evidence = {
            event.id: deepcopy(evidence)
            for event, evidence in zip(events, evidences, strict=True)
        }
        result._processing_records = {
            event.id: _ProcessingRecord(
                event._source_snapshot(), EventProcessingStatus.RECORDED
            ) for event in events
        }
        result._persistence_records = {
            event.id: deepcopy(record)
            for event, record in zip(events, records, strict=True)
        }
        return result
