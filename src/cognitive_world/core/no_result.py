"""Closed result-layer contract for an interaction with no confirmed result."""

from dataclasses import dataclass, field
from enum import Enum
import re

_NO_RESULT_SEAL = object()


class NoResultReason(str, Enum):
    """Distinct no-result outcomes; each is issued by its owning result boundary."""

    UNPARSEABLE_INPUT = "unparseable_input"
    CLARIFICATION_REQUIRED = "clarification_required"
    UNRESOLVED_ATTEMPT = "unresolved_attempt"
    NPC_REASONING_UNAVAILABLE = "npc_reasoning_unavailable"
    TECHNICAL_FAILURE = "technical_failure"
    CANDIDATES_REJECTED = "candidates_rejected"
    RETRIES_EXHAUSTED = "retries_exhausted"


@dataclass(frozen=True)
class NoResultState:
    """Result-layer state; direct construction does not establish its provenance."""

    request_id: str
    reason: NoResultReason
    input_fingerprint: str
    _seal: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id or len(self.request_id) > 128:
            raise ValueError("no-result request identity must be bounded")
        if not isinstance(self.reason, NoResultReason):
            raise TypeError("no-result reason must use the explicit protocol")
        if not isinstance(self.input_fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", self.input_fingerprint) is None:
            raise ValueError("no-result input fingerprint must be SHA-256 hex")

    def _snapshot(self) -> tuple[str, NoResultReason, str]:
        return self.request_id, self.reason, self.input_fingerprint

    def has_trusted_result_origin(self) -> bool:
        return self._seal is _NO_RESULT_SEAL


def _issue_no_result_state(
    request_id: str, reason: NoResultReason, input_fingerprint: str,
) -> NoResultState:
    """Internal issuer used after a trusted interaction boundary fixes a no-result."""
    return NoResultState(request_id, reason, input_fingerprint, _NO_RESULT_SEAL)
