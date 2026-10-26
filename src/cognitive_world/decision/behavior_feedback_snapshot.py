"""Versioned snapshot component for transient decision feedback.

The component stores historical failures, not a canonical cognition Store. Its
authenticity is supplied by the containing signed SnapshotBundle manifest;
EventHistory and each Event's processing attestation remain the source authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from cognitive_world.decision.behavior_feedback import BehaviorFailure, BehaviorFeedback


_SCHEMA = "cognitive-world/behavior-feedback-snapshot"
_VERSION = 1


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class VerifiedBehaviorFeedback:
    feedback: BehaviorFeedback
    status: str
    source_timeline_id: str
    source_simulation_tick: int
    source_session_id: str
    source_restore_generation: int
    agent_ids: tuple[str, ...]


class BehaviorFeedbackSnapshot:
    """Capture and reconstruct feedback only after binding every source Event."""

    @staticmethod
    def capture(*, feedback: BehaviorFeedback, event_history: object,
                timeline_id: str, simulation_tick: int, session_id: str,
                restore_generation: int, agent_ids: tuple[str, ...],
                memory_store=None, trust=None) -> bytes:
        if type(feedback) is not BehaviorFeedback:
            raise TypeError("canonical BehaviorFeedback is required")
        if (not isinstance(timeline_id, str) or not timeline_id
                or not isinstance(session_id, str) or not session_id
                or type(simulation_tick) is not int or simulation_tick < 0
                or type(restore_generation) is not int or restore_generation < 0
                or not isinstance(agent_ids, tuple)
                or any(not isinstance(item, str) or not item for item in agent_ids)
                or len(agent_ids) != len(set(agent_ids))):
            raise ValueError("invalid BehaviorFeedback snapshot binding")
        BehaviorFeedbackSnapshot._validate_history(feedback, event_history, set(agent_ids), simulation_tick, memory_store=memory_store, trust=trust)
        return _canonical(BehaviorFeedbackSnapshot._body(
            feedback, timeline_id, simulation_tick, session_id, restore_generation, agent_ids,
        ))

    @staticmethod
    def verify_and_restore(*, payload: bytes, event_history: object,
                           timeline_id: str, simulation_tick: int,
                           session_id: str | None = None,
                           restore_generation: int | None = None,
                           agent_ids: tuple[str, ...], memory_store=None, trust=None) -> VerifiedBehaviorFeedback:
        if not isinstance(payload, bytes):
            raise TypeError("BehaviorFeedback snapshot must be bytes")
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("malformed BehaviorFeedback snapshot") from error
        required = {"schema", "version", "timeline_id", "simulation_tick", "session_id",
                    "restore_generation", "agent_ids", "half_life_ticks",
                    "frustration_half_life_ticks", "maximum_penalty", "failures"}
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("malformed BehaviorFeedback snapshot fields")
        if value["schema"] != _SCHEMA or type(value["version"]) is not int or value["version"] not in (1,2):
            raise ValueError("unsupported BehaviorFeedback snapshot schema")
        if (value["timeline_id"] != timeline_id or value["simulation_tick"] != simulation_tick
                or (session_id is not None and value["session_id"] != session_id)
                or (restore_generation is not None
                    and value["restore_generation"] != restore_generation)
                or tuple(value["agent_ids"]) != tuple(sorted(agent_ids))):
            raise PermissionError("BehaviorFeedback snapshot binding does not match the signed bundle")
        failures = value["failures"]
        if not isinstance(failures, list):
            raise ValueError("BehaviorFeedback failures must be an array")
        records = []
        for row in failures:
            fields = {"owner_id", "action_type", "target", "method", "conditions", "event_id",
                      "tick", "penalty", "consecutive_failures"}
            consumption = None
            if value["version"] == 2:
                from cognitive_world.decision.consumed_failure import ConsumedFailureBinding
                if type(row) is not dict or type(row.get("record_version")) is not int or row["record_version"] not in (1,2):
                    raise ValueError("unsupported feedback record version")
                fields.add("record_version")
                if row["record_version"] == 2:
                    fields.add("consumption")
                    payload=row.get("consumption")
                    if type(payload) is not dict or set(payload)!={"version","proof_id"}:
                        raise ValueError("malformed feedback consumption binding")
                    consumption=ConsumedFailureBinding(**payload)
            if not isinstance(row, dict) or set(row) != fields:
                raise ValueError("malformed BehaviorFailure record")
            if (row["owner_id"] not in agent_ids or type(row["tick"]) is not int
                    or row["tick"] < 0 or row["tick"] > simulation_tick
                    or not isinstance(row["conditions"], list)
                    or any(not isinstance(pair, list) or len(pair) != 2
                           or any(not isinstance(item, str) for item in pair)
                           for pair in row["conditions"])):
                raise PermissionError("BehaviorFailure owner, time or condition is invalid")
            record = BehaviorFailure(
                row["owner_id"], row["action_type"], row["target"], row["method"],
                tuple(tuple(pair) for pair in row["conditions"]), row["event_id"],
                row["tick"], row["penalty"], row["consecutive_failures"], consumption,
            )
            if (not record.owner_id or not record.action_type or not record.target
                    or not record.method or not record.event_id
                    or isinstance(record.penalty, bool) or not isinstance(record.penalty, (int, float))
                    or not 0 < record.penalty <= value["maximum_penalty"]
                    or type(record.consecutive_failures) is not int
                    or record.consecutive_failures < 1):
                raise ValueError("invalid BehaviorFailure value")
            records.append(record)
        event_ids = [item.event_id for item in records]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("duplicate BehaviorFailure Event_ID")
        feedback = BehaviorFeedback(
            half_life_ticks=value["half_life_ticks"],
            frustration_half_life_ticks=value["frustration_half_life_ticks"],
            maximum_penalty=value["maximum_penalty"],
            history=records, _seen_events=set(event_ids),
        )
        BehaviorFeedbackSnapshot._validate_history(feedback, event_history, set(agent_ids), simulation_tick, memory_store=memory_store, trust=trust)
        return VerifiedBehaviorFeedback(
            feedback, "restored", value["timeline_id"], value["simulation_tick"],
            value["session_id"], value["restore_generation"], tuple(value["agent_ids"]),
        )

    @staticmethod
    def _body(feedback: BehaviorFeedback, timeline_id: str, tick: int, session_id: str,
              generation: int, agent_ids: tuple[str, ...]) -> dict[str, Any]:
        failures = [{
            "owner_id": item.owner_id, "action_type": item.action_type,
            "target": item.target, "method": item.method,
            "conditions": [list(pair) for pair in item.conditions],
            "event_id": item.event_id, "tick": item.tick,
            "penalty": item.penalty, "consecutive_failures": item.consecutive_failures,
        } for item in feedback.history]
        version=2 if any(item.consumption is not None for item in feedback.history) else _VERSION
        if version==2:
            from cognitive_world.decision.consumed_failure import ConsumedFailureBinding
            for item,row in zip(feedback.history,failures,strict=True):
                row["record_version"]=1 if item.consumption is None else 2
                if item.consumption is not None:
                    if type(item.consumption) is not ConsumedFailureBinding:
                        raise PermissionError("unsupported feedback consumption type")
                    row["consumption"]={"version":item.consumption.version,"proof_id":item.consumption.proof_id}
        return {
            "schema": _SCHEMA, "version": version, "timeline_id": timeline_id,
            "simulation_tick": tick, "session_id": session_id,
            "restore_generation": generation, "agent_ids": sorted(agent_ids),
            "half_life_ticks": feedback.half_life_ticks,
            "frustration_half_life_ticks": feedback.frustration_half_life_ticks,
            "maximum_penalty": feedback.maximum_penalty, "failures": failures,
        }

    @staticmethod
    def _validate_history(feedback: BehaviorFeedback, event_history: object,
                          agent_ids: set[str], simulation_tick: int, *, memory_store=None, trust=None) -> None:
        from cognitive_world.event.attempt_source import verify_confirmed_failure_event
        get_event = getattr(event_history, "get_event", None)
        if not callable(get_event):
            raise TypeError("authoritative EventHistory is required")
        event_ids = []
        for failure in feedback.history:
            if failure.owner_id not in agent_ids or type(failure.tick) is not int or not 0 <= failure.tick <= simulation_tick:
                raise PermissionError("BehaviorFailure owner or time is outside snapshot scope")
            if failure.consumption is not None:
                from cognitive_world.decision.consumed_failure import verify_consumed_failure
                if (type(failure.penalty) not in (int,float) or not 0<failure.penalty<=feedback.maximum_penalty
                        or type(failure.consecutive_failures) is not int or failure.consecutive_failures<1):
                    raise PermissionError("invalid consumed feedback score")
                verify_consumed_failure(failure,history=event_history,memory_store=memory_store,trust=trust,tick=simulation_tick)
                event_ids.append(failure.event_id)
                continue
            event = get_event(failure.event_id)
            source = None if event is None else event.metadata.get("confirmed_attempt_failure")
            observed_conditions = BehaviorFeedbackSnapshot._observed_conditions(
                event_history, () if not isinstance(source, dict) else source.get("source_refs", ()),
                failure.owner_id, failure.target,
            )
            if (event is None or not event.has_trusted_source("resolution")
                    or not verify_confirmed_failure_event(event)
                    or event.simulation_tick != failure.tick
                    or not isinstance(source, dict)
                    or source.get("owner_id") != failure.owner_id
                    or source.get("action_type") != failure.action_type
                    or tuple(source.get("target_refs", ()))[:1] != (failure.target,)
                    or source.get("method") != failure.method
                    or "door_locked" not in source.get("verified_conditions", ())
                    or not failure.conditions
                    or tuple(sorted(set(failure.conditions))) != failure.conditions
                    or set(failure.conditions) != observed_conditions):
                raise PermissionError("BehaviorFailure does not match a verified in-line locked-door Event")
            event_ids.append(failure.event_id)
        if len(event_ids) != len(set(event_ids)) or set(feedback._seen_events) != set(event_ids):
            raise PermissionError("BehaviorFeedback consumed-Event index is inconsistent")

    @staticmethod
    def _observed_conditions(event_history: object, source_refs: object,
                             owner_id: str, target: str) -> set[tuple[str, str]]:
        """Resolve feedback conditions only from signed, processor-issued observations.

        The failure Event's signed Attempt source binds these references. This
        method independently resolves each reference through EventHistory and
        refuses unknown or untrusted percept references.
        """
        from cognitive_world.observation.observable import EventProcessingEvidence

        if not isinstance(source_refs, (tuple, list)) or not source_refs:
            return set()
        get_event = getattr(event_history, "get_event", None)
        get_evidence = getattr(event_history, "get_processing_evidence", None)
        if not callable(get_event) or not callable(get_evidence):
            return set()

        events = {item.id: item for item in event_history.get_events()}
        facts: set[tuple[str, str]] = set()
        recognized: set[str] = set()
        for event_id, source_event in events.items():
            evidence = get_evidence(event_id)
            if (not isinstance(evidence, EventProcessingEvidence)
                    or evidence.source_event_id != event_id
                    or not evidence.has_trusted_source(source_event)):
                continue
            fact_refs = {fact.fact_id: fact for fact in evidence.observable_facts
                         if fact.has_trusted_source(source_event)}
            for ref in source_refs:
                if ref == event_id:
                    recognized.add(ref)
                elif isinstance(ref, str) and ref.startswith(f"percept:observation:{event_id}:"):
                    matching = next((fact for fact_id, fact in fact_refs.items()
                                     if fact_id in ref and fact.subject_ref == target
                                     and f":{owner_id}:" in ref
                                     and any(observer == owner_id
                                             and position == fact.location_id
                                             for observer, position, _ in
                                             evidence.event_time_context.observer_positions)), None)
                    if matching is not None:
                        recognized.add(ref)
                        facts.add((matching.predicate, str(matching.value)))
        if recognized != set(source_refs):
            return set()
        return facts


__all__ = ["BehaviorFeedbackSnapshot", "VerifiedBehaviorFeedback"]
