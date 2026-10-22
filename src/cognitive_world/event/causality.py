"""Explicit causal recording boundary for events."""

from dataclasses import dataclass, field

from cognitive_world.core.causal_graph import CausalGraph, CausalLink


@dataclass
class EventCausality:
    """Record caller-supplied event causality in a CausalGraph."""

    causal_graph: CausalGraph = field(default_factory=CausalGraph)

    def record_cause(self, event_id: str, cause_id: str) -> CausalLink:
        """Record that the supplied cause is associated with the given event."""
        link = CausalLink(cause=cause_id, effect=event_id)
        self.causal_graph.add_link(link)
        return link

    def find_cause(self, event_id: str, cause_id: str) -> tuple[CausalLink, ...]:
        """Find the recorded link between the supplied cause and event."""
        return self.causal_graph.find_links(cause=cause_id, effect=event_id)
