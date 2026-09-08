"""Integration tests proving R1 ("any mix of human/AI seats, including zero
human seats") directly against ``Match``'s seat-map-driven turn loop
(KAN-1280, PLAN.md Shape S2, ADR-0005) -- in-process, no subprocess, no
CLI/argparse, no real stdin.

The same drive function (``_drive_via_play_turn``) is used, unmodified, for
both a mixed human-fixture-vs-bot match and an all-bot (zero human seats)
match: proving "how many humans" is purely a difference in which
``SeatController`` implementations populate the ``seats`` mapping handed to
``Match.__init__``, never a separate branch in ``Match`` (or, elsewhere, the
CLI) itself.

``_FixtureController`` stands in for a "human fixture" per the V1 test plan
-- a small, test-only ``SeatController`` returning pre-determined (not real
stdin) choices, in the spirit of ``tests/integration/test_cli_play.py``'s
``_ScriptedController`` but adaptive to whatever the opponent has already
played, so it stays legal regardless of the bot's random choices.
"""

from __future__ import annotations

import random
from typing import Any

from agent_game_framework.agents import RandomBotController
from agent_game_framework.core import Match, SeatDecision
from examples.tictactoe import TicTacToeEngine

TicTacToeMatch = Match[Any, int, Any]


class _FixtureController:
    """A deterministic test-only ``SeatController``: always plays its
    earliest still-legal cell from a fixed preference order. Stands in for
    a pre-scripted "human fixture" seat (not real stdin) that adapts to
    whatever the other seat has already played, so a match is guaranteed to
    reach a legal, deterministic conclusion regardless of the opponent's
    (possibly random) choices.
    """

    def __init__(self, preference: list[int]) -> None:
        self._preference = preference

    def decide(self, observation: Any, legal_actions: list[int]) -> SeatDecision[int]:
        for cell in self._preference:
            if cell in legal_actions:
                return SeatDecision(action=cell)
        raise AssertionError("fixture controller found no legal preferred action")


def _drive_via_play_turn(match: TicTacToeMatch) -> int:
    """Drive ``match`` to completion using ``Match.play_turn()`` directly
    (not ``run_to_completion``, so this test can count exactly how many
    times ``is_terminal()`` flips from false to true).

    This is the *one* function both R1 configurations below call, unmodified
    -- the whole point being that neither ``Match`` nor this test branches on
    "is there a human seat," only the ``seats`` mapping passed to
    ``Match.__init__`` differs between the two tests.
    """
    terminal_transitions = 0
    turns = 0
    while not match.is_terminal():
        turns += 1
        assert turns <= 9, "tic-tac-toe turn loop did not terminate"
        match.play_turn()
        if match.is_terminal():
            terminal_transitions += 1
    return terminal_transitions


def test_human_fixture_vs_bot_reaches_a_conclusion_via_the_shared_seat_map_driver() -> None:
    """1 human-fixture seat + 1 bot seat: a mixed-seat match."""
    engine = TicTacToeEngine()
    seats = {
        "X": _FixtureController(preference=list(range(9))),
        "O": RandomBotController(rng=random.Random(1234)),
    }
    match: TicTacToeMatch = Match(engine, players=["X", "O"], seats=seats)

    terminal_transitions = _drive_via_play_turn(match)

    assert match.is_terminal() is True
    assert terminal_transitions == 1, "is_terminal() must flip to true exactly once"
    winners = match.winners()
    assert winners == [] or winners == ["X"] or winners == ["O"]
    assert len(winners) <= 1


def test_all_bot_zero_human_seats_reaches_a_conclusion_via_the_same_shared_driver() -> None:
    """0 human seats: both seats are bots. Same ``_drive_via_play_turn``
    function as the mixed-seat test above -- proving all-AI is a
    configuration (which controllers fill ``seats``), not a separate code
    path anywhere in ``Match``.
    """
    engine = TicTacToeEngine()
    seats = {
        "X": RandomBotController(rng=random.Random(1)),
        "O": RandomBotController(rng=random.Random(2)),
    }
    match: TicTacToeMatch = Match(engine, players=["X", "O"], seats=seats)

    terminal_transitions = _drive_via_play_turn(match)

    assert match.is_terminal() is True
    assert terminal_transitions == 1, "is_terminal() must flip to true exactly once"
    winners = match.winners()
    assert winners == [] or winners == ["X"] or winners == ["O"]
    assert len(winners) <= 1
