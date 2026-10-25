"""Governed creation of owner-scoped Goals from an explicit host proposal."""
from dataclasses import dataclass, field
from copy import deepcopy
from cognitive_world.cognition.proposal_origin import ProposalOriginMarker, bind_proposal_origin
from cognitive_world.runtime.write_fence import RuntimeWriteFence, RuntimeWritePermit


@dataclass
class GoalCreationProposal:
    owner_id: str
    goal_id: str
    description: str
    priority: float
    source_refs: list[str]
    metadata: dict = field(default_factory=dict)
    runtime_write_permit: RuntimeWritePermit | None = field(default=None, repr=False, compare=False)
    _origin_marker: ProposalOriginMarker = field(default_factory=ProposalOriginMarker, repr=False, compare=False)

    def __post_init__(self):
        self.source_refs = deepcopy(self.source_refs)
        self.metadata = deepcopy(self.metadata)
        if self.runtime_write_permit is None:
            self.runtime_write_permit = RuntimeWriteFence.bind_current_permit()
        bind_proposal_origin(self)
