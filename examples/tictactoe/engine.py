"""``TicTacToeEngine``: the reference ``GameEngine`` implementation (ADR-0003,
ADR-0007, KAN-1277).

A 3x3 board, two players, strict turn order. Cells are indexed 0-8,
row-major (``0 1 2 / 3 4 5 / 6 7 8``); an action is the int index of the
cell a player wants to mark. The ``players`` list passed to
``initial_state`` sets turn order -- ``players[0]`` moves first (the
conventional "X" seat), ``players[1]`` moves second (the conventional "O"
seat) -- but their actual ``PlayerId`` values are whatever the caller gives,
never hardcoded to the literal strings ``"X"``/``"O"``.

This engine never mutates a ``TicTacToeState`` it is handed: every method
treats ``state`` as immutable and ``apply_action`` returns a new instance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_game_framework.core.engine import IllegalActionError, PlayerId

TICTACTOE_SCHEMA_VERSION = 1

BOARD_SIZE = 9
"""Number of cells on the 3x3 board."""

Action = int
"""An action is the 0-8 index of the cell to mark."""

_WINNING_LINES: tuple[tuple[int, int, int], ...] = (
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),  # rows
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),  # columns
    (0, 4, 8),
    (2, 4, 6),  # diagonals
)
"""All 8 ways to win: 3 rows, 3 columns, 2 diagonals, as index triples into
the row-major 0-8 board."""


@dataclass
class TicTacToeState:
    """State for a Tic-Tac-Toe match.

    ``players`` is turn order: ``players[0]`` is the conventional "X" seat
    (moves first), ``players[1]`` is the conventional "O" seat. ``board`` is
    9 cells, row-major, each either the ``PlayerId`` who marked it or
    ``None`` if empty. ``turn_index`` (0 or 1) indexes into ``players`` for
    whose turn it is; meaningless once the game is terminal.
    """

    players: list[PlayerId]
    board: list[PlayerId | None] = field(default_factory=lambda: [None] * BOARD_SIZE)
    turn_index: int = 0


class TicTacToeEngine:
    """The reference ``GameEngine[TicTacToeState, Action, dict[str, Any]]``
    implementation (ADR-0003, ADR-0007). See the module docstring for the
    board/action encoding.
    """

    def initial_state(self, players: list[PlayerId], config: dict[str, Any]) -> TicTacToeState:
        if len(players) != 2:
            raise ValueError(f"tic-tac-toe requires exactly 2 players, got {players!r}")
        return TicTacToeState(players=list(players), board=[None] * BOARD_SIZE, turn_index=0)

    def current_players(self, state: TicTacToeState) -> list[PlayerId]:
        if self.is_terminal(state):
            return []
        return [state.players[state.turn_index]]

    def legal_actions(self, state: TicTacToeState, player: PlayerId) -> list[Action]:
        if player not in self.current_players(state):
            return []
        return [cell for cell in range(BOARD_SIZE) if state.board[cell] is None]

    def apply_action(
        self, state: TicTacToeState, player: PlayerId, action: Action
    ) -> TicTacToeState:
        if player not in self.current_players(state):
            raise IllegalActionError(f"{player!r} may not act now; it is not their turn")
        if not (0 <= action < BOARD_SIZE):
            raise IllegalActionError(f"cell {action!r} is out of range 0-{BOARD_SIZE - 1}")
        if state.board[action] is not None:
            raise IllegalActionError(f"cell {action!r} is already occupied")

        new_board = list(state.board)
        new_board[action] = player
        return TicTacToeState(
            players=list(state.players),
            board=new_board,
            turn_index=(state.turn_index + 1) % len(state.players),
        )

    def is_terminal(self, state: TicTacToeState) -> bool:
        return self._winner(state) is not None or all(cell is not None for cell in state.board)

    def winners(self, state: TicTacToeState) -> list[PlayerId]:
        winner = self._winner(state)
        return [winner] if winner is not None else []

    def observation_for(self, state: TicTacToeState, player: PlayerId) -> dict[str, Any]:
        """Tic-Tac-Toe has no hidden information: every player sees the same
        board, just tagged with whose observation it is."""
        return {
            "you": player,
            "board": list(state.board),
            "current_players": self.current_players(state),
        }

    def serialize(self, state: TicTacToeState) -> dict[str, Any]:
        return {
            "schema_version": TICTACTOE_SCHEMA_VERSION,
            "players": list(state.players),
            "board": list(state.board),
            "turn_index": state.turn_index,
        }

    def deserialize(self, data: dict[str, Any]) -> TicTacToeState:
        if data.get("schema_version") != TICTACTOE_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {data.get('schema_version')!r}")
        return TicTacToeState(
            players=list(data["players"]),
            board=list(data["board"]),
            turn_index=data["turn_index"],
        )

    def _winner(self, state: TicTacToeState) -> PlayerId | None:
        for a, b, c in _WINNING_LINES:
            mark = state.board[a]
            if mark is not None and mark == state.board[b] == state.board[c]:
                return mark
        return None
