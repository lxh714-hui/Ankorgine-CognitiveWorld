"""Production-path regressions for the first NPC-to-NPC communication slice."""

from cognitive_world.agent.action_loop import AgentActionLoop
from cognitive_world.agent.character import Character
from cognitive_world.agent.cognition_context import CognitionContext
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.cognition.belief import Belief
from cognitive_world.cognition.causal_review import (
    BeliefRevisionSuggestion, CognitiveReview,
)
from cognitive_world.cognition.container import CognitionContainer
from cognitive_world.cognition.goal import Goal
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.core.attributed_claim import AttributedClaimDraft, ClaimPropertyContract
from cognitive_world.cognition.personality import Personality
from cognitive_world.core.entity import Entity
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision.agent_decision import AgentDecision
from cognitive_world.decision.autonomous import ActionCandidate, CandidateEvaluation
from cognitive_world.dialogue.npc import NpcCommunicationDraft
from cognitive_world.event import EventHistory, EventProcessor, RoomLightChangedHandler, SystemEventFactory
from cognitive_world.observation.store import ObservationStore
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.engine import ResolutionEngine
from cognitive_world.runtime.agent_scheduler import AgentScheduler
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.scheduler import EventScheduler


class _UnresolvedResolution(ResolutionEngine):
    def _adjudicate(self, attempt):
        return None


class _CommunicationProvider:
    def __init__(self, *, claim=None):
        self.claim = claim

    def propose(self, situation, *, recipient_ids, maximum_candidates):
        assert maximum_candidates == 1
        if situation.owner_id != "npc-a" or "npc-b" not in recipient_ids:
            return ()
        facts = tuple(fact for fact in situation.observed_facts
                      if fact.predicate == "room_light_on" and fact.value == "True")
        if not facts:
            return ()
        return (NpcCommunicationDraft(
            "npc-b", "I observed that the room light is on.", (facts[0].percept_id,),
            self.claim,
        ),)


class _ReviewProvider:
    def __init__(self):
        self.requests = []

    def review(self, request):
        self.requests.append(request)
        if request.owner_id != "npc-b" or request.speech_observation_id is None:
            return CognitiveReview("No speech-based revision", "Retain uncertainty.", outcome="defer")
        objective = next((item for item in request.evidence
                          if item.observation_id != request.speech_observation_id
                          and item.content.get("fact_type") != "social_input"), None)
        if objective is None:
            return CognitiveReview("Insufficient independent evidence", "Defer.", outcome="defer")
        return CognitiveReview(
            "The recipient's independent observation supports revisiting this belief.",
            "The revision is subjective and limited to this observed room and time.",
            BeliefRevisionSuggestion(
                "belief-b", {"claim": "room light is on"}, 0.82,
                "Recipient's own trusted observation is consistent with the utterance.",
                (request.speech_observation_id, objective.observation_id),
            ),
            "accept",
        )


class _Candidates:
    def generate(self, situation):
        owner = situation.owner_id
        sources = tuple(fact.percept_id for fact in situation.observed_facts[:1])
        if owner == "npc-a":
            return (ActionCandidate(
                "a-wait", owner, None, "Wait and reassess", None,
                "Wait for further information.", (), (), (), ("Wait.",),
                "No world change is assumed.", (), 0.1, None, 0.1,
                sources, "test_non_social_option",
            ),)
        return (
            ActionCandidate(
                "b-follow", owner, "goal-b", "Follow the room-light observation", None,
                "Choose the option associated with the observed light.", (), (), (),
                ("Reassess after this choice.",), "Only the decision changes.", (),
                0.1, None, 0.2, sources, "test_choice",
            ),
            ActionCandidate(
                "b-hold", owner, "goal-b", "Hold the prior plan", None,
                "Continue with the prior plan while evidence is limited.", (), (), (),
                ("Reassess after this choice.",), "Only the decision changes.", (),
                0.1, None, 0.2, sources, "test_choice",
            ),
        )


class _Scores:
    def evaluate(self, situation, candidates):
        scores = {}
        if situation.owner_id == "npc-a":
            for candidate in candidates:
                scores[candidate.candidate_id] = (
                    1.0 if candidate.strategy == "npc_communication_v1" else 0.0
                )
        else:
            revised = any("light is on" in belief.claim for belief in situation.beliefs)
            for candidate in candidates:
                selected = (candidate.candidate_id == ("b-follow" if revised else "b-hold"))
                scores[candidate.candidate_id] = 1.0 if selected else 0.0
        return tuple(CandidateEvaluation(
            candidate.candidate_id, scores[candidate.candidate_id],
            (("deterministic_test_rule", scores[candidate.candidate_id]),),
            candidate.uncertainties,
        ) for candidate in candidates)


class _NoReview:
    def should_review(self, situation, evaluations):
        return False


def _world(*, communication: bool, trust=None, shared_memory_store=None,
           timeline_id="social-timeline", structured_claim=False,
           complete_environment=False):
    world = WorldState()
    if complete_environment:
        world.load_environment_snapshot({"room": {"light_on": False}})
    else:
        world.load_environment_data("room", {"light_on": False})
    registry = AgentRegistry()
    container = CognitionContainer()
    characters = {}
    for owner in ("npc-a", "npc-b"):
        world.load_entity(Entity(owner, "character", sensory_capabilities=("sight",)))
        world.load_location(owner, "room")
        goal_id = f"goal-{owner[-1]}"
        container.add_goal(Goal(goal_id, owner, "understand the room and decide what to do", 0.8, "active"))
        if owner == "npc-b":
            container.add_belief(Belief(
                "belief-b", owner, {"claim": "room light is off"}, [], 0.55,
            ))
        else:
            container.add_belief(Belief(
                "private-a", owner, {"claim": "A's private plan"}, ["private-source"], 0.7,
            ))
        if trust is not None:
            container.add_personality(Personality(owner))
        character = Character(f"character:{owner}", owner, owner if trust is not None else "", goal_ids=[goal_id],
                              belief_ids=["belief-b"] if owner == "npc-b" else ["private-a"])
        characters[owner] = character
        registry.register(RuntimeAgent(owner, character.id, goal_ids=[goal_id]))
    observations = ObservationStore()
    history = EventHistory(timeline_id=timeline_id if trust is not None else None)
    clock = SimulationClock()
    scheduler = EventScheduler()
    agent_scheduler = AgentScheduler()
    processor = EventProcessor(
        event_history=history, world_state=world, simulation_clock=clock,
        agent_registry=registry, observation_store=observations,
        persistence_trust=trust,
    )
    processor.register_handler("room_light_changed", RoomLightChangedHandler())
    context = RuntimeContext(
        clock, world, history, event_scheduler=scheduler,
        agent_scheduler=agent_scheduler, agent_registry=registry,
        observation_store=observations,
    )
    cognition_contexts = {
        owner: CognitionContext.from_character(
            characters[owner], container,
            shared_memory_store if shared_memory_store is not None else MemoryStore(),
            observation_store=observations,
        ) for owner in characters
    }
    loop = AgentActionLoop(action_resolution_flow=ActionResolutionFlow(
        resolution_engine=_UnresolvedResolution(), world_state=world,
    ))
    review = _ReviewProvider()
    runtime = SimulationRuntime(
        context, scheduler=scheduler, event_processor=processor,
        agent_action_loop=loop,
        cognition_context_provider=lambda agent: cognition_contexts[agent.agent_id],
        agent_decision=AgentDecision(
            candidate_policy=_Candidates(), evaluation_policy=_Scores(), review_policy=_NoReview(),
        ),
        cognitive_review_provider=review,
        npc_communication_provider=_CommunicationProvider() if communication else None,
        npc_claim_property_contracts=(
            (ClaimPropertyContract("environment.light_on", "boolean"),)
            if structured_claim else ()
        ),
        allow_environment_provider_discovery=False,
    )
    seed = SystemEventFactory().create(
        event_id="light-observed", event_type="room_light_changed", timestamp="0",
        simulation_tick=0,
        changes=[{"room_id": "room", "from_light_on": False, "to_light_on": True}],
    )
    processor.dispatch_with_evidence(seed)
    for owner in ("npc-a", "npc-b"):
        agent_scheduler.schedule_agent(owner, 1)
    return runtime, container, observations, history, review


def test_npc_autonomously_selects_speech_recipient_consumes_and_revises_then_changes_decision():
    control, control_cognition, control_observations, control_history, control_review = _world(communication=False)
    social, social_cognition, social_observations, social_history, social_review = _world(communication=True)

    control.step()
    social.step()

    control_b = next(record for record in control.last_agent_turn_results if record.agent_id == "npc-b")
    social_a = next(record for record in social.last_agent_turn_results if record.agent_id == "npc-a")
    social_b = next(record for record in social.last_agent_turn_results if record.agent_id == "npc-b")
    assert control_b.execution.proposal.metadata["selected_candidate_id"] == "b-hold"
    assert social_a.execution.proposal.metadata["selected_candidate_id"].startswith("npc-communication:")
    assert social_a.execution.attempt is None and social_a.execution.resolution is None
    delivery = social_a.execution.communication_result
    assert delivery.status == "delivered_pending_recipient_turn"
    assert delivery.sender_id == "npc-a" and delivery.recipient_id == "npc-b"
    assert social_a.event_committed and social_a.event_id == delivery.event_id
    assert social_b.execution.proposal.metadata["selected_candidate_id"] == "b-follow"
    communication_trace = next(
        item for item in social_a.execution.proposal.metadata["decision_trace"]
        if item["candidate_id"] == social_a.execution.proposal.metadata["selected_candidate_id"]
    )
    assert communication_trace["score"] == 0.99
    assert ("bounded_observed_evidence_review", -0.01) in communication_trace["factors"]
    assert any(item.startswith("percept:") for item in communication_trace["source_refs"])
    assert f"percept:{delivery.observation_id}" in social_b.newly_consumed_percept_ids

    speech = social_observations.get(delivery.observation_id)
    assert speech.observer_id == "npc-b" and speech.has_trusted_provenance()
    assert speech.content.value == "I observed that the room light is on."
    assert social_observations.get_by_observer("npc-a") == control_observations.get_by_observer("npc-a")
    assert social_cognition.get_belief("belief-b").content == {"claim": "room light is on"}
    assert social_cognition.get_belief("belief-b").owner_id == "npc-b"
    assert control_cognition.get_belief("belief-b").content == {"claim": "room light is off"}
    assert social_review.requests[-1].owner_id == "npc-b"
    assert {item.belief_id for item in social_review.requests[-1].beliefs} == {"belief-b"}
    assert social_review.requests[-1].speech_observation_id == delivery.observation_id
    assert {item.observation_id for item in social_review.requests[-1].evidence} == {
        delivery.observation_id,
        next(item.observation_id for item in social_observations.get_by_observer("npc-b")
             if item.content.predicate == "room_light_on"),
    }
    assert any(item.type == "dialogue_input" and item.cause == delivery.proposal_id
               for item in social_history.get_events())
    assert not any(item.type == "dialogue_input" for item in control_history.get_events())
    assert social.context.world_state.environment["room"]["light_on"] is True
    assert social_b.execution.event is None  # decision is not itself a world outcome


def test_trusted_l1_consumption_creates_durable_system_proof_independent_of_memory_decision():
    from cognitive_world.core.persistence import HmacPersistenceTrust
    from cognitive_world.cognition.l1_consumption_proof import (
        PROOF_MEMORY_TYPE, verify_proof,
    )

    trust = HmacPersistenceTrust(b"test-only-l1-consumption-key-32-bytes")
    memory_store = MemoryStore()
    runtime, _, observations, history, _ = _world(
        communication=True, trust=trust, shared_memory_store=memory_store,
    )
    runtime.step()
    delivery = next(item for item in runtime.last_agent_turn_results
                    if item.agent_id == "npc-a").execution.communication_result
    proof_records = tuple(item for item in memory_store.get_all_memories()
                          if item.type == PROOF_MEMORY_TYPE)
    assert len(proof_records) == 1
    record = proof_records[0]
    assert record.owner_id == "npc-b" and record.source_event == delivery.event_id
    assert record.content.observation_id == delivery.observation_id
    verify_proof(record.content, history=history, trust=trust,
                 checkpoint_timeline_id="social-timeline",
                 checkpoint_tick=runtime.context.clock.current_time)
    assert observations.get(delivery.observation_id).observer_id == "npc-b"
    # The system evidence is not exposed as a semantic memory to the NPC.
    npc_b = next(agent for agent in runtime.context.agent_registry.all_agents()
                 if agent.agent_id == "npc-b")
    context = runtime.cognition_context_provider(npc_b)
    assert not any(item.type == PROOF_MEMORY_TYPE for item in context.get_memories())

    from cognitive_world.cognition.snapshot import CognitiveStateSnapshot, reconstruct_isolated
    container = context.cognition_container
    contexts = tuple(runtime.cognition_context_provider(agent)
                     for agent in runtime.context.agent_registry.all_agents())
    with runtime.write_fence.operation():
        snapshot = CognitiveStateSnapshot.capture(
            cognition=container, memory_store=memory_store, runtime=runtime,
            agent_contexts=contexts, timeline_id="social-timeline", trust=trust,
        )
    restored = reconstruct_isolated(
        CognitiveStateSnapshot.from_bytes(snapshot.to_bytes(), trust=trust),
        trust=trust, expected_agents=snapshot.body.expected_agents,
        event_history=history,
    )
    assert restored.memory_store.get_memory(record.id) == record

    from dataclasses import replace
    import pytest
    with pytest.raises(PermissionError):
        verify_proof(replace(record.content, owner_id="npc-a"),
                     history=history, trust=trust,
                     checkpoint_timeline_id="social-timeline",
                     checkpoint_tick=runtime.context.clock.current_time)
    with pytest.raises(PermissionError):
        verify_proof(replace(record.content, observation_sha256="0" * 64),
                     history=history, trust=trust,
                     checkpoint_timeline_id="social-timeline",
                     checkpoint_tick=runtime.context.clock.current_time)
    with pytest.raises(PermissionError):
        memory_store._commit_memory(record)
    runtime.step()
    assert tuple(item.id for item in memory_store.get_all_memories()
                 if item.type == PROOF_MEMORY_TYPE) == (record.id,)


def test_d1_claim_is_bound_to_the_selected_utterance_and_signed_event():
    from cognitive_world.core.persistence import HmacPersistenceTrust
    from cognitive_world.core.attributed_claim import AttributedClaim
    from cognitive_world.event.persistence import verify_and_restore_event_records
    from cognitive_world.cognition.snapshot import cognitive_snapshot_codec

    trust = HmacPersistenceTrust(b"stage1-claim-signing-test-key-material-32")
    draft = AttributedClaimDraft(
        "room", "environment.light_on", "boolean", False, 0, 5, "room:room",
    )
    runtime, cognition, _, history, _ = _world(
        communication=True, trust=trust, shared_memory_store=MemoryStore(),
        structured_claim=True,
    )
    runtime.npc_communication_provider = _CommunicationProvider(claim=draft)
    runtime.step()
    event = next(item for item in history.get_events() if item.type == "dialogue_input")
    claim = event.dialogue_payload.claim
    assert type(claim) is AttributedClaim
    assert (claim.speaker_id, claim.recipient_id, claim.source_event_id) == (
        "npc-a", "npc-b", event.id,
    )
    assert claim.value is False and claim.valid_from_tick == 0
    assert event.changes == [{"utterance": "I observed that the room light is on."}]
    assert runtime.context.world_state.environment["room"]["light_on"] is True
    persisted = history.export_persisted_records()
    restored, _, _ = verify_and_restore_event_records(
        persisted, codec=cognitive_snapshot_codec(), trust=trust,
        expected_timeline_id="social-timeline",
    )
    restored_event = next(item for item in restored if item.id == event.id)
    assert restored_event.dialogue_payload.claim == claim
    from dataclasses import replace
    import pytest
    with pytest.raises(ValueError, match="digest"):
        replace(claim, recipient_id="npc-a")
    damaged = replace(event, dialogue_payload=None)
    assert not damaged.has_trusted_source("system")
    from cognitive_world.core.attributed_claim import validate_claim_for_event
    with pytest.raises(PermissionError):
        validate_claim_for_event(claim, event=damaged)


def test_d1_invalid_claim_contract_is_rejected_without_downgrade():
    from cognitive_world.core.persistence import HmacPersistenceTrust
    trust = HmacPersistenceTrust(b"stage1-claim-reject-test-key-material-32")
    draft = AttributedClaimDraft(
        "room", "unregistered.property", "boolean", True, 0, None, "room:room",
    )
    runtime, _, _, history, _ = _world(
        communication=True, trust=trust, shared_memory_store=MemoryStore(),
        structured_claim=True,
    )
    runtime.npc_communication_provider = _CommunicationProvider(claim=draft)
    runtime.step()
    assert not any(item.type == "dialogue_input" for item in history.get_events())
    assert history.get_processing_status("npc-dialogue:action-proposal:npc-a") is None


def test_d1_registered_property_type_mismatch_is_rejected_without_event():
    from cognitive_world.core.persistence import HmacPersistenceTrust
    trust = HmacPersistenceTrust(b"stage1-claim-type-reject-test-key-32bytes")
    draft = AttributedClaimDraft(
        "room", "environment.light_on", "string", "true", 0, None, "room:room",
    )
    runtime, _, _, history, _ = _world(
        communication=True, trust=trust, shared_memory_store=MemoryStore(),
        structured_claim=True,
    )
    runtime.npc_communication_provider = _CommunicationProvider(claim=draft)
    runtime.step()
    assert not any(item.type == "dialogue_input" for item in history.get_events())


def test_d1_legacy_event_codec_does_not_infer_a_claim():
    import json
    from cognitive_world.core.event import Event
    from cognitive_world.core.persistence import PersistedValueCodec

    codec = PersistedValueCodec()
    legacy = Event("legacy-dialogue", "dialogue_input", "0", ["a", "b"],
                   changes=[{"utterance": "a statement"}])
    encoded = codec.encode(legacy)
    assert encoded["$record"] == "cognitive_world.core.event:Event"
    encoded["fields"].pop("dialogue_payload")
    restored = codec.loads(json.dumps(encoded).encode("utf-8"))
    assert restored.dialogue_payload is None


def test_d2_nonverbal_proof_requires_real_l1_consumption_and_revalidates_source():
    from cognitive_world.core.persistence import HmacPersistenceTrust
    from cognitive_world.cognition.l1_consumption_proof import (
        NONVERBAL_PROOF_MEMORY_TYPE, NONVERBAL_PROOF_PURPOSE,
        NonverbalL1ConsumptionProof, verify_nonverbal_proof,
    )

    trust = HmacPersistenceTrust(b"stage1-nonverbal-test-key-material-32")
    memory = MemoryStore()
    runtime, cognition, _, history, _ = _world(
        communication=False, trust=trust, shared_memory_store=memory,
        complete_environment=True,
    )
    assert not any(item.type == NONVERBAL_PROOF_MEMORY_TYPE for item in memory.get_all_memories())
    runtime.step()
    records = [item for item in memory.get_all_memories()
               if item.type == NONVERBAL_PROOF_MEMORY_TYPE]
    assert {item.owner_id for item in records} == {"npc-a", "npc-b"}
    assert all(type(item.content) is NonverbalL1ConsumptionProof for item in records)
    for item in records:
        assert trust.verify(
            NONVERBAL_PROOF_PURPOSE, item.content.body(),
            bytes.fromhex(item.content.signature_hex),
        )
        verify_nonverbal_proof(
            item.content, history=history, trust=trust,
            checkpoint_timeline_id="social-timeline",
            checkpoint_tick=runtime.context.clock.current_time,
        )
    from dataclasses import replace
    import pytest
    with pytest.raises(PermissionError):
        verify_nonverbal_proof(
            replace(records[0].content, owner_id="unregistered-owner"),
            history=history, trust=trust, checkpoint_timeline_id="social-timeline",
            checkpoint_tick=runtime.context.clock.current_time,
        )
    with pytest.raises(PermissionError):
        verify_nonverbal_proof(
            replace(records[0].content, visibility_rule="unknown-rule/v1"),
            history=history, trust=trust, checkpoint_timeline_id="social-timeline",
            checkpoint_tick=runtime.context.clock.current_time,
        )
    with pytest.raises(PermissionError):
        verify_nonverbal_proof(
            replace(records[0].content, version=2),
            history=history, trust=trust, checkpoint_timeline_id="social-timeline",
            checkpoint_tick=runtime.context.clock.current_time,
        )
    with pytest.raises(PermissionError):
        verify_nonverbal_proof(
            replace(records[0].content, source_event_id="unknown-event"),
            history=history, trust=trust, checkpoint_timeline_id="social-timeline",
            checkpoint_tick=runtime.context.clock.current_time,
        )
    proof = records[0].content
    for changes in (
        {"signature_hex": "00" * 32},
        {"proof_id": "nonverbal-proof-tampered"},
        {"observation_sha256": "0" * 64},
        {"fact_id": "unknown-fact"},
        {"source_timeline_id": "unrelated-timeline"},
        {"consumption_timeline_id": "unrelated-timeline"},
        {"event_tick": proof.event_tick + 1},
    ):
        with pytest.raises(PermissionError):
            verify_nonverbal_proof(
                replace(proof, **changes), history=history, trust=trust,
                checkpoint_timeline_id="social-timeline",
                checkpoint_tick=runtime.context.clock.current_time,
            )
    from cognitive_world.event.history import EventHistory
    with pytest.raises(PermissionError):
        verify_nonverbal_proof(
            proof, history=EventHistory(timeline_id="unrelated-timeline"),
            trust=trust, checkpoint_timeline_id="social-timeline",
            checkpoint_tick=runtime.context.clock.current_time,
        )
    contexts = tuple(runtime.cognition_context_provider(agent)
                     for agent in runtime.context.agent_registry.all_agents())
    for context in contexts:
        context.bind_write_fence(runtime.write_fence)
    from cognitive_world.cognition.snapshot import (
        CognitiveStateSnapshot, cognitive_snapshot_codec, reconstruct_isolated,
        _COGNITIVE_SNAPSHOT_PURPOSE,
    )
    with runtime.write_fence.operation():
        snapshot = CognitiveStateSnapshot.capture(
            cognition=cognition, memory_store=memory, runtime=runtime,
            agent_contexts=contexts, timeline_id="social-timeline", trust=trust,
        )
    codec = cognitive_snapshot_codec()
    stores = list(snapshot.body.stores)
    memory_index = next(index for index, store in enumerate(stores)
                        if store.store_name == "memories")
    memory_snapshot = stores[memory_index]
    proof_record = next(record for record in memory_snapshot.records
                        if record.value.type == NONVERBAL_PROOF_MEMORY_TYPE)
    changed_memory = replace(
        proof_record.value,
        content=replace(proof_record.value.content, signature_hex="00" * 32),
    )
    changed_records = tuple(
        replace(record, value=changed_memory) if record is proof_record else record
        for record in memory_snapshot.records
    )
    from cognitive_world.core.persistence import sha256_hex
    changed_store = replace(memory_snapshot, records=changed_records,
                            state_version="sha256:pending")
    stores[memory_index] = replace(
        changed_store,
        state_version="sha256:" + sha256_hex(codec.dumps(changed_store)),
    )
    forged_body = replace(snapshot.body, stores=tuple(stores))
    forged_body_bytes = codec.dumps(forged_body)
    forged_snapshot = CognitiveStateSnapshot(
        forged_body, "sha256:" + sha256_hex(forged_body_bytes),
        trust.sign(_COGNITIVE_SNAPSHOT_PURPOSE, forged_body_bytes).hex(),
    )
    with pytest.raises((PermissionError, ValueError)):
        reconstruct_isolated(
            forged_snapshot, trust=trust,
            expected_agents=snapshot.body.expected_agents,
            event_history=history,
        )
    isolated = reconstruct_isolated(
        CognitiveStateSnapshot.from_bytes(snapshot.to_bytes(), trust=trust),
        trust=trust, expected_agents=snapshot.body.expected_agents,
        event_history=history,
    )
    for item in records:
        restored = isolated.memory_store.get_memory(item.id)
        assert restored == item
        verify_nonverbal_proof(
            restored.content, history=history, trust=trust,
            checkpoint_timeline_id="social-timeline",
            checkpoint_tick=snapshot.body.simulation_tick,
        )
    runtime.step()
    assert tuple(sorted(item.id for item in memory.get_all_memories()
                        if item.type == NONVERBAL_PROOF_MEMORY_TYPE)) == tuple(
        sorted(item.id for item in records)
    )


def test_nonverbal_proof_signature_verifies_in_independent_dpapi_process(tmp_path):
    import subprocess
    import sys
    import pytest
    from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
    from cognitive_world.cognition.l1_consumption_proof import (
        NONVERBAL_PROOF_MEMORY_TYPE, NONVERBAL_PROOF_PURPOSE,
    )

    if sys.platform != "win32":
        pytest.skip("Windows DPAPI is required")
    trust_path = tmp_path / "nonverbal-trust.json"
    trust = WindowsDpapiPersistenceTrust.initialize(trust_path)
    store = MemoryStore()
    runtime, _, _, _, _ = _world(
        communication=False, trust=trust, shared_memory_store=store,
        complete_environment=True,
    )
    runtime.step()
    proof = next(item.content for item in store.get_all_memories()
                 if item.type == NONVERBAL_PROOF_MEMORY_TYPE)
    script = (
        "import sys; from pathlib import Path; sys.path.insert(0, str(Path.cwd() / 'src')); "
        "from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust; "
        "trust=WindowsDpapiPersistenceTrust.open(sys.argv[1]); "
        "assert trust.verify(sys.argv[2], bytes.fromhex(sys.argv[3]), bytes.fromhex(sys.argv[4]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(trust_path), NONVERBAL_PROOF_PURPOSE,
         proof.body().hex(), proof.signature_hex],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_nonverbal_proof_core_uses_versioned_trusted_rule_configuration():
    from dataclasses import dataclass, replace
    import inspect
    import pytest
    import cognitive_world.cognition.l1_consumption_proof as proof_module
    from cognitive_world.core.persistence import HmacPersistenceTrust
    from cognitive_world.cognition.l1_consumption_proof import (
        NONVERBAL_PROOF_MEMORY_TYPE, NONVERBAL_PROOF_PURPOSE,
        L1ConsumptionIssuer, verify_nonverbal_proof,
    )
    from cognitive_world.observation.historical_rules import (
        HISTORICAL_OBSERVATION_RULES, HistoricalObservationRuleRegistry,
    )

    @dataclass(frozen=True)
    class SyntheticHistoricalRule:
        rule_id: str = "synthetic-observation"
        version: int = 7
        source_event_type: str = "room_light_changed"

        def supports_source(self, event, evidence):
            return event.type == self.source_event_type

        def issue(self, event, evidence, owner_id, fact_id):
            return HISTORICAL_OBSERVATION_RULES.by_reference(
                "room-light-on-colocated-sight/v1"
            ).issue(event, evidence, owner_id, fact_id)

    builtin = HISTORICAL_OBSERVATION_RULES.by_reference(
        "room-light-on-colocated-sight/v1"
    )
    synthetic = SyntheticHistoricalRule()
    configured = HistoricalObservationRuleRegistry((builtin, synthetic))
    assert configured.by_reference("room-light-on-colocated-sight/v1") is builtin
    assert configured.by_reference("synthetic-observation/v7") is synthetic
    assert "room-light-on-colocated-sight" not in inspect.getsource(proof_module)

    trust = HmacPersistenceTrust(b"stage11-synthetic-rule-test-key-material")
    memory = MemoryStore()
    runtime, cognition, _, history, _ = _world(
        communication=False, trust=trust, shared_memory_store=memory,
        complete_environment=True,
    )
    issuer_registry = HistoricalObservationRuleRegistry((synthetic,))
    runtime.agent_action_loop.agent_turn.l1_consumption_issuer = L1ConsumptionIssuer(
        history=history, clock=runtime.context.clock, trust=trust,
        fence=runtime.write_fence, rule_registry=issuer_registry,
    )
    runtime.step()
    records = tuple(item for item in memory.get_all_memories()
                    if item.type == NONVERBAL_PROOF_MEMORY_TYPE)
    assert {item.owner_id for item in records} == {"npc-a", "npc-b"}
    assert all(item.content.visibility_rule == "synthetic-observation/v7" for item in records)
    for item in records:
        verify_nonverbal_proof(
            item.content, history=history, trust=trust,
            checkpoint_timeline_id="social-timeline",
            checkpoint_tick=runtime.context.clock.current_time,
            rule_registry=issuer_registry,
        )

    unsigned_unknown_version = replace(
        records[0].content, visibility_rule="synthetic-observation/v8",
        signature_hex="pending",
    )
    unknown_version = replace(
        unsigned_unknown_version,
        signature_hex=trust.sign(
            NONVERBAL_PROOF_PURPOSE, unsigned_unknown_version.body(),
        ).hex(),
    )
    with pytest.raises(PermissionError, match="unknown"):
        verify_nonverbal_proof(
            unknown_version, history=history, trust=trust,
            checkpoint_timeline_id="social-timeline",
            checkpoint_tick=runtime.context.clock.current_time,
            rule_registry=configured,
        )

    contexts = tuple(runtime.cognition_context_provider(agent)
                     for agent in runtime.context.agent_registry.all_agents())
    for context in contexts:
        context.bind_write_fence(runtime.write_fence)
    from cognitive_world.cognition.snapshot import CognitiveStateSnapshot, reconstruct_isolated
    with runtime.write_fence.operation():
        snapshot = CognitiveStateSnapshot.capture(
            cognition=cognition, memory_store=memory, runtime=runtime,
            agent_contexts=contexts, timeline_id="social-timeline", trust=trust,
            historical_rule_registry=issuer_registry,
        )
    isolated = reconstruct_isolated(
        CognitiveStateSnapshot.from_bytes(snapshot.to_bytes(), trust=trust),
        trust=trust, expected_agents=snapshot.body.expected_agents,
        event_history=history, historical_rule_registry=issuer_registry,
    )
    assert {item.id for item in isolated.memory_store.get_all_memories()
            if item.type == NONVERBAL_PROOF_MEMORY_TYPE} == {item.id for item in records}

    class FailingRule(SyntheticHistoricalRule):
        def issue(self, event, evidence, owner_id, fact_id):
            raise RuntimeError("injected verifier failure")

    class WrongOwnerRule(SyntheticHistoricalRule):
        def issue(self, event, evidence, owner_id, fact_id):
            return replace(
                super().issue(event, evidence, owner_id, fact_id),
                observer_id="different-owner",
            )

    failing_registry = HistoricalObservationRuleRegistry((FailingRule(),))
    with pytest.raises(PermissionError, match="verification failed"):
        verify_nonverbal_proof(
            records[0].content, history=history, trust=trust,
            checkpoint_timeline_id="social-timeline",
            checkpoint_tick=runtime.context.clock.current_time,
            rule_registry=failing_registry,
        )
    with pytest.raises(PermissionError, match="historical Observation"):
        verify_nonverbal_proof(
            records[0].content, history=history, trust=trust,
            checkpoint_timeline_id="social-timeline",
            checkpoint_tick=runtime.context.clock.current_time,
            rule_registry=HistoricalObservationRuleRegistry((WrongOwnerRule(),)),
        )
    with pytest.raises(PermissionError):
        verify_nonverbal_proof(
            records[0].content, history=history, trust=trust,
            checkpoint_timeline_id="social-timeline", checkpoint_tick=10,
            rule_registry=HistoricalObservationRuleRegistry(()),
        )


def test_historical_rule_registration_rejects_missing_or_ambiguous_verifiers():
    import pytest
    from cognitive_world.observation.historical_rules import HistoricalObservationRuleRegistry

    class MissingVerifier:
        rule_id = "missing-verifier"
        version = 1
        source_event_type = "some_event"

    with pytest.raises(TypeError, match="verifier contract"):
        HistoricalObservationRuleRegistry((MissingVerifier(),))

    from cognitive_world.core.persistence import HmacPersistenceTrust
    trust = HmacPersistenceTrust(b"stage11-ambiguous-rule-test-key-material")
    memory = MemoryStore()
    runtime, _, _, history, _ = _world(
        communication=False, trust=trust, shared_memory_store=memory,
        complete_environment=True,
    )
    runtime.step()
    from cognitive_world.observation.historical_rules import HISTORICAL_OBSERVATION_RULES
    rule = HISTORICAL_OBSERVATION_RULES.by_reference("room-light-on-colocated-sight/v1")
    from dataclasses import replace
    registry = HistoricalObservationRuleRegistry((
        rule, replace(rule, rule_id="ambiguous-rule", version=2),
    ))
    event = next(item for item in history.get_events() if item.type == "room_light_changed")
    with pytest.raises(PermissionError, match="ambiguous"):
        registry.for_source(event, history.get_processing_evidence(event.id))


def test_l1_proof_real_dpapi_signature_verifies_in_independent_process(tmp_path):
    import subprocess
    import sys
    import pytest
    from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
    from cognitive_world.cognition.l1_consumption_proof import PROOF_MEMORY_TYPE

    if sys.platform != "win32":
        pytest.skip("Windows DPAPI is required")
    trust_path = tmp_path / "l1-trust"
    trust = WindowsDpapiPersistenceTrust.initialize(trust_path)
    store = MemoryStore()
    runtime, _, _, _, _ = _world(
        communication=True, trust=trust, shared_memory_store=store,
    )
    runtime.step()
    proof = next(item.content for item in store.get_all_memories()
                 if item.type == PROOF_MEMORY_TYPE)
    script = (
        "import sys; from pathlib import Path; sys.path.insert(0, str(Path.cwd() / 'src')); "
        "from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust; "
        "from cognitive_world.cognition.l1_consumption_proof import PROOF_PURPOSE; "
        "trust=WindowsDpapiPersistenceTrust.open(sys.argv[1]); "
        "assert trust.verify(PROOF_PURPOSE, bytes.fromhex(sys.argv[2]), bytes.fromhex(sys.argv[3]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(trust_path), proof.body().hex(),
         proof.signature_hex], stdin=subprocess.DEVNULL, capture_output=True,
        text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_speech_alone_cannot_revise_and_explicit_reject_defer_are_non_writes():
    from cognitive_world.cognition.causal_review import CognitiveBeliefReview, CognitiveReviewInput, CognitiveEvidence, BeliefSnapshot

    cognition = CognitionContainer()
    prior = Belief("belief-b", "npc-b", {"claim": "unsettled"}, [], 0.4)
    cognition.add_belief(prior)
    request = CognitiveReviewInput(
        "npc-b",
        (CognitiveEvidence("speech", "event-speech", {
            "fact_type": "social_input", "predicate": "utterance_delivered", "value": "claim",
        }),),
        (BeliefSnapshot("belief-b", prior.content, prior.confidence, ()),),
        "speech",
    )
    accept_without_independent = CognitiveReview(
        "accept", "none",
        BeliefRevisionSuggestion("belief-b", {"claim": "claim"}, 0.9, "reason", ("speech",)),
        "accept",
    )
    try:
        CognitiveBeliefReview().apply(accept_without_independent, request, cognition)
    except PermissionError:
        pass
    else:
        raise AssertionError("speech alone must not authorize a Belief revision")
    assert cognition.get_belief("belief-b") == prior
    assert CognitiveReview("contradicted", "direct evidence", outcome="reject").disposition == "reject"
    assert CognitiveReview("unclear", "insufficient evidence", outcome="defer").disposition == "defer"
