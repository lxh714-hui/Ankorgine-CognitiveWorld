"""Observation data model for information available to an observer."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


class _ObservationReceiptSeal:
    """Process-local marker used only by the controlled observation boundary."""

    def __deepcopy__(self, memo: dict[int, Any]) -> "_ObservationReceiptSeal":
        return self


_OBSERVATION_RECEIPT_SEAL = _ObservationReceiptSeal()


@dataclass(frozen=True)
class _ObservationProvenance:
    """Private receipt; ordinary Observation construction never creates one."""

    seal: _ObservationReceiptSeal = field(repr=False, compare=False)
    snapshot: tuple[Any, ...] = field(repr=False)
    context_fingerprint: str
    source_timeline_id: str | None = None
    source_runtime_session_id: str | None = None
    source_runtime_generation: int | None = None


@dataclass
class Observation:
    """Represent information obtained by a particular observer."""

    observation_id: str
    observer_id: str
    source_event_id: str
    content: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    _provenance: _ObservationProvenance | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def has_trusted_provenance(self) -> bool:
        """Return whether a controlled receipt still matches this exact payload.

        ObservationStore deliberately does not call this method to authorize
        records. Consumers must check it when using an Observation.
        """
        receipt = self._provenance
        if (
            not isinstance(receipt, _ObservationProvenance)
            or receipt.seal is not _OBSERVATION_RECEIPT_SEAL
            or not receipt.context_fingerprint
        ):
            return False
        try:
            return receipt.snapshot == self._snapshot()
        except Exception:
            return False

    def trusted_source_timeline_id(self) -> str | None:
        """Return the issuer-bound Timeline only while this payload is intact."""
        if not self.has_trusted_provenance():
            return None
        receipt = self._provenance
        value = receipt.source_timeline_id
        return value if isinstance(value, str) and value else None

    def trusted_source_runtime_binding(self) -> tuple[str, int] | None:
        """Return the issuing Runtime generation while the receipt is intact."""
        if not self.has_trusted_provenance():
            return None
        receipt = self._provenance
        session_id = receipt.source_runtime_session_id
        generation = receipt.source_runtime_generation
        if (not isinstance(session_id, str) or not session_id
                or type(generation) is not int or generation < 0):
            return None
        return session_id, generation

    def _snapshot(self) -> tuple[Any, ...]:
        return deepcopy(
            (
                self.observation_id,
                self.observer_id,
                self.source_event_id,
                self.content,
                self.metadata,
            )
        )
