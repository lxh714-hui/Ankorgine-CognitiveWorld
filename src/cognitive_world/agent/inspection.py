"""Opt-in bridge from real consumed cognition to the existing inspection authority."""
from dataclasses import dataclass, replace
import math

from cognitive_world.core.persistence import PersistedValueCodec
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.decision.agent_decision import AgentDecision
from cognitive_world.decision.autonomous import MAX_CANDIDATES, MAX_CONTEXT_ITEMS, DeterministicSituationAssessmentPolicy
from cognitive_world.decision.inspection import STRATEGY, InspectionCandidatePolicy, known_target
from cognitive_world.observation.container_inspection import ContainerInspectionAuthority


@dataclass(frozen=True)
class InspectionResult:
    status: str
    code: str
    proposal: ActionProposal
    event: object = None


def _snapshot(proposal):
    return (proposal.proposal_id, proposal.agent_id, proposal.action_type, proposal.target_refs,
            proposal.parameters, proposal.reasoning_refs, proposal.metadata)


class AutonomousInspectionService:
    """No second decision engine, ObservationStore or physical action executor."""

    def __init__(self, processor, cognitive_runtime, candidate_policy=None):
        self.processor, self.cognitive_runtime = processor, cognitive_runtime
        self.candidate_policy = candidate_policy or InspectionCandidatePolicy()
        self._codec, self._selections, self._turns, self._outcomes = PersistedValueCodec(), {}, {}, {}

    def _defer(self, owner, code):
        proposal = ActionProposal("inspection:defer", owner, "defer",
                                  metadata={"candidate_source": STRATEGY, "status": "deferred", "code": code})
        return InspectionResult("deferred", code, proposal)

    def select(self, turn, agent, cognition, decision, simulation_tick):
        p, owner = self.processor, agent.agent_id
        permit = p.write_fence.current_permit()
        p.write_fence.require_current_permit(permit)
        # Old operations cannot execute again. Keep only this operation's finite
        # turn/selection bookkeeping rather than growing a second history.
        self._selections = {k: v for k, v in self._selections.items() if v[3] is permit}
        self._turns = {k: v for k, v in self._turns.items() if v is permit}
        self._outcomes = {k: v for k, v in self._outcomes.items() if k in self._selections}
        if (turn.cognitive_runtime is not self.cognitive_runtime or turn.write_fence is not p.write_fence
                or self.cognitive_runtime._history_context is None
                or self.cognitive_runtime._history_context.history is not p.event_history
                or type(decision) is not AgentDecision or cognition.owner_id != owner
                or simulation_tick is None or not simulation_tick.is_clock_issued()
                or simulation_tick.tick != p.simulation_clock.current_time):
            raise PermissionError("inspection assembly/owner/time mismatch")
        key = (id(permit), owner)
        if key in self._turns:
            return self._defer(owner, "turn_budget_exhausted")
        self._turns[key] = permit  # Keep original identity alive; no id-reuse budget bypass.
        context, _ = turn.prepare_decision_context(agent, cognition, simulation_tick=simulation_tick)
        qualified = {}
        for percept in context.percepts[:MAX_CONTEXT_ITEMS]:
            observation = self.cognitive_runtime.consumed_observation_for_percept(owner, percept)
            if observation is not None and known_target(observation.content):
                qualified[percept.percept_id] = (percept, observation)
        if not qualified:
            return self._defer(owner, "no_qualified_percepts")
        context = replace(context, percepts=tuple(v[0] for v in qualified.values()))
        situation = DeterministicSituationAssessmentPolicy().assess(context)
        try:
            candidates = self.candidate_policy.generate(situation)
            if (type(candidates) is not tuple or not 1 <= len(candidates) <= MAX_CANDIDATES
                    or len({c.candidate_id for c in candidates}) != len(candidates)):
                raise ValueError("invalid inspection batch")
            by_id = {}
            for candidate in candidates:
                if candidate.owner_id != owner or candidate.strategy != STRATEGY or candidate.domain_payload is not None:
                    raise PermissionError("unknown inspection candidate owner/schema")
                if candidate.intent == "defer":
                    if candidate.target is not None:
                        raise PermissionError("defer cannot name a target")
                    continue
                if (candidate.intent != "Inspect" or len(candidate.source_refs) != 2
                        or candidate.tools or candidate.steps or candidate.required_capabilities
                        or candidate.method != "inspect " + (candidate.target or "")[7:]):
                    raise PermissionError("finite inspection candidate required")
                pair = qualified.get(candidate.source_refs[0])
                if (pair is None or candidate.source_refs[1] != pair[1].source_event_id
                        or candidate.target != "object:" + known_target(pair[1].content)):
                    raise PermissionError("candidate has no exact consumed target/source")
                by_id[candidate.candidate_id] = pair
            # Reuse all existing scoring, review, context and candidate budget validation.
            proposal = decision.propose_from_candidates(context, candidates)
            trace = proposal.metadata.get("decision_trace", ())
            scores = [item["score"] for item in trace]
            if len(scores) != len(candidates) or any(type(s) not in (int, float) or not math.isfinite(s) for s in scores):
                raise ValueError("invalid reviewed inspection scores")
            top = max(scores)
            if sum(abs(s - top) <= 1e-12 for s in scores) != 1:
                return self._defer(owner, "ambiguous_reviewed_scores")
            if proposal.action_type == "defer":
                return self._defer(owner, "selected_defer")
            pair = by_id.get(proposal.metadata.get("selected_candidate_id"))
            if pair is None:
                raise PermissionError("unissued selected candidate")
            self._selections[id(proposal)] = (proposal, self._codec.dumps(_snapshot(proposal)),
                pair, permit, p.event_history.timeline_id, p.simulation_clock.current_time,
                p.write_fence.restore_generation, None)
            return InspectionResult("selected", "awaiting_host_authorization", proposal)
        except Exception:
            return self._defer(owner, "candidate_generation_evaluation_or_review_failed")

    def prepare_selected(self, agent, proposal):
        """Selection is not authority. Produce at most one Phase 3 Event, never apply it here."""
        p = self.processor
        entry = self._selections.get(id(proposal))
        if entry is None or entry[0] is not proposal or agent.agent_id != proposal.agent_id:
            raise PermissionError("not an exact locally selected inspection proposal")
        original, encoded, pair, permit, timeline, tick, generation, event = entry
        p.write_fence.require_candidate_origin(permit)
        p.write_fence.require_current_permit(permit)
        if (self._codec.dumps(_snapshot(proposal)) != encoded or p.event_history.timeline_id != timeline
                or p.simulation_clock.current_time != tick or p.write_fence.restore_generation != generation
                or self.cognitive_runtime.consumed_observation_for_percept(proposal.agent_id, pair[0]) is None):
            raise PermissionError("inspection selection/source is stale or substituted")
        if event is not None:
            return InspectionResult("authorized", "same_inspection_event", proposal, event)
        if id(proposal) in self._outcomes:
            return self._outcomes[id(proposal)]
        authority = p.container_inspection_authority
        if type(authority) is not ContainerInspectionAuthority:
            result = InspectionResult("rejected", "inspection_policy_unavailable", proposal)
            self._outcomes[id(proposal)] = result
            return result
        try:
            event = authority.create_event(proposal.agent_id, proposal.target_refs[0][7:],
                                           event_id="event:autonomous-inspect:" + proposal.proposal_id)
        except PermissionError:
            result = InspectionResult("rejected", "host_authorization_declined", proposal)
            self._outcomes[id(proposal)] = result
            return result
        self._selections[id(proposal)] = (*entry[:-1], event)
        return InspectionResult("authorized", "awaiting_processor_execution", proposal, event)
