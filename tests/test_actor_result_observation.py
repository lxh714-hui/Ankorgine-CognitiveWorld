"""B1: real confirmed failures issue private receipts, never cognitive revision."""
from contextvars import copy_context
from copy import deepcopy
from dataclasses import replace

import pytest

from test_causal_resolution import _world, _attempt
from test_autonomous_world_runner import _production_world
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.core.entity import Entity
from cognitive_world.event import EventProcessor
from cognitive_world.event.environment import ResolutionEffectsHandler
from cognitive_world.event.history import EventHistory, EventProcessingStatus
from cognitive_world.observation import ObservationStore
from cognitive_world.observation.generator import ObservationGenerator
from cognitive_world.observation.observable import ObservableFactDraft
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.causal import MethodBasedResolutionEngine
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.write_fence import RuntimeWriteFence


def _fixture(*, locked=True, senses=("sight",)):
    world = _world(locked=locked)
    world.load_entity(Entity("agent-1", "character", sensory_capabilities=senses,
                             physical_capabilities=("manual_manipulation",)))
    world.load_entity(Entity("other", "character", sensory_capabilities=("sight",)))
    world.load_location("other", "door_contact")
    registry = AgentRegistry()
    for owner in ("agent-1", "other"):
        registry.register(RuntimeAgent(owner))
    clock, history, store = SimulationClock(9), EventHistory(), ObservationStore()
    fence = RuntimeWriteFence("b1-session")
    processor = EventProcessor(event_history=history, world_state=world,
        simulation_clock=clock, agent_registry=registry, observation_store=store,
        write_fence=fence)
    flow = ActionResolutionFlow(MethodBasedResolutionEngine(world_state=world), world_state=world)
    return world, clock, history, store, fence, processor, flow


def _results(store, owner="agent-1"):
    return tuple(o for o in store.get_by_observer(owner) if o.content.fact_type == "action_result")


def test_real_npc_turn_issues_owner_result_without_consumption_or_revision():
    runner, world, history, store = _production_world({
        "agent-a": ("goal-open", "open the archive door"),
        "agent-b": ("goal-wait", "wait patiently"),
    }, co_located=True, door_locked=True)
    context = runner.runtime.cognition_context_provider(runner.runtime.context.agent_registry.get("agent-a"))
    cognition = context.cognition_container
    before = deepcopy((dict(cognition.beliefs), dict(cognition.goals),
                       dict(cognition.self_models), context.memory_store.get_all_memories()))
    initial = len(history.get_events())
    runner.run(1)
    execution = runner.runtime.last_agent_turn_results[0].execution
    event, attempt = execution.event, execution.attempt
    assert execution.resolution.success is False
    assert len(history.get_events()) == initial + 1
    assert world.environment["door:archive"].is_open is False
    assert world.environment["door:archive"].is_locked is True
    observations = _results(store, "agent-a")
    assert len(observations) == 1 and _results(store, "agent-b") == ()
    observation = observations[0]
    fact = observation.content
    assert (fact.predicate, fact.value, fact.subject_ref, fact.location_id) == (
        "door_open_attempt_failed", True, "door:archive", "hall")
    assert observation.observer_id == attempt.agent_id
    assert observation.source_event_id == event.id
    assert observation.has_trusted_provenance() and fact.has_trusted_source(event)
    evidence = history.get_processing_evidence(event.id)
    assert fact in evidence.observable_facts and evidence.has_trusted_source(event)
    from cognitive_world.event.attempt_source import verify_confirmed_failure_event
    assert verify_confirmed_failure_event(event, attempt=attempt)
    assert before == (dict(cognition.beliefs), dict(cognition.goals),
                      dict(cognition.self_models), context.memory_store.get_all_memories())
    cognitive_runtime = runner.runtime.agent_action_loop.agent_turn.cognitive_runtime
    assert not cognitive_runtime.has_consumed_observation("agent-a", observation, source_event_id=event.id)
    from cognitive_world.observation.historical_rules import HistoricalObservationRuleRegistry
    assert HistoricalObservationRuleRegistry().for_source(event, evidence).rule_id == "door-open-failed-owner-result"
    # Subsequent ordinary turns must not silently activate the B2-B4 lifecycle.
    with runner.runtime.write_fence.operation():
        runner.runtime.agent_action_loop.agent_turn.prepare_decision_context(
            runner.runtime.context.agent_registry.get("agent-a"), context,
            simulation_tick=runner.runtime.context.clock.capture())
    assert not cognitive_runtime.has_consumed_observation("agent-a", observation, source_event_id=event.id)
    assert before == (dict(cognition.beliefs), dict(cognition.goals),
                      dict(cognition.self_models), context.memory_store.get_all_memories())



def test_result_requires_committed_history_and_retains_runtime_binding():
    world, clock, history, store, fence, processor, flow = _fixture()
    with fence.operation():
        event = flow.execute(_attempt(), simulation_tick=clock.capture())
        evidence = processor.process_with_evidence(event, world)
        generator = ObservationGenerator()
        assert generator.generate_authorized(event, evidence, observer_id="agent-1") == ()
        assert store.all() == ()
        processor.dispatch_with_evidence(event)
        observation, = _results(store)
        assert observation.has_trusted_provenance()
        assert observation.trusted_source_runtime_binding() == (fence.session_id, fence.restore_generation)
        assert generator.generate_authorized(event, evidence, observer_id="other", event_history=history) == ()
        assert generator.generate_authorized(event, replace(evidence, observable_facts=()),
            observer_id="agent-1", event_history=history) == ()
        processor.dispatch_with_evidence(event)
        assert len(_results(store)) == 1 and len(history.get_events()) == 1


class _MixedHandler(ResolutionEffectsHandler):
    def observable_facts(self, event, update):
        return (ObservableFactDraft("environment_state", "door_locked", True,
                                   subject_ref="door-1", location_id="door_contact"),)


def test_private_result_does_not_expand_sight_and_bystander_gets_only_door_state():
    world, clock, history, store, fence, processor, flow = _fixture(senses=())
    processor.register_handler("resolution", _MixedHandler())
    with fence.operation():
        event = flow.execute(_attempt(), simulation_tick=clock.capture())
        processor.dispatch_with_evidence(event)
    assert [o.content.predicate for o in store.get_by_observer("agent-1")] == ["door_open_attempt_failed"]
    assert [o.content.predicate for o in store.get_by_observer("other")] == ["door_locked"]
    assert len(history.get_events()) == 1 and world.environment["door-1"].is_open is False


@pytest.mark.parametrize("mutation", ["owner_id", "target_refs", "attempt_fingerprint", "state_slot_reads", "schema"])
def test_mutated_failure_source_cannot_issue_results(mutation):
    world, clock, history, store, fence, processor, flow = _fixture()
    with fence.operation():
        event = flow.execute(_attempt(), simulation_tick=clock.capture())
        event.metadata["confirmed_attempt_failure"][mutation] = "forged"
        with pytest.raises((PermissionError, ValueError)):
            processor.dispatch_with_evidence(event)
    assert not history.get_events() and not store.all()
    assert world.environment["door-1"].is_open is False


@pytest.mark.parametrize("missing", ["actor_registration", "clock", "location"])
def test_missing_event_time_owner_context_fails_closed(missing):
    world, clock, history, store, fence, processor, flow = _fixture()
    with fence.operation():
        event = flow.execute(_attempt(), simulation_tick=clock.capture())
        if missing == "actor_registration":
            processor.agent_registry.remove("agent-1")
        elif missing == "clock":
            processor.simulation_clock = None
        else:
            # Canonical initialization has not yet been sealed by processing.
            world.load_location("agent-1", "elsewhere")
        processor.dispatch_with_evidence(event)
    assert len(history.get_events()) == 1 and not _results(store)
    assert world.environment["door-1"].is_open is False


@pytest.mark.parametrize("method", ["invent a harmless method", "do not push the door"])
def test_unresolved_action_has_no_result_event(method):
    world, clock, history, store, fence, processor, flow = _fixture()
    with fence.operation():
        result, event = flow.execute_with_result(_attempt(method), simulation_tick=clock.capture())
    assert not result.confirmed and event is None
    assert not history.get_events() and not store.all()


def test_success_retains_door_state_observation_without_failure_fact():
    world, clock, history, store, fence, processor, flow = _fixture(locked=False)
    with fence.operation():
        event = flow.execute(_attempt(), simulation_tick=clock.capture())
        processor.dispatch_with_evidence(event)
    assert world.environment["door-1"].is_open is True
    assert len(history.get_events()) == 1 and not _results(store)
    assert [o.content.predicate for o in store.get_by_observer("agent-1")] == ["door_open"]


@pytest.mark.parametrize("invalidation", ["cancel", "generation"])
def test_late_task_cannot_commit_or_publish(invalidation):
    world, clock, history, store, fence, processor, flow = _fixture()
    with fence.operation() as permit:
        event = flow.execute(_attempt(), simulation_tick=clock.capture())
        old_context = copy_context()
        if invalidation == "cancel":
            assert fence.revoke_uncommitted(permit)
    if invalidation == "generation":
        fence.freeze_and_advance()
        fence.unfreeze()
    with pytest.raises(PermissionError):
        old_context.run(processor.dispatch_with_evidence, event)
    assert not history.get_events() and not store.all()
    assert world.environment["door-1"].is_open is False


def test_delivery_failure_retries_evidence_without_replaying_action(monkeypatch):
    world, clock, history, store, fence, processor, flow = _fixture()
    add = store.add
    with fence.operation():
        event = flow.execute(_attempt(), simulation_tick=clock.capture())
        def unavailable(observation):
            raise OSError("observation store unavailable")
        monkeypatch.setattr(store, "add", unavailable)
        with pytest.raises(RuntimeError, match="Observation delivery failed"):
            processor.dispatch_with_evidence(event)
        assert len(history.get_events()) == 1 and not store.all()
        assert history.get_processing_status(event.id) == EventProcessingStatus.OBSERVATIONS_PENDING
        evidence = history.get_processing_evidence(event.id)
        monkeypatch.setattr(store, "add", add)
        monkeypatch.setattr(flow.resolution_engine, "resolve", lambda _: pytest.fail("Resolution replayed"))
        assert processor.dispatch_with_evidence(event) == evidence
        processor.dispatch_with_evidence(event)
    assert len(_results(store)) == 1 and len(history.get_events()) == 1
    assert world.environment["door-1"].is_open is False


def test_precommit_append_failure_never_delivers_result(monkeypatch):
    world, clock, history, store, fence, processor, flow = _fixture()
    with fence.operation():
        event = flow.execute(_attempt(), simulation_tick=clock.capture())
        def unavailable(*args, **kwargs):
            raise OSError("history unavailable")
        monkeypatch.setattr(history, "append", unavailable)
        with pytest.raises(OSError):
            processor.dispatch_with_evidence(event)
    assert history.requires_recovery() and fence.recovery_required
    assert not history.get_events() and not store.all()
    assert world.environment["door-1"].is_open is False


@pytest.mark.parametrize("unsupported", ["method", "condition", "no_source", "missing_read", "wrong_target"])
def test_controlled_but_ineligible_failure_is_not_a_result(unsupported):
    from _trusted_event_support import FixedResolutionEngine
    from cognitive_world.resolution.engine import ResolutionDecision
    world, clock, history, store, fence, processor, flow = _fixture()
    with fence.operation():
        attempt = _attempt()
        result, _ = flow.execute_with_result(attempt, simulation_tick=clock.capture())
        metadata = deepcopy(result.metadata)
        if unsupported == "method":
            attempt = _attempt("wait beside the door")
        elif unsupported == "condition":
            metadata["confirmed_failure_conditions"]["conditions"] = ("door_locked", "tool_missing")
        elif unsupported == "no_source":
            metadata.pop("confirmed_failure_conditions")
        elif unsupported == "missing_read":
            metadata["confirmed_failure_conditions"]["state_slot_reads"] = ()
        else:
            from cognitive_world.decision import ActionPipeline, ActionProposal
            attempt = ActionPipeline().create_attempt(ActionProposal(
                "proposal-other", "agent-1", "enter the next room", ["missing-door"],
                {"method": "push the door"}))
        controlled_flow = ActionResolutionFlow(
            FixedResolutionEngine(ResolutionDecision(False, "not a causal explanation", metadata=metadata)),
            world_state=world)
        event = controlled_flow.execute(attempt, simulation_tick=clock.capture())
        if unsupported == "wrong_target":
            with pytest.raises(PermissionError):
                processor.dispatch_with_evidence(event)
            assert not history.get_events()
        else:
            processor.dispatch_with_evidence(event)
            assert len(history.get_events()) == 1
    assert not _results(store) and world.environment["door-1"].is_open is False


def test_handler_cannot_manufacture_reserved_result_fact():
    class ForgedHandler(ResolutionEffectsHandler):
        def observable_facts(self, event, update):
            return (ObservableFactDraft("action_result", "door_open_attempt_failed", True,
                                       subject_ref="door-1", location_id="door_contact"),)
    world, clock, history, store, fence, processor, flow = _fixture()
    processor.register_handler("resolution", ForgedHandler())
    with fence.operation():
        event = flow.execute(_attempt(), simulation_tick=clock.capture())
        with pytest.raises(PermissionError, match="issued only by EventProcessor"):
            processor.dispatch_with_evidence(event)
    assert not history.get_events() and not store.all()


def test_generation_change_after_commit_blocks_stale_delivery_retry(monkeypatch):
    world, clock, history, store, fence, processor, flow = _fixture()
    add = store.add
    with fence.operation():
        event = flow.execute(_attempt(), simulation_tick=clock.capture())
        context = copy_context()
        def unavailable(observation):
            raise OSError("delivery unavailable")
        monkeypatch.setattr(store, "add", unavailable)
        with pytest.raises(RuntimeError, match="Observation delivery failed"):
            processor.dispatch_with_evidence(event)
    fence.freeze_and_advance()
    fence.unfreeze()
    monkeypatch.setattr(store, "add", add)
    with pytest.raises(PermissionError):
        context.run(processor.dispatch_with_evidence, event)
    assert len(history.get_events()) == 1 and not store.all()
    assert world.environment["door-1"].is_open is False


@pytest.mark.parametrize("missing", ["entity", "location", "typed_door", "tick"])
def test_canonical_context_incomplete_cannot_publish_result(missing):
    from cognitive_world.core.world_state import WorldState
    world, clock, history, store, fence, processor, flow = _fixture()
    with fence.operation():
        event = flow.execute(_attempt(), simulation_tick=clock.capture())
        if missing == "tick":
            processor.simulation_clock = SimulationClock(10)
        else:
            # Independent initialization fixture with an intentionally missing
            # canonical component, not mutation of a live WorldState.
            incomplete = WorldState()
            incomplete.load_environment_data("door-1", world.environment["door-1"])
            if missing != "entity":
                incomplete.load_entity(world.get_entity("agent-1"))
            if missing != "location":
                incomplete.load_location("agent-1", "door_contact")
            if missing == "typed_door":
                incomplete = WorldState()
                incomplete.load_environment_data("door-1", {"is_locked": True, "is_open": False})
                incomplete.load_entity(world.get_entity("agent-1"))
                incomplete.load_location("agent-1", "door_contact")
            processor.world_state = incomplete
        if missing == "typed_door":
            with pytest.raises(PermissionError):
                processor.dispatch_with_evidence(event)
            assert not history.get_events()
        else:
            processor.dispatch_with_evidence(event)
            assert len(history.get_events()) == 1
    assert not _results(store)


def test_untrusted_copy_of_source_event_cannot_publish():
    from cognitive_world.core.event import Event
    world, clock, history, store, fence, processor, flow = _fixture()
    with fence.operation():
        event = flow.execute(_attempt(), simulation_tick=clock.capture())
        forged = Event(event.id, event.type, event.timestamp, cause=event.cause,
                       changes=deepcopy(event.changes), metadata=deepcopy(event.metadata),
                       simulation_tick=event.simulation_tick)
        with pytest.raises(ValueError, match="intact Event from a controlled source"):
            processor.dispatch_with_evidence(forged)
    assert not history.get_events() and not store.all()
