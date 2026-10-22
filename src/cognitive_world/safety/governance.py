"""Bounded semantic safety assessment, separate from world legality and causality.

The fixed invariant set lives in code and is not supplied by scenarios, player
text, NPC goals, director commands, or model output. The deterministic fallback
is deliberately conservative around ambiguous high-risk intents, while ordinary
fictional conflict remains available to Resolution.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
import math
from typing import Protocol



SAFETY_POLICY_VERSION = "cw-universal-safety-1"
MAX_SAFETY_INPUT_CHARS = 12_000
MAX_SAFETY_OUTPUT_CHARS = 4_000
MAX_SAFETY_STEPS = 5
PRESENTATION_SOURCES = frozenset({
    "player_presentation", "public_norm_projection", "world_notice",
    "world_content_hint", "npc_dialogue",
})
NON_ACTION_SOURCES = PRESENTATION_SOURCES | {"world_norm"}
UNIVERSAL_SAFETY_INVARIANTS = frozenset({
    "sexual_exploitation_or_sexualization_of_minors",
    "explicit_nonconsensual_sexual_violence",
    "actionable_serious_violent_crime_assistance",
    "operational_terrorism_or_mass_harm_assistance",
    "operational_human_trafficking_or_forced_exploitation_assistance",
    "suicide_or_self_harm_instructions_or_encouragement",
    "incitement_to_hateful_violence",
    "sexual_extortion_or_serious_privacy_abuse_assistance",
})


class SafetyDisposition(str, Enum):
    ALLOW = "allow"
    RESTRICT_PRESENTATION = "restrict_presentation"
    REFUSE = "refuse"
    CLARIFY = "clarify_or_safe_degrade"


class SafetyRiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    ELEVATED = "elevated"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SafetyInput:
    """Exact bounded content to assess; identity and provenance are host supplied."""

    actor_id: str
    source: str
    intent: str
    target_refs: tuple[str, ...] = ()
    method: str = ""
    context: str = ""
    ordered_steps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for label, value in (("actor_id", self.actor_id), ("source", self.source), ("intent", self.intent)):
            if not isinstance(value, str) or not value.strip() or len(value) > 4_000:
                raise ValueError(f"{label} must be bounded non-empty text")
        if not isinstance(self.target_refs, tuple):
            raise TypeError("target_refs must be an immutable tuple")
        if len(self.target_refs) > 16 or any(not isinstance(x, str) or not x or len(x) > 256 for x in self.target_refs):
            raise ValueError("target_refs exceed the safety input bound")
        if not isinstance(self.method, str) or len(self.method) > 4_000 or not isinstance(self.context, str) or len(self.context) > 4_000:
            raise ValueError("method/context exceed the safety input bound")
        if not isinstance(self.ordered_steps, tuple):
            raise TypeError("ordered_steps must be an immutable tuple")
        if len(self.ordered_steps) > MAX_SAFETY_STEPS or any(not isinstance(x, str) or not x or len(x) > 2_000 for x in self.ordered_steps):
            raise ValueError("ordered_steps exceed the safety input bound")
        if len(self.canonical_bytes()) > MAX_SAFETY_INPUT_CHARS:
            raise ValueError("safety input exceeds the encoded size bound")

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            {
                "actor_id": self.actor_id,
                "source": self.source,
                "intent": self.intent,
                "target_refs": self.target_refs,
                "method": self.method,
                "context": self.context,
                "ordered_steps": self.ordered_steps,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @property
    def content_digest(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()


def safety_input_from_proposal(proposal: object, *, source: str) -> SafetyInput:
    """Project only attempt-bearing proposal fields into the safety boundary."""
    from cognitive_world.decision.action_proposal import ActionProposal

    if not isinstance(proposal, ActionProposal):
        raise TypeError("safety proposal projection requires ActionProposal")
    params = proposal.parameters
    raw_steps = params.get("steps", ())
    if not isinstance(raw_steps, (tuple, list)):
        raise ValueError("proposal steps must be an ordered sequence")
    steps: list[str] = []
    for step in raw_steps:
        if isinstance(step, str):
            steps.append(step)
        elif isinstance(step, Mapping) and isinstance(step.get("method"), str):
            steps.append(step["method"])
        else:
            raise ValueError("proposal contains an invalid method step")
    method = params.get("method", "")
    preconditions = params.get("preconditions", ())
    if not isinstance(method, str) or not isinstance(preconditions, (tuple, list)):
        raise ValueError("proposal method or preconditions have an invalid shape")
    if any(not isinstance(value, str) for value in preconditions):
        raise ValueError("proposal preconditions must be text")
    return SafetyInput(
        actor_id=proposal.agent_id,
        source=source,
        intent=proposal.action_type,
        target_refs=tuple(proposal.target_refs),
        method=method,
        context="submitted preconditions (untrusted): " + " ".join(preconditions),
        ordered_steps=tuple(steps),
    )


def safety_input_from_attempt(attempt: object, *, source: str) -> SafetyInput:
    """Project the immutable Attempt snapshot into the safety boundary."""
    from cognitive_world.decision.attempt import Attempt

    if not isinstance(attempt, Attempt):
        raise TypeError("safety Attempt projection requires Attempt")
    params = attempt.parameters
    raw_steps = params.get("steps", ())
    if not isinstance(raw_steps, (tuple, list)):
        raise ValueError("Attempt steps must be an ordered sequence")
    steps: list[str] = []
    for step in raw_steps:
        if isinstance(step, str):
            steps.append(step)
        elif isinstance(step, Mapping) and isinstance(step.get("method"), str):
            steps.append(step["method"])
        else:
            raise ValueError("Attempt contains an invalid method step")
    method = params.get("method", "")
    if not isinstance(method, str):
        raise ValueError("Attempt method must be text")
    return SafetyInput(
        actor_id=attempt.agent_id,
        source=source,
        intent=attempt.action_type,
        target_refs=tuple(attempt.target_refs),
        method=method,
        context="Attempt preconditions (untrusted): " + " ".join(
            value for value in params.get("preconditions", ())
            if isinstance(value, str)
        ) if isinstance(params.get("preconditions", ()), (tuple, list)) else "Attempt preconditions unknown",
        ordered_steps=tuple(steps),
    )


@dataclass(frozen=True)
class SemanticSafetyAssessment:
    actor_id: str
    source: str
    intent: str
    method: str
    context: str
    multi_step_purpose: str
    risk_categories: tuple[str, ...]
    risk_level: SafetyRiskLevel
    disposition: SafetyDisposition
    basis_kind: str
    uncertainty: float
    content_digest: str
    subject_refs: tuple[str, ...] = ()
    subject_attribute_assessments: tuple[str, ...] = ()
    policy_version: str = SAFETY_POLICY_VERSION
    world_context_digest: str = "unbound"

    def __post_init__(self) -> None:
        if not isinstance(self.risk_level, SafetyRiskLevel) or not isinstance(self.disposition, SafetyDisposition):
            raise TypeError("assessment risk and disposition must use supported values")
        if isinstance(self.uncertainty, bool) or not isinstance(self.uncertainty, (int, float)) or not math.isfinite(self.uncertainty) or not 0 <= self.uncertainty <= 1:
            raise ValueError("uncertainty must be finite and in [0, 1]")
        if not self.content_digest or self.policy_version != SAFETY_POLICY_VERSION:
            raise ValueError("assessment is missing its content or policy binding")
        if not isinstance(self.world_context_digest, str) or not self.world_context_digest:
            raise ValueError("assessment is missing its world-context binding")
        if not isinstance(self.risk_categories, tuple) or not isinstance(self.subject_refs, tuple) or not isinstance(self.subject_attribute_assessments, tuple):
            raise TypeError("assessment collections must be immutable tuples")
        if any(not isinstance(value, str) or not value for value in (*self.risk_categories, *self.subject_refs, *self.subject_attribute_assessments)):
            raise ValueError("assessment collections contain invalid values")

    def matches(self, item: SafetyInput, world_context_digest: str) -> bool:
        return (
            self.actor_id == item.actor_id
            and self.source == item.source
            and self.intent == item.intent
            and self.method == item.method
            and self.context == item.context
            and self.content_digest == item.content_digest
            and self.world_context_digest == world_context_digest
            and self.policy_version == SAFETY_POLICY_VERSION
            and self.subject_refs == item.target_refs
        )


class SemanticSafetyProvider(Protocol):
    def assess_safety(
        self, item: SafetyInput, *,
        trusted_subjects: tuple["SafetySubjectContext", ...],
        max_output_chars: int,
    ) -> str:
        """Return untrusted JSON labels; it cannot authorize an Event or effect."""


@dataclass(frozen=True)
class SafetySubjectContext:
    """Read-only safety facts resolved from the active WorldState."""

    subject_id: str
    entity_type: str | None
    age_years: int | None
    profile_revision: int | None
    consent_status: str = "unknown"


class SafetyReadiness(str, Enum):
    DETERMINISTIC_ONLY = "deterministic_only_unvalidated"
    PROVIDER_CONFIGURED_UNVALIDATED = "provider_configured_unvalidated"


def _context_digest(world_id: int | None, tick: int | None,
                    subjects: tuple[SafetySubjectContext, ...]) -> str:
    value = (world_id, tick, tuple(
        (s.subject_id, s.entity_type, s.age_years, s.profile_revision, s.consent_status)
        for s in subjects
    ))
    return sha256(repr(value).encode("utf-8")).hexdigest()


_RISK_CUES = {
    "minor": ("minor", "underage", "child", "children", "teenager", "teen", "未成年", "未成年人", "儿童", "小孩", "未成年者"),
    "sexual": ("sexual", "sexually", "sexualize", "sex act", "性行为", "性化", "色情"),
    "coercion": ("non-consensual", "without consent", "rape", "sexual assault", "强迫发生性", "非自愿性", "性侵"),
    "self_harm": ("suicide", "self-harm", "kill myself", "encourage suicide", "鼓励自杀", "自杀", "自残"),
    "mass_harm": ("mass casualty", "mass attack", "terror attack", "大规模伤害", "恐怖袭击"),
    "serious_violence": ("poison someone", "hide a body", "evade police after assault", "untraceable weapon", "毒害某人", "掩埋尸体", "逃避警方追查", "伤害他人的具体方法"),
    "operational": ("step by step", "instructions to make", "instructions for", "how to build", "how to", "guide to", "plan to carry out", "实施步骤", "制作方法", "具体教程", "具体计划", "如何实施"),
    "support": ("rescue", "protect", "first aid", "investigate", "history of", "legal analysis", "fictional story", "crime fiction", "write a scene", "救援", "保护", "急救", "调查", "法律分析", "历史研究", "虚构故事", "小说情节"),
    "trafficking": ("human trafficking", "forced labor", "forced exploitation", "人口贩卖", "强迫劳动", "强迫剥削"),
    "hate_violence": ("incite hateful violence", "promote violence against a protected group", "仇恨暴力煽动", "煽动针对群体的暴力"),
    "privacy_extortion": ("sexual extortion", "sextortion", "dox", "勒索私密影像", "性勒索", "泄露住址"),
    "graphic_detail": ("graphic gore", "dismember", "mutilation", "露骨血腥", "肢解细节", "性行为过程"),
}
_NON_GRAPHIC_CUES = ("fade to black", "scene fades", "off-screen", "non-graphic", "淡出", "转场", "镜头移开", "不作细节描写")


_DISCUSSION_CUES = (
    "history of", "legal analysis", "historical discussion", "discuss the law",
    "legal history", "历史研究", "法律分析",
)


def _fallback_assessment(
    item: SafetyInput,
    subjects: tuple[SafetySubjectContext, ...],
    world_context_digest: str,
) -> SemanticSafetyAssessment:
    """Small multilingual semantic triage, not a complete classifier or keyword gate."""
    corpus = "\n".join((item.intent, item.method, item.context, *item.ordered_steps)).casefold()
    present = {name for name, cues in _RISK_CUES.items() if any(cue in corpus for cue in cues)}
    sexual = "sexual" in present or "coercion" in present
    support = "support" in present
    operational = "operational" in present

    prohibition_cues = ("prohibited", "forbidden", "illegal", "not permitted", "banned", "禁止", "违法", "不得", "严禁")
    if item.source == "world_norm" and any(cue in corpus for cue in prohibition_cues) and not operational:
        return SemanticSafetyAssessment(
            item.actor_id, item.source, item.intent, item.method, item.context,
            " | ".join(item.ordered_steps), ("prohibitive_norm_text",),
            SafetyRiskLevel.LOW, SafetyDisposition.ALLOW,
            "normative_description_not_action_guidance", 0.25, item.content_digest,
            item.target_refs, (), SAFETY_POLICY_VERSION, world_context_digest,
        )

    discussion_only = (
        not operational
        and any(cue in item.intent.casefold() for cue in _DISCUSSION_CUES)
    )
    if discussion_only:
        return SemanticSafetyAssessment(
            item.actor_id, item.source, item.intent, item.method, item.context,
            " | ".join(item.ordered_steps), ("serious_topic_discussion",),
            SafetyRiskLevel.LOW, SafetyDisposition.ALLOW,
            "non_operational_legal_or_historical_discussion", 0.25,
            item.content_digest, item.target_refs, (), SAFETY_POLICY_VERSION,
            world_context_digest,
        )

    disposition = SafetyDisposition.ALLOW
    level = SafetyRiskLevel.NONE
    categories: list[str] = []
    if sexual and "minor" in present:
        disposition, level = SafetyDisposition.REFUSE, SafetyRiskLevel.CRITICAL
        categories.append("sexual_content_involving_minor")
    elif sexual and any(
        subject.age_years is not None and subject.age_years < 18
        for subject in subjects
    ):
        disposition, level = SafetyDisposition.REFUSE, SafetyRiskLevel.CRITICAL
        categories.append("sexual_content_involving_minor")
    elif sexual and "coercion" in present:
        disposition, level = SafetyDisposition.REFUSE, SafetyRiskLevel.CRITICAL
        categories.append("non_consensual_sexual_violence")
    elif sexual and item.source != "player_presentation" and (
        not subjects
        or any(subject.age_years is None for subject in subjects)
        or any(subject.consent_status != "confirmed_for_current_context" for subject in subjects)
    ):
        disposition, level = SafetyDisposition.CLARIFY, SafetyRiskLevel.UNKNOWN
        categories.append("trusted_age_or_consent_context_unknown")
    elif "self_harm" in present and operational and not support:
        disposition, level = SafetyDisposition.REFUSE, SafetyRiskLevel.HIGH
        categories.append("self_harm_instructions_or_encouragement")
    elif "mass_harm" in present and operational and not support:
        disposition, level = SafetyDisposition.REFUSE, SafetyRiskLevel.CRITICAL
        categories.append("operational_mass_harm")
    elif "serious_violence" in present and operational and not support:
        disposition, level = SafetyDisposition.REFUSE, SafetyRiskLevel.HIGH
        categories.append("actionable_serious_violent_crime_assistance")
    elif "privacy_extortion" in present and not support:
        disposition, level = SafetyDisposition.REFUSE, SafetyRiskLevel.HIGH
        categories.append("sexual_extortion_or_serious_privacy_invasion")
    elif ("trafficking" in present or "hate_violence" in present) and operational and not support:
        disposition, level = SafetyDisposition.REFUSE, SafetyRiskLevel.HIGH
        categories.extend(sorted(present & {"trafficking", "privacy_extortion", "hate_violence"}))
    elif "hate_violence" in present and not support:
        disposition, level = SafetyDisposition.REFUSE, SafetyRiskLevel.HIGH
        categories.append("incitement_to_hateful_violence")
    elif ("minor" in present and sexual) or ("coercion" in present and sexual):
        disposition, level = SafetyDisposition.REFUSE, SafetyRiskLevel.CRITICAL
    elif ("minor" in present or "coercion" in present or "self_harm" in present or "mass_harm" in present or "trafficking" in present or "serious_violence" in present) and not support:
        disposition, level = SafetyDisposition.CLARIFY, SafetyRiskLevel.UNKNOWN
        categories.extend(sorted(present & {"minor", "coercion", "self_harm", "mass_harm"}))
    elif "sexual" in present:
        # Adult consensual intimacy is permitted; explicitness is handled at presentation.
        if item.source == "player_presentation" and any(cue in corpus for cue in _NON_GRAPHIC_CUES):
            disposition, level = SafetyDisposition.ALLOW, SafetyRiskLevel.LOW
            categories.append("non_graphic_fade_or_summary")
        else:
            disposition, level = SafetyDisposition.RESTRICT_PRESENTATION, SafetyRiskLevel.LOW
            categories.append("sexual_content_presentation_limit")
    elif "graphic_detail" in present and item.source == "player_presentation":
        disposition, level = SafetyDisposition.RESTRICT_PRESENTATION, SafetyRiskLevel.ELEVATED
        categories.append("graphic_detail_presentation_limit")
    elif any(word in corpus for word in ("fight", "battle", "war", "threaten", "steal", "argue", "conflict", "战斗", "战争", "争吵", "威胁", "偷窃", "冲突")):
        # Fictional conflict, crime, and negative emotion stay in the causal/decision system.
        disposition, level = SafetyDisposition.ALLOW, SafetyRiskLevel.LOW
        categories.append("fictional_conflict_allowed")

    return SemanticSafetyAssessment(
        item.actor_id, item.source, item.intent, item.method, item.context,
        " | ".join(item.ordered_steps), tuple(categories), level, disposition,
        "deterministic_semantic_triage", 0.55 if level is SafetyRiskLevel.UNKNOWN else 0.2,
        item.content_digest,
        item.target_refs, (), SAFETY_POLICY_VERSION, world_context_digest,
    )


def _parse_provider_result(
    item: SafetyInput, raw: str, world_context_digest: str,
) -> SemanticSafetyAssessment:
    if not isinstance(raw, str) or len(raw) > MAX_SAFETY_OUTPUT_CHARS:
        raise ValueError("safety provider output exceeds size bound")
    parsed = json.loads(raw)
    allowed = {"intent", "method", "context", "multi_step_purpose", "subject_attribute_assessments", "risk_categories", "risk_level", "disposition", "basis_kind", "uncertainty"}
    if not isinstance(parsed, dict) or set(parsed) != allowed:
        raise PermissionError("safety provider returned an invalid field set")
    text_fields = ("intent", "method", "context", "multi_step_purpose", "basis_kind")
    if any(not isinstance(parsed[key], str) or len(parsed[key]) > 1000 for key in text_fields):
        raise ValueError("safety assessment text fields exceed bounds")
    cats = parsed["risk_categories"]
    if not isinstance(cats, list) or len(cats) > 16 or any(not isinstance(x, str) or not x or len(x) > 120 for x in cats):
        raise ValueError("safety risk categories are invalid")
    subjects = parsed["subject_attribute_assessments"]
    if not isinstance(subjects, list) or len(subjects) > 16 or any(not isinstance(x, str) or not x or len(x) > 500 for x in subjects):
        raise ValueError("subject attribute assessments are invalid")
    try:
        level = SafetyRiskLevel(parsed["risk_level"])
        disposition = SafetyDisposition(parsed["disposition"])
    except (ValueError, TypeError) as exc:
        raise ValueError("safety provider returned an unsupported classification") from exc
    uncertainty = parsed["uncertainty"]
    if isinstance(uncertainty, bool) or not isinstance(uncertainty, (int, float)) or not math.isfinite(uncertainty) or not 0 <= uncertainty <= 1:
        raise ValueError("safety uncertainty is invalid")
    # Identity, targets, provenance, policy version, and digest are bound locally,
    # never accepted from model output.
    return SemanticSafetyAssessment(
        item.actor_id, item.source, parsed["intent"], parsed["method"],
        parsed["context"], parsed["multi_step_purpose"], tuple(cats), level,
        disposition, parsed["basis_kind"], float(uncertainty), item.content_digest,
        item.target_refs, tuple(subjects), SAFETY_POLICY_VERSION,
        world_context_digest,
    )


@dataclass
class UniversalSafetyGovernance:
    """The fixed safety boundary; world content cannot configure exemptions."""

    provider: SemanticSafetyProvider | None = None
    world_state: object | None = field(default=None, repr=False, compare=False)
    simulation_clock: object | None = field(default=None, repr=False, compare=False)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("UniversalSafetyGovernance cannot be subclassed to weaken core policy")

    @property
    def readiness(self) -> SafetyReadiness:
        """Report configuration status; configured providers remain unvalidated until exercised."""
        if self.provider is None:
            return SafetyReadiness.DETERMINISTIC_ONLY
        return SafetyReadiness.PROVIDER_CONFIGURED_UNVALIDATED

    def bind_runtime(self, world_state: object, simulation_clock: object) -> None:
        """Bind the authoritative world and simulation clock for safety context."""
        from cognitive_world.core.world_state import WorldState
        from cognitive_world.runtime.clock import SimulationClock

        if not isinstance(simulation_clock, SimulationClock):
            raise TypeError("safety runtime binding requires SimulationClock")
        if self.simulation_clock is not None and self.simulation_clock is not simulation_clock:
            raise PermissionError("safety governance cannot be rebound to another runtime clock")
        if self.world_state is not None and self.world_state is not world_state:
            raise PermissionError("safety governance cannot be rebound to another runtime world")
        self.bind_world_state(world_state)
        self.simulation_clock = simulation_clock

    def bind_world_state(self, world_state: object) -> None:
        from cognitive_world.core.world_state import WorldState

        if not isinstance(world_state, WorldState):
            raise TypeError("safety binding requires WorldState")
        if self.world_state is not None and self.world_state is not world_state:
            raise PermissionError("safety governance cannot be rebound to another runtime world")
        self.world_state = world_state

    def _resolve_subject_context(
        self, item: SafetyInput,
    ) -> tuple[tuple[SafetySubjectContext, ...], str]:
        from cognitive_world.core.entity import Entity, SafetySubjectProfile
        from cognitive_world.core.world_state import WorldState
        from cognitive_world.runtime.clock import SimulationClock

        subjects: list[SafetySubjectContext] = []
        world = self.world_state
        subject_ids = tuple(dict.fromkeys((item.actor_id, *item.target_refs)))
        if isinstance(world, WorldState):
            for subject_id in subject_ids:
                entity = world.get_entity(subject_id)
                if not isinstance(entity, Entity):
                    subjects.append(SafetySubjectContext(subject_id, None, None, None))
                    continue
                profile = entity.safety_profile
                if profile is not None and not isinstance(profile, SafetySubjectProfile):
                    raise TypeError("WorldState contains an invalid safety subject profile")
                subjects.append(SafetySubjectContext(
                    subject_id,
                    entity.type,
                    None if profile is None else profile.age_years,
                    None if profile is None else profile.profile_revision,
                ))
        else:
            subjects.extend(
                SafetySubjectContext(subject_id, None, None, None)
                for subject_id in subject_ids
            )
        clock = self.simulation_clock
        tick = clock.current_time if isinstance(clock, SimulationClock) else None
        digest = _context_digest(None if world is None else id(world), tick, tuple(subjects))
        return tuple(subjects), digest

    def assess(self, item: SafetyInput) -> SemanticSafetyAssessment:
        if not isinstance(item, SafetyInput):
            raise TypeError("safety assessment requires a bounded SafetyInput")
        trusted_subjects, world_digest = self._resolve_subject_context(item)
        fallback = _fallback_assessment(item, trusted_subjects, world_digest)
        # Deterministic hard stops cannot be downgraded by a provider response.
        if fallback.disposition is SafetyDisposition.REFUSE:
            return fallback
        if self.provider is None:
            return fallback
        try:
            from cognitive_world.resolution.provider_budget import claim_provider_call, provider_call_scope

            with provider_call_scope():
                if not claim_provider_call():
                    raise TimeoutError("safety provider-call budget is exhausted")
                raw = self.provider.assess_safety(
                    item,
                    trusted_subjects=trusted_subjects,
                    max_output_chars=MAX_SAFETY_OUTPUT_CHARS,
                )
            model = _parse_provider_result(item, raw, world_digest)
        except Exception:
            # A high-risk/ambiguous fallback never turns into permission on failure.
            if fallback.risk_level in {SafetyRiskLevel.UNKNOWN, SafetyRiskLevel.HIGH, SafetyRiskLevel.CRITICAL}:
                return SemanticSafetyAssessment(
                    item.actor_id, item.source, item.intent, item.method, item.context,
                    " | ".join(item.ordered_steps), fallback.risk_categories,
                    fallback.risk_level, SafetyDisposition.CLARIFY,
                    "provider_failure_safe_degrade", 1.0, item.content_digest,
                    item.target_refs, (), SAFETY_POLICY_VERSION, world_digest,
                )
            return fallback
        if not model.matches(item, world_digest):
            raise PermissionError("semantic assessment is not bound to the exact input")
        labels = " ".join(model.risk_categories).casefold()
        hard_risk_terms = (
            "sexual_content_involving_minor", "sexual exploitation of minors",
            "non_consensual_sexual_violence", "operational_mass_harm",
            "human_trafficking_assistance", "self_harm_instructions_or_encouragement",
            "hate_violence_incitation", "sexual_extortion_assistance",
        )
        if any(term in labels for term in hard_risk_terms):
            ordered_risks = list(SafetyRiskLevel)
            risk = model.risk_level if ordered_risks.index(model.risk_level) >= ordered_risks.index(SafetyRiskLevel.HIGH) else SafetyRiskLevel.HIGH
            return SemanticSafetyAssessment(
                item.actor_id, item.source, item.intent, item.method, item.context,
                model.multi_step_purpose, model.risk_categories, risk,
                SafetyDisposition.REFUSE, "non_overridable_category_gate", 1.0,
                item.content_digest, item.target_refs, model.subject_attribute_assessments,
                SAFETY_POLICY_VERSION, world_digest,
            )
        if "fictional_conflict_allowed" in fallback.risk_categories and model.disposition is SafetyDisposition.REFUSE:
            generic_only = all(
                category.casefold() in {"violence", "fictional_violence", "crime", "negative_emotion", "illegal_in_world"}
                for category in model.risk_categories
            )
            if generic_only:
                return fallback
        if fallback.disposition is SafetyDisposition.CLARIFY and model.disposition is SafetyDisposition.ALLOW:
            return fallback
        if fallback.disposition is SafetyDisposition.RESTRICT_PRESENTATION and model.disposition is SafetyDisposition.ALLOW:
            return fallback
        return model

    def require_action_allowed(self, item: SafetyInput) -> SemanticSafetyAssessment:
        if not isinstance(item, SafetyInput):
            raise TypeError("action safety gate requires a bounded SafetyInput")
        if item.source in NON_ACTION_SOURCES:
            raise PermissionError("non-action safety sources cannot authorize an action")
        assessment = self.assess(item)
        if assessment.disposition not in {SafetyDisposition.ALLOW, SafetyDisposition.RESTRICT_PRESENTATION}:
            raise PermissionError(f"safety governance did not authorize this action: {assessment.disposition.value}")
        return assessment

    def require_presentation_allowed(self, item: SafetyInput) -> SemanticSafetyAssessment:
        if not isinstance(item, SafetyInput):
            raise TypeError("presentation safety gate requires a bounded SafetyInput")
        if item.source not in PRESENTATION_SOURCES:
            raise PermissionError("presentation safety gate requires a presentation source")
        assessment = self.assess(item)
        if assessment.disposition is not SafetyDisposition.ALLOW:
            raise PermissionError("player-visible output was rejected by safety governance")
        return assessment
