"""Isolated registry for RuntimeAgent instances."""

from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import RLock
from typing import Iterator

from cognitive_world.agent.runtime_agent import RuntimeAgent


@dataclass
class AgentRegistry:
    """Store and retrieve RuntimeAgent snapshots by agent identifier."""

    _agents: dict[str, RuntimeAgent] = field(default_factory=dict, repr=False)
    _lock: RLock = field(default_factory=RLock, repr=False, compare=False)
    _revision: int = field(default=0, init=False, repr=False)

    def register(self, agent: RuntimeAgent) -> None:
        """Register an isolated copy of a RuntimeAgent by its ID."""
        if not isinstance(agent, RuntimeAgent):
            raise TypeError("agent must be a RuntimeAgent")
        with self._lock:
            self._agents[agent.agent_id] = deepcopy(agent)
            self._revision += 1

    def get(self, agent_id: str) -> RuntimeAgent | None:
        """Return an isolated copy of a registered Agent, if present."""
        with self._lock:
            agent = self._agents.get(agent_id)
            return deepcopy(agent) if agent is not None else None

    def remove(self, agent_id: str) -> RuntimeAgent | None:
        """Remove and return an isolated copy of a registered Agent."""
        with self._lock:
            agent = self._agents.pop(agent_id, None)
            if agent is not None:
                self._revision += 1
            return deepcopy(agent) if agent is not None else None

    def all_agents(self) -> tuple[RuntimeAgent, ...]:
        """Return isolated copies of all registered Agents."""
        with self._lock:
            return tuple(deepcopy(agent) for agent in self._agents.values())

    @contextmanager
    def snapshot_scope(self) -> Iterator[tuple[int, tuple[RuntimeAgent, ...]]]:
        """Hold membership stable while a caller validates a related snapshot.

        This registry lock is distinct from RuntimeWriteFence. Snapshot callers
        must hold both scopes; registry mutation itself is not a cognition or
        WorldState write and is not implicitly governed by that fence.
        """
        with self._lock:
            yield self._revision, tuple(
                deepcopy(agent) for agent in self._agents.values()
            )
