"""Lightweight Runtime construction must retain real in-memory history qualification."""
from copy import deepcopy
import pytest
from cognitive_world.agent import AgentActionLoop
from cognitive_world.event import EventHistory
from cognitive_world.runtime import RuntimeContext, SimulationClock, SimulationRuntime
from cognitive_world.core.world_state import WorldState
from tests._l1_history_support import light_history


def test_optional_processor_runtime_accepts_only_its_actual_in_memory_history():
    context, observation = light_history("owner", "current-light")
    runtime = SimulationRuntime(context, agent_action_loop=AgentActionLoop(),
        allow_environment_provider_discovery=False)
    cognitive = runtime.agent_action_loop.agent_turn.cognitive_runtime
    assert runtime.event_processor is None
    assert runtime.agent_action_loop.agent_turn.l1_consumption_issuer is None
    state = cognitive.process("owner", [observation])
    item, = state.metadata["l1_ingestion"]["items"]
    assert (item["source"], item["history"], item["consumption"]) == ("eligible", "eligible", "ingested")
    assert state.percept_ids == ["percept:" + observation.observation_id]
    assert cognitive.has_consumed_observation("owner", observation, source_event_id="current-light")
    workspace = deepcopy(cognitive.working_memory_store.get("owner"))
    receipt = dict(cognitive._l1_consumption_receipts)
    _, foreign = light_history("owner", "foreign-light")
    rejected = cognitive.process("owner", [foreign])
    assert rejected.metadata["l1_ingestion"]["items"][0]["history"] == "ineligible"
    assert not rejected.percepts and not rejected.percept_ids
    assert cognitive.working_memory_store.get("owner") == workspace
    assert cognitive._l1_consumption_receipts == receipt


def test_optional_processor_runtime_with_empty_history_does_not_invent_membership():
    _, observation = light_history("owner", "unavailable-source")
    context = RuntimeContext(SimulationClock(), WorldState(), EventHistory())
    runtime = SimulationRuntime(context, agent_action_loop=AgentActionLoop(),
        allow_environment_provider_discovery=False)
    cognitive = runtime.agent_action_loop.agent_turn.cognitive_runtime
    state = cognitive.process("owner", [observation])
    assert state.metadata["l1_ingestion"]["items"][0]["history"] == "ineligible"
    assert not state.percepts and not state.percept_ids
    assert cognitive.working_memory_store.get("owner") is None
    assert not cognitive._l1_consumption_receipts
