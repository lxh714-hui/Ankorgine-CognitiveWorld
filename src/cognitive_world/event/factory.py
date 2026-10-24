"""Create Event records from resolved outcomes."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from cognitive_world.core.event import Event
from cognitive_world.resolution.result import ResolutionResult
from cognitive_world.decision.attempt import Attempt
from cognitive_world.safety.governance import SafetyInput, UniversalSafetyGovernance


@dataclass
class EventFactory:
    """Build a factual Event record from a ResolutionResult."""

    safety_governance: UniversalSafetyGovernance = field(default_factory=UniversalSafetyGovernance)

    def __post_init__(self) -> None:
        if not isinstance(self.safety_governance, UniversalSafetyGovernance):
            raise TypeError("EventFactory requires UniversalSafetyGovernance")

    def bind_safety_governance(self, governance: UniversalSafetyGovernance) -> None:
        if not isinstance(governance, UniversalSafetyGovernance):
            raise TypeError("governance must be UniversalSafetyGovernance")
        self.safety_governance = governance

    def create_from_resolution(
        self,
        resolution_result: ResolutionResult,
        *,
        action_proposal_id: str | None = None,
        action_expectation_id: str | None = None,
    ) -> Event:
        """Create an Event retaining the resolution and Attempt provenance."""
        if not isinstance(resolution_result, ResolutionResult):
            raise TypeError("resolution_result must be a ResolutionResult")
        if not resolution_result._has_valid_confirmation():
            raise ValueError("ResolutionResult lacks a valid controlled confirmation")

        snapshot = resolution_result._attempt_snapshot
        if not isinstance(snapshot, tuple) or len(snapshot) != 9:
            raise PermissionError("Resolution confirmation lacks the complete bound Attempt snapshot")
        actor_id, action_type, targets, parameters = snapshot[1], snapshot[3], snapshot[4], snapshot[5]
        if not isinstance(actor_id, str) or not isinstance(action_type, str) or not isinstance(targets, (tuple, list)) or not isinstance(parameters, dict):
            raise PermissionError("Resolution confirmation has an invalid bound Attempt shape")
        method = parameters.get("method", "")
        raw_steps = parameters.get("steps", ())
        steps = tuple(
            item if isinstance(item, str) else str(item.get("method", ""))
            for item in raw_steps
        ) if isinstance(raw_steps, (tuple, list)) else ()
        self.safety_governance.require_action_allowed(SafetyInput(
            actor_id=actor_id,
            source="trusted_effect_commit",
            intent=action_type,
            target_refs=tuple(targets),
            method=method if isinstance(method, str) else "",
            context="effect authorization recheck; attempt fields remain untrusted claims",
            ordered_steps=steps,
        ))

        metadata = deepcopy(resolution_result.metadata)
        timestamp = metadata.pop("timestamp", "")
        simulation_tick = metadata.pop("simulation_tick", None)
        if simulation_tick is not None and (
            isinstance(simulation_tick, bool)
            or not isinstance(simulation_tick, int)
            or simulation_tick < 0
        ):
            raise ValueError("trusted simulation_tick must be a non-negative integer")
        attempt_fingerprint = None
        if isinstance(resolution_result._attempt_snapshot, tuple):
            try:
                attempt_fingerprint = Attempt.fingerprint_snapshot(
                    resolution_result._attempt_snapshot
                )
            except ValueError:
                # The existing signed ResolutionResult remains authoritative;
                # only stepwise replay requires this additional JSON digest.
                attempt_fingerprint = None
        metadata.update(
            {
                "resolution_id": resolution_result.resolution_id,
                "attempt_id": resolution_result.attempt_id,
                "attempt_fingerprint": attempt_fingerprint,
            }
        )
        if resolution_result.result_kind is not None:
            metadata["action_result_kind"] = resolution_result.result_kind.value
        if resolution_result.success is False:
            from cognitive_world.event.attempt_source import attempt_failure_source

            if simulation_tick is not None:
                try:
                    metadata["confirmed_attempt_failure"] = attempt_failure_source(
                        snapshot, tick=simulation_tick,
                        failure_conditions=resolution_result.metadata.get(
                            "confirmed_failure_conditions"
                        ),
                    )
                except ValueError:
                    # A confirmed failure may still be recorded, but cannot
                    # drive behavior adaptation without the structured source.
                    pass
        initiator_id = snapshot[8]
        if initiator_id is not None:
            if not isinstance(initiator_id, str) or not initiator_id:
                raise PermissionError("Resolution confirmation has invalid initiator attribution")
            metadata["initiator_id"] = initiator_id
        if action_proposal_id is not None:
            metadata["action_proposal_id"] = action_proposal_id
        if action_expectation_id is not None:
            metadata["action_expectation_id"] = action_expectation_id
        event = Event(
            id=f"event:{resolution_result.resolution_id}",
            type="resolution",
            timestamp=timestamp,
            cause=resolution_result.attempt_id,
            changes=[
                {
                    "success": resolution_result.success,
                    "outcome": resolution_result.outcome,
                },
                *deepcopy(resolution_result.world_effects),
            ],
            metadata=metadata,
            simulation_tick=simulation_tick,
        )
        event._issue_source_receipt("resolution")
        return event


@dataclass
class SystemEventFactory:
    """Explicit ingress for trusted runtime/system events outside an Attempt.

    This boundary is intended for trusted application subsystems. It is not an
    authentication mechanism against malicious code in the same process.
    """

    def create(
        self,
        *,
        event_id: str,
        event_type: str,
        timestamp: str,
        participants: list[str] | None = None,
        cause: str = "",
        changes: list[object] | None = None,
        metadata: dict[str, Any] | None = None,
        simulation_tick: int | None = None,
        dialogue_payload: object | None = None,
    ) -> Event:
        event = Event(
            id=event_id,
            type=event_type,
            timestamp=timestamp,
            participants=deepcopy(participants or []),
            cause=cause,
            changes=deepcopy(changes or []),
            metadata=deepcopy(metadata or {}),
            simulation_tick=simulation_tick,
            dialogue_payload=deepcopy(dialogue_payload),
        )
        event._issue_source_receipt("system")
        return event
