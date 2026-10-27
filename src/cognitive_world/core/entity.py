"""Core entity data model."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SafetySubjectProfile:
    """Explicit safety-relevant identity facts loaded as part of a world Entity.

    ``None`` means unknown. This record is not inferred from presentation,
    names, prose, or the generic ``attributes`` mapping.
    """

    age_years: int | None = None
    profile_revision: int = 0

    def __post_init__(self) -> None:
        if self.age_years is not None and (
            isinstance(self.age_years, bool)
            or not isinstance(self.age_years, int)
            or not 0 <= self.age_years <= 150
        ):
            raise ValueError("age_years must be a known age in [0, 150] or None")
        if (
            isinstance(self.profile_revision, bool)
            or not isinstance(self.profile_revision, int)
            or self.profile_revision < 0
        ):
            raise ValueError("profile_revision must be a non-negative integer")


@dataclass
class Entity:
    """A generic entity defined by the data contract."""

    id: str
    type: str
    attributes: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    # Physical capabilities belong to the world entity, not its cognition.
    # None means unknown and therefore cannot satisfy perception rules.
    sensory_capabilities: tuple[str, ...] | None = None
    physical_capabilities: tuple[str, ...] | None = None
    owner_id: str | None = None
    safety_profile: SafetySubjectProfile | None = None

    def __post_init__(self) -> None:
        from cognitive_world.core.physical import PhysicalStateSet,PhysicalTransitionRule
        if "physical" in self.state:
            physical=self.state["physical"]
            if type(physical) is not PhysicalStateSet or physical.entity_id!=self.id:
                raise ValueError("invalid physical state identity/type")
            physical.__post_init__()
        if "physical_rules" in self.attributes:
            rules=self.attributes["physical_rules"]
            if type(rules) is not tuple or any(type(r) is not PhysicalTransitionRule for r in rules):
                raise ValueError("typed physical rules required")
            for rule in rules:rule.__post_init__()
        if self.sensory_capabilities is not None:
            if not isinstance(self.sensory_capabilities, tuple) or any(
                not isinstance(item, str) or not item for item in self.sensory_capabilities
            ):
                raise TypeError(
                    "sensory_capabilities must be an immutable tuple of "
                    "non-empty strings or None"
                )
        if self.physical_capabilities is not None:
            if not isinstance(self.physical_capabilities, tuple) or any(
                not isinstance(item, str) or not item for item in self.physical_capabilities
            ):
                raise TypeError(
                    "physical_capabilities must be an immutable tuple of "
                    "non-empty strings or None"
                )
        if self.owner_id is not None and (not isinstance(self.owner_id, str) or not self.owner_id):
            raise ValueError("owner_id must be non-empty when provided")
        if self.safety_profile is not None and not isinstance(
            self.safety_profile, SafetySubjectProfile
        ):
            raise TypeError("safety_profile must be a SafetySubjectProfile or None")
