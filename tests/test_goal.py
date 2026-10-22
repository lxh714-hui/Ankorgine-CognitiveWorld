import pytest

from cognitive_world.cognition import (
    BeliefStore,
    CognitiveUpdateApplier,
    CognitiveUpdateValidator,
    Goal,
    GoalChange,
    GoalStore,
    GoalUpdateProposal,
)


def test_goal_saves_fields_and_source_references():
    goal = Goal(
        goal_id="goal-a",
        owner_id="agent-a",
        description="Reach the objective",
        priority=0.85,
        status="active",
        source_refs=["belief-a", "event-a"],
        metadata={"extension": {"tags": ["important"]}},
    )

    assert goal.goal_id == "goal-a"
    assert goal.id == "goal-a"
    assert goal.owner_id == "agent-a"
    assert goal.description == "Reach the objective"
    assert goal.priority == 0.85
    assert goal.status == "active"
    assert goal.source_refs == ["belief-a", "event-a"]


def test_goal_store_isolates_agents_and_copies_data():
    store = GoalStore()
    source_refs = ["event-a"]
    metadata = {"nested": ["original"]}
    goal_a = Goal(
        "goal-a", "agent-a", "Goal A", 0.7, "active", source_refs, metadata
    )
    goal_b = Goal("goal-b", "agent-b", "Goal B", 0.4, "active")

    store.add(goal_a)
    store.add(goal_b)
    source_refs.append("event-external")
    metadata["nested"].append("external")

    owner_a_goals = store.get("agent-a")
    assert len(owner_a_goals) == 1
    assert owner_a_goals[0].source_refs == ["event-a"]
    assert owner_a_goals[0].metadata == {"nested": ["original"]}
    assert [goal.goal_id for goal in store.get("agent-b")] == ["goal-b"]
    assert store.get("unknown-agent") == ()

    owner_a_goals[0].source_refs.append("read-mutation")
    owner_a_goals[0].metadata["nested"].append("read-mutation")
    assert store.get("agent-a")[0].source_refs == ["event-a"]
    assert store.get("agent-a")[0].metadata == {"nested": ["original"]}


def test_goal_store_update_replaces_only_matching_owner_goal():
    store = GoalStore()
    store.add(Goal("goal-a", "agent-a", "Before", 0.2, "active"))
    store.add(Goal("goal-b", "agent-a", "Other", 0.5, "active"))
    store.add(Goal("goal-a", "agent-b", "Separate", 0.3, "active"))

    proposal = GoalUpdateProposal(
        owner_id="agent-a",
        goal_id="goal-a",
        change=GoalChange(
            "complete", "active", "completed", 0.2, 0.9, "test", ["event-a"]
        ),
        source_refs=["event-a"],
    )
    validation = CognitiveUpdateValidator().validate(
        proposal, {"agent_id": "agent-a"}
    )
    CognitiveUpdateApplier(BeliefStore(), store).apply(proposal, validation)

    assert {goal.goal_id: goal.description for goal in store.get("agent-a")} == {
        "goal-a": "Before",
        "goal-b": "Other",
    }
    assert store.get("agent-a")[0].status == "completed"
    assert store.get("agent-b")[0].description == "Separate"


def test_goal_storage_does_not_change_world_event_memory_or_belief_stores():
    goals = GoalStore()
    beliefs = BeliefStore()
    goals.add(Goal("goal-a", "agent-a", "Observe", 0.5, "active"))

    assert goals.get("agent-a")[0].description == "Observe"
    assert beliefs.get("agent-a") is None
    assert not hasattr(goals, "world_state")
    assert not hasattr(goals, "event_history")
    assert not hasattr(goals, "memory_store")


def test_goal_store_rejects_update_without_validated_proposal():
    goals = GoalStore()
    goals.add(Goal("goal-a", "agent-a", "Before", 0.2, "active"))

    with pytest.raises(PermissionError):
        goals.update(Goal("goal-a", "agent-a", "After", 0.9, "completed"))
