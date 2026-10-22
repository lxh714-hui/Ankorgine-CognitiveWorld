"""Immutable, versioned world norms and a CWUI-safe public projection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from cognitive_world.safety.governance import (
    SafetyDisposition,
    SafetyInput,
    UniversalSafetyGovernance,
)


class GovernanceStatus(str, Enum):
    FORMAL_LAW = "formal_law"
    CUSTOMARY_GOVERNANCE = "customary_governance"
    MIXED = "mixed"
    NO_FORMAL_LAW = "no_formal_law"


class NormativeForce(str, Enum):
    PROHIBIT = "prohibit"
    REQUIRE = "require"
    PERMIT = "permit"
    REGULATE = "regulate"
    CUSTOMARY_EXPECTATION = "customary_expectation"


@dataclass(frozen=True)
class NormRule:
    rule_id: str
    title: str
    summary: str
    detail: str
    jurisdiction_ids: tuple[str, ...] = ()
    status: str = "active"
    is_public: bool = True
    children: tuple["NormRule", ...] = ()
    conduct_scope: str = ""
    normative_force: NormativeForce = NormativeForce.REGULATE

    def __post_init__(self) -> None:
        for name in ("rule_id", "title", "summary", "detail"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > 8_000:
                raise ValueError(f"{name} must be bounded non-empty text")
        if self.status not in {"active", "repealed", "suspended", "draft"}:
            raise ValueError("unsupported norm status")
        if type(self.is_public) is not bool:
            raise TypeError("is_public must be bool")
        if not isinstance(self.normative_force, NormativeForce):
            raise TypeError("normative_force must use a supported rule modality")
        if not isinstance(self.jurisdiction_ids, tuple) or not isinstance(self.children, tuple):
            raise TypeError("norm rule collections must be immutable tuples")
        if not isinstance(self.conduct_scope, str) or len(self.conduct_scope) > 2_000:
            raise ValueError("conduct_scope must be bounded text")
        if len(self.jurisdiction_ids) > 64 or any(not isinstance(x, str) or not x for x in self.jurisdiction_ids):
            raise ValueError("jurisdiction_ids are invalid")
        if len(self.children) > 64 or any(not isinstance(child, NormRule) for child in self.children):
            raise ValueError("children must be bounded NormRule records")


@dataclass(frozen=True)
class NormVersion:
    version_id: str
    effective_from_tick: int
    effective_until_tick: int | None
    legal_rules: tuple[NormRule, ...] = ()
    social_norms: tuple[NormRule, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.version_id, str) or not self.version_id:
            raise ValueError("version_id must be non-empty")
        if isinstance(self.effective_from_tick, bool) or not isinstance(self.effective_from_tick, int) or self.effective_from_tick < 0:
            raise ValueError("effective_from_tick must be non-negative")
        if self.effective_until_tick is not None and (
            isinstance(self.effective_until_tick, bool)
            or not isinstance(self.effective_until_tick, int)
            or self.effective_until_tick <= self.effective_from_tick
        ):
            raise ValueError("effective_until_tick must follow the start tick")
        if not isinstance(self.legal_rules, tuple) or not isinstance(self.social_norms, tuple):
            raise TypeError("version rules must be immutable tuples")
        if any(not isinstance(rule, NormRule) for rule in (*self.legal_rules, *self.social_norms)):
            raise TypeError("norm versions contain only NormRule records")
        if len(self.legal_rules) > 512 or len(self.social_norms) > 512:
            raise ValueError("norm version exceeds rule count bound")


@dataclass(frozen=True)
class WorldNorms:
    world_id: str
    governance_status: GovernanceStatus
    lawmaking_authority: str | None
    jurisdictions: tuple[tuple[str, str], ...]
    responsibility_and_process: str
    enforcement_or_governance_bodies: tuple[str, ...]
    law_morality_distinction: str
    versions: tuple[NormVersion, ...]
    active_version_id: str
    player_notice: str
    content_hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.world_id, str) or not self.world_id:
            raise ValueError("world_id is required")
        if not isinstance(self.governance_status, GovernanceStatus):
            raise TypeError("governance_status must be explicit")
        for name in ("jurisdictions", "enforcement_or_governance_bodies", "versions", "content_hints"):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"{name} must be an immutable tuple")
        for name in ("responsibility_and_process", "law_morality_distinction", "player_notice"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > 8_000:
                raise ValueError(f"{name} must be bounded non-empty text")
        if self.lawmaking_authority is not None and (not isinstance(self.lawmaking_authority, str) or len(self.lawmaking_authority) > 2_000):
            raise ValueError("lawmaking_authority is invalid")
        if len(self.versions) > 128 or not self.versions or any(not isinstance(v, NormVersion) for v in self.versions):
            raise ValueError("WorldNorms requires a bounded version history")
        ids = [version.version_id for version in self.versions]
        if len(set(ids)) != len(ids) or self.active_version_id not in ids or ids[-1] != self.active_version_id:
            raise ValueError("versions must be unique and include active_version_id")
        last_end = -1
        for index, version in enumerate(self.versions):
            if version.effective_from_tick < last_end:
                raise ValueError("norm versions must be ordered and non-overlapping")
            if index < len(self.versions) - 1 and version.effective_until_tick is None:
                raise ValueError("historical norm versions require an end tick")
            if index == len(self.versions) - 1 and version.effective_until_tick is not None:
                raise ValueError("the active norm version must not have an end tick")
            last_end = version.effective_until_tick if version.effective_until_tick is not None else version.effective_from_tick
        if len(self.jurisdictions) > 128 or any(
            not isinstance(item, tuple) or len(item) != 2 or any(not isinstance(x, str) or not x for x in item)
            for item in self.jurisdictions
        ):
            raise ValueError("jurisdictions must be (stable_id, name) pairs")
        jurisdiction_ids = {item[0] for item in self.jurisdictions}
        if len(jurisdiction_ids) != len(self.jurisdictions):
            raise ValueError("jurisdiction IDs must be unique")
        for version in self.versions:
            seen_rule_ids: set[str] = set()
            pending = [(rule, 1) for rule in (*version.legal_rules, *version.social_norms)]
            visited: set[int] = set()
            while pending:
                rule, depth = pending.pop()
                if depth > 8 or id(rule) in visited:
                    raise ValueError("norm tree is cyclic or too deep")
                visited.add(id(rule))
                if len(visited) > 2_000:
                    raise ValueError("norm version has too many nested entries")
                if rule.rule_id in seen_rule_ids:
                    raise ValueError("norm IDs must be unique within each version")
                seen_rule_ids.add(rule.rule_id)
                if not set(rule.jurisdiction_ids).issubset(jurisdiction_ids):
                    raise ValueError("norm references an unknown jurisdiction")
                pending.extend((child, depth + 1) for child in rule.children)
        if self.governance_status is GovernanceStatus.NO_FORMAL_LAW:
            if self.lawmaking_authority not in (None, ""):
                raise ValueError("a no-formal-law world cannot name a formal lawmaking authority")
            if any(version.legal_rules for version in self.versions):
                raise ValueError("a no-formal-law world cannot contain formal legal rules")
        if any(not isinstance(x, str) or not x or len(x) > 500 for x in self.enforcement_or_governance_bodies):
            raise ValueError("governance bodies are invalid")
        if any(not isinstance(x, str) or not x or len(x) > 500 for x in self.content_hints):
            raise ValueError("content_hints are invalid")

    @property
    def active_version(self) -> NormVersion:
        return next(v for v in self.versions if v.version_id == self.active_version_id)


@dataclass(frozen=True)
class PublicNormEntry:
    stable_id: str
    title: str
    summary: str
    detail: str
    applicable_regions: tuple[tuple[str, str], ...]
    current_status: str
    children: tuple["PublicNormEntry", ...] = ()
    conduct_scope: str = ""
    normative_force: str = NormativeForce.REGULATE.value


@dataclass(frozen=True)
class WorldNormsProjection:
    """Closed read-only data contract; contains public information only."""

    world_id: str
    world_notice: str
    governance_summary: str
    version_id: str
    legal_rules: tuple[PublicNormEntry, ...]
    social_norms: tuple[PublicNormEntry, ...]
    content_hints: tuple[str, ...]


def _public_entry(
    rule: NormRule,
    governance: UniversalSafetyGovernance,
    jurisdiction_names: Mapping[str, str],
) -> PublicNormEntry | None:
    if not rule.is_public or rule.status != "active":
        return None
    governance.require_presentation_allowed(SafetyInput(
        actor_id="public-world-projection",
        source="public_norm_projection",
        intent=rule.title,
        method=rule.detail,
        context=rule.summary,
    ))
    children = tuple(
        item for child in rule.children
        if (item := _public_entry(child, governance, jurisdiction_names)) is not None
    )
    return PublicNormEntry(
        rule.rule_id, rule.title, rule.summary, rule.detail,
        tuple((key, jurisdiction_names[key]) for key in rule.jurisdiction_ids), rule.status, children,
        rule.conduct_scope, rule.normative_force.value,
    )


def project_public_norms(
    norms: WorldNorms,
    version_id: str | None = None,
    *,
    safety_governance: UniversalSafetyGovernance,
) -> WorldNormsProjection:
    if not isinstance(norms, WorldNorms):
        raise TypeError("norms must be a validated WorldNorms record")
    selected_id = version_id or norms.active_version_id
    version = next((v for v in norms.versions if v.version_id == selected_id), None)
    if version is None:
        raise KeyError("unknown WorldNorms version")
    if not isinstance(safety_governance, UniversalSafetyGovernance):
        raise TypeError("public norm projection requires the configured safety governance")
    governance = safety_governance
    jurisdiction_names = dict(norms.jurisdictions)
    legal = tuple(item for rule in version.legal_rules if (item := _public_entry(rule, governance, jurisdiction_names)) is not None)
    social = tuple(item for rule in version.social_norms if (item := _public_entry(rule, governance, jurisdiction_names)) is not None)
    governance.require_presentation_allowed(SafetyInput(
        actor_id="public-world-projection",
        source="world_notice",
        intent=norms.player_notice,
        context="short pre-entry public notice",
    ))
    for hint in norms.content_hints:
        governance.require_presentation_allowed(SafetyInput(
            actor_id="public-world-projection",
            source="world_content_hint",
            intent=hint,
            context="pre-entry content disclosure",
        ))
    return WorldNormsProjection(
        norms.world_id, norms.player_notice, norms.governance_status.value,
        version.version_id, legal, social, norms.content_hints,
    )


def applicable_norm_rules(
    norms: WorldNorms,
    *,
    jurisdiction_id: str,
    simulation_tick: int,
) -> tuple[tuple[NormRule, ...], tuple[NormRule, ...]]:
    """Read rules effective in a jurisdiction; this does not decide legality or outcomes."""
    if not isinstance(norms, WorldNorms):
        raise TypeError("norms must be a validated WorldNorms record")
    if not isinstance(jurisdiction_id, str) or not jurisdiction_id:
        raise ValueError("jurisdiction_id is required")
    if isinstance(simulation_tick, bool) or not isinstance(simulation_tick, int) or simulation_tick < 0:
        raise ValueError("simulation_tick must be a non-negative integer")
    if jurisdiction_id not in {key for key, _ in norms.jurisdictions}:
        raise KeyError("unknown jurisdiction")
    version = next((item for item in norms.versions if
                    item.effective_from_tick <= simulation_tick and
                    (item.effective_until_tick is None or simulation_tick < item.effective_until_tick)), None)
    if version is None:
        return (), ()

    def select(items: tuple[NormRule, ...]) -> tuple[NormRule, ...]:
        selected: list[NormRule] = []
        pending = list(items)
        while pending:
            rule = pending.pop(0)
            if rule.status == "active" and (not rule.jurisdiction_ids or jurisdiction_id in rule.jurisdiction_ids):
                selected.append(rule)
                pending[0:0] = list(rule.children)
        return tuple(selected)

    return select(version.legal_rules), select(version.social_norms)


class NormsDraftProvider(Protocol):
    def generate_norms_draft(self, world_seed: str, *, max_output_chars: int) -> str: ...


@dataclass
class WorldNormsGenerationPipeline:
    """Manual/config/model draft ingestion followed by schema, safety, and consistency validation."""

    safety_governance: UniversalSafetyGovernance
    provider: NormsDraftProvider | None = None
    maximum_output_chars: int = 24_000

    def __post_init__(self) -> None:
        if isinstance(self.maximum_output_chars, bool) or not isinstance(self.maximum_output_chars, int) or not 1 <= self.maximum_output_chars <= 24_000:
            raise ValueError("maximum_output_chars must be within the WorldNorms bounds")

    def generate(self, source: Mapping[str, object] | str, *, world_id: str) -> WorldNorms:
        if isinstance(source, str):
            if self.provider is None:
                raise ValueError("a norms draft provider is required for natural-language generation")
            raw = self.provider.generate_norms_draft(source[:8_000], max_output_chars=self.maximum_output_chars)
            if not isinstance(raw, str) or len(raw) > self.maximum_output_chars:
                raise ValueError("generated norms draft exceeds size bound")
            source_data = json_load_mapping(raw)
        elif isinstance(source, Mapping):
            source_data = dict(source)
        else:
            raise TypeError("source must be structured config or a world seed string")
        import json
        try:
            encoded_source = json.dumps(source_data, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("WorldNorms source is not JSON-compatible") from exc
        if len(encoded_source) > self.maximum_output_chars:
            raise ValueError("WorldNorms source exceeds the schema input bound")
        norms = parse_world_norms(source_data, expected_world_id=world_id)
        # World laws can describe wrongdoing. Only operational assistance to
        # universal harms is rejected; legality itself is not treated as safety.
        for version in norms.versions:
            for rule in (*version.legal_rules, *version.social_norms):
                result = self.safety_governance.assess(SafetyInput(
                    actor_id="world-generation", source="world_norm", intent=rule.title,
                    method=rule.detail, context=rule.summary,
                ))
                if result.disposition is SafetyDisposition.REFUSE:
                    raise PermissionError("WorldNorms draft conflicts with universal safety constraints")
        return norms


def json_load_mapping(raw: str) -> Mapping[str, object]:
    import json
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("WorldNorms provider must return one JSON object")
    return parsed


def parse_world_norms(data: Mapping[str, object], *, expected_world_id: str) -> WorldNorms:
    allowed = {
        "world_id", "governance_status", "lawmaking_authority", "jurisdictions",
        "responsibility_and_process", "enforcement_or_governance_bodies",
        "law_morality_distinction", "versions", "active_version_id", "player_notice", "content_hints",
    }
    if set(data) != allowed:
        raise ValueError("WorldNorms schema contains missing or unsupported fields")
    if data["world_id"] != expected_world_id:
        raise PermissionError("WorldNorms world identity does not match the requested world")
    jurisdiction_values = data["jurisdictions"]
    version_values = data["versions"]
    if not isinstance(jurisdiction_values, list) or not isinstance(version_values, list):
        raise TypeError("jurisdictions and versions must be arrays")
    if not isinstance(data["enforcement_or_governance_bodies"], list) or not isinstance(data["content_hints"], list):
        raise TypeError("governance bodies and content hints must be arrays")
    if any(not isinstance(value, str) or not value for value in data["enforcement_or_governance_bodies"]):
        raise TypeError("governance bodies must be non-empty strings")
    if any(not isinstance(value, str) or not value for value in data["content_hints"]):
        raise TypeError("content hints must be non-empty strings")
    for key in ("responsibility_and_process", "law_morality_distinction", "active_version_id", "player_notice"):
        if not isinstance(data[key], str):
            raise TypeError(f"{key} must be a string")
    if data["lawmaking_authority"] is not None and not isinstance(data["lawmaking_authority"], str):
        raise TypeError("lawmaking_authority must be a string or None")
    jurisdictions = tuple((row["id"], row["name"]) for row in jurisdiction_values if isinstance(row, Mapping) and set(row) == {"id", "name"} and all(isinstance(row.get(key), str) and row[key] for key in ("id", "name")))
    if len(jurisdictions) != len(jurisdiction_values):
        raise ValueError("jurisdiction row schema is invalid")
    versions = tuple(_parse_version(row) for row in version_values)
    return WorldNorms(
        data["world_id"], GovernanceStatus(data["governance_status"]),
        data["lawmaking_authority"],
        jurisdictions, data["responsibility_and_process"],
        tuple(data["enforcement_or_governance_bodies"]),
        data["law_morality_distinction"], versions,
        data["active_version_id"], data["player_notice"],
        tuple(data["content_hints"]),
    )


def _parse_rule(data: object) -> NormRule:
    return _parse_rule_bounded(data, depth=1, budget=[0])


def _parse_rule_bounded(data: object, *, depth: int, budget: list[int]) -> NormRule:
    budget[0] += 1
    if depth > 8 or budget[0] > 2_000:
        raise ValueError("norm tree exceeds depth or node bounds")
    if not isinstance(data, Mapping) or set(data) != {
        "rule_id", "title", "summary", "detail", "jurisdiction_ids", "status", "is_public", "children", "conduct_scope", "normative_force"
    }:
        raise ValueError("norm rule schema is invalid")
    if not isinstance(data["jurisdiction_ids"], list) or not isinstance(data["children"], list):
        raise TypeError("norm rule arrays are invalid")
    if not isinstance(data["rule_id"], str) or not isinstance(data["title"], str) or not isinstance(data["summary"], str) or not isinstance(data["detail"], str) or not isinstance(data["status"], str) or not isinstance(data["conduct_scope"], str):
        raise TypeError("norm rule text fields must be strings")
    if any(not isinstance(value, str) for value in data["jurisdiction_ids"]):
        raise TypeError("jurisdiction references must be strings")
    if type(data["is_public"]) is not bool:
        raise TypeError("is_public must be bool")
    return NormRule(
        data["rule_id"], data["title"], data["summary"], data["detail"],
        tuple(data["jurisdiction_ids"]), data["status"], data["is_public"],
        tuple(_parse_rule_bounded(item, depth=depth + 1, budget=budget) for item in data["children"]),
        data["conduct_scope"], NormativeForce(data["normative_force"]),
    )


def _parse_version(data: object) -> NormVersion:
    if not isinstance(data, Mapping) or set(data) != {
        "version_id", "effective_from_tick", "effective_until_tick", "legal_rules", "social_norms"
    }:
        raise ValueError("norm version schema is invalid")
    if not isinstance(data["legal_rules"], list) or not isinstance(data["social_norms"], list):
        raise TypeError("norm version rule collections must be arrays")
    if not isinstance(data["version_id"], str):
        raise TypeError("version_id must be a string")
    return NormVersion(
        data["version_id"], data["effective_from_tick"], data["effective_until_tick"],
        tuple(_parse_rule(item) for item in data["legal_rules"]),
        tuple(_parse_rule(item) for item in data["social_norms"]),
    )
