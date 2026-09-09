"""Standalone game-algorithm contract (ADR-0004, SLICES.md V4 step 1) plus
the framework-provided composite ``SeatController``s built on top of it
(SLICES.md V4 steps 3-4): the ``GameAlgorithm`` Protocol,
``AlgorithmRecommendation``, ``AdvisedLLMSeatController``, and
``AutoplayNarratorSeatController``.

Per ADR-0004, an algorithm is a third pillar, independent of both
``GameEngine`` (ADR-0003) and ``SeatController`` (ADR-0005). The
``GameAlgorithm``/``AlgorithmRecommendation`` contract itself
(``game_algorithm.py``) has zero dependency on ``agent_game_framework.core``
or ``agent_game_framework.agents`` -- see ``game_algorithm.py``'s own
docstring and ``tests/unit/test_algorithm.py``'s static import check.
``AdvisedLLMSeatController`` (``advised_llm.py``) and
``AutoplayNarratorSeatController`` (``autoplay_narrator.py``) are different:
per ``docs/PLAN.md``'s package layout note, "``agent_game_framework.algorithm``
hosts the ``GameAlgorithm`` Protocol and both composite
``SeatController``s ... these are framework code, reused unchanged by every
game" -- both legitimately depend on ``agent_game_framework.core`` to compose
one (``SeatController``/``SeatDecision``), which is expected and fine;
ADR-0004's "zero dependency" constraint is specifically about the
standalone ``GameAlgorithm`` Protocol, not about composite controllers built
on top of it. This package ships no concrete algorithm either (see
``examples/tictactoe/algorithm``, KAN-1289) -- just the contract and its
generic composition helpers.
"""

from __future__ import annotations

from agent_game_framework.algorithm.advised_llm import AdvisedLLMSeatController
from agent_game_framework.algorithm.autoplay_narrator import AutoplayNarratorSeatController
from agent_game_framework.algorithm.game_algorithm import (
    AlgorithmRecommendation,
    GameAlgorithm,
)

__all__ = [
    "AdvisedLLMSeatController",
    "AlgorithmRecommendation",
    "AutoplayNarratorSeatController",
    "GameAlgorithm",
]
