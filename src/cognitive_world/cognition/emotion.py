"""Emotion state and trusted, character-specific appraisal configuration.

These are cognition records, not world facts. Emotion remains owned by the
existing CognitionContainer and profiles are part of the existing Personality
record held by PersonalityStore.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import math
from typing import Any


def _unit(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite number in [0, 1]")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be a finite number in [0, 1]")
    return number


@dataclass(frozen=True)
class EmotionReaction:
    """A trusted initialization rule relating a typed fact to an appraisal.

    Exact fact matching avoids interpreting arbitrary Event text as an emotion
    command. Rules are open to any non-empty fact and emotion labels.
    """

    fact_type: str
    predicate: str
    expected_value: Any
    emotion: str
    appraisal_strength: float
    goal_id: str | None = None
    belief_id: str | None = None
    memory_id: str | None = None
    self_belief: str | None = None
    working_memory_percept_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("fact_type", "predicate", "emotion"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        values = self.expected_value if isinstance(self.expected_value, tuple) else (self.expected_value,)
        if any(
            value is not None
            and not isinstance(value, (str, int, bool, float))
            for value in values
        ) or any(isinstance(value, float) and not math.isfinite(value) for value in values):
            raise TypeError("expected_value must use the ObservableFact scalar contract")
        object.__setattr__(self, "expected_value", deepcopy(self.expected_value))
        object.__setattr__(
            self, "appraisal_strength", _unit(self.appraisal_strength, "appraisal_strength")
        )
        for name in ("goal_id", "belief_id", "memory_id", "self_belief", "working_memory_percept_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{name} must be non-empty when provided")


@dataclass(frozen=True)
class EmotionDimensionProfile:
    """Per-dimension parameters; recovery is measured per simulation tick."""

    sensitivity: float = 0.0
    activation_threshold: float = 1.0
    growth_rate: float = 0.0
    recovery_per_tick: float = 0.0
    regulation: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "sensitivity", "activation_threshold", "growth_rate",
            "recovery_per_tick", "regulation",
        ):
            object.__setattr__(self, name, _unit(getattr(self, name), name))


@dataclass(frozen=True)
class EmotionProfile:
    """Explicit individual parameters, supplied by trusted character setup.

    Missing dimensions are neutral: no event activation and no decay is
    inferred. The default therefore creates no fabricated personality signal.
    ``suppression`` maps a receiving emotion to source-emotion suppression
    factors and is deliberately sparse and opt-in.
    """

    owner_id: str
    dimensions: tuple[tuple[str, EmotionDimensionProfile], ...] = ()
    reactions: tuple[EmotionReaction, ...] = ()
    suppression: tuple[tuple[str, str, float], ...] = ()
    impulse_ceiling: float = 0.0
    risk_bias_limit: float = 0.0
    attention_bias_limit: float = 0.0
    goal_drive_weights: tuple[tuple[str, float], ...] = ()
    goal_conflicts: tuple[tuple[str, str], ...] = ()
    impulse_affinity: tuple[tuple[str, float], ...] = ()
    risk_affinity: tuple[tuple[str, float], ...] = ()
    attention_affinity: tuple[tuple[str, str, float], ...] = ()
    review_affinity: tuple[tuple[str, float], ...] = ()
    goal_emotion_weights: tuple[tuple[str, str, float], ...] = ()
    goal_capability_requirements: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.owner_id, str) or not self.owner_id:
            raise ValueError("EmotionProfile owner_id must be non-empty")
        for name in (
            "dimensions", "reactions", "suppression", "goal_drive_weights",
            "goal_conflicts", "impulse_affinity", "risk_affinity",
            "attention_affinity", "review_affinity", "goal_emotion_weights",
            "goal_capability_requirements",
        ):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"{name} must be an immutable tuple")
        names: set[str] = set()
        for emotion, profile in self.dimensions:
            if not isinstance(emotion, str) or not emotion or not isinstance(profile, EmotionDimensionProfile):
                raise TypeError("dimensions must contain (emotion, EmotionDimensionProfile)")
            if emotion in names:
                raise ValueError("emotion dimensions must be unique")
            names.add(emotion)
        if any(not isinstance(rule, EmotionReaction) for rule in self.reactions):
            raise TypeError("reactions must contain EmotionReaction records")
        for name in ("impulse_ceiling", "risk_bias_limit", "attention_bias_limit"):
            object.__setattr__(self, name, _unit(getattr(self, name), name))
        for target, source, factor in self.suppression:
            if not target or not source:
                raise ValueError("suppression emotion labels must be non-empty")
            _unit(factor, "suppression factor")
        for goal_id, weight in self.goal_drive_weights:
            if not isinstance(goal_id, str) or not goal_id:
                raise ValueError("goal drive keys must be non-empty Goal IDs")
            # This is a bounded multiplier on persistent Goal.priority, not a
            # normalized share. 1.0 is neutral; 0.0 suppresses that goal's
            # base drive and 2.0 is the maximum configured amplification.
            if isinstance(weight, bool) or not isinstance(weight, (int, float)):
                raise TypeError("goal drive multiplier must be numeric")
            number = float(weight)
            if not math.isfinite(number) or not 0.0 <= number <= 2.0:
                raise ValueError("goal drive multiplier must be finite and in [0, 2]")
        for left, right in self.goal_conflicts:
            if not left or not right or left == right:
                raise ValueError("goal conflicts require two distinct Goal IDs")
        for name in ("impulse_affinity", "risk_affinity", "review_affinity"):
            for emotion, value in getattr(self, name):
                if not emotion:
                    raise ValueError(f"{name} emotion labels must be non-empty")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not -1.0 <= value <= 1.0:
                    raise ValueError(f"{name} values must be finite and in [-1, 1]")
        for emotion, focus, value in self.attention_affinity:
            if not emotion or not focus:
                raise ValueError("attention affinity labels must be non-empty")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not -1.0 <= value <= 1.0:
                raise ValueError("attention affinity values must be finite and in [-1, 1]")
        for goal_id, emotion, value in self.goal_emotion_weights:
            if not goal_id or not emotion:
                raise ValueError("goal emotion weight keys must be non-empty")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not -1.0 <= value <= 1.0:
                raise ValueError("goal emotion weights must be finite and in [-1, 1]")
        for goal_id, capability in self.goal_capability_requirements:
            if not goal_id or not capability:
                raise ValueError("goal capability requirements must be non-empty")

    def dimension(self, emotion: str) -> EmotionDimensionProfile | None:
        return next((value for key, value in self.dimensions if key == emotion), None)

    def drive_weight(self, goal_id: str) -> float:
        return next((value for key, value in self.goal_drive_weights if key == goal_id), 1.0)


@dataclass(init=False)
class Emotion:
    """Current dynamic multi-emotion state; ``state`` is legacy-compatible.

    Old records with a single ``state`` and ``intensity`` migrate in-memory to
    one entry in ``levels``. No old state is discarded.
    """

    id: str
    owner_id: str
    state: str
    intensity: float
    metadata: dict[str, Any]
    levels: dict[str, float]
    last_update_tick: int | None
    processed_sources: tuple[str, ...]

    def __init__(
        self,
        id: str,
        owner_id: str,
        state: str = "",
        intensity: float = 0.0,
        metadata: dict[str, Any] | None = None,
        *,
        levels: dict[str, float] | None = None,
        last_update_tick: int | None = None,
        processed_sources: tuple[str, ...] = (),
    ) -> None:
        if not isinstance(id, str) or not id or not isinstance(owner_id, str) or not owner_id:
            raise ValueError("Emotion id and owner_id must be non-empty")
        migrated = {} if levels is None else dict(levels)
        if levels is None and state:
            migrated[state] = intensity
        for emotion, value in migrated.items():
            if not isinstance(emotion, str) or not emotion:
                raise ValueError("emotion labels must be non-empty strings")
            migrated[emotion] = _unit(value, f"intensity for {emotion}")
        if last_update_tick is not None and (
            isinstance(last_update_tick, bool) or not isinstance(last_update_tick, int) or last_update_tick < 0
        ):
            raise ValueError("last_update_tick must be a non-negative integer or None")
        if not isinstance(processed_sources, tuple) or any(not isinstance(x, str) or not x for x in processed_sources):
            raise TypeError("processed_sources must be a tuple of non-empty strings")
        self.id = id
        self.owner_id = owner_id
        self.levels = migrated
        if levels is not None and migrated:
            self.state = max(migrated, key=lambda label: (migrated[label], label))
        else:
            self.state = state or "neutral"
        self.intensity = migrated.get(self.state, 0.0)
        self.metadata = deepcopy(metadata or {})
        self.last_update_tick = last_update_tick
        self.processed_sources = tuple(dict.fromkeys(processed_sources))

    def snapshot_levels(self) -> tuple[tuple[str, float], ...]:
        return tuple(sorted(self.levels.items()))


# Semantic name for new APIs; it is the same canonical class, not a second
# model or Store. ``Emotion`` remains the compatibility import.
EmotionState = Emotion
