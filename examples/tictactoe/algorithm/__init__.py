"""Tic-Tac-Toe's standalone reference ``GameAlgorithm`` (KAN-1289, SLICES.md
V4 step 2, ADR-0004): ``TicTacToeMinimaxAlgorithm``, a full minimax search.

Deliberately a sibling of ``examples.tictactoe`` (the ``TicTacToeEngine``
module), never importing anything from it -- see ``minimax.py``'s module
docstring for the full rationale. This is only ever *a* reference
implementation, not *the* implementation: per ADR-0004, anyone can publish
their own package implementing ``GameAlgorithm`` against Tic-Tac-Toe's public
observation/action types without touching this package or
``examples.tictactoe`` at all.
"""

from __future__ import annotations

from examples.tictactoe.algorithm.minimax import TicTacToeMinimaxAlgorithm

__all__ = ["TicTacToeMinimaxAlgorithm"]
