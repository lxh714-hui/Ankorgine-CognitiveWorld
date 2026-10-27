"""Committed Boolean results through signed processing and real NPC L1."""

from dataclasses import replace
import pytest
from test_pluggable_physics import Host, document
from cognitive_world.cognition.runtime import CognitiveRuntime
from cognitive_world.observation.generator import ObservationGenerator


def results(host):
    return tuple(
        o
        for o in host.runtime.context.observation_store.all()
        if o.content.predicate == "boolean_transition_applied"
    )


def consume(host):
    rt = host.runtime
    agent = rt.context.agent_registry.get(host.owner)
    with rt.write_fence.operation():
        return rt.agent_action_loop.agent_turn.prepare_decision_context(
            agent, rt.cognition_context_provider(agent)
        )[1]


def test_commit_delivery_actual_agent_consumption_and_duplicate():
    h = Host()
    rt = h.runtime
    with rt.write_fence.operation():
        decision, event = h.prepare()
        assert decision.success and not h.value() and not results(h)
        rt.event_processor.dispatch_with_evidence(event)
        rt.event_processor.dispatch_with_evidence(event)
    (observation,) = results(h)
    assert h.value() and observation.source_event_id == event.id
    assert observation.observer_id == h.owner and observation.has_trusted_provenance()
    assert observation.content.subject_ref == h.panel
    assert observation.content.value == ("open", True)
    assert observation.content.has_trusted_source(event)
    # NPC evidence does not create a player Presentation disclosure scope.
    from cognitive_world.runtime.context import PlayerSessionBinding, PlayerMode
    from cognitive_world.presentation import (
        PresentationPipeline,
        InMemoryChatOutputGateway,
    )

    rt.context.player_session = PlayerSessionBinding(
        "physical-view", "player", PlayerMode.ROLEPLAY, controlled_agent_id=h.owner
    )
    output = InMemoryChatOutputGateway(rt.context)
    assert (
        not PresentationPipeline.for_runtime(rt.context, output)
        .publish_event(event.id)
        .messages
    )
    turn = rt.agent_action_loop.agent_turn
    assert (
        h.owner,
        observation.observation_id,
    ) not in turn.cognitive_runtime._l1_consumption_receipts
    state = consume(h)
    pid = "percept:" + observation.observation_id
    assert pid in state.percept_ids
    assert any(
        i["observation_id"] == observation.observation_id
        and i["history"] == "eligible"
        and i["consumption"] == "ingested"
        for i in state.metadata["l1_ingestion"]["items"]
    )
    receipt = turn.cognitive_runtime._l1_consumption_receipts[
        (h.owner, observation.observation_id)
    ]
    count = len(rt.context.event_history.get_events())
    rt.context.observation_store.add(observation)
    assert results(h) == (observation,) and h.value()
    again = consume(h)
    assert (
        turn.cognitive_runtime.working_memory_store.get(h.owner).percept_ids.count(pid)
        == 1
    )
    assert any(
        i["observation_id"] == observation.observation_id
        and i["consumption"] == "duplicate"
        for i in again.metadata["l1_ingestion"]["items"]
    )
    assert (
        turn.cognitive_runtime._l1_consumption_receipts[
            (h.owner, observation.observation_id)
        ]
        == receipt
    )
    assert len(rt.context.event_history.get_events()) == count
    # Ordinary consumption does not become a new B2 system proof.
    assert not h.memory.get_all_memories()


def test_private_result_denies_bystander_and_invalid_owner_and_missing_history():
    data = document()
    data["scenarios"][0]["physical_rules"][0]["conditions"] = []
    data["scenarios"][0]["characters"].append(["watcher", "worker", "far"])
    h = Host(data)
    _, event = h.run()
    (observation,) = results(h)
    history = h.runtime.context.event_history
    evidence = history.get_processing_evidence(event.id)
    bystander = "physical:one:agent:watcher"
    assert h.runtime.context.agent_registry.get(bystander) is not None
    assert h.runtime.context.world_state.get_location(
        bystander
    ) == h.runtime.context.world_state.get_location(h.owner)
    assert not h.runtime.context.observation_store.get_by_observer(bystander)
    assert (
        ObservationGenerator().generate_authorized(
            event, evidence, observer_id=bystander, event_history=history
        )
        == ()
    )
    assert (
        ObservationGenerator().generate_authorized(event, evidence, observer_id=h.owner)
        == ()
    )
    runtime = CognitiveRuntime()
    state = runtime.process(h.owner, [observation])
    assert not state.percept_ids and runtime.working_memory_store.get(h.owner) is None
    assert not runtime._l1_consumption_receipts
    bound = h.runtime.agent_action_loop.agent_turn.cognitive_runtime
    altered = replace(observation, observer_id="unrelated-owner")
    state = bound.process("unrelated-owner", [altered])
    assert (
        not state.percept_ids
        and bound.working_memory_store.get("unrelated-owner") is None
    )


def test_rejected_and_stale_candidates_cannot_claim_success():
    data = document()
    data["objects"][1]["physical_state"]["properties"][0]["value"] = False
    h = Host(data)
    outcome, event = h.run()
    assert not outcome.success and event is not None and not results(h)
    h = Host()
    with h.runtime.write_fence.operation():
        _, stale = h.prepare()
        _, first = h.prepare()
        h.runtime.event_processor.dispatch_with_evidence(first)
        before = results(h)
        with pytest.raises((ValueError, PermissionError)):
            h.runtime.event_processor.dispatch_with_evidence(stale)
    assert results(h) == before and len(before) == 1
    assert h.runtime.context.event_history.get_event(stale.id) is None


def test_old_observation_is_immutable_after_later_transition():
    # A second installed operation reverses state through the same engine.
    data = document()
    data["scenarios"][0]["physical_rules"][0]["conditions"] = []
    data["scenarios"][0]["physical_rules"][0]["relations"] = []
    rule = dict(data["scenarios"][0]["physical_rules"][0])
    rule.update(
        rule_id="close-again",
        operation="reverse",
        expected=True,
        replacement=False,
        conditions=[],
        relations=[],
    )
    data["scenarios"][0]["physical_rules"].append(rule)
    h = Host(data)
    _, first = h.run()
    (old,) = results(h)
    assert h.run(operation="reverse")[0].success and not h.value()
    assert h.runtime.context.observation_store.get(old.observation_id) == old
    assert old.content.value == ("open", True)
    assert {o.content.value for o in results(h)} == {("open", True), ("open", False)}


def test_signed_restore_inherits_exact_fact_without_resigning_and_rejects_foreign_history(
    tmp_path, monkeypatch
):
    from cognitive_world.runtime.save_manager import SaveManager
    from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
    from cognitive_world.content.persistence import scenario_snapshot_codec
    from test_runtime_reconstruction import _dependency_manifest
    import cognitive_world.event.processor as processor_module

    h = Host()
    _, event = h.run()
    (observation,) = results(h)
    consume(h)
    manager = SaveManager(
        tmp_path / "saves", trust=h.trust, codec=scenario_snapshot_codec()
    )
    rt = h.runtime
    contexts = tuple(
        rt.cognition_context_provider(a) for a in rt.context.agent_registry.all_agents()
    )
    saved = manager.create_manual_save(
        runtime=rt,
        cognition=h.cognition,
        memory_store=h.memory,
        agent_contexts=contexts,
    )
    record = rt.context.event_history.get_persistence_record(event.id).to_json_record()

    class Assembler:
        def assemble(self, inputs):
            self.host = Host(inputs=inputs, trust=h.trust)
            return self.host.runtime

    def forbid(*args, **kwargs):
        pytest.fail("restore must not sign historical results")

    monkeypatch.setattr(processor_module, "make_persisted_event_record", forbid)
    assembly = Assembler()
    staged = manager.stage_restore(
        saved.save_id,
        timeline_id=saved.timeline_id,
        active_runtime=rt,
        assembler=assembly,
        dependencies=_dependency_manifest(),
        new_timeline_id="physical-observation-child",
    )
    child = RestoreCoordinator(ActiveRuntimeSlot(rt)).activate(staged)
    restored = assembly.host
    assert restored.value()
    assert (
        child.context.event_history.get_persistence_record(event.id).to_json_record()
        == record
    )
    # Observations are transient: explicit historical delivery is not restore-time consumption.
    assert not results(restored)
    restored_event = child.context.event_history.get_event(event.id)
    restored_evidence = child.context.event_history.get_processing_evidence(event.id)
    from cognitive_world.physics.observation import result_draft

    assert (
        result_draft(
            restored_event,
            location_id=restored_evidence.event_time_context.fact_location_id,
        )
        is not None
    ), repr(restored_event.changes)
    assert restored_evidence.has_trusted_source(restored_event)
    assert (
        child.context.event_history.get_processing_evidence(event.id)
        == restored_evidence
    )
    assert (
        restored_evidence.event_time_context.simulation_time
        == restored_event.simulation_tick
    )
    from cognitive_world.physics.observation import allows_result

    assert allows_result(
        restored_event,
        restored_evidence,
        restored.owner,
        event_history=child.context.event_history,
    ), repr(
        (
            child.context.event_history.requires_recovery(),
            child.context.event_history.get_processing_status(event.id),
            restored_evidence.event_time_context,
            restored_evidence.observable_facts,
        )
    )
    (delivered,) = ObservationGenerator().generate_authorized(
        restored_event,
        restored_evidence,
        observer_id=restored.owner,
        event_history=child.context.event_history,
        source_timeline_id=child.context.event_history.timeline_id,
        source_runtime_session_id=child.write_fence.session_id,
        source_runtime_generation=child.write_fence.restore_generation,
    )
    assert delivered.content == observation.content
    child.context.observation_store.add(delivered)
    state = consume(restored)
    assert any(
        i["observation_id"] == observation.observation_id and i["history"] == "eligible"
        for i in state.metadata["l1_ingestion"]["items"]
    ), repr(state.metadata["l1_ingestion"]["items"])
    assert not restored.memory.get_all_memories()
    monkeypatch.undo()
    foreign = Host()
    _, other_event = foreign.run()
    (other,) = results(foreign)
    # Same owner spelling and trusted provenance do not establish history membership.
    assert other.observer_id == restored.owner
    child.context.observation_store.add(other)
    cognitive = child.agent_action_loop.agent_turn.cognitive_runtime
    before = cognitive.working_memory_store.get(restored.owner)
    receipts = dict(cognitive._l1_consumption_receipts)
    state = consume(restored)
    assert any(
        i["observation_id"] == other.observation_id and i["history"] == "ineligible"
        for i in state.metadata["l1_ingestion"]["items"]
    )
    assert cognitive.working_memory_store.get(restored.owner) == before
    assert (
        restored.owner,
        other.observation_id,
    ) not in cognitive._l1_consumption_receipts
    assert cognitive._l1_consumption_receipts == receipts
    assert child.context.event_history.get_event(other_event.id) is None
