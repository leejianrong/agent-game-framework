"""Unit tests for ``RandomBotController`` (KAN-1278, ADR-0005): no external
calls, no subprocess.

Exercises the controller against both a Tic-Tac-Toe-shaped observation/action
(``int`` cell indices, as ``examples/tictactoe/engine.py`` uses) and a
generic ``str``-action case, since ``RandomBotController`` must work for any
``ActionT`` via the ``SeatController[ObservationT, ActionT]`` Protocol, not
just Tic-Tac-Toe.
"""

from __future__ import annotations

import random
from typing import Any

from agent_game_framework.agents import RandomBotController
from agent_game_framework.core import SeatController, SeatDecision

TRIALS = 500


def test_decide_only_ever_returns_a_legal_action_tictactoe_shaped() -> None:
    """Across many trials and varying ``legal_actions`` lists, every decision
    returned is a member of the ``legal_actions`` it was given."""
    bot = RandomBotController[dict[str, Any], int](rng=random.Random(1234))
    observation: dict[str, Any] = {"you": "X", "board": [None] * 9, "current_players": ["X"]}

    for shrink in range(9):
        legal_actions = list(range(shrink, 9))
        for _ in range(TRIALS):
            decision = bot.decide(observation, legal_actions)
            assert decision.action in legal_actions
            assert decision.banter is None


def test_decide_only_ever_returns_a_legal_action_generic_str_actions() -> None:
    bot = RandomBotController[dict[str, Any], str](rng=random.Random(99))
    legal_actions = ["rock", "paper", "scissors"]

    for _ in range(TRIALS):
        decision = bot.decide({}, legal_actions)
        assert decision.action in legal_actions
        assert decision.banter is None


def test_decide_with_a_single_legal_action_always_returns_it() -> None:
    bot = RandomBotController[dict[str, Any], int](rng=random.Random(7))
    for _ in range(50):
        decision = bot.decide({}, [4])
        assert decision.action == 4


def test_seeded_random_is_deterministic_across_instances() -> None:
    """Same seed -> same sequence of choices, useful for reproducible bot
    play in later CLI/e2e tests."""
    legal_actions = list(range(9))

    bot_a = RandomBotController[dict[str, Any], int](rng=random.Random(42))
    bot_b = RandomBotController[dict[str, Any], int](rng=random.Random(42))

    sequence_a = [bot_a.decide({}, legal_actions).action for _ in range(50)]
    sequence_b = [bot_b.decide({}, legal_actions).action for _ in range(50)]

    assert sequence_a == sequence_b


def test_different_seeds_can_produce_different_sequences() -> None:
    legal_actions = list(range(9))

    bot_a = RandomBotController[dict[str, Any], int](rng=random.Random(1))
    bot_b = RandomBotController[dict[str, Any], int](rng=random.Random(2))

    sequence_a = [bot_a.decide({}, legal_actions).action for _ in range(50)]
    sequence_b = [bot_b.decide({}, legal_actions).action for _ in range(50)]

    assert sequence_a != sequence_b


def test_random_bot_controller_satisfies_seat_controller_protocol() -> None:
    controller: SeatController[dict[str, Any], int] = RandomBotController(rng=random.Random(0))
    decision = controller.decide({}, [1, 2, 3])
    assert isinstance(decision, SeatDecision)
    assert decision.action in [1, 2, 3]
