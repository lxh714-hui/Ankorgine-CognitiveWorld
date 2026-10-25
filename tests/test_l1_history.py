"""Real-entry ordinary L1 qualification; foreign Store delivery is a host-boundary fixture."""

import pytest

from cognitive_world.cognition.runtime import CognitiveRuntime
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.dialogue.runtime import DialogueRequest
from cognitive_world.runtime.save_manager import SaveManager
from test_dialogue_runtime import make_dialogue
from test_npc_social_interaction import _world
from test_runtime_reconstruction import FakeTrust
from test_l1_consumption_crash_branch import _deliver, _save, _fork


def _prepare(service):
    agent = service.context.agent_registry.get("listener")
    context = service.cognition_context_provider(agent)
    return service.action_loop.agent_turn.prepare_decision_context(agent, context)


def _items(state):
    return state.metadata["l1_ingestion"]["items"]


def test_memory_history_delivery_and_duplicate_are_not_unknown():
    service, _, _, store, history, loop = make_dialogue()
    service.submit(DialogueRequest("current", "listener", "A statement"))
    observation, = store.get_by_observer("listener")
    _, state = _prepare(service)
    assert _items(state)[0]["history"] == "eligible"
    assert _items(state)[0]["consumption"] == "duplicate"
    assert state.percept_ids == [] and len(state.percepts) == 1
    runtime = loop.agent_turn.cognitive_runtime
    assert runtime.has_consumed_observation("listener", observation, source_event_id=observation.source_event_id)
    assert runtime.working_memory_store.get("listener").percept_ids == ["percept:" + observation.observation_id]
    assert len(history.get_events()) == 1


def test_direct_call_without_history_defers_and_does_not_create_working_memory():
    service, _, _, store, _, _ = make_dialogue()
    service.submit(DialogueRequest("source", "listener", "A statement"))
    observation, = store.get_by_observer("listener")
    runtime = CognitiveRuntime()
    for _ in range(2):
        state = runtime.process("listener", (observation,))
        assert not state.percepts and not state.percept_ids
        assert _items(state)[0]["history"] == "undetermined"
        assert _items(state)[0]["consumption"] == "not_consumed"
        assert runtime.working_memory_store.get("listener") is None
        assert not runtime._l1_consumption_receipts
    empty = runtime.process("listener", ())
    assert _items(empty) == ()
    assert runtime.working_memory_store.get("listener") is None


def test_dialogue_current_delivery_does_not_endorse_foreign_history():
    foreign, _, _, foreign_store, _, _ = make_dialogue()
    foreign.submit(DialogueRequest("foreign", "listener", "Foreign statement"))
    wrong, = foreign_store.get_by_observer("listener")
    service, _, _, store, history, loop = make_dialogue()
    # Explicit host Store delivery, not a claim that desktop auto-merges histories.
    store.add(wrong)
    assert wrong in service.cognition_context_provider(
        service.context.agent_registry.get("listener")).get_observations()
    result = service.submit(DialogueRequest("local", "listener", "Local statement"))
    assert result.status == "delivered_no_action"
    runtime = loop.agent_turn.cognitive_runtime
    workspace = runtime.working_memory_store.get("listener")
    assert "percept:" + wrong.observation_id not in workspace.percept_ids
    assert not runtime.has_consumed_observation("listener", wrong, source_event_id=wrong.source_event_id)
    assert ("listener", wrong.observation_id) not in runtime._l1_consumption_receipts
    _, state = _prepare(service)
    rejected, accepted = _items(state)
    assert rejected["history"] == "ineligible" and accepted["history"] == "eligible"
    assert all(p.source_observation_id != wrong.observation_id for p in state.percepts)
    assert len(workspace.percept_ids) == 1 and len(history.get_events()) == 1


def test_all_foreign_observations_preserve_existing_working_memory_and_receipts():
    foreign, _, _, source, _, _ = make_dialogue()
    foreign.submit(DialogueRequest("other", "listener", "Other statement"))
    wrong, = source.get_by_observer("listener")
    service, _, _, store, _, loop = make_dialogue()
    runtime = loop.agent_turn.cognitive_runtime
    store.add(wrong)
    _, state = _prepare(service)
    assert not state.percepts and runtime.working_memory_store.get("listener") is None
    assert not runtime._l1_consumption_receipts
    service.submit(DialogueRequest("valid", "listener", "Valid statement"))
    before = runtime.working_memory_store.get("listener")
    receipts = dict(runtime._l1_consumption_receipts)
    # A direct call on the same bound runtime still uses the shared qualifier.
    state = runtime.process("listener", (wrong,))
    assert not state.percepts and not state.percept_ids
    assert runtime.working_memory_store.get("listener") == before
    assert runtime._l1_consumption_receipts == receipts


def test_verified_fork_accepts_ancestor_and_rejects_sibling_via_agent_turn(tmp_path):
    trust = FakeTrust()
    parent, *_ = _world(communication=False, trust=trust, shared_memory_store=MemoryStore())
    ancestor = _deliver(parent, "ancestor")
    manager = SaveManager(tmp_path / "saves", trust=trust)
    saved = _save(manager, parent)
    child = _fork(manager, saved, parent, trust, "child")
    other_active, *_ = _world(communication=False, trust=trust, shared_memory_store=MemoryStore())
    sibling = _fork(manager, saved, other_active, trust, "sibling")
    other = _deliver(sibling, "sibling-only")
    foreign, = [o for o in sibling.context.observation_store.get_by_observer("npc-b")
                if o.source_event_id == other.id]
    with child.write_fence.operation():
        child.event_processor.dispatch_with_evidence(child.context.event_history.get_event(ancestor.id))
    child.context.observation_store.add(foreign)
    agent = child.context.agent_registry.get("npc-b")
    context = child.cognition_context_provider(agent)
    assert foreign in context.get_observations()
    events_before = len(child.context.event_history.get_events())
    with child.write_fence.operation():
        _, state = child.agent_action_loop.agent_turn.prepare_decision_context(
            agent, context, simulation_tick=child.context.clock.capture())
    runtime = child.agent_action_loop.agent_turn.cognitive_runtime
    workspace = runtime.working_memory_store.get("npc-b")
    ancestor_observation, = [o for o in context.get_observations() if o.source_event_id == ancestor.id]
    assert ancestor_observation.trusted_source_timeline_id() == "child"
    assert "percept:" + ancestor_observation.observation_id in workspace.percept_ids
    assert "percept:" + foreign.observation_id not in workspace.percept_ids
    assert not runtime.has_consumed_observation("npc-b", foreign, source_event_id=foreign.source_event_id)
    assert {i["history"] for i in _items(state)} == {"eligible", "ineligible"}
    assert len(child.context.event_history.get_events()) == events_before


def test_generation_change_retains_history_but_not_old_write_permit():
    runtime, *_ = _world(communication=False)
    event = _deliver(runtime, "before-generation-change")
    events_before = len(runtime.context.event_history.get_events())
    fence = runtime.write_fence
    with fence.operation() as old_permit:
        fence.freeze_and_advance()
        fence.unfreeze()
        with pytest.raises(PermissionError):
            fence.require_current_permit(old_permit)
    agent = runtime.context.agent_registry.get("npc-b")
    context = runtime.cognition_context_provider(agent)
    observation, = [o for o in context.get_observations() if o.source_event_id == event.id]
    assert observation.trusted_source_runtime_binding()[1] != fence.restore_generation
    with fence.operation():
        _, state = runtime.agent_action_loop.agent_turn.prepare_decision_context(agent, context)
    assert _items(state)[0]["history"] == "eligible"
    assert "percept:" + observation.observation_id in state.percept_ids
    assert len(runtime.context.event_history.get_events()) == events_before


def test_unavailable_history_preserves_workspace_and_receipts_through_agent_turn():
    service, _, _, store, history, loop = make_dialogue()
    service.submit(DialogueRequest("received", "listener", "A statement"))
    observation, = store.get_by_observer("listener")
    runtime = loop.agent_turn.cognitive_runtime
    before = runtime.working_memory_store.get("listener")
    receipts = dict(runtime._l1_consumption_receipts)
    history.mark_recovery_required(observation.source_event_id, "injected recovery boundary")
    decision, state = _prepare(service)
    assert not state.percepts and not state.percept_ids
    assert _items(state)[0]["history"] == "undetermined"
    assert _items(state)[0]["consumption"] == "not_consumed"
    assert runtime.working_memory_store.get("listener") == before
    assert runtime._l1_consumption_receipts == receipts
    assert any("history qualification" in cue for cue in decision.metacognitive_feedback.review_cues)


def test_real_agent_turn_unknown_history_does_not_create_workspace():
    runtime, *_ = _world(communication=False)
    event = _deliver(runtime, "pending-history")
    agent = runtime.context.agent_registry.get("npc-b")
    context = runtime.cognition_context_provider(agent)
    cognition = runtime.agent_action_loop.agent_turn.cognitive_runtime
    assert context.get_observations() and cognition.working_memory_store.get("npc-b") is None
    runtime.context.event_history.mark_recovery_required(event.id, "injected history failure")
    with runtime.write_fence.operation():
        decision, state = runtime.agent_action_loop.agent_turn.prepare_decision_context(agent, context)
    assert all(i["history"] == "undetermined" for i in _items(state))
    assert state.percepts == [] and state.percept_ids == []
    assert cognition.working_memory_store.get("npc-b") is None
    assert not cognition._l1_consumption_receipts


def test_equal_event_identity_does_not_substitute_foreign_authorization_context():
    from test_authorized_perception_vertical_slice import _world as light_world, _run_runtime, _registry, _light_event
    from cognitive_world.agent.turn import AgentTurn
    from cognitive_world.agent.character import Character
    from cognitive_world.agent.cognition_context import CognitionContext
    from cognitive_world.cognition.container import CognitionContainer
    from cognitive_world.observation.store import ObservationStore
    foreign_store = ObservationStore()
    _run_runtime(light_world(), registry=_registry(), event=_light_event(), observation_store=foreign_store)
    foreign, = foreign_store.get_by_observer("agent-near")
    local_store = ObservationStore()
    context, processor = _run_runtime(light_world(unknown_position=True), registry=_registry(),
                                      event=_light_event(), observation_store=local_store)
    assert not local_store.get_by_observer("agent-near")
    assert foreign.has_trusted_provenance()
    event = context.event_history.get_event(foreign.source_event_id)
    evidence = context.event_history.get_processing_evidence(event.id)
    assert foreign.content in evidence.observable_facts and foreign.content.has_trusted_source(event)
    local_store.add(foreign)
    cognition = CognitionContext.from_character(
        Character("near-character", "agent-near", ""), CognitionContainer(), MemoryStore(),
        observation_store=local_store)
    assert foreign in cognition.get_observations()
    turn = AgentTurn()
    turn.cognitive_runtime._bind_observation_history(context.event_history)
    _, state = turn.prepare_decision_context(context.agent_registry.get("agent-near"), cognition)
    assert _items(state)[0]["code"] == "authorization_evidence_mismatch"
    assert state.percepts == [] and state.percept_ids == []
    assert turn.cognitive_runtime.working_memory_store.get("agent-near") is None
    assert not turn.cognitive_runtime._l1_consumption_receipts
    assert len(context.event_history.get_events()) == 1



def _prepare_live(runtime):
    agent = runtime.context.agent_registry.get("npc-b")
    context = runtime.cognition_context_provider(agent)
    with runtime.write_fence.operation():
        return runtime.agent_action_loop.agent_turn.prepare_decision_context(agent, context)


def _live_mixed_inputs(prime):
    runtime, *_ = _world(communication=False)
    blocked_event = _deliver(runtime, "deferred-input")
    if prime:
        _prepare_live(runtime)
    accepted_event = _deliver(runtime, "independent-input")
    agent = runtime.context.agent_registry.get("npc-b")
    context = runtime.cognition_context_provider(agent)
    observations = context.get_observations()
    blocked, = [item for item in observations if item.source_event_id == blocked_event.id]
    accepted, = [item for item in observations if item.source_event_id == accepted_event.id]
    assert blocked.has_trusted_provenance() and accepted.has_trusted_provenance()
    return runtime, context, blocked, accepted


def _defer_at_qualification(monkeypatch, blocked_event_ids, visited):
    # Observations have already been issued by the real processor. Inject only
    # a verification failure; all successful comparisons use the real policy.
    from cognitive_world.observation.generator import ObservationGenerator
    original = ObservationGenerator.generate_authorized

    def generate(self, event, evidence, **kwargs):
        visited.append(event.id)
        if event.id in blocked_event_ids:
            raise ValueError("injected qualification failure")
        return original(self, event, evidence, **kwargs)

    monkeypatch.setattr(ObservationGenerator, "generate_authorized", generate)


@pytest.mark.parametrize("prime", [False, True], ids=["new-workspace", "prior-receipt"])
def test_real_turn_mixes_new_and_duplicate_ingestion_with_deferred_item(monkeypatch, prime):
    runtime, context, blocked, accepted = _live_mixed_inputs(prime)
    cognition = runtime.agent_action_loop.agent_turn.cognitive_runtime
    blocked_key = ("npc-b", blocked.observation_id)
    prior_receipt = cognition._l1_consumption_receipts.get(blocked_key)
    before = cognition.working_memory_store.get("npc-b")
    history_before = runtime.context.event_history.get_events()
    visited = []
    _defer_at_qualification(monkeypatch, {blocked.source_event_id}, visited)

    decision, state = _prepare_live(runtime)
    results = {item["observation_id"]: item for item in _items(state)}
    assert blocked.source_event_id in visited  # reached the actual qualifier
    assert results[blocked.observation_id]["source"] == "eligible"
    assert results[blocked.observation_id]["history"] == "undetermined"
    assert results[blocked.observation_id]["consumption"] == "not_consumed"
    assert results[accepted.observation_id]["history"] == "eligible"
    assert results[accepted.observation_id]["consumption"] == "ingested"
    assert "percept:" + accepted.observation_id in state.percept_ids
    assert all(p.source_observation_id != blocked.observation_id for p in state.percepts)
    assert cognition._l1_consumption_receipts.get(blocked_key) is prior_receipt
    workspace = cognition.working_memory_store.get("npc-b")
    old_count = 0 if before is None else before.percept_ids.count("percept:" + blocked.observation_id)
    assert workspace.percept_ids.count("percept:" + blocked.observation_id) == old_count
    assert workspace.percept_ids.count("percept:" + accepted.observation_id) == 1
    assert any("history qualification" in cue for cue in decision.metacognitive_feedback.review_cues)

    _, duplicate = _prepare_live(runtime)
    repeated = {item["observation_id"]: item for item in _items(duplicate)}
    assert repeated[accepted.observation_id]["consumption"] == "duplicate"
    assert repeated[blocked.observation_id]["history"] == "undetermined"
    assert repeated[blocked.observation_id]["consumption"] == "not_consumed"
    assert duplicate.percept_ids == []
    assert all(p.source_observation_id != blocked.observation_id for p in duplicate.percepts)
    assert cognition.working_memory_store.get("npc-b") == workspace
    assert cognition._l1_consumption_receipts.get(blocked_key) is prior_receipt
    assert runtime.context.event_history.get_events() == history_before


@pytest.mark.parametrize("prime", [False, True], ids=["absent-workspace", "existing-workspace"])
def test_all_per_item_deferred_inputs_never_call_workspace_update(monkeypatch, prime):
    runtime, context, blocked, accepted = _live_mixed_inputs(prime)
    cognition = runtime.agent_action_loop.agent_turn.cognitive_runtime
    before = cognition.working_memory_store.get("npc-b")
    receipts = dict(cognition._l1_consumption_receipts)
    observations = context.get_observations()
    history_before = runtime.context.event_history.get_events()
    visited = []
    _defer_at_qualification(monkeypatch, {item.source_event_id for item in observations}, visited)

    def forbidden_update(_workspace):
        pytest.fail("all deferred observations must not invoke WorkingMemory.update")

    monkeypatch.setattr(cognition.working_memory_store, "update", forbidden_update)
    _, state = _prepare_live(runtime)
    assert {item.source_event_id for item in observations}.issubset(visited)
    assert len(_items(state)) == len(observations)
    assert all(item["history"] == "undetermined" and item["consumption"] == "not_consumed"
               for item in _items(state))
    assert state.percepts == [] and state.percept_ids == []
    assert cognition.working_memory_store.get("npc-b") == before
    assert cognition._l1_consumption_receipts.keys() == receipts.keys()
    assert all(cognition._l1_consumption_receipts[key] is value for key, value in receipts.items())
    assert runtime.context.event_history.get_events() == history_before


class _InjectedL1Failure(RuntimeError):
    pass


@pytest.mark.parametrize("prime", [False, True], ids=["new-workspace", "prior-receipt"])
@pytest.mark.parametrize("failure_point", ["percept", "before-workspace-write", "after-workspace-write"])
def test_real_turn_failure_does_not_consume_deferred_neighbor(monkeypatch, prime, failure_point):
    runtime, context, blocked, accepted = _live_mixed_inputs(prime)
    cognition = runtime.agent_action_loop.agent_turn.cognitive_runtime
    before = cognition.working_memory_store.get("npc-b")
    receipts = dict(cognition._l1_consumption_receipts)
    memories = context.memory_store.get_all_memories()
    history_before = runtime.context.event_history.get_events()
    blocked_key = ("npc-b", blocked.observation_id)
    visited = []
    _defer_at_qualification(monkeypatch, {blocked.source_event_id}, visited)
    converted = []
    written = []
    original_process = cognition.perception_processor.process
    original_update = cognition.working_memory_store.update

    def process(observation, *, observer_id):
        converted.append(observation.observation_id)
        if failure_point == "percept" and observation.observation_id == accepted.observation_id:
            raise _InjectedL1Failure("injected Percept conversion failure")
        return original_process(observation, observer_id=observer_id)

    def update(workspace):
        written.append(workspace)
        if failure_point == "before-workspace-write":
            raise _InjectedL1Failure("injected pre-write failure")
        original_update(workspace)
        raise _InjectedL1Failure("injected committed-write failure")

    with monkeypatch.context() as fault:
        fault.setattr(cognition.perception_processor, "process", process)
        if failure_point != "percept":
            fault.setattr(cognition.working_memory_store, "update", update)
        with pytest.raises(_InjectedL1Failure):
            _prepare_live(runtime)

    assert blocked.source_event_id in visited
    assert blocked.observation_id not in converted
    assert accepted.observation_id in converted
    assert cognition._l1_consumption_receipts.keys() == receipts.keys()
    assert all(cognition._l1_consumption_receipts[key] is value for key, value in receipts.items())
    after = cognition.working_memory_store.get("npc-b")
    if failure_point == "after-workspace-write":
        # Ordinary L1 has no atomic rollback contract. Only eligible cursors may
        # have committed; this must not be mistaken for proof publication.
        assert after is not None and after == written[0]
        assert after.percept_ids.count("percept:" + accepted.observation_id) == 1
        previous_count = 0 if before is None else before.percept_ids.count("percept:" + blocked.observation_id)
        assert after.percept_ids.count("percept:" + blocked.observation_id) == previous_count
    else:
        assert after == before
        assert len(written) == (0 if failure_point == "percept" else 1)
    assert context.memory_store.get_all_memories() == memories
    assert runtime.context.event_history.get_events() == history_before

    # Retry cognition only, with the same deferred neighbor. No Event is replayed.
    _, retry = _prepare_live(runtime)
    results = {item["observation_id"]: item for item in _items(retry)}
    assert results[blocked.observation_id]["history"] == "undetermined"
    assert results[blocked.observation_id]["consumption"] == "not_consumed"
    assert results[accepted.observation_id]["consumption"] == (
        "duplicate" if failure_point == "after-workspace-write" else "ingested")
    assert all(p.source_observation_id != blocked.observation_id for p in retry.percepts)
    assert cognition._l1_consumption_receipts.get(blocked_key) is receipts.get(blocked_key)
    assert cognition.working_memory_store.get("npc-b").percept_ids.count(
        "percept:" + accepted.observation_id) == 1
    assert runtime.context.event_history.get_events() == history_before
