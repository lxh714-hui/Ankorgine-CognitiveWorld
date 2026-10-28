"""Recipient authorization value tests; not C-stage integration acceptance."""
from copy import deepcopy
import pytest
from cognitive_world.core.persistence import HmacPersistenceTrust, PersistedValueCodec
from cognitive_world.resolution.death_evidence import issue_recipient_binding, verify_recipient_binding


def authority():
    return HmacPersistenceTrust(b"recipient-host-durable-test-root!!")


def issued(recipients=("a",)):
    return issue_recipient_binding(authority(), event_id="event:resolution:one",
        attempt_fingerprint="exact-attempt-digest", target_id="b", recipients=recipients)


def verify(binding, **overrides):
    fields = dict(event_id="event:resolution:one", attempt_fingerprint="exact-attempt-digest", target_id="b")
    fields.update(overrides)
    return verify_recipient_binding(binding, authority(), **fields)


def test_recipient_authorization_survives_value_persistence_with_original_root():
    codec = PersistedValueCodec()
    payload = codec.dumps(issued())
    assert verify(codec.loads(payload)) == ("a",)
    assert codec.dumps(codec.loads(payload)) == payload


@pytest.mark.parametrize("recipients", [("a", "a"), ("z", "a"), ("",), (1,)])
def test_noncanonical_or_invalid_recipient_set_rejected(recipients):
    with pytest.raises(ValueError): issued(recipients)


@pytest.mark.parametrize("field,value", [("version", 2), ("target_id", "other"),
    ("event_id", "other"), ("recipients", ["a", "c"]), ("transition", ["dead", "alive"])])
def test_modified_binding_fails_closed(field, value):
    binding = deepcopy(issued())
    binding["body"][field] = value
    with pytest.raises((ValueError, PermissionError)): verify(binding)


@pytest.mark.parametrize("field", ["event_id", "target_id", "attempt_fingerprint"])
def test_valid_authorization_cannot_be_moved_to_another_occurrence(field):
    with pytest.raises(PermissionError): verify(issued(), **{field: "other"})


def test_event_signature_purpose_cannot_replace_recipient_authorization():
    binding = issued()
    binding["signature"] = authority().sign("some-event-attestation", b"event")
    with pytest.raises(PermissionError): verify(binding)
