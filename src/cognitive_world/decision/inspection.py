"""Finite Inspect hypotheses from qualified cognition; no world or authority access."""
from dataclasses import replace

from cognitive_world.decision.autonomous import (
    ActionCandidate, MAX_CANDIDATES, MAX_MODEL_OUTPUT_CHARS, _tokens, parse_untrusted_candidates,
)

STRATEGY = "autonomous_container_inspection_v1"


def known_target(fact):
    if fact.fact_type == "object_appearance" and fact.predicate in {"object_shape", "object_detail"}:
        return fact.subject_ref
    if fact.fact_type == "container_content" and fact.predicate == "directly_contained_in":
        return fact.value  # The observed parent, never an inferred nested container.
    return None


def defer_candidate(owner):
    return ActionCandidate("inspect:defer", owner, None, "defer", None, "defer inspection",
        (), (), (), (), "No inspection is performed.", (), 0.0, 0.0, 0.0, (), STRATEGY)


class InspectionCandidatePolicy:
    """One batch, at most five targets plus defer. Equal value does not select by ID."""

    def __init__(self, provider=None):
        self.provider = provider

    def generate(self, situation):
        targets = {}
        for fact in situation.observed_facts:
            target = known_target(fact)
            if target:
                targets.setdefault(target, fact)
        if len(targets) >= MAX_CANDIDATES:
            return (defer_candidate(situation.owner_id),)
        if self.provider is not None:
            payload = self.provider.generate_candidates(situation, max_candidates=MAX_CANDIDATES - 1,
                                                       max_output_chars=MAX_MODEL_OUTPUT_CHARS)
            parsed = parse_untrusted_candidates(payload, situation, maximum=MAX_CANDIDATES - 1)
            normalized = []
            for candidate in parsed:
                fact = targets.get(candidate.target)
                if candidate.intent != "Inspect" or fact is None:
                    raise PermissionError("model may propose only Inspect of a qualified observed identity")
                normalized.append(replace(candidate, strategy=STRATEGY, target="object:" + candidate.target,
                                          source_refs=(fact.percept_id, fact.source_event_id)))
            return (*normalized, defer_candidate(situation.owner_id))
        candidates = []
        goals = tuple(g for g in situation.goals if not g.blocked and g.status == "active")
        if not goals:
            return (defer_candidate(situation.owner_id),)
        for index, (target, fact) in enumerate(sorted(targets.items())):
            # Subjective goal relevance, not a claim that this object has container capability.
            matches = tuple(g for g in goals if _tokens(g.description) & _tokens(target))
            goal = max(matches or goals, key=lambda g: (g.motivation_score, g.goal_id), default=None)
            candidates.append(ActionCandidate(f"inspect:{index}", situation.owner_id,
                None if goal is None else goal.goal_id, "Inspect", "object:" + target,
                "inspect " + target, (), (), ("Independent host policy must authorize inspection.",),
                (), "May receive authorized direct-content information; nothing is yet known.",
                ("Current capability and access remain unverified.",), None, 0.2, 0.5,
                (fact.percept_id, fact.source_event_id), STRATEGY))
        return (*candidates, defer_candidate(situation.owner_id))
