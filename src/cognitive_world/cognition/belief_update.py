"""Non-mutating proposals for caller-supplied Belief updates."""

from copy import deepcopy
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from cognitive_world.cognition.belief import Belief
from cognitive_world.cognition.proposal_origin import ProposalOriginMarker, bind_proposal_origin
from cognitive_world.runtime.write_fence import RuntimeWriteFence, RuntimeWritePermit


@dataclass
class BeliefChange:
    """Describe one traceable candidate change to a Belief value."""

    operation: str
    previous_value: Any
    proposed_value: Any
    reason: str
    evidence_refs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.previous_value = deepcopy(self.previous_value)
        self.proposed_value = deepcopy(self.proposed_value)
        self.evidence_refs = deepcopy(self.evidence_refs)


@dataclass
class BeliefUpdateProposal:
    """Describe a proposed Belief update without applying it."""

    owner_id: str
    belief_id: str
    change: BeliefChange
    source_refs: list[str] = field(default_factory=list)
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    runtime_write_permit: RuntimeWritePermit | None = field(
        default=None, repr=False, compare=False
    )
    _origin_marker: ProposalOriginMarker = field(
        default_factory=ProposalOriginMarker, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.runtime_write_permit is None:
            object.__setattr__(self, "runtime_write_permit", RuntimeWriteFence.bind_current_permit())
        self.change = deepcopy(self.change)
        self.source_refs = deepcopy(self.source_refs)
        self.metadata = deepcopy(self.metadata)
        bind_proposal_origin(self)


@dataclass
class BeliefUpdater:
    """Build a proposal from a Belief and explicit caller-supplied values."""

    def propose_update(
        self, belief: Belief, cognition_context: Any
    ) -> BeliefUpdateProposal:
        """Return a detached proposal; never update the Belief or its Store.

        A mapping may explicitly provide ``new_value``, ``operation``,
        ``reason``, ``evidence_refs``, ``source_refs``, ``confidence``, and
        ``metadata``. Missing values retain the current Belief snapshot; this
        boundary performs no inference.
        """
        if not isinstance(belief, Belief):
            raise TypeError("belief must be a Belief")

        supplied = cognition_context if isinstance(cognition_context, Mapping) else {}
        source_refs = deepcopy(supplied.get("source_refs", belief.source_refs))
        change = BeliefChange(
            operation=supplied.get("operation", "replace"),
            previous_value=deepcopy(supplied.get("previous_value", belief.content)),
            proposed_value=deepcopy(supplied.get("new_value", belief.content)),
            reason=supplied.get("reason", "proposed from cognition context"),
            evidence_refs=deepcopy(supplied.get("evidence_refs", source_refs)),
        )
        return BeliefUpdateProposal(
            owner_id=belief.owner_id,
            belief_id=belief.belief_id,
            change=change,
            source_refs=source_refs,
            confidence=supplied.get("confidence", belief.confidence),
            metadata=deepcopy(supplied.get("metadata", {})),
        )
