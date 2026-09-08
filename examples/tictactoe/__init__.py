"""Tic-Tac-Toe: the throwaway reference ``GameEngine`` (KAN-1277, ADR-0007).

Exists purely to validate ``agent_game_framework.core``'s contract
(``GameEngine``, ``Match``) end-to-end against a real game with real
win/draw rules. It is not a product and is deliberately kept out of the
``agent-games/`` sibling-repo namespace reserved for real target games (see
ADR-0001) -- none of this module's code is expected to carry forward into
Catan/Poker/Wavelength.
"""

from __future__ import annotations

from examples.tictactoe.engine import TicTacToeEngine, TicTacToeState

__all__ = ["TicTacToeEngine", "TicTacToeState"]
