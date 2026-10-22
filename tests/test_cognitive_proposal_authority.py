"""Attack regressions for governed cognition candidate origin and validation reuse."""

from contextvars import copy_context
from dataclasses import replace
from threading import Event as ThreadEvent, Thread

import pytest

from cognitive_world.cognition import (
    Belief, BeliefChange, BeliefStore, BeliefUpdateProposal,
    CognitiveUpdateApplier, CognitiveUpdateValidator,
    Goal, GoalChange, GoalStore, GoalUpdateProposal,
)
from cognitive_world.cognition.container import CognitionContainer
from cognitive_world.cognition.emotion import Emotion
from cognitive_world.cognition.emotion_system import (
    EmotionProposal, EmotionUpdateApplier, EmotionUpdateValidator,
    _issue_emotion_update_context,
)
from cognitive_world.cognition.self_model import SelfModel, SelfModelStore
from cognitive_world.cognition.self_model_evolution import SelfModelUpdateProposal
from cognitive_world.runtime.write_fence import RuntimeWriteFence


def _setup():
    fence = RuntimeWriteFence("candidate-authority")
    beliefs, goals = BeliefStore(), GoalStore()
    applier = CognitiveUpdateApplier(beliefs, goals, write_fence=fence)
    with fence.operation():
        beliefs.add(Belief("belief-a", "agent-a", "old", ["obs-a"], 0.5))
        beliefs.add(Belief("belief-b", "agent-b", "old", ["obs-b"], 0.5))
        goals.add(Goal("goal-a", "agent-a", "go", 0.4, "active"))
    return fence, beliefs, goals, applier


def _belief(owner="agent-a", belief_id="belief-a", value="new"):
    return BeliefUpdateProposal(
        owner, belief_id, BeliefChange("replace", "old", value, "evidence", ["obs-a"]),
        ["obs-a"], 0.7,
    )


def _goal():
    return GoalUpdateProposal(
        "agent-a", "goal-a",
        GoalChange("update", "active", "completed", 0.4, 0.6, "evidence", ["obs-a"]),
        ["obs-a"],
    )


@pytest.mark.parametrize("kind", ["belief", "goal"])
def test_current_candidate_passes_validator_applier_and_final_store(kind):
    fence, beliefs, goals, applier = _setup()
    with fence.operation():
        proposal = _belief() if kind == "belief" else _goal()
        result = CognitiveUpdateValidator().validate(proposal, {"agent_id": "agent-a"})
        assert result.authorizes(proposal)
        applier.apply(proposal, result)
    if kind == "belief":
        assert beliefs.get_by_id("belief-a").content == "new"
    else:
        assert goals.get_owned("agent-a", "goal-a").status == "completed"
    assert fence.restore_generation == 0


@pytest.mark.parametrize("kind", ["belief", "goal"])
def test_old_candidate_cannot_rebind_permit_or_reuse_validation_at_store(kind):
    fence, beliefs, goals, applier = _setup()
    with fence.operation():
        proposal = _belief() if kind == "belief" else _goal()
        result = CognitiveUpdateValidator().validate(proposal, {"agent_id": "agent-a"})
    fence.freeze_and_advance()
    fence.unfreeze()
    with fence.operation() as fresh:
        with pytest.raises(PermissionError, match="rebind"):
            replace(proposal, runtime_write_permit=fresh)
        proposal.runtime_write_permit = fresh
        assert not result.authorizes(proposal)
        with pytest.raises(PermissionError):
            applier.apply(proposal, result)
        if kind == "belief":
            with pytest.raises(PermissionError):
                beliefs.update(Belief("belief-a", "agent-a", "new", ["obs-a"], 0.7),
                               proposal=proposal, validation_result=result)
        else:
            with pytest.raises(PermissionError):
                goals.update(Goal("goal-a", "agent-a", "go", 0.6, "completed", ["obs-a"]),
                             proposal=proposal, validation_result=result)
    assert beliefs.get_by_id("belief-a").content == "old"
    assert goals.get_owned("agent-a", "goal-a").status == "active"
    assert fence.restore_generation == 1


def test_validation_cannot_move_to_same_content_clone_other_owner_or_store():
    fence, beliefs, goals, applier = _setup()
    with fence.operation():
        proposal = _belief()
        result = CognitiveUpdateValidator().validate(proposal, {"agent_id": "agent-a"})
        clone = replace(proposal)
        other = _belief("agent-b", "belief-b")
        goal = _goal()
        assert not result.authorizes(clone)
        assert not result.authorizes(other)
        assert not result.authorizes(goal)
        assert not replace(result).authorizes(proposal)
        assert not replace(result, _proposal_snapshot=other).authorizes(other)
        for candidate in (clone, other, goal):
            with pytest.raises(PermissionError):
                applier.apply(candidate, result)
        with pytest.raises(PermissionError):
            goals.update(Goal("goal-a", "agent-a", "go", 0.6, "completed", ["obs-a"]),
                         proposal=goal, validation_result=result)
    assert beliefs.get_by_id("belief-a").content == "old"
    assert beliefs.get_by_id("belief-b").content == "old"
    assert goals.get_owned("agent-a", "goal-a").status == "active"


def test_mutating_validated_content_invalidates_result_even_at_final_store():
    fence, beliefs, _, applier = _setup()
    with fence.operation():
        proposal = _belief()
        result = CognitiveUpdateValidator().validate(proposal, {"agent_id": "agent-a"})
        proposal.change.proposed_value = "tampered"
        result._proposal_snapshot.change.proposed_value = "tampered"
        assert not result.authorizes(proposal)
        with pytest.raises(PermissionError):
            applier.apply(proposal, result)
        with pytest.raises(PermissionError):
            beliefs.update(Belief("belief-a", "agent-a", "tampered", ["obs-a"], 0.7),
                           proposal=proposal, validation_result=result)
    assert beliefs.get_by_id("belief-a").content == "old"


def test_freeze_competing_with_late_cognition_apply_keeps_old_candidate_out():
    fence, beliefs, _, applier = _setup()
    ready, release = ThreadEvent(), ThreadEvent()
    with fence.operation():
        proposal = _belief()
        result = CognitiveUpdateValidator().validate(proposal, {"agent_id": "agent-a"})
        operation_context = copy_context()
    failures = []

    def delayed_apply():
        ready.set()
        assert release.wait(2)
        try:
            operation_context.run(applier.apply, proposal, result)
        except PermissionError as error:
            failures.append(error)

    worker = Thread(target=delayed_apply)
    worker.start()
    assert ready.wait(2)
    fence.freeze_and_advance()
    fence.unfreeze()
    release.set()
    worker.join(2)
    assert not worker.is_alive()
    assert len(failures) == 1
    assert beliefs.get_by_id("belief-a").content == "old"


def test_self_model_candidate_cannot_rebind_after_generation_change():
    fence = RuntimeWriteFence("self-model-origin")
    store = SelfModelStore()
    applier = CognitiveUpdateApplier(BeliefStore(), GoalStore(), store, write_fence=fence)
    with fence.operation():
        store.add(SelfModel("agent-a", self_beliefs=[]))
        proposal = SelfModelUpdateProposal(
            "agent-a", (), "tentative claim", ("obs-a",), ("event-a",),
        )
        result = CognitiveUpdateValidator().validate(proposal, {
            "agent_id": "agent-a", "authorized_source_refs": ("obs-a",),
            "authorized_event_ids": ("event-a",),
            "authorized_source_event_pairs": {"obs-a": "event-a"},
        })
        assert result.authorizes(proposal)
    fence.freeze_and_advance()
    fence.unfreeze()
    with fence.operation() as fresh:
        with pytest.raises(PermissionError, match="rebind"):
            replace(proposal, runtime_write_permit=fresh)
        object.__setattr__(proposal, "runtime_write_permit", fresh)
        with pytest.raises(PermissionError):
            applier.apply(proposal, result)
    assert store.get("agent-a").self_beliefs == []


def test_emotion_candidate_and_decision_cannot_rebind_at_final_store():
    fence = RuntimeWriteFence("emotion-origin")
    cognition = CognitionContainer()
    cognition.bind_write_fence(fence)
    with fence.operation():
        cognition.add_emotion(Emotion("emotion-a", "agent-a"))
        proposal = EmotionProposal(
            "agent-a", "emotion-a", (), (("fear", 0.5),), None, 1,
            ("obs-a",), ("event-a",), processed_sources=("event-a",),
        )
        decision = EmotionUpdateValidator().validate(
            proposal, _issue_emotion_update_context(
                "agent-a", ("obs-a",), ("event-a",), 1,
                allow_clock_only=False,
            ),
        )
        assert decision.authorizes(proposal)
        assert not replace(decision).authorizes(proposal)
        object.__setattr__(decision, "_proposal", replace(proposal))
        assert decision.authorizes(proposal)
    fence.freeze_and_advance()
    fence.unfreeze()
    with fence.operation() as fresh:
        with pytest.raises(PermissionError, match="rebind"):
            replace(proposal, runtime_write_permit=fresh)
        object.__setattr__(proposal, "runtime_write_permit", fresh)
        assert not decision.authorizes(proposal)
        with pytest.raises(PermissionError):
            EmotionUpdateApplier(cognition, write_fence=fence).apply(
                proposal, decision, simulation_tick=1,
            )
        with pytest.raises(PermissionError):
            cognition.apply_emotion_update(
                Emotion("emotion-a", "agent-a", levels={"fear": 0.5},
                        last_update_tick=1, processed_sources=("event-a",)),
                proposal, decision, simulation_tick=1,
            )
    assert cognition.get_emotion("emotion-a").snapshot_levels() == ()
