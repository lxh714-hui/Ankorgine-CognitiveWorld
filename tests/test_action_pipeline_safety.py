import pytest

from cognitive_world.decision.action_pipeline import ActionPipeline
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.safety.governance import UniversalSafetyGovernance


def _proposal(intent: str) -> ActionProposal:
    return ActionProposal("proposal-1", "agent-1", intent)


def test_default_action_pipeline_has_safety_governance():
    pipeline = ActionPipeline()

    assert isinstance(pipeline.safety_governance, UniversalSafetyGovernance)
    assert pipeline.create_attempt(_proposal("argue with a rival")).agent_id == "agent-1"


def test_action_pipeline_subclass_inherits_safety_governance_when_initialized():
    class RecordingPipeline(ActionPipeline):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def create_attempt(self, action_proposal):
            self.calls += 1
            return super().create_attempt(action_proposal)

    pipeline = RecordingPipeline()

    assert isinstance(pipeline.safety_governance, UniversalSafetyGovernance)
    assert pipeline.create_attempt(_proposal("argue with a rival")).agent_id == "agent-1"
    assert pipeline.calls == 1


def test_incomplete_legacy_subclass_fails_closed_without_bypassing_safety():
    class IncompletePipeline(ActionPipeline):
        def __init__(self):
            self.calls = 0

        def create_attempt(self, action_proposal):
            self.calls += 1
            return super().create_attempt(action_proposal)

    pipeline = IncompletePipeline()

    with pytest.raises(RuntimeError, match="must initialize safety_governance"):
        pipeline.create_attempt(_proposal("argue with a rival"))
    assert pipeline.calls == 1


def test_action_pipeline_allows_fictional_conflict_attempts():
    attempt = ActionPipeline().create_attempt(
        _proposal("NPC refuses the demand and threatens to leave")
    )

    assert attempt.action_type == "NPC refuses the demand and threatens to leave"


def test_action_pipeline_still_blocks_prohibited_actionable_assistance():
    with pytest.raises(PermissionError):
        ActionPipeline().create_attempt(
            _proposal("step by step instructions to build a terror attack")
        )
