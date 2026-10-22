from cognitive_world.agent import Character, CognitionContext
from cognitive_world.cognition import CognitionContainer, MemoryStore
from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.observation import Observation, ObservationStore


def make_context(observation_store):
    character = Character(
        id="character_1", agent_id="agent_1", personality_id="personality_1"
    )
    return CognitionContext.from_character(
        character,
        CognitionContainer(),
        MemoryStore(),
        observation_store=observation_store,
    )


def test_context_reads_observations_for_its_agent_only():
    store = ObservationStore()
    owned = Observation("obs_1", "agent_1", "event_1", {"detail": "visible"})
    other = Observation("obs_2", "agent_2", "event_2", {"detail": "private"})
    store.add(owned)
    store.add(other)
    context = make_context(store)

    assert context.get_observations() == (owned,)


def test_returned_observations_do_not_mutate_store():
    store = ObservationStore()
    store.add(Observation("obs_1", "agent_1", "event_1", {"nested": ["initial"]}))
    context = make_context(store)

    returned = context.get_observations()
    returned[0].content["nested"].append("changed")

    assert store.get("obs_1").content == {"nested": ["initial"]}


def test_observation_read_does_not_change_event_or_world_state():
    store = ObservationStore()
    store.add(Observation("obs_1", "agent_1", "event_1", {"seen": True}))
    event = Event("event_1", "fact", "t1", changes=[{"value": [1]}])
    world_state = WorldState()
    before_event = event
    before_entities = world_state.entities
    before_facts = world_state.facts
    context = make_context(store)

    context.get_observations()

    assert event == before_event
    assert world_state.entities == before_entities
    assert world_state.facts == before_facts
