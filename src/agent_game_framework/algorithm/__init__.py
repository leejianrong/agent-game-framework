"""Standalone game-algorithm contract (ADR-0004, SLICES.md V4 step 1): the
``GameAlgorithm`` Protocol and its ``AlgorithmRecommendation`` return type.

Per ADR-0004, an algorithm is a third pillar, independent of both
``GameEngine`` (ADR-0003) and ``SeatController`` (ADR-0005) -- this package
has zero dependency on ``agent_game_framework.core`` or
``agent_game_framework.agents``, and none of that composition wiring
(``AdvisedLLMSeatController``, ``AutoplayNarratorSeatController``, later V4
steps) lives here. This package ships no concrete algorithm either (see
``examples/tictactoe/algorithm``, future KAN-1289) -- just the contract.
"""

from __future__ import annotations

from agent_game_framework.algorithm.game_algorithm import (
    AlgorithmRecommendation,
    GameAlgorithm,
)

__all__ = [
    "AlgorithmRecommendation",
    "GameAlgorithm",
]
