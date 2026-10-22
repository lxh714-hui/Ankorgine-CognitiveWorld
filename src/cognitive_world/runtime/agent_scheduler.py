"""Time-based scheduling of Agent turns."""

from dataclasses import dataclass, field


@dataclass
class AgentScheduler:
    """Queue Agent identifiers until their scheduled turn time is due."""

    _scheduled_agents: list[tuple[int, str]] = field(default_factory=list, repr=False)

    def schedule_agent(self, agent_id: str, execute_time: int) -> None:
        """Schedule an Agent identifier for a simulation time."""
        if not isinstance(agent_id, str):
            raise TypeError("agent_id must be a string")
        self._scheduled_agents.append((execute_time, agent_id))

    def get_due_agents(self, current_time: int) -> tuple[str, ...]:
        """Remove and return Agent identifiers due by ``current_time``."""
        due = sorted(
            (
                scheduled
                for scheduled in self._scheduled_agents
                if scheduled[0] <= current_time
            ),
            key=lambda scheduled: scheduled[0],
        )
        self._scheduled_agents = [
            scheduled
            for scheduled in self._scheduled_agents
            if scheduled[0] > current_time
        ]
        return tuple(agent_id for _, agent_id in due)
