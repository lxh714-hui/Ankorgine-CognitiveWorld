from dataclasses import fields

import pytest

from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.cognition.runtime import CognitiveRuntime
from cognitive_world.core.entity import Entity
from cognitive_world.core.world_state import WorldState
from cognitive_world.event import EventHistory, EventProcessor, RoomLightChangedHandler, SystemEventFactory
from cognitive_world.observation import ObservationStore
from cognitive_world.presentation import (
    InMemoryChatOutputGateway,
    PerspectiveAuthorizationError,
    PerspectiveContext,
    PlayerVisibleMessage,
    PresentationPipeline,
    VisibleInput,
)
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import PlayerMode, PlayerSessionBinding, RuntimeContext
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.scheduler import EventScheduler, ScheduledEvent


def _event(*, metadata=None):
    return SystemEventFactory().create(
        event_id="presentation-light-event",
        event_type="room_light_changed",
        timestamp="descriptive-only",
        changes=[{"room_id": "room-a", "from_light_on": False, "to_light_on": True}],
        metadata=metadata or {},
    )


def _scene(
    *,
    mode=PlayerMode.ROLEPLAY,
    agent_id="agent-near",
    include_session=True,
    metadata=None,
):
    world = WorldState()
    world.load_environment_data("room-a", {"light_on": False})
    world.load_environment_data("room-b", {"light_on": False})
    world.load_entity(Entity("agent-near", "agent", sensory_capabilities=("sight",)))
    world.load_entity(Entity("agent-far", "agent", sensory_capabilities=("sight",)))
    world.load_location("agent-near", "room-a")
    world.load_location("agent-far", "room-b")
    registry = AgentRegistry()
    registry.register(RuntimeAgent("agent-near", character_id="character-near"))
    registry.register(RuntimeAgent("agent-far", character_id="character-far"))
    history = EventHistory()
    observations = ObservationStore()
    session = None
    if include_session:
        if mode is PlayerMode.OBSERVER:
            session = PlayerSessionBinding(
                "session-1", "player-1", mode, observer_agent_id=agent_id
            )
        elif mode is PlayerMode.DIRECTOR:
            session = PlayerSessionBinding("session-1", "player-1", mode)
        else:
            session = PlayerSessionBinding(
                "session-1", "player-1", mode, controlled_agent_id=agent_id
            )
    scheduler = EventScheduler()
    event = _event(metadata=metadata)
    scheduler.schedule(ScheduledEvent(execute_time=1, event=event))
    context = RuntimeContext(
        SimulationClock(),
        world,
        history,
        scheduler=scheduler,
        agent_registry=registry,
        observation_store=observations,
        player_session=session,
    )
    processor = EventProcessor()
    processor.register_handler("room_light_changed", RoomLightChangedHandler())
    SimulationRuntime(context, event_processor=processor).step()
    gateway = InMemoryChatOutputGateway(context)
    pipeline = PresentationPipeline.for_runtime(context, gateway)
    return context, event, processor, pipeline, gateway


def test_production_event_to_player_chat_vertical_slice():
    context, event, _, pipeline, gateway = _scene(
        metadata={
            "presentation_facts": [{"text": "ATTACKER CONTROLLED NARRATIVE"}],
            "debug": "must-not-leak",
            "emotion": {"fear": 0.98},
            "private_cognition": "hidden thought",
        }
    )
    before_world = context.world_state.environment
    before_history = context.event_history.get_events()
    before_observations = context.observation_store.all()

    batch = pipeline.publish_event(event.id)

    assert len(batch.messages) == 1
    assert batch.messages[0].content == "房间里的灯亮了。"
    assert batch.messages[0].recipient_id == "player-1"
    assert batch.messages[0].observer_id == "agent-near"
    assert gateway.messages_for("player-1") == batch.messages
    assert "ATTACKER" not in repr(batch.messages)
    assert "debug" not in repr(batch.messages)
    assert "private_cognition" not in repr(batch.messages)
    assert context.world_state.environment == before_world
    assert context.event_history.get_events() == before_history
    assert context.observation_store.all() == before_observations

    # The same controlled observation still reaches the existing Agent L1 path.
    observed = context.observation_store.get_by_observer("agent-near")
    cognition_state = CognitiveRuntime().process("agent-near", observed)
    assert cognition_state.percept_ids == [f"percept:{observed[0].observation_id}"]


def test_agent_without_authorized_observation_receives_empty_output():
    _, event, _, pipeline, gateway = _scene(agent_id="agent-far")
    batch = pipeline.publish_event(event.id)
    assert batch.messages == ()
    assert gateway.messages_for("player-1") == ()


def test_roleplay_session_cannot_override_controlled_character_at_call_site():
    _, event, _, pipeline, gateway = _scene()
    with pytest.raises(TypeError):
        pipeline.publish_event(event.id, observer_id="agent-far")
    assert gateway.messages_for("player-1") == ()


def test_director_mode_is_denied_without_an_explicit_policy():
    _, event, _, pipeline, gateway = _scene(mode=PlayerMode.DIRECTOR)
    with pytest.raises(PerspectiveAuthorizationError, match="director mode"):
        pipeline.publish_event(event.id)
    assert gateway.messages_for("player-1") == ()


def test_observer_mode_uses_its_host_bound_view_agent_without_control_authority():
    _, event, _, pipeline, gateway = _scene(
        mode=PlayerMode.OBSERVER,
        agent_id="agent-near",
    )
    batch = pipeline.publish_event(event.id)
    assert batch.messages[0].recipient_id == "player-1"
    assert batch.messages[0].observer_id == "agent-near"
    assert gateway.messages_for("player-1") == batch.messages


def test_missing_trusted_player_session_defaults_to_denial():
    _, event, _, pipeline, gateway = _scene(include_session=False)
    with pytest.raises(PerspectiveAuthorizationError, match="trusted player session"):
        pipeline.publish_event(event.id)
    assert gateway.messages_for("player-1") == ()


def test_manually_constructed_perspective_or_visible_input_cannot_reach_composer():
    from cognitive_world.presentation import MinimalComposer

    perspective = PerspectiveContext(
        "player-1", "agent-near", frozenset({"environment"}),
        "session-1", PlayerMode.ROLEPLAY, "character-near",
    )
    forged = VisibleInput(
        "player-1", "agent-near", "session-1", "event-1", "fact-1", "obs-1",
        "environment", "environment_state", "room_light_on", True,
    )
    with pytest.raises(PermissionError):
        MinimalComposer().compose((forged,), perspective)


def test_manual_event_and_event_metadata_do_not_create_presentation_authority():
    context, event, _, pipeline, gateway = _scene()
    manual = SystemEventFactory().create(
        event_id="not-processed",
        event_type="room_light_changed",
        timestamp="t2",
        changes=[{"room_id": "room-a", "from_light_on": False, "to_light_on": True}],
        metadata={"presentation_facts": [{"text": "forged"}]},
    )
    context.event_history.append(manual)
    with pytest.raises(PermissionError, match="trusted recorded processing evidence"):
        pipeline.publish_event(manual.id)
    assert gateway.messages_for("player-1") == ()


def test_hand_built_messages_and_raw_backend_objects_are_rejected_by_gateway():
    context, event, _, pipeline, gateway = _scene()
    batch = pipeline.publish_event(event.id)
    manual = PlayerVisibleMessage(
        "player-1", "agent-near", "session-1", (event.id,), ("fact-forged",),
        "environment", "I saw a secret.",
    )
    for forged in (
        "raw string",
        event,
        context.observation_store.get_by_observer("agent-near")[0],
        manual,
    ):
        with pytest.raises(TypeError):
            gateway.send(forged)
    assert gateway.messages_for("player-1") == batch.messages


def test_post_validation_message_tampering_is_rejected_by_gateway():
    _, event, _, pipeline, gateway = _scene()
    batch = pipeline.publish_event(event.id)
    object.__setattr__(batch.messages[0], "content", "tampered internal analysis")
    with pytest.raises(PermissionError, match="modified"):
        gateway.send(batch)
    assert gateway.last_error_code == "authorization_rejected"


def test_message_contract_is_closed_and_does_not_expose_backend_metadata():
    assert {item.name for item in fields(PlayerVisibleMessage)} == {
        "recipient_id", "observer_id", "session_id", "source_event_ids",
        "source_fact_ids", "visibility_scope", "content", "_receipt",
    }
    assert "metadata" not in {item.name for item in fields(PlayerVisibleMessage)}
