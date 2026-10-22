"""Versioned historical visibility rules for durable L1 evidence.

Rules in this registry are trusted domain capabilities. Callers may select a
rule by source evidence, but cannot supply or replace a verifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable, Protocol

from cognitive_world.observation.observation import Observation


class HistoricalObservationRule(Protocol):
    """Trusted verifier contract for one versioned historical rule."""

    rule_id: str
    version: int
    source_event_type: str

    def supports_source(self, event: object, evidence: object) -> bool:
        """Select this verifier only when its durable-evidence preconditions hold."""

    def issue(self, event: object, evidence: object, owner_id: str,
              fact_id: str) -> Observation:
        """Reconstruct the historical Observation or fail closed."""


@dataclass(frozen=True)
class HistoricalRuleReference:
    rule_id: str
    version: int

    def __post_init__(self) -> None:
        if (not isinstance(self.rule_id, str) or not self.rule_id
                or "/" in self.rule_id or type(self.version) is not int
                or self.version < 1):
            raise ValueError("invalid historical rule identity")

    @property
    def wire_value(self) -> str:
        return f"{self.rule_id}/v{self.version}"

    @classmethod
    def from_wire_value(cls, value: str) -> "HistoricalRuleReference":
        if not isinstance(value, str) or "/v" not in value:
            raise PermissionError("unknown historical visibility rule")
        rule_id, version_text = value.rsplit("/v", 1)
        if not version_text.isascii() or not version_text.isdigit():
            raise PermissionError("unknown historical visibility rule version")
        try:
            reference = cls(rule_id, int(version_text))
        except ValueError as error:
            raise PermissionError("invalid historical visibility rule identity") from error
        if reference.wire_value != value:
            raise PermissionError("non-canonical historical visibility rule identity")
        return reference


@dataclass(frozen=True)
class _RoomLightOnColocatedSightV1:
    rule_id: str = "room-light-on-colocated-sight"
    version: int = 1
    source_event_type: str = "room_light_changed"

    @property
    def reference(self) -> HistoricalRuleReference:
        return HistoricalRuleReference(self.rule_id, self.version)

    def issue(self, event: object, evidence: object, owner_id: str,
              fact_id: str) -> Observation:
        if (event.type != self.source_event_type
                or not event.has_trusted_source("system")
                or not evidence.has_trusted_source(event)):
            raise PermissionError("source is not authorized by this historical rule")
        context = evidence.event_time_context
        observer = next((item for item in context.observer_positions
                         if item[0] == owner_id), None)
        fact = next((item for item in evidence.observable_facts
                     if item.fact_id == fact_id), None)
        conditions = dict(context.environment_conditions or ())
        if (context.simulation_time is None or context.fact_location_id is None
                or not context.environment_snapshot_complete
                or observer is None or observer[1] != context.fact_location_id
                or observer[2] is None or "sight" not in observer[2]
                or fact is None or not fact.has_trusted_source(event)
                or fact.fact_type != "environment_state"
                or fact.predicate != "room_light_on" or fact.value is not True
                or fact.location_id != context.fact_location_id
                or conditions.get(f"{context.fact_location_id}:light_on") is not True):
            raise PermissionError("historical visibility conditions are not proven")
        observation = Observation(
            f"observation:{event.id}:{owner_id}:{fact.fact_id}",
            owner_id, event.id, fact,
        )
        from cognitive_world.observation.observation import (
            _OBSERVATION_RECEIPT_SEAL, _ObservationProvenance,
        )
        fingerprint = sha256(repr((
            event._source_snapshot(), fact._snapshot(), context._snapshot(),
            owner_id, self.reference.wire_value,
        )).encode("utf-8")).hexdigest()
        object.__setattr__(observation, "_provenance", _ObservationProvenance(
            _OBSERVATION_RECEIPT_SEAL, observation._snapshot(), fingerprint,
        ))
        return observation

    def supports_source(self, event: object, evidence: object) -> bool:
        return (
            event.type == self.source_event_type
            and event.has_trusted_source("system")
            and evidence.has_trusted_source(event)
            and evidence.event_time_context.environment_snapshot_complete
        )


_ROOM_LIGHT_ON_COLOCATED_SIGHT_V1 = _RoomLightOnColocatedSightV1()


class HistoricalObservationRuleRegistry:
    """Explicit trusted configuration mapping versioned identities to verifiers."""

    def __init__(self, rules: Iterable[HistoricalObservationRule] | None = None) -> None:
        configured = (_ROOM_LIGHT_ON_COLOCATED_SIGHT_V1,) if rules is None else tuple(rules)
        by_identity: dict[tuple[str, int], HistoricalObservationRule] = {}
        by_event: dict[str, list[HistoricalObservationRule]] = {}
        for rule in configured:
            rule_id = getattr(rule, "rule_id", None)
            version = getattr(rule, "version", None)
            event_type = getattr(rule, "source_event_type", None)
            if (not isinstance(rule_id, str) or not rule_id or "/" in rule_id
                    or type(version) is not int or version < 1
                    or not isinstance(event_type, str) or not event_type
                    or not callable(getattr(rule, "supports_source", None))
                    or not callable(getattr(rule, "issue", None))):
                raise TypeError("historical rule does not satisfy the trusted verifier contract")
            identity = (rule_id, version)
            if identity in by_identity:
                raise ValueError("duplicate historical rule identity")
            by_identity[identity] = rule
            by_event.setdefault(event_type, []).append(rule)
        self._by_identity = by_identity
        self._by_event = {key: tuple(value) for key, value in by_event.items()}

    def by_reference(self, wire_value: str) -> HistoricalObservationRule:
        reference = HistoricalRuleReference.from_wire_value(wire_value)
        rule = self._by_identity.get((reference.rule_id, reference.version))
        if rule is None:
            raise PermissionError("unknown historical visibility rule")
        if (getattr(rule, "rule_id", None), getattr(rule, "version", None)) != (
            reference.rule_id, reference.version,
        ):
            raise PermissionError("registered historical rule identity changed")
        return rule

    def reference_for(self, rule: HistoricalObservationRule) -> str:
        reference = HistoricalRuleReference(
            getattr(rule, "rule_id", None), getattr(rule, "version", None),
        )
        if self.by_reference(reference.wire_value) is not rule:
            raise PermissionError("historical rule is not part of trusted configuration")
        return reference.wire_value

    def for_source(self, event: object, evidence: object) -> HistoricalObservationRule | None:
        if (not event.has_trusted_source("system")
                or not evidence.has_trusted_source(event)):
            return None
        candidates = tuple(
            rule for rule in self._by_event.get(getattr(event, "type", None), ())
            if rule.supports_source(event, evidence)
        )
        if len(candidates) > 1:
            raise PermissionError("historical source matches ambiguous registered rules")
        return self.by_reference(HistoricalRuleReference(
            candidates[0].rule_id, candidates[0].version,
        ).wire_value) if candidates else None


HISTORICAL_OBSERVATION_RULES = HistoricalObservationRuleRegistry()
