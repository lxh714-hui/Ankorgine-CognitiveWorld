from cognitive_world.decision.resolution import Resolution


def test_resolution_can_be_created():
    resolution = Resolution(
        id="resolution_001",
        attempt_id="attempt_001",
        outcome="partial_success",
    )

    assert isinstance(resolution, Resolution)


def test_resolution_saves_attempt_id_and_arbitrary_effects_and_metadata():
    effects = [
        {"change": {"field": "condition", "value": ["updated"]}},
        "descriptive effect",
    ]
    metadata = {"review": {"source": "rules", "notes": ["recorded"]}}
    resolution = Resolution(
        id="resolution_001",
        attempt_id="attempt_001",
        outcome="custom_outcome",
        effects=effects,
        metadata=metadata,
    )

    assert resolution.attempt_id == "attempt_001"
    assert resolution.outcome == "custom_outcome"
    assert resolution.effects == effects
    assert resolution.metadata == metadata
