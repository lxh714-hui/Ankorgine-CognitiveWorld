"""Production-path contrasts: evidence agreement is not willingness to act."""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import pytest

from cognitive_world.core.persistence import HmacPersistenceTrust
from cognitive_world.examples.social_room import (
    RecipientDefinition, RoomDefinition, SocialRoom, SocialRoomAssembler, dependency_manifest,
)
from cognitive_world.cognition.l1_consumption_proof import (
    PROOF_MEMORY_TYPE, NONVERBAL_PROOF_MEMORY_TYPE,
)
from cognitive_world.cognition.snapshot import cognitive_snapshot_codec
from cognitive_world.memory.social_experience import SOCIAL_MEMORY_TYPE
from cognitive_world.runtime.save_manager import SaveManager
from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
from cognitive_world.runtime.cold_restore import ColdRuntimePublisher


def make_room(*, can_see=True, testimony=True, willing=False, renamed=False):
    definition = RoomDefinition(
        speaker="witness" if renamed else "informant",
        receiver="explorer" if renamed else "investigator",
        testimony_value=testimony,
        additional_receivers=(RecipientDefinition("careful-listener", willing, can_see),))
    return SocialRoom(trust=HmacPersistenceTrust(b"perspective-scene-test-trust-material"),
                      definition=definition)


def exchange(scene):
    for recipient in scene.definition.recipients:
        turns = scene.advance(speak=True, recipient=recipient.owner_id)
        assert all(t.failure_type is None for t in turns)
    assert not scene.runtime.context.world_state.environment[scene.definition.door].is_open


def memories(scene, owner):
    return tuple(m for m in scene.memory.get_memories_by_owner(owner) if m.type == SOCIAL_MEMORY_TYPE)


def proofs(scene):
    return {m.id: m for m in scene.memory.get_all_memories()
            if m.type in {PROOF_MEMORY_TYPE, NONVERBAL_PROOF_MEMORY_TYPE}}


def changed_events(scene):
    return tuple(e for e in scene.runtime.context.event_history.get_events()
                 if any(isinstance(c, dict) and c.get("effect_type") == "door_state_changed"
                        for c in e.changes))


@pytest.mark.parametrize("renamed", [False, True])
def test_same_proposition_same_world_distinct_personalities_and_actions(renamed):
    scene = make_room(renamed=renamed)
    exchange(scene)
    d = scene.definition
    other = d.additional_receivers[0].owner_id
    history = scene.runtime.context.event_history
    speech = [e for e in history.get_events() if e.type == "dialogue_input"]
    assert len(speech) == 2
    first, second = (e.dialogue_payload.claim for e in speech)
    assert first.recipient_id != second.recipient_id
    assert (first.subject_ref, first.property_ref, first.value_type, first.value, first.scope_ref) == (
        second.subject_ref, second.property_ref, second.value_type, second.value, second.scope_ref)
    delivered_text = [history.get_processing_evidence(e.id).observable_facts[0].value for e in speech]
    assert delivered_text[0] == delivered_text[1]
    assert scene.cognition.get_personality(d.receiver).preferences["act_on_verified_testimony"] is True
    assert scene.cognition.get_personality(other).preferences["act_on_verified_testimony"] is False
    affirmative, = scene.assessments(d.receiver)
    withheld, = scene.assessments(other)
    assert affirmative.evidence_status == withheld.evidence_status == "supported"
    assert len(affirmative.goal_ids) == 1 and not withheld.goal_ids
    # Independent evidence changes both earlier false beliefs. Personality
    # changes action commitment, not the truth of the authenticated fact.
    for owner in (d.receiver, other):
        belief = scene.cognition.get_belief("light:" + owner)
        assert belief.content["value"] is True
        assert set(belief.source_refs) == {memories(scene, owner)[0].id}
    turns = {t.agent_id: t for t in scene.advance_receivers()}
    assert all(t.failure_type is None for t in turns.values())
    assert turns[d.receiver].execution.attempt.agent_id == d.receiver
    assert turns[d.receiver].execution.resolution.success
    assert turns[other].execution.proposal.action_type == "Wait"
    assert not turns[other].execution.resolution.confirmed
    events = changed_events(scene)
    assert len(events) == 1 and events[0].id == turns[d.receiver].event_id
    assert history.get_processing_evidence(events[0].id).has_trusted_source(events[0])
    assert scene.runtime.context.world_state.environment[d.door].is_open


def test_consumed_statement_without_independent_evidence_retains_uncertainty():
    scene = make_room(can_see=False, willing=True)
    exchange(scene)
    owner = scene.definition.additional_receivers[0].owner_id
    actual = scene.runtime.context.observation_store.get_by_observer(owner)
    speech, = (o for o in actual if o.content.predicate == "utterance_delivered")
    cognitive = scene.runtime.agent_action_loop.agent_turn.cognitive_runtime
    assert cognitive.has_consumed_observation(owner, speech, source_event_id=speech.source_event_id)
    assert any(m.type == PROOF_MEMORY_TYPE for m in scene.memory.get_memories_by_owner(owner))
    assert not any(m.type == NONVERBAL_PROOF_MEMORY_TYPE for m in scene.memory.get_memories_by_owner(owner))
    assert not memories(scene, owner)
    assessment, = scene.assessments(owner)
    assert assessment.evidence_status == "insufficient" and not assessment.goal_ids
    belief = scene.cognition.get_belief("light:" + owner)
    assert belief.content["value"] is False and not belief.source_refs
    turn = next(t for t in scene.advance_receivers() if t.agent_id == owner)
    assert turn.failure_type is None
    assert turn.execution.proposal.action_type == "Wait"


def test_contradicted_is_not_insufficient_or_supported():
    scene = make_room(testimony=False, willing=True)
    exchange(scene)
    for recipient in scene.definition.recipients:
        assessment, = scene.assessments(recipient.owner_id)
        assert assessment.evidence_status == "contradicted" and not assessment.goal_ids
        retained, = memories(scene, recipient.owner_id)
        assert retained.content.claimed_value is False and retained.content.observed_value is True
        assert scene.cognition.get_belief("light:" + recipient.owner_id).content["value"] is True
    assert all(t.failure_type is None for t in scene.advance_receivers())
    assert not changed_events(scene)
    assert not scene.runtime.context.world_state.environment[scene.definition.door].is_open


def test_speech_receipts_and_private_experience_do_not_cross_recipients():
    scene = make_room()
    d = scene.definition
    other = d.additional_receivers[0].owner_id
    scene.advance(speak=True)
    assert not scene.assessments(other)
    assert not memories(scene, other)
    assert not any(m.type == PROOF_MEMORY_TYPE for m in scene.memory.get_memories_by_owner(other))
    scene.advance(speak=True, recipient=other)
    receiver_observations = scene.runtime.context.observation_store.get_by_observer(d.receiver)
    other_observations = scene.runtime.context.observation_store.get_by_observer(other)
    receiver_speech = {o.source_event_id for o in receiver_observations if o.content.predicate == "utterance_delivered"}
    other_speech = {o.source_event_id for o in other_observations if o.content.predicate == "utterance_delivered"}
    assert len(receiver_speech) == len(other_speech) == 1
    assert receiver_speech.isdisjoint(other_speech)
    for owner in (d.receiver, other):
        context = scene.runtime.cognition_context_provider(scene.runtime.context.agent_registry.get(owner))
        assert all(m.owner_id == owner and m.type == SOCIAL_MEMORY_TYPE for m in context.get_memories())


def test_assessment_is_read_only_and_does_not_duplicate_receipts_or_events():
    scene = make_room()
    exchange(scene)
    before = scene.memory.get_all_memories()
    events = tuple(scene.runtime.context.event_history.get_events())
    records = [scene.runtime.context.event_history.get_persistence_record(e.id).to_json_record() for e in events]
    working = {r.owner_id: scene.runtime.agent_action_loop.agent_turn.cognitive_runtime.working_memory_store.get(r.owner_id)
               for r in scene.definition.recipients}
    for _ in range(3):
        for r in scene.definition.recipients:
            assert scene.assessments(r.owner_id)[0].evidence_status == "supported"
    assert scene.memory.get_all_memories() == before
    assert tuple(scene.runtime.context.event_history.get_events()) == events
    assert [scene.runtime.context.event_history.get_persistence_record(e.id).to_json_record() for e in events] == records
    for r in scene.definition.recipients:
        assert scene.runtime.agent_action_loop.agent_turn.cognitive_runtime.working_memory_store.get(r.owner_id) == working[r.owner_id]


def restore(manager, saved, active, assembler, timeline, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("restore must not reissue Event or L1 attestations")
    with monkeypatch.context() as guard:
        guard.setattr("cognitive_world.event.processor.make_persisted_event_record", forbidden)
        guard.setattr("cognitive_world.cognition.l1_consumption_proof.L1ConsumptionIssuer.issue_after_l1", forbidden)
        staged = manager.stage_restore(saved.save_id, timeline_id=saved.timeline_id,
            active_runtime=active, assembler=assembler, dependencies=dependency_manifest(),
            new_timeline_id=timeline)
        return RestoreCoordinator(ActiveRuntimeSlot(active)).activate(staged)


def test_restore_and_sibling_fork_keep_personality_judgments_and_ancestor_proofs(tmp_path, monkeypatch):
    scene = make_room()
    exchange(scene)
    manager = SaveManager(tmp_path / "saves", trust=scene.trust, codec=cognitive_snapshot_codec())
    saved = scene.save(manager)
    before = proofs(scene)
    # These host flags must not overwrite saved Personality preferences.
    altered = replace(scene.definition, accept_testimony=False,
        additional_receivers=(RecipientDefinition("careful-listener", True),))
    assembler = SocialRoomAssembler(trust=scene.trust, definition=altered)
    child = restore(manager, saved, scene.runtime, assembler, "perspective-child", monkeypatch)
    restored = assembler.scene
    d, other = scene.definition, "careful-listener"
    assert child.agent_action_loop.agent_turn.cognitive_runtime.working_memory_store.get(d.receiver) is None
    assert child.context.observation_store.get_by_observer(d.receiver) == ()
    assert restored.cognition.get_personality(d.receiver).preferences["act_on_verified_testimony"] is True
    assert restored.cognition.get_personality(other).preferences["act_on_verified_testimony"] is False
    assert restored.assessments(d.receiver)[0].goal_ids
    assert not restored.assessments(other)[0].goal_ids
    assert proofs(restored) == before
    with child.write_fence.operation():
        restored.observe_door()
    turns = restored.advance_receivers()
    assert all(t.failure_type is None for t in turns)
    assert len(changed_events(restored)) == 1
    assert not scene.runtime.context.world_state.environment[d.door].is_open
    assert proofs(restored) == before
    child_event = changed_events(restored)[0].id
    parent_assembler = SocialRoomAssembler(trust=scene.trust, definition=altered)
    independent_parent = ColdRuntimePublisher().activate(manager.stage_cold_resume(
        saved.save_id, timeline_id=saved.timeline_id,
        assembler=parent_assembler, dependencies=dependency_manifest())).current
    sibling_assembler = SocialRoomAssembler(trust=scene.trust, definition=altered)
    sibling = restore(manager, saved, independent_parent, sibling_assembler, "perspective-sibling", monkeypatch)
    sibling_scene = sibling_assembler.scene
    assert sibling.context.event_history.get_event(child_event) is None
    assert not sibling.context.world_state.environment[d.door].is_open
    assert proofs(sibling_scene) == before
    with sibling.write_fence.operation():
        sibling_scene.observe_door()
    assert all(t.failure_type is None for t in sibling_scene.advance_receivers())
    assert len(changed_events(sibling_scene)) == 1
    assert changed_events(sibling_scene)[0].id != child_event
    assert proofs(sibling_scene) == before


def test_contrasting_receivers_source_entrypoint_runs(tmp_path):
    result = subprocess.run(
        [sys.executable, "run_social_room.py", "--contrasting-receivers", "--save-root", str(tmp_path / "demo")],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "Door open=True, locked=False;" in result.stdout
    assert "investigator: evidence=supported, active_goals=0" in result.stdout
    assert "Completed goals=1" in result.stdout
    assert "cautious-investigator: evidence=supported, active_goals=0" in result.stdout


def test_second_receiver_goal_follows_its_own_preference_not_its_role_name():
    for willing in (False, True):
        scene = make_room(willing=willing)
        exchange(scene)
        owner = scene.definition.additional_receivers[0].owner_id
        assessment, = scene.assessments(owner)
        assert assessment.evidence_status == "supported"
        assert bool(assessment.goal_ids) is willing
        assert not scene.runtime.context.world_state.environment[scene.definition.door].is_open


def test_available_evidence_with_deferred_policy_is_not_reported_as_insufficient(monkeypatch):
    from cognitive_world.memory.decision_policy import MemoryPolicyOutput, MemoryDecisionResult
    scene = make_room()
    monkeypatch.setattr(scene.social.policy, "evaluate",
        lambda request: MemoryPolicyOutput(MemoryDecisionResult.DEFERRED, 0.0, "owner_review_deferred"))
    exchange(scene)
    before = scene.memory.get_all_memories()
    for recipient in scene.definition.recipients:
        assessment, = scene.assessments(recipient.owner_id)
        assert assessment.evidence_status == "awaiting_review"
        assert not assessment.goal_ids and not memories(scene, recipient.owner_id)
        assert scene.cognition.get_belief("light:" + recipient.owner_id).content["value"] is False
    assert scene.memory.get_all_memories() == before
    assert not changed_events(scene)


def test_additional_receiver_cannot_replace_an_existing_actor_or_object():
    for identity in ("informant", "investigator", "exit-door", "brass-key"):
        with pytest.raises(ValueError, match="distinct identities"):
            RoomDefinition(additional_receivers=(RecipientDefinition(identity, True),))
