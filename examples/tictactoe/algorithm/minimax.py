"""``TicTacToeMinimaxAlgorithm``: a standalone ``GameAlgorithm`` for
Tic-Tac-Toe, built by exhaustive minimax search (KAN-1289, SLICES.md V4 step
2, ADR-0004).

**This module is a sibling of, and never imports from, ``examples.tictactoe``
or ``examples.tictactoe.engine``.** Per ADR-0004, a ``GameAlgorithm`` must be
authorable by a third party with no access to a game's own repo -- so
everything this module needs about Tic-Tac-Toe is re-derived here from the
*rules* of the game (a 3x3 grid, 8 ways to win) and from the shape of
``TicTacToeEngine.observation_for``/``legal_actions`` as a third party would
read them off the engine's public docstrings, never by importing
``engine.py``'s own ``_WINNING_LINES``, ``BOARD_SIZE``, or any other
internal. The winning-line triples below are this module's own
independently-written copy of the same 8 lines -- see
``tests/unit/test_tictactoe_minimax.py`` for the static AST check enforcing
zero imports from ``examples.tictactoe``.

**The "no opponent PlayerId" subtlety this module is built around:** a
``GameAlgorithm.recommend`` call only ever receives ``observation["you"]``
(the caller's own ``PlayerId``) and the board -- never the opponent's
``PlayerId`` string, and there is no reliable way to discover it (an empty or
lightly-populated board may not contain it at all). This module never needs
it: every board cell is classified into one of exactly three abstract states
-- ``_MINE`` (``== observation["you"]``), ``_OPP`` (occupied, but not mine),
or ``_EMPTY`` (``None``) -- and the minimax search only ever places the
abstract ``_MINE``/``_OPP`` markers into candidate cells while simulating
hypothetical future moves, never a real second ``PlayerId`` value pulled from
anywhere.

**Scores convention** (``AlgorithmRecommendation.scores``, one entry per
legal move): the minimax value of the position that results from playing
that move, assuming optimal play by both sides from then on, from
``observation["you"]``'s perspective --

- ``1.0``  -- a forced win for you
- ``0.0``  -- a forced draw
- ``-1.0`` -- a forced loss

**Tie-break rule** for ``best_action``: ADR-0004 only requires *a* correct
best move, not which one when several are equally good (e.g. all 4 corners
from an empty board are equally optimal). Ties are broken deterministically
by lowest cell index, so callers/tests can assert one exact value rather than
"one of several acceptable answers".

**Search strategy:** plain exhaustive minimax, no alpha-beta pruning, no
memoization/transposition table. Tic-Tac-Toe's entire game tree is small
enough (on the order of 10^5 nodes) that a full search completes well under
a second in pure Python -- correctness and readability matter far more here
than shaving milliseconds off an already-instant search (see
``tests/unit/test_tictactoe_minimax.py``'s empty-board timing assertion).
"""

from __future__ import annotations

from typing import Any

from agent_game_framework.algorithm import AlgorithmRecommendation, GameAlgorithm

BOARD_SIZE = 9
"""Number of cells on a 3x3 Tic-Tac-Toe board -- a rule of the game itself,
not something read off ``examples.tictactoe.engine``."""

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
"""This module's own copy of the 8 Tic-Tac-Toe winning lines (3 rows, 3
columns, 2 diagonals) as index triples into a row-major 0-8 board -- a
third-party author would derive this from the rules of the game, not from
``examples.tictactoe.engine``'s ``_WINNING_LINES``, which this module never
imports."""

# Abstract cell markers used only inside this module's search -- never a
# real PlayerId. See the module docstring's "no opponent PlayerId" subtlety.
_EMPTY = 0
_MINE = 1
_OPP = -1

_Cell = int
_InternalBoard = list[_Cell]

# AlgorithmRecommendation.scores convention (see module docstring).
_WIN = 1.0
_DRAW = 0.0
_LOSS = -1.0

_LABELS = {_WIN: "a forced win", _DRAW: "a forced draw", _LOSS: "a forced loss"}


def _classify(cell: Any, me: Any) -> _Cell:
    """Map one raw board cell (a ``PlayerId`` or ``None``) to this module's
    abstract ``_MINE``/``_OPP``/``_EMPTY`` marker, per the module docstring's
    "no opponent PlayerId" subtlety -- ``me`` is the only ``PlayerId`` this
    module ever compares against."""
    if cell is None:
        return _EMPTY
    if cell == me:
        return _MINE
    return _OPP


def _winner(board: _InternalBoard) -> _Cell | None:
    """``_MINE``/``_OPP`` if that side has completed a winning line, else
    ``None``."""
    for a, b, c in _WINNING_LINES:
        mark = board[a]
        if mark != _EMPTY and mark == board[b] == board[c]:
            return mark
    return None


def _minimax(board: _InternalBoard, maximizing: bool) -> float:
    """Exhaustive minimax value of ``board``, from ``_MINE``'s perspective
    (``_WIN``/``_DRAW``/``_LOSS``), assuming optimal play by both sides from
    here on. ``maximizing=True`` means it is ``_MINE``'s turn to move (this
    call picks the max child value); ``maximizing=False`` means it is
    ``_OPP``'s turn (this call picks the min child value). Mutates ``board``
    in place while recursing and always undoes the mutation before
    returning, rather than copying the board on every recursive call."""
    winner = _winner(board)
    if winner == _MINE:
        return _WIN
    if winner == _OPP:
        return _LOSS

    empties = [i for i, cell in enumerate(board) if cell == _EMPTY]
    if not empties:
        return _DRAW

    if maximizing:
        best = _LOSS
        for i in empties:
            board[i] = _MINE
            value = _minimax(board, maximizing=False)
            board[i] = _EMPTY
            if value > best:
                best = value
        return best
    else:
        best = _WIN
        for i in empties:
            board[i] = _OPP
            value = _minimax(board, maximizing=True)
            board[i] = _EMPTY
            if value < best:
                best = value
        return best


class TicTacToeMinimaxAlgorithm:
    """A ``GameAlgorithm[dict[str, Any], int]`` for Tic-Tac-Toe, computed by
    full minimax search over the remaining empty cells. See the module
    docstring for the scores convention, the tie-break rule for
    ``best_action``, and why this module never needs the opponent's
    ``PlayerId``.

    Built only against Tic-Tac-Toe's public observation/action shape
    (``observation_for``/``legal_actions`` as documented on
    ``TicTacToeEngine``) -- see the module docstring for why this class
    never imports ``examples.tictactoe.engine`` to get at that shape.
    """

    def recommend(
        self, observation: dict[str, Any], legal_actions: list[int]
    ) -> AlgorithmRecommendation[int]:
        me = observation["you"]
        board: _InternalBoard = [_classify(cell, me) for cell in observation["board"]]

        scores: dict[int, float] = {}
        for action in legal_actions:
            board[action] = _MINE
            scores[action] = _minimax(board, maximizing=False)
            board[action] = _EMPTY

        # Highest score wins; ties broken by lowest cell index (see module
        # docstring's "Tie-break rule").
        best_action = min(legal_actions, key=lambda a: (-scores[a], a))
        best_score = scores[best_action]

        rationale = (
            f"cell {best_action} leads to {_LABELS[best_score]} with optimal play "
            f"(score {best_score:+.1f})"
        )

        return AlgorithmRecommendation(
            best_action=best_action,
            rationale=rationale,
            scores=scores,
        )


# Structural self-check: confirms TicTacToeMinimaxAlgorithm satisfies
# GameAlgorithm[dict[str, Any], int] at import time (mypy strict mode would
# also catch a mismatch here, but this makes the intent explicit in-module).
_: GameAlgorithm[dict[str, Any], int] = TicTacToeMinimaxAlgorithm()
