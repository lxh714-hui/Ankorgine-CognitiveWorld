"""Opt-in Runtime orchestration from owner-scoped development signals to content.

This module coordinates existing proposal validation and installation. It does
not own a content store, world state, or alternate scenario lifecycle.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from cognitive_world.decision.autonomous import ConflictOpportunityCandidate
from cognitive_world.runtime.conflict_opportunity import ConflictOpportunityScheduler

from .installation import ContentInstallationRecord, RuntimeContentInstaller, installation_record_key
from cognitive_world.event.history import EventProcessingStatus
from .llm import ContentGenerationRequest
from .runtime import ScenarioLifecycle


@dataclass(frozen=True)
class ContentExpansionNeed:
    """A non-authoritative, source-linked reason to consider reusable content."""

    finding_id: str
    owner_id: str
    kind: str
    source_refs: tuple[tuple[str, str], ...]
    importance: float
    relevance: float
    uncertainties: tuple[str, ...]
    simulation_tick: int

    def __post_init__(self) -> None:
        for name in ("finding_id", "owner_id", "kind"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or len(value) > 200:
                raise ValueError(f"{name} must be bounded and non-empty")
        if not isinstance(self.source_refs, tuple) or len(self.source_refs) > 16:
            raise ValueError("content need source references exceed their bound")
        if any(type(item) is not tuple or len(item) != 2 or
               any(not isinstance(part, str) or not part or len(part) > 1000 for part in item)
               for item in self.source_refs):
            raise TypeError("content need sources must be immutable typed reference pairs")
        if not isinstance(self.uncertainties, tuple) or len(self.uncertainties) > 16 or any(
            not isinstance(item, str) or not item or len(item) > 1000 for item in self.uncertainties
        ):
            raise ValueError("content need uncertainties exceed their bound")
        for name in ("importance", "relevance"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0,1]")
        if isinstance(self.simulation_tick, bool) or not isinstance(self.simulation_tick, int) or self.simulation_tick < 0:
            raise ValueError("content need requires a non-negative simulation tick")


class ContentNeedPolicy(Protocol):
    """Decide whether a scheduler finding warrants a bounded content brief."""

    def request_for(self, need: ContentExpansionNeed) -> ContentGenerationRequest | None: ...


class ContentGeneratorFactory(Protocol):
    """Create the existing generator abstraction for one approved brief."""

    def __call__(self, request: ContentGenerationRequest) -> object: ...


@dataclass(frozen=True)
class ContentExpansionResult:
    finding_id: str
    status: str
    instance_id: str | None = None
    failure_type: str | None = None


class ProactiveContentExpansion:
    """Use one committed, scheduler-issued finding per tick to drive content.

    The host must explicitly inject both a need policy and a generator factory.
    The factory may adapt ``ContentGenerator``/``LLMContentGenerator``; no
    provider or endpoint is selected or invoked by default.
    """

    def __init__(self, installer: RuntimeContentInstaller,
                 lifecycle: ScenarioLifecycle, *, world_id: str,
                 scheduler: ConflictOpportunityScheduler,
                 need_policy: ContentNeedPolicy,
                 generator_factory: ContentGeneratorFactory) -> None:
        if type(installer) is not RuntimeContentInstaller or type(lifecycle) is not ScenarioLifecycle:
            raise TypeError("content expansion requires the canonical installer and scenario lifecycle")
        if lifecycle.context is not installer.context or lifecycle.processor is not installer.processor:
            raise ValueError("content expansion authorities must share one Runtime and EventProcessor")
        if lifecycle.context.agent_scheduler is None:
            raise ValueError("content expansion requires the Runtime AgentScheduler")
        if type(scheduler) is not ConflictOpportunityScheduler:
            raise TypeError("content expansion requires the canonical Runtime scheduler")
        if not isinstance(world_id, str) or not world_id or len(world_id) > 160:
            raise ValueError("content expansion requires a bounded world ID")
        if not callable(getattr(need_policy, "request_for", None)) or not callable(generator_factory):
            raise TypeError("content expansion requires an explicit need policy and generator factory")
        self.installer = installer
        self.lifecycle = lifecycle
        self.world_id = world_id
        self.scheduler = scheduler
        self.need_policy = need_policy
        self.generator_factory = generator_factory
        self._last_tick: int | None = None
        self._last_results: tuple[ContentExpansionResult, ...] = ()

    def expand(self, findings: tuple[ConflictOpportunityCandidate, ...], *,
               simulation_tick: int) -> tuple[ContentExpansionResult, ...]:
        """Evaluate a bounded batch of findings issued by this Runtime scheduler.

        At most one proposal/install is attempted per simulation tick. A finding
        is accepted only by object identity from the scheduler's current owner
        result, so a manually reconstructed DTO is not treated as an issued
        development signal.
        """
        if (isinstance(simulation_tick, bool) or not isinstance(simulation_tick, int)
                or simulation_tick < 0):
            raise ValueError("content expansion requires the trusted scheduler tick")
        if not isinstance(findings, tuple) or len(findings) > 8:
            raise ValueError("content expansion finding batch exceeds its bound")
        if any(type(item) is not ConflictOpportunityCandidate for item in findings):
            raise TypeError("content demand must come from a typed scheduler finding")
        for finding in findings:
            issued = self.scheduler.current_for(finding.owner_id, simulation_tick)
            if not any(item is finding for item in issued):
                raise PermissionError("content expansion finding was not issued for this owner and tick")
        if self._last_tick == simulation_tick:
            return self._last_results
        self._last_tick = simulation_tick
        results: list[ContentExpansionResult] = []
        ranked = sorted(findings, key=lambda item: (-item.importance, -item.relevance, item.finding_id))
        for finding in ranked:
            if finding.lifecycle != "active" or finding.last_seen_tick != simulation_tick:
                results.append(ContentExpansionResult(finding.finding_id, "stale_signal"))
                continue

            instance_id = self._instance_id(self.world_id, finding.finding_id)
            key = installation_record_key(self.world_id, instance_id)
            existing = self.installer.context.world_state.facts.get(key)
            if existing is not None:
                status = self._existing_status(existing)
                results.append(ContentExpansionResult(finding.finding_id, status, instance_id))
                if status != "already_installed":
                    break
                continue

            need = ContentExpansionNeed(
                finding.finding_id, finding.owner_id, finding.kind,
                tuple((item.reference_type, item.reference_id) for item in finding.source_refs),
                finding.importance, finding.relevance, finding.uncertainties,
                simulation_tick,
            )
            try:
                request = self.need_policy.request_for(need)
                if request is None:
                    results.append(ContentExpansionResult(finding.finding_id, "no_content_need"))
                    continue
                if type(request) is not ContentGenerationRequest:
                    raise TypeError("content need policy must return ContentGenerationRequest or None")
                generator = self.generator_factory(request)
                if not callable(getattr(generator, "generate", None)):
                    raise TypeError("content generator factory returned an invalid generator")
                proposal = generator.generate()
                if len(proposal.scenarios) != 1:
                    raise ValueError("one runtime content demand must select exactly one ScenarioTemplate")
                template_id = proposal.scenarios[0].template_id
                reuse = self.installer.registry.matches_registered(proposal)
                if self.installer.registry.conflicts_with_registered(proposal):
                    raise ValueError("generated template identity conflicts with registered content")
                if reuse:
                    instance = self.installer.install_registered(
                        template_id, instance_id, self.world_id,
                        source_id=f"scheduler-finding:{finding.finding_id}",
                        source_refs=need.source_refs,
                    )
                    status = "installed_reused_templates"
                else:
                    instance = self.installer.install_proposal(
                        proposal, template_id=template_id, instance_id=instance_id,
                        world_id=self.world_id,
                        source_id=f"scheduler-finding:{finding.finding_id}",
                        source_refs=need.source_refs,
                    )
                    status = "installed_new_templates"
                self.lifecycle.register(instance)
                results.append(ContentExpansionResult(finding.finding_id, status, instance_id))
                # One demand may install one scenario only in a tick.
                break
            except Exception as error:
                existing = self.installer.context.world_state.facts.get(key)
                status = "rejected" if existing is None else self._existing_status(existing)
                if status == "already_installed":
                    # A later orchestration failure is not a successful caller result.
                    status = "recovery_required"
                results.append(ContentExpansionResult(
                    finding.finding_id, status,
                    instance_id if existing is not None else None,
                    type(error).__name__,
                ))
                break
        self._last_results = tuple(results)
        return self._last_results

    def _existing_status(self, record: object) -> str:
        if type(record) is not ContentInstallationRecord or record.status != "ready":
            return "recovery_required"
        history = self.installer.context.event_history
        event = history.get_event(record.completion_event_id)
        evidence = history.get_processing_evidence(record.completion_event_id)
        if (history.requires_recovery() or event is None or evidence is None
                or event.type != "runtime_content_ready" or not event.has_trusted_source("system")
                or not evidence.has_trusted_source(event)
                or event.changes != [{"world_id": record.world_id, "instance_id": record.instance_id,
                                      "template_id": record.template_id}]):
            return "recovery_required"
        status = history.get_processing_status(event.id)
        if status is EventProcessingStatus.COMPLETE:
            return "already_installed"
        if status in (EventProcessingStatus.RECORDED, EventProcessingStatus.OBSERVATIONS_PENDING):
            return "observations_pending"
        return "recovery_required"

    @staticmethod
    def _instance_id(world_id: str, finding_id: str) -> str:
        digest = sha256(f"{world_id}\0{finding_id}".encode("utf-8")).hexdigest()[:32]
        return f"proactive-{digest}"
