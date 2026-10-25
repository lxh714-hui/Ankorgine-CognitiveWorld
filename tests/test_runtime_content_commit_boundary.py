"""Real installation commit, scheduling and signed checkpoint boundaries."""
from threading import Event as Signal, Thread, current_thread

import pytest

from cognitive_world.agent import AgentActionLoop, AgentTurn, Character, CognitionContext, RuntimeAgent
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.cognition import CognitionContainer, MemoryStore
from cognitive_world.content import ContentRegistry, ContentValidator, RuntimeContentInstaller, installation_record_key, scenario_state_key
from cognitive_world.content.persistence import scenario_snapshot_codec
from cognitive_world.core.persistence import HmacPersistenceTrust
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision import AgentDecision
from cognitive_world.event.history import EventHistory, EventProcessingStatus
from cognitive_world.event.processor import EventProcessor
from cognitive_world.observation.store import ObservationStore
from cognitive_world.resolution.causal import MethodBasedResolutionEngine
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.runtime.scheduler import EventScheduler
from cognitive_world.runtime.agent_scheduler import AgentScheduler
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.write_fence import RuntimeWriteFence
from cognitive_world.runtime.conflict_opportunity import ConflictOpportunityScheduler
from cognitive_world.safety.governance import UniversalSafetyGovernance
from test_reusable_world_content import proposal
from test_runtime_content_installation import installation_world


def _signed_runtime(trust=None, inputs=None):
    from cognitive_world.decision.evidence_review import DeterministicLocalEvidenceReviewProvider
    trust = trust or HmacPersistenceTrust(b'content-boundary-test-trust-material-32')
    world = WorldState() if inputs is None else inputs.world_state
    history = EventHistory(timeline_id='content-parent') if inputs is None else inputs.event_history
    clock = SimulationClock() if inputs is None else inputs.clock
    fence = RuntimeWriteFence() if inputs is None else inputs.write_fence
    cognition = CognitionContainer() if inputs is None else inputs.cognition
    memory = MemoryStore() if inputs is None else inputs.memory_store
    agents, observations = AgentRegistry(), ObservationStore()
    links = {} if inputs is None else {item.agent_id: item for item in inputs.agent_links}
    if inputs is not None:
        for entry in inputs.expected_agents:
            agents.register(RuntimeAgent(entry.agent_id, entry.character_id,
                                         goal_ids=list(links[entry.agent_id].goal_ids)))
    safety = UniversalSafetyGovernance()
    context = RuntimeContext(clock, world, history, event_scheduler=EventScheduler(),
        agent_scheduler=AgentScheduler(), agent_registry=agents, observation_store=observations,
        safety_governance=safety)
    processor = EventProcessor(world_state=world, event_history=history, simulation_clock=clock,
        agent_registry=agents, observation_store=observations, persistence_trust=trust,
        persistence_codec=scenario_snapshot_codec(), write_fence=fence)
    loop = AgentActionLoop(agent_turn=AgentTurn(write_fence=fence), write_fence=fence,
        safety_governance=safety, action_resolution_flow=ActionResolutionFlow(
            resolution_engine=MethodBasedResolutionEngine(world_state=world),
            world_state=world, event_history=history, safety_governance=safety))

    def provide(agent):
        link = links.get(agent.agent_id)
        character = (Character(agent.character_id, agent.agent_id, agent.agent_id,
                               goal_ids=list(agent.goal_ids)) if link is None else
                     Character(link.character_id, link.agent_id, link.personality_id or '',
                         list(link.memory_ids), list(link.belief_ids), link.emotion_id or '',
                         goal_ids=list(link.goal_ids)))
        return CognitionContext.from_character(character, cognition, memory, observation_store=observations)

    restored = {} if inputs is None else dict(behavior_feedback=inputs.behavior_feedback,
                                             behavior_feedback_status=inputs.behavior_feedback_status)
    runtime = SimulationRuntime(context, event_processor=processor, write_fence=fence,
        agent_action_loop=loop, cognition_context_provider=provide, agent_decision=AgentDecision(),
        evidence_review_provider=DeterministicLocalEvidenceReviewProvider(),
        conflict_opportunity_scheduler=ConflictOpportunityScheduler(),
        allow_environment_provider_discovery=False, strict_dependency_binding=inputs is not None,
        **restored)
    cognition.bind_write_fence(fence)
    memory.bind_write_fence(fence)
    registry = ContentRegistry(ContentValidator(safety))
    installer = RuntimeContentInstaller(context, processor, registry, cognition, agents)
    return runtime, cognition, memory, installer


def _install(installer):
    return installer.install_proposal(proposal(), template_id='archive-visit', instance_id='one',
                                      world_id='content-world', source_id='test-host')


def test_ready_committed_delivery_failure_retains_agent_and_truthful_pending(monkeypatch):
    world, cognition, agents, context, processor, _, installer = installation_world()
    complete = context.event_history.mark_observations_complete

    def fail_completion(event_id):
        if event_id == 'runtime-content-ready:content-world:one':
            raise RuntimeError('injected post-commit delivery failure')
        return complete(event_id)

    monkeypatch.setattr(context.event_history, 'mark_observations_complete', fail_completion)
    with pytest.raises(RuntimeError, match='Observation delivery failed'):
        _install(installer)
    record = world.facts[installation_record_key('content-world', 'one')]
    assert record.status == 'ready'
    assert world.facts[scenario_state_key('content-world', 'one')].phase.value == 'available'
    ready = context.event_history.get_event(record.completion_event_id)
    assert ready is not None
    assert context.event_history.get_processing_evidence(ready.id).has_trusted_source(ready)
    assert context.event_history.get_processing_status(ready.id) is EventProcessingStatus.OBSERVATIONS_PENDING
    actor = 'content-world:one:agent:curator'
    assert agents.get(actor) is not None
    assert cognition.get_personality(actor) is not None and cognition.get_self_model(actor) is not None
    assert not context.event_history.requires_recovery()


def test_standard_signed_runtime_can_commit_installation():
    runtime, cognition, _, installer = _signed_runtime()
    with runtime.write_fence.operation():
        instance = _install(installer)
    history = runtime.context.event_history
    record = runtime.context.world_state.facts[installation_record_key('content-world', 'one')]
    assert record.status == 'ready'
    assert [event.type for event in history.get_events()] == ['runtime_content_installed', 'runtime_content_ready']
    for event in history.get_events():
        assert history.get_processing_evidence(event.id).has_trusted_source(event)
        assert history.get_persistence_record(event.id) is not None
    history.verify_persisted_lineage(codec=runtime.event_processor.persistence_codec,
                                    trust=runtime.event_processor.persistence_trust)
    assert runtime.context.agent_registry.get(instance.characters[0].agent_id) is not None
    assert not runtime.write_fence.recovery_required



def test_runner_waits_for_registration_to_ready_boundary(monkeypatch):
    from cognitive_world.runtime.autonomous_runner import AutonomousWorldRunner
    world, cognition, agents, context, processor, _, installer = installation_world()
    memory = MemoryStore()

    def provide(agent):
        return CognitionContext.from_character(
            Character(agent.character_id, agent.agent_id, agent.agent_id, goal_ids=list(agent.goal_ids)),
            cognition, memory, observation_store=context.observation_store)

    loop = AgentActionLoop(action_resolution_flow=ActionResolutionFlow(
        resolution_engine=MethodBasedResolutionEngine(world_state=world), world_state=world))
    runtime = SimulationRuntime(context, event_processor=processor, cognition_context_provider=provide,
        agent_action_loop=loop, agent_decision=AgentDecision(), allow_environment_provider_discovery=False)
    cognition.bind_write_fence(runtime.write_fence)
    registered, release, enumeration = Signal(), Signal(), Signal()
    acquired_while_pending, schedules, errors = [], [], []
    register, all_agents = agents.register, agents.all_agents
    schedule = context.agent_scheduler.schedule_agent

    def pause_register(agent):
        register(agent)
        registered.set()
        if not release.wait(10):
            raise TimeoutError('installer release signal missing')

    def observe_enumeration():
        if current_thread().name == 'content-runner' and not enumeration.is_set():
            acquired = agents._lock.acquire(blocking=False)
            if acquired:
                agents._lock.release()
            acquired_while_pending.append(acquired)
            enumeration.set()
        return all_agents()

    def observe_schedule(agent_id, tick):
        record = world.facts.get(installation_record_key('content-world', 'one'))
        schedules.append((agent_id, None if record is None else record.status,
                          context.event_history.get_event('runtime-content-ready:content-world:one') is not None))
        return schedule(agent_id, tick)

    monkeypatch.setattr(agents, 'register', pause_register)
    monkeypatch.setattr(agents, 'all_agents', observe_enumeration)
    monkeypatch.setattr(context.agent_scheduler, 'schedule_agent', observe_schedule)

    def install():
        try:
            with runtime.write_fence.operation():
                _install(installer)
        except BaseException as exc:
            errors.append(exc)

    def run():
        try:
            AutonomousWorldRunner(runtime).run_round()
        except BaseException as exc:
            errors.append(exc)

    installing = Thread(target=install, name='content-installer', daemon=True)
    running = Thread(target=run, name='content-runner', daemon=True)
    installing.start()
    try:
        assert registered.wait(10)
        assert context.event_history.get_event('runtime-content-ready:content-world:one') is None
        running.start()
        assert enumeration.wait(10)
    finally:
        release.set()
        installing.join(10)
        if running.ident is not None:
            running.join(10)
    assert not installing.is_alive() and not running.is_alive()
    assert acquired_while_pending == [False]
    assert errors == []
    assert schedules and all(status == 'ready' and committed for _, status, committed in schedules)



@pytest.mark.parametrize('failure', ['before-ready', 'registration-before-write', 'registration-after-write'])
def test_pre_ready_failure_removes_only_this_requests_agents(monkeypatch, failure):
    from dataclasses import replace
    world, cognition, agents, context, processor, _, installer = installation_world()
    value = proposal()
    value = replace(value, scenarios=(replace(value.scenarios[0], characters=(
        *value.scenarios[0].characters, ('visitor', 'curator', 'hall'))),))
    handle = installer._handler.handle_with_world_state
    register = agents.register
    calls = []

    def fail_handle(event, state):
        if failure == 'before-ready' and event.type == 'runtime_content_ready':
            raise RuntimeError('injected pre-ready failure')
        return handle(event, state)

    def fail_register(agent):
        calls.append(agent.agent_id)
        if len(calls) == 2 and failure == 'registration-before-write':
            raise RuntimeError('injected registration failure')
        register(agent)
        if len(calls) == 2 and failure == 'registration-after-write':
            raise RuntimeError('injected registration failure after write')

    monkeypatch.setattr(installer._handler, 'handle_with_world_state', fail_handle)
    monkeypatch.setattr(agents, 'register', fail_register)
    with pytest.raises(RuntimeError, match='injected'):
        installer.install_proposal(value, template_id='archive-visit', instance_id='one',
                                   world_id='content-world', source_id='test-host')
    record = world.facts[installation_record_key('content-world', 'one')]
    assert record.status == 'world_installed'
    assert context.event_history.get_event(record.installation_event_id) is not None
    assert context.event_history.get_event('runtime-content-ready:content-world:one') is None
    assert scenario_state_key('content-world', 'one') not in world.facts
    assert agents.all_agents() == ()
    assert cognition.get_personality('content-world:one:agent:curator') is not None
    assert not context.event_history.requires_recovery()


def test_late_agent_identity_claim_is_not_overwritten_or_removed(monkeypatch):
    world, cognition, agents, context, _, _, installer = installation_world()
    add_goal = cognition.add_goal
    foreign = RuntimeAgent('content-world:one:agent:curator', 'another-host-character')

    def claim_after_prepare(goal):
        add_goal(goal)
        agents.register(foreign)

    monkeypatch.setattr(cognition, 'add_goal', claim_after_prepare)
    with pytest.raises(ValueError, match='claimed'):
        _install(installer)
    assert agents.get(foreign.agent_id) == foreign
    assert world.facts[installation_record_key('content-world', 'one')].status == 'world_installed'
    assert context.event_history.get_event('runtime-content-ready:content-world:one') is None


def test_signed_ready_delivery_retry_preserves_event_bytes_and_does_not_reapply(monkeypatch):
    import cognitive_world.event.processor as processor_module
    runtime, cognition, _, installer = _signed_runtime()
    processor = runtime.event_processor
    history = runtime.context.event_history
    complete = history.mark_observations_complete
    persisted, applied = [], []
    make_record = processor_module.make_persisted_event_record
    apply = runtime.context.world_state.apply_event

    def record(*args, **kwargs):
        persisted.append(args[0].id)
        return make_record(*args, **kwargs)

    def apply_event(event, update):
        applied.append(event.id)
        return apply(event, update)

    def fail_completion(event_id):
        if event_id == 'runtime-content-ready:content-world:one':
            raise RuntimeError('injected ready delivery failure')
        return complete(event_id)

    monkeypatch.setattr(processor_module, 'make_persisted_event_record', record)
    monkeypatch.setattr(runtime.context.world_state, 'apply_event', apply_event)
    monkeypatch.setattr(history, 'mark_observations_complete', fail_completion)
    with runtime.write_fence.operation():
        with pytest.raises(RuntimeError, match='Observation delivery failed'):
            _install(installer)
        ready = history.get_event('runtime-content-ready:content-world:one')
        assert ready is not None
        original_evidence = history.get_processing_evidence(ready.id)
        before = [history.get_persistence_record(e.id).to_json_record() for e in history.get_events()]
        assert len(persisted) == len(applied) == len(before) == 2
        assert history.get_processing_status(ready.id) is EventProcessingStatus.OBSERVATIONS_PENDING
        actor = 'content-world:one:agent:curator'
        assert runtime.context.agent_registry.get(actor) is not None and cognition.get_personality(actor) is not None
        assert not runtime.write_fence.recovery_required
        monkeypatch.setattr(history, 'mark_observations_complete', complete)
        # Explicit retry in the original authorized operation; no new task authority.
        processor.dispatch_with_evidence(ready)
        assert history.get_processing_status(ready.id) is EventProcessingStatus.COMPLETE
        assert history.get_processing_evidence(ready.id) == original_evidence
        assert [history.get_persistence_record(e.id).to_json_record() for e in history.get_events()] == before
        assert len(persisted) == len(applied) == 2
        with pytest.raises(ValueError):
            installer.install_registered('archive-visit', 'one', 'content-world')
    with runtime.write_fence.operation():
        with pytest.raises(PermissionError, match='runtime operation'):
            processor.dispatch_with_evidence(ready)
    assert len(persisted) == len(applied) == len(history.get_events()) == 2



class _ContentAssembler:
    def __init__(self, trust):
        self.trust = trust

    def assemble(self, inputs):
        runtime, _, _, self.installer = _signed_runtime(self.trust, inputs)
        # Host-provided definitions, not inferred/recreated historical world state.
        self.installer.registry.register(proposal())
        return runtime


def test_signed_installation_checkpoint_decodes_and_restores_without_resigning(tmp_path, monkeypatch):
    from cognitive_world.runtime.save_manager import SaveManager
    from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
    from test_runtime_reconstruction import _dependency_manifest
    runtime, cognition, memory, installer = _signed_runtime()
    with runtime.write_fence.operation():
        instance = _install(installer)
    trust = runtime.event_processor.persistence_trust
    manager = SaveManager(tmp_path / 'saves', trust=trust, codec=scenario_snapshot_codec())
    contexts = tuple(runtime.cognition_context_provider(a) for a in runtime.context.agent_registry.all_agents())
    saved = manager.create_manual_save(runtime=runtime, cognition=cognition, memory_store=memory,
                                       agent_contexts=contexts)
    verified = manager.load_verified(saved.save_id, timeline_id=saved.timeline_id)
    assert verified.metadata.save_id == saved.save_id
    original_record = runtime.context.world_state.facts[installation_record_key('content-world', 'one')]
    before_events = runtime.context.event_history.get_events()
    before_records = [runtime.context.event_history.get_persistence_record(e.id).to_json_record() for e in before_events]
    import cognitive_world.event.processor as processor_module

    def forbid_new_history(*args, **kwargs):
        pytest.fail('restore must not reissue historical Event attestations')

    monkeypatch.setattr(processor_module, 'make_persisted_event_record', forbid_new_history)
    assembler = _ContentAssembler(trust)
    staged = manager.stage_restore(saved.save_id, timeline_id=saved.timeline_id, active_runtime=runtime,
        assembler=assembler, dependencies=_dependency_manifest(), new_timeline_id='content-child')
    child = RestoreCoordinator(ActiveRuntimeSlot(runtime)).activate(staged)
    record = child.context.world_state.facts[installation_record_key('content-world', 'one')]
    assert record == original_record and record.status == 'ready'
    assert child.context.world_state.facts[scenario_state_key('content-world', 'one')].phase.value == 'available'
    assert child.context.event_history.get_events() == before_events
    assert [child.context.event_history.get_persistence_record(e.id).to_json_record() for e in before_events] == before_records
    actor = instance.characters[0].agent_id
    assert child.context.agent_registry.get(actor) is not None
    restored_cognition = child.cognition_context_provider(child.context.agent_registry.get(actor))
    assert restored_cognition.get_personality() == contexts[0].get_personality()
    assert restored_cognition.get_self_model() == contexts[0].get_self_model()
    with child.write_fence.operation():
        with pytest.raises(ValueError):
            assembler.installer.install_registered('archive-visit', 'one', 'content-world')
    assert not child.write_fence.recovery_required


def test_codec_is_closed_and_existing_scenario_bytes_do_not_change():
    from dataclasses import dataclass
    from cognitive_world.cognition.snapshot import cognitive_snapshot_codec
    from cognitive_world.content.runtime import ScenarioPhase, ScenarioRuntimeState
    runtime, _, _, installer = _signed_runtime()
    with runtime.write_fence.operation():
        _install(installer)
    codec = scenario_snapshot_codec()
    record = runtime.context.world_state.facts[installation_record_key('content-world', 'one')]
    assert codec.loads(codec.dumps(record)) == record
    state = runtime.context.world_state.facts[scenario_state_key('content-world', 'one')]
    legacy = cognitive_snapshot_codec()
    legacy.register_type(ScenarioPhase)
    legacy.register_type(ScenarioRuntimeState)
    assert codec.dumps(state) == legacy.dumps(state)
    assert codec.loads(legacy.dumps(state)) == state
    encoded = codec.encode(record)
    encoded['fields']['status'] = 'invented'
    with pytest.raises(ValueError):
        codec.decode(encoded)
    encoded = codec.encode(record)
    encoded['fields']['unapproved_field'] = True
    with pytest.raises(ValueError, match='schema mismatch'):
        codec.decode(encoded)
    with pytest.raises(ValueError, match='unregistered'):
        codec.decode({'$record': 'unapproved.module:FutureRecord', 'fields': {}})

    @dataclass
    class Unknown:
        value: int

    with pytest.raises(TypeError, match='unregistered'):
        codec.dumps(Unknown(1))


@pytest.mark.parametrize('phase', ['world', 'ready'])
def test_encoding_failure_keeps_existing_recovery_protection(monkeypatch, phase):
    from cognitive_world.core.update import WorldUpdate
    runtime, _, _, installer = _signed_runtime()
    codec = runtime.event_processor.persistence_codec
    dumps = codec.dumps

    def fail_update(value):
        if isinstance(value, WorldUpdate) and (
                (phase == 'world' and value.target_id == 'runtime_content') or
                (phase == 'ready' and isinstance(value.payload, dict)
                 and installation_record_key('content-world', 'one') in value.payload)):
            raise TypeError('injected update encoding failure')
        return dumps(value)

    monkeypatch.setattr(codec, 'dumps', fail_update)
    with runtime.write_fence.operation():
        with pytest.raises(TypeError, match='injected'):
            _install(installer)
    history = runtime.context.event_history
    record = runtime.context.world_state.facts[installation_record_key('content-world', 'one')]
    assert record.status == ('world_installed' if phase == 'world' else 'ready')
    assert history.get_event('runtime-content-ready:content-world:one') is None
    assert (history.get_event(record.installation_event_id) is not None) == (phase == 'ready')
    assert runtime.write_fence.recovery_required and history.requires_recovery()
    assert len(runtime.context.agent_registry.all_agents()) == (0 if phase == 'world' else 1)
    before_events = history.get_events()
    with pytest.raises(PermissionError):
        with runtime.write_fence.operation():
            _install(installer)
    assert history.get_events() == before_events



def test_proactive_expansion_reports_committed_delivery_pending_without_reinstall(monkeypatch):
    from test_proactive_world_expansion import _runtime
    from cognitive_world.content import ProactiveContentExpansion
    from cognitive_world.runtime.autonomous_runner import AutonomousWorldRunner
    runtime, world, cognition, agents, context, processor, _, installer, lifecycle, actor, policy, generator, expansion = _runtime()
    complete = context.event_history.mark_observations_complete

    def fail_ready_delivery(event_id):
        if event_id.startswith('runtime-content-ready:world-one:proactive-'):
            raise RuntimeError('injected proactive ready delivery failure')
        return complete(event_id)

    monkeypatch.setattr(context.event_history, 'mark_observations_complete', fail_ready_delivery)
    AutonomousWorldRunner(runtime).run(1)
    result, = runtime.last_content_expansion_results
    assert result.status == 'observations_pending' and result.failure_type == 'RuntimeError'
    record = world.facts[installation_record_key('world-one', result.instance_id)]
    assert record.status == 'ready'
    assert context.event_history.get_processing_status(record.completion_event_id) is EventProcessingStatus.OBSERVATIONS_PENDING
    assert agents.get('world-one:' + result.instance_id + ':agent:curator') is not None
    before = context.event_history.get_events()
    replacement = ProactiveContentExpansion(installer, lifecycle, world_id='world-one',
        scheduler=runtime.conflict_opportunity_scheduler, need_policy=policy,
        generator_factory=lambda request: generator)
    finding = runtime.last_agent_turn_results[0].scheduler_findings
    repeated = replacement.expand(finding, simulation_tick=context.clock.current_time)
    assert repeated[0].status == 'observations_pending'
    assert context.event_history.get_events() == before and generator.calls == 1


def test_installation_batch_codec_roundtrip_rejects_invalid_existing_fields():
    from cognitive_world.content.installation import WorldContentBatch, ContentInstallationRecord
    from cognitive_world.content.pipeline import ContentInstantiator
    from cognitive_world.content.models import ScenarioInstance
    runtime, cognition, _, installer = _signed_runtime()
    installer.registry.register(proposal())
    plan = ContentInstantiator(installer.registry).prepare('archive-visit', 'one', 'content-world',
        world=runtime.context.world_state, cognition=cognition,
        agents=runtime.context.agent_registry, clock=runtime.context.clock)
    record = ContentInstallationRecord('content-world', 'one', 'archive-visit', 'host', None, 0,
                                      'world_installed', 'runtime-content:content-world:one')
    batch = WorldContentBatch(plan.entities, plan.locations, plan.environment,
                             installation_record_key('content-world', 'one'), record)
    codec = scenario_snapshot_codec()
    assert codec.loads(codec.dumps(batch)) == batch
    encoded = codec.encode(batch)
    encoded['fields']['entities'] = {'$tuple': ['untyped-entity']}
    with pytest.raises(TypeError):
        codec.decode(encoded)
    encoded = codec.encode(record)
    encoded['fields']['installation_tick'] = True
    with pytest.raises(ValueError):
        codec.decode(encoded)
    # Registering installation records does not admit every content dataclass.
    assert codec._name(ScenarioInstance) not in codec._types



def test_unrelated_event_with_ready_id_is_not_treated_as_ready_commit():
    from cognitive_world.event.handler import EventHandler
    from cognitive_world.event.factory import SystemEventFactory
    from cognitive_world.core.update import WorldUpdate
    world, _, agents, context, processor, _, installer = installation_world()

    class UnrelatedHandler(EventHandler):
        def handle(self, event):
            return WorldUpdate('facts', 'update', {})

    processor.register_handler('unrelated_content_event', UnrelatedHandler())
    unrelated = SystemEventFactory().create(
        event_id='runtime-content-ready:content-world:one', event_type='unrelated_content_event',
        timestamp='', simulation_tick=context.clock.current_time)
    processor.dispatch_with_evidence(unrelated)
    with pytest.raises(ValueError):
        _install(installer)
    assert context.event_history.get_event(unrelated.id) == unrelated
    assert world.facts[installation_record_key('content-world', 'one')].status == 'world_installed'
    assert scenario_state_key('content-world', 'one') not in world.facts
    assert agents.all_agents() == ()
