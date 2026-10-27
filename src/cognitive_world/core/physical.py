"""Closed physical data contracts; no engine objects or write capabilities."""

from dataclasses import dataclass
import math


def identity(value):
    if type(value) is not str or not value or len(value) > 1024:
        raise ValueError("bounded explicit identity required")


def version(value):
    if type(value) is not int or value != 1:
        raise ValueError("unsupported physical contract version")


@dataclass(frozen=True)
class PhysicalPropertyDefinition:
    version: int
    name: str
    value_type: str
    unit: str | None
    minimum: float | None = None
    maximum: float | None = None

    def __post_init__(self):
        version(self.version)
        identity(self.name)
        if self.value_type not in ("boolean", "number"):
            raise ValueError("unsupported property value type")
        if self.value_type == "boolean":
            if any(x is not None for x in (self.unit, self.minimum, self.maximum)):
                raise ValueError("boolean properties have no units or numeric bounds")
        else:
            if self.unit not in ("1", "kg", "m", "K", "N"):
                raise ValueError("unsupported explicit unit")
            for value in (self.minimum, self.maximum):
                if value is not None and (
                    type(value) not in (int, float) or not math.isfinite(value)
                ):
                    raise ValueError("bounds must be finite")
            if (
                self.minimum is not None
                and self.maximum is not None
                and self.minimum > self.maximum
            ):
                raise ValueError("reversed property bounds")

    def validate(self, value):
        self.__post_init__()
        if self.value_type == "boolean":
            if type(value) is not bool:
                raise ValueError("boolean value required")
        elif (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or self.minimum is not None
            and value < self.minimum
            or self.maximum is not None
            and value > self.maximum
        ):
            raise ValueError("physical value violates definition")


@dataclass(frozen=True)
class PhysicalValue:
    definition: PhysicalPropertyDefinition
    value: bool | float

    def __post_init__(self):
        if type(self.definition) is not PhysicalPropertyDefinition:
            raise TypeError("typed definition required")
        self.definition.validate(self.value)


@dataclass(frozen=True)
class PhysicalStateSet:
    version: int
    entity_id: str
    properties: tuple[PhysicalValue, ...]

    def __post_init__(self):
        version(self.version)
        identity(self.entity_id)
        if (
            type(self.properties) is not tuple
            or len(self.properties) > 32
            or any(type(x) is not PhysicalValue for x in self.properties)
        ):
            raise TypeError("bounded typed state set required")
        for value in self.properties:
            value.__post_init__()
        names = [p.definition.name for p in self.properties]
        if len(names) != len(set(names)):
            raise ValueError("duplicate physical property")

    def get(self, name):
        return next((p for p in self.properties if p.definition.name == name), None)


@dataclass(frozen=True)
class PhysicalRelation:
    version: int
    source: str
    target: str
    kinds: tuple[str, ...]

    def __post_init__(self):
        version(self.version)
        identity(self.source)
        identity(self.target)
        if (
            self.source == self.target
            or type(self.kinds) is not tuple
            or not self.kinds
            or len(self.kinds) != len(set(self.kinds))
            or any(
                k not in {"part_of", "attached_to", "controls", "owned_by", "held_by"}
                for k in self.kinds
            )
        ):
            raise ValueError("invalid typed relation")

    @property
    def attributes(self):
        # Compatibility read projection, never a separate relationship Store.
        return {"kinds": self.kinds}


@dataclass(frozen=True)
class PhysicalCondition:
    entity_id: str
    property_name: str
    value: bool | float

    def __post_init__(self):
        identity(self.entity_id)
        identity(self.property_name)
        if (
            type(self.value) not in (bool, int, float)
            or type(self.value) is float
            and not math.isfinite(self.value)
        ):
            raise ValueError("invalid condition scalar")


@dataclass(frozen=True)
class PhysicalTransitionRule:
    version: int
    rule_id: str
    operation: str
    receiver_id: str
    property_name: str
    expected: bool
    replacement: bool
    capability: str
    conditions: tuple[PhysicalCondition, ...]
    relations: tuple[PhysicalRelation, ...]

    def __post_init__(self):
        version(self.version)
        for value in (
            self.rule_id,
            self.operation,
            self.receiver_id,
            self.property_name,
            self.capability,
        ):
            identity(value)
        if (
            type(self.expected) is not bool
            or type(self.replacement) is not bool
            or self.expected == self.replacement
        ):
            raise ValueError("v1 supports a genuine boolean transition only")
        if (
            type(self.conditions) is not tuple
            or len(self.conditions) > 16
            or any(type(x) is not PhysicalCondition for x in self.conditions)
            or type(self.relations) is not tuple
            or len(self.relations) > 16
            or any(type(x) is not PhysicalRelation for x in self.relations)
        ):
            raise ValueError("bounded typed preconditions required")
        for x in (*self.conditions, *self.relations):
            x.__post_init__()


def validate_physical_rule(rule, entities):
    """Validate only this rule's typed dependencies against supplied entities.

    Full-world validation calls this for every installed rule. Interaction
    capture calls it for the selected rule, never unrelated rules on its inputs.
    """
    if type(rule) is not PhysicalTransitionRule:
        raise ValueError("unsupported physical rule")
    rule.__post_init__()

    def physical(identity):
        entity = entities.get(identity)
        state = getattr(entity, "state", {}).get("physical")
        if state is not None:
            if type(state) is not PhysicalStateSet or state.entity_id != identity:
                raise ValueError("physical state identity mismatch")
            state.__post_init__()
        return state

    receiver = physical(rule.receiver_id)
    value = None if receiver is None else receiver.get(rule.property_name)
    if value is None or value.definition.value_type != "boolean":
        raise ValueError("unsupported rule receiver property")
    for condition in rule.conditions:
        state = physical(condition.entity_id)
        prop = None if state is None else state.get(condition.property_name)
        if prop is None:
            raise ValueError("unknown rule condition")
        prop.definition.validate(condition.value)
    for relation in rule.relations:
        if relation.source not in entities or relation.target not in entities:
            raise ValueError("unknown rule relation endpoint")


def validate_physical_world(entities, locations, relations):
    """Cross-record semantics shared by admission, commit and verified restore."""
    parents = {}
    owners = {}
    holders = {}
    for key, entity in entities.items():
        state = getattr(entity, "state", {}).get("physical")
        if state is not None:
            if type(state) is not PhysicalStateSet or state.entity_id != key:
                raise ValueError("physical state identity mismatch")
            state.__post_init__()
        rules = getattr(entity, "attributes", {}).get("physical_rules", ())
        if type(rules) is not tuple or len(rules) > 16:
            raise ValueError("invalid physical rules")
        ids = []
        for rule in rules:
            validate_physical_rule(rule, entities)
            ids.append(rule.rule_id)
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate rule identity")
    for key, relation in relations.items():
        if type(relation) is not PhysicalRelation:
            continue  # unchanged legacy semantics
        relation.__post_init__()
        if (
            key != (relation.source, relation.target)
            or relation.source not in entities
            or relation.target not in entities
        ):
            raise ValueError("relation identity or endpoint missing")
        for kind, index in (
            ("part_of", parents),
            ("owned_by", owners),
            ("held_by", holders),
        ):
            if kind in relation.kinds:
                if relation.source in index:
                    raise ValueError("relation cardinality exceeded")
                index[relation.source] = relation.target
        if (
            "owned_by" in relation.kinds
            and entities[relation.source].owner_id != relation.target
        ):
            raise ValueError("ownership relation conflicts with canonical owner")
        if (
            "held_by" in relation.kinds
            and locations.get(relation.source) != relation.target
        ):
            raise ValueError("possession relation conflicts with canonical location")
    for start in parents:
        seen = set()
        node = start
        while node in parents:
            if node in seen:
                raise ValueError("physical composition cycle")
            seen.add(node)
            node = parents[node]


@dataclass(frozen=True)
class CandidateStateDelta:
    entity_id: str
    expected: PhysicalStateSet
    replacement: PhysicalStateSet

    def __post_init__(self):
        identity(self.entity_id)
        if (
            type(self.expected) is not PhysicalStateSet
            or type(self.replacement) is not PhysicalStateSet
            or self.expected.entity_id != self.entity_id
            or self.replacement.entity_id != self.entity_id
        ):
            raise ValueError("invalid candidate state identity")
        self.expected.__post_init__()
        self.replacement.__post_init__()
