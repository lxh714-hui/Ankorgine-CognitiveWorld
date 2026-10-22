from cognitive_world.core.causal_graph import CausalGraph
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.causality import EventCausality


def test_event_cause_can_be_recorded_and_queried():
    graph = CausalGraph()
    causality = EventCausality(causal_graph=graph)

    link = causality.record_cause(event_id="event_002", cause_id="event_001")

    assert link.cause == "event_001"
    assert link.effect == "event_002"
    assert causality.find_cause(event_id="event_002", cause_id="event_001") == (link,)
    assert graph.find_links() == (link,)


def test_recording_cause_does_not_change_world_state():
    world_state = WorldState()
    before = (
        dict(world_state.entities),
        dict(world_state.locations),
        dict(world_state.relationships),
        dict(world_state.facts),
        dict(world_state.environment),
    )
    causality = EventCausality()

    causality.record_cause(event_id="event_002", cause_id="event_001")

    after = (
        dict(world_state.entities),
        dict(world_state.locations),
        dict(world_state.relationships),
        dict(world_state.facts),
        dict(world_state.environment),
    )
    assert after == before
