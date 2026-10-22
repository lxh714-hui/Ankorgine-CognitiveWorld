from cognitive_world.core.causal_graph import CausalGraph
from cognitive_world.core.event import Event
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.handler import EventHandler
from cognitive_world.event.processor import EventProcessor
from cognitive_world.event.factory import SystemEventFactory


def system_event(event_id, event_type):
    return SystemEventFactory().create(event_id=event_id, event_type=event_type, timestamp="t1")


class FactUpdateHandler(EventHandler):
    def handle(self, event: Event) -> WorldUpdate:
        return WorldUpdate(
            target_id="facts",
            operation="update",
            payload={event.id: {"recorded": True}},
        )


def test_processor_records_explicit_cause_after_world_update():
    graph = CausalGraph()
    processor = EventProcessor(causal_graph=graph)
    processor.register_handler("generic", FactUpdateHandler())
    event = system_event("event_002", "generic")
    world_state = WorldState()

    processor.process(event, world_state, cause_id="event_001")

    assert world_state.facts == {"event_002": {"recorded": True}}
    assert graph.find_links(cause="event_001", effect="event_002")


def test_processor_does_not_record_causality_without_cause_id():
    graph = CausalGraph()
    processor = EventProcessor(causal_graph=graph)
    processor.register_handler("generic", FactUpdateHandler())
    event = system_event("event_003", "generic")
    world_state = WorldState()

    processor.process(event, world_state)

    assert world_state.facts == {"event_003": {"recorded": True}}
    assert graph.find_links() == ()


def test_cause_without_graph_fails_before_world_update():
    processor = EventProcessor()
    processor.register_handler("generic", FactUpdateHandler())
    event = system_event("event_004", "generic")
    world_state = WorldState()

    try:
        processor.process(event, world_state, cause_id="event_001")
    except ValueError as error:
        assert "CausalGraph is required" in str(error)
    else:
        raise AssertionError("Expected missing CausalGraph to be rejected")

    assert world_state.facts == {}
