"""Structured, Event-bound source for confirmed no-effect failures."""
from __future__ import annotations

from collections.abc import Mapping

from cognitive_world.core.event import Event
from cognitive_world.decision.attempt import Attempt


_FIELDS = {
    "schema", "attempt_id", "attempt_fingerprint", "owner_id",
    "action_type", "target_refs", "method", "simulation_tick", "source_refs",
    "verified_conditions", "condition_source_refs", "state_slot_reads",
}
_SCHEMA = "cognitive-world/confirmed-attempt-failure/v1"


def attempt_failure_source(snapshot: tuple[object, ...], *, tick: int,
                           failure_conditions: Mapping[str, object] | None = None) -> dict[str, object]:
    """Project the trusted Resolution snapshot into signed Event metadata."""
    if len(snapshot) != 9 or isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
        raise ValueError("confirmed failure requires a complete Attempt and simulation tick")
    attempt_id, owner, _, action_type, targets, parameters, metadata = snapshot[:7]
    if (not isinstance(attempt_id, str) or not attempt_id or not isinstance(owner, str)
            or not owner or not isinstance(action_type, str) or not action_type
            or not isinstance(targets, (list, tuple)) or not targets
            or any(not isinstance(item, str) or not item for item in targets)
            or not isinstance(parameters, Mapping)):
        raise ValueError("confirmed failure Attempt identity is malformed")
    method = parameters.get("method")
    if not isinstance(method, str) or not method:
        raise ValueError("confirmed failure Attempt has no structured method")
    refs = metadata.get("action_proposal_reasoning_refs", ()) if isinstance(metadata, Mapping) else ()
    if not isinstance(refs, (list, tuple)) or any(not isinstance(ref, str) or not ref for ref in refs):
        raise ValueError("Attempt evidence references are malformed")
    conditions = () if failure_conditions is None else failure_conditions.get("conditions", ())
    condition_refs = () if failure_conditions is None else failure_conditions.get("source_refs", ())
    reads = () if failure_conditions is None else failure_conditions.get("state_slot_reads", ())
    if (not isinstance(conditions, (tuple, list)) or not conditions
            or any(not isinstance(item, str) or not item for item in conditions)
            or not isinstance(condition_refs, (tuple, list)) or not condition_refs
            or any(not isinstance(item, str) or not item for item in condition_refs)
            or not isinstance(reads, (tuple, list)) or not reads
            or any(not isinstance(item, Mapping) for item in reads)):
        raise ValueError("confirmed failure lacks structured condition and state-read evidence")
    return {
        "schema": _SCHEMA,
        "attempt_id": attempt_id,
        "attempt_fingerprint": Attempt.fingerprint_snapshot(snapshot),
        "owner_id": owner,
        "action_type": action_type,
        "target_refs": tuple(targets),
        "method": method,
        "simulation_tick": tick,
        "source_refs": tuple(sorted(set(refs))),
        "verified_conditions": tuple(conditions),
        "condition_source_refs": tuple(condition_refs),
        "state_slot_reads": tuple(dict(item) for item in reads),
    }


def verify_confirmed_failure_event(event: object, *, attempt: Attempt | None = None) -> bool:
    """Check the signed-source projection and its Event/Attempt binding.

    Authenticity of a persisted instance still comes from EventProcessor's
    signed processing record; this function checks claim consistency only.
    """
    if not isinstance(event, Event) or event.type != "resolution" or event.simulation_tick is None:
        return False
    if (not event.changes or not isinstance(event.changes[0], Mapping)
            or event.changes[0].get("success") is not False or len(event.changes) != 1):
        return False
    source = event.metadata.get("confirmed_attempt_failure")
    if not isinstance(source, Mapping) or set(source) != _FIELDS or source.get("schema") != _SCHEMA:
        return False
    if (source.get("attempt_id") != event.cause
            or source.get("attempt_id") != event.metadata.get("attempt_id")
            or source.get("attempt_fingerprint") != event.metadata.get("attempt_fingerprint")
            or source.get("simulation_tick") != event.simulation_tick
            or not isinstance(source.get("owner_id"), str) or not source["owner_id"]
            or not isinstance(source.get("action_type"), str)
            or not isinstance(source.get("target_refs"), (tuple, list))
            or not source.get("target_refs")
            or any(not isinstance(item, str) or not item for item in source["target_refs"])
            or not isinstance(source.get("method"), str) or not source["method"]
            or not isinstance(source.get("source_refs"), (tuple, list))
            or any(not isinstance(item, str) or not item for item in source["source_refs"])
            or not isinstance(source.get("verified_conditions"), (tuple, list))
            or not source["verified_conditions"]
            or any(not isinstance(item, str) or not item for item in source["verified_conditions"])
            or not isinstance(source.get("condition_source_refs"), (tuple, list))
            or not source["condition_source_refs"]
            or any(not isinstance(item, str) or not item for item in source["condition_source_refs"])
            or not isinstance(source.get("state_slot_reads"), (tuple, list))
            or not source["state_slot_reads"]
            or any(not isinstance(item, Mapping) for item in source["state_slot_reads"])):
        return False
    if attempt is None:
        return True
    failure_conditions = {
        "conditions": source["verified_conditions"],
        "source_refs": source["condition_source_refs"],
        "state_slot_reads": source["state_slot_reads"],
    }
    try:
        expected = attempt_failure_source(
            attempt._resolution_snapshot(), tick=event.simulation_tick,
            failure_conditions=failure_conditions,
        )
    except (TypeError, ValueError):
        return False
    return dict(source) == expected
