"""Resolve a player view only from the host-bound RuntimeContext session."""

from dataclasses import dataclass

from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.presentation.contracts import (
    _PRESENTATION_SEAL,
    _Receipt,
    PerspectiveContext,
)
from cognitive_world.runtime.context import PlayerMode, RuntimeContext


class PerspectiveAuthorizationError(PermissionError):
    """Raised when trusted session, mode, or Agent binding is unavailable."""


@dataclass(frozen=True)
class PerspectiveResolver:
    """Resolve roleplay/observer views; director access remains unavailable."""

    runtime_context: RuntimeContext

    def resolve(self) -> PerspectiveContext:
        session = self.runtime_context.player_session
        registry = self.runtime_context.agent_registry
        if session is None or registry is None:
            raise PerspectiveAuthorizationError(
                "trusted player session and AgentRegistry are required"
            )
        if session.mode is PlayerMode.ROLEPLAY:
            observer_id = session.controlled_agent_id
        elif session.mode is PlayerMode.OBSERVER:
            observer_id = session.observer_agent_id
        else:
            raise PerspectiveAuthorizationError(
                "director mode has no approved visibility policy"
            )
        if not observer_id:
            raise PerspectiveAuthorizationError("session has no trusted view Agent")
        agent = registry.get(observer_id)
        if not isinstance(agent, RuntimeAgent) or agent.agent_id != observer_id:
            raise PerspectiveAuthorizationError("view Agent is not registered")
        if session.mode is PlayerMode.ROLEPLAY and not agent.character_id:
            raise PerspectiveAuthorizationError(
                "roleplay session is not bound to a registered Character"
            )

        perspective = PerspectiveContext(
            recipient_id=session.player_id,
            observer_id=observer_id,
            session_id=session.session_id,
            mode=session.mode,
            character_id=agent.character_id,
            # This is a policy output, never copied from a session or caller.
            visible_scopes=frozenset({"environment", "dialogue"}),
        )
        object.__setattr__(
            perspective,
            "_receipt",
            _Receipt(
                _PRESENTATION_SEAL,
                perspective._snapshot(),
                (
                    session.session_id,
                    session.player_id,
                    session.mode,
                    session.controlled_agent_id,
                    session.observer_agent_id,
                    agent.agent_id,
                    agent.character_id,
                ),
            ),
        )
        return perspective
