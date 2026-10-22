"""Resolution public API with the causal policy slice loaded on demand.

Core result/engine types stay available without pulling in Runtime or
Agent orchestration through the optional causal implementation.
"""

from importlib import import_module

from cognitive_world.resolution.engine import ResolutionDecision, ResolutionEngine
from cognitive_world.resolution.result import ResolutionResult


_LAZY_EXPORTS = {
    "ActionResolutionFlow": ("cognitive_world.resolution.action_flow", "ActionResolutionFlow"),
    "ActionInterpreter": ("cognitive_world.resolution.causal", "ActionInterpreter"),
    "ActionInterpretationProvider": ("cognitive_world.resolution.causal", "ActionInterpretationProvider"),
    "AssessmentStatus": ("cognitive_world.resolution.causal", "AssessmentStatus"),
    "CausalAssessment": ("cognitive_world.resolution.causal", "CausalAssessment"),
    "PhysicalEffectProposal": ("cognitive_world.resolution.causal", "PhysicalEffectProposal"),
    "EffectParticipant": ("cognitive_world.resolution.causal", "EffectParticipant"),
    "SuggestedPhysicalChange": ("cognitive_world.resolution.causal", "SuggestedPhysicalChange"),
    "PhysicalEffectSuggestion": ("cognitive_world.resolution.causal", "PhysicalEffectSuggestion"),
    "PhysicalEffectSuggestionProvider": ("cognitive_world.resolution.causal", "PhysicalEffectSuggestionProvider"),
    "PhysicalEffectTranslation": ("cognitive_world.resolution.causal", "PhysicalEffectTranslation"),
    "SupportedPhysicalEffectTranslator": ("cognitive_world.resolution.causal", "SupportedPhysicalEffectTranslator"),
    "OllamaPhysicalEffectSuggestionProvider": ("cognitive_world.resolution.providers", "OllamaPhysicalEffectSuggestionProvider"),
    "CausalAssessmentPolicy": ("cognitive_world.resolution.causal", "CausalAssessmentPolicy"),
    "CausalWorldContext": ("cognitive_world.resolution.causal", "CausalWorldContext"),
    "CognitiveInteractionView": ("cognitive_world.resolution.interaction_context", "CognitiveInteractionView"),
    "InteractionStateAggregate": ("cognitive_world.resolution.interaction_context", "InteractionStateAggregate"),
    "InteractionStateAggregator": ("cognitive_world.resolution.interaction_context", "InteractionStateAggregator"),
    "CausalReasoningProvider": ("cognitive_world.resolution.causal", "CausalReasoningProvider"),
    "CausalReasoningAdvice": ("cognitive_world.resolution.causal", "CausalReasoningAdvice"),
    "OpenAICompatibleCausalProvider": ("cognitive_world.resolution.providers", "OpenAICompatibleCausalProvider"),
    "DoorCausalAssessmentPolicy": ("cognitive_world.resolution.causal", "DoorCausalAssessmentPolicy"),
    "PassageCausalAssessmentPolicy": ("cognitive_world.resolution.causal", "PassageCausalAssessmentPolicy"),
    "CompositeCausalAssessmentPolicy": ("cognitive_world.resolution.causal", "CompositeCausalAssessmentPolicy"),
    "MethodBasedResolutionEngine": ("cognitive_world.resolution.causal", "MethodBasedResolutionEngine"),
    "PlannedStep": ("cognitive_world.resolution.stepwise", "PlannedStep"),
    "StepProgressStatus": ("cognitive_world.resolution.stepwise", "StepProgressStatus"),
    "StepwisePlanExecutor": ("cognitive_world.resolution.stepwise", "StepwisePlanExecutor"),
    "StepwiseProgress": ("cognitive_world.resolution.stepwise", "StepwiseProgress"),
    "StepwiseStepResult": ("cognitive_world.resolution.stepwise", "StepwiseStepResult"),
}

__all__ = ["ResolutionDecision", "ResolutionEngine", "ResolutionResult", *_LAZY_EXPORTS]


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
