"""Presentation filtering from existing trusted Agent Observation results."""

from dataclasses import dataclass

from cognitive_world.core.event import Event
from cognitive_world.event.history import EventHistory
from cognitive_world.observation.generator import VisibilityPolicy
from cognitive_world.observation.observable import EventProcessingEvidence, ObservableFact
from cognitive_world.observation.store import ObservationStore
from cognitive_world.presentation.contracts import (
    _PRESENTATION_SEAL,
    _Receipt,
    PerspectiveContext,
    VisibleInput,
)


@dataclass
class VisibilityFilter:
    """Accept only facts already authorized for the resolved view Agent."""

    event_history: EventHistory
    observation_store: ObservationStore

    def filter(
        self, event: Event, evidence: EventProcessingEvidence, perspective: PerspectiveContext
    ) -> tuple[VisibleInput, ...]:
        if not perspective.has_trusted_resolution():
            raise PermissionError("PerspectiveContext was not issued by PerspectiveResolver")
        if not isinstance(event, Event) or not event.has_trusted_source():
            raise PermissionError("presentation requires a trusted Event")
        if not isinstance(evidence, EventProcessingEvidence) or not evidence.has_trusted_source(event):
            raise PermissionError("presentation requires trusted event processing evidence")
        confirmed = self.event_history.get_event(event.id)
        stored_evidence = self.event_history.get_processing_evidence(event.id)
        if confirmed != event or stored_evidence != evidence:
            raise PermissionError("Event and evidence are not the recorded processing result")

        authorized: list[VisibleInput] = []
        if not VisibilityPolicy().allows(event, evidence, perspective.observer_id):
            return ()
        for observation in self.observation_store.get_by_observer(perspective.observer_id):
            if (
                observation.source_event_id != event.id
                or not observation.has_trusted_provenance()
                or not isinstance(observation.content, ObservableFact)
            ):
                continue
            fact = observation.content
            if (
                not fact.has_trusted_source(event)
                or fact.source_event_id != event.id
                or not any(candidate._snapshot() == fact._snapshot() for candidate in evidence.observable_facts)
            ):
                continue
            scope = self._scope_for(fact)
            if scope is None or scope not in perspective.visible_scopes:
                continue
            visible = VisibleInput(
                recipient_id=perspective.recipient_id,
                observer_id=perspective.observer_id,
                session_id=perspective.session_id,
                source_event_id=event.id,
                source_fact_id=fact.fact_id,
                source_observation_id=observation.observation_id,
                scope=scope,
                fact_type=fact.fact_type,
                predicate=fact.predicate,
                value=fact.value,
                subject_ref=fact.subject_ref,
                location_id=fact.location_id,
                source_event_changed_state=(
                    event.type == "resolution"
                    and bool(event.changes)
                    and isinstance(event.changes[0], dict)
                    and event.changes[0].get("success") is True
                    and len(event.changes) > 1
                ),
            )
            object.__setattr__(
                visible,
                "_receipt",
                _Receipt(
                    _PRESENTATION_SEAL,
                    visible._snapshot(),
                    perspective._snapshot(),
                ),
            )
            authorized.append(visible)
        return tuple(authorized)

    def validate_input(
        self, visible: VisibleInput, perspective: PerspectiveContext
    ) -> None:
        """Recheck every input against current trusted Event/evidence/Observation."""
        if not isinstance(visible, VisibleInput) or not visible.has_filter_receipt(perspective):
            raise PermissionError("VisibleInput is not an intact filter result")
        if (
            visible.recipient_id != perspective.recipient_id
            or visible.observer_id != perspective.observer_id
            or visible.session_id != perspective.session_id
        ):
            raise PermissionError("VisibleInput recipient or perspective does not match")
        event = self.event_history.get_event(visible.source_event_id)
        evidence = self.event_history.get_processing_evidence(visible.source_event_id)
        if event is None or evidence is None or not evidence.has_trusted_source(event):
            raise PermissionError("VisibleInput source is no longer verifiable")
        matching = tuple(
            observation
            for observation in self.observation_store.get_by_observer(perspective.observer_id)
            if observation.observation_id == visible.source_observation_id
        )
        if len(matching) != 1:
            raise PermissionError("authorized Observation is unavailable")
        observation = matching[0]
        if (
            not observation.has_trusted_provenance()
            or observation.source_event_id != event.id
            or observation.observer_id != perspective.observer_id
            or not isinstance(observation.content, ObservableFact)
            or observation.content.fact_id != visible.source_fact_id
            or not observation.content.has_trusted_source(event)
            or not VisibilityPolicy().allows(event, evidence, perspective.observer_id)
        ):
            raise PermissionError("VisibleInput no longer has valid observation authority")
        fact = observation.content
        if (
            fact.fact_type != visible.fact_type
            or fact.predicate != visible.predicate
            or fact.value != visible.value
            or fact.subject_ref != visible.subject_ref
            or fact.location_id != visible.location_id
            or visible.source_event_changed_state != (
                event.type == "resolution"
                and bool(event.changes)
                and isinstance(event.changes[0], dict)
                and event.changes[0].get("success") is True
                and len(event.changes) > 1
            )
            or self._scope_for(fact) != visible.scope
        ):
            raise PermissionError("VisibleInput content does not match its source fact")

    @staticmethod
    def _scope_for(fact: ObservableFact) -> str | None:
        if fact.fact_type == "social_output" and fact.predicate == "utterance_delivered":
            return "dialogue"
        if fact.fact_type == "environment_state" and fact.location_id is not None:
            return "environment"
        if (fact.fact_type == "movement" and fact.predicate == "actor_arrived"
                and isinstance(fact.value, str) and fact.location_id == fact.value
                and fact.subject_ref is not None):
            return "environment"
        return None
