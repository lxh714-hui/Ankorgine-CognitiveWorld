from copy import deepcopy

import pytest

from cognitive_world.agent import AgentTurn, Character, CognitionContext, RuntimeAgent
from cognitive_world.cognition import (
    Belief,
    BeliefChange,
    BeliefStore,
    BeliefUpdateProposal,
    CognitionContainer,
    CognitiveEvolutionEngine,
    CognitiveUpdateApplier,
    CognitiveUpdateValidator,
    Goal,
    GoalChange,
    GoalStore,
    GoalUpdateProposal,
    MemoryStore,
    ValidationResult,
)
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.history import EventHistory
from cognitive_world.observation import Observation, ObservationStore
from tests._trusted_event_support import make_system_event
from tests._trusted_observation_support import make_trusted_observation


def test_validated_belief_and_goal_proposals_are_applied_to_authoritative_stores():
    beliefs = BeliefStore()
    goals = GoalStore()
    beliefs.add(Belief("belief-1", "agent-1", {"claim": "old"}, ["old"], 0.4))
    goals.add(Goal("goal-1", "agent-1", "Reach station", 0.4, "active"))
    belief_proposal = BeliefUpdateProposal(
        owner_id="agent-1",
        belief_id="belief-1",
        change=BeliefChange(
            "replace", {"claim": "old"}, {"claim": "new"}, "evidence", ["obs-1"]
        ),
        source_refs=["obs-1"],
        confidence=0.8,
    )
    goal_proposal = GoalUpdateProposal(
        owner_id="agent-1",
        goal_id="goal-1",
        change=GoalChange(
            "complete", "active", "completed", 0.4, 0.9, "evidence", ["obs-1"]
        ),
        source_refs=["obs-1"],
    )
    validator = CognitiveUpdateValidator()
    applier = CognitiveUpdateApplier(beliefs, goals)

    updated_belief = applier.apply(
        belief_proposal, validator.validate(belief_proposal, {"agent_id": "agent-1"})
    )
    updated_goal = applier.apply(
        goal_proposal, validator.validate(goal_proposal, {"agent_id": "agent-1"})
    )

    assert updated_belief.content == {"claim": "new"}
    assert beliefs.get_by_id("belief-1") == updated_belief
    assert updated_goal.status == "completed"
    assert updated_goal.priority == 0.9
    assert goals.get_by_id("goal-1") == updated_goal


def test_same_goal_id_update_returns_the_correct_owner_record():
    goals = GoalStore()
    goals.add(Goal("shared-goal", "agent-a", "A private aim", 0.2, "active"))
    goals.add(Goal("shared-goal", "agent-b", "B private aim", 0.6, "active"))
    before_a = goals.get_owned("agent-a", "shared-goal")
    proposal = GoalUpdateProposal(
        owner_id="agent-b", goal_id="shared-goal",
        change=GoalChange("progress", "active", "completed", 0.6, 0.9,
                          "observed", ["obs-b"]),
        source_refs=["obs-b"],
    )
    validation = CognitiveUpdateValidator().validate(
        proposal, {"agent_id": "agent-b", "authorized_source_refs": ("obs-b",)},
    )

    result = CognitiveUpdateApplier(BeliefStore(), goals).apply(proposal, validation)

    assert goals.get_owned("agent-a", "shared-goal") == before_a
    assert goals.get_owned("agent-b", "shared-goal").status == "completed"
    assert result == goals.get_owned("agent-b", "shared-goal")
    assert (result.owner_id, result.goal_id, result.description, result.priority) == (
        "agent-b", "shared-goal", "B private aim", 0.9,
    )


def test_same_goal_id_remains_owner_scoped_in_cognition_and_decision_contexts():
    cognition = CognitionContainer()
    cognition.add_goal(Goal("shared-goal", "agent-a", "A private aim", 0.2, "active"))
    cognition.add_goal(Goal("shared-goal", "agent-b", "B private aim", 0.6, "active"))
    memory = MemoryStore()
    contexts = {
        owner: CognitionContext.from_character(
            Character(f"character-{owner}", owner, "", goal_ids=["shared-goal"]),
            cognition, memory,
        )
        for owner in ("agent-a", "agent-b")
    }
    for owner in ("agent-a", "agent-b"):
        goal = contexts[owner].get_goals()[0]
        assert goal.owner_id == owner
        assert goal.description == ("A private aim" if owner == "agent-a" else "B private aim")
        decision, _ = AgentTurn().prepare_decision_context(
            RuntimeAgent(owner, f"character-{owner}"), contexts[owner],
        )
        assert tuple(item.owner_id for item in decision.goals) == (owner,)
        assert decision.goals[0].description == goal.description

    proposal = GoalUpdateProposal(
        "agent-b", "shared-goal",
        GoalChange("progress", "active", "completed", 0.6, 0.8,
                   "observed", ["obs-b"]),
        ["obs-b"],
    )
    validation = CognitiveUpdateValidator().validate(
        proposal, {"agent_id": "agent-b", "authorized_source_refs": ("obs-b",)},
    )
    CognitiveUpdateApplier(cognition.belief_store, cognition.goal_store).apply(
        proposal, validation,
    )
    assert contexts["agent-a"].get_goals()[0].status == "active"
    assert contexts["agent-b"].get_goals()[0].status == "completed"
    decision_b, _ = AgentTurn().prepare_decision_context(
        RuntimeAgent("agent-b", "character-agent-b"), contexts["agent-b"],
    )
    assert decision_b.goals[0].owner_id == "agent-b"
    assert decision_b.goals[0].priority == 0.8
    assert "A private aim" not in repr(decision_b)


def test_shared_goal_id_requires_owner_for_ambiguous_compatibility_reads():
    cognition = CognitionContainer()
    cognition.add_goal(Goal("shared-goal", "agent-a", "A private aim", 0.2, "active"))
    cognition.add_goal(Goal("shared-goal", "agent-b", "B private aim", 0.6, "active"))
    assert cognition.get_goal("missing", owner_id="agent-b") is None
    assert cognition.goal_store.get_owned("other-agent", "shared-goal") is None
    assert cognition.get_goal("shared-goal", owner_id="agent-b").description == "B private aim"
    with pytest.raises(ValueError, match="owner"):
        cognition.goal_store.get_by_id("shared-goal")
    with pytest.raises(ValueError, match="owner"):
        cognition.get_goal("shared-goal")
    with pytest.raises(ValueError, match="owner"):
        _ = cognition.goals


def test_shared_goal_id_rejects_cross_owner_proposal_and_validation_reuse():
    goals = GoalStore()
    goals.add(Goal("shared-goal", "agent-a", "A private aim", 0.2, "active"))
    goals.add(Goal("shared-goal", "agent-b", "B private aim", 0.6, "active"))
    a_before = goals.get_owned("agent-a", "shared-goal")
    b_before = goals.get_owned("agent-b", "shared-goal")
    a_proposal = GoalUpdateProposal(
        "agent-a", "shared-goal",
        GoalChange("progress", "active", "completed", 0.2, 0.5,
                   "observed", ["obs-a"]), ["obs-a"],
    )
    b_proposal = GoalUpdateProposal(
        "agent-b", "shared-goal",
        GoalChange("progress", "active", "completed", 0.6, 0.8,
                   "observed", ["obs-b"]), ["obs-b"],
    )
    validator = CognitiveUpdateValidator()
    a_validation = validator.validate(a_proposal, {"agent_id": "agent-a"})
    rejected_for_b = validator.validate(a_proposal, {"agent_id": "agent-b"})
    applier = CognitiveUpdateApplier(BeliefStore(), goals)
    with pytest.raises(PermissionError):
        applier.apply(a_proposal, rejected_for_b)
    with pytest.raises(PermissionError):
        applier.apply(b_proposal, a_validation)
    with pytest.raises(ValueError, match="validated proposal"):
        goals.update(
            Goal("shared-goal", "agent-b", "B private aim", 0.8, "completed", ["obs-b"]),
            proposal=a_proposal, validation_result=a_validation,
        )
    assert goals.get_owned("agent-a", "shared-goal") == a_before
    assert goals.get_owned("agent-b", "shared-goal") == b_before


def test_rejected_or_unbound_validation_cannot_apply_or_update_store():
    beliefs = BeliefStore()
    goals = GoalStore()
    belief = Belief("belief-1", "agent-1", "old", ["source"], 0.5)
    beliefs.add(belief)
    proposal = BeliefUpdateProposal(
        owner_id="agent-1",
        belief_id="belief-1",
        change=BeliefChange("replace", "old", "new", "test", ["source"]),
        source_refs=["source"],
    )
    applier = CognitiveUpdateApplier(beliefs, goals)
    rejected = CognitiveUpdateValidator().validate(proposal, {"agent_id": "other"})

    with pytest.raises(PermissionError):
        applier.apply(proposal, rejected)
    with pytest.raises(PermissionError):
        applier.apply(proposal, ValidationResult(True, "manually accepted"))
    with pytest.raises(PermissionError):
        beliefs.update(Belief("belief-1", "agent-1", "new"))
    with pytest.raises(ValueError, match="validated update"):
        beliefs.add(Belief("belief-1", "agent-1", "new"))

    assert beliefs.get_by_id("belief-1") == belief


def test_store_rejects_stale_proposal_even_when_validation_was_accepted():
    beliefs = BeliefStore()
    goals = GoalStore()
    beliefs.add(Belief("belief-1", "agent-1", "old", ["source"], 0.5))
    proposal = BeliefUpdateProposal(
        owner_id="agent-1",
        belief_id="belief-1",
        change=BeliefChange(
            "replace", "old", "changed elsewhere", "test", ["source"]
        ),
        source_refs=["source"],
    )
    validation = CognitiveUpdateValidator().validate(
        proposal, {"agent_id": "agent-1"}
    )
    beliefs.update(
        Belief("belief-1", "agent-1", "changed elsewhere", ["source"], 0.0),
        proposal=proposal,
        validation_result=validation,
    )

    with pytest.raises(ValueError, match="changed since"):
        CognitiveUpdateApplier(beliefs, goals).apply(proposal, validation)


def test_evolution_only_proposes_and_has_no_world_or_event_side_effects():
    cognition = CognitionContainer()
    belief = Belief("belief-1", "agent-1", {"claim": "old"}, ["event-old"], 0.5)
    goal = Goal("goal-1", "agent-1", "Explore", 0.5, "active", ["event-old"])
    cognition.add_belief(belief)
    cognition.add_goal(goal)
    character = Character(
        id="character-1",
        agent_id="agent-1",
        personality_id="personality-1",
        belief_ids=[belief.belief_id],
        goal_ids=[goal.goal_id],
    )
    observation_store = ObservationStore()
    context = CognitionContext.from_character(
        character, cognition, MemoryStore(), observation_store=observation_store
    )
    before_belief = cognition.get_belief(belief.belief_id)
    before_goal = cognition.get_goal(goal.goal_id)
    world_state = WorldState()
    world_state.load_fact("existing", {"value": 1})
    facts_before = world_state.facts
    history = EventHistory()
    history.append(Event("prior", "fact", "t0"))
    history_before = history.get_events()
    event = make_system_event("event-1", "fact", changes=[{"value": 2}])
    observation_store.add(
        make_trusted_observation("observation-1", "agent-1", event.id, {"value": 2})
    )
    event_before = deepcopy(event)

    result = CognitiveEvolutionEngine().process(event, context)

    assert result.belief_update_proposals
    assert result.goal_update_proposals
    assert cognition.get_belief(belief.belief_id) == before_belief
    assert cognition.get_goal(goal.goal_id) == before_goal
    assert world_state.facts == facts_before
    assert history.get_events() == history_before
    assert event == event_before
