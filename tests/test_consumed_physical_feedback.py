"""Actual NPC turns, consumption proofs and signed checkpoint feedback."""
from dataclasses import replace
import json
import pytest
from test_interaction_range import document
from test_position_observation import Scene
from cognitive_world.agent import AgentActionLoop, AgentTurn, Character, CognitionContext
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.decision import AgentDecision
from cognitive_world.decision.autonomous import ActionCandidate, CandidateEvaluation
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.causal import MethodBasedResolutionEngine
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.agent_scheduler import AgentScheduler
from cognitive_world.event import SystemEventFactory
from cognitive_world.content.persistence import scenario_snapshot_codec
from cognitive_world.runtime.save_manager import SaveManager
from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
from cognitive_world.decision.behavior_feedback_snapshot import BehaviorFeedbackSnapshot
from test_runtime_reconstruction import _dependency_manifest


class Choices:
    def __init__(self,target,route): self.target,self.route=target,route
    def generate(self,situation):
        seen=next((f for f in situation.observed_facts if f.subject_ref==self.target),None)
        wait=ActionCandidate("wait",situation.owner_id,None,"Wait",None,"wait",(),(),(),("Wait.",),"Unknown.",(),0.,0.,.1,(),"content")
        if seen is None or any(f.subject_ref==self.target and f.predicate=="door_open" and f.value=="True" for f in situation.observed_facts):return (wait,)
        goal=next(g for g in situation.goals if g.status=="active")
        state_refs=tuple(f.percept_id for f in situation.observed_facts
            if f.subject_ref==self.target and f.fact_type=="environment_state")
        references=state_refs or (seen.percept_id,)
        def candidate(identity,intent,target,method,capability):
            return ActionCandidate(identity,situation.owner_id,goal.goal_id,intent,"object:"+target,
                method,(),(capability,),(),(method,),"Adjudicate the attempt.",(),.1,.1,.5,references,"content")
        return (wait,candidate("open","Open",self.target,"push open the door","manual_manipulation"),
            candidate("approach","Move",self.route,"walk through the passage","locomotion"))

class Scores:
    def evaluate(self,situation,candidates):
        return tuple(CandidateEvaluation(c.candidate_id,{"open":.9,"approach":.8,"wait":.1}[c.candidate_id],(),c.uncertainties) for c in candidates)
class NoReview:
    def should_review(self,*args):return False


class Host:
    def __init__(self,inputs=None,trust=None,data=None):
        if inputs is None:
            data=document() if data is None else data
            data["locations"][0]["mechanisms"][0]["destination_key"]="target"
            self.scene=Scene(data)
            world,cognition,agents,clock,history,store,processor=(self.scene.world,self.scene.cognition,
                self.scene.agents,self.scene.clock,self.scene.history,self.scene.store,self.scene.processor)
            self.trust=self.scene.trust;memory=MemoryStore()
        else:
            from test_runtime_content_commit_boundary import _signed_runtime
            rt,cognition,memory,_=_signed_runtime(trust,inputs)
            self.trust=trust;self.runtime=rt;self.cognition=cognition;self.memory=memory
            self._policy();return
        context=RuntimeContext(clock,world,history,agent_registry=agents,agent_scheduler=AgentScheduler(),observation_store=store)
        def provide(agent):return CognitionContext.from_character(Character(agent.character_id,agent.agent_id,
            agent.agent_id,goal_ids=list(agent.goal_ids)),cognition,memory,observation_store=store)
        loop=AgentActionLoop(agent_turn=AgentTurn(),action_resolution_flow=ActionResolutionFlow(
            MethodBasedResolutionEngine(world_state=world),world_state=world,event_history=history))
        self.runtime=SimulationRuntime(context,event_processor=processor,agent_action_loop=loop,
            cognition_context_provider=provide,allow_environment_provider_discovery=False)
        cognition.bind_write_fence(self.runtime.write_fence);memory.bind_write_fence(self.runtime.write_fence)
        self.cognition,self.memory=cognition,memory;self._policy()
        self.scene.target=self.target;self.scene.observe()
        with self.runtime.write_fence.operation():
            processor.dispatch_with_evidence(SystemEventFactory().create(event_id="route-view",event_type="environment_state_observed",
                timestamp="0",simulation_tick=0,changes=[{"environment_id":self.route}]))
    owner="world:one:agent:worker"
    target="world:one:mechanism:target/door"
    route="world:one:mechanism:far/route"
    def _policy(self):
        self.runtime.agent_decision=AgentDecision(candidate_policy=Choices(self.target,self.route),evaluation_policy=Scores(),review_policy=NoReview())
    def advance(self):
        rt=self.runtime;rt.context.agent_scheduler.schedule_agent(self.owner,rt.context.clock.current_time+1)
        rt.step();turn,=rt.last_agent_turn_results
        assert turn.failure_type is None
        return turn
    def consume(self):
        rt=self.runtime;actor=rt.context.agent_registry.get(self.owner)
        with rt.write_fence.operation():return rt.agent_action_loop.agent_turn.prepare_decision_context(
            actor,rt.cognition_context_provider(actor),simulation_tick=rt.context.clock.capture())
    def save(self,root):
        manager=SaveManager(root,trust=self.trust,codec=scenario_snapshot_codec());rt=self.runtime
        saved=manager.create_manual_save(runtime=rt,cognition=self.cognition,memory_store=self.memory,
            agent_contexts=tuple(rt.cognition_context_provider(a) for a in rt.context.agent_registry.all_agents()))
        return manager,saved


def test_actual_consumption_changes_next_choice_and_movement_releases_penalty():
    host=Host();rt=host.runtime
    failure=host.advance()
    assert failure.execution.resolution.success is False and failure.event_committed
    event=failure.execution.event
    assert event.metadata["confirmed_attempt_failure"]["verified_conditions"]==("interaction_out_of_reach",)
    assert not rt.context.world_state.environment[host.target].is_open
    assert rt.behavior_feedback.history==[]
    observation,=(o for o in rt.context.observation_store.get_by_observer(host.owner) if o.source_event_id==event.id)
    assert not any(o.source_event_id==event.id for o in rt.context.observation_store.get_by_observer("world:one:agent:other"))
    host.consume()
    assert len(rt.behavior_feedback.history)==1
    record=rt.behavior_feedback.history[0]
    assert record.consumption is not None
    proof=host.memory.get_memory(record.consumption.proof_id).content
    assert proof.observation_id==observation.observation_id and proof.source_event_id==event.id
    host.consume();assert rt.behavior_feedback.history==[record]
    movement=host.advance()
    assert movement.execution.proposal.action_type=="Move"
    assert rt.context.world_state.locations[host.owner]=="world:one:location:target"
    opened=host.advance()
    assert opened.execution.resolution.success and opened.execution.proposal.action_type=="Open"
    assert rt.context.world_state.environment[host.target].is_open
    assert host.advance().execution.proposal.action_type=="Wait"
    before=(list(rt.behavior_feedback.history),host.memory.get_memory(record.consumption.proof_id),tuple(rt.context.event_history.get_events()))
    # A stale original action permit cannot authorize a new dispatch operation.
    with rt.write_fence.operation(), pytest.raises(PermissionError):
        rt.event_processor.dispatch_with_evidence(event)
    from cognitive_world.observation.generator import ObservationGenerator
    evidence=rt.context.event_history.get_processing_evidence(event.id)
    for delivered in ObservationGenerator().generate_authorized(event,evidence,observer_id=host.owner,
        event_history=rt.context.event_history,source_timeline_id=rt.context.event_history.timeline_id,
        source_runtime_session_id=rt.write_fence.session_id,source_runtime_generation=rt.write_fence.restore_generation):
        rt.context.observation_store.add(delivered)
    host.consume()
    assert rt.behavior_feedback.history==before[0]
    assert host.memory.get_memory(record.consumption.proof_id)==before[1]
    assert tuple(rt.context.event_history.get_events())==before[2]
    assert len([e for e in before[2] if e.has_trusted_source("resolution")])==3


def test_feedback_proof_and_penalty_restore_without_resigning(tmp_path,monkeypatch):
    host=Host();failure=host.advance();host.consume()
    assert len(host.runtime.behavior_feedback.history)==1
    manager,saved=host.save(tmp_path/"save")
    class Assembler:
        def assemble(self,inputs):self.host=Host(inputs,host.trust);return self.host.runtime
    assembler=Assembler()
    def forbidden(*args,**kwargs):pytest.fail("restore must not re-sign old evidence")
    with monkeypatch.context() as guard:
        guard.setattr("cognitive_world.cognition.l1_consumption_proof.L1ConsumptionIssuer.issue_after_l1",forbidden)
        guard.setattr("cognitive_world.event.processor.make_persisted_event_record",forbidden)
        child=RestoreCoordinator(ActiveRuntimeSlot(host.runtime)).activate(manager.stage_restore(saved.save_id,
            timeline_id=saved.timeline_id,active_runtime=host.runtime,assembler=assembler,
            dependencies=_dependency_manifest(),new_timeline_id="feedback-child"))
    restored=assembler.host
    assert child.behavior_feedback.history==host.runtime.behavior_feedback.history
    assert not child.context.observation_store.all()
    assert child.agent_action_loop.agent_turn.cognitive_runtime._l1_consumption_receipts=={}
    # Fresh current context; no historical result consumption is manufactured.
    view=Scene.__new__(Scene);view.world=child.context.world_state;view.agents=child.context.agent_registry
    view.clock=child.context.clock;view.history=child.context.event_history;view.store=child.context.observation_store
    view.processor=child.event_processor;view.target=host.target;view.observe()
    movement=restored.advance()
    assert movement.execution.proposal.action_type=="Move"
    assert child.context.event_history.get_event(failure.execution.event.id) is not None
    assert host.runtime.context.event_history.get_event(movement.execution.event.id) is None


def capture(host):
    rt=host.runtime
    return BehaviorFeedbackSnapshot.capture(feedback=rt.behavior_feedback,event_history=rt.context.event_history,
        timeline_id=rt.context.event_history.timeline_id,simulation_tick=rt.context.clock.current_time,
        session_id=rt.write_fence.session_id,restore_generation=rt.write_fence.restore_generation,
        agent_ids=tuple(sorted(a.agent_id for a in rt.context.agent_registry.all_agents())),
        memory_store=host.memory,trust=host.trust)


def decode(host,payload,**overrides):
    rt=host.runtime
    return BehaviorFeedbackSnapshot.verify_and_restore(payload=payload,event_history=rt.context.event_history,
        timeline_id=rt.context.event_history.timeline_id,simulation_tick=rt.context.clock.current_time,
        agent_ids=tuple(sorted(a.agent_id for a in rt.context.agent_registry.all_agents())),
        memory_store=overrides.get("memory_store",host.memory),trust=host.trust)


def penalty(host,**changes):
    args=dict(owner_id=host.owner,action_type="Open",target="object:"+host.target,method="push open the door",
        facts=(),source_refs=(),tick=host.runtime.context.clock.current_time)
    args.update(changes)
    return host.runtime.behavior_feedback.penalty_for(**args)


def test_feedback_scoping_and_exact_v1_v2_encoding():
    host=Host();host.advance()
    old=capture(host);assert json.loads(old)["version"]==1
    assert not decode(host,old).feedback.history and penalty(host)==0
    host.consume();assert penalty(host)==pytest.approx(.2)
    assert penalty(host,target=host.target)==pytest.approx(.2)  # same canonical object, legacy bare spelling
    assert penalty(host,owner_id="world:one:agent:other")==0
    assert penalty(host,target="object:"+host.route)==0
    assert penalty(host,method="pull the door")==0
    payload=capture(host);raw=json.loads(payload)
    assert raw["version"]==2 and raw["failures"][0]["record_version"]==2
    restored=decode(host,payload).feedback
    assert restored.history==host.runtime.behavior_feedback.history
    with pytest.raises(PermissionError):restored.penalty_for(owner_id=host.owner,action_type="Open",target="object:"+host.target,
        method="push open the door",facts=(),source_refs=(),tick=host.runtime.context.clock.current_time)
    host.advance();assert penalty(host)==0


@pytest.mark.parametrize("change",["version","row_version","binding_version","unknown","binding_field","owner","event","proof","conditions","tick","action","target","method","duplicate","conflicting_duplicate"])
def test_malformed_and_conflicting_feedback_fails_closed(change):
    host=Host();host.advance();host.consume();raw=json.loads(capture(host));row=raw["failures"][0]
    if change=="version":raw["version"]=99
    elif change=="row_version":row["record_version"]=99
    elif change=="binding_version":row["consumption"]["version"]=99
    elif change=="unknown":row["extra"]="not accepted"
    elif change=="binding_field":row["consumption"]["claimed_consumed"]=True
    elif change=="owner":row["owner_id"]="world:one:agent:other"
    elif change=="event":row["event_id"]="uncommitted-result"
    elif change=="proof":row["consumption"]["proof_id"]="missing-proof"
    elif change=="conditions":row["conditions"][0][1]="another-location"
    elif change=="tick":row["tick"]=0
    elif change=="action":row["action_type"]="Another action"
    elif change=="target":row["target"]="object:"+host.route
    elif change=="method":row["method"]="another method"
    else:
        raw["failures"].append(json.loads(json.dumps(row)))
        if change=="conflicting_duplicate":raw["failures"][1]["method"]="another method"
    with pytest.raises((ValueError,PermissionError)):decode(host,json.dumps(raw).encode())


def test_restore_cannot_infer_missing_consumption_from_a_committed_event():
    host=Host();host.advance();host.consume();payload=capture(host)
    # A real canonical empty Store represents the negative restored component;
    # neither an Event nor a valid feedback JSON can replace the absent proof.
    with pytest.raises(PermissionError,match="proof"):
        decode(host,payload,memory_store=MemoryStore())


def test_wrong_owner_input_cannot_create_a_receipt_or_feedback():
    host=Host();turn=host.advance();rt=host.runtime
    observation,=(o for o in rt.context.observation_store.get_by_observer(host.owner)
        if o.source_event_id==turn.execution.event.id)
    other="world:one:agent:other";cognitive=rt.agent_action_loop.agent_turn.cognitive_runtime
    before=cognitive.working_memory_store.get(other)
    state=cognitive.process(other,[observation])
    assert state.percept_ids==[] and cognitive.working_memory_store.get(other)==before
    assert not cognitive.has_consumed_observation(other,observation,source_event_id=turn.execution.event.id)
    assert rt.behavior_feedback.history==[]


@pytest.mark.parametrize("failure_point",["sign","proof_commit","feedback_commit","working_memory"])
def test_post_l1_failure_freezes_capture_without_replaying_action(tmp_path,monkeypatch,failure_point):
    from cognitive_world.cognition.l1_consumption_proof import NONVERBAL_PROOF_PURPOSE
    host=Host();first=host.advance();rt=host.runtime
    initial=len(rt.context.event_history.get_events())
    if failure_point=="sign":
        original=host.trust.sign
        def fail(purpose,payload):
            if purpose==NONVERBAL_PROOF_PURPOSE:raise OSError("injected signing failure")
            return original(purpose,payload)
        monkeypatch.setattr(host.trust,"sign",fail)
    elif failure_point=="proof_commit":
        original=host.memory._commit_system_proof
        def fail(*args,**kwargs):original(*args,**kwargs);raise OSError("uncertain proof commit")
        monkeypatch.setattr(host.memory,"_commit_system_proof",fail)
    elif failure_point=="feedback_commit":
        class WriteThenRaise(list):
            def append(self,value):super().append(value);raise OSError("uncertain feedback commit")
        rt.behavior_feedback.history=WriteThenRaise()
    else:
        store=rt.agent_action_loop.agent_turn.cognitive_runtime.working_memory_store;original=store.update
        def fail(value):original(value);raise OSError("uncertain L1 mutation")
        monkeypatch.setattr(store,"update",fail)
    with pytest.raises(OSError):host.consume()
    assert rt.write_fence.recovery_required
    assert len(rt.context.event_history.get_events())==initial
    assert rt.context.event_history.get_event(first.execution.event.id) is not None
    assert not rt.context.world_state.environment[host.target].is_open
    with pytest.raises((PermissionError,RuntimeError)):
        host.save(tmp_path/"blocked")


def test_uncommitted_resolution_and_delivery_are_not_consumption():
    host=Host();rt=host.runtime;actor=rt.context.agent_registry.get(host.owner)
    with rt.write_fence.operation():
        execution=rt.agent_action_loop.run_turn_with_result(actor,rt.cognition_context_provider(actor),
            rt.agent_decision,simulation_tick=rt.context.clock.capture())
        assert not execution.resolution.success and execution.event is not None
        assert rt.context.event_history.get_event(execution.event.id) is None
        host.consume();assert rt.behavior_feedback.history==[] and penalty(host)==0
        rt.event_processor.dispatch_with_evidence(execution.event)
    assert rt.behavior_feedback.history==[] and penalty(host)==0
    host.consume();assert penalty(host)>0


def test_ambiguous_prior_ordinary_intake_is_deferred_without_freezing_or_fabricating_a_proof():
    host=Host();failure=host.advance();rt=host.runtime
    observation,=(o for o in rt.context.observation_store.get_by_observer(host.owner)
        if o.source_event_id==failure.execution.event.id)
    cognitive=rt.agent_action_loop.agent_turn.cognitive_runtime
    cognitive.process(host.owner,[observation])  # real, but not proof-protected intake
    before=tuple(host.memory.get_all_memories())
    host.consume()
    assert tuple(host.memory.get_all_memories())==before
    assert rt.behavior_feedback.history==[] and not rt.write_fence.recovery_required


def test_stale_operation_cannot_publish_consumed_feedback():
    host=Host();host.advance();rt=host.runtime;actor=rt.context.agent_registry.get(host.owner)
    memory=host.memory.get_all_memories()
    with rt.write_fence.operation():
        rt.write_fence.freeze_and_advance();rt.write_fence.unfreeze()
        with pytest.raises(PermissionError):
            rt.agent_action_loop.agent_turn.prepare_decision_context(actor,rt.cognition_context_provider(actor),
                simulation_tick=rt.context.clock.capture())
    assert rt.behavior_feedback.history==[] and host.memory.get_all_memories()==memory


def test_actual_runtime_stops_after_consumption_proof_failure(monkeypatch):
    from cognitive_world.cognition.l1_consumption_proof import NONVERBAL_PROOF_PURPOSE
    host=Host();failure=host.advance();rt=host.runtime;original=host.trust.sign
    def fail(purpose,payload):
        if purpose==NONVERBAL_PROOF_PURPOSE:raise OSError("injected post-L1 proof failure")
        return original(purpose,payload)
    monkeypatch.setattr(host.trust,"sign",fail)
    rt.context.agent_scheduler.schedule_agent(host.owner,rt.context.clock.current_time+1)
    rt.step()
    assert rt.last_agent_turn_results[0].failure_type=="OSError"
    assert rt.write_fence.recovery_required and not rt.running
    with pytest.raises(RuntimeError):rt.step()
    assert len([e for e in rt.context.event_history.get_events() if e.has_trusted_source("resolution")])==1
    assert not rt.context.world_state.environment[host.target].is_open


def test_cold_resume_and_siblings_preserve_proof_bytes_and_independent_feedback(tmp_path):
    from cognitive_world.runtime.cold_restore import ColdRuntimePublisher
    host=Host();host.advance();host.consume();manager,saved=host.save(tmp_path/"siblings")
    original=host.runtime.behavior_feedback.history[0]
    original_proof=host.memory.get_memory(original.consumption.proof_id)
    class Assembler:
        def assemble(self,inputs):self.host=Host(inputs,host.trust);return self.host.runtime
    cold=Assembler()
    parent=ColdRuntimePublisher().activate(manager.stage_cold_resume(saved.save_id,timeline_id=saved.timeline_id,
        assembler=cold,dependencies=_dependency_manifest())).current
    assert parent.behavior_feedback.history==[original]
    left,right=Assembler(),Assembler()
    child=RestoreCoordinator(ActiveRuntimeSlot(host.runtime)).activate(manager.stage_restore(saved.save_id,
        timeline_id=saved.timeline_id,active_runtime=host.runtime,assembler=left,dependencies=_dependency_manifest(),new_timeline_id="left-feedback"))
    sibling=RestoreCoordinator(ActiveRuntimeSlot(parent)).activate(manager.stage_restore(saved.save_id,
        timeline_id=saved.timeline_id,active_runtime=parent,assembler=right,dependencies=_dependency_manifest(),new_timeline_id="right-feedback"))
    assert child.behavior_feedback.history is not sibling.behavior_feedback.history
    assert left.host.memory.get_memory(original.consumption.proof_id)==original_proof
    assert right.host.memory.get_memory(original.consumption.proof_id)==original_proof
    view=Scene.__new__(Scene);view.world=child.context.world_state;view.agents=child.context.agent_registry
    view.clock=child.context.clock;view.history=child.context.event_history;view.store=child.context.observation_store
    view.processor=child.event_processor;view.target=host.target;view.observe()
    moved=left.host.advance()
    assert moved.execution.proposal.action_type=="Move"
    assert penalty(left.host)==0 and penalty(right.host)>0
    assert sibling.context.world_state.locations[host.owner]=="world:one:location:far"
    assert sibling.context.event_history.get_event(moved.execution.event.id) is None
    assert sibling.behavior_feedback.history==[original]


def test_absent_feedback_record_is_not_reconstructed_from_a_proof_alone():
    from cognitive_world.decision.behavior_feedback import BehaviorFeedback
    host=Host();host.advance();host.consume();rt=host.runtime
    payload=BehaviorFeedbackSnapshot.capture(feedback=BehaviorFeedback(),event_history=rt.context.event_history,
        timeline_id=rt.context.event_history.timeline_id,simulation_tick=rt.context.clock.current_time,
        session_id=rt.write_fence.session_id,restore_generation=rt.write_fence.restore_generation,
        agent_ids=tuple(sorted(a.agent_id for a in rt.context.agent_registry.all_agents())),
        memory_store=host.memory,trust=host.trust)
    assert not decode(host,payload).feedback.history


def test_old_result_without_a_published_proof_stays_deferred_after_cold_resume(tmp_path):
    from cognitive_world.runtime.cold_restore import ColdRuntimePublisher
    host=Host();failure=host.advance();manager,saved=host.save(tmp_path/"pending")
    class Assembler:
        def assemble(self,inputs):self.host=Host(inputs,host.trust);return self.host.runtime
    assembler=Assembler()
    resumed=ColdRuntimePublisher().activate(manager.stage_cold_resume(saved.save_id,timeline_id=saved.timeline_id,
        assembler=assembler,dependencies=_dependency_manifest())).current
    old=resumed.context.event_history.get_event(failure.execution.event.id)
    # Explicit, supported duplicate delivery; never rerun Resolution.
    resumed.event_processor.dispatch_with_evidence(old)
    before=assembler.host.memory.get_all_memories()
    assembler.host.consume()
    assert resumed.behavior_feedback.history==[] and not resumed.write_fence.recovery_required
    assert assembler.host.memory.get_all_memories()==before
    assert len([e for e in resumed.context.event_history.get_events() if e.has_trusted_source("resolution")])==1


def test_v2_mixed_history_keeps_legacy_lock_semantics_and_penalty():
    from cognitive_world.decision.autonomous import SituationFact
    data=document();data["locations"][2]["mechanisms"][0]["initially_locked"]=True
    host=Host(data=data);rt=host.runtime
    class BareReferences(Choices):
        def generate(self,situation):
            return tuple(replace(c,target=c.target.removeprefix("object:")) if c.target else c
                for c in super().generate(situation))
    rt.agent_decision.candidate_policy=BareReferences(host.target,host.route)
    assert not host.advance().execution.resolution.success
    host.consume();assert len(rt.behavior_feedback.history)==1
    assert host.advance().execution.proposal.action_type=="Move"
    with rt.write_fence.operation():
        rt.event_processor.dispatch_with_evidence(SystemEventFactory().create(event_id="locked-door-view",
            event_type="environment_state_observed",timestamp="",simulation_tick=rt.context.clock.current_time,
            changes=[{"environment_id":host.target}]))
    locked=host.advance()
    assert not locked.execution.resolution.success and locked.event_committed
    assert len(rt.behavior_feedback.history)==2
    assert rt.behavior_feedback.history[0].consumption is not None
    assert rt.behavior_feedback.history[1].consumption is None
    source=locked.execution.event.metadata["confirmed_attempt_failure"]
    facts=tuple(SituationFact("percept:"+o.observation_id,o.source_event_id,o.content.fact_type,
        o.content.predicate,str(o.content.value),o.content.fact_id)
        for o in rt.context.observation_store.get_by_observer(host.owner))
    assert rt.behavior_feedback.penalty_for(owner_id=host.owner,action_type=source["action_type"],target=source["target_refs"][0],
        method=source["method"],facts=facts,source_refs=source["source_refs"],tick=rt.context.clock.current_time)>0
    payload=capture(host);rows=json.loads(payload)["failures"]
    assert [row["record_version"] for row in rows]==[2,1]
    assert decode(host,payload).feedback.history==rt.behavior_feedback.history


@pytest.mark.parametrize("field",["version","visibility_rule","observation_sha256","fact_id"])
def test_correctly_signed_but_semantically_invalid_consumption_proof_is_rejected(field):
    from cognitive_world.cognition.l1_consumption_proof import NONVERBAL_PROOF_PURPOSE
    from cognitive_world.cognition.memory_store import _L1_PROOF_WRITE_AUTHORITY
    host=Host();host.advance();host.consume();payload=capture(host)
    failure=host.runtime.behavior_feedback.history[0]
    record=host.memory.get_memory(failure.consumption.proof_id)
    changes={"version":99,"visibility_rule":"interaction-out-of-reach-owner-result/v99",
        "observation_sha256":"0"*64,"fact_id":"missing-fact"}
    proof=replace(record.content,**{field:changes[field]})
    proof=replace(proof,signature_hex=host.trust.sign(NONVERBAL_PROOF_PURPOSE,proof.body()).hex())
    # The fixture root deliberately signs an invalid candidate. This exercises
    # semantic restore validation, without inventing or inserting any Event.
    scratch=MemoryStore();scratch.bind_write_fence(host.runtime.write_fence)
    with host.runtime.write_fence.operation() as permit:
        scratch._commit_system_proof(replace(record,content=proof),authority=_L1_PROOF_WRITE_AUTHORITY,permit=permit)
    with pytest.raises(PermissionError):decode(host,payload,memory_store=scratch)


def test_foreign_store_binding_rejects_before_consumption_without_recovery():
    from cognitive_world.decision.consumed_failure import process_with_feedback
    host,foreign=Host(),Host();failure=host.advance()
    rt=host.runtime;turn=rt.agent_action_loop.agent_turn
    observation,=(o for o in rt.context.observation_store.get_by_observer(host.owner)
        if o.source_event_id==failure.execution.event.id)
    foreign_actor=foreign.runtime.context.agent_registry.get(host.owner)
    context=foreign.runtime.cognition_context_provider(foreign_actor)
    before=turn.cognitive_runtime.working_memory_store.get(host.owner)
    with rt.write_fence.operation(),pytest.raises(PermissionError,match="binding"):
        process_with_feedback(turn,context,(observation,),beliefs=context.get_beliefs(),goals=context.get_goals())
    assert turn.cognitive_runtime.working_memory_store.get(host.owner)==before
    assert not rt.write_fence.recovery_required and rt.behavior_feedback.history==[]


@pytest.mark.parametrize("change",["world","adapter"])
def test_restore_rejects_foreign_applicability_or_missing_consumption_adapter(tmp_path,change):
    from cognitive_world.core.world_state import WorldState
    host=Host();host.advance();host.consume();manager,saved=host.save(tmp_path/"misbound")
    class BadAssembler:
        def assemble(self,inputs):
            restored=Host(inputs,host.trust).runtime
            if change=="world":restored.behavior_feedback._reach_context=(WorldState(),inputs.event_history)
            else:restored.agent_action_loop.agent_turn._consumed_failure_context=None
            return restored
    with pytest.raises((PermissionError,RuntimeError),match="consumed feedback"):
        manager.stage_restore(saved.save_id,timeline_id=saved.timeline_id,active_runtime=host.runtime,
            assembler=BadAssembler(),dependencies=_dependency_manifest(),new_timeline_id="wrong-feedback-context")
    assert not host.runtime.write_fence.frozen and not host.runtime.write_fence.recovery_required


def test_history_unavailable_defers_even_when_an_old_live_receipt_exists(monkeypatch):
    host=Host();failure=host.advance();host.consume();rt=host.runtime
    cognitive=rt.agent_action_loop.agent_turn.cognitive_runtime
    before=list(rt.behavior_feedback.history)
    memory=host.memory.get_all_memories()
    receipts=dict(cognitive._l1_consumption_receipts)
    workspace=cognitive.working_memory_store.get(host.owner)
    history=rt.context.event_history
    formal=tuple(history.get_persistence_record(e.id).to_json_record() for e in history.get_events())
    statuses=tuple((e.id,history.get_processing_status(e.id)) for e in history.get_events())
    # Temporary verification unavailability is not a new consumption and does
    # not by itself establish that an already published record is corrupted.
    def unavailable(*args,**kwargs):raise OSError("verification unavailable")
    with monkeypatch.context() as guard:
        guard.setattr(host.trust,"verify",unavailable)
        _,deferred=host.consume()
        assert deferred.percepts==[]
        assert deferred.percept_ids==[] and workspace.percept_ids
        items=deferred.metadata["l1_ingestion"]["items"]
        assert items and all(i["history"]=="undetermined" and i["consumption"]=="not_consumed" for i in items)
        assert deferred.metadata["consumed_physical_feedback"]["items"]==(
            (failure.execution.event.id,"history_undetermined"),)
        assert cognitive._l1_consumption_receipts.keys()==receipts.keys()
        assert all(cognitive._l1_consumption_receipts[key] is receipt for key,receipt in receipts.items())
        assert cognitive.working_memory_store.get(host.owner)==workspace
        assert rt.behavior_feedback.history==before and host.memory.get_all_memories()==memory
        assert tuple(history.get_persistence_record(e.id).to_json_record() for e in history.get_events())==formal
        assert tuple((e.id,history.get_processing_status(e.id)) for e in history.get_events())==statuses
        assert not rt.write_fence.recovery_required and not rt.write_fence.frozen
    issuer=rt.agent_action_loop.agent_turn.l1_consumption_issuer
    original_issue=issuer.issue_after_l1
    def forbid_old_proof(**kwargs):
        if kwargs["observation"].source_event_id==failure.execution.event.id:
            pytest.fail("resuming valid qualification must reuse the original consumption proof")
        return original_issue(**kwargs)
    with monkeypatch.context() as guard:
        # Guard proof issuance, not HMAC's signature-verification implementation.
        guard.setattr(issuer,"issue_after_l1",forbid_old_proof)
        _,resumed=host.consume()
        assert resumed.metadata["consumed_physical_feedback"]["items"]==(
            (failure.execution.event.id,"duplicate"),)
        assert all(i["history"]=="eligible" and i["consumption"]=="duplicate"
            for i in resumed.metadata["l1_ingestion"]["items"])
        assert rt.behavior_feedback.history==before and host.memory.get_all_memories()==memory
        assert cognitive.working_memory_store.get(host.owner)==workspace
        movement=host.advance()
    assert movement.execution.proposal.action_type=="Move" and movement.event_committed
    assert not rt.write_fence.recovery_required
    assert len([e for e in history.get_events() if e.id==failure.execution.event.id])==1
