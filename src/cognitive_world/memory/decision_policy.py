"""Explicit, bounded host policy contract for formal Memory decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
from typing import Protocol


class MemoryDecisionResult(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"


@dataclass(frozen=True)
class MemoryDecisionInput:
    """Immutable proposal-only view supplied to one installed policy call."""

    schema_version: int
    proposal_id: str
    proposal_schema_version: int
    proposal_digest: str
    owner_id: str
    memory_type: str
    proposal_content_json: str
    source_event_ids: tuple[str, ...]
    source_status: str
    timeline_id: str
    session_id: str
    restore_generation: int
    logical_record_id: str
    supersedes_record_id: str | None
    input_digest: str

    def __post_init__(self) -> None:
        if (type(self.schema_version) is not int or self.schema_version != 1
                or type(self.proposal_schema_version) is not int
                or self.proposal_schema_version != 1):
            raise ValueError("unsupported MemoryDecisionInput schema")
        if self.source_status != "event_history_reference_present":
            raise ValueError("MemoryDecisionInput requires a present EventHistory source")
        for value in (
            self.proposal_id, self.proposal_digest, self.owner_id, self.memory_type,
            self.proposal_content_json, self.timeline_id, self.session_id,
            self.input_digest, self.logical_record_id,
        ):
            if not isinstance(value, str) or not value:
                raise ValueError("MemoryDecisionInput contains an empty required value")
        if not isinstance(self.source_event_ids, tuple) or not self.source_event_ids:
            raise ValueError("MemoryDecisionInput requires source Event references")
        if (any(not isinstance(item, str) or not item for item in self.source_event_ids)
                or len(set(self.source_event_ids)) != len(self.source_event_ids)):
            raise ValueError("MemoryDecisionInput source Event references must be unique IDs")
        if (isinstance(self.restore_generation, bool)
                or not isinstance(self.restore_generation, int)
                or self.restore_generation < 0):
            raise ValueError("MemoryDecisionInput restore generation is invalid")
        expected_digest = _digest({
            "schema_version": self.schema_version,
            "proposal_id": self.proposal_id,
            "proposal_schema_version": self.proposal_schema_version,
            "proposal_digest": self.proposal_digest,
            "owner_id": self.owner_id,
            "memory_type": self.memory_type,
            "proposal_content_json": self.proposal_content_json,
            "source_event_ids": list(self.source_event_ids),
            "source_status": self.source_status,
            "timeline_id": self.timeline_id,
            "session_id": self.session_id,
            "restore_generation": self.restore_generation,
            "logical_record_id": self.logical_record_id,
            "supersedes_record_id": self.supersedes_record_id,
        })
        if self.input_digest != expected_digest:
            raise ValueError("MemoryDecisionInput digest does not match its fields")


@dataclass(frozen=True)
class MemoryPolicyOutput:
    """Closed result emitted by an explicitly configured host policy."""

    result: MemoryDecisionResult
    importance: float
    reason_code: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported MemoryPolicyOutput schema")
        if type(self.result) is not MemoryDecisionResult:
            raise TypeError("policy result must be a MemoryDecisionResult")
        if (isinstance(self.importance, bool) or not isinstance(self.importance, (int, float))
                or not 0.0 <= float(self.importance) <= 1.0):
            raise ValueError("policy importance must be a finite value in [0, 1]")
        import math
        if not math.isfinite(float(self.importance)):
            raise ValueError("policy importance must be finite")
        import re
        if (not isinstance(self.reason_code, str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", self.reason_code)):
            raise ValueError("policy reason_code must be a bounded identifier")


class MemoryDecisionPolicy(Protocol):
    """Host-supplied policy. Implementations receive only the bounded input."""

    policy_id: str
    policy_version: str

    def evaluate(self, decision_input: MemoryDecisionInput) -> MemoryPolicyOutput: ...


def build_decision_input(proposal: object, *, timeline_id: str,
                         session_id: str, restore_generation: int) -> MemoryDecisionInput:
    """Build a bounded canonical policy input from one captured proposal."""
    from cognitive_world.cognition.memory_proposal import MemoryProposal

    if type(proposal) is not MemoryProposal:
        raise TypeError("formal Memory decision requires the canonical MemoryProposal")
    content_json = _bounded_json(proposal.content)
    metadata_json = _bounded_json(proposal.metadata)
    proposal_body = {
        "schema_version": 1,
        "proposal_id": proposal.id,
        "source_event_ids": [proposal.source_event_id],
        "owner_id": proposal.owner_id,
        "memory_type": proposal.memory_type,
        "content": json.loads(content_json),
        "importance": _finite_number(proposal.importance, "proposal importance"),
        "confidence": _finite_number(proposal.confidence, "proposal confidence"),
        "metadata": json.loads(metadata_json),
        "logical_record_id": proposal.logical_record_id,
        "supersedes_record_id": proposal.supersedes_record_id,
    }
    proposal_digest = _digest(proposal_body)
    decision_fields = {
        "schema_version": 1,
        "proposal_id": proposal.id,
        "proposal_schema_version": 1,
        "proposal_digest": proposal_digest,
        "owner_id": proposal.owner_id,
        "memory_type": proposal.memory_type,
        "proposal_content_json": content_json,
        "source_event_ids": [proposal.source_event_id],
        "source_status": "event_history_reference_present",
        "timeline_id": timeline_id,
        "session_id": session_id,
        "restore_generation": restore_generation,
        "logical_record_id": proposal.logical_record_id,
        "supersedes_record_id": proposal.supersedes_record_id,
    }
    input_digest = _digest(decision_fields)
    return MemoryDecisionInput(
        schema_version=1,
        proposal_id=proposal.id,
        proposal_schema_version=1,
        proposal_digest=proposal_digest,
        owner_id=proposal.owner_id,
        memory_type=proposal.memory_type,
        proposal_content_json=content_json,
        source_event_ids=(proposal.source_event_id,),
        source_status="event_history_reference_present",
        timeline_id=timeline_id,
        session_id=session_id,
        restore_generation=restore_generation,
        logical_record_id=proposal.logical_record_id,
        supersedes_record_id=proposal.supersedes_record_id,
        input_digest=input_digest,
    )


def proposal_digest(proposal: object) -> str:
    """Return the canonical digest used to detect post-decision mutation."""
    from cognitive_world.cognition.memory_proposal import MemoryProposal

    if type(proposal) is not MemoryProposal:
        raise TypeError("formal Memory decision requires the canonical MemoryProposal")
    return _digest({
        "schema_version": 1,
        "proposal_id": proposal.id,
        "source_event_ids": [proposal.source_event_id],
        "owner_id": proposal.owner_id,
        "memory_type": proposal.memory_type,
        "content": json.loads(_bounded_json(proposal.content)),
        "importance": _finite_number(proposal.importance, "proposal importance"),
        "confidence": _finite_number(proposal.confidence, "proposal confidence"),
        "metadata": json.loads(_bounded_json(proposal.metadata)),
        "logical_record_id": proposal.logical_record_id,
        "supersedes_record_id": proposal.supersedes_record_id,
    })


def validate_decision_input(input_value: MemoryDecisionInput, proposal: object,
                            *, session_id: str, restore_generation: int,
                            timeline_id: str) -> None:
    """Independently compare the strategy input with the captured proposal."""
    from cognitive_world.cognition.memory_proposal import MemoryProposal

    if type(input_value) is not MemoryDecisionInput or type(proposal) is not MemoryProposal:
        raise TypeError("formal Memory decision inputs have unsupported types")
    input_value.__post_init__()
    if (input_value.proposal_id != proposal.id
            or input_value.proposal_digest != proposal_digest(proposal)
            or input_value.owner_id != proposal.owner_id
            or input_value.memory_type != proposal.memory_type
            or input_value.proposal_content_json != _bounded_json(proposal.content)
            or input_value.source_event_ids != (proposal.source_event_id,)
            or input_value.timeline_id != timeline_id
            or input_value.session_id != session_id
            or input_value.restore_generation != restore_generation
            or input_value.logical_record_id != proposal.logical_record_id
            or input_value.supersedes_record_id != proposal.supersedes_record_id):
        raise PermissionError("policy input does not match the captured proposal and Runtime context")


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _bounded_json(value: object) -> str:
    count = 0

    def check(item: object, depth: int = 0) -> object:
        nonlocal count
        count += 1
        if count > 4096 or depth > 24:
            raise ValueError("Memory policy input exceeds structural bounds")
        if item is None or type(item) in (str, bool, int):
            return item
        if type(item) is float:
            if not math.isfinite(item):
                raise ValueError("Memory policy input contains a non-finite number")
            return item
        if isinstance(item, (list, tuple)):
            return [check(child, depth + 1) for child in item]
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise TypeError("Memory policy mappings require string keys")
            return {key: check(child, depth + 1) for key, child in item.items()}
        raise TypeError("Memory policy input contains an unsupported value")

    encoded = json.dumps(check(value), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > 65536:
        raise ValueError("Memory policy input exceeds the byte limit")
    return encoded


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
