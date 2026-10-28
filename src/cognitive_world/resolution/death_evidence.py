"""Closed host-signed recipient binding; not an Observation or write permit.

This value layer has no automatic delivery or historical-upgrade behavior.
"""
from copy import deepcopy
import json
import base64

PURPOSE = "CognitiveWorld death-recipient authorization/v1"


def _payload(body):
    if type(body) is not dict or set(body) != {
        "version", "event_id", "attempt_fingerprint", "target_id", "transition", "recipients"
    }:
        raise ValueError("closed death-recipient body required")
    if type(body["version"]) is not int or body["version"] != 1:
        raise ValueError("unknown death-recipient version")
    for key in ("event_id", "target_id", "attempt_fingerprint"):
        if type(body[key]) is not str or not body[key] or len(body[key]) > 512:
            raise ValueError("exact bounded identities required")
    if body["transition"] != ["alive", "dead"]:
        raise ValueError("unsupported death transition")
    recipients = body["recipients"]
    if (type(recipients) is not list or len(recipients) > 64
            or any(type(r) is not str or not r or len(r) > 512 for r in recipients)
            or len(set(recipients)) != len(recipients)
            or recipients != sorted(recipients)):
        raise ValueError("finite canonical unique recipients required")
    return json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def issue_recipient_binding(trust, *, event_id, attempt_fingerprint, target_id, recipients):
    """Trusted host issuance with its existing durable PersistenceTrust.

    Passing this binding does not establish commit, registration, observation
    authorization at runtime, or generic contract admission.
    """
    if type(recipients) is not tuple:
        raise ValueError("explicit recipient tuple required")
    body = dict(version=1, event_id=event_id, attempt_fingerprint=attempt_fingerprint,
                target_id=target_id, transition=["alive", "dead"], recipients=list(recipients))
    payload = _payload(body)
    signature = trust.sign(PURPOSE, payload)
    if type(signature) is not bytes or not signature:
        raise ValueError("invalid host authorization signature")
    return {"body": body, "signature": base64.b64encode(signature).decode("ascii")}


def verify_recipient_binding(binding, trust, *, event_id, attempt_fingerprint, target_id):
    """Verify the dedicated authorization purpose independently of Event signing."""
    if type(binding) is not dict or set(binding) != {"body", "signature"}:
        raise ValueError("closed signed binding required")
    body = binding["body"]
    try:
        if type(binding["signature"]) is not str:
            raise ValueError("encoded signature required")
        signature = base64.b64decode(binding["signature"], validate=True)
        if base64.b64encode(signature).decode("ascii") != binding["signature"]:
            raise ValueError("canonical signature encoding required")
    except (ValueError, TypeError) as exc:
        raise PermissionError("invalid recipient signature encoding") from exc
    payload = _payload(body)
    if (type(signature) is not bytes or not signature
            or not trust.verify(PURPOSE, payload, signature)):
        raise PermissionError("invalid recipient authorization signature")
    if (body["event_id"], body["attempt_fingerprint"], body["target_id"]) != (
            event_id, attempt_fingerprint, target_id):
        raise PermissionError("recipient authorization occurrence mismatch")
    return tuple(deepcopy(body["recipients"]))
