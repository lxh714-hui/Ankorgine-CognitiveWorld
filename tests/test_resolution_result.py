from cognitive_world.core.world_state import WorldState
from cognitive_world.event.history import EventHistory
from cognitive_world.resolution import ResolutionResult


def test_resolution_result_saves_fields_and_references():
    result = ResolutionResult(
        resolution_id="resolution_001",
        attempt_id="attempt_001",
        success=True,
        outcome="completed",
        event_ids=["event_001", "event_002"],
        metadata={"rule": "rule_ref_001"},
    )

    assert result.resolution_id == "resolution_001"
    assert result.attempt_id == "attempt_001"
    assert result.success is True
    assert result.outcome == "completed"
    assert result.confirmed is False
    assert result.event_ids == ["event_001", "event_002"]
    assert result.metadata == {"rule": "rule_ref_001"}


def test_mutable_fields_are_isolated_on_construction_and_access():
    event_ids = ["event_001"]
    metadata = {"nested": {"labels": ["initial"]}}
    result = ResolutionResult(
        "resolution_001", "attempt_001", False, "rejected", event_ids, metadata
    )

    event_ids.append("event_external")
    metadata["nested"]["labels"].append("external")
    result.event_ids.append("event_returned")
    result.metadata["nested"]["labels"].append("returned")

    assert result.event_ids == ["event_001"]
    assert result.metadata == {"nested": {"labels": ["initial"]}}


def test_result_creation_has_no_world_or_event_side_effects():
    world_state = WorldState()
    event_history = EventHistory()
    before_world = (world_state.entities, world_state.facts)
    before_events = event_history.get_events()

    ResolutionResult(
        "resolution_001", "attempt_001", True, "no_change", confirmed=True
    )

    assert (world_state.entities, world_state.facts) == before_world
    assert event_history.get_events() == before_events
