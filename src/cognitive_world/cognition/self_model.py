"""Agent self-model data and owner-isolated storage."""

from copy import deepcopy
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any
from cognitive_world.cognition.proposal_origin import original_proposal_permit
from cognitive_world.runtime.write_fence import RuntimeWriteFence


@dataclass
class SelfModel:
    """Represent an Agent's beliefs about its identity and own state."""

    owner_id: str
    identity: Any = None
    capabilities: Any = field(default_factory=dict)
    limitations: Any = field(default_factory=dict)
    self_beliefs: Any = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.identity = deepcopy(self.identity)
        self.capabilities = deepcopy(self.capabilities)
        self.limitations = deepcopy(self.limitations)
        self.self_beliefs = deepcopy(self.self_beliefs)
        self.metadata = deepcopy(self.metadata)


@dataclass
class SelfModelStore:
    """Store one isolated SelfModel snapshot per Agent owner."""

    _self_models: dict[str, SelfModel] = field(default_factory=dict, repr=False)
    write_fence: RuntimeWriteFence | None = field(default=None, repr=False, compare=False)

    def bind_write_fence(self, fence: RuntimeWriteFence) -> None:
        if self.write_fence is not None and self.write_fence is not fence:
            raise ValueError("SelfModelStore is already bound to another runtime fence")
        self.write_fence = fence

    def add(self, self_model: SelfModel) -> None:
        """Register trusted initial SelfModel configuration exactly once."""
        scope = nullcontext() if self.write_fence is None else self.write_fence.commit_scope()
        with scope:
            self._add(self_model)

    def _add(self, self_model: SelfModel) -> None:
        if not isinstance(self_model, SelfModel):
            raise TypeError("self_model must be a SelfModel")
        if self_model.owner_id in self._self_models:
            raise ValueError("SelfModel already exists; use governed update")
        self._self_models[self_model.owner_id] = deepcopy(self_model)

    def get(self, owner_id: str) -> SelfModel | None:
        """Return an isolated SelfModel copy for an Agent, if present."""
        self_model = self._self_models.get(owner_id)
        return deepcopy(self_model) if self_model is not None else None

    def get_all(self) -> tuple[SelfModel, ...]:
        """Return isolated copies of every stored SelfModel."""
        return tuple(deepcopy(tuple(self._self_models.values())))

    def update(self, self_model: SelfModel, *, proposal: Any = None, validation_result: Any = None) -> None:
        """Replace only through a matching governed evolution proposal."""
        scope = nullcontext() if self.write_fence is None else self.write_fence.commit_scope()
        with scope:
            if self.write_fence is not None:
                self.write_fence.require_candidate_origin(
                    original_proposal_permit(proposal)
                )
            self._update(self_model, proposal=proposal, validation_result=validation_result)

    def _update(self, self_model: SelfModel, *, proposal: Any, validation_result: Any) -> None:
        if not isinstance(self_model, SelfModel):
            raise TypeError("self_model must be a SelfModel")
        from cognitive_world.cognition.self_model_evolution import SelfModelUpdateProposal
        from cognitive_world.cognition.validation import ValidationResult

        if not isinstance(proposal, SelfModelUpdateProposal) or not isinstance(validation_result, ValidationResult) or not validation_result.authorizes(proposal):
            raise PermissionError("SelfModel updates require matching validator authorization")
        current = self._self_models.get(proposal.owner_id)
        if current is None or self_model.owner_id != proposal.owner_id:
            raise PermissionError("SelfModel update owner is missing or mismatched")
        if tuple(current.self_beliefs) != proposal.previous_self_beliefs:
            raise ValueError("SelfModel changed after proposal validation")
        if self_model.identity != current.identity or self_model.capabilities != current.capabilities or self_model.limitations != current.limitations or self_model.metadata != current.metadata:
            raise PermissionError("governed SelfModel evolution may only update self-beliefs")
        if tuple(self_model.self_beliefs[:-1]) != tuple(current.self_beliefs):
            raise PermissionError("SelfModel proposal must preserve existing self-beliefs")
        added = self_model.self_beliefs[-1] if self_model.self_beliefs else None
        expected_sources = {
            "claim": proposal.claim,
            "status": "tentative",
            "source_refs": list(proposal.source_refs),
            "source_event_ids": list(proposal.source_event_ids),
        }
        if added != expected_sources or any(
            ref in set(proposal.source_refs)
            for existing in current.self_beliefs
            if isinstance(existing, dict)
            for ref in existing.get("source_refs", ())
        ):
            raise PermissionError("SelfModel update is not a new tentative evidence-bound claim")
        self._self_models[self_model.owner_id] = deepcopy(self_model)
