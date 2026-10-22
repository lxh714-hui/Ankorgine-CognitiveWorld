from cognitive_world.core.causal_graph import CausalGraph, CausalLink


def test_causal_link_can_be_created():
    link = CausalLink(
        cause="cause_001", effect="effect_001", strength=0.8, confidence=0.9
    )

    assert link.cause == "cause_001"
    assert link.effect == "effect_001"
    assert link.strength == 0.8
    assert link.confidence == 0.9


def test_causal_graph_adds_and_queries_link():
    graph = CausalGraph()
    link = CausalLink(cause="cause_001", effect="effect_001")

    graph.add_link(link)

    assert graph.find_links(cause="cause_001") == (link,)
    assert graph.find_links(effect="effect_001") == (link,)
    assert graph.find_links(cause="missing") == ()


def test_causal_graph_saves_multiple_links():
    graph = CausalGraph()
    first = CausalLink(cause="cause_001", effect="effect_001")
    second = CausalLink(cause="cause_002", effect="effect_002")

    graph.add_link(first)
    graph.add_link(second)

    assert graph.find_links() == (first, second)
