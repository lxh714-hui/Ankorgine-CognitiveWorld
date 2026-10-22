"""Versioned, non-authoritative testimony attached to a dialogue Event."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math


@dataclass(frozen=True)
class AttributedClaimDraft:
    """Untrusted structured testimony selected with an outbound utterance."""

    subject_ref: str
    property_ref: str
    value_type: str
    value: str | int | float | bool
    valid_from_tick: int
    valid_through_tick: int | None
    scope_ref: str

    def __post_init__(self) -> None:
        if any(not isinstance(item, str) or not item for item in (
            self.subject_ref, self.property_ref, self.value_type, self.scope_ref,
        )):
            raise ValueError("claim references and type must be non-empty")
        if self.value_type not in {"string", "integer", "number", "boolean"}:
            raise ValueError("unsupported claim value type")
        valid = {
            "string": type(self.value) is str,
            "integer": type(self.value) is int,
            "number": type(self.value) in (int, float) and math.isfinite(float(self.value)),
            "boolean": type(self.value) is bool,
        }[self.value_type]
        if not valid:
            raise TypeError("claim value does not match its declared type")
        if (type(self.valid_from_tick) is not int or self.valid_from_tick < 0
                or (self.valid_through_tick is not None and
                    (type(self.valid_through_tick) is not int
                     or self.valid_through_tick < self.valid_from_tick))):
            raise ValueError("claim applicability interval is invalid")


@dataclass(frozen=True)
class ClaimPropertyContract:
    """Host-registered type contract; it validates shape, never claim truth."""

    property_ref: str
    value_type: str
    version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.property_ref, str) or not self.property_ref:
            raise ValueError("property contract reference is required")
        if self.value_type not in {"string", "integer", "number", "boolean"}:
            raise ValueError("unsupported property contract value type")
        if self.version != 1:
            raise ValueError("unsupported property contract version")


@dataclass(frozen=True)
class AttributedClaim:
    """Immutable claim whose digest is covered by the original Event signature."""

    schema_version: int
    claim_id: str
    speaker_id: str
    recipient_id: str
    subject_ref: str
    property_ref: str
    value_type: str
    property_contract_version: int
    value: str | int | float | bool
    valid_from_tick: int
    valid_through_tick: int | None
    scope_ref: str
    source_event_id: str
    utterance_sha256: str
    content_sha256: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported AttributedClaim schema")
        if any(not isinstance(item, str) or not item for item in (
            self.claim_id, self.speaker_id, self.recipient_id, self.subject_ref,
            self.property_ref, self.value_type, self.scope_ref,
            self.source_event_id, self.utterance_sha256, self.content_sha256,
        )):
            raise ValueError("AttributedClaim identity is incomplete")
        if self.content_sha256 != sha256(self.canonical_body()).hexdigest():
            raise ValueError("AttributedClaim digest mismatch")
        if (type(self.property_contract_version) is not int
                or self.property_contract_version != 1
                or type(self.valid_from_tick) is not int or self.valid_from_tick < 0
                or (self.valid_through_tick is not None
                    and (type(self.valid_through_tick) is not int
                         or self.valid_through_tick < self.valid_from_tick))):
            raise ValueError("AttributedClaim contract version or interval is invalid")
        valid_value = {
            "string": type(self.value) is str,
            "integer": type(self.value) is int,
            "number": type(self.value) in (int, float)
                      and math.isfinite(float(self.value)),
            "boolean": type(self.value) is bool,
        }.get(self.value_type, False)
        if not valid_value:
            raise ValueError("AttributedClaim value does not match its declared type")

    def canonical_body(self) -> bytes:
        return json.dumps({
            "schema_version": 1, "claim_id": self.claim_id,
            "speaker_id": self.speaker_id, "recipient_id": self.recipient_id,
            "subject_ref": self.subject_ref, "property_ref": self.property_ref,
            "value_type": self.value_type,
            "property_contract_version": self.property_contract_version,
            "value": self.value,
            "valid_from_tick": self.valid_from_tick,
            "valid_through_tick": self.valid_through_tick,
            "scope_ref": self.scope_ref, "source_event_id": self.source_event_id,
            "utterance_sha256": self.utterance_sha256,
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
           allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class DialoguePayload:
    """Optional versioned extension; it is testimony, not a world change."""

    schema_version: int
    claim: AttributedClaim | None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported DialoguePayload schema")
        if self.claim is not None and type(self.claim) is not AttributedClaim:
            raise TypeError("dialogue payload claim must be AttributedClaim")


def bind_claim(*, draft: AttributedClaimDraft, contract: ClaimPropertyContract,
               speaker_id: str, recipient_id: str, event_id: str,
               utterance: str) -> AttributedClaim:
    """Bind selected testimony to this delivery after checking host contract."""
    if type(draft) is not AttributedClaimDraft or type(contract) is not ClaimPropertyContract:
        raise PermissionError("claim requires a registered property contract")
    if contract.property_ref != draft.property_ref or contract.value_type != draft.value_type:
        raise PermissionError("claim does not match its registered property contract")
    utterance_digest = sha256(utterance.encode("utf-8")).hexdigest()
    claim_id = "claim:" + sha256((event_id + "\0" + utterance_digest).encode("utf-8")).hexdigest()
    provisional = object.__new__(AttributedClaim)
    values = dict(
        schema_version=1, claim_id=claim_id, speaker_id=speaker_id,
        recipient_id=recipient_id, subject_ref=draft.subject_ref,
        property_ref=draft.property_ref, value_type=draft.value_type,
        property_contract_version=contract.version,
        value=draft.value, valid_from_tick=draft.valid_from_tick,
        valid_through_tick=draft.valid_through_tick, scope_ref=draft.scope_ref,
        source_event_id=event_id, utterance_sha256=utterance_digest,
    )
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    digest = sha256(provisional.canonical_body()).hexdigest()
    return AttributedClaim(**values, content_sha256=digest)


def encode_claim_draft(draft: AttributedClaimDraft) -> bytes:
    if type(draft) is not AttributedClaimDraft:
        raise TypeError("claim draft has an unsupported type")
    return json.dumps({
        "schema_version": 1, "subject_ref": draft.subject_ref,
        "property_ref": draft.property_ref, "value_type": draft.value_type,
        "value": draft.value, "valid_from_tick": draft.valid_from_tick,
        "valid_through_tick": draft.valid_through_tick, "scope_ref": draft.scope_ref,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
       allow_nan=False).encode("utf-8")


def decode_claim_draft(payload: bytes) -> AttributedClaimDraft:
    if not isinstance(payload, bytes) or len(payload) > 16 * 1024:
        raise ValueError("claim candidate payload is invalid or oversized")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("claim candidate payload is malformed") from None
    required = {
        "schema_version", "subject_ref", "property_ref", "value_type", "value",
        "valid_from_tick", "valid_through_tick", "scope_ref",
    }
    if not isinstance(value, dict) or set(value) != required or value["schema_version"] != 1:
        raise ValueError("unsupported claim candidate payload schema")
    draft = AttributedClaimDraft(
        value["subject_ref"], value["property_ref"], value["value_type"],
        value["value"], value["valid_from_tick"], value["valid_through_tick"],
        value["scope_ref"],
    )
    if encode_claim_draft(draft) != payload:
        raise ValueError("claim candidate payload is not canonical")
    return draft


def validate_claim_for_event(claim: AttributedClaim, *, event: object) -> None:
    """Recheck exact speaker, recipient, Event identity and utterance binding."""
    if type(claim) is not AttributedClaim or not getattr(event, "has_trusted_source", lambda *_: False)("system"):
        raise PermissionError("structured testimony requires an intact trusted dialogue Event")
    if event.type != "dialogue_input" or event.id != claim.source_event_id:
        raise PermissionError("claim source Event mismatch")
    if tuple(event.participants) != (claim.speaker_id, claim.recipient_id):
        raise PermissionError("claim participants do not match dialogue Event")
    if (len(event.changes) != 1 or set(event.changes[0]) != {"utterance"}
            or not isinstance(event.changes[0]["utterance"], str)):
        raise PermissionError("claim Event has an invalid utterance payload")
    utterance_digest = sha256(event.changes[0]["utterance"].encode("utf-8")).hexdigest()
    if utterance_digest != claim.utterance_sha256:
        raise PermissionError("claim is not bound to the committed utterance")
    expected_claim_id = "claim:" + sha256(
        (event.id + "\0" + utterance_digest).encode("utf-8")
    ).hexdigest()
    if claim.claim_id != expected_claim_id:
        raise PermissionError("claim identity is not derived from its source Event")
    if claim.content_sha256 != sha256(claim.canonical_body()).hexdigest():
        raise PermissionError("claim digest mismatch")
    valid = {
        "string": type(claim.value) is str,
        "integer": type(claim.value) is int,
        "number": type(claim.value) in (int, float) and math.isfinite(float(claim.value)),
        "boolean": type(claim.value) is bool,
    }.get(claim.value_type, False)
    if type(claim.property_contract_version) is not int or claim.property_contract_version != 1 or not valid:
        raise PermissionError("claim value or property contract version is invalid")
