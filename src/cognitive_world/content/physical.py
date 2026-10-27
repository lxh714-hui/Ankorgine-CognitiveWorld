"""Closed JSON adapters and local-reference materialization, not executable JSON."""

from dataclasses import replace
from cognitive_world.core.physical import (
    PhysicalPropertyDefinition,
    PhysicalValue,
    PhysicalStateSet,
    PhysicalRelation,
    PhysicalCondition,
    PhysicalTransitionRule,
    validate_physical_world,
)


def closed(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError("invalid physical JSON fields")
    return value


def sequence(value):
    if type(value) is not list or len(value) > 32:
        raise ValueError("bounded physical array required")
    return value


def state(value, identity):
    if value is None:
        return None
    value = closed(value, ("version", "properties"))
    props = []
    for item in sequence(value["properties"]):
        item = closed(item, ("definition", "value"))
        raw = item["definition"]
        if type(raw) is dict and raw.get("value_type") == "boolean":
            raw = {**closed(raw, ("version", "name", "value_type")), "unit": None}
        else:
            raw = closed(
                raw, ("version", "name", "value_type", "unit", "minimum", "maximum")
            )
        definition = PhysicalPropertyDefinition(**raw)
        props.append(PhysicalValue(definition, item["value"]))
    return PhysicalStateSet(value["version"], identity, tuple(props))


def relation(value):
    value = closed(value, ("source", "target", "kinds"))
    return PhysicalRelation(
        1, value["source"], value["target"], tuple(sequence(value["kinds"]))
    )


def rule(value):
    value = closed(
        value,
        (
            "version",
            "rule_id",
            "operation",
            "receiver_id",
            "property_name",
            "expected",
            "replacement",
            "capability",
            "conditions",
            "relations",
        ),
    )
    return PhysicalTransitionRule(
        **{
            **value,
            "conditions": tuple(
                PhysicalCondition(**closed(v, ("entity_id", "property_name", "value")))
                for v in sequence(value["conditions"])
            ),
            "relations": tuple(relation(v) for v in sequence(value["relations"])),
        }
    )


def bindings(values):
    result = []
    for value in sequence(values):
        value = closed(
            value,
            (
                "target_ref",
                "version",
                "rule_id",
                "operation",
                "receiver_id",
                "property_name",
                "expected",
                "replacement",
                "capability",
                "conditions",
                "relations",
            ),
        )
        result.append(
            (
                value["target_ref"],
                rule({k: v for k, v in value.items() if k != "target_ref"}),
            )
        )
    return tuple(result)


def validate_refs(scenario, refs):
    for relation in scenario.physical_relations:
        if relation.source not in refs or relation.target not in refs:
            raise ValueError("physical relation reference missing")
    for target, rule in scenario.physical_rules:
        if target not in refs or rule.receiver_id not in refs:
            raise ValueError("physical rule target missing")
        if any(c.entity_id not in refs for c in rule.conditions):
            raise ValueError("physical condition reference missing")
        for r in rule.relations:
            if r.source not in refs or r.target not in refs:
                raise ValueError("physical rule relation reference missing")


def materialize(entities, scenario, templates, refs, locations, existing):
    byid = {e.id: e for e in entities}
    for key, tid, _, _ in scenario.objects:
        template = templates.object(tid)
        if template.physical_state is not None:
            eid = refs["object:" + key]
            entity = byid[eid]
            byid[eid] = replace(
                entity,
                state={
                    **entity.state,
                    "physical": replace(template.physical_state, entity_id=eid),
                },
            )

    def remap(r):
        return replace(r, source=refs[r.source], target=refs[r.target])

    relations = tuple(remap(r) for r in scenario.physical_relations)
    for local, rule in scenario.physical_rules:
        eid = refs[local]
        entity = byid[eid]
        value = replace(
            rule,
            receiver_id=refs[rule.receiver_id],
            conditions=tuple(
                replace(c, entity_id=refs[c.entity_id]) for c in rule.conditions
            ),
            relations=tuple(remap(r) for r in rule.relations),
        )
        rules = entity.attributes.get("physical_rules", ())
        byid[eid] = replace(
            entity, attributes={**entity.attributes, "physical_rules": (*rules, value)}
        )
    relation_map = {(r.source, r.target): r for r in relations}
    if len(relation_map) != len(relations):
        raise ValueError("duplicate physical relation endpoints")
    validate_physical_world({**existing, **byid}, locations, relation_map)
    return tuple(byid.values()), relations
