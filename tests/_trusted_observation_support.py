"""Test-only construction of observations from a controlled fixture boundary.

This helper is intentionally absent from the production package and must not
be used by application code as an authorization mechanism.
"""

from copy import deepcopy

from cognitive_world.observation.observation import (
    Observation,
    _OBSERVATION_RECEIPT_SEAL,
    _ObservationProvenance,
)


def make_trusted_observation(
    observation_id: str,
    observer_id: str,
    source_event_id: str,
    content,
    metadata=None,
    *,
    context_fingerprint: str = "test:event-time-context",
) -> Observation:
    """Create a signed fixture tied to a non-empty test context reference."""
    observation = Observation(
        observation_id,
        observer_id,
        source_event_id,
        content,
        {} if metadata is None else metadata,
    )
    object.__setattr__(
        observation,
        "_provenance",
        _ObservationProvenance(
            seal=_OBSERVATION_RECEIPT_SEAL,
            snapshot=deepcopy(observation._snapshot()),
            context_fingerprint=context_fingerprint,
        ),
    )
    return observation
