"""Real L1 -> existing candidate/evaluation/review -> independently governed Inspect."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from cognitive_world.agent import AgentActionLoop, AgentTurn, Character, CognitionContext, RuntimeAgent
from cognitive_world.agent.inspection import AutonomousInspectionService
from cognitive_world.cognition import CognitionContainer, Goal, MemoryStore
from cognitive_world.cognition.perception import Percept
from cognitive_world.core.object_appearance import ObjectAppearance
from cognitive_world.decision import AgentDecision
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.decision.autonomous import CandidateEvaluation, DeterministicActionEvaluationPolicy
from cognitive_world.decision.context import DecisionContext
from cognitive_world.decision.inspection import InspectionCandidatePolicy
from cognitive_world.event.factory import SystemEventFactory
from test_container_inspection import scene, consumer


def setup(*, targets=("bag",), provider=None, goal=True):
    w, p, relationship, authority = scene()
    for target in targets:
        entity = w.get_entity(target)
        w.load_entity(replace(entity, attributes={**entity.attributes,
            "appearance": ObjectAppearance(1, "box", "plain", True, True)}))
    w.load_environment_data("room", {"light_on": True})
    cognition, memory = CognitionContainer(), MemoryStore()
    if goal: cognition.add_goal(Goal("inspect-goal", "a", "inspect bag", 0.9, "active"))
    ctx = CognitionContext.from_character(Character("a", "a", "", goal_ids=["inspect-goal"] if goal else []),
        cognition, memory, observation_store=p.observation_store)
    core = consumer(p)
    turn = AgentTurn(cognitive_runtime=core, write_fence=p.write_fence)
    service = AutonomousInspectionService(p, core, InspectionCandidatePolicy(provider))
    loop = AgentActionLoop(agent_turn=turn, write_fence=p.write_fence, inspection_service=service)
    return w, p, authority, relationship, cognition, memory, ctx, core, turn, service, loop


def exterior(p, target="bag", owner="a", ident=None):
    event = SystemEventFactory().create(event_id=ident or "exterior:" + target, event_type="object_observed",
        timestamp="", simulation_tick=p.simulation_clock.current_time, participants=[owner],
        changes=[{"entity_id": target, "observer_id": owner, "precision": "coarse"}])
    p.dispatch_with_evidence(event)
    return next(o for o in p.observation_store.get_by_observer(owner) if o.source_event_id == event.id)


def run(p, loop, ctx, decision=None):
    return loop.run_turn_with_result(RuntimeAgent("a"), ctx, decision or AgentDecision(),
                                     simulation_tick=p.simulation_clock.capture())


def test_real_turn_observes_selects_authorizes_delivers_then_next_turn_consumes():
    w, p, _, _, cognition, memory, ctx, core, turn, service, loop = setup()
    before = deepcopy((dict(w.entities), dict(w.locations), dict(w.relationships)))
    with p.write_fence.operation():
        source = exterior(p)
        assert not core.has_consumed_observation("a", source, source_event_id=source.source_event_id)
        execution = run(p, loop, ctx)
        assert execution.inspection_result.status == "authorized"
        assert execution.attempt is None and execution.resolution is None
        assert execution.event.type == "container_inspected"
        assert core.has_consumed_observation("a", source, source_event_id=source.source_event_id)
        assert not any(o.content.fact_type == "container_content" for o in p.observation_store.all())
        assert not p.event_history.get_event(execution.event.id)
        p.dispatch_with_evidence(execution.event)
        result, = [o for o in p.observation_store.get_by_observer("a") if o.content.fact_type == "container_content"]
        assert not core.has_consumed_observation("a", result, source_event_id=result.source_event_id)
        assert not p.observation_store.get_by_observer("other")
        assert service.prepare_selected(RuntimeAgent("a"), execution.proposal).event is execution.event
        p.dispatch_with_evidence(execution.event)
        exhausted = run(p, loop, ctx)
        assert exhausted.event is None and exhausted.inspection_result.code == "turn_budget_exhausted"
    with p.write_fence.operation():
        decision, _ = turn.prepare_decision_context(RuntimeAgent("a"), ctx, simulation_tick=p.simulation_clock.capture())
        assert core.has_consumed_observation("a", result, source_event_id=result.source_event_id)
        assert any(percept.source_observation_id == result.observation_id for percept in decision.percepts)
    assert (w.entities, w.locations, w.relationships) == before
    assert not memory.get_all_memories() and not cognition.beliefs
    assert len(p.event_history.get_events()) == 2


@pytest.mark.parametrize("defect", ["unconsumed", "fake_id", "other_actor", "source_percept", "container", "memory_only"])
def test_unconsumed_forged_or_memory_only_source_never_qualifies(defect, monkeypatch):
    _, p, _, _, _, _, ctx, core, turn, service, loop = setup()
    with p.write_fence.operation():
        source = exterior(p)
        if defect not in {"unconsumed", "memory_only"}: core.process("a", [source])
        fact = source.content
        if defect == "container": fact = replace(fact, subject_ref="bottle")
        percept = Percept("percept:" + source.observation_id, "a", source.observation_id, fact)
        if defect == "fake_id": percept.source_observation_id = "fake"
        elif defect == "other_actor":
            # The frozen owner check alone is not authority; same-owner copies of another fact still fail.
            percept.content = replace(fact, source_event_id="other:event")
        elif defect == "source_percept": percept.percept_id = "substituted"
        from cognitive_world.cognition.memory import Memory
        memories = (Memory("retrieved-bag", "a", "episodic", {"container": "bag"}, 0.5, source.source_event_id),)
        decision = DecisionContext(type(core.process("a", []))("a"),
                                   percepts=() if defect == "memory_only" else (percept,),
                                   long_term_memories=memories if defect == "memory_only" else ())
        monkeypatch.setattr(turn, "prepare_decision_context", lambda *a, **k: (decision, None))
        result = run(p, loop, ctx)
        assert result.event is None and result.inspection_result.code == "no_qualified_percepts"
    assert len(p.event_history.get_events()) == 1


class Provider:
    def __init__(self, payload): self.payload, self.calls = payload, 0
    def generate_candidates(self, situation, **limits):
        self.calls += 1
        assert limits["max_candidates"] == 5
        assert not hasattr(situation, "world_state")
        return self.payload


def payload(**changes):
    row = {"intent": "Inspect", "target": "bag", "method": "inspect bag", "goal_id": "inspect-goal"}
    row.update(changes)
    return json.dumps({"candidates": [row]})


@pytest.mark.parametrize("change", [{"authorized": True}, {"actor": "other"}, {"source_refs": ["fake"]},
    {"target": "bottle"}, {"domain_payload": "accepted"}, {"contents": ["nested"]}, {"steps": ["Take"]}])
def test_model_unknown_authority_fields_and_candidate_expansion_fail_closed(change):
    provider = Provider(payload(**change))
    _, p, _, _, _, _, ctx, _, _, _, loop = setup(provider=provider)
    with p.write_fence.operation():
        exterior(p)
        result = run(p, loop, ctx)
        assert result.event is None and result.inspection_result.status == "deferred"
    assert provider.calls == 1 and len(p.event_history.get_events()) == 1


def test_valid_model_hypothesis_still_needs_independent_policy():
    provider = Provider(payload())
    _, p, auth, _, _, _, ctx, _, _, _, loop = setup(provider=provider)
    auth.policy = None
    with p.write_fence.operation():
        exterior(p)
        result = run(p, loop, ctx)
        assert result.event is None and result.inspection_result.status == "rejected"
    assert provider.calls == 1


@pytest.mark.parametrize("failure", ["none", "deny", "exception"])
def test_selection_does_not_supply_inspection_permission(failure):
    _, p, auth, _, _, _, ctx, _, _, _, loop = setup()
    if failure == "none": p.container_inspection_authority = None
    elif failure == "deny": auth.policy.evaluate = lambda _: False
    else:
        def broken(_): raise RuntimeError("policy unavailable")
        auth.policy.evaluate = broken
    with p.write_fence.operation():
        exterior(p)
        result = run(p, loop, ctx)
        assert result.inspection_result.status == "rejected" and result.event is None
    assert all(o.content.fact_type != "container_content" for o in p.observation_store.all())


@pytest.mark.parametrize("case", ["no_input", "no_goal", "ambiguous", "score_error", "review_error", "budget"])
def test_selection_and_review_defer_without_guessing(case):
    _, p, _, _, _, _, ctx, _, _, service, loop = setup(targets=("bag", "extra"), goal=case != "no_goal")
    decision = AgentDecision()
    if case == "score_error":
        class Bad:
            def evaluate(self, situation, candidates): return tuple(CandidateEvaluation(c.candidate_id, float("nan"), (), ()) for c in candidates)
        decision.evaluation_policy = Bad()
    elif case == "review_error":
        class Bad:
            def should_review(self, *a): return True
            def reassess(self, *a): raise RuntimeError("review failed")
        decision.review_policy = Bad()
    elif case == "budget":
        base = service.candidate_policy
        class Excess:
            def generate(self, s): return base.generate(s) * 7
        service.candidate_policy = Excess()
    with p.write_fence.operation():
        if case != "no_input": exterior(p)
        if case == "ambiguous": exterior(p, "extra")
        result = run(p, loop, ctx, decision)
        assert result.event is None and result.inspection_result.status == "deferred"


@pytest.mark.parametrize("mutation", ["actor", "target", "source", "method", "fake_accepted", "tick", "timeline", "generation", "operation"])
def test_selected_proposal_is_bound_to_exact_source_owner_and_live_operation(mutation):
    _, p, _, _, _, _, ctx, _, turn, service, _ = setup()
    with p.write_fence.operation():
        exterior(p)
        result = service.select(turn, RuntimeAgent("a"), ctx, AgentDecision(), p.simulation_clock.capture())
        assert result.status == "selected"
        proposal = result.proposal
        if mutation == "actor": proposal.agent_id = "other"
        elif mutation == "target": proposal._target_refs = ["object:bottle"]
        elif mutation == "source": proposal._reasoning_refs = ["fake"]
        elif mutation == "method": proposal._parameters["method"] = "steal"
        elif mutation == "fake_accepted":
            proposal = ActionProposal(proposal.proposal_id, proposal.agent_id, proposal.action_type,
                proposal.target_refs, proposal.parameters, proposal.reasoning_refs, proposal.metadata)
        elif mutation == "tick": p.simulation_clock.advance(1)
        elif mutation == "timeline": p.event_history.timeline_id = "sibling"
        if mutation not in {"generation", "operation"}:
            with pytest.raises(PermissionError): service.prepare_selected(RuntimeAgent("a"), proposal)
    if mutation in {"generation", "operation"}:
        if mutation == "generation": p.write_fence.freeze_and_advance(); p.write_fence.unfreeze()
        with p.write_fence.operation(), pytest.raises(PermissionError): service.prepare_selected(RuntimeAgent("a"), proposal)
    assert all(o.content.fact_type != "container_content" for o in p.observation_store.all())


def test_multiple_targets_are_ranked_and_not_chosen_by_first_id():
    w, p, _, _, _, _, ctx, _, _, service, loop = setup(targets=("bag", "extra"))
    w.load_entity(replace(w.get_entity("extra"), physical_capabilities=("container",)))
    base = service.candidate_policy
    class DifferentCosts:
        def generate(self, situation):
            return tuple(replace(c, estimated_cost=0.0 if c.target == "object:extra" else 1.0)
                         if c.intent == "Inspect" else c for c in base.generate(situation))
    service.candidate_policy = DifferentCosts()
    with p.write_fence.operation():
        exterior(p, "bag"); exterior(p, "extra")
        result = run(p, loop, ctx)
        assert result.inspection_result.status == "authorized"
        assert result.proposal.target_refs == ["object:extra"]
        assert result.proposal.metadata["decision_trace"][0]["candidate_id"] != "inspect:0"


@pytest.mark.parametrize("defect", ["duplicate_id", "unknown_strategy", "changed_source", "changed_owner"])
def test_custom_candidate_policy_cannot_launder_unqualified_binding(defect):
    _, p, _, _, _, _, ctx, _, _, service, loop = setup()
    base = service.candidate_policy
    class Altered:
        def generate(self, situation):
            candidates = base.generate(situation)
            first = candidates[0]
            if defect == "duplicate_id": return (first, first)
            if defect == "unknown_strategy": first = replace(first, strategy="accepted")
            elif defect == "changed_source": first = replace(first, source_refs=("fake", "fake"))
            else: first = replace(first, owner_id="other")
            return (first, candidates[-1])
    service.candidate_policy = Altered()
    with p.write_fence.operation():
        exterior(p)
        result = run(p, loop, ctx)
        assert result.event is None and result.inspection_result.status == "deferred"


def test_authorized_inspection_still_rechecks_state_at_processor_after_aba():
    from test_governed_relationship import prepare, request
    w, p, _, relationship, _, _, ctx, _, _, _, loop = setup()
    with p.write_fence.operation():
        exterior(p)
        result = run(p, loop, ctx)
        assert result.inspection_result.status == "authorized"
        for ident, operation in (("release", "release"), ("return", "contain")):
            event, _ = prepare(p, relationship, request(operation, target="x", parent="bag", ident=ident))
            p.dispatch_with_evidence(event)
        assert w.get_location("x") == "bag"
        with pytest.raises(PermissionError): p.dispatch_with_evidence(result.event)
    assert not p.event_history.get_event(result.event.id)


def test_safety_boundary_still_precedes_inspection_authorization(monkeypatch):
    _, p, _, _, _, _, ctx, _, _, _, loop = setup()
    def refuse(*a, **kw): raise PermissionError("safety refusal")
    monkeypatch.setattr(loop.safety_governance, "require_action_allowed", refuse)
    with p.write_fence.operation():
        exterior(p)
        with pytest.raises(PermissionError, match="safety refusal"): run(p, loop, ctx)
    assert len(p.event_history.get_events()) == 1


def test_scheduled_runtime_inspection_and_checkpoint_forks_do_not_restore_selection(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from cognitive_world.cognition.personality import Personality
    from cognitive_world.observation.container_inspection import ContainerInspectionAuthority
    from cognitive_world.runtime.cold_restore import ColdRuntimePublisher
    from cognitive_world.runtime.recovery import RestoreCoordinator
    from cognitive_world.cognition.l1_consumption_proof import NONVERBAL_PROOF_MEMORY_TYPE
    from test_container_inspection import Policy
    from test_item_take import save
    from test_runtime_content_commit_boundary import _signed_runtime, _install
    from test_runtime_reconstruction import _dependency_manifest
    import cognitive_world.event.processor as processing
    runtime, cognition, memory, installer = _signed_runtime()
    initial, _, _, _, _, _, _, _, _, _, _ = setup()
    w, p = runtime.context.world_state, runtime.event_processor
    for entity in initial.entities.values(): w.load_entity(entity)
    for key, value in initial.locations.items(): w.load_location(key, value)
    for relation in initial.relationships.values(): w.load_relationship(relation)
    w.load_environment_data("room", {"light_on": True})
    for owner in ("a", "other"):
        p.agent_registry.register(RuntimeAgent(owner, owner, goal_ids=["inspect-goal"] if owner == "a" else []))
    turn = runtime.agent_action_loop.agent_turn
    service = AutonomousInspectionService(p, turn.cognitive_runtime)
    runtime.agent_action_loop.inspection_service = service
    p.container_inspection_authority = ContainerInspectionAuthority(p, Policy())
    with runtime.write_fence.operation():
        for owner in ("a", "other"): cognition.add_personality(Personality(owner))
        cognition.add_goal(Goal("inspect-goal", "a", "inspect bag", 0.9, "active"))
        _install(installer)
        source = exterior(p)
    baseline = (dict(w.entities), dict(w.locations), dict(w.relationships))
    runtime.context.agent_scheduler.schedule_agent("a", runtime.context.clock.current_time + 1)
    runtime.step()
    record, = [r for r in runtime.last_agent_turn_results if r.agent_id == "a"]
    assert record.event_committed and record.failure_type is None
    assert record.execution.inspection_result.status == "authorized"
    event = record.execution.event
    observation, = [o for o in p.observation_store.get_by_observer("a") if o.source_event_id == event.id]
    assert not turn.cognitive_runtime.has_consumed_observation("a", observation, source_event_id=event.id)
    runtime.context.agent_scheduler.schedule_agent("a", runtime.context.clock.current_time + 1)
    runtime.step()
    assert turn.cognitive_runtime.has_consumed_observation("a", observation, source_event_id=event.id)
    assert len([e for e in p.event_history.get_events() if e.type == "container_inspected"]) == 2
    assert (w.entities, w.locations, w.relationships) == baseline
    assert not p.observation_store.get_by_observer("other")
    proofs = [m for m in memory.get_all_memories() if m.type == NONVERBAL_PROOF_MEMORY_TYPE]
    assert len([m for m in proofs if m.content.observation_id == observation.observation_id]) == 1
    with runtime.write_fence.operation():
        selected = service.select(turn, p.agent_registry.get("a"), runtime.cognition_context_provider(p.agent_registry.get("a")),
                                   AgentDecision(), p.simulation_clock.capture())
        assert selected.status == "selected"
    saved_proof_ids = {m.id for m in memory.get_all_memories() if m.type == NONVERBAL_PROOF_MEMORY_TYPE}
    manager, saved = save(SimpleNamespace(runtime=runtime, cognition=cognition, memory=memory, trust=p.persistence_trust), tmp_path/"saves")
    signed = p.event_history.export_persisted_records()
    class Assembler:
        def assemble(self, inputs):
            self.runtime, self.cognition, self.memory, _ = _signed_runtime(p.persistence_trust, inputs)
            return self.runtime
    restored = Assembler()
    with monkeypatch.context() as guard:
        guard.setattr(processing, "make_persisted_event_record", lambda *a, **k: pytest.fail("restore re-sign"))
        ColdRuntimePublisher().activate(manager.stage_cold_resume(saved.save_id, timeline_id=saved.timeline_id,
            assembler=restored, dependencies=_dependency_manifest()))
    assert restored.runtime.agent_action_loop.inspection_service is None
    assert restored.runtime.event_processor.container_inspection_authority is None
    assert restored.runtime.context.observation_store.all() == ()
    assert restored.runtime.context.event_history.export_persisted_records() == signed
    assert {m.id for m in restored.memory.get_all_memories() if m.type == NONVERBAL_PROOF_MEMORY_TYPE} == saved_proof_ids
    branches = []
    for name in ("inspect-autonomous-child", "inspect-autonomous-sibling"):
        parent, child = Assembler(), Assembler()
        slot = ColdRuntimePublisher().activate(manager.stage_cold_resume(saved.save_id, timeline_id=saved.timeline_id,
            assembler=parent, dependencies=_dependency_manifest()))
        branches.append(RestoreCoordinator(slot).activate(manager.stage_restore(saved.save_id,
            timeline_id=saved.timeline_id, active_runtime=slot.current, assembler=child,
            dependencies=_dependency_manifest(), new_timeline_id=name)))
    for branch in branches:
        assert branch.context.observation_store.all() == ()
        assert branch.agent_action_loop.inspection_service is None
        assert branch.event_processor.container_inspection_authority is None
        fresh = AutonomousInspectionService(branch.event_processor, branch.agent_action_loop.agent_turn.cognitive_runtime)
        with branch.write_fence.operation(), pytest.raises(PermissionError):
            fresh.prepare_selected(branch.context.agent_registry.get("a"), selected.proposal)


def test_historical_source_can_propose_but_current_location_can_deny_authorization():
    from cognitive_world.core.entity import Entity
    from cognitive_world.core.update import WorldUpdate
    from cognitive_world.event.handler import EventHandler
    w, p, _, _, _, _, ctx, core, _, _, loop = setup()
    w.load_entity(Entity("elsewhere", "location"))
    class Move(EventHandler):
        def handle(self, event): return WorldUpdate("locations", "update", {"bag": "elsewhere"})
    p.register_handler("move-bag", Move())
    with p.write_fence.operation():
        source = exterior(p)
        p.dispatch_with_evidence(SystemEventFactory().create(event_id="move", event_type="move-bag", timestamp="", simulation_tick=0))
        result = run(p, loop, ctx)
        assert core.has_consumed_observation("a", source, source_event_id=source.source_event_id)
        assert result.inspection_result.status == "rejected" and result.event is None
    assert not any(e.type == "container_inspected" for e in p.event_history.get_events())


def test_rejected_selection_does_not_retry_policy_in_same_turn():
    _, p, authority, _, _, _, ctx, _, turn, service, _ = setup()
    calls = []
    def deny(c): calls.append(c); return False
    authority.policy.evaluate = deny
    with p.write_fence.operation():
        exterior(p)
        selected = service.select(turn, RuntimeAgent("a"), ctx, AgentDecision(), p.simulation_clock.capture())
        first = service.prepare_selected(RuntimeAgent("a"), selected.proposal)
        second = service.prepare_selected(RuntimeAgent("a"), selected.proposal)
        assert first.status == "rejected" and second is first and len(calls) == 1


def test_new_operation_prunes_old_selection_without_reviving_it():
    _, p, _, _, _, _, ctx, _, turn, service, _ = setup()
    with p.write_fence.operation():
        exterior(p)
        old = service.select(turn, RuntimeAgent("a"), ctx, AgentDecision(), p.simulation_clock.capture())
    with p.write_fence.operation():
        current = service.select(turn, RuntimeAgent("a"), ctx, AgentDecision(), p.simulation_clock.capture())
        assert current.status == "selected" and len(service._selections) == 1
        with pytest.raises(PermissionError): service.prepare_selected(RuntimeAgent("a"), old.proposal)
