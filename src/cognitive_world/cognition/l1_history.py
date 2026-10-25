"""Ordinary L1 history membership, independent of delivery and action authority."""

from dataclasses import dataclass

from cognitive_world.event.history import EventHistory
from cognitive_world.observation.observable import ObservableFact


@dataclass(frozen=True)
class L1HistoryContext:
    history: EventHistory
    codec: object = None
    trust: object = None

    def evidence_index(self):
        """Return this canonical history's evidence, or an explicit unknown reason."""
        if self.history.requires_recovery():
            return None, "history_recovery_required"
        if self.trust is not None:
            try:
                events, evidence, _ = self.history.verify_persisted_lineage(
                    codec=self.codec, trust=self.trust)
            except Exception:
                return None, "history_verification_unavailable"
            return ({event.id: (event, item) for event, item in zip(events, evidence, strict=True)}, None)
        if self.history.fork_manifest_bytes is not None:
            return None, "ancestor_verification_unavailable"
        # A canonical live in-memory history does not require persistent signatures.
        return ({event.id: (event, self.history.get_processing_evidence(event.id))
                 for event in self.history.get_events()}, None)

    def classify(self, observation, index):
        pair = index.get(observation.source_event_id)
        if pair is None:
            return "ineligible", "source_event_outside_history"
        event, evidence = pair
        if (not event.has_trusted_source() or evidence is None
                or not evidence.has_trusted_source(event)):
            return "undetermined", "processing_evidence_unavailable"
        fact = observation.content
        if not isinstance(fact, ObservableFact):
            return "undetermined", "unsupported_fact_binding"
        if (not fact.has_trusted_source(event)
                or not any(fact == item for item in evidence.observable_facts)):
            return "ineligible", "source_fact_mismatch"
        # Reuse the issuance policy and original delivery binding to check the
        # authorization-context fingerprint, not merely an equal Event/fact ID.
        # This creates only comparison values: no Store delivery or world action.
        from cognitive_world.observation.generator import ObservationGenerator
        binding = observation.trusted_source_runtime_binding()
        try:
            expected = ObservationGenerator().generate_authorized(
                event, evidence, observer_id=observation.observer_id,
                source_timeline_id=observation.trusted_source_timeline_id(),
                source_runtime_session_id=None if binding is None else binding[0],
                source_runtime_generation=None if binding is None else binding[1],
                event_history=self.history)
        except (TypeError, ValueError, PermissionError):
            return "undetermined", "authorization_verification_unavailable"
        if not any(item._snapshot() == observation._snapshot()
                   and item._provenance.context_fingerprint == observation._provenance.context_fingerprint
                   for item in expected):
            return "ineligible", "authorization_evidence_mismatch"
        return "eligible", "history_member"
