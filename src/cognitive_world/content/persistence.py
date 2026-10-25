"""Explicit persistence types for the bounded Scenario runtime contract."""

from cognitive_world.cognition.snapshot import cognitive_snapshot_codec
from cognitive_world.core.persistence import PersistedValueCodec

from .runtime import ScenarioPhase, ScenarioRuntimeState
from .installation import ContentInstallationRecord, WorldContentBatch


def scenario_snapshot_codec() -> PersistedValueCodec:
    """Extend the canonical snapshot allow-list with typed Scenario state."""
    codec = cognitive_snapshot_codec()
    codec.register_type(ScenarioPhase)
    codec.register_type(ScenarioRuntimeState)
    codec.register_type(ContentInstallationRecord)
    codec.register_type(WorldContentBatch)
    return codec
