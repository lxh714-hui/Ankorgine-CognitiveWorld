"""Stable interaction addressing; no state or authorization lives here."""

from dataclasses import dataclass


@dataclass(frozen=True)
class InteractionReference:
    """Address one potential target without asserting that it exists or is visible.

    Bare references remain object addresses for existing door/passage callers.
    The namespace is routing information, never a causal rule or permission.
    """

    namespace: str
    identifier: str
    legacy: bool = False

    def __post_init__(self) -> None:
        if self.namespace not in {"object", "agent"}:
            raise ValueError("interaction namespace is unsupported")
        if not isinstance(self.identifier, str) or not self.identifier or len(self.identifier) > 1024:
            raise ValueError("interaction identifier must be bounded non-empty text")
        if type(self.legacy) is not bool or (self.legacy and self.namespace != "object"):
            raise ValueError("legacy interaction addresses are object-only")

    @classmethod
    def parse(cls, value: str) -> "InteractionReference":
        if not isinstance(value, str) or not value or len(value) > 1024:
            raise ValueError("interaction target must be bounded non-empty text")
        for namespace in ("object", "agent"):
            prefix = f"{namespace}:"
            if value.startswith(prefix):
                identifier = value[len(prefix):]
                if not identifier:
                    raise ValueError("interaction target has no identifier")
                return cls(namespace, identifier)
        # Compatibility with the existing open IDs (including IDs containing
        # colons). This is explicitly an object address, never type inference.
        return cls("object", value, legacy=True)
