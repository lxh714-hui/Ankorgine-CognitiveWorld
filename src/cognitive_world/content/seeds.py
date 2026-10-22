"""Expose event hooks only from confirmed, observer-authorized facts."""
from __future__ import annotations

from dataclasses import dataclass

from cognitive_world.event.history import EventHistory
from cognitive_world.observation.store import ObservationStore

from .models import ScenarioInstance


@dataclass(frozen=True)
class SeedOpportunity:
    """An attention hook for an Agent, not an Event or an ActionProposal."""
    seed_id: str
    scenario_instance_id: str
    observer_id: str
    observation_id: str
    source_event_id: str
    importance: float


def observed_seed_opportunities(instance: ScenarioInstance, observer_id: str, *,
                                history: EventHistory, observations: ObservationStore) -> tuple[SeedOpportunity, ...]:
    """Match only processor evidence that this Agent was permitted to observe.

    A caller may offer these hooks to an owner-scoped decision policy. The hook
    has no power to select an action or confirm an event.
    """
    if not isinstance(instance, ScenarioInstance) or not isinstance(observer_id, str) or not observer_id:
        raise TypeError("seed matching requires an instance and observer identity")
    if not isinstance(history, EventHistory) or not isinstance(observations, ObservationStore):
        raise TypeError("seed matching requires canonical history and observation store")
    opportunities: list[SeedOpportunity] = []
    for observation in observations.get_by_observer(observer_id):
        if not observation.has_trusted_provenance():
            continue
        event = history.get_event(observation.source_event_id)
        evidence = history.get_processing_evidence(observation.source_event_id)
        if event is None or evidence is None or not evidence.has_trusted_source(event):
            continue
        fact = observation.content
        if not any(item == fact for item in evidence.observable_facts):
            continue
        for seed in instance.event_seeds:
            if fact.predicate != seed.trigger_predicate or type(fact.value) is not type(seed.trigger_value) or fact.value != seed.trigger_value:
                continue
            if seed.participant_keys and not any(character.agent_id == observer_id and
                character.instance_id == f"{instance.world_id}:{instance.instance_id}:character:{key}"
                for key in seed.participant_keys for character in instance.characters):
                continue
            opportunities.append(SeedOpportunity(seed.seed_id, instance.instance_id, observer_id,
                                                  observation.observation_id, event.id, seed.importance))
    return tuple(opportunities)
