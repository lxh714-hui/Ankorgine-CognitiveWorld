"""Bounded appearance projection; range never substitutes for disclosure authority.

Legacy evidence retains its carried-object interpretation. Configured ranges use
one authored metric axis in an explicitly shared observation domain, not 3D/FOV.
"""
from cognitive_world.core.object_appearance import ObjectAppearance
from cognitive_world.core.observation_range import ObservationZone, ObservationRangePolicy


def capture(world, target, observer_id=None):
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
    if "observation_policy" in entity.attributes:
        policy = entity.attributes["observation_policy"]
        if type(policy) is not ObservationRangePolicy:
            return ()
        policy.__post_init__()
        values["range_version"] = policy.version
        observer_location = world.locations.get(observer_id)
        source = world.get_entity(observer_location) if observer_location else None
        destination = world.get_entity(room) if room else None
        observer_zone = None if source is None else source.attributes.get("observation_zone")
        target_zone = None if destination is None else destination.attributes.get("observation_zone")
        if type(observer_zone) is ObservationZone and type(target_zone) is ObservationZone:
            observer_zone.__post_init__()
            target_zone.__post_init__()
            observer_light = world.environment.get(observer_location)
            values.update({"observer_id": observer_id, "observer_location": observer_location,
                "observer_frame": observer_zone.frame_id, "target_frame": target_zone.frame_id,
                "observer_offset_m": observer_zone.offset_m, "target_offset_m": target_zone.offset_m,
                "coarse_distance_m": policy.coarse_distance_m, "detail_distance_m": policy.detail_distance_m,
                "detail_authorized": observer_id in policy.detail_observers,
                "observer_lit": isinstance(observer_light, dict) and observer_light.get("light_on") is True})
    return tuple((f"object:{target}:{k}", v) for k,v in values.items() if v is not None)


def select_precision(conditions, target, observer, requested):
    """Evaluate the same closed rule before projection and after evidence issuance."""
    p = f"object:{target}:"
    values = {key[len(p):]: value for key,value in conditions.items() if key.startswith(p)}
    if (observer is None or observer[2] is None or "sight" not in observer[2]
            or requested not in {"coarse", "detail"}
            or values.get("visible") is not True or values.get("lit") is not True):
        return None
    if "range_version" in values:
        try:
            policy = ObservationRangePolicy(values["range_version"], values["coarse_distance_m"],
                values["detail_distance_m"], ())
            source = ObservationZone(1, values["observer_frame"], values["observer_offset_m"])
            destination = ObservationZone(1, values["target_frame"], values["target_offset_m"])
        except (KeyError, TypeError, ValueError):
            return None
        if (observer[0] != values.get("observer_id") or observer[1] != values.get("observer_location")
                or source.frame_id != destination.frame_id or values.get("observer_lit") is not True):
            return None
        distance = abs(source.offset_m - destination.offset_m)
        if distance > policy.coarse_distance_m:
            return None
        detail = (values.get("detail_authorized") is True and distance <= policy.detail_distance_m)
    else:
        if observer[1] != values.get("location"):
            return None
        detail = values.get("holder") == observer[0]
    return "detail" if requested == "detail" and detail and values.get("detail_visible") is True else "shape"


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
    if request["entity_id"] != fact.subject_ref:
        return False
    ctx = evidence.event_time_context
    observer = next((o for o in ctx.observer_positions if o[0] == observer_id), None)
    values = dict(ctx.environment_conditions or ())
    p = f"object:{fact.subject_ref}:"
    if (fact.location_id != ctx.fact_location_id or values.get(p+"location") != fact.location_id
            or fact.fact_type != "object_appearance"):
        return False
    level = select_precision(values, fact.subject_ref, observer, request["precision"])
    return level is not None and fact.predicate == "object_"+level and fact.value == values.get(p+level)
