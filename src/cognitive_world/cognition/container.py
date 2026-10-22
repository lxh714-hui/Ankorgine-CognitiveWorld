"""Compatibility facade over the authoritative cognition stores."""

from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping
from cognitive_world.runtime.write_fence import RuntimeWriteFence

from cognitive_world.cognition.belief import Belief, BeliefStore
from cognitive_world.cognition.emotion import Emotion
from cognitive_world.cognition.goal import Goal, GoalStore
from cognitive_world.cognition.personality import Personality, PersonalityStore
from cognitive_world.cognition.self_model import SelfModel, SelfModelStore


@dataclass
class CognitionContainer:
    """Unify access to cognition stores without keeping duplicate records.

    The four long-lived cognition models are stored only in their dedicated
    stores. Legacy ``add_*`` and ``get_*`` methods delegate to those stores.
    Emotion remains container-owned because it has no dedicated store.
    """

    personality_store: PersonalityStore = field(default_factory=PersonalityStore)
    belief_store: BeliefStore = field(default_factory=BeliefStore)
    goal_store: GoalStore = field(default_factory=GoalStore)
    self_model_store: SelfModelStore = field(default_factory=SelfModelStore)
    _emotions: dict[str, Emotion] = field(default_factory=dict, repr=False)
    write_fence: RuntimeWriteFence | None = field(default=None, repr=False, compare=False)

    def bind_write_fence(self, fence: RuntimeWriteFence) -> None:
        if self.write_fence is not None and self.write_fence is not fence:
            raise ValueError("CognitionContainer is already bound to another runtime fence")
        self.write_fence = fence
        self.personality_store.bind_write_fence(fence)
        self.belief_store.bind_write_fence(fence)
        self.goal_store.bind_write_fence(fence)
        self.self_model_store.bind_write_fence(fence)

    @property
    def personalities(self) -> Mapping[str, Personality]:
        return MappingProxyType(
            {item.id: item for item in self.personality_store.get_all()}
        )

    @property
    def beliefs(self) -> Mapping[str, Belief]:
        return MappingProxyType({item.id: item for item in self.belief_store.get_all()})

    @property
    def goals(self) -> Mapping[str, Goal]:
        goals = self.goal_store.get_all()
        if len({item.id for item in goals}) != len(goals):
            raise ValueError("Goal IDs are shared by multiple owners; use owner-scoped access")
        return MappingProxyType({item.id: item for item in goals})

    @property
    def self_models(self) -> Mapping[str, SelfModel]:
        return MappingProxyType(
            {item.owner_id: item for item in self.self_model_store.get_all()}
        )

    @property
    def emotions(self) -> Mapping[str, Emotion]:
        return MappingProxyType(deepcopy(self._emotions))

    def add_personality(self, personality: Personality) -> None:
        """Register through the authoritative PersonalityStore."""
        self.personality_store.add(personality)

    def get_personality(self, object_id: str) -> Personality | None:
        """Read a Personality from the authoritative PersonalityStore."""
        return self.personality_store.get_by_id(object_id)

    def add_belief(self, belief: Belief) -> None:
        """Register through the authoritative BeliefStore."""
        self.belief_store.add(belief)

    def get_belief(self, object_id: str) -> Belief | None:
        """Read a Belief from the authoritative BeliefStore."""
        return self.belief_store.get_by_id(object_id)

    def add_goal(self, goal: Goal) -> None:
        """Register through the authoritative GoalStore."""
        self.goal_store.add(goal)

    def get_goal(self, object_id: str, *, owner_id: str | None = None) -> Goal | None:
        """Read a Goal from the authoritative GoalStore."""
        if owner_id is not None:
            return self.goal_store.get_owned(owner_id, object_id)
        return self.goal_store.get_by_id(object_id)

    def add_self_model(self, self_model: SelfModel) -> None:
        """Register through the authoritative SelfModelStore."""
        self.self_model_store.add(self_model)

    def get_self_model(self, owner_id: str) -> SelfModel | None:
        """Read an Agent SelfModel from the authoritative store."""
        return self.self_model_store.get(owner_id)

    def add_emotion(self, emotion: Emotion) -> None:
        """Register an initial Emotion state; replacements require governance."""
        from contextlib import nullcontext
        scope = nullcontext() if self.write_fence is None else self.write_fence.commit_scope()
        with scope:
            self._add_emotion(emotion)

    def _add_emotion(self, emotion: Emotion) -> None:
        if not isinstance(emotion, Emotion):
            raise TypeError("emotion must be an Emotion")
        if emotion.id in self._emotions:
            raise ValueError("Emotion already exists; use a validated update")
        self._emotions[emotion.id] = deepcopy(emotion)

    def apply_emotion_update(
        self, emotion: Emotion, proposal: Any, validation: Any, *, simulation_tick: int
    ) -> None:
        """Apply a validated proposal to the existing canonical Emotion owner."""
        from contextlib import nullcontext
        from cognitive_world.cognition.emotion_system import EmotionDecision, EmotionProposal
        from cognitive_world.cognition.proposal_origin import original_proposal_permit

        scope = nullcontext() if self.write_fence is None else self.write_fence.commit_scope()
        with scope:
            if self.write_fence is not None:
                self.write_fence.require_candidate_origin(
                    original_proposal_permit(proposal)
                )
            self._apply_emotion_update(
                emotion, proposal, validation, simulation_tick=simulation_tick
            )

    def _apply_emotion_update(
        self, emotion: Emotion, proposal: Any, validation: Any, *, simulation_tick: int
    ) -> None:
        from cognitive_world.cognition.emotion_system import EmotionDecision, EmotionProposal

        if not isinstance(emotion, Emotion) or not isinstance(proposal, EmotionProposal):
            raise TypeError("Emotion update requires an Emotion and EmotionProposal")
        if not isinstance(validation, EmotionDecision) or not validation.authorizes(proposal):
            raise PermissionError("Emotion updates require a matching validator result")
        if simulation_tick != proposal.simulation_tick:
            raise ValueError("validated Emotion update is stale for the current simulation tick")
        current = self._emotions.get(proposal.emotion_id)
        if current is None or current.owner_id != proposal.owner_id:
            raise PermissionError("Emotion target missing or owner mismatch")
        if current.snapshot_levels() != proposal.previous_levels or current.last_update_tick != proposal.previous_tick:
            raise ValueError("Emotion changed after proposal validation")
        if emotion.id != current.id or emotion.owner_id != current.owner_id:
            raise PermissionError("updated Emotion identity cannot change")
        if emotion.snapshot_levels() != proposal.proposed_levels or emotion.last_update_tick != proposal.simulation_tick:
            raise ValueError("updated Emotion does not match validated proposal")
        self._emotions[emotion.id] = deepcopy(emotion)

    def get_emotion(self, object_id: str) -> Emotion | None:
        emotion = self._emotions.get(object_id)
        return deepcopy(emotion) if emotion is not None else None
