"""Pure replaceable boolean-transition model, independent of UI and cognition."""

from dataclasses import dataclass, replace
from typing import Protocol
from cognitive_world.core.physical import (
    PhysicalStateSet,
    PhysicalTransitionRule,
    PhysicalRelation,
    CandidateStateDelta,
    identity,
)


@dataclass(frozen=True)
class InteractionRequest:
    actor_id: str
    target_id: str
    operation: str

    def __post_init__(self):
        for value in (self.actor_id, self.target_id, self.operation):
            identity(value)


@dataclass(frozen=True)
class PhysicsContext:
    states: tuple[PhysicalStateSet, ...]
    relations: tuple[PhysicalRelation, ...]
    capabilities: tuple[str, ...]
    rule: PhysicalTransitionRule

    def __post_init__(self):
        if (
            type(self.states) is not tuple
            or len(self.states) > 128
            or any(type(s) is not PhysicalStateSet for s in self.states)
            or len({s.entity_id for s in self.states}) != len(self.states)
            or type(self.relations) is not tuple
            or len(self.relations) > 1024
            or any(type(r) is not PhysicalRelation for r in self.relations)
            or type(self.rule) is not PhysicalTransitionRule
            or type(self.capabilities) is not tuple
        ):
            raise ValueError("invalid bounded physics context")
        for value in (*self.states, *self.relations, self.rule):
            value.__post_init__()
        for capability in self.capabilities:
            identity(capability)


@dataclass(frozen=True)
class PhysicsOutcome:
    status: str
    delta: CandidateStateDelta | None
    evidence: tuple[str, ...]

    def __post_init__(self):
        if (
            self.status not in ("changed", "rejected", "unsupported")
            or (self.status == "changed") != (type(self.delta) is CandidateStateDelta)
            or self.status != "changed"
            and self.delta is not None
            or type(self.evidence) is not tuple
            or len(self.evidence) > 32
        ):
            raise ValueError("invalid physics outcome")
        for item in self.evidence:
            identity(item)


class PhysicsEngine(Protocol):
    def evaluate(
        self, request: InteractionRequest, context: PhysicsContext
    ) -> PhysicsOutcome: ...


class BooleanTransitionEngine:
    def evaluate(self, request, context):
        if (
            type(request) is not InteractionRequest
            or type(context) is not PhysicsContext
        ):
            raise TypeError("typed physics request and context required")
        request.__post_init__()
        context.__post_init__()
        rule = context.rule
        rule.__post_init__()
        states = {s.entity_id: s for s in context.states}
        if request.operation != rule.operation:
            return PhysicsOutcome("unsupported", None, ())
        if rule.capability not in context.capabilities:
            return PhysicsOutcome("rejected", None, ("capability",))
        for relation in rule.relations:
            found = next(
                (
                    r
                    for r in context.relations
                    if (r.source, r.target) == (relation.source, relation.target)
                ),
                None,
            )
            if found is None or not set(relation.kinds).issubset(found.kinds):
                return PhysicsOutcome("rejected", None, ("relation",))
        for condition in rule.conditions:
            state = states.get(condition.entity_id)
            value = None if state is None else state.get(condition.property_name)
            if value is None:
                return PhysicsOutcome("unsupported", None, ())
            if (
                type(value.value) is not type(condition.value)
                or value.value != condition.value
            ):
                return PhysicsOutcome("rejected", None, ("condition",))
        state = states.get(rule.receiver_id)
        value = None if state is None else state.get(rule.property_name)
        if value is None or value.definition.value_type != "boolean":
            return PhysicsOutcome("unsupported", None, ())
        if value.value is not rule.expected:
            return PhysicsOutcome("rejected", None, ("prior_state",))
        changed = replace(
            state,
            properties=tuple(
                (
                    replace(v, value=rule.replacement)
                    if v.definition.name == rule.property_name
                    else v
                )
                for v in state.properties
            ),
        )
        return PhysicsOutcome(
            "changed",
            CandidateStateDelta(state.entity_id, state, changed),
            ("conditions_verified",),
        )
