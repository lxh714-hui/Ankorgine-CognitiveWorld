"""Deterministic limits for the transient NPC feedback mechanism."""

import pytest

from cognitive_world.decision.autonomous import SituationFact
from cognitive_world.decision.behavior_feedback import BehaviorFeedback


def _fact(source, value, predicate="door_locked"):
    return SituationFact(f"percept:{source}", f"event:{source}", "environment",
                         predicate, value, source)


def _failure(feedback, *, event_id, tick, facts=None, sources=None, owner="agent-a"):
    return feedback.record_failure(
        owner_id=owner, action_type="try door", target="door:archive",
        method="turn handle", facts=(_fact("door", "True"),) if facts is None else facts,
        source_refs=("percept:door",) if sources is None else sources,
        event_id=event_id, tick=tick,
    )


def _penalty(feedback, tick, *, facts=None, sources=None, owner="agent-a"):
    return feedback.penalty_for(
        owner_id=owner, action_type="try door", target="door:archive",
        method="turn handle", facts=(_fact("door", "True"),) if facts is None else facts,
        source_refs=("percept:door",) if sources is None else sources, tick=tick,
    )


def test_repeated_confirmed_failures_accumulate_without_double_consuming_event():
    feedback = BehaviorFeedback(half_life_ticks=8)
    assert _failure(feedback, event_id="event:1", tick=2)
    assert _penalty(feedback, 2) == pytest.approx(0.2)
    assert not _failure(feedback, event_id="event:1", tick=2)
    assert _failure(feedback, event_id="event:2", tick=2)
    assert _penalty(feedback, 2) == pytest.approx(0.4)
    assert len(feedback.history) == 2
    assert feedback.history[-1].consecutive_failures == 2
    assert _penalty(feedback, 10) == pytest.approx(0.2)
    assert _penalty(feedback, 10) == pytest.approx(0.2)
    assert feedback.history[-1].penalty == pytest.approx(0.4)
    assert feedback.frustration_for("agent-a", 2) == pytest.approx(0.12)
    assert feedback.frustration_for("agent-a", 6) == pytest.approx(0.06)


def test_relevant_observed_change_invalidates_current_penalty_but_preserves_history():
    feedback = BehaviorFeedback()
    assert _failure(feedback, event_id="event:1", tick=1)
    # A new authorized observation of the same predicate changes the target condition.
    new_facts = (_fact("door", "True"), _fact("door-new", "False"))
    assert _penalty(feedback, 2, facts=new_facts,
                    sources=("percept:door", "percept:door-new")) == 0
    # Unrelated facts do not change the scoped target condition.
    unrelated = (_fact("door", "True"), _fact("window", "Open", "window_open"))
    assert _penalty(feedback, 2, facts=unrelated, sources=("percept:door",)) > 0
    assert len(feedback.history) == 1


def test_owner_source_and_time_fail_closed():
    feedback = BehaviorFeedback()
    assert _failure(feedback, event_id="event:1", tick=3)
    assert _penalty(feedback, 3, owner="agent-b") == 0
    assert _penalty(feedback, 3, sources=()) == 0
    with pytest.raises(ValueError, match="time"):
        _penalty(feedback, 2)
    with pytest.raises(ValueError, match="time"):
        _penalty(feedback, None)
    with pytest.raises(ValueError, match="time"):
        _failure(feedback, event_id="event:2", tick=2)
