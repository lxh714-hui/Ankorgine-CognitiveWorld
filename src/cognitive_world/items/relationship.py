"""Finite host-policy relationship operations; no independent canonical Store."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import hmac
import secrets

from cognitive_world.core.physical import PhysicalRelation, validate_physical_world
from cognitive_world.core.world_state import WorldStateSlot, _leaf_slots
from cognitive_world.core.persistence import PersistedValueCodec
from cognitive_world.core.update import WorldUpdate
from cognitive_world.decision.attempt import Attempt
from cognitive_world.resolution.engine import ResolutionEngine, ResolutionDecision
from cognitive_world.items.containment import effective_location

CONTRACT = "GovernedObjectRelation/v1"
EFFECT = "governed_object_relation_v1"
OPERATIONS = {"contain", "release", "detach", "transfer"}


def capture(world, history, attempt):
    """Bounded exact dependencies, including negative item-relation membership."""
    if type(attempt) is not Attempt or attempt.action_type not in OPERATIONS:
        raise PermissionError("unsupported object operation")
    refs, params = attempt.target_refs, attempt.parameters
    if len(refs) != 1 or not refs[0].startswith("object:"):
        raise PermissionError("one exact object required")
    item_id = refs[0][7:]
    expected_keys = {"old_owner", "new_owner"} if attempt.action_type == "transfer" else {"parent"}
    if set(params) != expected_keys:
        raise PermissionError("closed operation parameters required")
    actor, item = world.get_entity(attempt.agent_id), world.get_entity(item_id)
    if (actor is None or item is None or actor.id != attempt.agent_id or item.id != item_id
            or item.type in {"character", "agent", "location"}):
        raise PermissionError("unsupported actor/item")
    if "manual_manipulation" not in (actor.physical_capabilities or ()):
        raise PermissionError("manual capability required")
    related = tuple(sorted(((key, value) for key, value in world.relationships.items()
                            if item_id in key), key=lambda pair: pair[0]))
    if len(related) > 16 or any(type(r) is not PhysicalRelation for _, r in related):
        raise PermissionError("unsupported item relationship closure")
    ids = {item_id, attempt.agent_id}
    if attempt.action_type == "transfer":
        if params["old_owner"] != item.owner_id or params["new_owner"] == item.owner_id:
            raise PermissionError("ownership expectation mismatch")
        if type(params["new_owner"]) is not str or not params["new_owner"]:
            raise PermissionError("explicit new owner required")
        ids.update(x for x in (item.owner_id, params["new_owner"]) if x is not None)
    else:
        if type(params["parent"]) is not str or not params["parent"]:
            raise PermissionError("explicit parent required")
        ids.add(params["parent"])
    ids.update(x for key, _ in related for x in key)
    # Include spatial chains: release uses the current effective parent location.
    for start in tuple(ids):
        current, seen = start, set()
        while current is not None:
            if current in seen or len(ids) > 64:
                raise PermissionError("invalid or over-budget spatial closure")
            seen.add(current)
            entity = world.get_entity(current)
            if entity is None or entity.id != current:
                raise PermissionError("missing operation endpoint")
            ids.add(current)
            if entity.type == "location": break
            current = world.get_location(current)
    slots = []
    for key in sorted(ids):
        entity = world.get_entity(key)
        slots.extend(_leaf_slots("entities", key, entity))
        slots.append(WorldStateSlot("locations", key))
    for key, relation in related:
        slots.extend(_leaf_slots("relationships", key, relation))
    # Negative relationship membership has history too. Include the canonical
    # tombstone origins for this item, so add/remove ABA cannot restore an old
    # grant merely because the current relationship set and location match.
    slots.extend(slot for slot in world._slot_origins
                 if slot.collection == "relationships" and type(slot.record_id) is tuple
                 and item_id in slot.record_id)
    if len(slots) > 512:
        raise PermissionError("operation dependency budget exceeded")
    reads = tuple(world.read_state_slot(s, event_history=history).to_record()
                  for s in dict.fromkeys(slots))
    if any(not world.verify_state_slot_record(r, event_history=history)
           or r["present"] and r["origin_kind"] not in {"event", "initialization"} for r in reads):
        raise PermissionError("operation dependency lacks canonical provenance")
    values = tuple({"id": key, "owner_id": world.get_entity(key).owner_id,
                    "life": deepcopy(world.get_entity(key).state.get("life")),
                    "capabilities": world.get_entity(key).physical_capabilities,
                    "location": world.get_location(key)} for key in sorted(ids))
    body = {"attempt": attempt._resolution_snapshot(), "related": related, "reads": reads,
            "state": values}
    # Independently validate that this finite operation is currently meaningful.
    stage(world, body)
    return body


def stage(world, body):
    """Build fully validated replacement collections without publishing them."""
    snapshot = body["attempt"]
    op, item_id, params = snapshot[3], snapshot[4][0][7:], snapshot[5]
    entities, locations, relations = (deepcopy(dict(world.entities)),
                                    deepcopy(dict(world.locations)), deepcopy(dict(world.relationships)))
    item = entities[item_id]
    if op == "transfer":
        if item.owner_id != params["old_owner"] or params["new_owner"] not in entities:
            raise PermissionError("owner changed or missing")
        # Preserve unrelated kinds even when owned_by shares a pair.
        for key, r in tuple(relations.items()):
            if type(r) is PhysicalRelation and r.source == item_id and "owned_by" in r.kinds:
                kinds = tuple(k for k in r.kinds if k != "owned_by")
                if kinds: relations[key] = replace(r, kinds=kinds)
                else: del relations[key]
        entities[item_id] = replace(item, owner_id=params["new_owner"])
        key = (item_id, params["new_owner"])
        prior = relations.get(key)
        if prior is not None and type(prior) is not PhysicalRelation:
            raise PermissionError("unsupported ownership pair")
        relations[key] = PhysicalRelation(1 if prior is None else prior.version, *key,
            (() if prior is None else prior.kinds) + ("owned_by",))
    else:
        parent = params["parent"]
        key = (item_id, parent)
        prior = relations.get(key)
        if op == "contain":
            if "container" not in (entities[parent].physical_capabilities or ()):
                raise PermissionError("container capability required")
            if any(r.source == item_id and set(r.kinds) & {"held_by", "contained_in", "attached_to", "part_of"}
                   for r in relations.values() if type(r) is PhysicalRelation):
                raise PermissionError("item must first be released/detached")
            if effective_location(world, item_id) != effective_location(world, parent):
                raise PermissionError("container is not co-located")
            relations[key] = PhysicalRelation(2, *key, (() if prior is None else prior.kinds) + ("contained_in",))
            locations[item_id] = parent
        else:
            if type(prior) is not PhysicalRelation:
                raise PermissionError("exact current relationship required")
            if op == "release":
                kinds = set(prior.kinds) & {"held_by", "contained_in"}
                if len(kinds) != 1 or locations.get(item_id) != parent:
                    raise PermissionError("holder/container mismatch")
                remove = kinds.pop()
            elif op == "detach":
                if ("attached_to" not in prior.kinds or "detachable" not in (item.physical_capabilities or ())
                        or any(r.source == item_id and set(r.kinds) & {"part_of", "held_by", "contained_in"}
                               for r in relations.values() if type(r) is PhysicalRelation)):
                    raise PermissionError("unsupported detachable structure")
                remove = "attached_to"
            else:
                raise PermissionError("unsupported relationship operation")
            remaining = tuple(k for k in prior.kinds if k != remove)
            if remaining: relations[key] = replace(prior, kinds=remaining)
            else: del relations[key]
            locations[item_id] = effective_location(world, parent)
        if effective_location(world, snapshot[1]) != effective_location(world, parent):
            raise PermissionError("actor is not co-located")
    validate_physical_world(entities, locations, relations)
    return entities, locations, relations


class RelationshipAuthority:
    """Trusted host policy issuance; ephemeral grants never survive restoration."""
    def __init__(self, processor, policy=None):
        self.processor, self.policy = processor, policy
        self._key, self._permits, self._revoked = secrets.token_bytes(32), {}, set()
        self._codec = PersistedValueCodec()

    def _signature(self, body):
        return hmac.new(self._key, self._codec.dumps(body), hashlib.sha256).hexdigest()

    def authorize(self, attempt):
        p = self.processor
        if self.policy is None or not callable(getattr(self.policy, "evaluate", None)):
            raise PermissionError("explicit relationship policy required")
        policy_id, version = getattr(self.policy, "policy_id", None), getattr(self.policy, "policy_version", None)
        if type(policy_id) is not str or not policy_id or type(version) is not str or not version:
            raise PermissionError("explicit policy identity required")
        permit = p.write_fence.current_permit()
        p.write_fence.require_current_permit(permit)
        captured = capture(p.world_state, p.event_history, attempt)
        if self.policy.evaluate(deepcopy(captured)) is not True:
            raise PermissionError("relationship policy declined")
        if capture(p.world_state, p.event_history, attempt) != captured:
            raise PermissionError("policy call changed dependencies")
        p.write_fence.require_candidate_origin(permit)
        p.write_fence.require_current_permit(permit)
        body = {**captured, "contract": CONTRACT, "policy": (policy_id, version),
                "timeline": p.event_history.timeline_id, "tick": p.simulation_clock.current_time,
                "token": secrets.token_hex(24)}
        self._permits[body["token"]] = (permit, self.policy)
        return {"body": body, "signature": self._signature(body)}

    def revoke(self, grant):
        self._revoked.add(grant["body"]["token"])

    def validate(self, event):
        body = validate_history(event)
        p = self.processor
        grant = event.changes[1]["authorization"]
        entry = self._permits.get(body["token"])
        if entry is None or entry[1] is not self.policy:
            raise PermissionError("missing grant or replaced policy")
        p.write_fence.require_candidate_origin(entry[0])
        p.write_fence.require_current_permit(entry[0])
        if (body["token"] in self._revoked or body["timeline"] != p.event_history.timeline_id
                or body["tick"] != p.simulation_clock.current_time
                or self.policy is None or body["policy"] != (self.policy.policy_id, self.policy.policy_version)
                or not hmac.compare_digest(grant["signature"], self._signature(body))):
            raise PermissionError("forged, foreign, revoked or stale relationship grant")
        s = body["attempt"]
        attempt = Attempt(s[0], s[1], s[2], s[3], s[4], s[5], s[6], intent_id=s[7], initiator_id=s[8])
        current = capture(p.world_state, p.event_history, attempt)
        if any(current[k] != body[k] for k in current):
            raise PermissionError("relationship dependency changed")
        origin = event._trusted_live_resolution_origin()
        if origin is None or origin[1] != s[0] or origin[2] != s[1] or origin[5] != Attempt.fingerprint_snapshot(s):
            raise PermissionError("relationship grant lacks exact live Attempt origin")
        return stage(p.world_state, body)


def validate_history(event):
    """Validate closed signed historical structure, never issue live authority."""
    if len(event.changes) != 2 or event.changes[0] != {"success": True, "outcome": "object relationship changed"}:
        raise PermissionError("one exact successful relationship effect required")
    effect = event.changes[1]
    if type(effect) is not dict or set(effect) != {"effect_type", "authorization"} or effect["effect_type"] != EFFECT:
        raise PermissionError("closed relationship effect required")
    auth = effect["authorization"]
    if type(auth) is not dict or set(auth) != {"body", "signature"} or type(auth["signature"]) is not str:
        raise PermissionError("closed relationship grant required")
    b = auth["body"]
    if type(b) is not dict or set(b) != {"attempt", "related", "reads", "state", "contract", "policy", "timeline", "tick", "token"}:
        raise PermissionError("closed relationship body required")
    s = b["attempt"]
    Attempt.fingerprint_snapshot(s)
    if (type(s) is not tuple or len(s) != 9 or type(s[5]) is not dict
            or type(b["tick"]) is not int or b["tick"] < 0
            or type(b["timeline"]) is not str or not b["timeline"]
            or type(b["policy"]) is not tuple or len(b["policy"]) != 2
            or any(type(x) is not str or not x for x in b["policy"])
            or type(b["token"]) is not str or len(b["token"]) != 48
            or type(b["reads"]) is not tuple or not 1 <= len(b["reads"]) <= 512
            or type(b["related"]) is not tuple or len(b["related"]) > 16):
        raise PermissionError("invalid relationship history values")
    if type(b["state"]) is not tuple or not 1 <= len(b["state"]) <= 64:
        raise PermissionError("bounded policy state required")
    keys = {"old_owner", "new_owner"} if s[3] == "transfer" else {"parent"}
    if (set(s[5]) != keys or b["contract"] != CONTRACT or s[3] not in OPERATIONS or len(s[4]) != 1
            or not s[4][0].startswith("object:") or b["tick"] != event.simulation_tick
            or event.cause != s[0] or event.id != "event:resolution:" + s[0]):
        raise PermissionError("relationship occurrence mismatch")
    return b


class RelationshipResolutionEngine(ResolutionEngine):
    def __init__(self, grant):
        self.grant = deepcopy(grant)

    def _adjudicate(self, attempt):
        if self.grant["body"]["attempt"] != attempt._resolution_snapshot():
            raise PermissionError("relationship Attempt substitution")
        return ResolutionDecision(True, "object relationship changed",
            metadata={"simulation_tick": self.grant["body"]["tick"]},
            world_effects=({"effect_type": EFFECT, "authorization": self.grant},))


def current_update(event, processor):
    authority = processor.relationship_authority
    if type(authority) is not RelationshipAuthority or authority.processor is not processor:
        raise PermissionError("installed relationship authority required")
    authority.validate(event)
    return WorldUpdate("object_relationship", "apply", deepcopy(event.changes[1]))
