"""Integration tests for the ``Match`` orchestrator (KAN-1275, ADR-0003):
drives a full game programmatically through ``Match``, in-process, against
the ``CounterEngine`` fake defined in ``tests/conftest.py``. No subprocess,
no CLI/MCP -- those connectors are separate, later tickets.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import pytest

from agent_game_framework.core import IllegalActionError, Match

if TYPE_CHECKING:
    from conftest import CounterEngine, CounterMatch

INC = "inc"


def test_turn_loop_alternates_players_to_a_terminal_state(
    make_match: Callable[..., CounterMatch],
) -> None:
    """Drives a full match to completion using only ``current_players()`` to
    decide who acts each turn -- proving the turn loop is driven correctly by
    the contract, not by an out-of-band assumption about seat order.
    """
    match = make_match(players=["A", "B"], target=3)

    is_terminal_count = 0
    turns = 0
    while not match.is_terminal():
        turns += 1
        assert turns <= 100, "turn loop did not terminate"
        acting = match.current_players()
        assert len(acting) == 1, "CounterEngine is strict turn order, never simultaneous"
        player = acting[0]
        assert match.legal_actions(player) == [INC]
        match.submit_action(player, INC)
        if match.is_terminal():
            is_terminal_count += 1

    assert match.is_terminal() is True
    assert is_terminal_count == 1, "is_terminal must flip to true exactly once"
    assert match.winners() == ["A"]
    # A reaches target=3 on its 3rd turn; B gets 2 turns in between.
    assert match.serialize()["scores"] == {"A": 3, "B": 2}


def test_turn_loop_rejects_out_of_turn_submission_mid_game(
    make_match: Callable[..., CounterMatch],
) -> None:
    match = make_match(players=["A", "B"], target=5)
    match.submit_action("A", INC)  # A's turn; now it's B's turn.
    before = match.serialize()

    with pytest.raises(IllegalActionError):
        match.submit_action("A", INC)  # still B's turn -- A may not act again.

    assert match.serialize() == before
    assert match.current_players() == ["B"]


def test_match_state_round_trips_mid_game_and_play_continues_identically(
    make_match: Callable[..., CounterMatch], counter_engine: CounterEngine
) -> None:
    """serialize()/deserialize() round-trip via Match, mid-game, including
    schema_version passthrough -- and a match resumed from the dump plays
    out identically to the original.
    """
    original = make_match(players=["A", "B"], target=3)
    original.submit_action("A", INC)
    original.submit_action("B", INC)
    dumped = original.serialize()
    assert "schema_version" in dumped

    resumed: CounterMatch = Match(counter_engine, players=["A", "B"])
    resumed.deserialize(dumped)
    assert resumed.serialize() == dumped

    # Play both matches to completion identically and compare end states.
    for match in (original, resumed):
        while not match.is_terminal():
            player = match.current_players()[0]
            match.submit_action(player, INC)

    assert original.serialize() == resumed.serialize()
    assert original.winners() == resumed.winners() == ["A"]
