"""B3 system evidence. Predictions are subjective; only processed Events are results."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, asdict, replace
from hashlib import sha256
import json

from cognitive_world.cognition.memory import Memory, SystemOnlyMemoryContent
from cognitive_world.core.persistence import PersistedValueCodec
from cognitive_world.decision.attempt import Attempt
from cognitive_world.runtime.write_fence import RuntimeWriteFence

EXPECTATION_TYPE = "system_action_expectation_v1"
ASSOCIATION_TYPE = "system_action_result_association_v1"
EXPECTATION_PURPOSE = "cognitive-world/action-expectation/v1"
ASSOCIATION_PURPOSE = "cognitive-world/action-result-association/v1"
POLICY = "attempt-result-association/v1"
_AUTHORITY = object()
_SELECTION = ContextVar("b3_selection", default=None)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _digest(value):
    return sha256(_canonical(value)).hexdigest()


def expectation_id(timeline, owner, attempt_id):
    return "action-expectation:" + _digest((1, timeline, owner, attempt_id))


def association_id(identity):
    return "action-result-association:" + _digest((1, identity, "formal-result"))


@dataclass(frozen=True)
class _SelectionReceipt:
    authority: object
    proposal_id: str
    owner_id: str
    candidate_id: str
    expected_text: str
    proposal_fingerprint: str
    tick: int
    permit: object


@contextmanager
def selection_scope(issuer):
    token = _SELECTION.set(issuer)
    try:
        yield
    finally:
        _SELECTION.reset(token)


@dataclass(frozen=True)
class _SelectionTime:
    authority:object
    issuer:object
    tick:int
    timeline_id:str
    permit:object


@dataclass(frozen=True)
class _SourceBindingReceipt:
    authority:object
    issuer:object
    binding:object
    permit:object


def capture_selection_time():
    issuer=_SELECTION.get()
    if issuer is None:return None
    permit=RuntimeWriteFence.bind_current_permit()
    issuer.fence.require_current_permit(permit)
    return _SelectionTime(_AUTHORITY,issuer,issuer.clock.capture().tick,issuer.history.timeline_id,permit)


def bind_selection(proposal,tick,*,selected=None):
    if proposal.metadata.get("candidate_source")=="npc_communication_v1":return proposal
    if tick is not None:
        issuer=_SELECTION.get()
        if (type(tick) is not _SelectionTime or tick.authority is not _AUTHORITY
                or tick.issuer is not issuer or tick.timeline_id!=issuer.history.timeline_id):
            raise PermissionError("selection time has no trusted source")
        from cognitive_world.resolution.causal import ActionInterpreter
        issuer._issue_npc_source(proposal,selected,tick)
        proposal._b3_selection=_SelectionReceipt(_AUTHORITY,proposal.proposal_id,proposal.agent_id,
            selected.candidate_id,selected.expected_result,ActionInterpreter().proposal_fingerprint(proposal),
            tick.tick,tick.permit)
    return proposal


@dataclass(frozen=True)
class ActionExpectationRecord(SystemOnlyMemoryContent):
    version: int
    record_id: str
    owner_id: str
    timeline_id: str
    decision_tick: int | None
    freeze_tick: int
    origin: str
    candidate_id: str | None
    proposal_id: str
    attempt_id: str
    attempt_fingerprint: str
    attempt_json: str
    representation: str
    expected_text: str | None
    policy: str = POLICY
    signature_hex: str = ""

    def body(self):
        value = asdict(self); value.pop("signature_hex")
        return _canonical(value)


@dataclass(frozen=True)
class ActionResultAssociation(SystemOnlyMemoryContent):
    version: int
    record_id: str
    owner_id: str
    timeline_id: str
    expectation_id: str
    expectation_digest: str
    attempt_id: str
    attempt_fingerprint: str
    event_id: str
    event_digest: str
    resolution_id: str
    classification: str = "uncomparable"
    policy: str = POLICY
    signature_hex: str = ""

    def body(self):
        value = asdict(self); value.pop("signature_hex")
        return _canonical(value)


def validate_structure(record):
    from cognitive_world.cognition.action_expectation_source import ActionExpectationSourceBinding,validate_source_structure
    if type(record) is ActionExpectationSourceBinding:
        validate_source_structure(record)
        return
    if type(record) not in (ActionExpectationRecord, ActionResultAssociation):
        raise PermissionError("unknown B3 record")
    if type(record.version) is not int or record.version != 1 or record.policy != POLICY:
        raise PermissionError("unsupported B3 version or historical policy")
    if any(not isinstance(v, str) or not v for v in
           (record.record_id, record.owner_id, record.timeline_id, record.attempt_id)):
        raise PermissionError("invalid B3 identity")
    if type(record) is ActionExpectationRecord:
        if (type(record.freeze_tick) is not int or record.freeze_tick < 0
                or record.origin not in ("npc", "player")
                or not isinstance(record.proposal_id, str) or not record.proposal_id
                or not isinstance(record.attempt_json, str) or len(record.attempt_json.encode()) > 16000):
            raise PermissionError("invalid expectation boundary")
        try:
            snapshot = json.loads(record.attempt_json)
            fingerprint = Attempt.fingerprint_snapshot(snapshot)
        except (ValueError, TypeError):
            raise PermissionError("invalid canonical Attempt") from None
        if (not isinstance(snapshot, list) or len(snapshot) != 9
                or _canonical(snapshot).decode() != record.attempt_json
                or snapshot[0] != record.attempt_id or snapshot[1] != record.owner_id
                or snapshot[2] != record.proposal_id or fingerprint != record.attempt_fingerprint
                or record.record_id != expectation_id(record.timeline_id, record.owner_id, record.attempt_id)):
            raise PermissionError("expectation Attempt binding mismatch")
        if record.representation == "expectation_absent":
            if (record.expected_text is not None or record.decision_tick is not None
                    or record.candidate_id is not None):
                raise PermissionError("absent expectation has prediction fields")
        elif record.representation == "free_text":
            if (not isinstance(record.expected_text,str) or not 1<=len(record.expected_text)<=2000
                    or not isinstance(record.candidate_id,str) or not record.candidate_id
                    or type(record.decision_tick) is not int or not 0<=record.decision_tick<=record.freeze_tick):
                raise PermissionError("invalid expectation representation")
        else:
            # No typed expectation projector has been approved for this slice.
            raise PermissionError("unregistered expectation representation")
    elif (record.record_id != association_id(record.expectation_id)
          or record.classification != "uncomparable"
          or any(not isinstance(v, str) or not v for v in
                 (record.expectation_id, record.expectation_digest, record.event_id,
                  record.event_digest, record.resolution_id))):
        raise PermissionError("invalid result association")


def verify_signature(record, trust):
    validate_structure(record)
    from cognitive_world.cognition.action_expectation_source import ActionExpectationSourceBinding,SOURCE_PURPOSE
    purpose=(SOURCE_PURPOSE if type(record) is ActionExpectationSourceBinding else
             EXPECTATION_PURPOSE if type(record) is ActionExpectationRecord else ASSOCIATION_PURPOSE)
    try:
        signature = bytes.fromhex(record.signature_hex)
    except (TypeError, ValueError):
        raise PermissionError("invalid B3 signature encoding") from None
    if not trust.verify(purpose, record.body(), signature):
        raise PermissionError("invalid B3 signature")


def _verify_membership(record, history, lineage, checkpoint_tick):
    node = history
    while node is not None and node.timeline_id != record.timeline_id:
        node = getattr(node, "_parent_history", None)
    if node is None:
        raise PermissionError("B3 record is outside Timeline ancestry")
    from cognitive_world.cognition.action_expectation_source import ActionExpectationSourceBinding,SOURCE_TYPE
    tick=(record.freeze_tick if type(record) is ActionExpectationRecord else
          record.issued_tick if type(record) is ActionExpectationSourceBinding else None)
    if tick is not None:
        if tick > checkpoint_tick:
            raise PermissionError("expectation is later than checkpoint")
        if node.fork_manifest_bytes is not None:
            from cognitive_world.core.timeline import TimelineForkManifest
            if tick < TimelineForkManifest.from_bytes(node.fork_manifest_bytes).simulation_tick:
                raise PermissionError("expectation predates its Timeline")
    if record.timeline_id != history.timeline_id:
        from cognitive_world.cognition.memory_revision import MemoryRevisionLineage
        from cognitive_world.cognition.snapshot import cognitive_snapshot_codec
        if type(lineage) is not MemoryRevisionLineage or lineage.timeline_id != history.timeline_id:
            raise PermissionError("B3 ancestor requires checkpoint membership")
        lineage.verify_event_history(history)
        encoded = dict(lineage.inherited_records).get(record.record_id)
        if encoded is None:
            raise PermissionError("B3 record absent from inherited checkpoint")
        memory = cognitive_snapshot_codec().loads(encoded)
        kind=(SOURCE_TYPE if type(record) is ActionExpectationSourceBinding else
              EXPECTATION_TYPE if type(record) is ActionExpectationRecord else ASSOCIATION_TYPE)
        if (type(memory) is not Memory or memory.type != kind
                or memory.owner_id != record.owner_id or memory.content != record):
            raise PermissionError("B3 ancestor record changed")
    return node


def verify_records(memories, *, history, trust, checkpoint_tick, lineage=None):
    from cognitive_world.cognition.action_expectation_source import (
        SOURCE_TYPE,ActionExpectationSourceBinding,verify_source_records,
    )
    verify_source_records(memories,trust,checkpoint_tick=checkpoint_tick)
    records = {}
    for memory in memories:
        if memory.type not in (EXPECTATION_TYPE, ASSOCIATION_TYPE,SOURCE_TYPE):
            if memory.type.startswith("system_action_"):
                raise PermissionError("unknown B3 system record")
            continue
        record = memory.content
        cls=(ActionExpectationSourceBinding if memory.type==SOURCE_TYPE else
             ActionExpectationRecord if memory.type==EXPECTATION_TYPE else ActionResultAssociation)
        if (type(record) is not cls or memory.id != record.record_id or memory.owner_id != record.owner_id
                or memory.source_event != (record.event_id if cls is ActionResultAssociation else "")):
            raise PermissionError("malformed B3 Memory envelope")
        verify_signature(record, trust)
        _verify_membership(record, history, lineage, checkpoint_tick)
        if record.record_id in records:
            raise PermissionError("duplicate B3 record")
        records[record.record_id] = record
    history.verify_persisted_lineage(codec=PersistedValueCodec(), trust=trust)
    for record in records.values():
        if type(record) is not ActionResultAssociation:
            continue
        expected = records.get(record.expectation_id)
        if (type(expected) is not ActionExpectationRecord
                or sha256(expected.body()).hexdigest() != record.expectation_digest
                or (record.owner_id, record.timeline_id, record.attempt_id, record.attempt_fingerprint)
                   != (expected.owner_id, expected.timeline_id, expected.attempt_id, expected.attempt_fingerprint)):
            raise PermissionError("association expectation mismatch")
        node = _verify_membership(record, history, lineage, checkpoint_tick)
        from cognitive_world.cognition.l1_consumption_proof import _source_timeline
        event = node.get_event(record.event_id)
        evidence = node.get_processing_evidence(record.event_id)
        if (event is None or evidence is None or not event.has_trusted_source("resolution")
                or not evidence.has_trusted_source(event)
                or _source_timeline(node, event.id, trust) != record.timeline_id
                or event.cause != record.attempt_id
                or event.metadata.get("attempt_id") != record.attempt_id
                or event.metadata.get("attempt_fingerprint") != record.attempt_fingerprint
                or event.metadata.get("action_proposal_id") != expected.proposal_id
                or event.metadata.get("resolution_id") != record.resolution_id
                or event.id != "event:" + record.resolution_id
                or event.metadata.get("action_expectation_id") != expected.record_id
                or sha256(PersistedValueCodec().dumps(event._source_snapshot())).hexdigest() != record.event_digest
                or type(event.simulation_tick) is not int
                or not expected.freeze_tick <= event.simulation_tick <= checkpoint_tick):
            raise PermissionError("association authoritative result mismatch")
    for event in history.get_events():
        identity = event.metadata.get("action_expectation_id")
        if identity is not None:
            association = records.get(association_id(identity))
            if (identity not in records or type(association) is not ActionResultAssociation
                    or association.event_id != event.id):
                raise PermissionError("incomplete required B3 association")


class ActionExpectationIssuer:
    """One Runtime-bound issuer; pending execution markers are transient, not evidence."""
    def __init__(self, *, context, fence, trust, context_provider):
        self.context, self.fence, self.trust = context, fence, trust
        self.history, self.clock = context.event_history, context.clock
        self.context_provider = context_provider
        self._registered = set()
        self._started = set()
        self._source_permits = {}

    def store_for(self, owner):
        from cognitive_world.cognition.memory_store import MemoryStore
        agent = self.context.agent_registry.get(owner)
        if agent is None:
            raise PermissionError("B3 owner is unregistered")
        context = self.context_provider(agent)
        if context.owner_id != owner or type(context.memory_store) is not MemoryStore:
            raise PermissionError("B3 canonical owner Store unavailable")
        if context.memory_store.write_fence is not self.fence:
            raise PermissionError("B3 Store belongs to another Runtime")
        return context.memory_store

    def _issue_npc_source(self,proposal,selected,stamp):
        from cognitive_world.decision.autonomous import ActionCandidate
        from cognitive_world.cognition.action_expectation_source import NpcSelectedExpectation
        if (type(selected) is not ActionCandidate or type(stamp) is not _SelectionTime
                or stamp.authority is not _AUTHORITY or stamp.issuer is not self
                or _SELECTION.get() is not self or selected.owner_id!=proposal.agent_id
                or selected.candidate_id!=proposal.metadata.get("selected_candidate_id")
                or selected.expected_result!=proposal.parameters.get("expected_result")
                or tuple(proposal.reasoning_refs)!=selected.source_refs):
            raise PermissionError("NPC source is not the actual validated selection")
        self.fence.require_candidate_origin(stamp.permit)
        return self._publish_source(proposal,"npc_selected","free_text",
            NpcSelectedExpectation(selected.candidate_id,stamp.tick,selected.expected_result),stamp.tick)

    def issue_player_source(self,proposal,*,authority):
        from cognitive_world.cognition.action_expectation_source import (
            _PLAYER_ENTRY_AUTHORITY,PlayerExpectationAbsent,PLAYER_ABSENCE_POLICY,
        )
        from cognitive_world.runtime.context import PlayerMode
        session=self.context.player_session
        if (authority is not _PLAYER_ENTRY_AUTHORITY or session is None
                or session.mode is not PlayerMode.ROLEPLAY or session.controlled_agent_id!=proposal.agent_id):
            raise PermissionError("player absence has no authenticated player-entry provenance")
        return self._publish_source(proposal,"player_action","expectation_absent",
            PlayerExpectationAbsent(PLAYER_ABSENCE_POLICY),self.clock.capture().tick)

    def _publish_source(self,proposal,kind,representation,data,tick):
        from cognitive_world.cognition.action_expectation_source import (
            ActionExpectationSourceBinding,SOURCE_POLICY,SOURCE_TYPE,SOURCE_PURPOSE,source_id,
        )
        from cognitive_world.resolution.causal import ActionInterpreter
        permit=RuntimeWriteFence.bind_current_permit()
        with self.fence.commit_scope():
            self.fence.require_candidate_origin(proposal.runtime_write_permit)
            store=self.store_for(proposal.agent_id)
            identity=source_id(self.history.timeline_id,proposal.agent_id,proposal.proposal_id)
            prior=store.get_memory(identity)
            if prior is not None and (prior.type!=SOURCE_TYPE or type(prior.content) is not ActionExpectationSourceBinding):
                raise PermissionError("conflicting source binding envelope")
            binding=ActionExpectationSourceBinding(1,identity,SOURCE_POLICY,kind,proposal.agent_id,
                self.history.timeline_id,proposal.proposal_id,ActionInterpreter().proposal_fingerprint(proposal),
                representation,data,tuple(proposal.reasoning_refs),tick if prior is None else prior.content.issued_tick,"")
            validate_structure(binding)
            if prior is not None:
                verify_signature(prior.content,self.trust)
                if replace(prior.content,signature_hex="")!=binding:
                    raise PermissionError("conflicting action source binding identity")
                original=self._source_permits.get(identity)
                if original is None:
                    raise PermissionError("historical source binding is not current entry authorization")
                self.fence.require_candidate_origin(original)
                proposal._b3_source=_SourceBindingReceipt(_AUTHORITY,self,prior.content,original)
                return prior.content
            try:
                binding=replace(binding,signature_hex=self.trust.sign(SOURCE_PURPOSE,binding.body()).hex())
                verify_signature(binding,self.trust)
                store._commit_action_record(Memory(identity,binding.owner_id,SOURCE_TYPE,binding,0.0,""),
                    authority=_AUTHORITY,permit=permit)
                self._source_permits[identity]=permit
                proposal._b3_source=_SourceBindingReceipt(_AUTHORITY,self,binding,permit)
                return binding
            except BaseException:
                self.fence.mark_recovery_required()
                raise

    def reference_for(self,proposal,receipt):
        from cognitive_world.cognition.action_expectation_source import source_digest
        from cognitive_world.resolution.causal import ActionInterpreter
        with self.fence.commit_scope():
            if (type(receipt) is not _SourceBindingReceipt or receipt.authority is not _AUTHORITY
                    or receipt.issuer is not self):
                raise PermissionError("untrusted proposal source reference")
            self.fence.require_candidate_origin(receipt.permit)
            binding=receipt.binding
            stored=self.store_for(proposal.agent_id).get_memory(binding.record_id)
            if (stored is None or stored.content!=binding or binding.timeline_id!=self.history.timeline_id
                    or binding.proposal_id!=proposal.proposal_id or binding.owner_id!=proposal.agent_id
                    or binding.proposal_digest!=ActionInterpreter().proposal_fingerprint(proposal)):
                raise PermissionError("conflicting selected proposal changed before expectation freeze")
            verify_signature(binding,self.trust)
            return {"version":1,"record_id":binding.record_id,"content_digest":source_digest(binding)}

    def freeze(self, attempt, proposal, *, origin):
        permit = RuntimeWriteFence.bind_current_permit()
        with self.fence.commit_scope():
            self.fence.require_candidate_origin(permit)
            store = self.store_for(attempt.agent_id)
            timeline = self.history.timeline_id
            if not isinstance(timeline, str) or not timeline:
                raise PermissionError("B3 requires canonical Timeline")
            identity = expectation_id(timeline, attempt.agent_id, attempt.attempt_id)
            prior_memory = store.get_memory(identity)
            if prior_memory is not None:
                if type(prior_memory.content) is not ActionExpectationRecord:
                    raise PermissionError("conflicting expectation envelope")
                verify_signature(prior_memory.content, self.trust)
            for memory in store.get_all_memories():
                if (type(memory.content) is ActionExpectationRecord
                        and memory.content.proposal_id == attempt.action_proposal_id
                        and memory.content.attempt_id != attempt.attempt_id):
                    raise PermissionError("selected proposal is already bound to another Attempt; do not replay")
                if (type(memory.content) is ActionExpectationRecord
                        and memory.content.attempt_id == attempt.attempt_id
                        and memory.content.timeline_id != timeline):
                    raise PermissionError("ancestor Attempt cannot be executed on a child Timeline")
            from cognitive_world.cognition.action_expectation_source import (
                ActionExpectationSourceBinding,NpcSelectedExpectation,attempt_source_reference,
                validate_attempt_source,validate_expectation_source,AmbiguousActionExpectationSource,
            )
            reference=attempt_source_reference(attempt._resolution_snapshot())
            if proposal is not None:
                from cognitive_world.cognition.action_expectation_source import reference_for_proposal
                if reference_for_proposal(proposal)!=reference:
                    raise PermissionError("selected proposal source differs from final Attempt")
            source_memory=store.get_memory(reference["record_id"])
            if source_memory is None or type(source_memory.content) is not ActionExpectationSourceBinding:
                raise AmbiguousActionExpectationSource("required trusted action source is unavailable")
            binding=source_memory.content
            verify_signature(binding,self.trust)
            validate_attempt_source(attempt._resolution_snapshot(),binding)
            source_origin="npc" if binding.source_kind=="npc_selected" else "player"
            if origin!=source_origin:
                raise PermissionError("origin claim differs from trusted action source")
            data=binding.source_data
            npc=type(data) is NpcSelectedExpectation
            record=ActionExpectationRecord(1,identity,attempt.agent_id,timeline,
                data.decision_tick if npc else None,
                self.clock.capture().tick if prior_memory is None else prior_memory.content.freeze_tick,
                source_origin,data.candidate_id if npc else None,attempt.action_proposal_id,
                attempt.attempt_id,attempt.content_fingerprint(),_canonical(attempt._resolution_snapshot()).decode(),
                binding.representation,data.expected_text if npc else None)
            validate_structure(record)
            validate_expectation_source(record,binding)
            if prior_memory is not None:
                verify_signature(prior_memory.content, self.trust)
                if replace(prior_memory.content, signature_hex="") != record:
                    raise PermissionError("conflicting expectation identity")
                return prior_memory.content
            source_permit=self._source_permits.get(binding.record_id)
            if source_permit is None:
                raise AmbiguousActionExpectationSource("restored source cannot authorize a new historical Attempt")
            self.fence.require_candidate_origin(source_permit)
            try:
                record = replace(record, signature_hex=self.trust.sign(EXPECTATION_PURPOSE, record.body()).hex())
                verify_signature(record, self.trust)
                store._commit_action_record(Memory(identity, record.owner_id, EXPECTATION_TYPE, record, 0.0, ""),
                    authority=_AUTHORITY, permit=permit)
                self._registered.add(identity)
                return record
            except BaseException:
                self.fence.mark_recovery_required()
                raise

    def begin_resolution(self, record):
        with self.fence.commit_scope():
            from cognitive_world.cognition.action_expectation_source import attempt_source_reference
            reference=attempt_source_reference(json.loads(record.attempt_json))
            source_permit=self._source_permits.get(reference["record_id"])
            if source_permit is None:
                raise PermissionError("restored incomplete action source cannot authorize Resolution")
            self.fence.require_candidate_origin(source_permit)
            if record.record_id not in self._registered or record.record_id in self._started:
                raise PermissionError("B3 Attempt already started or restored incomplete; do not replay")
            self._started.add(record.record_id)

    def associate(self, event):
        identity = event.metadata.get("action_expectation_id")
        if identity is None:
            return
        with self.fence.commit_scope():
            try:
                # The expectation's owner is located by canonical Attempt identity,
                # never from target prose or an untrusted owner claim.
                matches = []
                for agent in self.context.agent_registry.all_agents():
                    store = self.store_for(agent.agent_id)
                    found = store.get_memory(identity)
                    if found is not None and all(s is not store for s, _ in matches):
                        matches.append((store, found))
                if len(matches) != 1:
                    raise PermissionError("missing or ambiguous canonical expectation")
                store, memory = matches[0]; expected = memory.content
                verify_signature(expected, self.trust)
                record = ActionResultAssociation(1, association_id(identity), expected.owner_id,
                    expected.timeline_id, identity, sha256(expected.body()).hexdigest(),
                    expected.attempt_id, expected.attempt_fingerprint, event.id,
                    sha256(PersistedValueCodec().dumps(event._source_snapshot())).hexdigest(),
                    event.metadata.get("resolution_id", ""))
                existing = store.get_memory(record.record_id)
                if existing is not None:
                    if replace(existing.content, signature_hex="") != record:
                        raise PermissionError("conflicting result association")
                    verify_records(store.get_all_memories(), history=self.history, trust=self.trust,
                        checkpoint_tick=self.clock.current_time, lineage=store._revision_lineage)
                    return existing.content
                record = replace(record, signature_hex=self.trust.sign(ASSOCIATION_PURPOSE, record.body()).hex())
                envelope = Memory(record.record_id, record.owner_id, ASSOCIATION_TYPE, record, 0.0, event.id)
                verify_records((*store.get_all_memories(), envelope), history=self.history, trust=self.trust,
                    checkpoint_tick=self.clock.current_time, lineage=store._revision_lineage)
                store._commit_action_record(envelope, authority=_AUTHORITY,
                    permit=RuntimeWriteFence.bind_current_permit())
                return record
            except BaseException:
                self.fence.mark_recovery_required()
                raise
