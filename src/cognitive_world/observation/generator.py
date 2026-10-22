"""Default-deny policy evaluation and controlled Observation issuance."""

from dataclasses import dataclass
from hashlib import sha256

from cognitive_world.core.event import Event
from cognitive_world.observation.observation import Observation
from cognitive_world.observation.observable import EventProcessingEvidence


class ObservationAuthorizationError(PermissionError):
    """Raised when trusted facts and event-time observer context are missing."""


@dataclass(frozen=True)
class VisibilityPolicy:
    """First narrow perception rule: a registered agent sees a lit-room change."""

    def allows(
        self, event: Event, evidence: EventProcessingEvidence, observer_id: str
    ) -> bool:
        if (
            not isinstance(event, Event)
            or not event.has_trusted_source()
            or event.type not in {"room_light_changed", "resolution", "environment_state_observed", "dialogue_input", "dialogue_reply"}
            or not isinstance(evidence, EventProcessingEvidence)
            or not evidence.has_trusted_source(event)
            or not isinstance(observer_id, str)
            or not observer_id
        ):
            return False
        context = evidence.event_time_context
        if event.type in {"dialogue_input", "dialogue_reply"}:
            # A trusted input event explicitly addresses one registered receiver.
            event_observers = {item[0] for item in context.observer_positions}
            return any(
                fact.has_trusted_source(event)
                and fact.fact_type == ("social_input" if event.type == "dialogue_input" else "social_output")
                and fact.predicate == "utterance_delivered"
                and fact.subject_ref == observer_id
                and observer_id in event.participants
                and observer_id in event_observers
                and context.fact_location_id == fact.location_id
                and next(
                    (position for identity, position, _ in context.observer_positions if identity == observer_id),
                    None,
                ) == fact.location_id
                for fact in evidence.observable_facts
            )
        if context.simulation_time is None or context.fact_location_id is None:
            return False
        observer = next(
            (item for item in context.observer_positions if item[0] == observer_id),
            None,
        )
        if observer is None:
            return False
        _, position, senses = observer
        if (
            position != context.fact_location_id
            or senses is None
            or "sight" not in senses
        ):
            return False
        conditions = dict(context.environment_conditions or ())
        room_light = any(
            fact.has_trusted_source(event)
            and fact.fact_type == "environment_state"
            and fact.predicate == "room_light_on"
            and type(fact.value) is bool
            and fact.location_id == context.fact_location_id
            for fact in evidence.observable_facts
        )
        door_open = any(
            fact.has_trusted_source(event)
            and fact.fact_type == "environment_state"
            and fact.predicate in {"door_open", "door_locked"}
            and type(fact.value) is bool
            and fact.location_id == context.fact_location_id
            and fact.subject_ref is not None
            and conditions.get(f"door:{fact.subject_ref}:{'open' if fact.predicate == 'door_open' else 'locked'}") is fact.value
            for fact in evidence.observable_facts
        )
        passage_known = any(
            fact.has_trusted_source(event)
            and fact.fact_type == "environment_state"
            and fact.predicate == "passage_destination"
            and isinstance(fact.value, str)
            and fact.location_id == context.fact_location_id
            and fact.subject_ref is not None
            and conditions.get(f"passage:{fact.subject_ref}:destination") == fact.value
            for fact in evidence.observable_facts
        )
        actor_arrived = any(
            fact.has_trusted_source(event)
            and fact.fact_type == "movement"
            and fact.predicate == "actor_arrived"
            and isinstance(fact.value, str)
            and fact.location_id == context.fact_location_id
            and fact.subject_ref is not None
            and conditions.get(f"location:{fact.subject_ref}") == fact.value
            for fact in evidence.observable_facts
        )
        return (
            room_light
            and conditions.get(f"{context.fact_location_id}:light_on") is True
        ) or door_open or passage_known or actor_arrived


@dataclass
class ObservationGenerator:
    """Compatibility surface that fails closed rather than copying an Event."""

    def generate(self, event: Event, observer_id: str) -> Observation:
        """Reject generation until authorized observable facts can be supplied.

        An Event's provenance proves its controlled origin, not that its
        contents were available to a particular observer at the event time.
        """
        if not isinstance(event, Event):
            raise TypeError("event must be an Event")
        if not event.has_trusted_source():
            raise ObservationAuthorizationError(
                "cannot observe an Event without controlled provenance"
            )
        raise ObservationAuthorizationError(
            "trusted Event provenance is insufficient; observable facts and "
            "event-time observer context are not available"
        )

    def generate_authorized(
        self,
        event: Event,
        evidence: EventProcessingEvidence,
        *,
        observer_id: str,
        source_timeline_id: str | None = None,
        source_runtime_session_id: str | None = None,
        source_runtime_generation: int | None = None,
    ) -> tuple[Observation, ...]:
        """Issue only facts authorized by the narrow, default-deny policy."""
        if source_timeline_id is not None and (
            not isinstance(source_timeline_id, str) or not source_timeline_id
        ):
            raise ValueError("source_timeline_id must be non-empty when provided")
        if (source_runtime_session_id is None) != (source_runtime_generation is None):
            raise ValueError("Runtime session and generation must be supplied together")
        if source_runtime_session_id is not None and (
            not isinstance(source_runtime_session_id, str)
            or not source_runtime_session_id
            or type(source_runtime_generation) is not int
            or source_runtime_generation < 0
        ):
            raise ValueError("Runtime binding must contain a session and non-negative generation")
        if not VisibilityPolicy().allows(event, evidence, observer_id):
            return ()
        context = evidence.event_time_context
        from cognitive_world.observation.observation import (
            _OBSERVATION_RECEIPT_SEAL,
            _ObservationProvenance,
        )

        observations: list[Observation] = []
        for fact in evidence.observable_facts:
            authorized_content = (
                fact.has_trusted_source(event)
                and fact.location_id == context.fact_location_id
                and (
                    (event.type in {"dialogue_input", "dialogue_reply"} and fact.fact_type == ("social_input" if event.type == "dialogue_input" else "social_output") and fact.predicate == "utterance_delivered" and fact.subject_ref == observer_id and observer_id in event.participants and observer_id in {item[0] for item in context.observer_positions} and context.fact_location_id == fact.location_id and next((position for identity, position, _ in context.observer_positions if identity == observer_id), None) == fact.location_id and isinstance(fact.value, str))
                    or
                    (fact.fact_type == "environment_state" and fact.value is True and fact.predicate == "room_light_on" and dict(context.environment_conditions or ()).get(f"{context.fact_location_id}:light_on") is True)
                    or (fact.fact_type == "environment_state" and fact.predicate == "door_open" and type(fact.value) is bool and fact.subject_ref is not None and dict(context.environment_conditions or ()).get(f"door:{fact.subject_ref}:open") is fact.value)
                    or (fact.fact_type == "environment_state" and fact.predicate == "door_locked" and type(fact.value) is bool and fact.subject_ref is not None and dict(context.environment_conditions or ()).get(f"door:{fact.subject_ref}:locked") is fact.value)
                    or (fact.fact_type == "environment_state" and isinstance(fact.value, str) and fact.predicate == "passage_destination" and fact.subject_ref is not None and dict(context.environment_conditions or ()).get(f"passage:{fact.subject_ref}:destination") == fact.value)
                    or (fact.fact_type == "movement" and fact.predicate == "actor_arrived" and isinstance(fact.value, str) and fact.subject_ref is not None and dict(context.environment_conditions or ()).get(f"location:{fact.subject_ref}") == fact.value)
                )
            )
            if not authorized_content:
                continue
            observation = Observation(
                observation_id=f"observation:{event.id}:{observer_id}:{fact.fact_id}",
                observer_id=observer_id,
                source_event_id=event.id,
                content=fact,
            )
            basis = repr(
                (
                    event._source_snapshot(),
                    evidence.source_event_id,
                    fact._snapshot(),
                    context._snapshot(),
                    observer_id,
                    source_timeline_id,
                    source_runtime_session_id,
                    source_runtime_generation,
                    "co-located registered observer with known sight; room light on",
                )
            )
            fingerprint = sha256(basis.encode("utf-8")).hexdigest()
            object.__setattr__(
                observation,
                "_provenance",
                _ObservationProvenance(
                    _OBSERVATION_RECEIPT_SEAL,
                    observation._snapshot(),
                    fingerprint,
                    source_timeline_id,
                    source_runtime_session_id,
                    source_runtime_generation,
                ),
            )
            observations.append(observation)
        return tuple(observations)
