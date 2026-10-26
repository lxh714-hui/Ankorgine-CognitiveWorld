"""Bounded visual projection and replayable authorization evidence.

Detail is currently limited to explicitly visible carried objects. Room membership
alone never proves inspection reach; no distance/FOV/occlusion model is implied.
"""
from cognitive_world.core.object_appearance import ObjectAppearance

def capture(world, target):
    entity = world.get_entity(target)
    appearance = None if entity is None else entity.attributes.get("appearance")
    if type(appearance) is not ObjectAppearance:
        return ()
    appearance.__post_init__()
    position = world.locations.get(target)
    carrier = world.get_entity(position) if position else None
    room = world.locations.get(position) if carrier is not None and carrier.type == "character" else position
    light = world.environment.get(room)
    values = {"shape": appearance.shape, "detail": appearance.detail,
              "visible": appearance.visible, "detail_visible": appearance.detail_visible,
              "location": room, "holder": entity.owner_id if entity.owner_id == position else None,
              "lit": isinstance(light, dict) and light.get("light_on") is True}
    return tuple((f"object:{target}:{k}", v) for k,v in values.items() if v is not None)


def allows_object_fact(event, evidence, observer_id, fact):
    if event.type != "object_observed" or not fact.has_trusted_source(event):
        return False
    if len(event.changes) != 1 or not isinstance(event.changes[0], dict):
        return False
    request = event.changes[0]
    if set(request) != {"entity_id", "observer_id", "precision"}:
        return False
    if request["observer_id"] != observer_id or event.participants != [observer_id]:
        return False
    if request["precision"] not in {"coarse", "detail"} or request["entity_id"] != fact.subject_ref:
        return False
    ctx = evidence.event_time_context
    observer = next((o for o in ctx.observer_positions if o[0] == observer_id), None)
    values = dict(ctx.environment_conditions or ())
    prefix = f"object:{fact.subject_ref}:"
    if (observer is None or observer[2] is None or "sight" not in observer[2]
            or observer[1] != fact.location_id or fact.location_id != ctx.fact_location_id
            or values.get(prefix+"location") != fact.location_id
            or values.get(prefix+"visible") is not True or values.get(prefix+"lit") is not True
            or fact.fact_type != "object_appearance"):
        return False
    if fact.predicate == "object_shape":
        return fact.value == values.get(prefix+"shape")
    return (fact.predicate == "object_detail" and request["precision"] == "detail"
            and values.get(prefix+"holder") == observer_id
            and values.get(prefix+"detail_visible") is True
            and fact.value == values.get(prefix+"detail"))
