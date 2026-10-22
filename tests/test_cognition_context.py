from cognitive_world.agent import Character, CognitionContext
from cognitive_world.cognition import (
    Belief,
    CognitionContainer,
    Emotion,
    Goal,
    Memory,
    MemoryDecisionAuthority,
    MemoryPersistence,
    MemoryQuery,
    MemoryRetriever,
    MemoryProposal,
    MemoryStore,
    MemoryWriteFactory,
    Personality,
)
from cognitive_world.core.event import Event
from cognitive_world.event.history import EventHistory


def save_approved_memory(proposal, memory_store, event_history):
    decision = MemoryDecisionAuthority().issue(
        proposal,
        accepted=True,
        importance=proposal.importance,
        memory_type=proposal.memory_type,
    )
    request = MemoryWriteFactory().create_request(decision, proposal)
    return MemoryPersistence(memory_store, event_history).save(request)


def make_proposal(proposal_id, event_id, owner_id, content, importance):
    return MemoryProposal(
        id=proposal_id,
        source_event_id=event_id,
        owner_id=owner_id,
        memory_type="experience",
        content=content,
        importance=importance,
    )


class FixedMemoryRetriever(MemoryRetriever):
    def __init__(self, memory_store, result):
        super().__init__(memory_store)
        self.result = result
        self.received_query = None

    def retrieve(
        self, query: MemoryQuery, *, allowed_memory_ids: tuple[str, ...]
    ) -> tuple[Memory, ...]:
        self.received_query = query
        memories = []
        for memory in self.result:
            if memory.id not in allowed_memory_ids:
                continue
            stored_memory = self.memory_store.get_memory(memory.id)
            assert stored_memory is not None
            memories.append(stored_memory)
        return tuple(memories)


def test_context_binds_character_and_reads_cognition_and_memory():
    container = CognitionContainer()
    memory_store = MemoryStore()
    personality = Personality(owner_id="agent_001", traits={"trait": "steady"})
    belief = Belief(
        id="belief_001",
        owner_id="agent_001",
        content={"claim": "known"},
        confidence=0.8,
        source="observation",
    )
    goal = Goal(
        id="goal_001",
        owner_id="agent_001",
        description="general goal",
        priority=0.7,
        status="active",
    )
    emotion = Emotion(
        id="emotion_001",
        owner_id="agent_001",
        state="calm",
        intensity=0.2,
    )
    container.add_personality(personality)
    container.add_belief(belief)
    container.add_goal(goal)
    container.add_emotion(emotion)
    event_history = EventHistory()
    event_history.append(Event(id="event_001", type="generic", timestamp="t1"))
    proposal = make_proposal(
        "proposal_001", "event_001", "agent_001", {"event": "remembered"}, 0.9
    )
    memory = save_approved_memory(proposal, memory_store, event_history)
    character = Character(
        id="character_001",
        agent_id="agent_001",
        personality_id=personality.id,
        memory_ids=[memory.id],
        belief_ids=[belief.id],
        emotion_id=emotion.id,
        goal_ids=[goal.id],
    )

    context = CognitionContext.from_character(character, container, memory_store)

    assert context.character_id == character.id
    assert context.get_personality() == personality
    assert context.get_beliefs() == (belief,)
    assert context.get_goals() == (goal,)
    assert context.get_emotion() == emotion
    assert context.get_memories() == (memory,)


def test_context_reads_do_not_mutate_cognition_or_memory_stores():
    container = CognitionContainer()
    memory_store = MemoryStore()
    belief = Belief(
        id="belief_001",
        owner_id="agent_001",
        content={"nested": ["original"]},
        confidence=0.5,
        source="record",
    )
    container.add_belief(belief)
    event_history = EventHistory()
    event_history.append(Event(id="event_001", type="generic", timestamp="t1"))
    proposal = make_proposal(
        "proposal_001", "event_001", "agent_001", {"nested": ["original"]}, 0.4
    )
    memory = save_approved_memory(proposal, memory_store, event_history)
    character = Character(
        id="character_001",
        agent_id="agent_001",
        personality_id="personality_missing",
        belief_ids=[belief.id],
        memory_ids=[memory.id],
    )
    context = CognitionContext.from_character(character, container, memory_store)

    context.get_beliefs()[0].content["nested"].append("external")
    context.get_memories()[0].content["nested"].append("external")

    assert container.get_belief(belief.id).content == {"nested": ["original"]}
    assert memory_store.get_memory(memory.id).content == {"nested": ["original"]}


def test_context_uses_memory_retriever_for_relevant_memories():
    memory_store = MemoryStore()
    event_history = EventHistory()
    event_history.append(Event(id="event_001", type="generic", timestamp="t1"))
    proposal = make_proposal(
        "proposal_001", "event_001", "agent_001", {"details": ["stored"]}, 0.7
    )
    memory = save_approved_memory(proposal, memory_store, event_history)
    retriever = FixedMemoryRetriever(memory_store, [memory])
    character = Character(
        id="character_001",
        agent_id="agent_001",
        personality_id="personality_001",
        memory_ids=[memory.id],
    )
    context = CognitionContext.from_character(
        character,
        CognitionContainer(),
        memory_store,
        memory_retriever=retriever,
    )
    query = MemoryQuery(owner_id="agent_001", query="stored details", limit=3)

    result = context.get_relevant_memories(query)
    assert result[0].content["details"] == ("stored",)

    assert retriever.received_query is query
    assert memory_store.get_memory(memory.id).content == {"details": ["stored"]}
