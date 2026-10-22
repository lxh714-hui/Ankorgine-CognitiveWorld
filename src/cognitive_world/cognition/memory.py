"""Memory data model for the cognition layer."""

from dataclasses import dataclass, field
import re
from typing import Any


class SystemOnlyMemoryContent:
    """Marker for canonical system records excluded from semantic retrieval.

    This marker describes a record's visibility boundary, not permission to
    create or persist it. Trusted Store paths still govern system-record writes.
    """


@dataclass(frozen=True)
class MemoryDecisionProvenance:
    """Versioned shape reserved for D3 decision provenance.

    Snapshot signatures bind these fields but do not prove that a policy call
    occurred or grant permission to write. D3 must validate the issuance path.
    """

    schema_version: int
    decision_id: str
    policy_id: str
    policy_version: str
    proposal_id: str
    proposal_digest: str
    input_digest: str
    reason_code: str
    owner_id: str
    source_event_ids: tuple[str, ...]
    timeline_id: str
    session_id: str
    restore_generation: int
    supersedes_record_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported MemoryDecisionProvenance schema")
        for name in (
            "decision_id", "policy_id", "policy_version", "proposal_id",
            "owner_id", "timeline_id", "session_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty")
        for name in ("proposal_digest", "input_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        if (not isinstance(self.reason_code, str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", self.reason_code)):
            raise ValueError("reason_code is not a bounded reason identifier")
        if (not isinstance(self.source_event_ids, tuple) or not self.source_event_ids
                or any(not isinstance(item, str) or not item for item in self.source_event_ids)
                or len(set(self.source_event_ids)) != len(self.source_event_ids)):
            raise ValueError("source_event_ids must be unique non-empty IDs")
        if not isinstance(self.reason_code, str):
            raise ValueError("reason_code must be a bounded reason identifier")
        if (isinstance(self.restore_generation, bool)
                or not isinstance(self.restore_generation, int)
                or self.restore_generation < 0):
            raise ValueError("restore_generation must be non-negative")
        if self.supersedes_record_id is not None and (
            not isinstance(self.supersedes_record_id, str) or not self.supersedes_record_id
        ):
            raise ValueError("supersedes_record_id must be a non-empty ID or None")


@dataclass(frozen=True)
class MemoryDecisionProvenanceV2:
    """Accepted policy-call evidence used by new formal Memory/v2 writes.

    This is data carried by a record, not a capability. Runtime authorization
    is checked separately at the final Store boundary.
    """

    schema_version: int
    decision_id: str
    policy_id: str
    policy_version: str
    proposal_id: str
    proposal_digest: str
    input_digest: str
    reason_code: str
    owner_id: str
    source_event_ids: tuple[str, ...]
    timeline_id: str
    session_id: str
    restore_generation: int
    supersedes_record_id: str | None = None
    outcome: str = "accepted"

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 2:
            raise ValueError("unsupported MemoryDecisionProvenance schema")
        if self.outcome != "accepted":
            raise ValueError("only accepted policy decisions can be persisted")
        if (type(self.source_event_ids) is not tuple or not self.source_event_ids
                or len(set(self.source_event_ids)) != len(self.source_event_ids)):
            raise ValueError("formal provenance requires source Event identities")
        if any(not isinstance(item, str) or not item for item in self.source_event_ids):
            raise ValueError("formal provenance source Event identities are invalid")
        if (not isinstance(self.restore_generation, int)
                or isinstance(self.restore_generation, bool) or self.restore_generation < 0):
            raise ValueError("formal provenance restore generation is invalid")
        if (not isinstance(self.proposal_digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", self.proposal_digest)
                or not isinstance(self.input_digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", self.input_digest)):
            raise ValueError("formal provenance digests must be lowercase SHA-256")
        for name in ("decision_id", "policy_id", "policy_version", "proposal_id",
                     "reason_code", "owner_id", "timeline_id", "session_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"formal provenance {name} must be non-empty")
        if self.supersedes_record_id is not None and (
            not isinstance(self.supersedes_record_id, str) or not self.supersedes_record_id
        ):
            raise ValueError("formal provenance predecessor must be non-empty or None")


@dataclass
class Memory:
    """A structured record of an owner's experience."""

    id: str
    owner_id: str
    type: str
    content: Any
    importance: float
    source_event: str
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1
    decision_provenance: MemoryDecisionProvenance | None = None
    logical_record_id: str | None = None
    supersedes_record_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int:
            raise TypeError("Memory schema_version must be an integer")
        if self.schema_version == 1:
            if (self.decision_provenance is not None or self.logical_record_id is not None
                    or self.supersedes_record_id is not None):
                raise ValueError("Memory/v1 cannot carry D3 provenance or revision links")
        elif self.schema_version == 2:
            if type(self.decision_provenance) not in {
                MemoryDecisionProvenance, MemoryDecisionProvenanceV2,
            }:
                raise ValueError("Memory/v2 requires typed decision provenance")
            if self.decision_provenance.owner_id != self.owner_id:
                raise ValueError("Memory decision provenance owner mismatch")
            if self.source_event not in self.decision_provenance.source_event_ids:
                raise ValueError("Memory source Event is absent from decision provenance")
            if self.decision_provenance.supersedes_record_id != self.supersedes_record_id:
                raise ValueError("Memory revision link differs from decision provenance")
            if (not isinstance(self.id, str) or not self.id
                    or not isinstance(self.logical_record_id, str) or not self.logical_record_id
                    or not isinstance(self.supersedes_record_id, (str, type(None)))
                    or self.supersedes_record_id == self.id):
                raise ValueError("Memory/v2 requires revision and logical identities plus a valid predecessor reference")
        else:
            raise ValueError("unsupported Memory schema version")
