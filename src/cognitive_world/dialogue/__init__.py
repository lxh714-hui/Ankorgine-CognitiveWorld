"""Bounded dialogue ingress and receiver-owned agency contracts."""

from .runtime import (
    DialogueInputHandler,
    DialogueInterpretation,
    DialogueInterpretationProvider,
    DialogueResponseCandidate,
    DialogueResponseCandidateProvider,
    DialogueExpressionProvider,
    DialogueReplyHandler,
    DialogueRequest,
    DialogueResult,
    PlayerDialogueService,
)
from .ollama import OllamaDialogueResponseCandidateProvider
from .npc import (
    NpcCommunicationDraft,
    NpcCommunicationCandidateProvider,
    NpcCommunicationCandidatePolicy,
    NpcDialogueDelivery,
    NpcDialogueService,
)

__all__ = [
    "DialogueInputHandler",
    "DialogueInterpretation",
    "DialogueInterpretationProvider",
    "DialogueResponseCandidate",
    "DialogueResponseCandidateProvider",
    "DialogueExpressionProvider",
    "DialogueReplyHandler",
    "DialogueRequest",
    "DialogueResult",
    "PlayerDialogueService",
    "OllamaDialogueResponseCandidateProvider",
    "NpcCommunicationDraft",
    "NpcCommunicationCandidateProvider",
    "NpcCommunicationCandidatePolicy",
    "NpcDialogueDelivery",
    "NpcDialogueService",
]
