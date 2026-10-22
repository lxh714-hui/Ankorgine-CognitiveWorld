"""Belief data model and owner-isolated storage for the cognition layer."""

from copy import deepcopy
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any
from cognitive_world.cognition.proposal_origin import original_proposal_permit
from cognitive_world.runtime.write_fence import RuntimeWriteFence


@dataclass(init=False)
class Belief:
    """Represent an Agent's subjective judgement about the world or self."""

    belief_id: str
    owner_id: str
    content: Any
    source_refs: list[str]
    confidence: float
    metadata: dict[str, Any]

    def __init__(
        self,
        belief_id: str | None = None,
        owner_id: str = "",
        content: Any = None,
        source_refs: list[str] | float | None = None,
        confidence: float | str = 0.0,
        metadata: dict[str, Any] | None = None,
        *,
        id: str | None = None,
        source: str | None = None,
    ) -> None:
        """Initialize a Belief, accepting the former ``id``/``source`` fields."""
        if isinstance(source_refs, (int, float)) and isinstance(confidence, str):
            # Former positional form: Belief(id, owner_id, content, confidence, source).
            source_refs, confidence = [confidence], float(source_refs)
        elif source_refs is None:
            source_refs = [] if source is None else [source]

        self.belief_id = belief_id if belief_id is not None else (id or "")
        self.owner_id = owner_id
        self.content = deepcopy(content)
        self.source_refs = deepcopy(list(source_refs))
        self.confidence = float(confidence)
        self.metadata = deepcopy(metadata if metadata is not None else {})

    @property
    def id(self) -> str:
        """Compatibility alias for ``belief_id`` used by CognitionContainer."""
        return self.belief_id

    @property
    def source(self) -> str:
        """Compatibility view of the first source reference, if present."""
        return self.source_refs[0] if self.source_refs else ""


@dataclass
class BeliefStore:
    """Unique isolated store for Belief records, indexed by Belief ID."""

    _beliefs: dict[str, Belief] = field(default_factory=dict, repr=False)
    write_fence: RuntimeWriteFence | None = field(default=None, repr=False, compare=False)

    def bind_write_fence(self, fence: RuntimeWriteFence) -> None:
        if self.write_fence is not None and self.write_fence is not fence:
            raise ValueError("BeliefStore is already bound to another runtime fence")
        self.write_fence = fence

    def add(self, belief: Belief) -> None:
        """Register an initial Belief; existing records require validated updates."""
        scope = nullcontext() if self.write_fence is None else self.write_fence.commit_scope()
        with scope:
            self._add(belief)

    def _add(self, belief: Belief) -> None:
        if not isinstance(belief, Belief):
            raise TypeError("belief must be a Belief")
        if belief.belief_id in self._beliefs:
            raise ValueError("Belief already exists; use a validated update")
        self._beliefs[belief.belief_id] = deepcopy(belief)

    def get(self, owner_id: str) -> Belief | None:
        """Return the most recently added Belief for an owner (legacy API)."""
        belief = next(
            (
                item
                for item in reversed(tuple(self._beliefs.values()))
                if item.owner_id == owner_id
            ),
            None,
        )
        return deepcopy(belief) if belief is not None else None

    def get_by_id(self, belief_id: str) -> Belief | None:
        """Return an isolated Belief copy by its unique identifier."""
        belief = self._beliefs.get(belief_id)
        return deepcopy(belief) if belief is not None else None

    def get_by_owner(self, owner_id: str) -> tuple[Belief, ...]:
        """Return isolated Belief copies belonging to one Agent."""
        return tuple(
            deepcopy(belief)
            for belief in self._beliefs.values()
            if belief.owner_id == owner_id
        )

    def get_all(self) -> tuple[Belief, ...]:
        """Return isolated copies of every Belief in insertion order."""
        return tuple(deepcopy(tuple(self._beliefs.values())))

    def update(
        self,
        belief: Belief,
        *,
        proposal: Any = None,
        validation_result: Any = None,
    ) -> None:
        """Apply only a Belief snapshot authorized by its validated proposal."""
        scope = nullcontext() if self.write_fence is None else self.write_fence.commit_scope()
        with scope:
            if self.write_fence is not None:
                self.write_fence.require_candidate_origin(
                    original_proposal_permit(proposal)
                )
            self._update(belief, proposal=proposal, validation_result=validation_result)

    def _update(self, belief: Belief, *, proposal: Any, validation_result: Any) -> None:
        from cognitive_world.cognition.belief_update import BeliefUpdateProposal
        from cognitive_world.cognition.validation import ValidationResult

        if not isinstance(belief, Belief):
            raise TypeError("belief must be a Belief")
        if (
            not isinstance(proposal, BeliefUpdateProposal)
            or not isinstance(validation_result, ValidationResult)
            or not validation_result.authorizes(proposal)
        ):
            raise PermissionError("Belief updates require a matching accepted validation")
        current = self._beliefs.get(proposal.belief_id)
        expected_metadata = {} if current is None else deepcopy(current.metadata)
        expected_metadata.update(deepcopy(proposal.metadata))
        if (
            proposal.owner_id != belief.owner_id
            or proposal.belief_id != belief.belief_id
            or current is None
            or current.owner_id != proposal.owner_id
            or current.content != proposal.change.previous_value
            or proposal.change.proposed_value != belief.content
            or proposal.source_refs != belief.source_refs
            or proposal.confidence != belief.confidence
            or expected_metadata != belief.metadata
        ):
            raise ValueError("Belief does not match its validated proposal")
        owned = [
            belief_id
            for belief_id, existing in self._beliefs.items()
            if existing.owner_id == belief.owner_id
        ]
        if len(owned) == 1 and owned[0] != belief.belief_id:
            del self._beliefs[owned[0]]
        self._beliefs[belief.belief_id] = deepcopy(belief)
