"""Dependency references for one simulation runtime instance."""

from dataclasses import dataclass
from enum import Enum

from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.history import EventHistory
from cognitive_world.runtime.agent_scheduler import AgentScheduler
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.scheduler import EventScheduler
from cognitive_world.observation.store import ObservationStore
from cognitive_world.safety.governance import UniversalSafetyGovernance


class PlayerMode(str, Enum):
    """Player presentation modes recognized by the trusted runtime binding."""

    ROLEPLAY = "roleplay"
    OBSERVER = "observer"
    DIRECTOR = "director"


@dataclass(frozen=True)
class PlayerSessionBinding:
    """Host-supplied identity and viewpoint binding for one runtime session.

    This contract does not authenticate a network user. The application host
    must populate it from its trusted session setup; absence means deny.
    """

    session_id: str
    player_id: str
    mode: PlayerMode
    controlled_agent_id: str | None = None
    observer_agent_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("session_id must be a non-empty string")
        if not isinstance(self.player_id, str) or not self.player_id:
            raise ValueError("player_id must be a non-empty string")
        if not isinstance(self.mode, PlayerMode):
            raise TypeError("mode must be a PlayerMode")
        for name in ("controlled_agent_id", "observer_agent_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{name} must be non-empty when provided")
        if self.mode is PlayerMode.ROLEPLAY and not self.controlled_agent_id:
            raise ValueError("roleplay mode requires a controlled_agent_id")
        if self.mode is PlayerMode.OBSERVER and not self.observer_agent_id:
            raise ValueError("observer mode requires an observer_agent_id")


@dataclass(init=False)
class RuntimeContext:
    """Hold references to a runtime's clock, world records, and schedulers."""

    clock: SimulationClock
    world_state: WorldState
    event_history: EventHistory
    event_scheduler: EventScheduler | None = None
    agent_scheduler: AgentScheduler | None = None
    agent_registry: AgentRegistry | None = None
    observation_store: ObservationStore | None = None
    player_session: PlayerSessionBinding | None = None
    safety_governance: UniversalSafetyGovernance

    def __init__(
        self,
        clock: SimulationClock,
        world_state: WorldState,
        event_history: EventHistory,
        scheduler: EventScheduler | None = None,
        event_scheduler: EventScheduler | None = None,
        agent_scheduler: AgentScheduler | None = None,
        agent_registry: AgentRegistry | None = None,
        observation_store: ObservationStore | None = None,
        player_session: PlayerSessionBinding | None = None,
        safety_governance: UniversalSafetyGovernance | None = None,
    ) -> None:
        if (
            scheduler is not None
            and event_scheduler is not None
            and scheduler is not event_scheduler
        ):
            raise ValueError("scheduler and event_scheduler must reference the same object")
        self.clock = clock
        self.world_state = world_state
        self.event_history = event_history
        self.event_scheduler = event_scheduler if event_scheduler is not None else scheduler
        self.agent_scheduler = agent_scheduler
        self.agent_registry = agent_registry
        self.observation_store = observation_store
        if player_session is not None and not isinstance(
            player_session, PlayerSessionBinding
        ):
            raise TypeError("player_session must be a PlayerSessionBinding or None")
        self.player_session = player_session
        if safety_governance is None:
            safety_governance = UniversalSafetyGovernance()
        if not isinstance(safety_governance, UniversalSafetyGovernance):
            raise TypeError("safety_governance must be UniversalSafetyGovernance")
        safety_governance.bind_runtime(world_state, clock)
        self.safety_governance = safety_governance

    @property
    def scheduler(self) -> EventScheduler | None:
        """Compatibility alias for the EventScheduler reference."""
        return self.event_scheduler

    @scheduler.setter
    def scheduler(self, value: EventScheduler | None) -> None:
        self.event_scheduler = value
