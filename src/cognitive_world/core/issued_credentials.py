"""Process-local credentials bound to the identity and current content of an object."""
from __future__ import annotations

from threading import RLock
import weakref


class _IssuedObjectCredentials:
    """Remember verifier-issued object identities without retaining them forever."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._issued: dict[tuple[str, int], tuple[weakref.ReferenceType[object], object]] = {}

    def issue(self, purpose: str, value: object, fingerprint: object) -> None:
        key = (purpose, id(value))

        def discard(reference: weakref.ReferenceType[object]) -> None:
            with self._lock:
                current = self._issued.get(key)
                if current is not None and current[0] is reference:
                    self._issued.pop(key, None)

        reference = weakref.ref(value, discard)
        with self._lock:
            self._issued[key] = (reference, fingerprint)

    def require(self, purpose: str, value: object, fingerprint: object) -> None:
        with self._lock:
            issued = self._issued.get((purpose, id(value)))
            if (issued is None or issued[0]() is not value
                    or issued[1] != fingerprint):
                raise PermissionError(f"{purpose} credential is not issued for this intact object")


_CREDENTIALS = _IssuedObjectCredentials()


def _issue_object_credential(purpose: str, value: object, fingerprint: object) -> None:
    _CREDENTIALS.issue(purpose, value, fingerprint)


def _require_object_credential(purpose: str, value: object, fingerprint: object) -> None:
    _CREDENTIALS.require(purpose, value, fingerprint)
