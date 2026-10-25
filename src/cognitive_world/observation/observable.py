"""Typed, event-bound objective facts and event-time observation context."""

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, TypeAlias

from cognitive_world.core.event import Event


FactScalar: TypeAlias = str | int | float | bool | None
FactValue: TypeAlias = FactScalar | tuple[FactScalar, ...]


class _ProcessorSeal:
    def __deepcopy__(self, memo: dict[int, Any]) -> "_ProcessorSeal":
        return self


_PROCESSOR_SEAL = _ProcessorSeal()


def _valid_value(value: FactValue) -> bool:
    values = value if isinstance(value, tuple) else (value,)
    return all(
        item is None
        or isinstance(item, (str, int, bool))
        or (isinstance(item, float) and math.isfinite(item))
        for item in values
    )


@dataclass(frozen=True)
class ObservableFactDraft:
    """Explicit objective claim produced by an event-specific trusted handler.

    `fact_type` and `predicate` are open strings, not action categories.
    The deliberately small value shape excludes arbitrary metadata, nested
    backend objects, audiences, scopes, and private cognition records.
    """

    fact_type: str
    predicate: str
    value: FactValue
    subject_ref: str | None = None
    location_id: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.fact_type, str)
            or not self.fact_type
            or not isinstance(self.predicate, str)
            or not self.predicate
        ):
            raise ValueError("fact_type and predicate must be non-empty")
        if self.subject_ref is not None and (
            not isinstance(self.subject_ref, str) or not self.subject_ref
        ):
            raise ValueError("subject_ref must be non-empty when provided")
        if self.location_id is not None and (
            not isinstance(self.location_id, str) or not self.location_id
        ):
            raise ValueError("location_id must be non-empty when provided")
        if not _valid_value(self.value):
            raise TypeError("ObservableFact value must be a finite scalar or scalar tuple")


@dataclass(frozen=True)
class _FactReceipt:
    seal: _ProcessorSeal = field(repr=False, compare=False)
    event_snapshot: tuple[Any, ...] = field(repr=False)
    fact_snapshot: tuple[Any, ...] = field(repr=False)


@dataclass(frozen=True)
class ObservableFact:
    """Immutable objective fact issued after controlled Event processing."""

    fact_id: str
    source_event_id: str
    fact_type: str
    predicate: str
    value: FactValue
    subject_ref: str | None = None
    location_id: str | None = None
    _receipt: _FactReceipt | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.fact_id, str)
            or not self.fact_id
            or not isinstance(self.source_event_id, str)
            or not self.source_event_id
        ):
            raise ValueError("fact_id and source_event_id must be non-empty")
        if (
            not isinstance(self.fact_type, str)
            or not self.fact_type
            or not isinstance(self.predicate, str)
            or not self.predicate
        ):
            raise ValueError("fact_type and predicate must be non-empty")
        if self.subject_ref is not None and (
            not isinstance(self.subject_ref, str) or not self.subject_ref
        ):
            raise ValueError("subject_ref must be non-empty when provided")
        if self.location_id is not None and (
            not isinstance(self.location_id, str) or not self.location_id
        ):
            raise ValueError("location_id must be non-empty when provided")
        if not _valid_value(self.value):
            raise TypeError("ObservableFact value must be a finite scalar or scalar tuple")

    def _snapshot(self) -> tuple[Any, ...]:
        return (
            self.fact_id,
            self.source_event_id,
            self.fact_type,
            self.predicate,
            deepcopy(self.value),
            self.subject_ref,
            self.location_id,
        )

    def has_trusted_source(self, event: Event) -> bool:
        receipt = self._receipt
        if not isinstance(event, Event) or not event.has_trusted_source():
            return False
        return (
            isinstance(receipt, _FactReceipt)
            and receipt.seal is _PROCESSOR_SEAL
            and self.source_event_id == event.id
            and receipt.event_snapshot == event._source_snapshot()
            and receipt.fact_snapshot == self._snapshot()
        )


class EventStatePhase(str, Enum):
    """Which side of the Event application an event-time capture describes."""

    AFTER_WORLD_UPDATE = "after_world_update"
    BEFORE_WORLD_UPDATE = "before_world_update"


@dataclass(frozen=True)
class EventTimeObservationContext:
    """Immutable, event-bound context; absent inputs remain explicitly unknown.

    `event_timestamp` is the timestamp carried by the trusted Event. It is not
    a SimulationClock capture time. This foundation does not invent observer
    identity, position, environment, or sensory conditions.
    """

    source_event_id: str
    event_timestamp: str
    state_phase: EventStatePhase
    observer_id: str | None = None
    observer_position: str | None = None
    environment_conditions: tuple[tuple[str, FactValue], ...] | None = None
    environment_snapshot_complete: bool = False
    sensory_conditions: tuple[str, ...] | None = None
    world_state_values: tuple[tuple[str, str, FactValue], ...] = ()
    simulation_time: int | None = None
    fact_location_id: str | None = None
    observer_positions: tuple[tuple[str, str | None, tuple[str, ...] | None], ...] = ()
    observer_state_phase: EventStatePhase = EventStatePhase.BEFORE_WORLD_UPDATE
    _receipt: _FactReceipt | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.source_event_id, str) or not self.source_event_id:
            raise ValueError("source_event_id must be non-empty")
        if not isinstance(self.event_timestamp, str):
            raise TypeError("event_timestamp must be a string")
        if not isinstance(self.state_phase, EventStatePhase):
            raise TypeError("state_phase must be an EventStatePhase")
        if self.simulation_time is not None and (
            isinstance(self.simulation_time, bool) or not isinstance(self.simulation_time, int)
        ):
            raise TypeError("simulation_time must be an integer or unknown")
        if self.fact_location_id is not None and (
            not isinstance(self.fact_location_id, str) or not self.fact_location_id
        ):
            raise ValueError("fact_location_id must be non-empty when known")
        if not isinstance(self.observer_state_phase, EventStatePhase):
            raise TypeError("observer_state_phase must be an EventStatePhase")
        if not isinstance(self.observer_positions, tuple):
            raise TypeError("observer_positions must be an immutable tuple")
        for entry in self.observer_positions:
            if not isinstance(entry, tuple) or len(entry) != 3:
                raise TypeError("observer_positions entries must be (id, position, senses)")
            observer_id, position, senses = entry
            if not isinstance(observer_id, str) or not observer_id:
                raise ValueError("observer ids must be non-empty")
            if position is not None and (not isinstance(position, str) or not position):
                raise ValueError("known observer positions must be non-empty")
            if senses is not None and (
                not isinstance(senses, tuple)
                or any(not isinstance(item, str) or not item for item in senses)
            ):
                raise TypeError("known sensory capabilities must be immutable strings")
        if self.observer_id is not None and (
            not isinstance(self.observer_id, str) or not self.observer_id
        ):
            raise ValueError("observer_id must be non-empty when known")
        if self.observer_position is not None and (
            not isinstance(self.observer_position, str) or not self.observer_position
        ):
            raise ValueError("known observer identifiers and positions must be non-empty")
        if self.environment_conditions is not None and not isinstance(
            self.environment_conditions, tuple
        ):
            raise TypeError("environment_conditions must be an immutable tuple or unknown")
        if type(self.environment_snapshot_complete) is not bool:
            raise TypeError("environment_snapshot_complete must be bool")
        if self.environment_conditions is None and self.environment_snapshot_complete:
            raise ValueError("unknown environment conditions cannot be marked complete")
        if self.environment_conditions == () and not self.environment_snapshot_complete:
            raise ValueError("an empty environment snapshot must be explicitly complete")
        if self.sensory_conditions is not None and not isinstance(
            self.sensory_conditions, tuple
        ):
            raise TypeError("sensory_conditions must be an immutable tuple or unknown")
        if not isinstance(self.world_state_values, tuple):
            raise TypeError("world_state_values must be an immutable tuple")
        for entry in self.environment_conditions or ():
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise TypeError("environment_conditions entries must be 2-item tuples")
            key, value = entry
            if not isinstance(key, str) or not key or not _valid_value(value):
                raise ValueError("environment conditions must be typed scalar values")
        if self.sensory_conditions is not None and any(
            not isinstance(condition, str) or not condition
            for condition in self.sensory_conditions
        ):
            raise ValueError("known sensory conditions must be non-empty strings")
        for entry in self.world_state_values:
            if not isinstance(entry, tuple) or len(entry) != 3:
                raise TypeError("world_state_values entries must be 3-item tuples")
            collection, key, value = entry
            if (
                not isinstance(collection, str)
                or not collection
                or not isinstance(key, str)
                or not key
                or not _valid_value(value)
            ):
                raise ValueError("world state snapshot entries must be typed scalar values")

    def _snapshot(self) -> tuple[Any, ...]:
        return (
            self.source_event_id,
            self.event_timestamp,
            self.state_phase,
            self.observer_id,
            self.observer_position,
            deepcopy(self.environment_conditions),
            self.environment_snapshot_complete,
            deepcopy(self.sensory_conditions),
            deepcopy(self.world_state_values),
            self.simulation_time,
            self.fact_location_id,
            deepcopy(self.observer_positions),
            self.observer_state_phase,
        )

    def has_trusted_source(self, event: Event) -> bool:
        receipt = self._receipt
        if not isinstance(event, Event) or not event.has_trusted_source():
            return False
        return (
            isinstance(receipt, _FactReceipt)
            and receipt.seal is _PROCESSOR_SEAL
            and self.source_event_id == event.id
            and receipt.event_snapshot == event._source_snapshot()
            and receipt.fact_snapshot == self._snapshot()
        )


@dataclass(frozen=True)
class EventProcessingEvidence:
    """Read-only result of the controlled EventProcessor observation hook."""

    source_event_id: str
    observable_facts: tuple[ObservableFact, ...]
    event_time_context: EventTimeObservationContext

    def __post_init__(self) -> None:
        if not isinstance(self.source_event_id, str) or not self.source_event_id:
            raise ValueError("source_event_id must be non-empty")
        if not isinstance(self.observable_facts, tuple) or any(
            not isinstance(fact, ObservableFact) for fact in self.observable_facts
        ):
            raise TypeError("observable_facts must be a tuple of ObservableFact")
        if not isinstance(self.event_time_context, EventTimeObservationContext):
            raise TypeError("event_time_context must be EventTimeObservationContext")

    def has_trusted_source(self, event: Event) -> bool:
        return (
            isinstance(event, Event)
            and event.has_trusted_source()
            and self.source_event_id == event.id
            and self.event_time_context.has_trusted_source(event)
            and all(fact.has_trusted_source(event) for fact in self.observable_facts)
        )


def _issue_processing_evidence(
    event: Event,
    drafts: tuple[ObservableFactDraft, ...],
    *,
    simulation_time: int | None = None,
    observer_positions: tuple[tuple[str, str | None, tuple[str, ...] | None], ...] = (),
    environment_conditions: tuple[tuple[str, FactValue], ...] | None = None,
    environment_snapshot_complete: bool = False,
    observer_state_phase: EventStatePhase = EventStatePhase.BEFORE_WORLD_UPDATE,
) -> EventProcessingEvidence:
    """Private EventProcessor issuance boundary; not a public auth API."""
    if not isinstance(event, Event) or not event.has_trusted_source():
        raise PermissionError("observable facts require a trusted processed Event")
    facts: list[ObservableFact] = []
    for index, draft in enumerate(drafts):
        if not isinstance(draft, ObservableFactDraft):
            raise TypeError("event handler facts must be ObservableFactDraft records")
        fact = ObservableFact(
            fact_id=f"observable:{event.id}:{index}",
            source_event_id=event.id,
            fact_type=draft.fact_type,
            predicate=draft.predicate,
            value=deepcopy(draft.value),
            subject_ref=draft.subject_ref,
            location_id=draft.location_id,
        )
        object.__setattr__(
            fact,
            "_receipt",
            _FactReceipt(_PROCESSOR_SEAL, event._source_snapshot(), fact._snapshot()),
        )
        facts.append(fact)

    fact_location = next(
        (draft.location_id for draft in drafts if draft.location_id is not None), None
    )
    context = EventTimeObservationContext(
        source_event_id=event.id,
        event_timestamp=event.timestamp,
        state_phase=EventStatePhase.AFTER_WORLD_UPDATE,
        environment_conditions=environment_conditions,
        environment_snapshot_complete=environment_snapshot_complete,
        simulation_time=simulation_time,
        fact_location_id=fact_location,
        observer_positions=observer_positions,
        observer_state_phase=observer_state_phase,
    )
    object.__setattr__(
        context,
        "_receipt",
        _FactReceipt(_PROCESSOR_SEAL, event._source_snapshot(), context._snapshot()),
    )
    return EventProcessingEvidence(event.id, tuple(facts), context)
