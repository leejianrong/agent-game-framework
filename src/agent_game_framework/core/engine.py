"""``GameEngine`` Protocol and its supporting types (ADR-0003, PLAN.md Shape S1).

Every game (Tic-Tac-Toe now; Catan, Poker, Wavelength later) implements this
one typed Protocol so it can plug into the ``Match`` orchestrator and, later,
the CLI/MCP connectors without any of those layers knowing game-specific
rules. It is intentionally more general than any single game strictly needs:
``current_players`` returns a *list* because more than one entry signals a
simultaneous-move phase (e.g. a Wavelength guess round), not an error --
never narrow this to a single ``current_player: PlayerId | None`` in game or
connector code.
"""

from __future__ import annotations

from typing import Any, Protocol

PlayerId = str
"""A stable identifier for a seat in a game (e.g. ``"X"``, ``"O"``, a player
name).

A plain ``str`` alias rather than a distinct newtype: games, ``Match``, and
(later) connectors pass these around as ordinary strings -- CLI seat flags,
dict keys, JSON state dumps -- and a newtype would add call-site ceremony
without preventing any error that ``legal_actions``/``apply_action`` would
not already reject.
"""


class IllegalActionError(Exception):
    """Raised when an action is not legal for a player against the current state.

    Raised by ``GameEngine.apply_action`` on a rule violation, and by
    ``Match.submit_action`` when the acting player is not currently in
    ``current_players``. In both cases, per ADR-0003, the caller's state
    reference is left untouched -- no partial or invalid transition is ever
    applied.
    """


class GameEngine[StateT, ActionT, ObservationT](Protocol):
    """The one contract every game implements (ADR-0003).

    ``StateT``, ``ActionT``, and ``ObservationT`` are per-game typed data
    (e.g. dataclasses); the only requirement the framework places on
    ``StateT`` is that it round-trips through ``serialize``/``deserialize``
    as a JSON-safe ``dict``.

    A ``GameEngine`` implementation never mutates ``state`` in place -- every
    method here treats ``state`` as immutable and returns a new value where a
    transition is needed (``apply_action``). ``Match`` is the only code
    allowed to call ``apply_action``: it is the single writer of a running
    game's state (see ``agent_game_framework.core.match.Match``).
    """

    def initial_state(self, players: list[PlayerId], config: dict[str, Any]) -> StateT:
        """Build the starting state for a new match with these players."""
        ...

    def current_players(self, state: StateT) -> list[PlayerId]:
        """Whose turn(s) it is right now.

        More than one entry means a simultaneous-move phase, not an error.
        An empty list is valid too, and should coincide with
        ``is_terminal(state)`` being true.
        """
        ...

    def legal_actions(self, state: StateT, player: PlayerId) -> list[ActionT]:
        """All actions ``player`` may currently take.

        Returns an empty list if ``player`` is not in ``current_players``.
        """
        ...

    def apply_action(self, state: StateT, player: PlayerId, action: ActionT) -> StateT:
        """Return the state after ``player`` takes ``action``.

        Raises ``IllegalActionError`` if ``action`` is not legal for
        ``player`` against ``state``. Must not mutate ``state`` in place --
        on error, the caller's existing reference stays exactly as it was.
        """
        ...

    def is_terminal(self, state: StateT) -> bool:
        """Whether the game has ended."""
        ...

    def winners(self, state: StateT) -> list[PlayerId]:
        """Players who won. Empty for a draw, or for a non-terminal state."""
        ...

    def observation_for(self, state: StateT, player: PlayerId) -> ObservationT:
        """The per-player view of ``state``.

        Hidden information (hole cards, a hidden Wavelength target, etc.) is
        enforced here, once, by the game's own code -- never reimplemented
        per connector.
        """
        ...

    def serialize(self, state: StateT) -> dict[str, Any]:
        """A JSON-safe ``dict`` for ``state``, always including ``schema_version``."""
        ...

    def deserialize(self, data: dict[str, Any]) -> StateT:
        """Inverse of ``serialize``. ``data`` always carries ``schema_version``."""
        ...
