"""Core game contract (ADR-0003, PLAN.md Shape S1/S2/S3): the ``GameEngine``
Protocol every game implements, the ``Match`` orchestrator that is the single
writer of a running game's state, and the ``SeatController`` Protocol
(ADR-0005) every seat-filling implementation satisfies.

This module ships no concrete game (see ``examples/tictactoe``, KAN-1277) and
no concrete seat controllers (``HumanCLIController``, ``RandomBotController``,
KAN-1278+) -- just the contracts and the orchestrator that sits directly on
top of them.
"""

from __future__ import annotations

from agent_game_framework.core.engine import GameEngine, IllegalActionError, PlayerId
from agent_game_framework.core.match import Match
from agent_game_framework.core.seat_controller import (
    AgentTimeoutError,
    SeatController,
    SeatDecision,
)

__all__ = [
    "AgentTimeoutError",
    "GameEngine",
    "IllegalActionError",
    "Match",
    "PlayerId",
    "SeatController",
    "SeatDecision",
]
