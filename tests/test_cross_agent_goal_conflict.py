"""Production Runtime slice for private, source-bound cross-Agent Goal findings."""

import pytest

from cognitive_world.cognition import GoalResourceDemand
from cognitive_world.cognition.goal_update import GoalUpdater
from cognitive_world.cognition.update_apply import CognitiveUpdateApplier
from cognitive_world.cognition.validation import CognitiveUpdateValidator
from cognitive_world.core.entity import Entity
from cognitive_world.core.world_state import WorldState
from cognitive_world.runtime.conflict_opportunity import ConflictOpportunityScheduler
from cognitive_world.runtime.conflict_opportunity import MAX_CROSS_AGENT_GOAL_PROJECTIONS
from test_autonomous_world_runner import _production_world


RESOURCE = "object:resource:archive-key"


def _demands(*, scope="window:morning", exclusive=True, resource=RESOURCE):
    return (GoalResourceDemand(resource, scope, exclusive),)


def _two_agent_runner(left, right, *, include_resource=True, registration_order=None):
    return _production_world(
        {
            "agent-a": ("goal-a", "private plan alpha"),
            "agent-b": ("goal-b", "private plan beta"),
        },
        resource_demands={"agent-a": left, "agent-b": right},
        include_claimed_resource=include_resource,
        registration_order=registration_order,
    )


def _findings_by_owner(runner):
    return {
        record.agent_id: record.scheduler_findings
        for record in runner.runtime.last_agent_turn_results
    }


def test_runtime_projects_supported_conflict_without_disclosing_partner_goal():
    runner, world, history, _ = _two_agent_runner(_demands(), _demands())
    before_entity_ids = set(world.entities)
    before_event_ids = tuple(event.id for event in history.get_events())
    before_goals = {
        owner: runner.runtime.cognition_context_provider(
            runner.runtime.context.agent_registry.get(owner)
        ).get_goals()
        for owner in ("agent-a", "agent-b")
    }

    runner.run_round()

    findings = _findings_by_owner(runner)
    assert set(findings) == {"agent-a", "agent-b"}
    for owner, other_goal in (("agent-a", "goal-b"), ("agent-b", "goal-a")):
        issue = next(item for item in findings[owner] if item.kind == "supported_conflict")
        assert issue.owner_id == owner
        assert issue.goal_ids == (("goal-a",) if owner == "agent-a" else ("goal-b",))
        assert issue.target_refs == (RESOURCE,)
        assert {item.reference_type for item in issue.source_refs} == {
            "goal", "goal_revision", "world_slot"
        }
        assert other_goal not in repr(issue)
        assert ("agent-b" if owner == "agent-a" else "agent-a") not in repr(issue)
        record = next(row for row in runner.runtime.last_agent_turn_results if row.agent_id == owner)
        assert record.execution and record.execution.proposal
        trace = record.execution.proposal.metadata["decision_trace"]
        linked = [row for row in trace if issue.finding_id in row["scheduler_finding_ids"]]
        assert linked
        assert all(dict(row["factors"])["scheduler_relevance"] > 0 for row in linked)
        assert record.event_tree_snapshot is not None
        assert any(
            issue.finding_id in branch.scheduler_finding_ids
            for branch in record.event_tree_snapshot.branches
        )

    # Discovery is attention/diagnostic only: no resource effect is committed.
    assert set(world.entities) == before_entity_ids
    assert tuple(event.id for event in history.get_events()) == before_event_ids
    assert world.environment["door:archive"].is_open is False
    assert {
        owner: runner.runtime.cognition_context_provider(
            runner.runtime.context.agent_registry.get(owner)
        ).get_goals()
        for owner in ("agent-a", "agent-b")
    } == before_goals


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (_demands(), _demands(scope="window:evening"), "potential_conflict"),
        (_demands(exclusive=False), _demands(exclusive=False), "shared_target_only"),
    ],
)
def test_same_resource_does_not_imply_supported_conflict(left, right, expected):
    runner, _world, _history, _ = _two_agent_runner(left, right)
    runner.run_round()
    findings = _findings_by_owner(runner)
    for owner in ("agent-a", "agent-b"):
        assert any(item.kind == expected for item in findings[owner])
        assert not any(item.kind == "supported_conflict" for item in findings[owner])


def test_free_text_and_unverified_resource_references_do_not_create_supported_conflict():
    text_only, *_ = _two_agent_runner((), ())
    text_only.run_round()
    assert all(not values for values in _findings_by_owner(text_only).values())

    missing, *_ = _two_agent_runner(_demands(), _demands(), include_resource=False)
    missing.run_round()
    assert all(not values for values in _findings_by_owner(missing).values())


def test_duplicate_goal_ids_are_resolved_through_owner_scoped_goal_store():
    runner, *_ = _production_world(
        {
            "agent-a": ("shared-goal-id", "private alpha"),
            "agent-b": ("shared-goal-id", "private beta"),
        },
        resource_demands={"agent-a": _demands(), "agent-b": _demands()},
    )
    runner.run_round()
    findings = _findings_by_owner(runner)
    for owner in ("agent-a", "agent-b"):
        assert any(item.kind == "supported_conflict" for item in findings[owner])
        assert all(item.goal_ids == ("shared-goal-id",) for item in findings[owner])

    context_b = runner.runtime.cognition_context_provider(
        runner.runtime.context.agent_registry.get("agent-b")
    )
    goal_b = context_b.get_goals()[0]
    before_a = runner.runtime.cognition_context_provider(
        runner.runtime.context.agent_registry.get("agent-a")
    ).get_goals()[0]
    with runner.runtime.write_fence.operation():
        proposal = GoalUpdater().propose_update(
            goal_b, {"new_state": "completed", "new_priority": 0.8,
                     "source_refs": ["trusted:goal-completion"]},
        )
        validation = CognitiveUpdateValidator().validate(
            proposal, {"agent_id": "agent-b"},
        )
        updated = CognitiveUpdateApplier(
            context_b.cognition_container.belief_store,
            context_b.cognition_container.goal_store,
            write_fence=runner.runtime.write_fence,
        ).apply(proposal, validation)
    assert updated.owner_id == "agent-b" and updated.goal_id == "shared-goal-id"
    assert updated.status == "completed" and updated.priority == 0.8
    assert updated.description == "private beta"
    assert runner.runtime.cognition_context_provider(
        runner.runtime.context.agent_registry.get("agent-a")
    ).get_goals()[0] == before_a
    assert context_b.get_goals()[0] == updated


def test_stale_resource_slot_receipt_is_not_accepted_by_runtime_scheduler_binding():
    runner, world, history, _ = _two_agent_runner(_demands(), _demands())
    runner.runtime._bind_cross_agent_goal_projection(0)
    stale = runner.runtime.conflict_opportunity_scheduler._cross_agent_goal_projections
    assert stale

    changed_world = WorldState()
    changed_world.load_entity(Entity("resource:archive-key", "replacement-resource"))
    runner.runtime.conflict_opportunity_scheduler.bind_cross_agent_goal_projections(
        stale,
        world_state=changed_world,
        event_history=history,
        simulation_tick=0,
    )
    assert runner.runtime.conflict_opportunity_scheduler._cross_agent_goal_projections == ()


def test_cross_agent_projection_budget_is_enforced_before_scheduler_acceptance():
    runner, world, history, _ = _two_agent_runner(_demands(), _demands())
    runner.runtime._bind_cross_agent_goal_projection(0)
    projection = runner.runtime.conflict_opportunity_scheduler._cross_agent_goal_projections[0]
    with pytest.raises(ValueError, match="over budget"):
        runner.runtime.conflict_opportunity_scheduler.bind_cross_agent_goal_projections(
            (projection,) * (MAX_CROSS_AGENT_GOAL_PROJECTIONS + 1),
            world_state=world,
            event_history=history,
            simulation_tick=0,
        )


def test_conflict_identity_is_deduplicated_and_independent_of_registration_order():
    first, *_ = _two_agent_runner(_demands(), _demands())
    second, *_ = _two_agent_runner(
        _demands(), _demands(), registration_order=("agent-b", "agent-a")
    )
    first.run_round()
    second.run_round()
    first_ids = {
        owner: next(item.finding_id for item in rows if item.kind == "supported_conflict")
        for owner, rows in _findings_by_owner(first).items()
    }
    second_ids = {
        owner: next(item.finding_id for item in rows if item.kind == "supported_conflict")
        for owner, rows in _findings_by_owner(second).items()
    }
    assert first_ids == second_ids

    first.run_round()
    repeated_ids = {
        owner: next(item.finding_id for item in rows if item.kind == "supported_conflict")
        for owner, rows in _findings_by_owner(first).items()
    }
    assert repeated_ids == first_ids
    for owner in ("agent-a", "agent-b"):
        tracked = first.runtime.conflict_opportunity_scheduler.tracked_for(owner)
        conflict = next(item for item in tracked if item.kind == "supported_conflict")
        assert conflict.sightings == 2


def test_goal_status_change_re_evaluates_and_dormants_prior_cross_agent_issue():
    runner, *_ = _two_agent_runner(_demands(), _demands())
    runner.run_round()
    previous = next(
        item for item in runner.runtime.conflict_opportunity_scheduler.tracked_for("agent-a")
        if item.kind == "supported_conflict"
    )

    agent = runner.runtime.context.agent_registry.get("agent-b")
    context = runner.runtime.cognition_context_provider(agent)
    goal = next(item for item in context.get_goals() if item.goal_id == "goal-b")
    with runner.runtime.write_fence.operation():
        proposal = GoalUpdater().propose_update(
            goal,
            {"new_state": "completed", "reason": "goal is no longer active",
             "source_refs": ["trusted:goal-completion"]},
        )
        validation = CognitiveUpdateValidator().validate(
            proposal, {"agent_id": "agent-b"}
        )
        applier = CognitiveUpdateApplier(
            context.cognition_container.belief_store,
            context.cognition_container.goal_store,
            write_fence=runner.runtime.write_fence,
        )
        applier.apply(proposal, validation)
    updated = context.cognition_container.goal_store.get_owned("agent-b", "goal-b")
    assert updated is not None and updated.resource_demands == _demands()

    runner.run_round()
    assert not any(
        item.kind == "supported_conflict"
        for item in runner.runtime.last_agent_turn_results[0].scheduler_findings
    )
    runner.run_round()
    dormant = next(
        item for item in runner.runtime.conflict_opportunity_scheduler.tracked_for("agent-a")
        if item.finding_id == previous.finding_id
    )
    assert dormant.lifecycle == "dormant"
    assert not any(
        item.kind == "supported_conflict"
        for item in runner.runtime.conflict_opportunity_scheduler.current_for(
            "agent-a", runner.runtime.context.clock.current_time
        )
    )


def test_goal_resource_reference_requires_explicit_object_namespace():
    with pytest.raises(ValueError):
        GoalResourceDemand("resource:archive-key", "window:morning", True)
    with pytest.raises(ValueError):
        GoalResourceDemand("agent:someone", "window:morning", True)
