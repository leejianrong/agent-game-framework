"""Core game contract (ADR-0003, PLAN.md Shape S1/S2): the ``GameEngine``
Protocol every game implements, and the ``Match`` orchestrator that is the
single writer of a running game's state.

This module ships no concrete game (see ``examples/tictactoe``, KAN-1277) and
no seat controllers (KAN-1276) -- just the contract and the orchestrator that
sits directly on top of it.
"""

from __future__ import annotations

from agent_game_framework.core.engine import GameEngine, IllegalActionError, PlayerId
from agent_game_framework.core.match import Match

__all__ = [
    "GameEngine",
    "IllegalActionError",
    "Match",
    "PlayerId",
]
