"""Narrow private projection of a validated Boolean transition, not raw state."""

from cognitive_world.core.physical import CandidateStateDelta
from cognitive_world.observation.observable import ObservableFactDraft


def result_draft(event, *, location_id):
    """Called after handler validation; issuance still belongs to EventProcessor."""
    if (
        not event.has_trusted_source("resolution")
        or len(event.changes) != 2
        or event.changes[0].get("success") is not True
    ):
        return None
    effect = event.changes[1]
    if (
        not isinstance(effect, dict)
        or effect.get("effect_type") != "physical_state_transition_v1"
    ):
        return None
    delta = effect.get("delta")
    if type(delta) is not CandidateStateDelta or location_id is None:
        return None
    before = {p.definition.name: p for p in delta.expected.properties}
    changed = [
        p for p in delta.replacement.properties if before.get(p.definition.name) != p
    ]
    if len(changed) != 1 or type(changed[0].value) is not bool:
        return None
    value = changed[0]
    return ObservableFactDraft(
        "action_result",
        "boolean_transition_applied",
        (value.definition.name, value.value),
        delta.entity_id,
        location_id,
    )


def allows_result(event, evidence, observer_id, fact=None, event_history=None):
    """Exact committed owner-result binding; co-location grants nothing."""
    from cognitive_world.event.history import EventHistory, EventProcessingStatus

    if (
        not isinstance(event_history, EventHistory)
        or event_history.requires_recovery()
        or not evidence.has_trusted_source(event)
    ):
        return False
    committed = event_history.get_event(event.id)
    if (
        committed is None
        or committed._source_snapshot() != event._source_snapshot()
        or event_history.get_processing_evidence(event.id) != evidence
    ):
        return False
    status = event_history.get_processing_status(event.id)
    # Restored canonical records are RECORDED; inherited verified prefixes have
    # no local delivery lifecycle. Neither is a claim of replayed UI delivery.
    if status not in {
        EventProcessingStatus.OBSERVATIONS_PENDING,
        EventProcessingStatus.COMPLETE,
        EventProcessingStatus.RECORDED,
    } and not (
        status is None and event_history.get_persistence_record(event.id) is not None
    ):

        return False
    if len(event.changes) != 2 or not isinstance(event.changes[1], dict):
        return False
    effect = event.changes[1]
    if effect.get("actor_id") != observer_id:
        return False
    context = evidence.event_time_context
    positions = [
        p for owner, p, _ in context.observer_positions if owner == observer_id
    ]
    if (
        context.simulation_time != event.simulation_tick
        or context.fact_location_id is None
        or positions != [context.fact_location_id]
    ):
        return False
    draft = result_draft(event, location_id=context.fact_location_id)
    if draft is None:
        return False
    return any(
        item.has_trusted_source(event)
        and (
            item.fact_type,
            item.predicate,
            item.value,
            item.subject_ref,
            item.location_id,
        )
        == (
            draft.fact_type,
            draft.predicate,
            draft.value,
            draft.subject_ref,
            draft.location_id,
        )
        and (fact is None or item == fact)
        for item in evidence.observable_facts
    )
