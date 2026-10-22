from cognitive_world.core.event import Event
from cognitive_world.observation import Observation, ObservationStore


def test_store_adds_and_gets_observation():
    store = ObservationStore()
    observation = Observation("obs_1", "observer_1", "event_1", {"fact": [1]})

    store.add(observation)

    assert store.get("obs_1") == observation
    assert store.all() == (observation,)


def test_store_queries_observations_by_observer():
    store = ObservationStore()
    first = Observation("obs_1", "observer_1", "event_1", "first")
    second = Observation("obs_2", "observer_2", "event_2", "second")
    third = Observation("obs_3", "observer_1", "event_3", "third")
    for observation in (first, second, third):
        store.add(observation)

    assert store.get_by_observer("observer_1") == (first, third)


def test_store_isolates_input_and_returned_observations():
    store = ObservationStore()
    observation = Observation("obs_1", "observer_1", "event_1", {"nested": ["original"]})
    store.add(observation)

    observation.content["nested"].append("source mutation")
    retrieved = store.get("obs_1")
    retrieved.content["nested"].append("read mutation")

    assert store.get("obs_1").content == {"nested": ["original"]}


def test_observation_store_does_not_modify_source_event():
    event = Event(
        id="event_1",
        type="change",
        timestamp="t1",
        participants=["entity_1"],
        changes=[{"state": ["before"]}],
    )
    original_event = Event(
        id="event_1",
        type="change",
        timestamp="t1",
        participants=["entity_1"],
        changes=[{"state": ["before"]}],
    )
    observation = Observation("obs_1", "observer_1", event.id, {"noticed": True})
    store = ObservationStore()

    store.add(observation)

    assert event == original_event
