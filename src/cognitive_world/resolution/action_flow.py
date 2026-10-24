"""Orchestrate the Attempt resolution and Event creation boundaries."""

from dataclasses import dataclass, field

from cognitive_world.core.event import Event
from cognitive_world.decision.attempt import Attempt
from cognitive_world.event.factory import EventFactory
from cognitive_world.resolution.engine import ResolutionEngine
from cognitive_world.resolution.result import ResolutionResult
from cognitive_world.core.world_state import WorldState
from cognitive_world.runtime.clock import SimulationTime
from cognitive_world.event.history import EventHistory
from cognitive_world.safety.governance import SafetyInput, UniversalSafetyGovernance


@dataclass
class ActionResolutionFlow:
    """Connect a ResolutionEngine result to EventFactory creation."""

    resolution_engine: ResolutionEngine = field(default_factory=ResolutionEngine)
    event_factory: EventFactory = field(default_factory=EventFactory)
    action_expectations: object | None = field(default=None, repr=False, kw_only=True)
    expectation_origin: str = field(default="npc", kw_only=True)
    world_state: WorldState | None = None
    event_history: EventHistory | None = None
    safety_governance: UniversalSafetyGovernance = field(default_factory=UniversalSafetyGovernance)

    def __post_init__(self) -> None:
        if not isinstance(self.safety_governance, UniversalSafetyGovernance):
            raise TypeError("ActionResolutionFlow requires UniversalSafetyGovernance")
        if self.world_state is not None:
            self.safety_governance.bind_world_state(self.world_state)
        self.event_factory.bind_safety_governance(self.safety_governance)
        self._bind_resolution_safety(self.safety_governance)

    def bind_safety_governance(self, governance: UniversalSafetyGovernance) -> None:
        if not isinstance(governance, UniversalSafetyGovernance):
            raise TypeError("governance must be UniversalSafetyGovernance")
        self.safety_governance = governance
        if self.world_state is not None:
            governance.bind_world_state(self.world_state)
        self.event_factory.bind_safety_governance(governance)
        self._bind_resolution_safety(governance)

    def _bind_resolution_safety(self, governance: UniversalSafetyGovernance) -> None:
        from cognitive_world.resolution.causal import MethodBasedResolutionEngine

        if isinstance(self.resolution_engine, MethodBasedResolutionEngine):
            self.resolution_engine.bind_safety_governance(governance)

    def supported_attempt_methods(self, mechanism_kind: str) -> tuple[str, ...]:
        """Return canonical method text offered by this flow's installed rule adapter."""
        provider = getattr(self.resolution_engine, "supported_attempt_methods", None)
        if not callable(provider):
            return ()
        values = provider(mechanism_kind)
        return tuple(value for value in values if isinstance(value, str) and value)

    def execute(
        self, attempt: Attempt, *, action_proposal_id: str | None = None,
        simulation_tick: SimulationTime | None = None,
    ) -> Event:
        """Resolve an Attempt and return the Event created from its result."""
        if not isinstance(attempt, Attempt):
            raise TypeError("attempt must be an Attempt")
        resolution_result, event = self.execute_with_result(
            attempt,
            action_proposal_id=action_proposal_id,
            simulation_tick=simulation_tick,
        )
        if event is None:
            raise ValueError("ResolutionEngine did not issue a valid confirmation for this Attempt (unresolved)")
        return event

    def execute_with_result(
        self, attempt: Attempt, *, action_proposal: object | None = None, action_proposal_id: str | None = None,
        simulation_tick: SimulationTime | None = None,
    ) -> tuple[ResolutionResult, Event | None]:
        """Return the controlled result and an Event only when it is confirmed."""
        if not isinstance(attempt, Attempt):
            raise TypeError("attempt must be an Attempt")
        params = attempt.parameters
        raw_steps = params.get("steps", ())
        steps = tuple(
            step if isinstance(step, str) else str(step.get("method", ""))
            for step in raw_steps
        ) if isinstance(raw_steps, (tuple, list)) else ()
        method = params.get("method", "")
        norms = None if self.world_state is None else self.world_state.world_norms
        world_id = norms.world_id if norms is not None else "unknown"
        self.safety_governance.require_action_allowed(SafetyInput(
            actor_id=attempt.agent_id,
            source="action_attempt",
            intent=attempt.action_type,
            target_refs=tuple(attempt.target_refs),
            method=method if isinstance(method, str) else "",
            context=f"world:{world_id}; submitted preconditions (untrusted): " + " ".join(str(value) for value in params.get("preconditions", ()) if isinstance(value, str)),
            ordered_steps=steps,
        ))
        if self.world_state is not None and hasattr(self.resolution_engine, "world_state"):
            setattr(self.resolution_engine, "world_state", self.world_state)
        if self.event_history is not None and hasattr(self.resolution_engine, "event_history"):
            setattr(self.resolution_engine, "event_history", self.event_history)
        if hasattr(self.resolution_engine, "simulation_time"):
            setattr(self.resolution_engine, "simulation_time", None)
        if simulation_tick is not None:
            if not isinstance(simulation_tick, SimulationTime) or not simulation_tick.is_clock_issued():
                raise PermissionError("Resolution time must come from SimulationClock")
            if hasattr(self.resolution_engine, "simulation_time"):
                setattr(self.resolution_engine, "simulation_time", simulation_tick)

        expectation = None
        if self.action_expectations is not None:
            if action_proposal_id is not None and action_proposal_id != attempt.action_proposal_id:
                raise PermissionError("B3 proposal/Attempt source mismatch")
            action_proposal_id = attempt.action_proposal_id
            expectation = self.action_expectations.freeze(attempt, action_proposal, origin=self.expectation_origin)
            self.action_expectations.begin_resolution(expectation)
        resolution_result = self.resolution_engine.resolve(attempt)
        if not isinstance(resolution_result, ResolutionResult):
            raise TypeError(
                "ResolutionEngine.resolve must return a ResolutionResult"
            )
        if not resolution_result._has_valid_confirmation(attempt):
            if resolution_result.confirmed is False and resolution_result.outcome == "unresolved":
                return resolution_result, None
            raise ValueError("ResolutionEngine did not issue a valid confirmation for this Attempt")
        options = {} if expectation is None else {"action_expectation_id": expectation.record_id}
        event = self.event_factory.create_from_resolution(
            resolution_result, action_proposal_id=action_proposal_id, **options
        )
        if not isinstance(event, Event) or not event.has_trusted_source("resolution"):
            raise ValueError("EventFactory did not return an intact Resolution-sourced Event")
        return resolution_result, event
