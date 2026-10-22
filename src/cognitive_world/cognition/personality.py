"""Stable Personality data and owner-isolated storage."""

from copy import deepcopy
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any
from cognitive_world.runtime.write_fence import RuntimeWriteFence

from cognitive_world.cognition.emotion import EmotionProfile


@dataclass(init=False)
class Personality:
    """Describe an Agent's relatively stable long-term tendencies."""

    owner_id: str
    traits: dict[str, Any]
    preferences: dict[str, Any]
    values: dict[str, Any]
    metadata: dict[str, Any]
    emotion_profile: EmotionProfile | None

    def __init__(
        self,
        owner_id: str | None = None,
        traits: dict[str, Any] | None = None,
        preferences: dict[str, Any] | None = None,
        values: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        *,
        id: str | None = None,
        emotion_profile: EmotionProfile | None = None,
    ) -> None:
        """Initialize a Personality, accepting legacy ``id`` as owner alias."""
        self.owner_id = owner_id if owner_id is not None else (id or "")
        self.traits = deepcopy(traits if traits is not None else {})
        self.preferences = deepcopy(preferences if preferences is not None else {})
        self.values = deepcopy(values if values is not None else {})
        self.metadata = deepcopy(metadata if metadata is not None else {})
        if emotion_profile is not None and not isinstance(emotion_profile, EmotionProfile):
            raise TypeError("emotion_profile must be an EmotionProfile or None")
        if emotion_profile is not None and emotion_profile.owner_id != self.owner_id:
            raise PermissionError("EmotionProfile owner must match Personality owner")
        self.emotion_profile = deepcopy(emotion_profile)

    @property
    def id(self) -> str:
        """Compatibility alias used by existing cognition references."""
        return self.owner_id


@dataclass
class PersonalityStore:
    """Store one isolated Personality snapshot per Agent owner."""

    _personalities: dict[str, Personality] = field(default_factory=dict, repr=False)
    write_fence: RuntimeWriteFence | None = field(default=None, repr=False, compare=False)

    def bind_write_fence(self, fence: RuntimeWriteFence) -> None:
        if self.write_fence is not None and self.write_fence is not fence:
            raise ValueError("PersonalityStore is already bound to another runtime fence")
        self.write_fence = fence

    def add(self, personality: Personality) -> None:
        """Register initial Personality config; profile replacement is governed."""
        scope = nullcontext() if self.write_fence is None else self.write_fence.commit_scope()
        with scope:
            self._add(personality)

    def _add(self, personality: Personality) -> None:
        if not isinstance(personality, Personality):
            raise TypeError("personality must be a Personality")
        current = self._personalities.get(personality.owner_id)
        if current is not None:
            if current.emotion_profile != personality.emotion_profile:
                raise PermissionError("EmotionProfile is immutable after trusted initialization")
            raise ValueError("Personality already exists; use update")
        self._personalities[personality.owner_id] = deepcopy(personality)

    def get(self, owner_id: str) -> Personality | None:
        """Return an isolated Personality copy for an Agent, if present."""
        personality = self._personalities.get(owner_id)
        return deepcopy(personality) if personality is not None else None

    def get_by_id(self, personality_id: str) -> Personality | None:
        """Return a Personality copy by its legacy ID/owner key."""
        return self.get(personality_id)

    def get_all(self) -> tuple[Personality, ...]:
        """Return isolated copies of all stored Personality records."""
        return tuple(deepcopy(tuple(self._personalities.values())))

    def update(self, personality: Personality) -> None:
        """Replace the stored Personality snapshot for its owner."""
        if self.write_fence is not None:
            raise PermissionError(
                "Personality has no governed runtime evolution contract"
            )
        if not isinstance(personality, Personality):
            raise TypeError("personality must be a Personality")
        current = self._personalities.get(personality.owner_id)
        if current is not None and current.emotion_profile != personality.emotion_profile:
            raise PermissionError("EmotionProfile changes require a future governed growth proposal")
        self._personalities[personality.owner_id] = deepcopy(personality)
