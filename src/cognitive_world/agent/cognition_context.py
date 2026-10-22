"""Read-only access context for a Character's cognition records."""

from dataclasses import dataclass, field
from typing import Any

from cognitive_world.agent.character import Character
from cognitive_world.cognition.belief import Belief
from cognitive_world.cognition.container import CognitionContainer
from cognitive_world.cognition.emotion import Emotion
from cognitive_world.cognition.goal import Goal
from cognitive_world.cognition.memory import Memory
from cognitive_world.cognition.memory_retrieval import (
    MAX_MEMORY_QUERY_RESULTS,
    MemoryQuery,
    MemoryRetriever,
    MemorySnapshot,
)
from cognitive_world.cognition.memory_semantic_retrieval import HybridMemoryRetriever
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.cognition.metacognition import MetacognitiveFeedback
from cognitive_world.cognition.personality import Personality
from cognitive_world.cognition.self_model import SelfModel
from cognitive_world.observation.observation import Observation
from cognitive_world.observation.store import ObservationStore
from cognitive_world.runtime.write_fence import RuntimeWriteFence


@dataclass
class CognitionContext:
    """Connect a Character's cognition references to read-only containers."""

    character_id: str
    owner_id: str
    cognition_container: CognitionContainer
    memory_store: MemoryStore
    metadata: dict[str, Any] = field(default_factory=dict)
    memory_retriever: MemoryRetriever | HybridMemoryRetriever | None = field(
        default=None, repr=False,
    )
    _personality_id: str | None = field(default=None, repr=False)
    _belief_ids: tuple[str, ...] = field(default_factory=tuple, repr=False)
    _emotion_id: str | None = field(default=None, repr=False)
    _memory_ids: tuple[str, ...] = field(default_factory=tuple, repr=False)
    _goal_ids: tuple[str, ...] = field(default_factory=tuple, repr=False)
    observation_store: ObservationStore | None = field(default=None, repr=False)
    metacognitive_feedback: MetacognitiveFeedback | None = field(
        default=None, repr=False
    )

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"character_id", "owner_id", "_memory_ids"} and hasattr(self, name):
            raise AttributeError(f"{name} is immutable after CognitionContext creation")
        object.__setattr__(self, name, value)

    def bind_write_fence(self, fence: RuntimeWriteFence) -> None:
        """Bind canonical cognition/memory writers to this runtime session."""
        self.memory_store.bind_write_fence(fence)
        self.cognition_container.bind_write_fence(fence)

    @classmethod
    def from_character(
        cls,
        character: Character,
        cognition_container: CognitionContainer,
        memory_store: MemoryStore,
        metadata: dict[str, Any] | None = None,
        memory_retriever: MemoryRetriever | HybridMemoryRetriever | None = None,
        observation_store: ObservationStore | None = None,
        metacognitive_feedback: MetacognitiveFeedback | None = None,
    ) -> "CognitionContext":
        """Create a context using references declared by a Character."""
        if not isinstance(character, Character):
            raise TypeError("character must be a Character")
        if not isinstance(character.agent_id, str) or not character.agent_id:
            raise ValueError("Character agent_id must be non-empty")
        if any(not isinstance(memory_id, str) or not memory_id for memory_id in character.memory_ids):
            raise ValueError("Character memory_ids must contain non-empty IDs")
        return cls(
            character_id=character.id,
            owner_id=character.agent_id,
            cognition_container=cognition_container,
            memory_store=memory_store,
            metadata={} if metadata is None else metadata,
            memory_retriever=memory_retriever,
            observation_store=observation_store,
            metacognitive_feedback=metacognitive_feedback,
            _personality_id=character.personality_id,
            _belief_ids=tuple(character.belief_ids),
            _emotion_id=character.emotion_id or None,
            _memory_ids=tuple(character.memory_ids),
            _goal_ids=tuple(character.goal_ids),
        )

    def get_personality(self) -> Personality | None:
        if self._personality_id is None:
            return None
        personality = self.cognition_container.get_personality(self._personality_id)
        if personality is None or personality.owner_id != self.owner_id:
            return None
        return personality

    def get_beliefs(self) -> tuple[Belief, ...]:
        return tuple(
            belief
            for belief_id in self._belief_ids
            if (belief := self.cognition_container.get_belief(belief_id)) is not None
            and belief.owner_id == self.owner_id
        )

    def get_goals(self) -> tuple[Goal, ...]:
        return tuple(
            goal
            for goal_id in self._goal_ids
            if (goal := self.cognition_container.goal_store.get_owned(
                self.owner_id, goal_id
            )) is not None
        )

    def get_emotion(self) -> Emotion | None:
        if self._emotion_id is None:
            return None
        emotion = self.cognition_container.get_emotion(self._emotion_id)
        if emotion is None or emotion.owner_id != self.owner_id:
            return None
        return emotion

    def get_self_model(self) -> SelfModel | None:
        """Read the Agent's SelfModel from the shared cognition authority."""
        return self.cognition_container.get_self_model(self.owner_id)

    def get_memories(self) -> tuple[Memory, ...]:
        return tuple(
            memory
            for memory_id in self._memory_ids
            if (memory := self.memory_store.get_memory(memory_id)) is not None
            and memory.owner_id == self.owner_id
            and MemoryStore.is_semantically_retrievable(memory)
        )

    def get_relevant_memories(self, query: MemoryQuery) -> tuple[MemorySnapshot, ...]:
        """Retrieve Character-linked memories as immutable owner snapshots."""
        if query.owner_id != self.owner_id:
            raise ValueError("MemoryQuery owner_id does not match CognitionContext")
        retriever = self.memory_retriever or MemoryRetriever(self.memory_store)
        allowed_ids = tuple(dict.fromkeys(self._memory_ids))
        authorized: list[MemorySnapshot] = []
        seen_ids: set[str] = set()
        for memory in retriever.retrieve(query, allowed_memory_ids=allowed_ids):
            if len(authorized) >= min(query.limit, MAX_MEMORY_QUERY_RESULTS):
                break
            # Re-read the canonical record and recheck both Character linkage
            # and owner. A replaceable strategy can rank, but cannot authorize.
            if getattr(memory, "id", None) not in allowed_ids:
                continue
            if memory.id in seen_ids:
                continue
            canonical = self.memory_store.get_memory(memory.id)
            if (canonical is None or canonical.owner_id != self.owner_id
                    or not MemoryStore.is_semantically_retrievable(canonical)):
                continue
            if not isinstance(canonical.source_event, str) or not canonical.source_event:
                continue
            authorized.append(MemorySnapshot.from_memory(canonical))
            seen_ids.add(memory.id)
        return tuple(authorized)

    def get_observations(self) -> tuple[Observation, ...]:
        """Return isolated observations belonging to this Character's Agent."""
        if self.observation_store is None:
            return ()
        return self.observation_store.get_by_observer(self.owner_id)

    def get_metacognitive_feedback(self) -> MetacognitiveFeedback | None:
        """Return only the turn-local feedback addressed to this owner."""
        feedback = self.metacognitive_feedback
        if feedback is None:
            return None
        if feedback.owner_id != self.owner_id:
            raise PermissionError("metacognitive feedback belongs to another Agent")
        return feedback
