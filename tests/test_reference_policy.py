from dataclasses import replace
import pytest
from cognitive_world.cognition import CognitionState, Goal
from cognitive_world.cognition.emotion_system import DecisionModulation
from cognitive_world.decision.agent_decision import AgentDecision
from cognitive_world.decision.autonomous import DeterministicActionEvaluationPolicy, DeterministicSituationAssessmentPolicy
from cognitive_world.decision.context import DecisionContext
from cognitive_world.decision.evidence_review import DeterministicLocalEvidenceReviewProvider, EvidenceAwareEvaluationPolicy
from cognitive_world.resolution.evidence import AuthorizedStateQuery
from test_authorized_state_query import runtime_with_observations
from test_autonomous_agent_decision import _candidate


def _inputs():
    context = DecisionContext(cognition_state=CognitionState('agent-a'),
        goals=(Goal('goal', 'agent-a', 'act', .5),),
        decision_modulation=DecisionModulation('agent-a', risk_bias=-.4, impulse_bias=1., impulse_probability_ceiling=1.))
    candidates = (_candidate('agent-a',candidate_id='careful',risk=.1,commitment=.1),
                  _candidate('agent-a',candidate_id='bold',risk=.9,commitment=.9))
    return context, candidates


def test_reference_excludes_impulse_and_epsilon_controls_selection():
    context, candidates = _inputs()
    situation = DeterministicSituationAssessmentPolicy().assess(context)
    evaluator = DeterministicActionEvaluationPolicy()
    actual = evaluator.evaluate(situation,candidates)
    reference = evaluator.evaluate_reference(situation,candidates)
    assert actual[1].score > actual[0].score
    assert reference[0].score > reference[1].score
    assert all(dict(item.factors)['bounded_impulse'] == 0 for item in reference)
    assert AgentDecision().propose_from_candidates(context,candidates).metadata['selected_candidate_id'] == 'bold'
    assert AgentDecision(reference_epsilon=0).propose_from_candidates(context,candidates).metadata['selected_candidate_id'] == 'careful'
    assert AgentDecision(reference_epsilon=1).propose_from_candidates(context,candidates).metadata['selected_candidate_id'] == 'bold'


@pytest.mark.parametrize('epsilon',[-1,float('nan'),float('inf'),True,'bad'])
def test_invalid_reference_epsilon_rejected(epsilon):
    context,candidates=_inputs()
    with pytest.raises(ValueError): AgentDecision(reference_epsilon=epsilon).propose_from_candidates(context,candidates)


def test_unsupported_evaluator_fails_closed_only_when_enabled():
    context,candidates=_inputs()
    class Custom:
        def evaluate(self,situation,candidates):
            return DeterministicActionEvaluationPolicy().evaluate(situation,candidates)
    assert AgentDecision(evaluation_policy=Custom()).propose_from_candidates(context,candidates)
    with pytest.raises(PermissionError):
        AgentDecision(evaluation_policy=Custom(),reference_epsilon=0).propose_from_candidates(context,candidates)


def test_evidence_snapshot_single_provider_call_and_binding(monkeypatch):
    from test_candidate_evidence_review import Candidates
    from cognitive_world.cognition.runtime import CognitiveRuntime
    runtime=runtime_with_observations()
    cr=CognitiveRuntime(); cr._bind_observation_history(runtime.event_history)
    cognition=cr.process('viewer',runtime.observation_store.get_by_observer('viewer'))
    context=DecisionContext(cognition_state=cognition,percepts=tuple(cognition.percepts))
    situation=DeterministicSituationAssessmentPolicy().assess(context)
    candidates=Candidates().generate(situation)
    calls=[]
    original=DeterministicLocalEvidenceReviewProvider.review_evidence
    def counted(self,candidate,evidence,**kwargs):
        calls.append((candidate.candidate_id,evidence)); return original(self,candidate,evidence,**kwargs)
    monkeypatch.setattr(DeterministicLocalEvidenceReviewProvider,'review_evidence',counted)
    provider=DeterministicLocalEvidenceReviewProvider()
    policy=EvidenceAwareEvaluationPolicy(AuthorizedStateQuery(runtime),3,provider)
    actual,reference,snapshots=policy.evaluate_with_reference(situation,candidates)
    assert len(calls)==len(candidates)==len(snapshots)
    assert [x.candidate_id for x in actual]==[x.candidate_id for x in reference]
    snap=snapshots[0]; evidence=calls[0][1]
    snap.validate('viewer',candidates[0],evidence,provider)
    with pytest.raises(PermissionError): snap.validate('other',candidates[0],evidence,provider)
    with pytest.raises(PermissionError): snap.validate('viewer',replace(candidates[0],method='forged'),evidence,provider)
    with pytest.raises(PermissionError): snap.validate('viewer',candidates[0],(),provider)
    with pytest.raises(PermissionError): replace(snap,provider_version=2).validate('viewer',candidates[0],evidence,provider)
    assert all(dict(x.factors)['bounded_impulse']==0 for x in reference)


def test_reference_review_is_recomputed_for_counterfactual_scores(monkeypatch):
    from cognitive_world.decision.autonomous import BoundedDecisionReviewPolicy
    context,candidates=_inputs()
    calls=[]
    original=BoundedDecisionReviewPolicy.should_review
    def record(self,situation,evaluations):
        result=original(self,situation,evaluations)
        calls.append((situation.impulse_bias,tuple(x.score for x in evaluations),result))
        return result
    monkeypatch.setattr(BoundedDecisionReviewPolicy,'should_review',record)
    AgentDecision(reference_epsilon=1).propose_from_candidates(context,candidates)
    assert any(impulse == 0 for impulse,_,_ in calls)
    assert any(impulse == 1 for impulse,_,_ in calls)
    assert next(scores for impulse,scores,_ in calls if impulse == 0) != next(scores for impulse,scores,_ in calls if impulse == 1)


def test_reference_tie_preserves_candidate_id_tiebreak():
    context,_=_inputs()
    candidates=(_candidate('agent-a',candidate_id='z',risk=.5,commitment=.5),
                _candidate('agent-a',candidate_id='a',risk=.5,commitment=.5))
    assert AgentDecision(reference_epsilon=0).propose_from_candidates(context,candidates).metadata['selected_candidate_id']=='a'


def test_valid_no_adjustment_and_provider_failure_are_distinct(monkeypatch):
    runtime=runtime_with_observations()
    context=DecisionContext(cognition_state=CognitionState('viewer'))
    situation=DeterministicSituationAssessmentPolicy().assess(context)
    no_target=(_candidate('viewer',candidate_id='plain',risk=None,commitment=.5,goal=None),)
    provider=DeterministicLocalEvidenceReviewProvider()
    policy=EvidenceAwareEvaluationPolicy(AuthorizedStateQuery(runtime),3,provider)
    actual,reference,snapshots=policy.evaluate_with_reference(situation,no_target)
    assert snapshots[0].status=='no_adjustment' and snapshots[0].analysis is None
    assert actual==reference
    targeted=(replace(no_target[0],target='object:door-west'),)
    def broken(*args,**kwargs): raise OSError('provider unavailable')
    monkeypatch.setattr(DeterministicLocalEvidenceReviewProvider,'propose_query',broken)
    with pytest.raises(RuntimeError,match='provider failed'):
        policy.evaluate_with_reference(situation,targeted)


def test_enabled_reference_runs_real_runtime_evidence_and_formal_action():
    from test_autonomous_world_runner import _production_world, _action
    runner, world, history, _ = _production_world({'agent-a': ('goal-a', 'open the archive door')})
    runner.runtime.agent_decision.reference_epsilon=0
    report=runner.run(1)
    action=_action(report,'agent-a')
    assert action.proposal is not None and action.event_committed
    assert world.environment['door:archive'].is_open
    assert any(event.has_trusted_source('resolution') for event in history.get_events())


def test_incompatible_evidence_provider_rejected_without_second_call():
    from test_candidate_evidence_review import LocalProvider, Candidates
    runtime=runtime_with_observations()
    provider=LocalProvider()
    context=DecisionContext(cognition_state=CognitionState('viewer'))
    situation=DeterministicSituationAssessmentPolicy().assess(context)
    policy=EvidenceAwareEvaluationPolicy(AuthorizedStateQuery(runtime),3,provider)
    with pytest.raises(PermissionError,match='compatible evidence provider'):
        policy.evaluate_with_reference(situation,Candidates().generate(situation))
    assert provider.seen == []


def test_reference_review_can_differ_from_actual_review():
    from cognitive_world.decision.autonomous import BoundedDecisionReviewPolicy
    context,candidates=_inputs()
    situation=replace(DeterministicSituationAssessmentPolicy().assess(context),uncertainties=())
    evaluator=DeterministicActionEvaluationPolicy()
    review=BoundedDecisionReviewPolicy()
    actual=evaluator.evaluate(situation,candidates)
    reference=evaluator.evaluate_reference(situation,candidates)
    assert not review.should_review(situation,actual)
    assert review.should_review(situation,reference)
    class FixedSituation:
        def assess(self,context): return situation
    proposal=AgentDecision(situation_policy=FixedSituation(),reference_epsilon=0).propose_from_candidates(context,candidates)
    assert proposal.metadata['selected_candidate_id']=='careful'
    assert all('bounded_review_caution' not in dict(item['factors']) for item in proposal.metadata['decision_trace'])


@pytest.mark.parametrize('bad', ['missing','nan','duplicate'])
def test_incomplete_or_invalid_reference_fails_closed(monkeypatch,bad):
    context,candidates=_inputs()
    original=DeterministicActionEvaluationPolicy.evaluate_reference
    def invalid(self,situation,candidates):
        items=original(self,situation,candidates)
        if bad=='missing': return items[:1]
        if bad=='nan': return (replace(items[0],score=float('nan')),items[1])
        return (items[0],items[0])
    monkeypatch.setattr(DeterministicActionEvaluationPolicy,'evaluate_reference',invalid)
    with pytest.raises(ValueError,match='reference evaluation'):
        AgentDecision(reference_epsilon=0).propose_from_candidates(context,candidates)


def test_invalid_analysis_and_provider_failure_are_distinct(monkeypatch):
    from test_candidate_evidence_review import Candidates
    runtime=runtime_with_observations()
    from cognitive_world.cognition.runtime import CognitiveRuntime
    cr=CognitiveRuntime(); cr._bind_observation_history(runtime.event_history)
    cognition=cr.process('viewer',runtime.observation_store.get_by_observer('viewer'))
    context=DecisionContext(cognition_state=cognition,percepts=tuple(cognition.percepts))
    situation=DeterministicSituationAssessmentPolicy().assess(context)
    policy=EvidenceAwareEvaluationPolicy(AuthorizedStateQuery(runtime),3,DeterministicLocalEvidenceReviewProvider())
    monkeypatch.setattr(DeterministicLocalEvidenceReviewProvider,'review_evidence',lambda *a,**k: 'invalid-json')
    with pytest.raises(ValueError,match='validation failed'):
        policy.evaluate_with_reference(situation,Candidates().generate(situation))


def test_exact_reference_gap_is_inclusive_and_smaller_bound_excludes():
    import math
    from cognitive_world.decision.autonomous import BoundedDecisionReviewPolicy
    context,candidates=_inputs()
    situation=DeterministicSituationAssessmentPolicy().assess(context)
    reference=DeterministicActionEvaluationPolicy().evaluate_reference(situation,candidates)
    review=BoundedDecisionReviewPolicy()
    if review.should_review(situation,reference): reference=review.reassess(situation,candidates,reference)
    scores={x.candidate_id:x.score for x in reference}
    gap=scores['careful']-scores['bold']
    assert gap > 0
    assert AgentDecision(reference_epsilon=gap).propose_from_candidates(context,candidates).metadata['selected_candidate_id']=='bold'
    assert AgentDecision(reference_epsilon=math.nextafter(gap,0)).propose_from_candidates(context,candidates).metadata['selected_candidate_id']=='careful'
    assert AgentDecision(reference_epsilon=0).has_custom_autonomous_policies()


def test_invalid_enabled_policy_never_commits_world_event():
    from test_autonomous_world_runner import _production_world
    runner,world,history,_=_production_world({'agent-a':('goal-a','open the archive door')})
    runner.runtime.agent_decision.reference_epsilon=-1
    before=history.get_events()
    assert not world.environment['door:archive'].is_open
    runner.run(1)
    assert not world.environment['door:archive'].is_open
    assert history.get_events()==before


def test_unconsumed_observation_is_valid_no_adjustment_with_reference(monkeypatch):
    from test_candidate_evidence_review import Candidates
    runtime=runtime_with_observations()
    context=DecisionContext(cognition_state=CognitionState('viewer'))
    situation=DeterministicSituationAssessmentPolicy().assess(context)
    candidates=Candidates().generate(situation)
    provider=DeterministicLocalEvidenceReviewProvider()
    policy=EvidenceAwareEvaluationPolicy(AuthorizedStateQuery(runtime),3,provider)
    calls=[]
    original=DeterministicLocalEvidenceReviewProvider.review_evidence
    def record(self,candidate,evidence,**kwargs):
        calls.append(evidence)
        return original(self,candidate,evidence,**kwargs)
    monkeypatch.setattr(DeterministicLocalEvidenceReviewProvider,'review_evidence',record)
    actual,reference,snapshots=policy.evaluate_with_reference(situation,candidates)
    assert not calls
    assert all(item.status=='no_adjustment' and item.analysis is None for item in snapshots)
    assert actual==reference
    assert AgentDecision(candidate_policy=Candidates(),evaluation_policy=policy,reference_epsilon=0).propose(context)
    assert not calls
    # The legacy unconfigured path also withholds the unconsumed observation.
    assert AgentDecision(candidate_policy=Candidates(),evaluation_policy=policy).propose(context)
    assert not calls


def test_mixed_consumed_and_unconsumed_evidence_uses_only_consumed(monkeypatch):
    from test_candidate_evidence_review import Candidates
    from cognitive_world.cognition.runtime import CognitiveRuntime
    from cognitive_world.event import EventProcessor, SystemEventFactory
    runtime=runtime_with_observations()
    consumed,=runtime.observation_store.get_by_observer('viewer')
    cr=CognitiveRuntime(); cr._bind_observation_history(runtime.event_history)
    cognition=cr.process('viewer',(consumed,))
    processor=EventProcessor(world_state=runtime.world_state,event_history=runtime.event_history,
        simulation_clock=runtime.clock,agent_registry=runtime.agent_registry,
        observation_store=runtime.observation_store)
    processor.dispatch_with_evidence(SystemEventFactory().create(event_id='observed:door-west-again',
        event_type='environment_state_observed',timestamp='',simulation_tick=runtime.clock.current_time,
        changes=[{'environment_id':'door-west'}]))
    observations=runtime.observation_store.get_by_observer('viewer')
    assert len(observations)==2 and observations[0].observation_id==consumed.observation_id
    context=DecisionContext(cognition_state=cognition,percepts=tuple(cognition.percepts))
    situation=DeterministicSituationAssessmentPolicy().assess(context)
    candidates=Candidates().generate(situation)
    provider=DeterministicLocalEvidenceReviewProvider()
    policy=EvidenceAwareEvaluationPolicy(AuthorizedStateQuery(runtime),3,provider)
    calls=[]
    original=DeterministicLocalEvidenceReviewProvider.review_evidence
    def record(self,candidate,evidence,**kwargs):
        calls.append((candidate.candidate_id,evidence))
        return original(self,candidate,evidence,**kwargs)
    monkeypatch.setattr(DeterministicLocalEvidenceReviewProvider,'review_evidence',record)
    actual,reference,snapshots=policy.evaluate_with_reference(situation,candidates)
    assert len(calls)==len(candidates)==len(snapshots)
    assert all(tuple(item.observation_id for item in evidence)==(consumed.observation_id,) for _,evidence in calls)
    assert all(item.observation_id!=observations[1].observation_id for _,batch in calls for item in batch)
    for candidate,(_,evidence),snapshot,a,r in zip(candidates,calls,snapshots,actual,reference,strict=True):
        assert snapshot.status=='analysis'
        snapshot.validate('viewer',candidate,evidence,provider)
        assert dict(a.factors)['bounded_observed_evidence_review']==dict(r.factors)['bounded_observed_evidence_review']


def test_reference_evidence_authorization_failure_is_not_no_adjustment():
    from test_candidate_evidence_review import Candidates
    runtime=runtime_with_observations()
    context=DecisionContext(cognition_state=CognitionState('viewer'))
    situation=DeterministicSituationAssessmentPolicy().assess(context)
    policy=EvidenceAwareEvaluationPolicy(AuthorizedStateQuery(runtime),4,DeterministicLocalEvidenceReviewProvider())
    with pytest.raises(PermissionError,match='time mismatch'):
        policy.evaluate_with_reference(situation,Candidates().generate(situation))
