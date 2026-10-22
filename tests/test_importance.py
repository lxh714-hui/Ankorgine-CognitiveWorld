from cognitive_world.cognition import ImportanceScore


def test_importance_score_stores_fields_and_metadata():
    metadata = {"assessment": {"labels": ["manual"]}}
    score = ImportanceScore(
        target_id="short_001",
        score=0.72,
        reason="caller-provided evaluation",
        metadata=metadata,
    )

    assert score.target_id == "short_001"
    assert score.score == 0.72
    assert score.reason == "caller-provided evaluation"
    assert score.metadata == metadata
