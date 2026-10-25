from cognitive_world.core.persistence import HmacPersistenceTrust
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.core.attributed_claim import AttributedClaimDraft, ClaimPropertyContract
from cognitive_world.memory.social_experience import SocialExperienceService, SOCIAL_MEMORY_TYPE
from cognitive_world.memory.decision_policy import MemoryPolicyOutput, MemoryDecisionResult
from cognitive_world.cognition.l1_consumption_proof import PROOF_MEMORY_TYPE, NONVERBAL_PROOF_MEMORY_TYPE
from cognitive_world.agent.character import Character
from test_npc_social_interaction import _world


class Accept:
    policy_id = "test-social-policy"
    policy_version = "1"
    def evaluate(self, value):
        return MemoryPolicyOutput(MemoryDecisionResult.ACCEPTED, 0.5, "verified_comparison")


def test_verified_social_experience():
    trust = HmacPersistenceTrust(b"social-slice-test-signing-material")
    store = MemoryStore()
    rt, cognition, observations, history, _ = _world(
        communication=True, trust=trust, shared_memory_store=store,
        structured_claim=True, complete_environment=True)
    rt.npc_communication_provider.claim = AttributedClaimDraft("room", "room_light_on", "boolean", True, 0, 0, "event:light-observed")
    rt.npc_dialogue_service.claim_property_contracts["room_light_on"] = ClaimPropertyContract("room_light_on", "boolean")
    rt.step()
    records = store.get_all_memories()
    speech = next(m for m in records if m.type == PROOF_MEMORY_TYPE)
    evidence = next(m for m in records if m.type == NONVERBAL_PROOF_MEMORY_TYPE and m.owner_id == "npc-b")
    service = SocialExperienceService(runtime=rt, cognition=cognition, memory_store=store, policy=Accept())
    with rt.write_fence.operation():
        memory = service.review(character=Character("character:npc-b", "npc-b", ""),
                                speech_memory_id=speech.id, evidence_memory_id=evidence.id)
    assert memory.type == SOCIAL_MEMORY_TYPE
    assert memory.content.comparison == "supported"


def test_room_runs_real_npc_turns_and_commits_keyed_door():
    from cognitive_world.examples.social_room import SocialRoom
    scene = SocialRoom(trust=HmacPersistenceTrust(b"room-world-test-signing-material"))
    first = scene.advance(speak=True)
    assert scene.runtime.context.world_state.environment[scene.definition.door].is_locked
    assert scene.memory.get_all_memories()
    second = scene.advance()
    state = scene.runtime.context.world_state.environment[scene.definition.door]
    assert state.is_open and not state.is_locked
    assert any(item.execution.event is not None for item in second)
    independent = SocialRoom(trust=scene.trust)
    assert independent.runtime.context.event_history.timeline_id != scene.runtime.context.event_history.timeline_id


import pytest
from dataclasses import replace
from cognitive_world.examples.social_room import (
    SocialRoom, RoomDefinition, SocialRoomAssembler, dependency_manifest,
)
from cognitive_world.cognition.snapshot import cognitive_snapshot_codec
from cognitive_world.memory.social_experience import (
    SocialExperience, EvidenceGoalDraft, authorized_social_memories,
)
from cognitive_world.runtime.save_manager import SaveManager
from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator


def room(**changes):
    return SocialRoom(trust=HmacPersistenceTrust(b"room-world-test-signing-material"),
                      definition=replace(RoomDefinition(), **changes))


def social_records(scene):
    return [m for m in scene.memory.get_all_memories() if m.type == SOCIAL_MEMORY_TYPE]


@pytest.mark.parametrize("accept,claim,expected", [(True, True, True), (False, True, False), (True, False, False)])
def test_policy_and_independent_evidence_change_real_action(accept, claim, expected):
    scene = room(accept_testimony=accept, testimony_value=claim)
    first = scene.advance(speak=True)
    assert all(item.failure_type is None for item in first)
    experiences = social_records(scene)
    assert len(experiences) == 1
    assert experiences[0].content.comparison == ("supported" if claim else "contradicted")
    # A's claim cannot set the canonical light. Both owners retain distinct records.
    assert scene.runtime.context.world_state.environment[scene.definition.room]["light_on"] is True
    belief = scene.cognition.get_belief("light:" + scene.definition.receiver)
    assert belief.content == {"property": "room_light_on", "value": True}
    second = scene.advance()
    assert all(item.failure_type is None for item in second)
    state = scene.runtime.context.world_state.environment[scene.definition.door]
    assert state.is_open is expected
    changed = [e for e in scene.runtime.context.event_history.get_events()
               if any(isinstance(c, dict) and c.get("effect_type") == "door_state_changed" for c in e.changes)]
    assert len(changed) == int(expected)
    goals = scene.cognition.goal_store.get(scene.definition.receiver)
    assert any(g.description == scene.definition.goal_description for g in goals) is expected


def test_missing_key_cannot_be_supplied_by_method_text():
    scene = room(key_available=False)
    scene.advance(speak=True)
    result = scene.advance()[0]
    assert result.execution.attempt is not None
    assert result.execution.resolution.confirmed
    assert not result.execution.resolution.success
    assert not scene.runtime.context.world_state.environment[scene.definition.door].is_open
    assert scene.runtime.context.world_state.get_entity(scene.definition.key).owner_id is None
    assert scene.runtime.context.world_state.locations[scene.definition.key] == scene.definition.drawer


def test_speech_delivery_alone_does_not_create_experience_and_private_proofs_stay_private():
    scene = room()
    assert not social_records(scene)
    assert not scene.memory.get_all_memories()
    scene.advance(speak=True)
    d = scene.definition
    # Only the addressed receiver gets the speech; observation is not world truth.
    speech = [o for o in scene.runtime.context.observation_store.get_by_observer(d.receiver)
              if o.content.predicate == "utterance_delivered"]
    assert len(speech) == 1
    assert not any(o.content.predicate == "utterance_delivered"
                   for o in scene.runtime.context.observation_store.get_by_observer(d.speaker))
    owner_context = scene.runtime.cognition_context_provider(scene.runtime.context.agent_registry.get(d.receiver))
    other_context = scene.runtime.cognition_context_provider(scene.runtime.context.agent_registry.get(d.speaker))
    assert len([m for m in owner_context.get_memories() if m.type == SOCIAL_MEMORY_TYPE]) == 1
    assert not other_context.get_memories()
    assert all(not m.type.startswith("system_l1_") for m in owner_context.get_memories())
    assert scene.cognition.get_belief("light:" + d.speaker).content != scene.cognition.get_belief("light:" + d.receiver).content


def test_duplicate_review_preserves_identity_and_does_not_replay_world_action():
    scene = room()
    scene.advance(speak=True)
    original = social_records(scene)[0]
    before = tuple(scene.runtime.context.event_history.get_events())
    d = scene.definition
    with scene.runtime.write_fence.operation():
        duplicate = scene.social.review(
            character=Character("character:" + d.receiver, d.receiver, ""),
            speech_memory_id=original.content.speech_memory_id,
            evidence_memory_id=original.content.evidence_memory_id)
    assert duplicate == original
    assert social_records(scene) == [original]
    assert tuple(scene.runtime.context.event_history.get_events()) == before


def test_unknown_version_tamper_and_foreign_goal_evidence_reject():
    scene = room()
    scene.advance(speak=True)
    record = social_records(scene)[0]
    with pytest.raises(ValueError):
        replace(record.content, version=2)
    from cognitive_world.memory.social_experience import verify_experience
    records = {m.id: m for m in scene.memory.get_all_memories()}
    for changes in ({"speaker_id": "impostor"}, {"comparison": "contradicted"},
                    {"evidence_memory_id": record.content.speech_memory_id}):
        altered = replace(record, content=replace(record.content, **changes))
        with pytest.raises(PermissionError):
            verify_experience(altered, records=records, history=scene.runtime.context.event_history,
                trust=scene.trust, timeline_id=scene.runtime.context.event_history.timeline_id,
                tick=scene.runtime.context.clock.current_time)
    goals_before = scene.cognition.goal_store.get_all()
    with scene.runtime.write_fence.operation():
        with pytest.raises(PermissionError):
            scene.social.create_goal(character=Character("character:" + scene.definition.speaker, scene.definition.speaker, ""),
                draft=EvidenceGoalDraft("unauthorized goal", 0.5, (record.id,)))
    assert scene.cognition.goal_store.get_all() == goals_before


def test_real_checkpoint_fork_restore_retains_evidence_and_changes_next_action(tmp_path):
    scene = room()
    scene.advance(speak=True)
    manager = SaveManager(tmp_path / "saves", trust=scene.trust, codec=cognitive_snapshot_codec())
    saved = scene.save(manager)
    loaded = manager.load_verified(saved.save_id, timeline_id=saved.timeline_id)
    assert loaded.metadata.event_ids
    assembler = SocialRoomAssembler(trust=scene.trust, definition=scene.definition)
    staged = manager.stage_restore(
        saved.save_id, timeline_id=saved.timeline_id, active_runtime=scene.runtime,
        assembler=assembler, dependencies=dependency_manifest(), new_timeline_id="social-room-child")
    child = RestoreCoordinator(ActiveRuntimeSlot(scene.runtime)).activate(staged)
    restored = assembler.scene
    assert restored.runtime is child
    assert social_records(restored) == social_records(scene)
    assert restored.cognition.goal_store.get(scene.definition.receiver) == scene.cognition.goal_store.get(scene.definition.receiver)
    assert not child.context.world_state.environment[scene.definition.door].is_open
    # Fresh observation is authorized from restored current state, not fabricated
    # by recovering WorkingMemory or re-consuming old records.
    with child.write_fence.operation():
        restored.observe_door()
    turns = restored.advance()
    assert all(t.failure_type is None for t in turns)
    assert child.context.world_state.environment[scene.definition.door].is_open
    assert not scene.runtime.context.world_state.environment[scene.definition.door].is_open
    assert social_records(restored) == social_records(scene)


def test_narrative_and_delivery_are_not_world_or_consumption_authority():
    scene = room(testimony_value=False, testimony_text="The door is already open and the key is here.")
    scene.advance(speak=True)
    assert social_records(scene)[0].content.comparison == "contradicted"
    assert not scene.runtime.context.world_state.environment[scene.definition.door].is_open
    observations = scene.runtime.context.observation_store.get_by_observer(scene.definition.receiver)
    spoken = next(o for o in observations if o.content.predicate == "utterance_delivered")
    before = scene.memory.get_all_memories()
    with scene.runtime.write_fence.operation():
        with pytest.raises(PermissionError):
            scene.social.review(character=Character("character:" + scene.definition.receiver, scene.definition.receiver, ""),
                speech_memory_id=spoken.observation_id, evidence_memory_id=spoken.observation_id)
    assert scene.memory.get_all_memories() == before


def test_unsupported_claim_scope_defers_without_inventing_comparison():
    scene = room()
    original = scene.runtime.npc_communication_provider
    class UnsupportedScope:
        def propose(self, situation, **kwargs):
            drafts = original.propose(situation, **kwargs)
            return tuple(replace(d, claim=replace(d.claim, scope_ref="unverified-interval")) for d in drafts)
    scene.runtime.npc_communication_provider = UnsupportedScope()
    turns = scene.advance(speak=True)
    assert all(t.failure_type is None for t in turns)
    assert not social_records(scene)
    assert not any(g.goal_id.startswith("evidence-goal:") for g in scene.cognition.goal_store.get_all())
    assert not scene.runtime.context.world_state.environment[scene.definition.door].is_open


def test_goal_creation_governance_rejects_unsealed_and_stale_generation():
    from cognitive_world.cognition.goal_creation import GoalCreationProposal
    from cognitive_world.cognition.goal import Goal
    from cognitive_world.cognition.validation import CognitiveUpdateValidator, ValidationResult
    from cognitive_world.cognition.update_apply import CognitiveUpdateApplier
    scene = room()
    scene.advance(speak=True)
    record = social_records(scene)[0]
    rt = scene.runtime
    with rt.write_fence.operation():
        proposal = GoalCreationProposal(scene.definition.receiver, "fresh-goal", "A new objective", 0.5, [record.id])
        validation = CognitiveUpdateValidator().validate(proposal, {
            "agent_id": scene.definition.receiver, "authorized_source_refs": [record.id]})
        assert validation.accepted
        with pytest.raises(PermissionError):
            scene.cognition.goal_store.create(Goal("fresh-goal", scene.definition.receiver, "A new objective", 0.5),
                proposal=proposal, validation_result=ValidationResult(True, "forged"))
    rt.write_fence.freeze_and_advance()
    rt.write_fence.unfreeze()
    with rt.write_fence.operation():
        with pytest.raises(PermissionError):
            CognitiveUpdateApplier(scene.cognition.belief_store, scene.cognition.goal_store,
                write_fence=rt.write_fence).apply(proposal, validation)
    assert scene.cognition.goal_store.get_owned(scene.definition.receiver, "fresh-goal") is None


def test_goal_registration_failure_freezes_capture_without_replaying_action(monkeypatch, tmp_path):
    scene = room(accept_testimony=False)
    scene.advance(speak=True)
    memory = social_records(scene)[0]
    before = tuple(scene.runtime.context.event_history.get_events())
    def fail_register(agent):
        raise RuntimeError("injected registration failure")
    monkeypatch.setattr(scene.runtime.context.agent_registry, "register", fail_register)
    with scene.runtime.write_fence.operation():
        with pytest.raises(RuntimeError, match="injected"):
            scene.social.create_goal(
                character=Character("character:" + scene.definition.receiver, scene.definition.receiver, ""),
                draft=EvidenceGoalDraft("a new governed objective", 0.6, (memory.id,)))
    assert scene.runtime.write_fence.recovery_required
    assert tuple(scene.runtime.context.event_history.get_events()) == before
    manager = SaveManager(tmp_path / "saves", trust=scene.trust, codec=cognitive_snapshot_codec())
    with pytest.raises(PermissionError):
        scene.save(manager)
    assert not scene.runtime.context.world_state.environment[scene.definition.door].is_open


def test_unknown_social_payload_and_legacy_write_do_not_gain_authority():
    from cognitive_world.cognition.memory import Memory
    from cognitive_world.core.persistence import PersistedValueCodec
    scene = room()
    scene.advance(speak=True)
    original = social_records(scene)[0]
    bad = replace(original, type="attributed_social_experience_v99")
    assert not MemoryStore.is_semantically_retrievable(bad)
    legacy = Memory("legacy-social", original.owner_id, SOCIAL_MEMORY_TYPE,
                    original.content, 0.5, original.source_event)
    with scene.runtime.write_fence.operation():
        with pytest.raises(PermissionError):
            scene.memory._commit_memory(legacy)
    # An old closed codec cannot silently decode the newly approved payload.
    encoded = cognitive_snapshot_codec().dumps(original.content)
    with pytest.raises((TypeError, ValueError)):
        PersistedValueCodec().loads(encoded)


def test_completed_door_and_social_state_survive_second_published_checkpoint(tmp_path):
    scene = room()
    scene.advance(speak=True)
    scene.advance()
    manager = SaveManager(tmp_path / "complete", trust=scene.trust, codec=cognitive_snapshot_codec())
    saved = scene.save(manager)
    assembler = SocialRoomAssembler(trust=scene.trust)
    staged = manager.stage_restore(saved.save_id, timeline_id=saved.timeline_id,
        active_runtime=scene.runtime, assembler=assembler, dependencies=dependency_manifest(),
        new_timeline_id="completed-room-child")
    child = RestoreCoordinator(ActiveRuntimeSlot(scene.runtime)).activate(staged)
    restored = assembler.scene
    d = scene.definition
    assert child.context.world_state.environment[d.door] == scene.runtime.context.world_state.environment[d.door]
    assert child.context.world_state.get_entity(d.key).owner_id == d.receiver
    assert child.context.world_state.locations[d.drawer] == d.table
    assert restored.cognition.get_belief("light:" + d.receiver) == scene.cognition.get_belief("light:" + d.receiver)
    before = [e for e in child.context.event_history.get_events()
              if any(isinstance(c, dict) and c.get("effect_type") == "door_state_changed" for c in e.changes)]
    with child.write_fence.operation():
        restored.observe_door()
    restored.advance()
    after = [e for e in child.context.event_history.get_events()
             if any(isinstance(c, dict) and c.get("effect_type") == "door_state_changed" for c in e.changes)]
    assert after == before
    assert social_records(restored) == social_records(scene)


def test_source_checkout_entrypoint_runs_and_publishes_real_save(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    result = subprocess.run([sys.executable, "run_social_room.py", "--save-root", str(tmp_path / "run")],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "Door open=True, locked=False; checkpoint=" in result.stdout
    again = subprocess.run([sys.executable, "run_social_room.py", "--save-root", str(tmp_path / "run")],
                           cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert again.returncode == 0, again.stderr
    assert "Door open=True, locked=False; checkpoint=" in again.stdout


def test_completed_new_goal_is_not_reactivated_or_executed():
    from cognitive_world.cognition.goal_update import GoalUpdater
    from cognitive_world.cognition.validation import CognitiveUpdateValidator
    from cognitive_world.cognition.update_apply import CognitiveUpdateApplier
    scene = room()
    scene.advance(speak=True)
    goal = next(g for g in scene.cognition.goal_store.get(scene.definition.receiver)
                if g.goal_id.startswith("evidence-goal:"))
    with scene.runtime.write_fence.operation():
        proposal = GoalUpdater().propose_update(goal, {
            "new_state": "abandoned", "source_refs": goal.source_refs,
            "reason": "The owner abandons this objective."})
        validation = CognitiveUpdateValidator().validate(proposal, {
            "agent_id": goal.owner_id, "authorized_source_refs": goal.source_refs})
        CognitiveUpdateApplier(scene.cognition.belief_store, scene.cognition.goal_store,
            write_fence=scene.runtime.write_fence).apply(proposal, validation)
    scene.advance()
    current = scene.cognition.goal_store.get_owned(goal.owner_id, goal.goal_id)
    assert current.status == "abandoned"
    assert not scene.runtime.context.world_state.environment[scene.definition.door].is_open
    assert len([g for g in scene.cognition.goal_store.get(goal.owner_id)
                if g.goal_id.startswith("evidence-goal:")]) == 1


def test_uncertain_social_memory_publication_freezes_without_action_replay(monkeypatch, tmp_path):
    scene = room()
    commit = scene.memory._commit_memory
    def committed_then_error(memory, **kwargs):
        commit(memory, **kwargs)
        if memory.type == SOCIAL_MEMORY_TYPE:
            raise OSError("injected post-commit uncertainty")
    monkeypatch.setattr(scene.memory, "_commit_memory", committed_then_error)
    turns = scene.advance(speak=True)
    assert any(t.failure_type == "OSError" for t in turns)
    assert scene.runtime.write_fence.recovery_required
    assert len(social_records(scene)) == 1
    assert not any(g.goal_id.startswith("evidence-goal:") for g in scene.cognition.goal_store.get_all())
    assert not scene.runtime.context.world_state.environment[scene.definition.door].is_open
    manager = SaveManager(tmp_path / "uncertain", trust=scene.trust, codec=cognitive_snapshot_codec())
    with pytest.raises(PermissionError):
        scene.save(manager)


def test_initialized_room_can_publish_before_first_turn_without_inventing_experience(tmp_path):
    scene = room()
    manager = SaveManager(tmp_path / "initial", trust=scene.trust, codec=cognitive_snapshot_codec())
    saved = scene.save(manager)
    manager.load_verified(saved.save_id, timeline_id=saved.timeline_id)
    assert not social_records(scene)
    assert scene.runtime.context.world_state.environment[scene.definition.door].is_locked


def test_selected_speech_can_be_delivered_without_recipient_consumption():
    scene = room()
    rt, d = scene.runtime, scene.definition
    rt.context.agent_scheduler.schedule_agent(d.speaker, 1)
    rt.step()
    delivered = [o for o in rt.context.observation_store.get_by_observer(d.receiver)
                 if o.content.predicate == "utterance_delivered"]
    assert len(delivered) == 1
    assert rt.agent_action_loop.agent_turn.cognitive_runtime.working_memory_store.get(d.receiver) is None
    assert not any(m.owner_id == d.receiver for m in scene.memory.get_all_memories())
    assert not social_records(scene)
    assert not any(g.goal_id.startswith("evidence-goal:") for g in scene.cognition.goal_store.get(d.receiver))
    scene.advance()
    assert len(social_records(scene)) == 1


def test_restore_does_not_reinterpret_old_experience_using_current_testimony_configuration(tmp_path):
    scene = room()
    scene.advance(speak=True)
    manager = SaveManager(tmp_path / "policy-change", trust=scene.trust, codec=cognitive_snapshot_codec())
    saved = scene.save(manager)
    # The current speaker configuration is not authority over an old observed value.
    assembler = SocialRoomAssembler(trust=scene.trust,
                                   definition=replace(scene.definition, testimony_value=False))
    staged = manager.stage_restore(saved.save_id, timeline_id=saved.timeline_id,
        active_runtime=scene.runtime, assembler=assembler, dependencies=dependency_manifest(),
        new_timeline_id="changed-policy-child")
    child = RestoreCoordinator(ActiveRuntimeSlot(scene.runtime)).activate(staged)
    restored = assembler.scene
    with child.write_fence.operation():
        restored.observe_door()
    restored.advance()
    assert restored.cognition.get_belief("light:" + scene.definition.receiver).content["value"] is True
    assert social_records(restored) == social_records(scene)
