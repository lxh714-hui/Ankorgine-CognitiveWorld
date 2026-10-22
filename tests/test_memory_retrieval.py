from dataclasses import FrozenInstanceError

import pytest

from cognitive_world.agent import AgentTurn, Character, CognitionContext, RuntimeAgent
from cognitive_world.cognition import (
    CognitionContainer,
    Goal,
    Memory,
    MemoryDecisionAuthority,
    MemoryPersistence,
    MemoryQuery,
    MemoryProposal,
    MemoryRetriever,
    MemoryStore,
    MemoryWriteFactory,
    MetacognitiveFeedback,
    Personality,
    BoundedMetacognitionPolicy,
)
from cognitive_world.cognition.memory_retrieval import MemorySnapshot
from cognitive_world.cognition.runtime import CognitionState
from cognitive_world.decision import AgentDecision, DecisionContext
from cognitive_world.event.history import EventHistory
from cognitive_world.core.event import Event


class CapturingDecision(AgentDecision):
    def propose(self, context):
        self.context = context
        return super().propose(context)


def _context_with_memories(memories, *, refs=None, owner="agent-a"):
    store = MemoryStore()
    for memory in memories:
        store._commit_memory(memory)
    character = Character(
        id=f"character-{owner}",
        agent_id=owner,
        personality_id=f"personality-{owner}",
        memory_ids=list(refs if refs is not None else [m.id for m in memories]),
    )
    return CognitionContext.from_character(
        character, CognitionContainer(), store
    ), store


def test_query_is_immutable_and_preserves_compatibility_fields():
    metadata = {"filters": {"type": ["experience"]}}
    query = MemoryQuery("agent-a", "old memory", 3, metadata)
    metadata["filters"]["type"].append("changed")
    assert query.owner_id == "agent-a"
    assert query.query == "old memory"
    assert query.limit == 3
    assert query.metadata["filters"]["type"] == ("experience",)
    with pytest.raises(FrozenInstanceError):
        query.query = "forged"


def test_retrieves_only_character_linked_owner_memory_and_keeps_source_event():
    own = Memory("m-own", "agent-a", "experience", {"note": "old red door"}, 0.7, "event-full-17")
    other = Memory("m-other", "agent-b", "experience", {"note": "old red door"}, 1.0, "event-18")
    unlinked = Memory("m-unlinked", "agent-a", "experience", {"note": "old red door"}, 1.0, "event-19")
    context, _ = _context_with_memories([own, other, unlinked], refs=["m-own"])

    result = context.get_relevant_memories(MemoryQuery("agent-a", "red door", 5))

    assert isinstance(result, tuple)
    assert len(result) == 1
    assert isinstance(result[0], MemorySnapshot)
    assert result[0].id == "m-own"
    assert result[0].source_event == "event-full-17"
    with pytest.raises(AttributeError, match="immutable"):
        context._memory_ids = ("m-unlinked",)


def test_memory_snapshot_is_deeply_immutable_and_detached_from_store():
    memory = Memory("m1", "agent-a", "experience", {"nested": ["original"]}, 0.5, "event-1")
    context, store = _context_with_memories([memory])
    result = context.get_relevant_memories(MemoryQuery("agent-a", "original", 2))[0]

    with pytest.raises(TypeError):
        result.content["nested"][0] = "changed"
    assert store.get_memory("m1").content == {"nested": ["original"]}


def test_identical_recollections_from_distinct_events_remain_distinct():
    memories = [
        Memory("m1", "agent-a", "experience", "red door opened", 0.5, "event-1"),
        Memory("m2", "agent-a", "experience", "red door opened", 0.5, "event-2"),
    ]
    context, _ = _context_with_memories(memories)

    results = context.get_relevant_memories(MemoryQuery("agent-a", "red door", 5))

    assert tuple(item.source_event for item in results) == ("event-1", "event-2")


def test_ranking_is_relevant_first_stable_and_importance_only_breaks_ties():
    memories = [
        Memory("z-tie", "agent-a", "experience", "door was red", 0.2, "event-z"),
        Memory("a-tie", "agent-a", "experience", "door was red", 0.8, "event-a"),
        Memory("irrelevant", "agent-a", "experience", "blue sky", 1.0, "event-i"),
    ]
    context, store = _context_with_memories(memories)
    retriever = MemoryRetriever(store)
    query = MemoryQuery("agent-a", "red door", 3)

    first = retriever.retrieve(query, allowed_memory_ids=("z-tie", "a-tie", "irrelevant"))
    second = retriever.retrieve(query, allowed_memory_ids=("irrelevant", "a-tie", "z-tie"))

    assert tuple(item.id for item in first) == ("a-tie", "z-tie")
    assert tuple(item.id for item in second) == tuple(item.id for item in first)
    assert all(not hasattr(item, "confidence") for item in first)
    assert all(not hasattr(item, "timestamp") for item in first)


def test_missing_time_or_emotion_salience_does_not_create_retrieval_score():
    memories = [
        Memory("m-b", "agent-a", "experience", "red door", 0.4, "event-b"),
        Memory("m-a", "agent-a", "experience", "red door", 0.4, "event-a"),
    ]
    context, store = _context_with_memories(memories)
    retriever = MemoryRetriever(store)

    result = retriever.retrieve(
        MemoryQuery("agent-a", "red door", 2),
        allowed_memory_ids=("m-b", "m-a"),
    )

    assert tuple(memory.id for memory in result) == ("m-a", "m-b")


def test_invalid_importance_tie_falls_back_to_id_without_fabricated_value():
    memories = [
        Memory("m-b", "agent-a", "experience", "red door", float("nan"), "event-b"),
        Memory("m-a", "agent-a", "experience", "red door", 0.9, "event-a"),
    ]
    _, store = _context_with_memories(memories)
    result = MemoryRetriever(store).retrieve(
        MemoryQuery("agent-a", "red door", 2),
        allowed_memory_ids=("m-b", "m-a"),
    )

    assert tuple(memory.id for memory in result) == ("m-a", "m-b")
    assert result[1].importance != result[1].importance


def test_l5_requests_relevant_memory_and_builds_context_without_store_write():
    owner = "agent-a"
    store = MemoryStore()
    history = EventHistory()
    history.append(Event("event-1", "confirmed-experience", "t1"))
    proposal = MemoryProposal(
        id="proposal-1",
        source_event_id="event-1",
        owner_id=owner,
        memory_type="experience",
        content={"note": "red door was locked"},
        importance=0.5,
    )
    memory_decision = MemoryDecisionAuthority().issue(
        proposal, accepted=True, importance=proposal.importance, memory_type=proposal.memory_type
    )
    request = MemoryWriteFactory().create_request(memory_decision, proposal)
    memory = MemoryPersistence(store, history).save(request)
    container = CognitionContainer()
    container.add_personality(Personality(owner, traits={"careful": True}))
    container.add_goal(Goal("g1", owner, "inspect the red door", 0.8))
    character = Character("c1", owner, "p1", memory_ids=[memory.id], goal_ids=["g1"])
    cognition_context = CognitionContext.from_character(character, container, store)
    decision = CapturingDecision()
    before = store.get_all_memories()
    goals_before = container.get_goal("g1")

    AgentTurn().execute(RuntimeAgent(owner, "c1"), cognition_context, decision)

    snapshot = decision.context
    assert tuple(item.id for item in snapshot.long_term_memories) == (memory.id,)
    assert snapshot.long_term_memories[0].source_event == "event-1"
    assert snapshot.metacognitive_feedback.memory_queries
    assert snapshot.metacognitive_feedback.memory_queries[0].owner_id == owner
    assert store.get_all_memories() == before
    assert container.get_goal("g1") == goals_before


def test_metacognition_limits_rounds_and_queries_and_stops_repeated_queries():
    policy = BoundedMetacognitionPolicy(maximum_retrievals=2, maximum_feedback_rounds=2)
    context = DecisionContext(
        CognitionState("agent-a"),
        percepts=(),
        goals=(),
        beliefs=(),
    )
    first = policy.review(context, prior_queries=(), remaining_query_budget=2)
    assert len(first.memory_queries) == 0
    assert "uncertainty" in first.review_cues[0]

    container = CognitionContainer()
    container.add_goal(Goal("g1", "agent-a", "look for the red door", 0.7))
    character = Character("c1", "agent-a", "p1", goal_ids=["g1"])
    cognition_context = CognitionContext.from_character(character, container, MemoryStore())
    decision = CapturingDecision()
    AgentTurn(metacognition_policy=policy).execute(
        RuntimeAgent("agent-a", "c1"), cognition_context, decision
    )
    assert len(decision.context.metacognitive_feedback.memory_queries) <= 2
    assert len({q.query.casefold() for q in decision.context.metacognitive_feedback.memory_queries}) == len(
        decision.context.metacognitive_feedback.memory_queries
    )
    assert "uncertainty" in " ".join(decision.context.metacognitive_feedback.review_cues).casefold()


def test_duplicate_queries_terminate_and_untrusted_policy_cannot_expand_budget():
    class RepeatingPolicy:
        maximum_retrievals = 99
        maximum_feedback_rounds = 99
        results_per_query = 99

        def __init__(self):
            self.calls = 0

        def review(self, context, *, prior_queries, remaining_query_budget):
            self.calls += 1
            return MetacognitiveFeedback(
                "agent-a",
                memory_queries=(MemoryQuery("agent-a", "unique absent memory", 99),),
            )

    container = CognitionContainer()
    container.add_goal(Goal("g1", "agent-a", "inspect the red door", 0.7))
    character = Character("c1", "agent-a", "p1", goal_ids=["g1"])
    cognition_context = CognitionContext.from_character(character, container, MemoryStore())
    policy = RepeatingPolicy()
    decision = CapturingDecision()

    AgentTurn(metacognition_policy=policy).execute(
        RuntimeAgent("agent-a", "c1"), cognition_context, decision
    )

    assert policy.calls <= 2
    assert len(decision.context.metacognitive_feedback.memory_queries) <= 2
    assert "uncertainty" in " ".join(decision.context.metacognitive_feedback.review_cues).casefold()


def test_zero_retrieval_budget_exits_without_fabricating_a_memory_result():
    class NoRetrievalPolicy:
        maximum_retrievals = 0
        maximum_feedback_rounds = 4
        results_per_query = 5

        def review(self, context, *, prior_queries, remaining_query_budget):
            raise AssertionError("review cannot run after the zero retrieval budget")

    character = Character("c1", "agent-a", "p1")
    context = CognitionContext.from_character(character, CognitionContainer(), MemoryStore())
    decision = CapturingDecision()

    AgentTurn(metacognition_policy=NoRetrievalPolicy()).execute(
        RuntimeAgent("agent-a", "c1"), context, decision
    )

    assert decision.context.long_term_memories == ()
    assert "budget exhausted" in " ".join(decision.context.metacognitive_feedback.review_cues).casefold()


def test_query_cannot_cross_owner_or_access_private_unreferenced_memory():
    memories = [
        Memory("m-own", "agent-a", "experience", "red door", 0.4, "event-a"),
        Memory("m-private", "agent-b", "experience", "red door secret", 0.9, "event-b"),
    ]
    context, _ = _context_with_memories(memories, refs=["m-own", "m-private"])
    with pytest.raises(ValueError, match="owner_id"):
        context.get_relevant_memories(MemoryQuery("agent-b", "secret", 1))
    results = context.get_relevant_memories(MemoryQuery("agent-a", "red door secret", 5))
    assert tuple(memory.id for memory in results) == ("m-own",)


def test_replaceable_strategy_cannot_expand_character_or_owner_scope():
    memories = [
        Memory("m-own", "agent-a", "experience", "red door", 0.4, "event-a"),
        Memory("m-unlinked", "agent-a", "experience", "red door", 0.8, "event-c"),
        Memory("m-private", "agent-b", "experience", "red door", 0.9, "event-b"),
    ]
    store = MemoryStore()
    for memory in memories:
        store._commit_memory(memory)

    class IgnoresScope:
        def retrieve(self, query, *, allowed_memory_ids):
            assert allowed_memory_ids == ("m-own",)
            return (store.get_memory("m-unlinked"), store.get_memory("m-private"))

    character = Character("c1", "agent-a", "p1", memory_ids=["m-own"])
    context = CognitionContext.from_character(
        character, CognitionContainer(), store, memory_retriever=IgnoresScope()
    )

    assert context.get_relevant_memories(MemoryQuery("agent-a", "red door", 5)) == ()


def test_empty_memory_still_produces_a_valid_decision_context():
    context, _ = _context_with_memories([], refs=[])
    decision = CapturingDecision()
    AgentTurn().execute(RuntimeAgent("agent-a", "character-agent-a"), context, decision)

    assert isinstance(decision.context, DecisionContext)
    assert decision.context.long_term_memories == ()
    assert "uncertainty" in " ".join(decision.context.metacognitive_feedback.review_cues).casefold()


def test_subjective_memory_remains_memory_with_provenance_not_world_fact():
    memory = Memory(
        "mistaken", "agent-a", "experience", "the door was open", 0.99, "event-verified-source"
    )
    context, _ = _context_with_memories([memory])
    result = context.get_relevant_memories(MemoryQuery("agent-a", "door open", 1))[0]

    assert result.content == "the door was open"
    assert result.source_event == "event-verified-source"
    assert not hasattr(result, "confirmed")
