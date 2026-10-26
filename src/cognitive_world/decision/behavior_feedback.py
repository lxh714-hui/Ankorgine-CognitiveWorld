"""Process-local, owner-scoped feedback from committed action outcomes.

This is a decision aid, not canonical cognition or a world fact. Its history
uses the separately signed feedback snapshot component; Runtime references
are rebound during verified reconstruction, never persisted as credentials.
"""

from dataclasses import dataclass, field
import math

from cognitive_world.decision.autonomous import ActionCandidate, CandidateEvaluation, SituationAssessment


def _target_conditions(facts: tuple[object, ...], target: str | None,
                       source_refs: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    if target is None or not source_refs:
        return ()
    latest: dict[str, str] = {}
    for fact in facts:
        if fact.percept_id in source_refs or fact.source_event_id in source_refs:
            latest[fact.predicate] = fact.value
    return tuple(sorted(latest.items()))


@dataclass(frozen=True)
class BehaviorFailure:
    owner_id: str
    action_type: str
    target: str
    method: str
    conditions: tuple[tuple[str, str], ...]
    event_id: str
    tick: int
    penalty: float
    consecutive_failures: int
    consumption: object | None = None


@dataclass
class BehaviorFeedback:
    """Bounded owner-scoped history; reads never mutate the stored penalty."""

    half_life_ticks: int = 8
    frustration_half_life_ticks: int = 4
    maximum_penalty: float = 0.6
    history: list[BehaviorFailure] = field(default_factory=list)
    _seen_events: set[str] = field(default_factory=set, repr=False)

    _reach_context: object | None = field(default=None,init=False,repr=False,compare=False)

    def __post_init__(self) -> None:
        if type(self.half_life_ticks) is not int or self.half_life_ticks < 1:
            raise ValueError("half_life_ticks must be positive")
        if type(self.frustration_half_life_ticks) is not int or self.frustration_half_life_ticks < 1:
            raise ValueError("frustration_half_life_ticks must be positive")
        if not math.isfinite(self.maximum_penalty) or not 0 < self.maximum_penalty <= 1:
            raise ValueError("maximum_penalty must be in (0, 1]")

    def record_failure(
        self, *, owner_id: str, action_type: str, target: str,
        method: str, facts: tuple[object, ...], source_refs: tuple[str, ...],
        event_id: str, tick: int,
    ) -> bool:
        """Accept only a caller-verified committed failure and observed target state."""
        if not all(isinstance(value, str) and value for value in (owner_id, action_type, target, method, event_id)):
            raise ValueError("failure identity is incomplete")
        if type(tick) is not int or tick < 0:
            raise ValueError("failure tick is invalid")
        conditions = _target_conditions(facts, target, source_refs)
        if not conditions or event_id in self._seen_events:
            return False
        prior = next((item for item in reversed(self.history) if
            (item.owner_id, item.action_type, item.target, item.method, item.conditions)
            == (owner_id, action_type, target, method, conditions)), None)
        if prior is not None and tick < prior.tick:
            raise ValueError("failure time moved backwards")
        penalty, count = self._next_failure_weight(prior, tick)
        self.history.append(BehaviorFailure(
            owner_id, action_type, target, method, conditions, event_id, tick,
            penalty, count,
        ))
        self._seen_events.add(event_id)
        return True

    def _next_failure_weight(self, prior: BehaviorFailure | None, tick: int) -> tuple[float, int]:
        previous = 0.0 if prior is None else self._decayed(prior, tick)
        return (min(self.maximum_penalty, previous + 0.2),
                1 if prior is None else prior.consecutive_failures + 1)

    def _decayed(self, item: BehaviorFailure, tick: int) -> float:
        if type(tick) is not int or tick < item.tick:
            raise ValueError("feedback time is missing or reversed")
        return item.penalty * 2 ** (-(tick - item.tick) / self.half_life_ticks)

    def penalty_for(self, *, owner_id: str, action_type: str, target: str | None,
                    method: str, facts: tuple[object, ...],
                    source_refs: tuple[str, ...], tick: int) -> float:
        from cognitive_world.decision.consumed_failure import reach_failure_applies, same_interaction_target
        matches=[item for item in reversed(self.history) if item.consumption is not None
            and (item.owner_id,item.action_type,item.method)==(owner_id,action_type,method)
            and same_interaction_target(item.target,target)]
        reach_penalty=0.
        if matches:
            if self._reach_context is None:raise PermissionError("feedback applicability context is unavailable")
            world,history=self._reach_context
            applicable=next((item for item in matches if reach_failure_applies(item,world,history)),None)
            reach_penalty=0. if applicable is None else self._decayed(applicable,tick)
        conditions = _target_conditions(facts, target, source_refs)
        if not conditions:
            return reach_penalty
        prior = next((item for item in reversed(self.history) if
            (item.owner_id, item.action_type, item.target, item.method, item.conditions)
            == (owner_id, action_type, target, method, conditions)), None)
        return max(reach_penalty,0.0 if prior is None else self._decayed(prior, tick))

    def frustration_for(self, owner_id: str, tick: int) -> float:
        """Bounded turn-local feeling signal; never a canonical Emotion update."""
        prior = next((item for item in reversed(self.history) if item.owner_id == owner_id and item.consumption is None), None)
        if prior is None:
            return 0.0
        if type(tick) is not int or tick < prior.tick:
            raise ValueError("feedback time is missing or reversed")
        return min(0.3, 0.06 * prior.consecutive_failures) * 2 ** (
            -(tick - prior.tick) / self.frustration_half_life_ticks
        )

    def adjust(self, situation: SituationAssessment, candidates: tuple[ActionCandidate, ...],
               evaluations: tuple[CandidateEvaluation, ...], *, tick: int) -> tuple[CandidateEvaluation, ...]:
        if type(tick) is not int or tick < 0:
            raise ValueError("feedback requires a valid simulation tick")
        by_id = {item.candidate_id: item for item in candidates}
        frustration = self.frustration_for(situation.owner_id, tick)
        adjusted = []
        for evaluation in evaluations:
            candidate = by_id[evaluation.candidate_id]
            if candidate.owner_id != situation.owner_id:
                raise PermissionError("feedback candidate belongs to another Agent")
            penalty = self.penalty_for(
                owner_id=situation.owner_id, action_type=candidate.intent,
                target=candidate.target, method=candidate.method,
                facts=situation.observed_facts, source_refs=candidate.source_refs,
                tick=tick,
            )
            adjusted.append(CandidateEvaluation(
                evaluation.candidate_id,
                evaluation.score - penalty - 0.1 * frustration * candidate.commitment,
                (*evaluation.factors, ("recent_confirmed_failure", -penalty),
                 ("transient_frustration_caution", -0.1 * frustration * candidate.commitment)),
                evaluation.uncertainty,
            ))
        return tuple(adjusted)
