from threading import Event as ThreadEvent, Thread

import pytest

from cognitive_world.cognition.memory import Memory
from cognitive_world.cognition.memory_proposal import MemoryProposal
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.cognition.container import CognitionContainer
from cognitive_world.cognition.personality import Personality
from cognitive_world.agent.cognition_context import CognitionContext
from cognitive_world.agent.character import Character
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.agent.turn import AgentTurn
from cognitive_world.event.history import EventHistory
from cognitive_world.core.event import Event
from cognitive_world.memory.memory_decision import MemoryDecisionAuthority
from cognitive_world.memory.memory_persistence import MemoryPersistence
from cognitive_world.memory.memory_write_factory import MemoryWriteFactory
from cognitive_world.runtime.write_fence import RuntimeWriteFence


def _request(proposal):
    decision = MemoryDecisionAuthority().issue(
        proposal, accepted=True, importance=proposal.importance,
        memory_type=proposal.memory_type,
    )
    return MemoryWriteFactory().create_request(decision, proposal)


def _history():
    history = EventHistory()
    history.append(Event(id="source", type="record", timestamp="t0"))
    return history


def test_memory_persistence_accepts_current_candidate_and_rejects_late_candidate():
    fence = RuntimeWriteFence("memory-session")
    store = MemoryStore()
    persistence = MemoryPersistence(store, _history(), write_fence=fence)
    with fence.operation():
        proposal = MemoryProposal("m1", "source", "owner", "experience", "current", 0.7)
        request = _request(proposal)
        saved = persistence.save(request)
    assert store.get_memory(saved.id) == saved

    with fence.operation():
        stale_proposal = MemoryProposal("m2", "source", "owner", "experience", "late", 0.7)
        stale_request = _request(stale_proposal)
        with pytest.raises(AttributeError, match="origin is immutable"):
            stale_proposal._runtime_write_permit = fence.capture()
    fence.freeze_and_advance()
    fence.unfreeze()

    with fence.operation():
        with pytest.raises(PermissionError, match="candidate is not bound"):
            persistence.save(stale_request)
        # Reissuing a new request from the old proposal preserves its origin.
        with pytest.raises(PermissionError, match="candidate is not bound"):
            persistence.save(_request(stale_proposal))
    assert store.get_memory("memory:m2") is None
    assert set(store.memories) == {"memory:m1"}


def test_memory_store_final_commit_boundary_rejects_stale_context():
    fence = RuntimeWriteFence()
    store = MemoryStore(write_fence=fence)
    with fence.operation():
        pass
    fence.freeze_and_advance()
    fence.unfreeze()
    with pytest.raises(PermissionError):
        store._commit_memory(Memory("m", "owner", "experience", "late", 0.5, "source"))
    assert store.get_memory("m") is None


def test_memory_commit_and_generation_change_are_serialized():
    entered, release, frozen = ThreadEvent(), ThreadEvent(), ThreadEvent()

    class BlockingStore(MemoryStore):
        def _commit_memory(self, memory):
            entered.set()
            assert release.wait(2)
            super()._commit_memory(memory)

    fence = RuntimeWriteFence()
    store = BlockingStore(write_fence=fence)
    persistence = MemoryPersistence(store, _history())
    order = []

    def commit():
        with fence.operation():
            proposal = MemoryProposal("race", "source", "owner", "experience", "commit", 0.8)
            persistence.save(_request(proposal))
        order.append("commit")

    def freeze():
        assert entered.wait(2)
        fence.freeze_and_advance()
        order.append("freeze")
        frozen.set()

    commit_thread = Thread(target=commit)
    freeze_thread = Thread(target=freeze)
    commit_thread.start()
    freeze_thread.start()
    assert entered.wait(2)
    release.set()
    assert frozen.wait(2)
    commit_thread.join(2)
    freeze_thread.join(2)
    assert order == ["commit", "freeze"]
    assert store.get_memory("memory:race") is not None


def test_normal_agent_turn_binds_canonical_memory_and_keeps_personality_immutable():
    owner = "owner"
    container = CognitionContainer()
    initial = Personality(owner_id=owner, traits={"steady": True})
    container.add_personality(initial)
    memory_store = MemoryStore()
    character = Character("character", owner, owner)
    cognition = CognitionContext.from_character(character, container, memory_store)
    agent = RuntimeAgent(owner, character.id)
    fence = RuntimeWriteFence()

    AgentTurn(write_fence=fence).prepare_decision_context(agent, cognition)

    assert memory_store.write_fence is fence
    assert container.personality_store.write_fence is fence
    assert container.personality_store.get(owner) == initial
    with pytest.raises(PermissionError, match="no governed runtime evolution"):
        container.personality_store.update(
            Personality(owner_id=owner, traits={"steady": False})
        )
