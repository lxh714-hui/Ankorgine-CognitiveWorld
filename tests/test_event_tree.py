"""Tests for the bounded, candidate-only Event Tree runtime slice."""

from dataclasses import replace

import pytest

from cognitive_world.decision import (
    ActionCandidate,
    ActionProposal,
    EventTreeExplorer,
)
from test_autonomous_world_runner import _production_world


def _proposal(*, selected="candidate-a"):
    trace = (
        {
            "candidate_id": "candidate-a",
            "goal_id": "goal-a",
            "intent": "inspect the mechanism",
            "target": "object:mechanism",
            "method": "look for a visible control",
            "source_refs": ("percept:owner", "event:owner"),
            "score": 0.8,
            "factors": (("goal_alignment", 0.5),),
            "uncertainty": ("the internal state is not observed",),
        },
        {
            "candidate_id": "candidate-b",
            "goal_id": "goal-a",
            "intent": "ask about the mechanism",
            "target": "object:mechanism",
            "method": "ask a nearby person",
            "source_refs": ("percept:owner",),
            "score": 0.4,
            "factors": (("information_gain", 0.2),),
            "uncertainty": (),
        },
    )
    return ActionProposal(
        proposal_id="proposal:owner:1",
        agent_id="owner",
        action_type="inspect",
        metadata={"selected_candidate_id": selected, "decision_trace": trace},
    )


def _candidate(candidate_id, *, target="object:mechanism", refs=("percept:owner",)):
    return ActionCandidate(
        candidate_id=candidate_id,
        owner_id="owner",
        goal_id="goal-a",
        intent="check another possible approach",
        target=target,
        method="use a newly described but unassessed method",
        tools=(),
        required_capabilities=(),
        preconditions=(),
        steps=(),
        expected_result="learn whether the method is viable",
        uncertainties=("causal support has not been evaluated",),
        estimated_risk=None,
        estimated_cost=None,
        commitment=0.1,
        source_refs=refs,
        strategy="fake-provider-contract-test",
    )


def test_runtime_records_tree_from_real_decision_proposal_and_keeps_authority_chain():
    runner, world, history, _observations = _production_world({
        "agent-a": ("goal-open", "open the archive door"),
    })

    report = runner.run(1)

    record = runner.runtime.last_agent_turn_results[0]
    assert record.execution is not None
    assert record.event_tree_failure_type is None
    tree = record.event_tree_snapshot
    assert tree is not None
    proposal = record.execution.proposal
    trace = proposal.metadata["decision_trace"]
    assert tree.owner_id == proposal.agent_id == "agent-a"
    assert tree.source_proposal_id == proposal.proposal_id
    assert tree.simulation_tick is not None
    assert tree.semantics == "candidate_exploration_only"
    assert len(tree.branches) <= tree.branch_budget
    assert all(branch.parent_id == tree.root_id for branch in tree.branches)
    assert {branch.candidate_id for branch in tree.branches}.issubset(
        {item["candidate_id"] for item in trace}
    )
    assert all(branch.candidate_source for branch in tree.branches)
    assert any(branch.selected_by_decision for branch in tree.branches)
    assert report.rounds[0].agent_actions[0].status == "success"
    assert world.environment["door:archive"].is_open is True
    assert any(event.has_trusted_source("resolution") for event in history.get_events())


def test_expansion_is_lazy_bounded_and_prunes_unexpanded_candidates():
    explorer = EventTreeExplorer.from_proposal(_proposal(), branch_budget=1)
    before = explorer.snapshot()
    assert before.branches == ()
    assert before.pending_candidate_count == 2

    expanded = explorer.expand(1)
    snapshot = explorer.snapshot()
    assert len(expanded) == 1
    assert expanded[0].parent_id == snapshot.root_id
    assert expanded[0].candidate_id == "candidate-a"
    assert snapshot.pending_candidate_count == 0
    assert snapshot.pruned_candidate_ids == ("candidate-b",)
    assert snapshot.pruning[0].parent_id == snapshot.root_id
    assert snapshot.pruning[0].reason == "global_branch_budget"
    assert explorer.expand(1) == ()


def test_fake_branch_provider_is_bounded_and_cannot_add_authority_or_world_effects():
    class FakeProvider:
        def __init__(self, proposals):
            self.proposals = proposals

        def propose_branches(self, context):
            assert context.owner_id == "owner"
            assert context.remaining_branch_budget == 2
            return self.proposals

    explorer = EventTreeExplorer.from_proposal(_proposal(), branch_budget=3)
    parent = explorer.expand(1)[0]
    added = explorer.expand_with_provider(
        parent.node_id, FakeProvider((_candidate("candidate-c"),))
    )
    branch = added[0]
    assert branch.parent_id == parent.node_id
    assert branch.assessed is False
    assert branch.subjective_score is None
    assert branch.selected_by_decision is False
    assert branch.source_refs == ("percept:owner",)
    assert branch.candidate_source == "fake-provider-contract-test"

    bad = EventTreeExplorer.from_proposal(_proposal(), branch_budget=3)
    bad_parent = bad.expand(1)[0]
    with pytest.raises(PermissionError):
        bad.expand_with_provider(
            bad_parent.node_id,
            FakeProvider((_candidate("candidate-c", refs=("private:other-agent",)),)),
        )


def test_tree_exploration_does_not_write_world_history_observations_or_cognition():
    runner, world, history, observations = _production_world({
        "agent-a": ("goal-open", "open the archive door"),
    })
    runner.run(1)
    record = runner.runtime.last_agent_turn_results[0]
    proposal = record.execution.proposal
    cognition_runtime = runner.runtime.agent_action_loop.agent_turn.cognitive_runtime
    memory_before = cognition_runtime.working_memory_store.get("agent-a")
    world_before = dict(world.environment)
    history_before = tuple(event.id for event in history.get_events())
    observations_before = tuple(
        item.observation_id for item in observations.get_by_observer("agent-a")
    )

    explorer = EventTreeExplorer.from_proposal(proposal)
    explorer.expand(2)
    snapshot = explorer.snapshot()

    assert snapshot.branches
    assert dict(world.environment) == world_before
    assert tuple(event.id for event in history.get_events()) == history_before
    assert tuple(
        item.observation_id for item in observations.get_by_observer("agent-a")
    ) == observations_before
    assert cognition_runtime.working_memory_store.get("agent-a") == memory_before


def test_malformed_trace_and_unselected_claims_are_rejected_or_unselected():
    with pytest.raises(ValueError):
        EventTreeExplorer.from_proposal(_proposal(selected="not-in-trace"))

    malformed = ActionProposal(
        proposal_id="proposal:owner:bad",
        agent_id="owner",
        action_type="attempt",
        metadata={"decision_trace": ({"candidate_id": "bad", "score": float("nan")},)},
    )
    with pytest.raises(ValueError):
        EventTreeExplorer.from_proposal(malformed)


def test_provider_expansion_is_single_use_per_parent_and_records_duplicate_basis():
    class Provider:
        calls = 0

        def propose_branches(self, context):
            self.calls += 1
            return (_candidate("fresh"), _candidate("same-meaning"))

    explorer = EventTreeExplorer.from_proposal(_proposal(), branch_budget=4, simulation_tick=7)
    parent = explorer.expand(1)[0]
    provider = Provider()
    added = explorer.expand_with_provider(parent.node_id, provider)
    assert len(added) == 1
    assert explorer.expand_with_provider(parent.node_id, provider) == ()
    snapshot = explorer.snapshot()
    assert provider.calls == snapshot.provider_calls_used == 1
    assert snapshot.branches[0].expansion_status == "expanded"
    assert added[0].assessed is False and added[0].subjective_score is None
    assert snapshot.pruning[-1].candidate_id == "same-meaning"
    assert snapshot.pruning[-1].reason == "duplicate_candidate"
    assert snapshot.simulation_tick == 7


def test_provider_limits_calls_and_children_without_repeating_model_work():
    class Provider:
        calls = 0

        def propose_branches(self, context):
            self.calls += 1
            return (_candidate(f"new-{self.calls}"),)

    explorer = EventTreeExplorer.from_proposal(
        _proposal(), branch_budget=4, provider_call_budget=1,
    )
    first, second = explorer.expand(2)
    provider = Provider()
    assert explorer.expand_with_provider(first.node_id, provider)
    assert explorer.expand_with_provider(second.node_id, provider) == ()
    assert provider.calls == 1
    assert explorer.snapshot().branches[1].expansion_reason == "provider_call_budget"


def test_semantic_dedup_preserves_distinct_tools_and_preconditions():
    class Provider:
        def propose_branches(self, context):
            return (
                _candidate("approach-a"),
                replace(_candidate("approach-b"), tools=("object:owned-tool",)),
            )

    explorer = EventTreeExplorer.from_proposal(_proposal(), branch_budget=4)
    parent = explorer.expand(1)[0]
    added = explorer.expand_with_provider(parent.node_id, Provider())
    assert {branch.candidate_id for branch in added} == {"approach-a", "approach-b"}


def test_invalid_provider_batch_is_atomic_and_cannot_broaden_owner_evidence():
    class Provider:
        def propose_branches(self, context):
            return (
                _candidate("valid"),
                replace(_candidate("foreign"), owner_id="someone-else"),
            )

    explorer = EventTreeExplorer.from_proposal(_proposal(), branch_budget=4)
    parent = explorer.expand(1)[0]
    with pytest.raises(PermissionError):
        explorer.expand_with_provider(parent.node_id, Provider())
    snapshot = explorer.snapshot()
    assert len(snapshot.branches) == 1
    assert snapshot.branches[0].expansion_status == "blocked"
    assert snapshot.provider_calls_used == 1
    assert explorer.expand_with_provider(parent.node_id, Provider()) == ()


def test_provider_failure_is_diagnostic_and_never_materializes_hypotheses():
    class BrokenProvider:
        def propose_branches(self, context):
            raise RuntimeError("unavailable")

    explorer = EventTreeExplorer.from_proposal(_proposal(), branch_budget=4)
    parent = explorer.expand(1)[0]
    with pytest.raises(RuntimeError):
        explorer.expand_with_provider(parent.node_id, BrokenProvider())
    snapshot = explorer.snapshot()
    assert len(snapshot.branches) == 1
    assert snapshot.branches[0].expansion_reason == "provider_error"
    assert snapshot.provider_calls_used == 1
    assert snapshot.semantics == "candidate_exploration_only"


def test_runtime_bound_scheduler_links_require_current_issued_finding_ids():
    metadata = _proposal().metadata
    trace = list(metadata["decision_trace"])
    trace[0] = {**trace[0], "scheduler_finding_ids": ("scheduler-finding:foreign",)}
    metadata["decision_trace"] = tuple(trace)
    proposal = ActionProposal(
        proposal_id="proposal:owner:linked", agent_id="owner",
        action_type="inspect", metadata=metadata,
    )
    with pytest.raises(PermissionError):
        EventTreeExplorer.from_proposal(proposal, scheduler_finding_ids=())
    tree = EventTreeExplorer.from_proposal(
        proposal, scheduler_finding_ids=("scheduler-finding:foreign",),
    ).snapshot()
    assert tree.owner_id == "owner"
    assert tree.branches == ()
