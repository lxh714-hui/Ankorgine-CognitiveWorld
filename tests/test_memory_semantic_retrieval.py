"""Semantic retrieval is a bounded candidate channel, never a read grant."""

import re

import pytest

from cognitive_world.agent import AgentTurn, Character, CognitionContext, RuntimeAgent
from cognitive_world.cognition import CognitionContainer, Memory, MemoryQuery, MemoryStore
from cognitive_world.cognition.memory_semantic_retrieval import (
    HybridMemoryRetriever,
    MemorySemanticIndex,
)
from cognitive_world.cognition.metacognition import MetacognitiveFeedback
from cognitive_world.runtime.write_fence import RuntimeWriteFence


OWNER = "agent-semantic"


class _TokenEmbedding:
    """Test-only configured concept vectors, independent of Memory IDs/gold."""

    def __init__(self):
        self.calls = []
        self.vectors = {
            "watchman": (3.0, 0.0, 0.0),
            "sentry": (3.0, 0.0, 0.0),
            "north": (0.0, 2.0, 0.0),
            "northern": (0.0, 2.0, 0.0),
            "gate": (0.0, 0.0, 1.0),
            "entry": (0.0, 0.0, 1.0),
        }

    def embed(self, text):
        self.calls.append(text)
        components = [0.0, 0.0, 0.0]
        for token in re.findall(r"[a-z]+", text.casefold()):
            vector = self.vectors.get(token)
            if vector is not None:
                components = [a + b for a, b in zip(components, vector, strict=True)]
        return tuple(components)


class _CountingStore(MemoryStore):
    def __init__(self):
        super().__init__()
        self.read_ids = []

    def get_memory(self, memory_id):
        self.read_ids.append(memory_id)
        return super().get_memory(memory_id)


def _context(memories, refs, *, store=None, feedback=None):
    store = store or _CountingStore()
    for memory in memories:
        store._commit_memory(memory)
    character = Character(
        "character-semantic", OWNER, "personality-semantic", memory_ids=list(refs)
    )
    context = CognitionContext.from_character(
        character, CognitionContainer(), store, metacognitive_feedback=feedback,
    )
    return context, store


def test_semantic_index_rebuilds_from_authorized_canonical_records_and_rechecks_content():
    memories = (
        Memory("m-watch", OWNER, "experience", "watchman at north gate", 0.6, "event-watch"),
        Memory("m-unlinked", OWNER, "experience", "sentry at northern entry", 0.7, "event-private"),
        Memory("m-other", "agent-other", "experience", "sentry at northern entry", 0.7, "event-other"),
    )
    context, store = _context(memories, ("m-watch",))
    provider = _TokenEmbedding()
    index = MemorySemanticIndex.rebuild(
        store=store, owner_id=OWNER,
        allowed_memory_ids=context._memory_ids, provider=provider,
    )
    rebuilt = MemorySemanticIndex.rebuild(
        store=store, owner_id=OWNER,
        allowed_memory_ids=context._memory_ids, provider=provider,
    )
    query = MemoryQuery(OWNER, "sentry northern entry", 5)
    first = index.candidates(
        query, store=store, allowed_memory_ids=context._memory_ids,
        provider=provider, minimum_similarity=0.8,
    )
    second = rebuilt.candidates(
        query, store=store, allowed_memory_ids=context._memory_ids,
        provider=provider, minimum_similarity=0.8,
    )
    assert first == second
    assert tuple(item.memory.id for item in first) == ("m-watch",)
    assert first[0].memory.source_event == "event-watch"
    assert 0.8 <= first[0].similarity <= 1.0
    assert set(store.read_ids) == {"m-watch"}
    assert all("private" not in text for text in provider.calls)

    # An index built from an older canonical record cannot emit a changed
    # record under the same ID; a fresh query builds from the current Store.
    replacement = _CountingStore()
    replacement._commit_memory(Memory(
        "m-watch", OWNER, "experience", "unrelated harbor note", 0.6, "event-watch",
    ))
    assert index.candidates(
        query, store=replacement, allowed_memory_ids=context._memory_ids,
        provider=provider, minimum_similarity=0.8,
    ) == ()
    assert index.candidates(
        query, store=store, allowed_memory_ids=(),
        provider=provider, minimum_similarity=0.8,
    ) == ()
    assert index.candidates(
        query, store=_CountingStore(), allowed_memory_ids=context._memory_ids,
        provider=provider, minimum_similarity=0.8,
    ) == ()
    assert MemorySemanticIndex.rebuild(
        store=replacement, owner_id=OWNER,
        allowed_memory_ids=context._memory_ids, provider=provider,
    ).candidates(
        query, store=replacement, allowed_memory_ids=context._memory_ids,
        provider=provider, minimum_similarity=0.8,
    ) == ()


def test_hybrid_retrieval_adds_alias_memory_without_changing_lexical_order_or_scope():
    memories = (
        Memory("m-lexical", OWNER, "experience", "sentry reported a lantern", 0.6, "event-1"),
        Memory("m-alias", OWNER, "experience", "watchman at north gate", 0.5, "event-2"),
        Memory("m-unlinked", OWNER, "experience", "sentry at northern entry", 0.9, "event-3"),
        Memory("m-other", "agent-other", "experience", "sentry at northern entry", 0.9, "event-4"),
    )
    context, store = _context(memories, ("m-lexical", "m-alias"))
    context.memory_retriever = HybridMemoryRetriever(
        store, _TokenEmbedding(), minimum_similarity=0.8,
    )
    before = store.get_all_memories()
    result = context.get_relevant_memories(MemoryQuery(OWNER, "sentry northern entry", 5))
    assert tuple(item.id for item in result) == ("m-lexical", "m-alias")
    assert tuple(item.source_event for item in result) == ("event-1", "event-2")
    assert set(store.read_ids) == {"m-lexical", "m-alias"}
    assert store.get_all_memories() == before
    assert context.get_relevant_memories(MemoryQuery(OWNER, "silver compass observatory", 5)) == ()


@pytest.mark.parametrize("failure", ["unavailable", "timeout", "dimension"])
def test_provider_failure_keeps_original_lexical_result(failure):
    memories = (
        Memory("m-watch", OWNER, "experience", "watchman at north gate", 0.6, "event-1"),
        Memory("m-gate", OWNER, "experience", "north gate note", 0.5, "event-2"),
    )
    context, store = _context(memories, ("m-watch", "m-gate"))

    class _BrokenProvider:
        def embed(self, text):
            if failure == "timeout":
                raise TimeoutError("private provider error")
            return (1.0, 0.0) if "watchman" in text else (1.0, 0.0, 0.0)

    context.memory_retriever = HybridMemoryRetriever(
        store, None if failure == "unavailable" else _BrokenProvider(),
    )
    result = context.get_relevant_memories(MemoryQuery(OWNER, "watchman", 5))
    assert tuple(item.id for item in result) == ("m-watch",)


def test_semantic_scan_and_result_count_are_bounded():
    memories = tuple(
        Memory(f"m-{index:03d}", OWNER, "experience", "watchman", 0.5, f"event-{index}")
        for index in range(70)
    )
    refs = tuple(memory.id for memory in memories)
    context, store = _context(memories, refs)
    provider = _TokenEmbedding()
    context.memory_retriever = HybridMemoryRetriever(store, provider)
    result = context.get_relevant_memories(MemoryQuery(OWNER, "sentry", 99))
    assert len(result) == 5
    assert tuple(item.id for item in result) == refs[:5]
    assert len(provider.calls) == 65  # 64 authorized records + one query
    assert set(store.read_ids) <= set(refs)


def test_runtime_generation_change_disables_semantic_channel_but_keeps_lexical():
    memories = (
        Memory("m-lexical", OWNER, "experience", "sentry at the gate", 0.5, "event-1"),
        Memory("m-alias", OWNER, "experience", "watchman at north gate", 0.5, "event-2"),
    )
    context, store = _context(memories, ("m-lexical", "m-alias"))
    fence = RuntimeWriteFence("semantic-session")
    context.memory_retriever = HybridMemoryRetriever(store, _TokenEmbedding(), runtime_fence=fence)
    fence.freeze_and_advance()
    result = context.get_relevant_memories(MemoryQuery(OWNER, "sentry", 5))
    assert tuple(item.id for item in result) == ("m-lexical",)


def test_agent_turn_uses_opt_in_semantic_channel_for_alias_without_store_write():
    from cognitive_world.decision.action_proposal import ActionProposal

    memory = Memory("m-watch", OWNER, "experience", "watchman at north gate", 0.6, "event-1")
    feedback = MetacognitiveFeedback(
        OWNER, memory_queries=(MemoryQuery(OWNER, "sentry northern entry", 5),),
    )
    context, store = _context((memory,), (memory.id,), feedback=feedback)
    context.memory_retriever = HybridMemoryRetriever(store, _TokenEmbedding())
    before = store.get_all_memories()

    class _Decision:
        def __init__(self):
            self.context = None

        def propose(self, decision_context):
            self.context = decision_context
            return ActionProposal("proposal-semantic", OWNER, "wait")

    decision = _Decision()
    AgentTurn().execute(RuntimeAgent(OWNER, "character-semantic"), context, decision)
    assert tuple(item.id for item in decision.context.long_term_memories) == (memory.id,)
    assert decision.context.long_term_memories[0].source_event == "event-1"
    assert store.get_all_memories() == before
