"""Dispatch events to registered handlers and forward update requests."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from contextlib import contextmanager, nullcontext
from typing import Protocol

from cognitive_world.core.causal_graph import CausalGraph
from cognitive_world.core.event import Event
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldState
from cognitive_world.core.persistence import PersistedValueCodec, PersistenceTrust, sha256_hex
from cognitive_world.core._world_write import processor_write_scope
from cognitive_world.core.door import DoorState
from cognitive_world.core.passage import PassageState
from cognitive_world.event.causality import EventCausality
from cognitive_world.event.handler import EventHandler
from cognitive_world.event.environment import (
    EnvironmentStateObservedHandler,
    ResolutionEffectsHandler,
    WorldNormsUpdatedHandler,
)
from cognitive_world.event.history import EventHistory
from cognitive_world.event.persistence import make_persisted_event_record
from cognitive_world.observation.observable import (
    EventProcessingEvidence,
    FactValue,
    ObservableFactDraft,
    _issue_processing_evidence,
)
from cognitive_world.runtime.write_fence import RuntimeWriteFence


class _ScheduledEvent(Protocol):
    """Structural contract for a runtime-scheduled Event record."""

    event: Event


@dataclass
class EventProcessor:
    """Routes events to handlers without applying changes directly."""

    _handlers: dict[str, EventHandler] = field(default_factory=dict, repr=False)
    causal_graph: CausalGraph | None = None
    event_history: EventHistory | None = field(default_factory=EventHistory)
    world_state: WorldState | None = None
    simulation_clock: object | None = None
    agent_registry: object | None = None
    observation_store: object | None = None
    persistence_trust: PersistenceTrust | None = None
    persistence_codec: PersistedValueCodec | None = None
    write_fence: RuntimeWriteFence | None = None

    def __post_init__(self) -> None:
        # Keep legacy construction usable while ensuring this processor always
        # has the same EventHistory-based replay guard used by Runtime callers.
        if self.event_history is None:
            self.event_history = EventHistory()
        if self.persistence_trust is not None:
            if not callable(getattr(self.persistence_trust, "sign", None)) or not callable(
                getattr(self.persistence_trust, "verify", None)
            ):
                raise TypeError("persistence_trust must expose sign and verify")
            if self.persistence_codec is None:
                self.persistence_codec = PersistedValueCodec()
        if self.persistence_codec is not None and not isinstance(
            self.persistence_codec, PersistedValueCodec
        ):
            raise TypeError("persistence_codec must be PersistedValueCodec")
        self._handlers.setdefault("resolution", ResolutionEffectsHandler())
        self._handlers.setdefault("world_norms_updated", WorldNormsUpdatedHandler())
        self._handlers.setdefault(
            "environment_state_observed", EnvironmentStateObservedHandler()
        )

    def register_handler(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for an event type."""
        self._handlers[event_type] = handler

    @contextmanager
    def _write_scope(self, event: Event):
        """Fence Runtime-originated work, while retaining host-side Event dispatch."""
        if self.write_fence is None:
            with nullcontext():
                yield None
            return
        if RuntimeWriteFence.current_permit() is None:
            if event._runtime_write_permit is not None:
                # A Runtime-originated late Event cannot mint a replacement
                # permit after its original operation has ended.
                with self.write_fence.commit_scope():
                    yield None
                return
            # Explicit synchronous host/scheduler submission starts a fresh
            # operation. Bind it once so a later replay cannot acquire a new
            # generation merely by calling dispatch again.
            with self.write_fence.operation() as permit:
                event._runtime_write_permit = permit
                with self.write_fence.commit_scope():
                    yield permit
            return
        with self.write_fence.commit_scope() as permit:
            if event._runtime_write_permit is None:
                event._runtime_write_permit = permit
            else:
                self.write_fence.require_candidate_origin(event._runtime_write_permit)
            yield permit

    def process(
        self,
        event: Event,
        world_state: WorldState,
        cause_id: str | None = None,
    ) -> None:
        """Apply a handled event while preserving the legacy None return."""
        self.process_with_evidence(event, world_state, cause_id)

    def process_with_evidence(
        self,
        event: Event,
        world_state: WorldState,
        cause_id: str | None = None,
    ) -> EventProcessingEvidence:
        scope = self._write_scope(event)
        with scope:
            return self._process_with_evidence(event, world_state, cause_id)

    def _process_with_evidence(
        self,
        event: Event,
        world_state: WorldState,
        cause_id: str | None = None,
    ) -> EventProcessingEvidence:
        """Process an Event and return its typed, processor-issued evidence."""
        if not isinstance(event, Event) or not event.has_trusted_source():
            raise ValueError(
                "EventProcessor requires an intact Event from a controlled source"
            )
        if cause_id is not None and self.causal_graph is None:
            raise ValueError("A CausalGraph is required when cause_id is provided")
        if event.type == "world_norms_updated":
            clock_tick = getattr(self.simulation_clock, "current_time", None)
            if (
                isinstance(clock_tick, bool)
                or not isinstance(clock_tick, int)
                or event.simulation_tick != clock_tick
            ):
                raise PermissionError("WorldNorms version changes require the current trusted simulation tick")

        history = self.event_history
        if history is None:  # Defensive for callers mutating the public field.
            raise RuntimeError("EventHistory is required for guarded event processing")
        if (self.persistence_trust is not None and history.get_events()
                and history.last_persistence_record_digest() is None):
            raise PermissionError(
                "cannot extend an EventHistory without a complete signed persistence chain"
            )
        if self.persistence_trust is not None and not history.timeline_id:
            raise PermissionError(
                "persistent Event processing requires an explicitly bound Timeline ID"
            )
        is_new = history.begin_processing(event)
        if not is_new:
            evidence = history.get_processing_evidence(event.id)
            if evidence is None or not evidence.has_trusted_source(event):
                raise RuntimeError(
                    f"Event {event.id} was already processed but has no reusable evidence"
                )
            return evidence

        # Close the initialization-only loaders before invoking any handler.
        # Otherwise a buggy handler could mutate WorldState through load_* even
        # though apply_event itself is capability-gated.
        seal_initialization = getattr(world_state, "_seal_initialization", None)
        if callable(seal_initialization):
            seal_initialization()

        try:
            try:
                handler = self._handlers[event.type]
            except KeyError:
                raise LookupError(
                    f"No handler registered for event type: {event.type}"
                ) from None

            update_request = handler.handle_with_world_state(event, world_state)
            if not isinstance(update_request, WorldUpdate):
                raise TypeError("EventHandler.handle must return a WorldUpdate")

            fact_drafts = handler.observable_facts(event, update_request)
            if not isinstance(fact_drafts, tuple) or any(
                not isinstance(draft, ObservableFactDraft) for draft in fact_drafts
            ):
                raise TypeError(
                    "EventHandler.observable_facts must return a tuple of "
                    "ObservableFactDraft records"
                )
            if not event.has_trusted_source():
                raise ValueError("Event was mutated during controlled processing")
            self._validate_physical_slot_reads(event, world_state, history)
            self._validate_confirmed_failure_source(event, world_state, history)
        except Exception:
            history.abandon_prepared_processing(event.id)
            raise

        # From this point onward replay is forbidden: apply_event and later
        # in-memory writes do not offer rollback or durable atomicity.
        history.mark_applying_world_update(event.id)
        try:
            with processor_write_scope(world_state, event, update_request):
                world_state.apply_event(event, update_request)
            # The context contract is AFTER_WORLD_UPDATE. Capture observer
            # positions immediately at this event boundary, never later from
            # an unrelated runtime tick.
            observer_positions = self._capture_observers(world_state)
            conditions: list[tuple[str, FactValue]] = []
            environment = getattr(world_state, "environment", None)
            environment_snapshot_complete = (
                getattr(world_state, "environment_snapshot_complete", False) is True
            )
            for draft in fact_drafts:
                if not isinstance(environment, Mapping):
                    break
                if draft.predicate == "room_light_on" and draft.location_id:
                    room_state = environment.get(draft.location_id)
                    if isinstance(room_state, dict) and type(room_state.get("light_on")) is bool:
                        conditions.append((f"{draft.location_id}:light_on", room_state["light_on"]))
                elif draft.predicate == "door_open" and draft.subject_ref:
                    door = environment.get(draft.subject_ref)
                    if isinstance(door, DoorState):
                        conditions.append((f"door:{draft.subject_ref}:open", door.is_open))
                elif draft.predicate == "door_locked" and draft.subject_ref:
                    door = environment.get(draft.subject_ref)
                    if isinstance(door, DoorState):
                        conditions.append((f"door:{draft.subject_ref}:locked", door.is_locked))
                elif draft.predicate == "passage_destination" and draft.subject_ref:
                    passage = environment.get(draft.subject_ref)
                    if (
                        isinstance(passage, PassageState)
                        and passage.destination_location_id == draft.value
                    ):
                        conditions.append((
                            f"passage:{draft.subject_ref}:destination",
                            passage.destination_location_id,
                        ))
                elif draft.predicate == "actor_arrived" and draft.subject_ref:
                    if world_state.locations.get(draft.subject_ref) == draft.value:
                        conditions.append((f"location:{draft.subject_ref}", draft.value))
            if conditions:
                environment_conditions: tuple[tuple[str, FactValue], ...] | None = tuple(conditions)
            elif environment_snapshot_complete:
                # Empty is meaningful only when the authoritative state says
                # its environment mapping is a complete snapshot.
                environment_conditions = ()
            else:
                # A missing/unrelated/unsupported value remains unknown.
                environment_conditions = None
            if event.has_trusted_source("resolution"):
                simulation_time = event.simulation_tick
            else:
                simulation_time = getattr(self.simulation_clock, "current_time", None)
            evidence = _issue_processing_evidence(
                event,
                fact_drafts,
                simulation_time=simulation_time,
                observer_positions=observer_positions,
                environment_conditions=environment_conditions,
                environment_snapshot_complete=environment_snapshot_complete,
            )
            if cause_id is not None:
                EventCausality(self.causal_graph).record_cause(
                    event_id=event.id,
                    cause_id=cause_id,
                )
            persistence_record = None
            if self.persistence_trust is not None:
                if self.persistence_codec is None:
                    raise RuntimeError("persistence codec is missing")
                persistence_record = make_persisted_event_record(
                    event, evidence,
                    update_digest=sha256_hex(self.persistence_codec.dumps(update_request)),
                    changed_slots=world_state.changed_slot_records_for_event(event.id),
                    previous_record_digest=history.last_persistence_record_digest(),
                    timeline_id=history.timeline_id,
                    codec=self.persistence_codec,
                    trust=self.persistence_trust,
                )
            if self.persistence_trust is None:
                # Preserve the legacy EventHistory override contract when
                # persistent attestations are not enabled for this runtime.
                history.append(event, processing_evidence=evidence)
            else:
                history.append(
                    event, processing_evidence=evidence,
                    persistence_record=persistence_record,
                )
            return evidence
        except Exception as exc:
            try:
                history.mark_recovery_required(event.id, f"{type(exc).__name__}: {exc}")
            finally:
                # The processor still holds the Runtime's commit lock here.
                # Invalidate its permits before another canonical writer enters.
                if self.write_fence is not None:
                    self.write_fence.mark_recovery_required()
            raise

    @staticmethod
    def _validate_confirmed_failure_source(
        event: Event, world_state: WorldState, history: EventHistory,
    ) -> None:
        if "confirmed_attempt_failure" not in event.metadata:
            return  # legacy failures remain history, but cannot seed feedback
        from cognitive_world.event.attempt_source import verify_confirmed_failure_event

        if not event.has_trusted_source("resolution") or not verify_confirmed_failure_event(event):
            raise PermissionError("confirmed failure has no valid structured Attempt source")
        source = event.metadata["confirmed_attempt_failure"]
        target_refs = source["target_refs"]
        target = target_refs[0]
        reads = source["state_slot_reads"]
        lock_read = any(
            isinstance(item.get("slot"), Mapping)
            and item["slot"].get("collection") == "environment"
            and item["slot"].get("record_id") == target
            and item["slot"].get("path") == ("is_locked",)
            for item in reads
        )
        door_state = world_state.environment.get(target)
        if ("door_locked" not in source["verified_conditions"]
                or not lock_read
                or getattr(door_state, "is_locked", None) is not True
                or any(not world_state.verify_state_slot_record(item, event_history=history)
                       for item in reads)):
            raise PermissionError("confirmed failure conditions are stale or lack authoritative state provenance")

    @staticmethod
    def _validate_physical_slot_reads(
        event: Event, world_state: WorldState, history: EventHistory
    ) -> None:
        """Revalidate physical read values and any cited Event lineage pre-commit."""
        if "physical_effect_provenance" not in event.metadata:
            return
        records = event.metadata.get("physical_effect_provenance")
        if not isinstance(records, (tuple, list)) or not 1 <= len(records) <= 4:
            raise PermissionError("physical effects require bounded provenance records")
        for record in records:
            if not isinstance(record, Mapping):
                raise PermissionError("physical effect provenance must be structured")
            reads = record.get("state_slot_reads")
            if not isinstance(reads, (tuple, list)) or not 1 <= len(reads) <= 32:
                raise PermissionError("physical effect requires bounded state-slot read receipts")
            if any(not world_state.verify_state_slot_record(
                item, event_history=history
            ) for item in reads):
                raise PermissionError(
                    "physical effect state-slot reads are stale or lack authoritative lineage"
                )

    def _capture_observers(
        self, world_state: WorldState
    ) -> tuple[tuple[str, str | None, tuple[str, ...] | None], ...]:
        registry = self.agent_registry
        all_agents = getattr(registry, "all_agents", None)
        if not callable(all_agents):
            return ()
        snapshots = []
        locations = getattr(world_state, "locations", {})
        if not isinstance(locations, Mapping):
            locations = {}
        get_entity = getattr(world_state, "get_entity", None)
        for agent in all_agents():
            observer_id = getattr(agent, "agent_id", None)
            if not isinstance(observer_id, str) or not observer_id:
                continue
            position = locations.get(observer_id)
            if not isinstance(position, str) or not position:
                position = None
            entity = get_entity(observer_id) if callable(get_entity) else None
            senses = getattr(entity, "sensory_capabilities", None)
            if not isinstance(senses, tuple):
                senses = None
            snapshots.append((observer_id, position, senses))
        return tuple(snapshots)

    def dispatch(self, scheduled_event: _ScheduledEvent | Event) -> None:
        """Forward a scheduled or newly generated Event to the process flow."""
        if self.world_state is None:
            raise ValueError("WorldState is required to dispatch a scheduled event")
        event = (
            scheduled_event
            if isinstance(scheduled_event, Event)
            else scheduled_event.event
        )
        self.process(event, self.world_state)

    def dispatch_with_evidence(
        self, scheduled_event: _ScheduledEvent | Event
    ) -> EventProcessingEvidence:
        """Dispatch and, when configured, store policy-authorized observations."""
        event = scheduled_event if isinstance(scheduled_event, Event) else scheduled_event.event
        scope = self._write_scope(event)
        with scope:
            return self._dispatch_with_evidence(scheduled_event)

    def _dispatch_with_evidence(
        self, scheduled_event: _ScheduledEvent | Event
    ) -> EventProcessingEvidence:
        if self.world_state is None:
            raise ValueError("WorldState is required to dispatch a scheduled event")
        event = (
            scheduled_event
            if isinstance(scheduled_event, Event)
            else scheduled_event.event
        )
        evidence = self.process_with_evidence(event, self.world_state)
        if self.observation_store is not None:
            from cognitive_world.observation.generator import ObservationGenerator

            generator = ObservationGenerator()
            history = self.event_history
            if history is None:
                raise RuntimeError("EventHistory is required for Observation delivery")
            history.mark_observations_pending(event.id)
            try:
                for observer_id, _, _ in evidence.event_time_context.observer_positions:
                    for observation in generator.generate_authorized(
                        event, evidence, observer_id=observer_id,
                        source_timeline_id=history.timeline_id,
                        source_runtime_session_id=(
                            None if self.write_fence is None
                            else self.write_fence.session_id
                        ),
                        source_runtime_generation=(
                            None if self.write_fence is None
                            else self.write_fence.restore_generation
                        ),
                    ):
                        self.observation_store.add(observation)
                history.mark_observations_complete(event.id)
            except Exception as exc:
                # Keep the evidence and retry delivery only; process_with_evidence
                # will return the recorded evidence without reapplying WorldState.
                raise RuntimeError(
                    f"Observation delivery failed for Event {event.id}; retry dispatch to resume"
                ) from exc
        return evidence
