"""In-process origin receipts for governed cognition proposals.

The marker survives detached copies, but its first captured permit cannot be
rebound by dataclass replacement or by changing the proposal's public field.
This is a runtime authority boundary, not a defense against arbitrary code
executing with the same Python process's private module access.
"""

from threading import RLock
from weakref import WeakKeyDictionary

from cognitive_world.runtime.write_fence import RuntimeWritePermit


class ProposalOriginMarker:
    __slots__ = ("__weakref__",)

    def __deepcopy__(self, memo):
        return self


_origins: WeakKeyDictionary[ProposalOriginMarker, RuntimeWritePermit | None] = WeakKeyDictionary()
_lock = RLock()


def bind_proposal_origin(proposal: object) -> None:
    marker = getattr(proposal, "_origin_marker", None)
    permit = getattr(proposal, "runtime_write_permit", None)
    if type(marker) is not ProposalOriginMarker:
        raise PermissionError("cognition proposal has no valid origin marker")
    with _lock:
        if marker in _origins:
            if _origins[marker] is not permit:
                raise PermissionError("cognition proposal cannot rebind its original permit")
        else:
            _origins[marker] = permit


def original_proposal_permit(proposal: object) -> RuntimeWritePermit | None:
    marker = getattr(proposal, "_origin_marker", None)
    if type(marker) is not ProposalOriginMarker:
        raise PermissionError("cognition proposal has no valid origin marker")
    with _lock:
        if marker not in _origins:
            raise PermissionError("cognition proposal has no issued origin")
        permit = _origins[marker]
    if getattr(proposal, "runtime_write_permit", None) is not permit:
        raise PermissionError("cognition proposal permit differs from its origin")
    return permit
