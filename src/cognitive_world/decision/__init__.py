"""Decision-layer public API, loaded on demand.

Keeping this facade lazy prevents importing a low-level value object such as
``decision.attempt`` from eagerly loading AgentDecision, Cognition, and Runtime.
"""

from importlib import import_module


_EXPORTS = {
    "Attempt": ("cognitive_world.decision.attempt", "Attempt"),
    "Intent": ("cognitive_world.decision.intent", "Intent"),
    "Resolution": ("cognitive_world.decision.resolution", "Resolution"),
    "ActionProposal": ("cognitive_world.decision.action_proposal", "ActionProposal"),
    "AgentDecision": ("cognitive_world.decision.agent_decision", "AgentDecision"),
    "DecisionContext": ("cognitive_world.decision.context", "DecisionContext"),
    "FrozenMapping": ("cognitive_world.decision.snapshot", "FrozenMapping"),
    "FrozenRecordSnapshot": ("cognitive_world.decision.snapshot", "FrozenRecordSnapshot"),
    "ActionPipeline": ("cognitive_world.decision.action_pipeline", "ActionPipeline"),
    "ActionCandidate": ("cognitive_world.decision.autonomous", "ActionCandidate"),
    "ObservedAffordance": ("cognitive_world.decision.autonomous", "ObservedAffordance"),
    "ConflictOpportunityCandidate": ("cognitive_world.decision.autonomous", "ConflictOpportunityCandidate"),
    "SchedulerEvidenceRef": ("cognitive_world.decision.autonomous", "SchedulerEvidenceRef"),
    "ActionCandidateGenerationPolicy": ("cognitive_world.decision.autonomous", "ActionCandidateGenerationPolicy"),
    "ActionEvaluationPolicy": ("cognitive_world.decision.autonomous", "ActionEvaluationPolicy"),
    "BoundedDecisionReviewPolicy": ("cognitive_world.decision.autonomous", "BoundedDecisionReviewPolicy"),
    "CandidateEvaluation": ("cognitive_world.decision.autonomous", "CandidateEvaluation"),
    "SituationAssessment": ("cognitive_world.decision.autonomous", "SituationAssessment"),
    "SituationAssessmentPolicy": ("cognitive_world.decision.autonomous", "SituationAssessmentPolicy"),
    "DeterministicSituationAssessmentPolicy": ("cognitive_world.decision.autonomous", "DeterministicSituationAssessmentPolicy"),
    "DeterministicOpenEndedCandidatePolicy": ("cognitive_world.decision.autonomous", "DeterministicOpenEndedCandidatePolicy"),
    "DeterministicActionEvaluationPolicy": ("cognitive_world.decision.autonomous", "DeterministicActionEvaluationPolicy"),
    "DecisionLanguageModelProvider": ("cognitive_world.decision.autonomous", "DecisionLanguageModelProvider"),
    "ModelAssistedCandidatePolicy": ("cognitive_world.decision.autonomous", "ModelAssistedCandidatePolicy"),
    "OpenAICompatibleDecisionProvider": ("cognitive_world.decision.autonomous", "OpenAICompatibleDecisionProvider"),
    "EventTreeBranch": ("cognitive_world.decision.event_tree", "EventTreeBranch"),
    "EventTreePruning": ("cognitive_world.decision.event_tree", "EventTreePruning"),
    "EventTreeSnapshot": ("cognitive_world.decision.event_tree", "EventTreeSnapshot"),
    "EventTreeExplorer": ("cognitive_world.decision.event_tree", "EventTreeExplorer"),
    "EventTreeBranchProposalContext": ("cognitive_world.decision.event_tree", "EventTreeBranchProposalContext"),
    "EventTreeBranchProposalProvider": ("cognitive_world.decision.event_tree", "EventTreeBranchProposalProvider"),
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
