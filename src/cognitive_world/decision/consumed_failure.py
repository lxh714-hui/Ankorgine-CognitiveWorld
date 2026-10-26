"""One typed consumed-result adapter; proofs remain in the canonical MemoryStore."""
from dataclasses import dataclass
from copy import deepcopy
from cognitive_world.event.attempt_source import confirmed_reach_failure_source
from cognitive_world.core.interaction import InteractionReference

REACH_RULE = "interaction-out-of-reach-owner-result/v1"

@dataclass(frozen=True)
class ConsumedFailureBinding:
    version: int
    proof_id: str
    def __post_init__(self):
        if type(self.version) is not int or self.version != 1 or type(self.proof_id) is not str or not self.proof_id or len(self.proof_id)>1024:
            raise ValueError("unsupported consumed failure binding")


def verify_consumed_failure(failure, *, history, memory_store, trust, tick):
    from cognitive_world.cognition.l1_consumption_proof import (
        NonverbalL1ConsumptionProof, NONVERBAL_PROOF_MEMORY_TYPE, verify_nonverbal_proof)
    from cognitive_world.cognition.memory_store import MemoryStore
    if type(failure.consumption) is not ConsumedFailureBinding or type(memory_store) is not MemoryStore or trust is None:
        raise PermissionError("consumed feedback requires canonical durable consumption evidence")
    binding=failure.consumption
    binding.__post_init__()
    record=memory_store.get_memory(binding.proof_id)
    if (record is None or record.type!=NONVERBAL_PROOF_MEMORY_TYPE
            or type(record.content) is not NonverbalL1ConsumptionProof
            or record.id!=binding.proof_id or record.owner_id!=failure.owner_id
            or record.source_event!=failure.event_id):
        raise PermissionError("feedback consumption proof is missing or mismatched")
    proof=record.content
    verify_nonverbal_proof(proof,history=history,trust=trust,
        checkpoint_timeline_id=history.timeline_id,checkpoint_tick=tick)
    event=history.get_event(failure.event_id)
    source=confirmed_reach_failure_source(event)
    evidence=history.get_processing_evidence(failure.event_id)
    fact=next((f for f in evidence.observable_facts if f.fact_id==proof.fact_id),None) if evidence else None
    conditions=() if fact is None else (("actor_location",fact.location_id),("failure_category","interaction_out_of_reach"))
    if (source is None or proof.visibility_rule!=REACH_RULE or proof.owner_id!=failure.owner_id
            or proof.source_event_id!=failure.event_id or failure.tick!=proof.consumption_tick
            or source["owner_id"]!=failure.owner_id or source["action_type"]!=failure.action_type
            or tuple(source["target_refs"])!=(failure.target,) or source["method"]!=failure.method
            or failure.conditions!=conditions):
        raise PermissionError("feedback source, owner, method or consumed fact conflicts")
    return proof


def same_interaction_target(left, right):
    try:
        a,b = InteractionReference.parse(left), InteractionReference.parse(right)
        return (a.namespace,a.identifier) == (b.namespace,b.identifier)
    except (TypeError, ValueError):
        return False


def reach_failure_applies(failure, world, history):
    if world is None or history is None:
        raise PermissionError("consumed feedback has no canonical applicability context")
    from cognitive_world.resolution.interaction_range import capture_reach
    event=history.get_event(failure.event_id)
    source=confirmed_reach_failure_source(event)
    if source is None:return False
    target=InteractionReference.parse(failure.target).identifier
    state=world.environment.get(target)
    if state is None:return False
    reach=capture_reach(world,failure.owner_id,target,state.interaction_location_id)
    # This is an engine applicability fence, not an Observation or a new fact.
    return (reach.configured and reach.status=="out_of_reach" and
        all(world.verify_state_slot_record(r,event_history=history) for r in source["state_slot_reads"]))


def process_with_feedback(turn, context, observations, *, beliefs, goals):
    cognitive=turn.cognitive_runtime
    binding=turn._consumed_failure_context
    if binding is None:
        return cognitive.process(context.owner_id,observations,beliefs=beliefs,goals=goals)
    feedback,issuer,boundary=binding
    history=issuer.history
    from cognitive_world.observation.observation import Observation
    candidates=[o for o in observations if isinstance(o,Observation) and getattr(o.content,"predicate",None)=="interaction_out_of_reach"
        and o.observer_id==context.owner_id and o.has_trusted_provenance()
        and confirmed_reach_failure_source(history.get_event(o.source_event_id)) is not None]
    if not candidates:
        return cognitive.process(context.owner_id,observations,beliefs=beliefs,goals=goals)
    history_context=cognitive._history_context
    if (type(boundary) is not frozenset or history_context is None or history_context.history is not history
            or history_context.trust is not issuer.trust
            or context.memory_store.write_fence is not issuer.fence
            or feedback._reach_context is None or feedback._reach_context[1] is not history):
        raise PermissionError("consumed feedback requires the canonical history and Store binding")
    with issuer.fence.commit_scope():
        from cognitive_world.runtime.write_fence import RuntimeWriteFence
        permit=RuntimeWriteFence.bind_current_permit()
        issuer.fence.require_candidate_origin(permit)
        previous=deepcopy(cognitive.working_memory_store.get(context.owner_id))
        try:
            state=cognitive.process(context.owner_id,observations,beliefs=beliefs,goals=goals)
        except BaseException:
            if cognitive.working_memory_store.get(context.owner_id)!=previous:
                issuer.fence.mark_recovery_required()
            raise
        outcomes=[]
        for observation in candidates:
            event_id=observation.source_event_id
            item=next((i for i in state.metadata["l1_ingestion"]["items"] if i["observation_id"]==observation.observation_id),None)
            if item is None or item["source"]!="eligible":
                outcomes.append((event_id,"source_rejected"));continue
            if item["history"]!="eligible":
                outcomes.append((event_id,"history_"+item["history"]));continue
            if item["consumption"] not in ("ingested","duplicate") or not cognitive.has_consumed_observation(context.owner_id,observation,source_event_id=event_id):
                outcomes.append((event_id,"not_consumed"));continue
            if event_id in feedback._seen_events:
                existing=next(f for f in feedback.history if f.event_id==event_id)
                try:
                    verify_consumed_failure(existing,history=history,memory_store=context.memory_store,trust=issuer.trust,tick=issuer.clock.current_time)
                except BaseException:
                    issuer.fence.mark_recovery_required()
                    raise
                outcomes.append((event_id,"duplicate"));continue
            if event_id in boundary or item["consumption"]!="ingested":
                outcomes.append((event_id,"ambiguous_prior_consumption"));continue
            try:
                proof=issuer.issue_after_l1(owner_id=context.owner_id,observation=observation,
                    cognitive_runtime=cognitive,memory_store=context.memory_store)
                if proof is None:raise PermissionError("eligible consumption proof was not published")
                source=confirmed_reach_failure_source(history.get_event(event_id))
                from cognitive_world.decision.behavior_feedback import BehaviorFailure
                conditions=(("actor_location",observation.content.location_id),("failure_category","interaction_out_of_reach"))
                prior=next((f for f in reversed(feedback.history) if f.consumption is not None
                    and (f.owner_id,f.action_type,f.method,f.conditions)==
                    (context.owner_id,source["action_type"],source["method"],conditions)
                    and same_interaction_target(f.target,source["target_refs"][0])
                    and reach_failure_applies(f,*feedback._reach_context)),None)
                penalty,count=feedback._next_failure_weight(prior,proof.consumption_tick)
                value=BehaviorFailure(context.owner_id,source["action_type"],source["target_refs"][0],source["method"],conditions,
                    event_id,proof.consumption_tick,penalty,count,ConsumedFailureBinding(1,proof.proof_id))
                verify_consumed_failure(value,history=history,memory_store=context.memory_store,trust=issuer.trust,tick=issuer.clock.current_time)
                feedback.history.append(value);feedback._seen_events.add(event_id)
                outcomes.append((event_id,"applied"))
            except BaseException:
                # No rollback or retry is inferred after possible L1/proof/feedback writes.
                issuer.fence.mark_recovery_required();raise
        state.metadata["consumed_physical_feedback"]={"version":1,"items":tuple(outcomes)}
        return state
