from importlib import import_module

from cognitive_world.agent import Character, CognitionContext
from cognitive_world.cognition import (
    CognitionContainer,
    Goal,
    MemoryDecisionAuthority,
    MemoryPersistence,
    MemoryStore,
    MemoryProposal,
    MemoryWriteFactory,
)
from cognitive_world.core.event import Event
from cognitive_world.event.history import EventHistory


def test_memory_has_only_memory_store_as_storage_entry():
    cognition_container = CognitionContainer()
    memory_store = MemoryStore()

    assert not hasattr(cognition_container, "add_memory")
    assert not hasattr(cognition_container, "get_memory")
    history = EventHistory()
    history.append(Event(id="event_001", type="generic", timestamp="t1"))
    proposal = MemoryProposal(
        id="proposal_001",
        source_event_id="event_001",
        owner_id="character_001",
        memory_type="experience",
        content={"note": "remembered"},
        importance=0.8,
    )
    decision = MemoryDecisionAuthority().issue(
        proposal,
        accepted=True,
        importance=proposal.importance,
        memory_type=proposal.memory_type,
    )
    request = MemoryWriteFactory().create_request(decision, proposal)
    memory = MemoryPersistence(memory_store, history).save(request)
    assert memory_store.get_memory(memory.id) == memory


def test_context_gets_goals_by_explicit_character_goal_ids():
    container = CognitionContainer()
    memory_store = MemoryStore()
    referenced_goal = Goal(
        id="goal_referenced",
        owner_id="agent_001",
        description="explicitly referenced",
        priority=1.0,
        status="active",
    )
    inferred_goal = Goal(
        id="goal_inferred",
        owner_id="agent_001",
        description="must not be inferred by owner",
        priority=1.0,
        status="active",
    )
    container.add_goal(referenced_goal)
    container.add_goal(inferred_goal)
    character = Character(
        id="character_001",
        agent_id="agent_001",
        personality_id="personality_001",
        goal_ids=[referenced_goal.id],
    )

    context = CognitionContext.from_character(character, container, memory_store)

    assert context.get_goals() == (referenced_goal,)


def test_cognition_boundary_modules_have_no_world_event_or_ai_dependencies():
    module_names = (
        "cognitive_world.cognition.container",
        "cognitive_world.cognition.memory_store",
        "cognitive_world.agent.character",
        "cognitive_world.agent.cognition_context",
    )
    forbidden_names = {"WorldState", "Event", "AI"}

    for module_name in module_names:
        module = import_module(module_name)
        assert forbidden_names.isdisjoint(vars(module))
