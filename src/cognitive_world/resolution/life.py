"""Host-authorized LifeTransition/v1; no perception or lifecycle side effects."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import hmac
import secrets

from cognitive_world.core.life import LifeState
from cognitive_world.core.world_state import WorldStateSlot
from cognitive_world.core.persistence import PersistedValueCodec
from cognitive_world.core.update import WorldUpdate
from cognitive_world.decision.attempt import Attempt
from cognitive_world.resolution.engine import ResolutionEngine, ResolutionDecision

CONTRACT = "LifeTransition/v1"
OPERATION = "life_transition"


def _reads(world, history, target):
    entity = world.get_entity(target)
    if entity is None or type(entity.state.get("life")) is not LifeState:
        raise PermissionError("explicit typed life state required")
    entity.__post_init__()
    if entity.state["life"] != LifeState(1, "alive"):
        raise PermissionError("only alive to dead is supported")
    slots = [WorldStateSlot("entities", target, path) for path in
             (("id",), ("type",), ("state", "life", "version"), ("state", "life", "value"))]
    reads = tuple(world.read_state_slot(s, event_history=history).to_record() for s in slots)
    if any(not world.verify_state_slot_record(r, event_history=history)
           or r["origin_kind"] not in ("initialization", "event") for r in reads):
        raise PermissionError("life state lacks canonical provenance")
    return reads


class LifeTransitionAuthority:
    """Constructed and installed by the trusted host, never by a provider.

    The key is ephemeral and never serialized. Historical attestations retain
    the original accepted binding; they are not new execution capabilities.
    """
    def __init__(self, processor):
        if processor.world_state is None or processor.event_history is None:
            raise ValueError("canonical processor world/history required")
        self.processor = processor
        self._key = secrets.token_bytes(32)
        self._revoked = set()
        self._permits = {}
        self._codec = PersistedValueCodec()

    def _signature(self, body):
        return hmac.new(self._key, self._codec.dumps(body), hashlib.sha256).hexdigest()

    def authorize(self, attempt, *, recipients=()):
        if type(attempt) is not Attempt or attempt.action_type != OPERATION:
            raise PermissionError("explicit life-transition Attempt required")
        if len(attempt.target_refs) != 1 or not attempt.target_refs[0].startswith("entity:"):
            raise PermissionError("one exact entity target required")
        if attempt.parameters != {"transition": "alive_to_dead"}:
            raise PermissionError("unsupported life operation parameters")
        fence = self.processor.write_fence
        if fence is None:
            raise PermissionError("life authorization requires a Runtime fence")
        permit = fence.current_permit()
        fence.require_current_permit(permit)
        target = attempt.target_refs[0][7:]
        body = dict(contract=CONTRACT, operation=OPERATION, target=target,
                    attempt=attempt._resolution_snapshot(),
                    reads=_reads(self.processor.world_state, self.processor.event_history, target),
                    transition=("alive", "dead"), write_set=((target, "state", "life"),),
                    timeline=self.processor.event_history.timeline_id,
                    tick=self.processor.simulation_clock.current_time,
                    token=secrets.token_hex(24))
        from cognitive_world.resolution.death_evidence import issue_recipient_binding
        if self.processor.persistence_trust is None:
            raise PermissionError("durable host trust required for recipient authorization")
        body["recipient_binding"] = issue_recipient_binding(
            self.processor.persistence_trust,
            event_id="event:resolution:" + attempt.attempt_id,
            attempt_fingerprint=Attempt.fingerprint_snapshot(body["attempt"]),
            target_id=target, recipients=recipients)
        self._permits[body["token"]] = permit
        return {"body": body, "signature": self._signature(body)}

    def revoke(self, authorization):
        self._revoked.add(authorization["body"]["token"])

    def validate(self, effect, snapshot, tick):
        validate_effect(effect, snapshot, tick)
        auth = effect["authorization"]
        body = auth["body"]
        if effect["effect_type"] != "life_transition_v2":
            raise PermissionError("new life submissions require recipient binding v1")
        verify_bound_recipients(effect, self.processor.persistence_trust)
        self.processor.write_fence.require_current_permit(self._permits.get(body["token"]))
        if (not hmac.compare_digest(auth["signature"], self._signature(body))
                or body["token"] in self._revoked
                or body["timeline"] != self.processor.event_history.timeline_id
                or body["tick"] != self.processor.simulation_clock.current_time
                or body["reads"] != _reads(self.processor.world_state,
                                          self.processor.event_history, body["target"])):
            raise PermissionError("unauthorized or stale life candidate")


def validate_effect(effect, snapshot, tick):
    if type(effect) is not dict or set(effect) != {"effect_type", "authorization"}:
        raise PermissionError("one closed life effect required")
    auth = effect["authorization"]
    if (effect["effect_type"] not in ("life_transition_v1", "life_transition_v2") or type(auth) is not dict
            or set(auth) != {"body", "signature"} or type(auth["signature"]) is not str):
        raise PermissionError("invalid life authorization envelope")
    b = auth["body"]
    expected = {"contract", "operation", "target", "attempt", "reads",
            "transition", "write_set", "timeline", "tick", "token"}
    if effect["effect_type"] == "life_transition_v2":
        expected.add("recipient_binding")
    if type(b) is not dict or set(b) != expected:
        raise PermissionError("closed authorization body required")
    if (b["contract"] != CONTRACT or b["operation"] != OPERATION
            or b["attempt"] != snapshot or b["tick"] != tick
            or b["transition"] != ("alive", "dead")
            or b["write_set"] != ((b["target"], "state", "life"),)
            or snapshot[3] != OPERATION or snapshot[4] != ["entity:" + b["target"]]
            or snapshot[5] != {"transition": "alive_to_dead"}):
        raise PermissionError("life Attempt/contract/write-set mismatch")


def validate_entry(event, authority=None):
    origin = event._trusted_live_resolution_origin()
    life_effect = any(type(c) is dict and c.get("effect_type") in ("life_transition_v1", "life_transition_v2")
                      for c in event.changes[1:])
    if not life_effect and (origin is None or origin[3] != OPERATION):
        return
    if (type(authority) is not LifeTransitionAuthority or origin is None
            or len(event.changes) != 2
            or event.changes[0] != {"success": True, "outcome": "life state changed"}):
        raise PermissionError("life submission requires host authority and exact effect")
    effect = event.changes[1]
    try:
        snapshot = effect["authorization"]["body"]["attempt"]
        if (snapshot[0] != origin[1] or snapshot[1] != origin[2]
                or Attempt.fingerprint_snapshot(snapshot) != origin[5]):
            raise PermissionError("life origin mismatch")
        authority.validate(effect, snapshot, event.simulation_tick)
        verify_bound_recipients(effect, authority.processor.persistence_trust, event_id=event.id)
    except (KeyError, TypeError, IndexError, ValueError) as exc:
        raise PermissionError("invalid life candidate") from exc


class LifeTransitionEngine(ResolutionEngine):
    def __init__(self, authorization):
        self.authorization = deepcopy(authorization)

    def _adjudicate(self, attempt):
        effect = {"effect_type": "life_transition_v2", "authorization": self.authorization}
        tick = self.authorization["body"]["tick"]
        validate_effect(effect, attempt._resolution_snapshot(), tick)
        return ResolutionDecision(True, "life state changed",
                                  metadata={"simulation_tick": tick}, world_effects=(effect,))


def current_update(event, world, authority):
    if authority is None or world is not authority.processor.world_state:
        raise PermissionError("life authority belongs to a different canonical world")
    validate_entry(event, authority)
    target = event.changes[1]["authorization"]["body"]["target"]
    entity = world.get_entity(target)
    state = dict(entity.state)
    state["life"] = LifeState(1, "dead")
    replacement = replace(entity, state=state)
    replacement.__post_init__()
    return WorldUpdate("entities", "update", {target: replacement})


def verify_bound_recipients(effect, trust, *, event_id=None):
    """Historical proof verification uses durable host trust, never a new permit."""
    if effect.get("effect_type") == "life_transition_v1":
        return ()  # Exact legacy contract: no historical recipient authorization.
    from cognitive_world.resolution.death_evidence import verify_recipient_binding
    body = effect["authorization"]["body"]
    snapshot = body["attempt"]
    return verify_recipient_binding(body["recipient_binding"], trust,
        event_id=event_id or "event:resolution:" + snapshot[0],
        attempt_fingerprint=Attempt.fingerprint_snapshot(snapshot), target_id=body["target"])
