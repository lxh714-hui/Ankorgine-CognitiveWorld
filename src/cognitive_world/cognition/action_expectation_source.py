"""Closed historical action-entry provenance; never a Runtime authorization token."""
from dataclasses import asdict,dataclass
from contextlib import contextmanager
from hashlib import sha256
import json
import re
from cognitive_world.cognition.memory import SystemOnlyMemoryContent

SOURCE_TYPE="system_action_expectation_source_v1"
SOURCE_PURPOSE="cognitive-world/action-expectation-source/v1"
SOURCE_POLICY="trusted-action-entry/v1"
SOURCE_REF_KEY="action_expectation_source"
PLAYER_ABSENCE_POLICY="player-no-explicit-expectation/v1"
_PLAYER_ENTRY_AUTHORITY=object()


class AmbiguousActionExpectationSource(PermissionError):
    code="ambiguous_action_expectation_source"


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()


def source_id(timeline,owner,proposal_id):
    return "action-expectation-source:"+sha256(canonical((1,timeline,owner,proposal_id))).hexdigest()


@dataclass(frozen=True)
class NpcSelectedExpectation:
    candidate_id:str
    decision_tick:int
    expected_text:str


@dataclass(frozen=True)
class PlayerExpectationAbsent:
    absence_policy:str


@dataclass(frozen=True)
class ActionExpectationSourceBinding(SystemOnlyMemoryContent):
    version:int
    record_id:str
    policy:str
    source_kind:str
    owner_id:str
    timeline_id:str
    proposal_id:str
    proposal_digest:str
    representation:str
    source_data:NpcSelectedExpectation|PlayerExpectationAbsent
    source_refs:tuple[str,...]
    issued_tick:int
    signature_hex:str

    def body(self):
        value=asdict(self);value.pop("signature_hex")
        return canonical(value)


def source_digest(binding):
    return sha256(binding.body()).hexdigest()


def validate_source_structure(binding):
    if (type(binding) is not ActionExpectationSourceBinding
            or type(binding.version) is not int or binding.version!=1
            or binding.policy!=SOURCE_POLICY):
        raise PermissionError("unsupported expectation source schema/policy")
    if (any(not isinstance(s,str) or not s for s in
            (binding.record_id,binding.owner_id,binding.timeline_id,binding.proposal_id))
            or binding.record_id!=source_id(binding.timeline_id,binding.owner_id,binding.proposal_id)
            or not isinstance(binding.proposal_digest,str)
            or re.fullmatch(r"[0-9a-f]{64}",binding.proposal_digest) is None
            or type(binding.issued_tick) is not int or binding.issued_tick<0
            or type(binding.source_refs) is not tuple or len(binding.source_refs)>8
            or any(not isinstance(s,str) or not s for s in binding.source_refs)):
        raise PermissionError("invalid expectation source bindings")
    data=binding.source_data
    if binding.source_kind=="npc_selected":
        if (type(data) is not NpcSelectedExpectation or binding.representation!="free_text"
                or not isinstance(data.candidate_id,str) or not data.candidate_id
                or not isinstance(data.expected_text,str) or not 1<=len(data.expected_text)<=2000
                or type(data.decision_tick) is not int or data.decision_tick!=binding.issued_tick):
            raise PermissionError("invalid NPC selection source")
    elif binding.source_kind=="player_action":
        if (type(data) is not PlayerExpectationAbsent
                or binding.representation!="expectation_absent"
                or data.absence_policy!=PLAYER_ABSENCE_POLICY):
            raise PermissionError("invalid trusted player absence source")
    else:
        raise PermissionError("unknown expectation source kind")


def verify_source(binding,trust):
    validate_source_structure(binding)
    try:signature=bytes.fromhex(binding.signature_hex)
    except (TypeError,ValueError):raise PermissionError("invalid source signature encoding") from None
    if not trust.verify(SOURCE_PURPOSE,binding.body(),signature):
        raise PermissionError("invalid expectation source signature")


def attempt_source_reference(snapshot):
    if (not isinstance(snapshot,(tuple,list)) or len(snapshot)!=9
            or not isinstance(snapshot[5],dict) or not isinstance(snapshot[6],dict)):
        raise PermissionError("invalid canonical Attempt shape")
    reference=snapshot[6].get(SOURCE_REF_KEY)
    if reference is None:
        raise AmbiguousActionExpectationSource("legacy B3 Attempt has no independently verifiable source")
    if (type(reference) is not dict or set(reference)!={"version","record_id","content_digest"}
            or type(reference["version"]) is not int or reference["version"]!=1
            or not isinstance(reference["record_id"],str) or not reference["record_id"]
            or not isinstance(reference["content_digest"],str)
            or re.fullmatch(r"[0-9a-f]{64}",reference["content_digest"]) is None):
        raise PermissionError("malformed Attempt source reference")
    return reference


def _proposal_from_attempt(snapshot):
    metadata=dict(snapshot[6]);metadata.pop(SOURCE_REF_KEY)
    refs=metadata.pop("action_proposal_reasoning_refs",None)
    if not isinstance(refs,(tuple,list)) or any(not isinstance(r,str) for r in refs):
        raise PermissionError("Attempt lacks original proposal source references")
    return {"proposal_id":snapshot[2],"agent_id":snapshot[1],"action_type":snapshot[3],
            "target_refs":snapshot[4],"parameters":snapshot[5],"reasoning_refs":list(refs),"metadata":metadata},tuple(refs)


def validate_attempt_source(snapshot,binding):
    """Pure shared rule: compare to source evidence, never to an origin claim."""
    validate_source_structure(binding)
    reference=attempt_source_reference(snapshot)
    proposal,refs=_proposal_from_attempt(snapshot)
    if (reference["record_id"]!=binding.record_id or reference["content_digest"]!=source_digest(binding)
            or snapshot[1]!=binding.owner_id or snapshot[2]!=binding.proposal_id
            or sha256(canonical(proposal)).hexdigest()!=binding.proposal_digest
            or refs!=binding.source_refs):
        raise PermissionError("conflicting Attempt/proposal/source binding mismatch")
    if binding.source_kind=="npc_selected":
        data=binding.source_data
        if (snapshot[5].get("expected_result")!=data.expected_text
                or snapshot[6].get("selected_candidate_id")!=data.candidate_id):
            raise PermissionError("original NPC selection differs from final Attempt")
    # Player absence is established by the authenticated player-entry policy;
    # an unrelated open Attempt parameter is not interpreted as a prediction.


def validate_expectation_source(record,binding):
    snapshot=json.loads(record.attempt_json)
    validate_attempt_source(snapshot,binding)
    if (record.owner_id!=binding.owner_id or record.timeline_id!=binding.timeline_id
            or record.proposal_id!=binding.proposal_id or record.freeze_tick<binding.issued_tick):
        raise PermissionError("expectation/source owner, Timeline or time mismatch")
    if binding.source_kind=="npc_selected":
        data=binding.source_data
        expected=("npc","free_text",data.expected_text,data.candidate_id,data.decision_tick)
    else:
        expected=("player","expectation_absent",None,None,None)
    if (record.origin,record.representation,record.expected_text,record.candidate_id,record.decision_tick)!=expected:
        raise PermissionError("expectation semantics differ from trusted action source")


def verify_source_records(memories,trust,*,checkpoint_tick=None):
    from cognitive_world.cognition.action_expectation import EXPECTATION_TYPE,ActionExpectationRecord
    sources={}
    for memory in memories:
        if memory.type!=SOURCE_TYPE:continue
        binding=memory.content
        if (type(binding) is not ActionExpectationSourceBinding or memory.id!=binding.record_id
                or memory.owner_id!=binding.owner_id or memory.source_event!=""):
            raise PermissionError("malformed source Memory envelope")
        verify_source(binding,trust)
        if checkpoint_tick is not None and binding.issued_tick>checkpoint_tick:
            raise PermissionError("source binding is later than checkpoint")
        if binding.record_id in sources:raise PermissionError("duplicate source binding")
        sources[binding.record_id]=binding
    for memory in memories:
        if memory.type!=EXPECTATION_TYPE:continue
        if type(memory.content) is not ActionExpectationRecord:
            raise PermissionError("invalid expectation type")
        reference=attempt_source_reference(json.loads(memory.content.attempt_json))
        binding=sources.get(reference["record_id"])
        if binding is None:
            raise AmbiguousActionExpectationSource("required historical source binding is unavailable")
        validate_expectation_source(memory.content,binding)
    return sources


def _trusted_receipt(proposal):
    receipt=getattr(proposal,"_b3_source",None)
    if receipt is None:return None
    from cognitive_world.cognition.action_expectation import (
        _SourceBindingReceipt,_AUTHORITY,ActionExpectationIssuer,
    )
    if (type(receipt) is not _SourceBindingReceipt or receipt.authority is not _AUTHORITY
            or type(receipt.issuer) is not ActionExpectationIssuer):
        raise PermissionError("proposal has no trusted source receipt")
    return receipt


def reference_for_proposal(proposal):
    receipt=_trusted_receipt(proposal)
    return None if receipt is None else receipt.issuer.reference_for(proposal,receipt)


@contextmanager
def source_reference_scope(proposal):
    """Hold the same fence until the new immutable Attempt is fully frozen."""
    receipt=_trusted_receipt(proposal)
    if receipt is None:
        yield None
        return
    with receipt.issuer.fence.commit_scope():
        yield receipt.issuer.reference_for(proposal,receipt)
