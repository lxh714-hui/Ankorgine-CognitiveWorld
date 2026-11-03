"""Finite host-authorized direct-content disclosure, not a world mutation."""
from copy import deepcopy
import hashlib
import hmac
import secrets

from cognitive_world.core.persistence import PersistedValueCodec
from cognitive_world.core.physical import PhysicalRelation
from cognitive_world.core.world_state import WorldStateSlot, _leaf_slots
from cognitive_world.items.containment import effective_location
from cognitive_world.observation.observable import ObservableFactDraft

CONTRACT = "ContainerInspection/v1"
EVENT_TYPE = "container_inspected"


def capture(processor, actor_id, container_id):
    """Bounded current closure; membership absence retains tombstone origins."""
    world, history = processor.world_state, processor.event_history
    actor, container = world.get_entity(actor_id), world.get_entity(container_id)
    if (actor is None or container is None or actor.id != actor_id or container.id != container_id
            or "container" not in (container.physical_capabilities or ())
            or "sight" not in (actor.sensory_capabilities or ())
            or processor.agent_registry is None
            or not any(a.agent_id == actor_id for a in processor.agent_registry.all_agents())):
        raise PermissionError("registered sight-capable actor and container required")
    room = effective_location(world, container_id)
    if effective_location(world, actor_id) != room:
        raise PermissionError("inspection requires a shared effective location")
    direct = []
    for key, relation in world.relationships.items():
        if container_id in key:
            if type(relation) is not PhysicalRelation:
                raise PermissionError("unsupported container relationship")
            if key[1] == container_id and "contained_in" in relation.kinds:
                if relation.version != 2 or relation.source != key[0] or relation.target != key[1]:
                    raise PermissionError("invalid containment identity")
                direct.append(key[0])
    direct = tuple(sorted(direct))
    if len(direct) > 32:
        raise PermissionError("inspection content budget exceeded")
    ids = {actor_id, container_id, *direct}
    for item in direct:
        parents = [key[1] for key, r in world.relationships.items()
                   if key[0] == item and type(r) is PhysicalRelation and "contained_in" in r.kinds]
        if parents != [container_id] or world.get_location(item) != container_id:
            raise PermissionError("ambiguous or inconsistent direct containment")
    for start in tuple(ids):
        current, seen = start, set()
        while current is not None:
            if current in seen or len(ids) > 64:
                raise PermissionError("invalid inspection spatial closure")
            seen.add(current)
            entity = world.get_entity(current)
            if entity is None or entity.id != current:
                raise PermissionError("missing inspection endpoint")
            ids.add(current)
            if entity.type == "location":
                break
            current = world.get_location(current)
    related = tuple(sorted((key, r) for key, r in world.relationships.items()
                           if any(i in key for i in ids)))
    if len(related) > 128 or any(type(r) is not PhysicalRelation for _, r in related):
        raise PermissionError("inspection relationship budget exceeded")
    slots = []
    for identity in sorted(ids):
        slots.extend(_leaf_slots("entities", identity, world.get_entity(identity)))
        slots.append(WorldStateSlot("locations", identity))
    for key, r in related:
        slots.extend(_leaf_slots("relationships", key, r))
    slots.extend(slot for slot in world._slot_origins
                 if slot.collection == "relationships" and type(slot.record_id) is tuple
                 and any(i in slot.record_id for i in ids))
    if len(slots) > 1024:
        raise PermissionError("inspection read budget exceeded")
    reads = tuple(world.read_state_slot(s, event_history=history).to_record() for s in dict.fromkeys(slots))
    if any(not world.verify_state_slot_record(r, event_history=history) for r in reads):
        raise PermissionError("unverified inspection provenance")
    state = tuple({"id": i, "owner": world.get_entity(i).owner_id,
                   "location": world.get_location(i),
                   "capabilities": world.get_entity(i).physical_capabilities,
                   "life": deepcopy(world.get_entity(i).state.get("life"))} for i in sorted(ids))
    return {"actor": actor_id, "container": container_id, "direct": direct,
            "room": room, "related": related, "reads": reads, "state": state,
            "timeline": history.timeline_id, "tick": processor.simulation_clock.current_time}


class ContainerInspectionAuthority:
    """Installed host policy selects exactly which direct identities to disclose."""

    def __init__(self, processor, policy=None):
        self.processor, self.policy = processor, policy
        self._key, self._grants, self._revoked = secrets.token_bytes(32), {}, set()
        self._codec = PersistedValueCodec()

    def _signature(self, body):
        return hmac.new(self._key, self._codec.dumps(body), hashlib.sha256).hexdigest()

    def create_event(self, actor_id, container_id, *, event_id):
        from cognitive_world.event.factory import SystemEventFactory
        p, policy = self.processor, self.policy
        if p.container_inspection_authority is not self or policy is None:
            raise PermissionError("installed inspection policy required")
        identity = (getattr(policy, "policy_id", None), getattr(policy, "policy_version", None))
        if any(type(x) is not str or not x for x in identity) or not callable(getattr(policy, "evaluate", None)):
            raise PermissionError("versioned inspection policy required")
        permit = p.write_fence.current_permit()
        p.write_fence.require_current_permit(permit)
        before = capture(p, actor_id, container_id)
        try:
            selected = policy.evaluate(deepcopy(before))
        except Exception as error:
            raise PermissionError("inspection policy failed closed") from error
        if (type(selected) is not tuple or any(type(i) is not str for i in selected)
                or len(set(selected)) != len(selected) or not set(selected) <= set(before["direct"])):
            raise PermissionError("policy must select only exact direct content identities")
        if capture(p, actor_id, container_id) != before:
            raise PermissionError("inspection dependencies changed during policy evaluation")
        p.write_fence.require_candidate_origin(permit)
        p.write_fence.require_current_permit(permit)
        body = {"contract": CONTRACT, "capture": before, "selected": tuple(sorted(selected)),
                "policy": identity, "timeline": p.event_history.timeline_id,
                "tick": p.simulation_clock.current_time, "event_id": event_id,
                "token": secrets.token_hex(24)}
        self._grants[body["token"]] = (permit, policy)
        event = SystemEventFactory().create(event_id=event_id, event_type=EVENT_TYPE, timestamp="",
            simulation_tick=body["tick"], participants=[actor_id],
            changes=[{"body": body, "signature": self._signature(body)}])
        event._runtime_write_permit = permit
        return event

    def revoke(self, event):
        self._revoked.add(event.changes[0]["body"]["token"])

    def validate(self, event):
        body = historical_body(event)
        p = self.processor
        entry = self._grants.get(body["token"])
        if p.container_inspection_authority is not self or entry is None or entry[1] is not self.policy:
            raise PermissionError("inspection grant unavailable")
        p.write_fence.require_candidate_origin(entry[0])
        p.write_fence.require_current_permit(entry[0])
        if (body["token"] in self._revoked or body["timeline"] != p.event_history.timeline_id
                or body["tick"] != p.simulation_clock.current_time
                or body["policy"] != (self.policy.policy_id, self.policy.policy_version)
                or not hmac.compare_digest(event.changes[0]["signature"], self._signature(body))
                or capture(p, body["capture"]["actor"], body["capture"]["container"]) != body["capture"]):
            raise PermissionError("forged, revoked, foreign or stale inspection")
        return body


def historical_body(event):
    """Shape verification only; signed history supplies historical authenticity."""
    if (event.type != EVENT_TYPE or not event.has_trusted_source("system") or len(event.changes) != 1
            or type(event.changes[0]) is not dict or set(event.changes[0]) != {"body", "signature"}):
        raise PermissionError("invalid inspection source")
    body = event.changes[0]["body"]
    if (type(body) is not dict or set(body) != {"contract", "capture", "selected", "policy", "timeline", "tick", "event_id", "token"}
            or body["contract"] != CONTRACT or body["event_id"] != event.id
            or body["tick"] != event.simulation_tick or type(body["tick"]) is not int
            or type(body["timeline"]) is not str or not body["timeline"]
            or type(body["policy"]) is not tuple or len(body["policy"]) != 2
            or any(type(x) is not str or not x for x in body["policy"])
            or type(body["token"]) is not str or len(body["token"]) != 48
            or type(event.changes[0]["signature"]) is not str):
        raise PermissionError("invalid inspection contract")
    c = body["capture"]
    if (type(c) is not dict or set(c) != {"actor", "container", "direct", "room", "related", "reads", "state", "timeline", "tick"}
            or any(type(c[k]) is not str or not c[k] for k in ("actor", "container", "room"))
            or event.participants != [c["actor"]] or type(c["direct"]) is not tuple
            or len(c["direct"]) > 32 or any(type(i) is not str or not i for i in c["direct"])
            or type(body["selected"]) is not tuple or any(type(i) is not str for i in body["selected"])
            or tuple(sorted(set(body["selected"]))) != body["selected"]
            or not set(body["selected"]) <= set(c["direct"])
            or type(c["related"]) is not tuple or len(c["related"]) > 128
            or type(c["reads"]) is not tuple or not 1 <= len(c["reads"]) <= 1024
            or type(c["state"]) is not tuple or not 1 <= len(c["state"]) <= 64
            or c["timeline"] != body["timeline"] or c["tick"] != body["tick"]):
        raise PermissionError("invalid inspection closure")
    return body


def fact_drafts(body):
    c = body["capture"]
    # A relation fact contains no owner, hidden attributes or nested content.
    return tuple(ObservableFactDraft("container_content", "directly_contained_in", c["container"],
                 subject_ref=item, location_id=c["room"]) for item in body["selected"])


def allows_fact(event, evidence, owner, fact, history=None):
    """Historical disclosure qualification never grants live execution authority."""
    try:
        b = historical_body(event)
    except (PermissionError, TypeError, ValueError):
        return False
    c, ctx = b["capture"], evidence.event_time_context
    if (not evidence.has_trusted_source(event) or owner != c["actor"]
            or ctx.simulation_time != b["tick"] or ctx.fact_location_id != c["room"]
            or not any(a == owner for a, _, _ in ctx.observer_positions)
            or dict(ctx.environment_conditions or ()).get("container-inspection:source") != event.id
            or not fact.has_trusted_source(event) or fact not in evidence.observable_facts
            or fact.fact_type != "container_content" or fact.predicate != "directly_contained_in"
            or fact.subject_ref not in b["selected"] or fact.value != c["container"]
            or fact.location_id != c["room"]):
        return False
    if history is not None:
        recorded = history.get_event(event.id)
        if (history.requires_recovery() or recorded is None
                or recorded._source_snapshot() != event._source_snapshot()
                or history.get_processing_evidence(event.id) != evidence):
            return False
    return True
