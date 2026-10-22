"""Runtime public API with low-level clock imports kept side-effect free.

The clock value type is also used by Resolution for trusted-time validation.
Higher-level orchestration exports are resolved only when requested so that
importing ``runtime.clock`` does not load RuntimeContext, Agent, or Decision.
"""

from importlib import import_module


_EXPORTS = {
    "SimulationClock": ("cognitive_world.runtime.clock", "SimulationClock"),
    "RuntimeContext": ("cognitive_world.runtime.context", "RuntimeContext"),
    "SimulationRuntime": ("cognitive_world.runtime.runtime", "SimulationRuntime"),
    "EventScheduler": ("cognitive_world.runtime.scheduler", "EventScheduler"),
    "ScheduledEvent": ("cognitive_world.runtime.scheduler", "ScheduledEvent"),
    "RuntimeSnapshot": ("cognitive_world.runtime.snapshot", "RuntimeSnapshot"),
    "RuntimeWriteFence": ("cognitive_world.runtime.write_fence", "RuntimeWriteFence"),
    "RuntimeWritePermit": ("cognitive_world.runtime.write_fence", "RuntimeWritePermit"),
    "AgentScheduler": ("cognitive_world.runtime.agent_scheduler", "AgentScheduler"),
    "AutonomousWorldRunner": ("cognitive_world.runtime.autonomous_runner", "AutonomousWorldRunner"),
    "AutonomousWorldReport": ("cognitive_world.runtime.autonomous_runner", "AutonomousWorldReport"),
    "WorldRoundReport": ("cognitive_world.runtime.autonomous_runner", "WorldRoundReport"),
    "AgentActionReport": ("cognitive_world.runtime.autonomous_runner", "AgentActionReport"),
    "ConflictOpportunityScheduler": ("cognitive_world.runtime.conflict_opportunity", "ConflictOpportunityScheduler"),
    "ConflictOpportunityAnalysisProvider": ("cognitive_world.runtime.conflict_opportunity", "ConflictOpportunityAnalysisProvider"),
    "ConflictOpportunityProviderContext": ("cognitive_world.runtime.conflict_opportunity", "ConflictOpportunityProviderContext"),
    "DependencyStrategy": ("cognitive_world.runtime.reconstruction", "DependencyStrategy"),
    "RuntimeDependencyResolution": ("cognitive_world.runtime.reconstruction", "RuntimeDependencyResolution"),
    "RuntimeDependencyManifest": ("cognitive_world.runtime.reconstruction", "RuntimeDependencyManifest"),
    "RuntimeAssemblyInputs": ("cognitive_world.runtime.reconstruction", "RuntimeAssemblyInputs"),
    "RuntimeAssembler": ("cognitive_world.runtime.reconstruction", "RuntimeAssembler"),
    "StagedRuntime": ("cognitive_world.runtime.reconstruction", "StagedRuntime"),
    "RuntimeReconstructionError": ("cognitive_world.runtime.reconstruction", "RuntimeReconstructionError"),
    "IsolatedRuntimeReconstructionFactory": ("cognitive_world.runtime.reconstruction", "IsolatedRuntimeReconstructionFactory"),
    "RestoreState": ("cognitive_world.runtime.recovery", "RestoreState"),
    "RuntimeRestoreError": ("cognitive_world.runtime.recovery", "RuntimeRestoreError"),
    "RuntimePublication": ("cognitive_world.runtime.recovery", "RuntimePublication"),
    "ActiveRuntimeSlot": ("cognitive_world.runtime.recovery", "ActiveRuntimeSlot"),
    "RestoreCoordinator": ("cognitive_world.runtime.recovery", "RestoreCoordinator"),
    "SaveKind": ("cognitive_world.runtime.save_manager", "SaveKind"),
    "SaveMetadata": ("cognitive_world.runtime.save_manager", "SaveMetadata"),
    "VerifiedSave": ("cognitive_world.runtime.save_manager", "VerifiedSave"),
    "SaveError": ("cognitive_world.runtime.save_manager", "SaveError"),
    "SaveCommittedError": ("cognitive_world.runtime.save_manager", "SaveCommittedError"),
    "DependencyTracker": ("cognitive_world.runtime.save_manager", "DependencyTracker"),
    "SaveManager": ("cognitive_world.runtime.save_manager", "SaveManager"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
