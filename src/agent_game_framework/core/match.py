"""``Match`` orchestrator: the single writer of a running game's state
(ADR-0003, PLAN.md Shape S2).

``Match`` owns the one mutable ``StateT`` for a game and is the only thing
allowed to call ``GameEngine.apply_action``. The CLI and MCP connectors
(later tickets) drive a game through one ``Match`` instance each, never by
mutating engine state directly -- that's what makes ``Match`` the single
writer, with no two-actors-race-to-mutate-state scenario to resolve.
"""

from __future__ import annotations

from typing import Any

from agent_game_framework.core.engine import GameEngine, IllegalActionError, PlayerId


class Match[StateT, ActionT, ObservationT]:
    """Drives one game's turn loop on top of a ``GameEngine`` implementation.

    Construct with the engine implementation plus the players and config for
    a new match; ``initial_state`` is called immediately. The turn loop is
    driven by repeatedly calling ``current_players()`` and then
    ``submit_action()`` for whichever player(s) it names.
    """

    def __init__(
        self,
        engine: GameEngine[StateT, ActionT, ObservationT],
        players: list[PlayerId],
        config: dict[str, Any] | None = None,
    ) -> None:
        self._engine = engine
        self._state = engine.initial_state(players, config or {})

    @property
    def state(self) -> StateT:
        """The current engine state.

        Treat as read-only from outside ``Match``: by convention, nothing
        but ``Match.submit_action``/``Match.deserialize`` changes it.
        """
        return self._state

    def current_players(self) -> list[PlayerId]:
        """Whose turn(s) it is right now (see ``GameEngine.current_players``)."""
        return self._engine.current_players(self._state)

    def legal_actions(self, player: PlayerId) -> list[ActionT]:
        """Actions ``player`` may currently take."""
        return self._engine.legal_actions(self._state, player)

    def submit_action(self, player: PlayerId, action: ActionT) -> StateT:
        """Apply ``action`` on behalf of ``player``, and return the new state.

        Raises ``IllegalActionError`` -- and leaves ``Match``'s internal
        state completely unchanged -- if either:

        - ``player`` is not currently in ``current_players()`` (it is not
          their turn, or not a simultaneous-move phase they're part of), or
        - the engine itself rejects the action via ``apply_action``.
        """
        if player not in self._engine.current_players(self._state):
            raise IllegalActionError(
                f"{player!r} is not in current_players(); it is not their turn to act"
            )
        # Only rebind self._state after a successful apply_action call, so a
        # raised IllegalActionError never leaves Match holding a partial or
        # invalid transition (ADR-0003).
        new_state = self._engine.apply_action(self._state, player, action)
        self._state = new_state
        return self._state

    def is_terminal(self) -> bool:
        """Whether the game has ended (see ``GameEngine.is_terminal``)."""
        return self._engine.is_terminal(self._state)

    def winners(self) -> list[PlayerId]:
        """Players who won (see ``GameEngine.winners``)."""
        return self._engine.winners(self._state)

    def observation_for(self, player: PlayerId) -> ObservationT:
        """The per-player view of the current state (see ``GameEngine.observation_for``)."""
        return self._engine.observation_for(self._state, player)

    def serialize(self) -> dict[str, Any]:
        """A JSON-safe dict for the current state, via the engine's ``serialize``."""
        return self._engine.serialize(self._state)

    def deserialize(self, data: dict[str, Any]) -> None:
        """Replace the current state from ``data``, via the engine's ``deserialize``.

        ``data`` always carries a ``schema_version`` key; interpreting it is
        entirely the engine's responsibility, not ``Match``'s.
        """
        self._state = self._engine.deserialize(data)
