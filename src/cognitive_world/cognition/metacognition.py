"""Turn-local metacognitive feedback and bounded review strategy contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from cognitive_world.cognition.memory_retrieval import MemoryQuery, MAX_MEMORY_QUERY_RESULTS

if TYPE_CHECKING:
    from cognitive_world.decision.context import DecisionContext


MAX_MEMORY_RETRIEVALS_PER_TURN = 2
MAX_METACOGNITIVE_FEEDBACK_ROUNDS = 2
MAX_MEMORY_RESULTS_PER_QUERY = MAX_MEMORY_QUERY_RESULTS


@dataclass(frozen=True)
class MetacognitiveFeedback:
    """Owner-bound review cues and optional requests for another retrieval."""

    owner_id: str
    review_cues: tuple[str, ...] = ()
    memory_queries: tuple[MemoryQuery, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.owner_id, str) or not self.owner_id:
            raise ValueError("owner_id must be non-empty")
        if not isinstance(self.review_cues, tuple) or any(
            not isinstance(cue, str) or not cue for cue in self.review_cues
        ):
            raise TypeError("review_cues must be a tuple of non-empty strings")
        if not isinstance(self.memory_queries, tuple) or any(
            not isinstance(query, MemoryQuery) for query in self.memory_queries
        ):
            raise TypeError("memory_queries must be a tuple of MemoryQuery records")
        if any(query.owner_id != self.owner_id for query in self.memory_queries):
            raise PermissionError("memory query belongs to a different Agent")


class MetacognitionPolicy(Protocol):
    """Replaceable turn-local L5 review strategy; receives snapshots only."""

    maximum_retrievals: int
    maximum_feedback_rounds: int
    results_per_query: int

    def review(
        self,
        context: DecisionContext,
        *,
        prior_queries: tuple[MemoryQuery, ...],
        remaining_query_budget: int,
    ) -> MetacognitiveFeedback: ...


def _text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    fields = getattr(value, "_fields", None)
    if fields is not None and hasattr(fields, "items"):
        return _text_values(fields)
    if isinstance(value, dict) or hasattr(value, "items"):
        result: list[str] = []
        for key, item in value.items():
            result.extend(_text_values(key))
            result.extend(_text_values(item))
        return result
    if isinstance(value, (tuple, list, set, frozenset)):
        return [text for item in value for text in _text_values(item)]
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, dict):
        return [
            text
            for name, item in attributes.items()
            if not name.startswith("_")
            for text in _text_values(item)
        ]
    return []


@dataclass(frozen=True)
class BoundedMetacognitionPolicy:
    """Small deterministic L5 baseline with explicit retrieval/round budgets.

    It asks for a second, differently scoped query only when the first search
    returned no memory and a distinct current cognitive cue exists. It does
    not infer missing facts or write to cognition Stores.
    """

    maximum_retrievals: int = 2
    maximum_feedback_rounds: int = 2
    results_per_query: int = 5

    def __post_init__(self) -> None:
        for name in (
            "maximum_retrievals",
            "maximum_feedback_rounds",
            "results_per_query",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.maximum_retrievals > MAX_MEMORY_RETRIEVALS_PER_TURN:
            raise ValueError("maximum_retrievals exceeds the per-turn safety bound")
        if self.maximum_feedback_rounds > MAX_METACOGNITIVE_FEEDBACK_ROUNDS:
            raise ValueError("maximum_feedback_rounds exceeds the per-turn safety bound")
        if self.results_per_query < 1 or self.results_per_query > MAX_MEMORY_RESULTS_PER_QUERY:
            raise ValueError("results_per_query is outside the supported bound")

    def review(
        self,
        context: DecisionContext,
        *,
        prior_queries: tuple[MemoryQuery, ...],
        remaining_query_budget: int,
    ) -> MetacognitiveFeedback:
        owner_id = context.cognition_state.agent_id
        if remaining_query_budget <= 0:
            return MetacognitiveFeedback(
                owner_id, review_cues=("Memory retrieval budget exhausted; retain uncertainty.",)
            )
        if context.long_term_memories:
            return MetacognitiveFeedback(
                owner_id, review_cues=("Relevant personal memory is available for review.",)
            )

        cues: list[str] = []
        for percept in context.percepts:
            cues.extend(_text_values(percept.content))
        working = context.working_memory
        if working is not None:
            cues.extend(_text_values(working.focus))
            cues.extend(_text_values(working.context))
        for goal in context.goals:
            if getattr(goal, "status", "active") == "active":
                cues.extend(_text_values(getattr(goal, "description", None)))
        for belief in context.beliefs:
            cues.extend(_text_values(getattr(belief, "content", None)))

        compact = tuple(dict.fromkeys(text.strip() for text in cues if text.strip()))
        if not compact:
            return MetacognitiveFeedback(
                owner_id, review_cues=("No usable retrieval cue; retain uncertainty.",)
            )

        candidate_texts = [" ".join(compact)]
        candidate_texts.extend(compact)
        seen = {
            (query.owner_id, " ".join(query.query.casefold().split()))
            for query in prior_queries
        }
        for text in candidate_texts:
            key = (owner_id, " ".join(text.casefold().split()))
            if key in seen:
                continue
            return MetacognitiveFeedback(
                owner_id,
                review_cues=("Current evidence is incomplete; review a scoped personal-memory match.",),
                memory_queries=(
                    MemoryQuery(
                        owner_id=owner_id,
                        query=text,
                        limit=max(1, self.results_per_query),
                    ),
                ),
            )
        return MetacognitiveFeedback(
            owner_id,
            review_cues=("No new distinct memory query remains; retain uncertainty.",),
        )
