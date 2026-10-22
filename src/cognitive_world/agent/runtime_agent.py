"""Runtime-facing identity and goal references for an Agent instance."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from cognitive_world.agent.context import AgentContext


@dataclass(init=False)
class RuntimeAgent:
    """Represent an Agent participating in a simulation runtime."""

    agent_id: str
    character_id: str | None = None
    goal_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    _context: AgentContext = field(repr=False, compare=False)

    def __init__(
        self,
        agent_id: str,
        character_id: str | None = None,
        goal_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        context: AgentContext | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.character_id = character_id
        self.goal_ids = deepcopy(goal_ids if goal_ids is not None else [])
        self.metadata = deepcopy(metadata if metadata is not None else {})

        initial_context = context or AgentContext(
            agent_id=agent_id,
            character_id=character_id,
            goal_ids=self.goal_ids,
            metadata=self.metadata,
        )
        if not isinstance(initial_context, AgentContext):
            raise TypeError("context must be an AgentContext")
        if initial_context.agent_id != agent_id:
            raise ValueError("RuntimeAgent agent_id must match its AgentContext agent_id")
        if character_id is None and initial_context.character_id is not None:
            self.character_id = initial_context.character_id
        elif initial_context.character_id != character_id:
            raise ValueError(
                "RuntimeAgent character_id must match its AgentContext character_id"
            )
        self._context = deepcopy(initial_context)

    @property
    def context(self) -> AgentContext:
        """Return an isolated copy of the Agent's initialization context."""
        return self.get_context()

    def get_context(self) -> AgentContext:
        """Return an isolated copy of the Agent's initialization context."""
        if self._context.agent_id != self.agent_id:
            raise ValueError("RuntimeAgent agent_id no longer matches its AgentContext")
        if self._context.character_id != self.character_id:
            raise ValueError(
                "RuntimeAgent character_id no longer matches its AgentContext"
            )
        return deepcopy(self._context)

    def get_identity(self) -> dict[str, str | None]:
        """Return the Agent's basic identity as an independent mapping."""
        return {
            "agent_id": self.agent_id,
            "character_id": self.character_id,
        }

    def get_goals(self) -> list[str]:
        """Return an isolated copy of the associated Goal identifiers."""
        return deepcopy(self.goal_ids)
