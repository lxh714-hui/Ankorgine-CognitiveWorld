"""Independent player-visible contracts, authorization, and output boundary."""

from cognitive_world.presentation.composer import MinimalComposer
from cognitive_world.presentation.contracts import (
    NoResultNarrativeMessage,
    PlayerActionFeedbackMessage,
    PerspectiveContext,
    PlayerClarificationMessage,
    PlayerVisibleMessage,
    ValidatedMessageBatch,
    VisibleInput,
)
from cognitive_world.presentation.gateway import (
    ChatOutputGateway,
    InMemoryChatOutputGateway,
)
from cognitive_world.presentation.perspective import (
    PerspectiveAuthorizationError,
    PerspectiveResolver,
)
from cognitive_world.presentation.pipeline import PresentationPipeline
from cognitive_world.presentation.validator import PresentationValidator
from cognitive_world.presentation.visibility import VisibilityFilter

__all__ = [
    "ChatOutputGateway",
    "InMemoryChatOutputGateway",
    "MinimalComposer",
    "NoResultNarrativeMessage",
    "PlayerActionFeedbackMessage",
    "PerspectiveAuthorizationError",
    "PerspectiveContext",
    "PerspectiveResolver",
    "PlayerClarificationMessage",
    "PlayerVisibleMessage",
    "PresentationPipeline",
    "PresentationValidator",
    "ValidatedMessageBatch",
    "VisibilityFilter",
    "VisibleInput",
]
