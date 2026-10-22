from dataclasses import FrozenInstanceError, fields, replace

import pytest

from cognitive_world.core.event import Event
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.event.handler import EventHandler
from cognitive_world.event.history import EventHistory
from cognitive_world.event.processor import EventProcessor
from cognitive_world.observation import (
    EventStatePhase,
    EventTimeObservationContext,
    EventProcessingEvidence,
    ObservationAuthorizationError,
    ObservationGenerator,
    ObservationStore,
    ObservableFact,
    ObservableFactDraft,
)


class EmptyHandler(EventHandler):
    def handle(self, event):
        return WorldUpdate("facts", "update", {"generic": event.changes})


class ExplicitFactHandler(EmptyHandler):
    def observable_facts(self, event, update):
        return (
            ObservableFactDraft(
                fact_type="door.state",
                subject_ref="door-7",
                predicate="state_changed_to",
                value="open",
            ),
            # Open-ended semantics: this is not rejected for being a new action.
            ObservableFactDraft(
                fact_type="future_method.experimental",
                predicate="was_resolved_as",
                value="attempted",
                subject_ref="device-2",
            ),
        )


def _event(event_id="event-1", **kwargs):
    return SystemEventFactory().create(
        event_id=event_id,
        event_type="world_change",
        timestamp="t-event",
        **kwargs,
    )


def test_hand_built_event_cannot_reach_fact_issuance():
    history = EventHistory()
    processor = EventProcessor(event_history=history)
    processor.register_handler("world_change", ExplicitFactHandler())
    manual = Event("manual", "world_change", "t-event")

    with pytest.raises(ValueError, match="controlled source"):
        processor.process(manual, WorldState())

    assert history.get_processing_evidence(manual.id) is None


def test_hand_built_fact_and_processing_evidence_are_not_self_authenticating():
    event = _event()
    hand_built = ObservableFact(
        "manual-fact", event.id, "door.state", "state_changed_to", "open", "door-7"
    )
    hand_built_evidence = EventProcessingEvidence(
        event.id,
        (hand_built,),
        EventTimeObservationContext(
            source_event_id=event.id,
            event_timestamp=event.timestamp,
            state_phase=EventStatePhase.AFTER_WORLD_UPDATE,
        ),
    )

    assert not hand_built.has_trusted_source(event)
    assert not hand_built_evidence.has_trusted_source(event)


def test_controlled_handler_explicitly_emits_typed_facts_and_event_time_evidence():
    history = EventHistory()
    processor = EventProcessor(event_history=history)
    processor.register_handler("world_change", ExplicitFactHandler())
    event = _event(changes=[{"untyped": "change"}], metadata={"audience": "all"})

    evidence = processor.process_with_evidence(event, WorldState())

    assert evidence.has_trusted_source(event)
    assert len(evidence.observable_facts) == 2
    assert evidence.observable_facts[0].source_event_id == event.id
    assert evidence.observable_facts[0].value == "open"
    assert evidence.observable_facts[1].fact_type == "future_method.experimental"
    assert evidence.event_time_context.state_phase is EventStatePhase.AFTER_WORLD_UPDATE
    assert evidence.event_time_context.event_timestamp == event.timestamp
    assert evidence.event_time_context.has_trusted_source(event)
    assert history.get_processing_evidence(event.id).has_trusted_source(event)


def test_generic_world_update_and_event_metadata_do_not_become_facts():
    processor = EventProcessor()
    processor.register_handler("world_change", EmptyHandler())
    event = _event(
        changes=[{"secret": "event changes are not auto-facts"}],
        metadata={"prompt": "private", "visible_scopes": ["all"]},
    )

    evidence = processor.process_with_evidence(event, WorldState())

    assert evidence.observable_facts == ()
    assert evidence.event_time_context.world_state_values == ()


def test_fact_is_immutable_event_bound_and_invalidated_by_content_replacement():
    event = _event()
    processor = EventProcessor()
    processor.register_handler("world_change", ExplicitFactHandler())
    evidence = processor.process_with_evidence(event, WorldState())
    fact = evidence.observable_facts[0]

    with pytest.raises(FrozenInstanceError):
        fact.value = "closed"
    altered = replace(fact, value="closed")
    assert not altered.has_trusted_source(event)
    assert fact.has_trusted_source(event)


def test_event_time_evidence_is_snapshot_and_does_not_follow_later_world_changes():
    world = WorldState()
    history = EventHistory()
    processor = EventProcessor(event_history=history, world_state=world)
    processor.register_handler("world_change", ExplicitFactHandler())
    first = _event("first")
    first_evidence = processor.process_with_evidence(first, world)
    original_value = first_evidence.observable_facts[0].value

    second = _event("second", changes=[{"later": True}])
    processor.process_with_evidence(second, world)
    retrieved = history.get_processing_evidence(first.id)

    assert retrieved.observable_facts[0].value == original_value
    assert retrieved.event_time_context.state_phase is EventStatePhase.AFTER_WORLD_UPDATE


def test_observable_contract_contains_no_agent_private_cognition_fields():
    from cognitive_world.observation import EventTimeObservationContext, ObservableFact

    names = {
        item.name
        for model in (ObservableFact, EventTimeObservationContext)
        for item in fields(model)
    }
    assert not names.intersection(
        {"beliefs", "goals", "emotion", "memory", "cognition", "prompt"}
    )


def test_missing_observer_location_and_senses_remain_unknown_and_do_not_authorize():
    processor = EventProcessor()
    processor.register_handler("world_change", ExplicitFactHandler())
    event = _event()
    evidence = processor.process_with_evidence(event, WorldState())
    context = evidence.event_time_context

    assert context.observer_id is None
    assert context.observer_position is None
    assert context.sensory_conditions is None
    assert context.environment_conditions is None
    assert context.environment_snapshot_complete is False
    assert not hasattr(evidence, "authorized_observation")
    with pytest.raises(ObservationAuthorizationError):
        ObservationGenerator().generate(event, "agent-1")
    assert ObservationStore().all() == ()


def test_explicitly_complete_empty_environment_is_distinct_from_unknown():
    world = WorldState()
    world.load_environment_snapshot({})
    processor = EventProcessor()
    processor.register_handler("world_change", ExplicitFactHandler())

    evidence = processor.process_with_evidence(_event("known-empty"), world)

    assert world.environment_snapshot_complete is True
    assert evidence.event_time_context.environment_conditions == ()
    assert evidence.event_time_context.environment_snapshot_complete is True


def test_legacy_world_state_adapter_without_completeness_marker_stays_unknown():
    class MinimalWorldState:
        def __init__(self):
            self.applied = []

        def apply_event(self, event, update):
            self.applied.append((event, update))

    world = MinimalWorldState()
    processor = EventProcessor()
    processor.register_handler("world_change", ExplicitFactHandler())
    event = _event("legacy-world-state")

    evidence = processor.process_with_evidence(event, world)

    assert len(world.applied) == 1
    assert world.applied[0][0] is event
    assert evidence.event_time_context.environment_conditions is None
    assert evidence.event_time_context.environment_snapshot_complete is False


def test_unknown_environment_does_not_authorize_otherwise_qualified_observer():
    from cognitive_world.agent.registry import AgentRegistry
    from cognitive_world.agent.runtime_agent import RuntimeAgent
    from cognitive_world.core.entity import Entity
    from cognitive_world.runtime.clock import SimulationClock

    class RoomLightDraftHandler(EmptyHandler):
        def observable_facts(self, event, update):
            return (
                ObservableFactDraft(
                    fact_type="environment_state",
                    predicate="room_light_on",
                    value=True,
                    subject_ref="room-a",
                    location_id="room-a",
                ),
            )

    world = WorldState()
    world.load_entity(Entity("observer-1", "agent", sensory_capabilities=("sight",)))
    world.load_location("observer-1", "room-a")
    registry = AgentRegistry()
    registry.register(RuntimeAgent("observer-1"))
    processor = EventProcessor(agent_registry=registry, simulation_clock=SimulationClock())
    processor.register_handler("room_light_changed", RoomLightDraftHandler())
    event = SystemEventFactory().create(
        event_id="unknown-environment-light",
        event_type="room_light_changed",
        timestamp="descriptive-only",
        changes=[{"room_id": "room-a", "from_light_on": False, "to_light_on": True}],
    )

    evidence = processor.process_with_evidence(event, world)

    assert evidence.event_time_context.environment_conditions is None
    assert evidence.event_time_context.environment_snapshot_complete is False
    assert ObservationGenerator().generate_authorized(
        event, evidence, observer_id="observer-1"
    ) == ()


def test_event_history_is_storage_not_fact_authority():
    event = _event()
    history = EventHistory()
    history.append(event)

    assert history.get_event(event.id) is not None
    assert history.get_processing_evidence(event.id) is None


def test_processor_revalidates_source_after_handler_before_world_write():
    class MutatingHandler(ExplicitFactHandler):
        def handle(self, event):
            event.changes.append({"tampered": True})
            return super().handle(event)

    class TrackingWorldState(WorldState):
        def __init__(self):
            super().__init__()
            self.applied = False

        def apply_event(self, event, update):
            self.applied = True
            super().apply_event(event, update)

    world = TrackingWorldState()
    history = EventHistory()
    processor = EventProcessor(event_history=history)
    processor.register_handler("world_change", MutatingHandler())

    with pytest.raises(ValueError, match="mutated during controlled processing"):
        processor.process(_event(), world)

    assert not world.applied
    assert history.get_events() == ()
