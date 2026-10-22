from cognitive_world.agent import AgentRegistry, RuntimeAgent


def test_agent_registry_can_be_created():
    assert isinstance(AgentRegistry(), AgentRegistry)


def test_registry_stores_and_gets_agent_by_id():
    registry = AgentRegistry()
    agent = RuntimeAgent(agent_id="agent_001", goal_ids=["goal_001"])

    registry.register(agent)

    registered = registry.get("agent_001")
    assert registered is not None
    assert registered.agent_id == "agent_001"
    assert registered.get_goals() == ["goal_001"]
    assert registry.get("missing") is None


def test_registry_removes_agent():
    registry = AgentRegistry()
    agent = RuntimeAgent(agent_id="agent_001")
    registry.register(agent)

    removed = registry.remove("agent_001")

    assert removed == agent
    assert registry.get("agent_001") is None
    assert registry.remove("agent_001") is None


def test_registry_manages_multiple_agents():
    registry = AgentRegistry()
    first = RuntimeAgent(agent_id="agent_001")
    second = RuntimeAgent(agent_id="agent_002")
    registry.register(first)
    registry.register(second)

    assert registry.all_agents() == (first, second)


def test_external_agent_mutations_do_not_pollute_registry():
    registry = AgentRegistry()
    source = RuntimeAgent(
        agent_id="agent_001",
        goal_ids=["goal_001"],
        metadata={"nested": {"labels": ["stored"]}},
    )
    registry.register(source)
    source.goal_ids.append("goal_source")
    source.metadata["nested"]["labels"].append("source")

    fetched = registry.get("agent_001")
    assert fetched is not None
    fetched.goal_ids.append("goal_fetched")
    fetched.metadata["nested"]["labels"].append("fetched")

    snapshot = registry.all_agents()
    snapshot[0].goal_ids.append("goal_snapshot")
    snapshot[0].metadata["nested"]["labels"].append("snapshot")

    stored = registry.get("agent_001")
    assert stored is not None
    assert stored.get_goals() == ["goal_001"]
    assert stored.metadata == {"nested": {"labels": ["stored"]}}
