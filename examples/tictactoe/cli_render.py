"""Tic-Tac-Toe's own CLI board renderer -- lives here, not in the shared
framework ``cli.py``, so the framework's connector stays game-agnostic
(ADR-0001, ADR-0006): the framework only knows *that* a registered game may
optionally supply a renderer (``cli.RENDERER_REGISTRY``), never *how* to draw
one specific game's board.

Empty cells render as their own 0-8 index rather than a placeholder like
``.`` -- the human-readable board doubles as the input legend on every
render (including the very first, empty one, printed before any move is
made), so the cell-number mapping never needs a separate one-off legend that
would go stale as soon as a mark is placed.
"""

from __future__ import annotations

from typing import Any


def render_board(board: list[str | None]) -> str:
    """Render a 9-cell row-major Tic-Tac-Toe ``board`` as a 3x3 grid, e.g.::

        X | O | 2
        ---------
        3 | X | 5
        ---------
        6 | 7 | O

    An empty cell shows its own index (its legal-move number); an occupied
    one shows the mark that occupies it.
    """

    def cell(index: int) -> str:
        mark = board[index]
        return mark if mark is not None else str(index)

    rows = [" | ".join(cell(row * 3 + col) for col in range(3)) for row in range(3)]
    separator = "-" * len(rows[0])
    return f"\n{separator}\n".join(rows)


def render_observation(observation: dict[str, Any]) -> str:
    """Adapter for ``cli.RENDERER_REGISTRY``: pulls ``"board"`` out of a
    ``TicTacToeEngine.observation_for``-shaped observation dict and renders
    it via ``render_board``."""
    return render_board(observation["board"])
