"""Core data structures for recording causal associations."""

from dataclasses import dataclass, field


@dataclass
class CausalLink:
    """A recorded association between a cause and an effect."""

    cause: str
    effect: str
    strength: float = 0.0
    confidence: float = 0.0


@dataclass
class CausalGraph:
    """A collection of recorded causal links."""

    _links: list[CausalLink] = field(default_factory=list, repr=False)

    def add_link(self, link: CausalLink) -> None:
        """Add a causal link to the graph."""
        self._links.append(link)

    def find_links(
        self, cause: str | None = None, effect: str | None = None
    ) -> tuple[CausalLink, ...]:
        """Return links matching the supplied cause and/or effect."""
        return tuple(
            link
            for link in self._links
            if (cause is None or link.cause == cause)
            and (effect is None or link.effect == effect)
        )
