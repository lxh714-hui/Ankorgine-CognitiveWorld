"""System-only cognition records stay outside ordinary semantic Memory views."""

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys

import pytest

from cognitive_world.agent.character import Character
from cognitive_world.agent.cognition_context import CognitionContext
from cognitive_world.cognition.l1_consumption_proof import (
    L1ConsumptionProof,
    NonverbalL1ConsumptionProof,
    NONVERBAL_PROOF_MEMORY_TYPE,
    PROOF_MEMORY_TYPE,
    verify_nonverbal_proof,
    verify_proof,
)
from cognitive_world.cognition.memory import Memory, SystemOnlyMemoryContent
from cognitive_world.cognition.memory_retrieval import (
    MemoryQuery, MemoryRetriever, MemorySnapshot,
)
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.cognition.container import CognitionContainer
from cognitive_world.cognition.snapshot import (
    CognitiveStateSnapshot,
    reconstruct_isolated,
)
from cognitive_world.memory.memory_decision import MemoryDecisionAuthority
from cognitive_world.memory.memory_persistence import MemoryPersistence
from cognitive_world.cognition.memory_proposal import MemoryProposal
from cognitive_world.memory.memory_write_factory import MemoryWriteFactory
from cognitive_world.core.persistence import HmacPersistenceTrust
from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust

from test_npc_social_interaction import _world


def _make_runtime(kind: str):
    trust = HmacPersistenceTrust(b"semantic-visibility-test-key-material-32")
    store = MemoryStore()
    runtime, _, _, history, _ = _world(
        communication=kind == "verbal",
        trust=trust,
        shared_memory_store=store,
        complete_environment=kind == "nonverbal",
    )
    runtime.step()
    proof_type = PROOF_MEMORY_TYPE if kind == "verbal" else NONVERBAL_PROOF_MEMORY_TYPE
    record = next(
        item for item in store.get_all_memories()
        if item.type == proof_type and item.owner_id == "npc-b"
    )
    return runtime, trust, store, history, record


def _context_with_links(runtime, owner_id: str, memory_ids: list[str]) -> CognitionContext:
    agent = runtime.context.agent_registry.get(owner_id)
    original = runtime.cognition_context_provider(agent)
    character = Character(
        original.character_id, owner_id, original._personality_id or "", memory_ids=memory_ids,
        belief_ids=[item.id for item in original.get_beliefs()],
        goal_ids=[item.goal_id for item in original.get_goals()],
    )
    return CognitionContext.from_character(
        character,
        original.cognition_container,
        original.memory_store,
        memory_retriever=original.memory_retriever,
        observation_store=original.observation_store,
    )


def _write_ordinary_memory(runtime, store, history, owner_id: str, source_event_id: str,
                          content: str):
    persistence = MemoryPersistence(store, history, write_fence=runtime.write_fence)
    with runtime.write_fence.operation():
        proposal = MemoryProposal(
            id=f"semantic-visibility-{owner_id}",
            source_event_id=source_event_id,
            owner_id=owner_id,
            memory_type="experience",
            content=content,
            importance=0.6,
        )
        decision = MemoryDecisionAuthority().issue(
            proposal, accepted=True, importance=proposal.importance,
            memory_type=proposal.memory_type,
        )
        request = MemoryWriteFactory().create_request(decision, proposal)
        return persistence.save(request)


@pytest.mark.parametrize("kind", ("verbal", "nonverbal"))
def test_system_proofs_are_hidden_from_explicit_character_memory_links_and_survive_snapshot(kind, tmp_path):
    runtime, trust, store, history, proof_record = _make_runtime(kind)
    ordinary = _write_ordinary_memory(
        runtime, store, history, "npc-b", proof_record.source_event,
        proof_record.content.visibility_rule,
    )
    context = _context_with_links(runtime, "npc-b", [proof_record.id, ordinary.id])

    # Both the ordinary list and relevance-ranked view use the same boundary,
    # even where the proof text would match the query.
    assert tuple(item.id for item in context.get_memories()) == (ordinary.id,)
    query = MemoryQuery(
        owner_id="npc-b", query=proof_record.content.visibility_rule, limit=5,
    )
    relevant = context.get_relevant_memories(query)
    assert tuple(item.id for item in relevant) == (ordinary.id,)
    assert proof_record.id not in {item.id for item in relevant}
    direct = MemoryRetriever(store).retrieve(
        query, allowed_memory_ids=(proof_record.id, ordinary.id),
    )
    assert tuple(item.id for item in direct) == (ordinary.id,)

    # System proofs remain available to their trusted verifier and canonical
    # persistence path; semantic filtering does not remove or rewrite them.
    assert store.get_memory(proof_record.id) == proof_record
    if type(proof_record.content) is L1ConsumptionProof:
        verify_proof(
            proof_record.content, history=history, trust=trust,
            checkpoint_timeline_id=history.timeline_id,
            checkpoint_tick=runtime.context.clock.current_time,
        )
    else:
        assert type(proof_record.content) is NonverbalL1ConsumptionProof
        verify_nonverbal_proof(
            proof_record.content, history=history, trust=trust,
            checkpoint_timeline_id=history.timeline_id,
            checkpoint_tick=runtime.context.clock.current_time,
        )

    contexts = []
    for agent in runtime.context.agent_registry.all_agents():
        if agent.agent_id == "npc-b":
            contexts.append(context)
        else:
            contexts.append(runtime.cognition_context_provider(agent))
    with runtime.write_fence.operation():
        snapshot = CognitiveStateSnapshot.capture(
            cognition=context.cognition_container,
            memory_store=store,
            runtime=runtime,
            agent_contexts=tuple(contexts),
            timeline_id=history.timeline_id,
            trust=trust,
        )
    restored = reconstruct_isolated(
        CognitiveStateSnapshot.from_bytes(snapshot.to_bytes(), trust=trust),
        trust=trust,
        expected_agents=snapshot.body.expected_agents,
        event_history=history,
    )
    restored_context = CognitionContext.from_character(
        Character(
            context.character_id, "npc-b", context._personality_id or "",
            memory_ids=[proof_record.id, ordinary.id],
        ),
        restored.cognition,
        restored.memory_store,
    )
    assert tuple(item.id for item in restored_context.get_memories()) == (ordinary.id,)
    assert tuple(item.id for item in restored_context.get_relevant_memories(query)) == (ordinary.id,)
    assert restored.memory_store.get_memory(proof_record.id) == proof_record

    # Exercise the supported SaveManager -> isolated reconstruction ->
    # RestoreCoordinator path with an explicit proof ID in the saved link list.
    from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
    from cognitive_world.runtime.save_manager import SaveManager
    from test_runtime_reconstruction import LocalRuntimeAssembler, _dependency_manifest

    manager = SaveManager(tmp_path / "saves", trust=trust)
    for item in contexts:
        item.bind_write_fence(runtime.write_fence)
    metadata = manager.create_manual_save(
        runtime=runtime,
        cognition=context.cognition_container,
        memory_store=store,
        agent_contexts=tuple(contexts),
    )
    active, _, _, _, _ = _world(
        communication=False,
        trust=trust,
        shared_memory_store=MemoryStore(),
        timeline_id=history.timeline_id,
    )
    staged = manager.stage_restore(
        metadata.save_id,
        timeline_id=metadata.timeline_id,
        active_runtime=active,
        assembler=LocalRuntimeAssembler(trust),
        dependencies=_dependency_manifest(),
        new_timeline_id=f"{history.timeline_id}-visibility-restore",
    )
    resumed = RestoreCoordinator(ActiveRuntimeSlot(active)).activate(staged)
    resumed_context = resumed.cognition_context_provider(
        resumed.context.agent_registry.get("npc-b")
    )
    assert tuple(item.id for item in resumed_context.get_memories()) == (ordinary.id,)
    assert tuple(item.id for item in resumed_context.get_relevant_memories(query)) == (ordinary.id,)
    assert resumed_context.memory_store.get_memory(proof_record.id) == proof_record


@dataclass(frozen=True)
class _UnregisteredSystemRecord(SystemOnlyMemoryContent):
    payload: str


@pytest.mark.parametrize(
    "record_type,content",
    (
        (PROOF_MEMORY_TYPE, "malformed verbal proof"),
        (NONVERBAL_PROOF_MEMORY_TYPE, "malformed nonverbal proof"),
        ("future-system-record-v9", _UnregisteredSystemRecord("opaque")),
    ),
)
def test_unknown_or_inconsistent_system_classification_fails_closed(record_type, content):
    bad = Memory("system-record", "owner", record_type, content, 0.0, "source")
    ordinary = Memory("ordinary", "owner", "experience", "ordinary note", 0.5, "source")
    store = MemoryStore.from_isolated_snapshot((bad, ordinary))
    context = CognitionContext.from_character(
        Character("character", "owner", "", memory_ids=[bad.id, ordinary.id]),
        CognitionContainer(),
        store,
    )

    assert tuple(item.id for item in context.get_memories()) == (ordinary.id,)
    assert tuple(item.id for item in context.get_relevant_memories(
        MemoryQuery("owner", "ordinary note", 5),
    )) == (ordinary.id,)
    with pytest.raises(PermissionError):
        MemorySnapshot.from_memory(bad)
    with pytest.raises(PermissionError):
        MemoryStore()._commit_memory(bad)


@pytest.mark.skipif(os.name != "nt", reason="real Windows DPAPI cross-process acceptance")
def test_nonverbal_system_proof_stays_hidden_after_dpapi_save_restore_with_explicit_link(
    tmp_path,
):
    """A DPAPI-restored canonical proof remains system-only under explicit Character linkage."""
    trust_path = tmp_path / "trust-ring.json"
    trust = WindowsDpapiPersistenceTrust.initialize(trust_path)
    memory_store = MemoryStore()
    runtime, _, _, history, _ = _world(
        communication=False,
        trust=trust,
        shared_memory_store=memory_store,
        complete_environment=True,
    )
    runtime.step()

    proof_record = next(
        memory for memory in memory_store.get_all_memories()
        if memory.type == NONVERBAL_PROOF_MEMORY_TYPE and memory.owner_id == "npc-b"
    )
    assert type(proof_record.content) is NonverbalL1ConsumptionProof
    ordinary = _write_ordinary_memory(
        runtime, memory_store, history, "npc-b", proof_record.source_event,
        "authorized ordinary note for DPAPI retrieval check",
    )

    contexts = []
    for agent in runtime.context.agent_registry.all_agents():
        if agent.agent_id == "npc-b":
            # This supported Character/CognitionContext composition records a
            # literal proof ID in the signed AgentLink snapshot.
            contexts.append(_context_with_links(
                runtime, "npc-b", [proof_record.id, ordinary.id],
            ))
        else:
            contexts.append(runtime.cognition_context_provider(agent))
    for context in contexts:
        context.bind_write_fence(runtime.write_fence)

    from cognitive_world.runtime.save_manager import SaveManager

    manager = SaveManager(tmp_path / "saves", trust=trust)
    saved = manager.create_manual_save(
        runtime=runtime,
        cognition=contexts[0].cognition_container,
        memory_store=memory_store,
        agent_contexts=tuple(contexts),
    )
    assert manager.load_verified(saved.save_id, timeline_id=saved.timeline_id)

    script = r'''
import sys
from cognitive_world.agent.character import Character
from cognitive_world.cognition.l1_consumption_proof import (
    NONVERBAL_PROOF_MEMORY_TYPE, NonverbalL1ConsumptionProof,
    verify_nonverbal_proof,
)
from cognitive_world.cognition.memory_retrieval import MemoryQuery, MemoryRetriever
from cognitive_world.core.persistence import WindowsDpapiPersistenceTrust
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
from cognitive_world.runtime.save_manager import SaveManager
from test_npc_social_interaction import _world
from test_runtime_reconstruction import LocalRuntimeAssembler, _dependency_manifest

trust = WindowsDpapiPersistenceTrust.open(sys.argv[1])
manager = SaveManager(sys.argv[2], trust=trust)
saved = manager.load_verified(sys.argv[3], timeline_id=sys.argv[4])
active, _, _, _, _ = _world(
    communication=False, trust=trust, shared_memory_store=MemoryStore(),
    timeline_id=saved.metadata.timeline_id, complete_environment=True,
)
staged = manager.stage_restore(
    sys.argv[3], timeline_id=saved.metadata.timeline_id,
    active_runtime=active, assembler=LocalRuntimeAssembler(trust),
    dependencies=_dependency_manifest(), new_timeline_id='dpapi-visibility-child',
)
slot = ActiveRuntimeSlot(active)
restored = RestoreCoordinator(slot).activate(staged)
assert slot.current is restored
context = restored.cognition_context_provider(
    restored.context.agent_registry.get('npc-b'),
)
proof_id, ordinary_id = sys.argv[5], sys.argv[6]
assert proof_id in context._memory_ids
assert ordinary_id in context._memory_ids

proof = context.memory_store.get_memory(proof_id)
ordinary = context.memory_store.get_memory(ordinary_id)
assert proof is not None and proof.type == NONVERBAL_PROOF_MEMORY_TYPE
assert type(proof.content) is NonverbalL1ConsumptionProof
assert proof.owner_id == 'npc-b'
assert ordinary is not None and ordinary.owner_id == 'npc-b'
verify_nonverbal_proof(
    proof.content, history=restored.context.event_history, trust=trust,
    checkpoint_timeline_id='dpapi-visibility-child',
    checkpoint_tick=restored.context.clock.current_time,
)

query = MemoryQuery(
    owner_id='npc-b', query='authorized ordinary note for DPAPI retrieval check',
    limit=5,
)
assert tuple(item.id for item in context.get_memories()) == (ordinary_id,)
assert tuple(item.id for item in context.get_relevant_memories(query)) == (ordinary_id,)
assert tuple(item.id for item in MemoryRetriever(context.memory_store).retrieve(
    query, allowed_memory_ids=(proof_id, ordinary_id),
)) == (ordinary_id,)
assert context.memory_store.get_memory(proof_id) == proof
'''
    env = os.environ.copy()
    repo = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = os.pathsep.join((
        str(repo / "src"), str(repo / "tests"), env.get("PYTHONPATH", ""),
    ))
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(trust_path), str(manager.root),
         saved.save_id, saved.timeline_id, proof_record.id, ordinary.id],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=60, env=env,
    )
    assert result.returncode == 0, result.stderr
