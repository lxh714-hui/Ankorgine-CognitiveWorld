"""Initialized identity and cognition references for a runtime Agent."""

from copy import deepcopy
from typing import Any


class AgentContext:
    """Hold isolated initial-state references for an Agent entering simulation."""

    __slots__ = (
        "agent_id",
        "character_id",
        "personality_id",
        "_goal_ids",
        "_relationship_ids",
        "_memory_refs",
        "_belief_refs",
        "_emotion_state",
        "_metadata",
    )

    def __init__(
        self,
        agent_id: str,
        character_id: str | None = None,
        personality_id: str | None = None,
        goal_ids: list[str] | None = None,
        relationship_ids: list[str] | None = None,
        memory_refs: list[str] | None = None,
        belief_refs: list[str] | None = None,
        emotion_state: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.character_id = character_id
        self.personality_id = personality_id
        self._goal_ids = deepcopy(goal_ids if goal_ids is not None else [])
        self._relationship_ids = deepcopy(
            relationship_ids if relationship_ids is not None else []
        )
        self._memory_refs = deepcopy(memory_refs if memory_refs is not None else [])
        self._belief_refs = deepcopy(belief_refs if belief_refs is not None else [])
        self._emotion_state = deepcopy(emotion_state)
        self._metadata = deepcopy(metadata if metadata is not None else {})

    @property
    def goal_ids(self) -> list[str]:
        return self.get_goal_ids()

    @property
    def relationship_ids(self) -> list[str]:
        return self.get_relationship_ids()

    @property
    def memory_refs(self) -> list[str]:
        return self.get_memory_refs()

    @property
    def belief_refs(self) -> list[str]:
        return self.get_belief_refs()

    @property
    def emotion_state(self) -> Any:
        return self.get_emotion_state()

    @property
    def metadata(self) -> dict[str, Any]:
        return self.get_metadata()

    def get_identity(self) -> dict[str, str | None]:
        """Return an independent mapping of the initial identity references."""
        return {
            "agent_id": self.agent_id,
            "character_id": self.character_id,
            "personality_id": self.personality_id,
        }

    def get_goal_ids(self) -> list[str]:
        return deepcopy(self._goal_ids)

    def get_relationship_ids(self) -> list[str]:
        return deepcopy(self._relationship_ids)

    def get_memory_refs(self) -> list[str]:
        return deepcopy(self._memory_refs)

    def get_belief_refs(self) -> list[str]:
        return deepcopy(self._belief_refs)

    def get_emotion_state(self) -> Any:
        return deepcopy(self._emotion_state)

    def get_metadata(self) -> dict[str, Any]:
        return deepcopy(self._metadata)
