"""Unit tests for ``TicTacToeMinimaxAlgorithm`` (KAN-1289, ADR-0004,
SLICES.md V4 step 2): no external calls, no subprocess.

Covers: correct ``best_action``/``scores`` for known positions (including a
position with exactly one non-losing move), an empty-board smoke test, a
basic "recommendation is always legal" safety check, and a static AST check
that ``examples/tictactoe/algorithm`` never imports from
``examples.tictactoe`` (mirrors ``tests/unit/test_algorithm.py``'s
``agent_game_framework.core``/``agent_game_framework.agents`` import-hygiene
check for the analogous ADR-0004 guarantee).
"""

from __future__ import annotations

import ast
import inspect
import time
from typing import Any

from examples.tictactoe.algorithm import TicTacToeMinimaxAlgorithm
from examples.tictactoe.algorithm import minimax as minimax_module

_BOARD_SIZE = 9


def _legal_actions(board: list[Any]) -> list[int]:
    return [cell for cell in range(_BOARD_SIZE) if board[cell] is None]


def _observation(board: list[str | None], you: str) -> dict[str, Any]:
    return {"you": you, "board": board, "current_players": [you]}


def test_takes_immediate_win_over_a_move_that_only_draws() -> None:
    """X has two-in-a-row (cells 0, 1) with cell 2 open: playing it wins
    immediately. Playing 5 instead (blocking O's own row-1 threat) is also
    non-losing but only forces a draw, per hand-verified optimal play from
    that resulting position -- a strictly worse choice than the immediate
    win, so it must not be picked."""
    board: list[str | None] = ["X", "X", None, "O", "O", None, None, None, None]
    observation = _observation(board, you="X")
    legal_actions = _legal_actions(board)

    algorithm = TicTacToeMinimaxAlgorithm()
    recommendation = algorithm.recommend(observation, legal_actions)

    assert recommendation.best_action == 2
    assert recommendation.scores is not None
    assert recommendation.scores[2] == 1.0  # forced win, per the module's scores convention
    assert recommendation.scores[5] < 1.0  # a legal alternative, but strictly worse


def test_only_one_non_losing_move_is_found() -> None:
    """O threatens to complete row 1 (cells 3, 4 filled, cell 5 open) and
    has no other threat. Every legal move other than blocking cell 5 hands O
    the win on its next turn; only cell 5 avoids a forced loss for X. This
    is the "one non-losing move" case the ticket calls out explicitly."""
    board: list[str | None] = ["X", None, None, "O", "O", None, None, None, "X"]
    observation = _observation(board, you="X")
    legal_actions = _legal_actions(board)
    assert legal_actions == [1, 2, 5, 6, 7]

    algorithm = TicTacToeMinimaxAlgorithm()
    recommendation = algorithm.recommend(observation, legal_actions)

    assert recommendation.best_action == 5
    assert recommendation.scores is not None
    for action in legal_actions:
        if action == 5:
            assert recommendation.scores[action] > -1.0  # the one non-losing move
        else:
            assert recommendation.scores[action] == -1.0  # every other move is a forced loss


def test_empty_board_runs_quickly_and_returns_a_legal_action() -> None:
    """Full 3x3 minimax from an empty board is a well-known small search
    (on the order of 10^5 nodes). Well-established Tic-Tac-Toe theory says
    every corner and the center are equally optimal first moves and the
    game is a forced draw with perfect play either side, but this test
    deliberately does not pin down *which* cell comes back -- only that the
    search completes fast and returns a legal, defensible move -- per the
    ticket's explicit guidance to avoid baking in a possibly-misremembered
    theory fact as an exact-cell assertion."""
    board: list[str | None] = [None] * _BOARD_SIZE
    observation = _observation(board, you="X")
    legal_actions = _legal_actions(board)

    algorithm = TicTacToeMinimaxAlgorithm()
    start = time.monotonic()
    recommendation = algorithm.recommend(observation, legal_actions)
    elapsed = time.monotonic() - start

    assert recommendation.best_action in legal_actions
    assert elapsed < 5.0  # generously loose bound; a full search is near-instant in practice


def test_best_action_is_always_a_legal_action() -> None:
    """Basic sanity/safety check: nothing downstream (this module, or
    ``Match``) re-validates ``best_action`` automatically until
    ``Match.submit_action`` is eventually called -- this is a regression
    guard that ``recommend`` never hands back an out-of-range or occupied
    cell, across a handful of representative positions."""
    algorithm = TicTacToeMinimaxAlgorithm()

    boards: list[list[str | None]] = [
        [None] * _BOARD_SIZE,
        ["X", "X", None, "O", "O", None, None, None, None],
        ["X", None, None, "O", "O", None, None, None, "X"],
        ["X", "O", "X", "X", "O", "O", "O", "X", None],  # one empty cell left
    ]
    for board in boards:
        legal_actions = _legal_actions(board)
        assert legal_actions  # every board above still has at least one empty cell
        observation = _observation(board, you="X")
        recommendation = algorithm.recommend(observation, legal_actions)
        assert recommendation.best_action in legal_actions


def _imported_module_names(source: str) -> set[str]:
    """Every module name referenced by an ``import``/``from ... import`` in
    ``source``, via straightforward AST inspection -- mirrors
    ``tests/unit/test_algorithm.py``'s helper of the same name/shape."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def test_tictactoe_algorithm_package_has_zero_imports_from_tictactoe_engine() -> None:
    """Static, ticket-mandated check: ``examples/tictactoe/algorithm``'s own
    modules must never import from ``examples.tictactoe`` (its ``engine``
    module included) -- this is the literal, checkable meaning of "a sibling
    module ... never importing its internals". Forbidding all of
    ``examples.tictactoe``, not just ``examples.tictactoe.engine``, also
    catches an import of the package's own ``__init__`` (which re-exports
    ``TicTacToeEngine``) as a backdoor around a narrower check.
    """
    modules = [
        inspect.getmodule(TicTacToeMinimaxAlgorithm),
        minimax_module,
    ]
    for module in modules:
        assert module is not None
        source = inspect.getsource(module)
        imported = _imported_module_names(source)
        forbidden_prefix = "examples.tictactoe"
        offending = {
            name
            for name in imported
            if name == forbidden_prefix or name.startswith(forbidden_prefix + ".")
        }
        assert not offending, (
            f"{module.__name__} must not import from {forbidden_prefix} (KAN-1289, ADR-0004); "
            f"found: {offending}"
        )
